# -*- coding: utf-8 -*-
"""
Multi-session state management for concurrent session execution.

This module provides the StateSession class that supports multiple concurrent
sessions via a class-level registry keyed by session_id. Each persistent
agent session gets one StateSession holding its isolated runtime properties
(run counters, current todo pointer, GUI flag), preventing race conditions
when several sessions run turns concurrently.

Usage:
    from agent_core.core.state.session import StateSession

    # At session creation/restore:
    StateSession.start(session_id="abc123", current_session=session)

    # During a turn (in any consumer):
    session = StateSession.get(session_id)      # raises RuntimeError if not found
    session = StateSession.get_or_none(session_id)  # returns None if not found

    # At session deletion:
    StateSession.end(session_id)

    # Around work done for a session (its serial loop, or a call made for it
    # outside the loop), so context-scoped consumers can find it:
    with StateSession.bind(session_id):
        ...
    state = StateSession.bound()      # None outside any bound session
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import ClassVar, Iterator, Optional, Dict, Any, TYPE_CHECKING

from agent_core.core.state.types import AgentProperties

if TYPE_CHECKING:
    from agent_core.core.session.session import Session


#: Id of the session whose work runs in the current context. asyncio tasks
#: and asyncio.to_thread inherit it, so everything a session's loop starts
#: (actions, sub-agents, LLM calls) sees the session that started it.
_bound_session_id: ContextVar[Optional[str]] = ContextVar(
    "bound_session_id", default=None
)


@dataclass
class StateSession:
    """Per-session runtime state isolated from other concurrent sessions.

    Attributes:
        session_id: Unique identifier for this session
        current_session: The Session object for this lane
        event_stream: Snapshot of the event stream for this session
        gui_mode: Whether this session is running in GUI mode
        agent_properties: Per-session properties (action_count, token_count, etc.)
    """

    _instances: ClassVar[Dict[str, "StateSession"]] = {}

    session_id: str = ""
    current_session: Optional["Session"] = None
    event_stream: Optional[str] = None
    gui_mode: bool = False
    agent_properties: AgentProperties = field(
        default_factory=lambda: AgentProperties(current_task_id="", action_count=0)
    )

    # ------------------------------------------------------------------ #
    # Multi-session lifecycle (class methods)
    # ------------------------------------------------------------------ #
    @classmethod
    def start(
        cls,
        session_id: str,
        *,
        current_session: Optional["Session"] = None,
        event_stream: Optional[str] = None,
        gui_mode: bool = False,
    ) -> "StateSession":
        """Create or update the state bag for the given session_id.

        If state already exists for this session_id, its `agent_properties`
        (which hold per-run counters like action_count and token_count) are
        preserved across re-entries. Only the context fields (session,
        event_stream, gui_mode) are refreshed.

        Args:
            session_id: Unique identifier for this session
            current_session: The Session object for this lane
            event_stream: Snapshot of the event stream
            gui_mode: Whether running in GUI mode

        Returns:
            The created or updated StateSession instance
        """
        existing = cls._instances.get(session_id)
        if existing is not None:
            if current_session is not None:
                existing.current_session = current_session
            if event_stream is not None:
                existing.event_stream = event_stream
            existing.gui_mode = gui_mode
            existing.agent_properties.set_property("current_task_id", session_id)
            return existing

        inst = cls()
        inst.session_id = session_id
        inst.current_session = current_session
        inst.event_stream = event_stream
        inst.gui_mode = gui_mode
        inst.agent_properties = AgentProperties(
            current_task_id=session_id,
            action_count=0,
        )
        cls._instances[session_id] = inst
        return inst

    @classmethod
    def get(cls, session_id: str) -> "StateSession":
        """Get session state by ID.

        Raises:
            RuntimeError: If session is not found
        """
        if session_id not in cls._instances:
            raise RuntimeError(f"StateSession not found for session_id: {session_id}")
        return cls._instances[session_id]

    @classmethod
    def get_or_none(cls, session_id: Optional[str]) -> Optional["StateSession"]:
        """Get session state by ID, or None if not found."""
        if not session_id:
            return None
        return cls._instances.get(session_id)

    @classmethod
    def end(cls, session_id: str) -> None:
        """Remove a session's state (session deletion)."""
        cls._instances.pop(session_id, None)

    @classmethod
    @contextmanager
    def bind(cls, session_id: str) -> Iterator[None]:
        """Mark the current context as doing work for ``session_id``."""
        token = _bound_session_id.set(session_id)
        try:
            yield
        finally:
            _bound_session_id.reset(token)

    @classmethod
    def bound(cls) -> Optional["StateSession"]:
        """State of the session the current context works for, if any."""
        return cls.get_or_none(_bound_session_id.get())

    @classmethod
    def get_all_session_ids(cls) -> list[str]:
        """Get all active session IDs."""
        return list(cls._instances.keys())

    @classmethod
    def clear_all(cls) -> None:
        """Clear all sessions. Use with caution (mainly for testing)."""
        cls._instances.clear()

    # ------------------------------------------------------------------ #
    # Mutators
    # ------------------------------------------------------------------ #
    def update_current_session(self, new_session: Optional["Session"]) -> None:
        """Update the Session object for this lane."""
        self.current_session = new_session

    def update_event_stream(self, new_event_stream: Optional[str]) -> None:
        """Update the event stream snapshot for this session."""
        self.event_stream = new_event_stream

    def update_gui_mode(self, gui_mode: bool) -> None:
        """Update the GUI mode flag for this session."""
        self.gui_mode = gui_mode

    def set_agent_property(self, key: str, value: Any) -> None:
        """Set an agent property for this session."""
        self.agent_properties.set_property(key, value)

    def get_agent_property(self, key: str, default: Any = None) -> Any:
        """Get an agent property for this session."""
        return self.agent_properties.get_property(key, default)

    def get_agent_properties(self) -> Dict[str, Any]:
        """Get all agent properties for this session."""
        return self.agent_properties.to_dict()
