# -*- coding: utf-8 -*-
"""
TaskManager for CraftBot.

Thin wrapper around the shared agent_core TaskManager. CraftBot uses the
STATE singleton for state access and per-task event streams for multi-tasking.
"""

from typing import Awaitable, Callable, List, Optional, TYPE_CHECKING
from pathlib import Path

from agent_core.core.impl.task import TaskManager as _TaskManager
from app.database_interface import DatabaseInterface
from app.event_stream import EventStreamManager
from app.state.state_manager import StateManager
from app.state.agent_state import STATE
from app.config import AGENT_WORKSPACE_ROOT, AGENT_FILE_SYSTEM_PATH

if TYPE_CHECKING:
    from app.llm import LLMInterface
    from app.context_engine import ContextEngine


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
    ):
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
            # No chatserver hooks for CraftBot (local only)
            on_task_created_chatserver=None,
            on_todo_transition=None,
            on_task_ended_chatserver=None,
            finalize_todos_chatserver=None,
        )


__all__ = ["TaskManager"]
