# -*- coding: utf-8 -*-
"""Living UI build data + the stable module API around its step program.

The program itself is :class:`~app.workflows.living_ui.workflow.LivingUIWorkflow`
(one class: prompts + the work→verify engine, see
:mod:`app.workflows.workflow`). This module owns what is NOT
per-turn dispatch:

- :class:`BuildState` — the durable per-project state
  (``logs/build_state.json``), written only by code hooks, never the LLM;
- the fix ledger (``reference/briefs/.fixlog/<key>.md``) — append-only
  attempt history injected into every retry so no failed approach is
  re-tried blind;
- code-managed task todos (:func:`sync_todos`);
- the stable entry points the platform calls (recorders + compute_step),
  kept as module functions so manager.py / construction_events.py /
  registrations.py never need to resolve the workflow themselves.

Everything here is fail-open: a recording failure must never break a build.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

from app.workflows.workflow import WorkState

# Budgets (single source — the workflow class reads these; tests may
# monkeypatch the workflow instance, not these aliases).
FIX_ROUND_BUDGET = 8  # build rounds before a genuine last-resort ask
WALK_ATTEMPT_BUDGET = 3  # verdict-less walks before the worker self-verifies
FIXLOG_INJECT_CAP = 2000  # chars of fixlog inlined into a retry query

_FIXLOG_REL = Path("reference") / "briefs" / ".fixlog"


# ═════════════════════════════ build state ══════════════════════════════════


class BuildState(WorkState):
    """Living UI's :class:`WorkState`: same fields, generic names; kept at
    the project's historical ``logs/build_state.json`` and able to load
    files written under the pre-generic field names (mid-flight projects
    keep their state)."""

    STATE_REL: ClassVar[Path] = Path("logs") / "build_state.json"
    LEGACY_KEYS: ClassVar[Dict[str, str]] = {
        "fix_rounds": "rounds",
        "launched": "staged",
        "validated": "verified",
        "walk_failures": "check_failures",
        "walk_attempts": "check_attempts",
        "last_validate": "last_result",
    }


# ═════════════════════════════ fix ledger ═══════════════════════════════════


def fixlog_path(project_path: Path, key: str) -> Path:
    return Path(project_path) / _FIXLOG_REL / f"{key}.md"


def fixlog_append(
    project_path: Path,
    key: str,
    agent_type: str,
    errors_given: str,
    agent_reported: str,
) -> None:
    """Record one attempt. Never raises."""
    try:
        path = fixlog_path(project_path, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        n = 1
        if path.exists():
            n = path.read_text(encoding="utf-8").count("## Attempt ") + 1
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        entry = (
            f"\n## Attempt {n} — {stamp} — agent={agent_type}\n"
            f"### Errors given (verbatim)\n{errors_given.strip() or '(none)'}\n"
            f"### Agent reported\n{agent_reported.strip() or '(no manifest)'}\n"
            f"### Outcome\npending next validate\n"
        )
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.debug(f"[BUILD_DIRECTOR] fixlog append skipped: {e}")


def fixlog_backfill_outcome(project_path: Path, key: str, outcome: str) -> None:
    """Replace the LAST 'pending next validate' with the observed outcome —
    the oscillation killer: attempt N+1 sees what happened after attempt N."""
    try:
        path = fixlog_path(project_path, key)
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")
        marker = "### Outcome\npending next validate\n"
        idx = text.rfind(marker)
        if idx == -1:
            return
        replacement = f"### Outcome\n{outcome.strip()}\n"
        path.write_text(
            text[:idx] + replacement + text[idx + len(marker) :], encoding="utf-8"
        )
    except Exception as e:
        logger.debug(f"[BUILD_DIRECTOR] fixlog backfill skipped: {e}")


def fixlog_excerpt(project_path: Path, key: str, cap: int = FIXLOG_INJECT_CAP) -> str:
    try:
        path = fixlog_path(project_path, key)
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8").strip()
        if len(text) <= cap:
            return text
        # Trim at an attempt boundary — a raw character cut starts the
        # mandatory-reading block mid-sentence ("s given (verbatim)").
        tail = text[-cap:]
        boundary = tail.find("\n## Attempt ")
        if boundary != -1:
            tail = tail[boundary:]
        return "…(older attempts trimmed)\n" + tail.strip()
    except Exception:
        return ""


def fixlog_block(project_path: Path, key: str) -> str:
    """Retry-query block: the attempt history as MANDATORY reading."""
    excerpt = fixlog_excerpt(project_path, key)
    if not excerpt:
        return ""
    return (
        "\n\nPREVIOUS FAILED ATTEMPTS — MANDATORY READING:\n"
        f"{excerpt}\n"
        f"Full history: read_file {fixlog_path(project_path, key)}\n"
        "Every recorded approach was tried and FAILED — do NOT repeat any of "
        "them. State in your output which previous approach you are replacing "
        "and why yours is different. Read the ACTUAL data shape (api.gen.ts, "
        "or one live GET) before editing any data access."
    )


def leads_block(project_path: Path, state_class=BuildState) -> str:
    """Retry-query block: user replies surfaced as debugging LEADS. A lead
    is a hint to REPRODUCE and VERIFY — never a fact to trust blindly and
    never a command that by itself 'fixes' anything."""
    leads = state_class.load(project_path).user_leads[-3:]
    if not leads:
        return ""
    numbered = "\n".join(f"- {t}" for t in leads)
    return (
        "\n\nUSER-SUPPLIED LEADS (evidence, not gospel):\n"
        f"{numbered}\n"
        "Treat each as a pointer to investigate: reproduce it against the "
        "LIVE app/backend, confirm the real cause yourself, then fix. If a "
        "lead does not reproduce, say so and keep debugging from the actual "
        "evidence — do not blindly apply what the user said."
    )


def _extract_errors_block(query: str) -> str:
    """The failure text portion of a composed retry query (best effort).

    Only the FAILURE blocks belong in the ledger's 'Errors given' — falling
    back to the query head recorded the TARGETED-UPDATE boilerplate as
    'errors' and buried the real history (session 20260717115332)."""
    for marker in (
        "The last build/launch attempt FAILED",
        "The last check found these features NOT working",
        # Fossil markers, kept so old persisted queries still extract:
        "WALK FAILURE",
        "Fix this validation error",
        "FAILURES",
        "Errors:",
    ):
        idx = (query or "").find(marker)
        if idx != -1:
            return query[idx : idx + 1200]
    return "(no failure block in the query — first build round)"


# ═════════════════════════════ code-managed todos ════════════════════════════


def sync_todos(task: Any, project: Any, state: WorkState) -> None:
    """Write the code-computed phase plan (build → present) onto the task
    and broadcast it.

    Direct mutation on purpose: TaskManager.update_todos only works on the
    ACTIVE task, and step turns run regardless of which task is active.
    Fail-open; only touches persistence/broadcast when something changed."""
    try:
        computed = [
            {
                "content": "Build the app",
                "status": "completed" if state.verified else "in_progress",
                "active_form": "Building the app",
            },
            {
                "content": "Present the app",
                "status": "in_progress" if state.verified else "pending",
                "active_form": "Presenting the app",
            },
        ]
        current = [
            {"content": t.content, "status": t.status}
            for t in (getattr(task, "todos", None) or [])
        ]
        if [(t["content"], t["status"]) for t in computed] == [
            (t["content"], t["status"]) for t in current
        ]:
            return
        from agent_core.core.task.todo import TodoItem

        existing_ids = {t.content: t.id for t in (getattr(task, "todos", None) or [])}
        task.todos = [
            TodoItem(
                content=t["content"],
                status=t["status"],
                active_form=t.get("active_form"),
                **(
                    {"id": existing_ids[t["content"]]}
                    if t["content"] in existing_ids
                    else {}
                ),
            )
            for t in computed
        ]
        try:
            from app.usage.session_storage import get_session_storage

            get_session_storage().persist_task(task)
        except Exception:
            pass
        try:
            from app.living_ui.broadcast import _dispatch_todos

            _dispatch_todos(project.id, [t.to_dict() for t in task.todos])
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"[BUILD_DIRECTOR] todo sync skipped: {e}")


# ═════════════════════════════ stable entry points ═══════════════════════════
# Module functions the PLATFORM calls (manager.py launch results, the
# construction-events spawn tap, the user-message hook). They delegate to
# the ONE registered workflow instance.


def _domain():
    from agent_core.core.registry.task_workflows import get_workflow

    # Importing the module registers the workflow (idempotent).
    from app.workflows.living_ui.workflow import WORKFLOW_ID  # noqa: F401

    return get_workflow(WORKFLOW_ID)


def record_validate_outcome(project_path: Path, result: Dict[str, Any]) -> None:
    """Every launch_and_verify outcome. success = the app is STAGED
    (running) — the independent walk still decides "done"."""
    _domain().record_work_outcome(Path(project_path), result)


def record_walk_outcome(project_path: Path, sub_status: str, result_text: str) -> None:
    """The walk_verify verdict — the only thing that can mark the app done."""
    _domain().record_check_outcome(Path(project_path), sub_status, result_text)


def record_user_lead(project_path: Path, message: str) -> None:
    """A user reply, stored as a debugging lead (evidence, not a command)."""
    _domain().record_user_lead(Path(project_path), message)


def adopt_reset(
    project_path: Path, *, targeted: bool = False, incoming_request: str = ""
) -> None:
    """Reset the build state for a NEW owner task (project adoption).

    An adopted project gets a fresh round/check budget and is un-verified
    (the update round must re-earn the walk pass). The FIX LEDGER is kept
    (it stops the next coding round from re-trying dead ends), but
    ``user_leads`` are CLEARED: leads are work orders scoped to a phase,
    and stale ones from previous phases resurrect already-served requests
    (session 20260717081601: a sidebar color fix arrived with an old
    'add a settings page + AI study plan' lead and the agent built all
    three). The adopting funnel records the NEW request right after.

    ``targeted``: this adoption carries a specific change request → work
    and check scope to the CHANGE (proportionality: a sidebar color fix
    must not cost a full-app walk). The check escalates back to full
    rigor on its own when the round touches more than the frontend.
    Fail-open like every recorder."""
    try:
        path = Path(project_path)
        state = BuildState.load(path)
        state.rounds = 0
        state.pending_round = False
        state.awaiting_user_decision = False
        state.staged = False
        state.verified = False
        state.check_attempts = 0
        state.check_failures = []
        state.last_result = None
        state.notify_step_issued = False
        state.presentation_asked = False
        state.infra_blocked = False
        state.checked_ok = []
        state.update_scope = targeted
        state.touched_areas = []
        # Un-served leads (phase never PASSed) become BACKLOG — never
        # auto-executed; the presentation step offers them back to the
        # user. The incoming request is excluded (it's the new phase) and
        # removed from the backlog if it re-asks an old item.
        incoming = (incoming_request or "").strip()
        for lead in state.user_leads:
            if lead and lead != incoming and lead not in state.backlog:
                state.backlog.append(lead)
        if incoming and incoming in state.backlog:
            state.backlog.remove(incoming)
        state.backlog = state.backlog[-10:]
        state.user_leads = []
        state.save(path)
        from app.workflows.workflow import journal

        journal(
            path,
            "adopted",
            targeted=targeted,
            backlog=len(state.backlog),
            phase=state.phase,
        )
    except Exception as e:
        logger.warning(f"[BUILD_DIRECTOR] adopt reset skipped: {e}")


def record_touch(project_path: Path, area: str) -> None:
    """A work-round file write touched ``area`` (frontend/backend/config…) —
    the check phase's escalation signal: a 'targeted update' whose writes
    leave the frontend gets the FULL walk anyway. Fail-open, cheap dedup."""
    try:
        area = (area or "").strip()
        if area not in ("frontend", "backend", "config", "tests"):
            return
        path = Path(project_path)
        state = BuildState.load(path)
        if area not in state.touched_areas:
            state.touched_areas.append(area)
            state.save(path)
    except Exception as e:
        logger.debug(f"[BUILD_DIRECTOR] touch record skipped: {e}")


def record_spawn(
    project_path: Path,
    agent_type: str,
    query: str,
    sub_status: str,
    result_text: str,
) -> None:
    """Record a coding_agent attempt in the fix ledger so the next build
    round never re-tries a failed approach blind. Fail-open."""
    try:
        if agent_type != "coding_agent":
            return
        # A worker that died of LLM infrastructure failure made no attempt:
        # pause the loop (no fixlog entry — nothing was tried).
        from app.agentic.engine import INFRA_LLM_MARKER

        if INFRA_LLM_MARKER in (result_text or ""):
            state = BuildState.load(Path(project_path))
            state.infra_blocked = True
            state.save(Path(project_path))
            logger.warning(
                "[BUILD_DIRECTOR] worker died of LLM infrastructure "
                f"failure — pausing (no budget spent): {project_path}"
            )
            return
        errors_given = _extract_errors_block(query)
        fixlog_append(
            project_path, "VALIDATE", agent_type, errors_given, result_text[-1500:]
        )
    except Exception as e:
        logger.debug(f"[BUILD_DIRECTOR] record_spawn skipped: {e}")


def compute_step(
    subject: Any,
    task: Any,
    turn_context: Dict[str, Any],
    program=None,
) -> Optional[Dict[str, Any]]:
    """One turn of the Living UI program (convenience entry point; pass a
    program instance to drive a variant)."""
    return (program or _domain()).compute(subject, task, turn_context)
