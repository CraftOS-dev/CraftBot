# -*- coding: utf-8 -*-
"""
Multi-session state management for concurrent task execution.

This module provides the StateSession class that supports multiple concurrent
sessions via a class-level registry keyed by session_id. This allows multiple
tasks to run simultaneously without state conflicts.

Usage:
    from agent_core.core.state.session import StateSession

    # At session start:
    StateSession.start(session_id="task_123", current_task=task, event_stream=stream)

    # During session (in any consumer):
    session = StateSession.get(session_id)      # raises RuntimeError if not found
    session = StateSession.get_or_none(session_id)  # returns None if not found

    # At session end:
    StateSession.end(session_id)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Optional, Dict, Any, TYPE_CHECKING

from agent_core.core.state.types import AgentProperties

if TYPE_CHECKING:
    from agent_core.core.task.task import Task


@dataclass
class StateSession:
    """Per-session state that is isolated from other concurrent sessions.

    This supports multiple concurrent sessions via a class-level registry
    keyed by session_id. Each task/trigger gets its own StateSession instance,
    preventing race conditions when multiple tasks run simultaneously.

    Attributes:
        session_id: Unique identifier for this session (typically task_id)
        current_task: The Task object for this session
        event_stream: Snapshot of the event stream for this session
        gui_mode: Whether running in GUI mode
        agent_properties: Per-session properties (action_count, token_count, etc.)
    """

    _instances: ClassVar[Dict[str, "StateSession"]] = {}

    # Core task context
    session_id: str = ""
    current_task: Optional["Task"] = None
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
        current_task: Optional["Task"] = None,
        event_stream: Optional[str] = None,
        gui_mode: bool = False,
    ) -> "StateSession":
        """Create or update a session for the given session_id.

        Args:
            session_id: Unique identifier for this session (typically task_id)
            current_task: The Task object for this session
            event_stream: Snapshot of the event stream
            gui_mode: Whether running in GUI mode

        Returns:
            The created or updated StateSession instance
        """
        inst = cls()
        inst.session_id = session_id
        inst.current_task = current_task
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
        """Get session by ID.

        Args:
            session_id: The session identifier

        Returns:
            The StateSession instance

        Raises:
            RuntimeError: If session is not found
        """
        if session_id not in cls._instances:
            raise RuntimeError(f"StateSession not found for session_id: {session_id}")
        return cls._instances[session_id]

    @classmethod
    def get_or_none(cls, session_id: Optional[str]) -> Optional["StateSession"]:
        """Get session by ID, or None if not found.

        Args:
            session_id: The session identifier (can be None)

        Returns:
            The StateSession instance, or None if not found or session_id is None
        """
        if not session_id:
            return None
        return cls._instances.get(session_id)

    @classmethod
    def end(cls, session_id: str) -> None:
        """End and remove a session.

        Args:
            session_id: The session identifier to remove
        """
        cls._instances.pop(session_id, None)

    @classmethod
    def get_all_session_ids(cls) -> list[str]:
        """Get all active session IDs.

        Returns:
            List of active session IDs
        """
        return list(cls._instances.keys())

    @classmethod
    def clear_all(cls) -> None:
        """Clear all sessions. Use with caution (mainly for testing)."""
        cls._instances.clear()

    # ------------------------------------------------------------------ #
    # Mutators (same API as WhiteCollarAgent's StateSession)
    # ------------------------------------------------------------------ #
    def update_current_task(self, new_task: Optional["Task"]) -> None:
        """Update the current task for this session."""
        self.current_task = new_task

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
