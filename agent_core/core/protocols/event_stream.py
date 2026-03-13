# -*- coding: utf-8 -*-
"""
Protocol definitions for EventStream and EventStreamManager.

This module defines protocols for event stream operations.
"""

from typing import Any, List, Optional, Protocol, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core import EventRecord


class EventStreamProtocol(Protocol):
    """
    Protocol for per-session event streams.

    This defines the minimal interface that an event stream implementation
    must provide for logging and retrieving events.
    """

    head_summary: Optional[str]
    tail_events: List["EventRecord"]

    def log(
        self,
        kind: str,
        message: str,
        severity: str = "INFO",
        *,
        display_message: Optional[str] = None,
        action_name: Optional[str] = None,
    ) -> int:
        """
        Log an event and return its index.

        Args:
            kind: Event category (e.g., "ACTION_START").
            message: Event message content.
            severity: Severity level ("INFO", "WARNING", "ERROR").
            display_message: Optional display-friendly message.
            action_name: Optional action name for filtering.

        Returns:
            The index of the logged event.
        """
        ...

    def to_prompt_snapshot(
        self,
        max_events: int = 60,
        include_summary: bool = True,
    ) -> str:
        """
        Build compact history for LLM prompts.

        Args:
            max_events: Maximum number of recent events to include.
            include_summary: Whether to include the head summary.

        Returns:
            Formatted string of event history.
        """
        ...

    def summarize_if_needed(self) -> None:
        """Trigger summarization when threshold exceeded."""
        ...

    def mark_session_synced(self, call_type: str) -> None:
        """
        Mark events synced to session cache.

        Args:
            call_type: The type of LLM call being synced.
        """
        ...

    def get_delta_events(self, call_type: str) -> Tuple[str, bool]:
        """
        Get events since last sync.

        Args:
            call_type: The type of LLM call.

        Returns:
            Tuple of (delta_text, cache_invalidated).
        """
        ...

    def clear(self) -> None:
        """Reset the stream."""
        ...


class EventStreamManagerProtocol(Protocol):
    """
    Protocol for managing multiple event streams.

    This manages per-task event streams plus a default conversation stream.
    """

    def get_stream(self) -> EventStreamProtocol:
        """
        Get current session's stream.

        Returns:
            The current EventStream instance.
        """
        ...

    def create_stream(
        self,
        task_id: str,
        temp_dir: Optional[str] = None,
    ) -> EventStreamProtocol:
        """
        Create per-task stream.

        Args:
            task_id: The task identifier.
            temp_dir: Optional temporary directory path.

        Returns:
            The created EventStream instance.
        """
        ...

    def remove_stream(self, task_id: str) -> None:
        """
        Remove task's stream.

        Args:
            task_id: The task identifier.
        """
        ...

    def log(
        self,
        kind: str,
        message: str,
        severity: str = "INFO",
        *,
        display_message: Optional[str] = None,
        action_name: Optional[str] = None,
    ) -> int:
        """
        Log to current session's stream.

        Args:
            kind: Event category.
            message: Event message content.
            severity: Severity level.
            display_message: Optional display-friendly message.
            action_name: Optional action name.

        Returns:
            The index of the logged event.
        """
        ...

    def snapshot(self, include_summary: bool = True) -> str:
        """
        Get prompt snapshot of current stream.

        Args:
            include_summary: Whether to include head summary.

        Returns:
            Formatted event history string.
        """
        ...
