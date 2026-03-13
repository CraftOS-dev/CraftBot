# -*- coding: utf-8 -*-
"""
Protocol definition for StateManager.

This module defines the StateManagerProtocol that specifies the
interface for state management operations.
"""

from typing import Any, Dict, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core import Task


class StateManagerProtocol(Protocol):
    """
    Protocol for state management.

    This defines the minimal interface for managing agent state,
    including task state and session state.
    """

    async def start_session(
        self,
        gui_mode: bool = False,
        conversation_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """
        Initialize session state.

        Args:
            gui_mode: Whether in GUI mode.
            conversation_id: Optional conversation identifier.
            session_id: Optional session identifier.
        """
        ...

    def clean_state(self) -> None:
        """End current session."""
        ...

    def is_running_task(self, session_id: Optional[str] = None) -> bool:
        """
        Check if task is running.

        Args:
            session_id: Optional session to check.

        Returns:
            True if a task is running.
        """
        ...

    def on_task_created(self, task: "Task") -> None:
        """
        Handle task creation.

        Args:
            task: The created Task.
        """
        ...

    def on_task_ended(
        self,
        task: "Task",
        status: str,
        summary: Optional[str] = None,
    ) -> None:
        """
        Handle task completion.

        Args:
            task: The completed Task.
            status: Final status.
            summary: Optional summary.
        """
        ...

    def bump_event_stream(self) -> None:
        """Refresh event stream in session."""
        ...

    def bump_task_state(self) -> None:
        """Refresh task state in session."""
        ...
