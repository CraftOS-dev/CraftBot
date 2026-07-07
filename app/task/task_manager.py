# -*- coding: utf-8 -*-
"""
TaskManager for CraftBot.

Thin wrapper around the shared agent_core TaskManager. CraftBot uses the
STATE singleton for state access and per-task event streams for multi-tasking.
"""

from typing import Any, Awaitable, Callable, Dict, List, Optional, TYPE_CHECKING
from pathlib import Path

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from agent_core.core.impl.task import TaskManager as _TaskManager
from agent_core.core.task import Task
from app.database_interface import DatabaseInterface
from app.event_stream import EventStreamManager
from app.state.state_manager import StateManager
from app.state.agent_state import STATE
from app.config import AGENT_WORKSPACE_ROOT, AGENT_FILE_SYSTEM_PATH
from app.logger import logger
from traccia import span

if TYPE_CHECKING:
    from app.llm import LLMInterface
    from app.context_engine import ContextEngine
    from agent_core.core.impl.workflow_lock import WorkflowLockManager


# Hook signature: (active_task, updated_todos_as_dicts) -> None.
# Fires after every update_todos call, regardless of transitions, so
# subscribers see the initial all-pending plan as well as later updates.
PostUpdateTodosHook = Callable[[Task, List[Dict[str, Any]]], None]


def _get_gui_mode() -> bool:
    return STATE.gui_mode


def _get_agent_property(name: str, default) -> any:
    return STATE.get_agent_property(name, default)


def _set_agent_property(name: str, value) -> None:
    STATE.set_agent_property(name, value)


# =============================================================================
# Event Stream Hooks for Per-Task Streams
# =============================================================================


def _make_on_stream_create(event_stream_manager: EventStreamManager):
    """Create hook for event stream creation.

    CRITICAL for multi-tasking: Each task needs its own event stream to prevent
    event leakage between concurrent tasks.
    """

    def on_stream_create(task_id: str, temp_dir: Path) -> None:
        event_stream_manager.create_stream(task_id, temp_dir)

    return on_stream_create


def _on_task_persist(task: Task) -> None:
    """Persist task state to SessionStorage for crash recovery."""
    try:
        from app.usage.session_storage import get_session_storage

        get_session_storage().persist_task(task)
    except Exception as e:
        logger.warning(f"[TaskManager] Failed to persist task {task.id}: {e}")


def _make_on_task_remove_persist(event_stream_manager: EventStreamManager):
    """Build the finalize-persistence hook.

    Called once per task at terminal status. Persists the final event stream
    to disk so the task can be brought back via the resume flow. The task
    row itself was already kept up-to-date by ``_on_task_persist`` on every
    state change, so we don't re-write it here. We deliberately do NOT call
    ``session_storage.remove_task`` — the row needs to stick around for the
    Continue Task button to work.
    """

    def on_task_remove_persist(task: Task) -> None:
        try:
            from app.usage.session_storage import get_session_storage

            storage = get_session_storage()
            # Persist the final event stream while it's still in memory.
            # `on_stream_remove` (below) hasn't fired yet, so the per-task
            # stream is still accessible by id.
            stream = event_stream_manager.get_stream_by_id(task.id)
            if stream is not None:
                storage.persist_event_stream(task.id, stream)
        except Exception as e:
            logger.warning(
                f"[TaskManager] Failed to persist final event stream for {task.id}: {e}"
            )

    return on_task_remove_persist


def _make_on_stream_remove(event_stream_manager: EventStreamManager):
    """Create hook for event stream removal on task completion."""

    def on_stream_remove(task_id: str) -> None:
        event_stream_manager.remove_stream(task_id)

    return on_stream_remove


class TaskManager(_TaskManager):
    """TaskManager configured for CraftBot.

    Uses STATE singleton for state access and per-task event streams for
    multi-tasking support. No chatserver hooks are provided since CraftBot
    operates locally without network reporting.
    """

    def __init__(
        self,
        db_interface: DatabaseInterface,
        event_stream_manager: EventStreamManager,
        state_manager: StateManager,
        llm_interface: Optional["LLMInterface"] = None,
        context_engine: Optional["ContextEngine"] = None,
        on_task_end_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        workflow_lock_manager: Optional["WorkflowLockManager"] = None,
    ):
        self._post_update_todos_hooks: List[PostUpdateTodosHook] = []

        super().__init__(
            db_interface=db_interface,
            event_stream_manager=event_stream_manager,
            state_manager=state_manager,
            llm_interface=llm_interface,
            context_engine=context_engine,
            on_task_end_callback=on_task_end_callback,
            workspace_root=Path(AGENT_WORKSPACE_ROOT),
            agent_file_system_path=AGENT_FILE_SYSTEM_PATH,
            # State hooks using STATE singleton
            get_gui_mode=_get_gui_mode,
            get_agent_property=_get_agent_property,
            set_agent_property=_set_agent_property,
            get_conversation_id=lambda: None,  # CraftBot has no conversation IDs
            get_active_task_id=None,  # Use _current_session_id fallback
            # Event stream hooks for per-task streams (CRITICAL for multi-tasking)
            on_stream_create=_make_on_stream_create(event_stream_manager),
            on_stream_remove=_make_on_stream_remove(event_stream_manager),
            # Session persistence hooks for crash recovery
            on_task_persist=_on_task_persist,
            on_task_remove_persist=_make_on_task_remove_persist(event_stream_manager),
            # No chatserver hooks for CraftBot (local only)
            # No chatserver hooks for CraftBot (local only).
            on_task_created_chatserver=None,
            on_todo_transition=None,
            on_task_ended_chatserver=None,
            finalize_todos_chatserver=None,
            # Workflow lock registry for auto-release on task end
            workflow_lock_manager=workflow_lock_manager,
        )

    def add_post_update_todos_hook(self, hook: PostUpdateTodosHook) -> None:
        """Register a hook that fires after every update_todos call.

        Use this to observe todo changes without coupling domain-specific
        logic into TaskManager. Each hook receives the active Task and the
        updated todo list (as dicts).
        """
        self._post_update_todos_hooks.append(hook)

    def update_todos(self, todos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Update todos, then notify registered post-update hooks.

        We override (rather than using the parent's on_todo_transition) because
        that hook fires only on status changes — the initial plan where every
        item is 'pending' produces zero transitions and subscribers would miss
        the first snapshot.
        """
        result = super().update_todos(todos)
        if self.active and self._post_update_todos_hooks:
            for hook in self._post_update_todos_hooks:
                try:
                    hook(self.active, result)
                except Exception as e:
                    logger.warning(f"[TaskManager] post_update_todos hook failed: {e}")
        return result


__all__ = ["TaskManager", "PostUpdateTodosHook"]
