"""Task ownership of Living UI projects (mixin of LivingUIManager).

THE ownership seam: every path that makes a task the development owner of
a project funnels through ``ensure_project_owner`` — supersede the old
owner, bind, install the workflow, reset build state. Mechanically
extracted from manager.py — bodies unchanged (one latent bug fixed: the
trigger-queue fallback in start_development used ``Trigger`` without
importing it, a NameError silently eaten by its try/except).
"""

import time
from pathlib import Path
from typing import Optional

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


class OwnershipMixin:
    """One owner task per project — enforced by construction.

    Relies on host attributes: ``projects``, ``_task_manager``,
    ``_trigger_service``, ``_trigger_queue``, ``_save_projects``.
    """

    def set_project_task(self, project_id: str, task_id: str) -> None:
        """Associate a task ID with a project."""
        if project_id in self.projects:
            self.projects[project_id].task_id = task_id

    async def adopt_project(self, project_id: str, task_id: str, request: str = ""):
        """Make ``task_id`` the ONE owner of an existing project (updates,
        retries, continuations — any state: built, broken, or half-built).

        Supersede rule: a project has exactly one owner task. If a previous
        owner is still alive it is CANCELLED first — two tasks driving one
        project is how walk verdicts and leads end up split across owners.
        Then the build state is reset for a fresh round budget (fix-ledger
        history kept; see steps.adopt_reset).

        ``request``: the change request — REQUIRED for a targeted update
        phase. Dropping it here made conductor adoptions structurally
        un-targeted (session 20260717082740: full-app rigor for a sidebar
        color change even though change_request was passed to the action).

        Returns the project, or None if it doesn't exist.
        """
        project = self.resolve_project(project_id)
        if not project:
            return None

        await self.ensure_project_owner(
            project.id, task_id, reset_state=True, request=request
        )
        logger.info(f"[LIVING_UI] Project {project.id} adopted by task {task_id}")
        return project

    def resolve_project(self, ref: str):
        """Resolve a project by id, slug, name, or full directory name —
        models reach for 'gre-prep-master' or 'gre_prep_master_59a6550b'
        before the hex id (sessions 20260717052445 / 20260717082740).
        Unique match only; ambiguity returns None (the caller lists
        candidates)."""
        if not ref:
            return None
        project = self.projects.get(ref)
        if project:
            return project
        wanted = ref.strip().lower().replace("-", "_").replace(" ", "_")
        # Full directory name ('<slug>_<id>'): the tail segment is the id.
        if "_" in wanted:
            project = self.projects.get(wanted.rsplit("_", 1)[-1])
            if project and Path(project.path).name.lower() == wanted:
                return project
        matches = [
            p
            for p in self.projects.values()
            if Path(p.path).name.rsplit("_", 1)[0] == wanted
            or p.name.strip().lower().replace("-", "_").replace(" ", "_") == wanted
        ]
        return matches[0] if len(matches) == 1 else None

    async def start_development(
        self, request: str, project_ref: Optional[str] = None
    ) -> Optional[str]:
        """Chat-entry funnel: ONE call turns a user's build/update request
        into a development task — created WITH the workflow, bound through
        ensure_project_owner when it targets an existing app. Kills the
        task_start + skill-guess routing for Living UI work.

        Returns the task id, or None when the manager isn't wired for
        tasks yet. ``project_ref`` may be an id, slug, or name; when it
        doesn't resolve, the task still starts and the workflow's
        bootstrap decides (adopt vs scaffold) with `livingui ls` context.
        """
        if not self._task_manager:
            return None
        from app.workflows.living_ui.workflow import WORKFLOW_ID

        project = self.resolve_project(project_ref) if project_ref else None

        if project:
            task_name = f"Update Living UI: {project.name}"
            task_instruction = (
                f"Update the existing Living UI project '{project.name}'.\n"
                f"Project ID: {project.id}\n"
                f"Project Path: {project.path}\n\n"
                f"USER REQUEST:\n{request}"
            )
        else:
            task_name = "Create Living UI application"
            task_instruction = (
                "Build (or update) a Living UI application for this request. "
                "If it concerns an app the user already has, find it "
                "(`livingui ls`) and living_ui_adopt it — never scaffold a "
                f"duplicate.\n\nUSER REQUEST:\n{request}"
            )

        task_id = self._task_manager.create_task(
            task_name=task_name,
            task_instruction=task_instruction,
            mode="complex",
            action_sets=["file_operations", "code_execution", "living_ui", "core"],
            workflow_id=WORKFLOW_ID,
        )

        if project:
            await self.ensure_project_owner(
                project.id, task_id, reset_state=True, request=request
            )

        # Fire the start trigger (must beat continuation triggers).
        try:
            if self._trigger_service is not None:
                from app.triggers import TriggerSource, TriggerSpec

                await self._trigger_service.emit(
                    TriggerSpec(
                        source=TriggerSource.LIVING_UI_DEV,
                        description=f"[Living UI] Develop: {task_name}",
                        priority=5,
                        session_id=task_id,
                        payload={"type": "living_ui_develop"},
                    )
                )
            elif self._trigger_queue is not None:
                from app.trigger import Trigger

                trigger = Trigger(
                    fire_at=time.time(),
                    priority=5,
                    next_action_description=f"[Living UI] Develop: {task_name}",
                    session_id=task_id,
                    payload={"type": "living_ui_develop"},
                )
                await self._trigger_queue.put(trigger)
        except Exception as e:
            logger.warning(f"[LIVING_UI] start trigger failed: {e}")

        logger.info(
            f"[LIVING_UI] Development task {task_id} started "
            f"(project={project.id if project else 'new'})"
        )
        return task_id

    async def ensure_project_owner(
        self,
        project_id: str,
        task_id: str,
        *,
        reset_state: bool = True,
        request: str = "",
    ) -> None:
        """THE ownership funnel — every path that makes a task the
        DEVELOPMENT owner of a project goes through here (adopt, scaffold,
        modal creation, crash-fix). Enforces the invariant by construction:
        whoever owns a project is driven by the deterministic build
        workflow — a workflow-less owner cannot be produced.

        - Supersedes a previous owner (one owner per project, always).
        - Binds ``project.task_id`` and persists the registry.
        - Installs the workflow on the task (no-op when already attached).
        - ``reset_state``: fresh round/check budget for a NEW owner of
          EXISTING work (adopt, crash-fix); False for a freshly scaffolded
          project whose state is already clean.
        - ``request``: recorded as a user lead — the next round's work order.

        Deliberate exception: the import flow's placeholder task link
        (browser_adapter) bypasses this — it is a broadcast key for the
        import UI, not a development owner.
        """
        project = self.projects.get(project_id)
        if not project:
            return

        old_task_id = project.task_id
        if old_task_id and old_task_id != task_id and self._task_manager:
            try:
                old_task = self._task_manager.tasks.get(old_task_id)
                if old_task and old_task.status not in ("completed", "cancelled"):
                    await self._task_manager.mark_task_cancel(
                        reason=(
                            f"Superseded: project {project_id} adopted by "
                            f"task {task_id}"
                        ),
                        task_id=old_task_id,
                    )
                    logger.info(
                        f"[LIVING_UI] Cancelled previous owner task "
                        f"{old_task_id} of {project_id} (superseded)"
                    )
            except Exception as e:
                logger.warning(
                    f"[LIVING_UI] Could not cancel previous owner "
                    f"{old_task_id}: {e}"
                )

        self.set_project_task(project_id, task_id)
        self._save_projects()

        # Ownership and the build loop must never diverge (sessions
        # 20260716145940 / 20260717052445 / 20260717055257: every
        # workflow-less owner came from a path that skipped this).
        self._install_workflow_on_task(task_id)

        if reset_state:
            # Fresh round budget for the new owner; fixlog/leads kept. A
            # concrete change request makes this a TARGETED update phase
            # (work + check scope to the change; escalates itself to full
            # rigor if the round touches more than the frontend).
            try:
                from app.workflows.living_ui.steps import adopt_reset

                adopt_reset(
                    Path(project.path),
                    targeted=bool(request),
                    incoming_request=request,
                )
            except Exception as e:
                logger.warning(f"[LIVING_UI] adopt reset failed (non-fatal): {e}")

        if request:
            try:
                from app.workflows.living_ui.steps import record_user_lead

                record_user_lead(Path(project.path), request)
            except Exception:
                pass

    def _install_workflow_on_task(self, task_id: str) -> None:
        """Attach the living_ui_development workflow to an ALREADY-RUNNING task.

        Three steps, each required:
        1. ``task.workflow_id`` — the registry key the router/context/step
           machinery resolves every turn.
        2. Re-seed the LLM session caches: they were created with the
           general agent's system prompt; ending + recreating them makes
           the next turn establish under the workflow's purpose-built one
           (_create_session_caches reads the workflow off the task).
        3. Reset the event-stream sync points: the re-established session
           must receive the FULL first prompt — a delta-only establish
           would ground the new session on nothing.
        Fail-open: adoption still succeeds if any step fails; the task
        just keeps its generic prompt until the next session reset.
        """
        if not self._task_manager:
            return
        try:
            from app.workflows.living_ui.workflow import (
                LEGACY_WORKFLOW_ID,
                WORKFLOW_ID,
            )

            task = self._task_manager.tasks.get(task_id)
            if task is None or getattr(task, "workflow_id", None) in (
                WORKFLOW_ID,
                LEGACY_WORKFLOW_ID,
            ):
                return
            task.workflow_id = WORKFLOW_ID

            try:
                self._task_manager.llm_interface.end_all_session_caches(task_id)
                self._task_manager._create_session_caches(task_id)
            except Exception as e:
                logger.warning(
                    f"[LIVING_UI] adopt: session cache re-seed failed: {e}"
                )

            try:
                from agent_core import get_event_stream_manager
                from agent_core.core.impl.llm import LLMCallType

                esm = get_event_stream_manager()
                stream = esm.get_stream_by_id(task_id) if esm else None
                if stream is not None:
                    for call_type in (
                        LLMCallType.REASONING,
                        LLMCallType.ACTION_SELECTION,
                        LLMCallType.GUI_REASONING,
                        LLMCallType.GUI_ACTION_SELECTION,
                    ):
                        stream.reset_session_sync(call_type)
            except Exception as e:
                logger.warning(f"[LIVING_UI] adopt: sync reset failed: {e}")

            # Persist: workflow_id must survive a restart, or a resumed
            # task would come back as the workflow-less hand-builder.
            try:
                from app.usage.session_storage import get_session_storage

                get_session_storage().persist_task(task)
            except Exception as e:
                logger.warning(f"[LIVING_UI] adopt: task persist failed: {e}")

            logger.info(
                f"[LIVING_UI] Installed living_ui_development workflow on "
                f"task {task_id} (adoption)"
            )
        except Exception as e:
            logger.warning(f"[LIVING_UI] workflow install failed (non-fatal): {e}")
