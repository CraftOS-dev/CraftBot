# -*- coding: utf-8 -*-
"""
Protocol definition for ContextEngine.

This module defines the ContextEngineProtocol that specifies the
interface for prompt construction.
"""

from typing import Any, Dict, Optional, Protocol, Tuple


class ContextEngineProtocol(Protocol):
    """
    Protocol for prompt construction.

    This defines the minimal interface for building prompts
    with context from various sources.
    """

    def make_prompt(
        self,
        query: Optional[str] = None,
        expected_format: Optional[str] = None,
        system_flags: Optional[Dict[str, bool]] = None,
        user_flags: Optional[Dict[str, bool]] = None,
    ) -> Tuple[str, str]:
        """
        Build system and user prompts.

        Args:
            query: Optional query to include.
            expected_format: Expected response format.
            system_flags: Flags for system prompt sections.
            user_flags: Flags for user prompt sections.

        Returns:
            Tuple of (system_prompt, user_prompt).
        """
        ...

    def get_event_stream(self) -> str:
        """
        Get formatted event stream.

        Returns:
            Formatted event stream string.
        """
        ...

    def get_task_state(self) -> str:
        """
        Get formatted task state.

        Returns:
            Formatted task state string.
        """
        ...

    def get_agent_state(self) -> str:
        """
        Get formatted agent state.

        Returns:
            Formatted agent state string.
        """
        ...

    def get_memory_context(
        self,
        query: Optional[str] = None,
        top_k: int = 5,
    ) -> str:
        """
        Get formatted memory context.

        Args:
            query: Optional query for retrieval.
            top_k: Number of results.

        Returns:
            Formatted memory context string.
        """
        ...

    def get_event_stream_delta(self, call_type: str) -> Tuple[str, bool]:
        """
        Get events added since the last sync point for session caching.

        Args:
            call_type: The type of LLM call.

        Returns:
            Tuple of (delta_events_string, has_delta).
        """
        ...

    def mark_event_stream_synced(self, call_type: str) -> None:
        """
        Mark that all current events have been synced to the session cache.

        Args:
            call_type: The type of LLM call.
        """
        ...

    def reset_event_stream_sync(self, call_type: str) -> None:
        """
        Reset the sync point for a session cache.

        Args:
            call_type: The type of LLM call.
        """
        ...
