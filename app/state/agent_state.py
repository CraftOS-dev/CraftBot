# -*- coding: utf-8 -*-
"""Global runtime state for a single-user, single-agent process."""

from dataclasses import dataclass
from typing import Any, Optional
from app.state.types import AgentProperties
from app.task import Task
from agent_core.core.state.session import StateSession


@dataclass
class AgentState:
    """Authoritative runtime state for the agent."""

    current_task: Optional[Task] = None
    event_stream: Optional[str] = None
    gui_mode: bool = False
    agent_properties: AgentProperties = AgentProperties(
        current_task_id="", action_count=0
    )
    # UI event bus reference, set by the interface at boot so module-level
    # hooks (e.g. _report_usage) can emit UI events without holding a
    # controller handle. Typed Any to avoid pulling ui_layer into state.
    event_bus: Any = None
    # The agent's main asyncio event loop, captured when the interface
    # adapter starts. Worker threads (e.g. LLM calls via asyncio.to_thread)
    # use this to schedule coroutines back onto the loop via
    # asyncio.run_coroutine_threadsafe. Typed Any to avoid importing asyncio.
    main_loop: Any = None

    def update_current_task(self, new_task: Optional[Task]) -> None:
        self.current_task = new_task

    def update_event_stream(self, new_event_stream: Optional[str]) -> None:
        self.event_stream = new_event_stream

    def update_gui_mode(self, gui_mode: bool) -> None:
        self.gui_mode = gui_mode

    def refresh(
        self,
        *,
        current_task: Optional[Task] = None,
        event_stream: Optional[str] = None,
        gui_mode: Optional[bool] = None,
    ) -> None:
        """Update only fields that changed."""
        self.current_task = current_task
        self.event_stream = event_stream
        self.gui_mode = gui_mode

    def set_agent_property(self, key, value):
        """
        Sets a global agent property (not specific to any task).
        """
        self.agent_properties.set_property(key, value)

    def get_agent_property(self, key, default=None):
        """
        Retrieves a global agent property.
        """
        return self.agent_properties.get_property(key, default)

    def get_agent_properties(self):
        """
        Retrieves all global agent properties.
        """
        return self.agent_properties.to_dict()


# ---- Global runtime state ----
STATE = AgentState()


def get_session_props(session_id: Optional[str] = None) -> AgentProperties:
    """Return the AgentProperties bag that owns per-task counters
    (token_count, action_count) for the active task.

    If `session_id` is given, returns that session's properties; otherwise
    uses STATE.agent_properties.current_task_id to find the active session.
    Falls back to the global STATE.agent_properties when no session exists
    (e.g. conversation mode or before a task is created).

    This is the single source of truth for per-task counters — the global
    STATE counters must not be used for limit checks or token attribution.
    """
    sid = session_id or STATE.agent_properties.get_property("current_task_id", "")
    if sid:
        session = StateSession.get_or_none(sid)
        if session is not None:
            return session.agent_properties
    return STATE.agent_properties
