# -*- coding: utf-8 -*-
"""
Protocol definition for LLMInterface.

This module defines the LLMInterfaceProtocol that specifies the
interface for LLM operations.
"""

from typing import Any, Dict, List, Optional, Protocol


class LLMInterfaceProtocol(Protocol):
    """
    Protocol for LLM operations.

    This defines the minimal interface that an LLM implementation
    must provide for use by shared agent code.
    """

    provider: str
    model: str
    temperature: float
    max_tokens: int

    async def generate_response_async(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
    ) -> str:
        """
        Generate an LLM response asynchronously.

        Args:
            user_prompt: The user message to send.
            system_prompt: Optional system prompt.
            image_urls: Optional list of image URLs for vision models.

        Returns:
            The generated response text.
        """
        ...

    def generate_response(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
    ) -> str:
        """
        Generate an LLM response synchronously.

        Args:
            user_prompt: The user message to send.
            system_prompt: Optional system prompt.
            image_urls: Optional list of image URLs for vision models.

        Returns:
            The generated response text.
        """
        ...

    def create_session_cache(
        self,
        task_id: str,
        call_type: str,
        system_prompt: str,
    ) -> Optional[str]:
        """
        Create a session cache for a task.

        Args:
            task_id: The task identifier.
            call_type: The type of LLM call (e.g., "reasoning").
            system_prompt: The system prompt to cache.

        Returns:
            Cache identifier, or None if caching not supported.
        """
        ...

    def invalidate_session_cache(
        self,
        task_id: str,
        call_type: str,
    ) -> None:
        """
        Invalidate a session cache.

        Args:
            task_id: The task identifier.
            call_type: The type of LLM call.
        """
        ...

    def invalidate_all_session_caches(self, task_id: str) -> None:
        """
        Invalidate all session caches for a task.

        Args:
            task_id: The task identifier.
        """
        ...
