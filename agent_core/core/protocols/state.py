# -*- coding: utf-8 -*-
"""
Protocol definition for StateManager.

This module defines the StateManagerProtocol that specifies the
interface for state management operations.
"""

from typing import Optional, Protocol


class StateManagerProtocol(Protocol):
    """
    Protocol for state management.

    This defines the minimal interface for managing per-session runtime
    state (turn lifecycle, message recording, event stream refresh).
    """

    async def start_turn(self, session_id: str) -> None:
        """
        Refresh per-session state at the start of a turn.

        Args:
            session_id: The session the turn runs in.
        """
        ...

    def clean_state(self) -> None:
        """End the turn, clearing the global state mirror."""
        ...

    def record_user_message(
        self,
        content: str,
        session_id: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> None:
        """
        Record a user message to a session's event stream.

        Args:
            content: The message content.
            session_id: The session the message belongs to (main if omitted).
            platform: Optional platform identifier.
        """
        ...

    def record_agent_message(
        self,
        content: str,
        session_id: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> None:
        """
        Record an agent message to a session's event stream.

        Args:
            content: The message content.
            session_id: The session the message belongs to (main if omitted).
            platform: Optional platform identifier.
        """
        ...

    def bump_event_stream(self) -> None:
        """Refresh the event stream snapshot in state."""
        ...
