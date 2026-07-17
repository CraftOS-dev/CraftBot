# -*- coding: utf-8 -*-
"""Living UI extension-hook registrations — the domain plugs itself in.

The core agent loop knows only generic hook points
(:mod:`agent_core.core.registry.extensions`); everything Living-UI-specific
the loop used to inline lives HERE and registers at import. Remove
``app/living_ui`` and none of these register — the agent runs without the
domain, byte-identically elsewhere.

Registered points:
- ``boot_restore``        — the ghost guard: cancel stale creation tasks
                            before restored triggers are scheduled.
- ``user_message_routed`` — a user reply to a creation task is recorded as
                            a debugging lead (and un-parks a stuck build).
- ``task_end_gate``       — a creation task may not complete before its
                            project passes validation (incl. the walk).
- ``action_start/end``    — construction-event observation (Live
                            Construction View + build-state recording).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

from agent_core.core.registry.extensions import register_hook

# Development-workflow ids a living-ui owner task may carry (current name
# + the pre-rename legacy id persisted tasks still hold).
_WORKFLOW_IDS = ("living_ui_development", "living_ui_creation")


# ─────────────────────────── boot restore: ghost guard ──────────────────────


async def _ghost_guard(agent: Any) -> None:
    """Cancel stale Living UI creation ghosts instead of resuming them.

    Killed runs leave creation tasks status=running forever; boot restore
    resurrects them, they re-scaffold zombie projects, and their
    continuation triggers saturate the serial consumer (observed: four
    ghosts, four duplicate projects, and a starved real task). Rule: a
    restored task resumes iff the project registry names it as some
    project's OWNER (task_id match, any project status); everything else
    — projectless ghosts and superseded ex-owners — is cancelled. Project
    records come from the manager singleton when constructed, else the
    registry file on disk (the guard runs ~16ms before the adapter
    constructs the manager)."""
    task_manager = getattr(agent, "task_manager", None)
    if task_manager is None:
        return

    projects = []
    try:
        from app.living_ui._state import get_living_ui_manager

        manager = get_living_ui_manager()
        if manager is not None:
            projects = list(manager.projects.values())
        else:
            import json
            from types import SimpleNamespace

            from app.config import AGENT_WORKSPACE_ROOT

            registry = Path(AGENT_WORKSPACE_ROOT) / "living_ui_projects.json"
            if registry.exists():
                for rec in (
                    json.loads(registry.read_text(encoding="utf-8")).get("projects", [])
                    or []
                ):
                    projects.append(
                        SimpleNamespace(
                            id=rec.get("id"),
                            status=rec.get("status"),
                            task_id=rec.get("taskId"),
                            created_at=float(rec.get("createdAt", 0)) / 1000.0,
                        )
                    )
    except Exception as e:
        logger.warning(f"[RESTORE] Living UI project lookup failed: {e}")
        return  # can't judge — resume as before

    restored_creations = [
        task
        for tid in list(getattr(agent, "_restored_task_ids", []) or [])
        if (task := task_manager.tasks.get(tid))
        and task.status == "running"
        and getattr(task, "workflow_id", None) in _WORKFLOW_IDS
    ]
    if not restored_creations:
        return

    # Keeper rule: OWNERSHIP, not project status. The registry records
    # exactly one owner task per project (the ensure_project_owner
    # supersede rule), so a restored task the registry names as owner is
    # legitimate whatever state its project is in — "error" is a normal
    # mid-fix state (every failed validate flips to it), and the old
    # status=="creating" test killed owners parked at the budget gate
    # waiting for the user's reply (sessions 20260717115332/20260717121411:
    # restart + reply → reply had no task to route to → duplicate task).
    # Cancelled: tasks owning no project (true ghosts) and tasks whose
    # project now names a different owner (superseded).
    owners = {
        getattr(p, "task_id", None): p for p in projects if getattr(p, "task_id", None)
    }
    for task in restored_creations:
        if task.id in owners:
            continue  # the project's recorded owner resumes normally
        logger.info(
            f"[RESTORE] Cancelling stale Living UI creation task {task.id} "
            f"('{task.name}') — superseded or projectless ghost"
        )
        # Project-status mutation deliberately does NOT happen here: disk
        # records would be overwritten by the manager's own registry save.
        # The manager reconciles orphaned creating-projects at bind time
        # (reconcile_interrupted_builds).
        try:
            await task_manager._end_task(
                task,
                "cancelled",
                "Stale Living UI creation task from a previous run — "
                "not resumed after restart.",
            )
        except Exception as e:
            logger.warning(f"[RESTORE] Failed to cancel ghost task {task.id}: {e}")


# ───────────────────── user reply: record as a lead ─────────────────────────


def _record_lead_on_reply(agent: Any, session_id: str, user_message: str) -> None:
    """A user reply to a running creation task is EVIDENCE, not a command.
    Record the message as a debugging LEAD for the next build round (the
    agent reproduces/verifies it rather than trusting it), and if the agent
    had reported itself stuck, resume autonomous debugging WITH that lead.
    No-op for every other task/state."""
    task_manager = getattr(agent, "task_manager", None)
    if not session_id or task_manager is None:
        return
    task = task_manager.tasks.get(session_id)
    if task is None or getattr(task, "workflow_id", None) not in _WORKFLOW_IDS:
        return
    from app.living_ui._state import get_living_ui_manager
    from app.workflows.living_ui.steps import record_user_lead

    manager = get_living_ui_manager()
    project = next(
        (
            p
            for p in (manager.projects.values() if manager else [])
            if getattr(p, "task_id", None) == session_id
        ),
        None,
    )
    if project is not None:
        record_user_lead(Path(project.path), user_message or "")


# ───────────────────────── task_end completion gate ─────────────────────────


def _task_end_gate(session_id: str) -> Optional[str]:
    """Refuse task_end(complete) for a creation task whose project has not
    passed validation (which includes the browser walk). Returning None =
    no objection."""
    if not session_id:
        return None
    import app.internal_action_interface as _iai

    task_manager = _iai.InternalActionInterface.task_manager
    task = task_manager.tasks.get(session_id) if task_manager else None
    if task is None or getattr(task, "workflow_id", None) not in _WORKFLOW_IDS:
        return None
    from app.living_ui import get_living_ui_manager

    manager = get_living_ui_manager()
    if manager is None:
        return None
    project = next(
        (
            p
            for p in manager.projects.values()
            if getattr(p, "task_id", None) == session_id
        ),
        None,
    )
    if project is not None and not manager.is_validated(project.id):
        return (
            "NOT DONE — task_end refused. This task owns the Living UI "
            f"project '{project.name}' ({project.id}) and its validation "
            "has NOT passed (the pipeline includes a browser walk of every "
            "feature). Finish the work: fix what validation reported, "
            "living_ui_validate until it PASSES, living_ui_notify_ready, "
            "and only then end the task. If the build is genuinely "
            "impossible, end with status='abort' and an honest reason."
        )
    return None


# ─────────────────────────── registration (import-time) ─────────────────────


def register() -> None:
    register_hook("boot_restore", _ghost_guard)
    register_hook("user_message_routed", _record_lead_on_reply)
    register_hook("task_end_gate", _task_end_gate)
    # Conversation-mode entry: living_ui_develop is THE direct action for
    # Living UI build/update requests (bypasses task_start + skill guess).
    register_hook("conversation_actions", lambda: ["living_ui_develop"])
    # Construction-event observation: same (start, end) pair ActionManager
    # used to receive directly.
    try:
        from app.living_ui.construction_events import make_action_hooks

        on_start, on_end = make_action_hooks()
        register_hook("action_start", on_start)
        register_hook("action_end", on_end)
    except Exception as e:
        logger.warning(f"[LIVING_UI] construction hook registration failed: {e}")


register()
