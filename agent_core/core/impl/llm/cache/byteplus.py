# -*- coding: utf-8 -*-
"""
core.llm.cache.byteplus

BytePlus-specific cache management using the Responses API.
"""

from __future__ import annotations

import hashlib
import logging
import requests
from typing import Any, Dict, List, Optional

from .config import get_cache_config


# Logging setup
try:
    from agent_core.utils.logger import logger
except Exception:  # pragma: no cover
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# Maximum input length for BytePlus API (in tokens)
BYTEPLUS_MAX_INPUT_TOKENS = 229376


class BytePlusContextOverflowError(Exception):
    """Raised when BytePlus API rejects input due to context length exceeding maximum."""
    pass


class BytePlusCacheManager:
    """Manages both prefix and session caches for BytePlus Responses API.

    Uses the Responses API with `previous_response_id` chaining instead of
    the Context API. This approach is recommended by BytePlus for better
    cache control and reliability.

    Prefix Cache:
        - For independent calls (event summarization, triggers, etc.)
        - Static system prompt cached, varying user prompts
        - Keyed by hash of system prompt
        - First request: caching={"type": "enabled", "prefix": True}
        - Subsequent requests: previous_response_id + caching={"type": "disabled"}
          (prefix stays static, not updated with new responses)

    Session Cache:
        - For task/GUI calls where context APPENDS over time
        - Context grows with each call (multi-turn-like)
        - Keyed by composite key: task_id:call_type
        - Each call type (reasoning, action_selection, etc.) gets its own session
        - First request: caching={"type": "enabled", "prefix": True}
        - Subsequent requests: previous_response_id + caching={"type": "enabled"}
          (context continues to grow with each response)
    """

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        # Prefix cache: prompt_hash -> response_id (for independent calls)
        # Stores the initial response_id to chain subsequent requests
        self._prefix_cache_registry: Dict[str, str] = {}
        # Session cache: "task_id:call_type" -> response_id (for task/GUI calls)
        # Each call type within a task gets its own session cache
        # The response_id is updated after each call to maintain the chain
        self._session_cache_registry: Dict[str, str] = {}
        # Use shared cache configuration
        self._config = get_cache_config()

    # ─────────────────── Session Key Helper ───────────────────

    def _make_session_key(self, task_id: str, call_type: str) -> str:
        """Create composite key for session cache: task_id:call_type"""
        return f"{task_id}:{call_type}"

    # ─────────────────── Responses API Call ───────────────────

    def _call_responses_api(
        self,
        input_messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        previous_response_id: Optional[str] = None,
        caching_enabled: bool = True,
        caching_prefix: bool = False,
    ) -> Dict[str, Any]:
        """Make a request to BytePlus Responses API.

        Args:
            input_messages: List of message dicts with "role" and "content".
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.
            previous_response_id: ID of previous response to chain from (for caching).
            caching_enabled: Whether to enable caching for this request.
            caching_prefix: Whether this is a prefix cache (True) or session cache (False).

        Returns:
            Raw response dict from the API including 'id' and 'output'.

        Raises:
            requests.HTTPError: If the API call fails.
        """
        url = f"{self.base_url.rstrip('/')}/responses"
        payload: Dict[str, Any] = {
            "model": self.model,
            "input": input_messages,
            "temperature": temperature,
        }

        # IMPORTANT: max_output_tokens is NOT supported when caching.prefix is set
        # Only add max_output_tokens when NOT using prefix caching
        if not caching_prefix:
            payload["max_output_tokens"] = max_tokens

        # Add previous_response_id if chaining from cached context
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id

        # Add caching configuration
        caching_config: Dict[str, Any] = {
            "type": "enabled" if caching_enabled else "disabled",
        }
        if caching_prefix:
            caching_config["prefix"] = True
        payload["caching"] = caching_config

        # Enforce JSON output format (Responses API uses text.format, not response_format)
        payload["text"] = {"format": {"type": "json_object"}}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        # Log the request
        logger.info(f"[BYTEPLUS REQUEST] URL: {url}")
        logger.info(f"[BYTEPLUS REQUEST] Payload: {self._sanitize_payload_for_logging(payload)}")

        response = requests.post(url, json=payload, headers=headers, timeout=600)

        # Log the response status
        logger.info(f"[BYTEPLUS RESPONSE] Status: {response.status_code}")

        # Try to log response body even on error
        try:
            response_json = response.json()
            logger.info(f"[BYTEPLUS RESPONSE] Body: {response_json}")
        except Exception as json_err:
            logger.warning(f"[BYTEPLUS RESPONSE] Failed to parse JSON: {json_err}")
            logger.info(f"[BYTEPLUS RESPONSE] Raw text: {response.text[:1000]}")  # First 1000 chars
            response.raise_for_status()
            return {}

        # Check for context overflow error before raising status
        if response.status_code == 400:
            error_info = response_json.get("error", {})
            error_message = error_info.get("message", "")
            # Detect "Input length X exceeds the maximum length Y" error
            if "exceeds the maximum length" in error_message:
                logger.warning(f"[BYTEPLUS] Context overflow detected: {error_message}")
                raise BytePlusContextOverflowError(error_message)

        response.raise_for_status()
        return response_json

    def _sanitize_payload_for_logging(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize payload for logging by truncating long content."""
        sanitized = {}
        for key, value in payload.items():
            if key == "input":
                # Truncate message content for readability
                sanitized[key] = []
                for msg in value:
                    truncated_msg = {
                        "role": msg.get("role"),
                        "content": msg.get("content", "")[:200] + "..." if len(msg.get("content", "")) > 200 else msg.get("content", "")
                    }
                    sanitized[key].append(truncated_msg)
            else:
                sanitized[key] = value
        return sanitized

    # ─────────────────── Prefix Cache Methods ───────────────────

    def get_or_create_prefix_cache(
        self, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int
    ) -> Dict[str, Any]:
        """Get response using prefix cache, creating cache on first call.

        For prefix cache, the system prompt is cached and reused.
        On the first call, we use caching={"type": "enabled"} (without prefix flag)
        to get a response AND enable automatic caching.
        On subsequent calls, we use previous_response_id with caching={"type": "disabled"}
        to use the cached prefix without growing the context.

        IMPORTANT: Do NOT use caching.prefix=True on first call - that tells BytePlus
        to ONLY create a cache without generating output (output_tokens=0).

        Args:
            system_prompt: The static system prompt to cache.
            user_prompt: The user prompt for this request.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.

        Returns:
            Response dict with 'id', 'output', 'usage', etc.
        """
        prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:16]

        if prompt_hash in self._prefix_cache_registry:
            # Use existing prefix cache - chain from stored response_id
            # Use caching disabled since prefix should stay static
            logger.debug(f"[CACHE] Using prefix cache for hash {prompt_hash}")
            response_id = self._prefix_cache_registry[prompt_hash]
            return self._call_responses_api(
                input_messages=[{"role": "user", "content": user_prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                previous_response_id=response_id,
                caching_enabled=False,  # Don't update the cache, just use it
                caching_prefix=False,
            )

        # First call - use regular caching (NOT prefix=True which returns no output)
        logger.info(f"[CACHE] Creating prefix cache for hash {prompt_hash}")
        result = self._call_responses_api(
            input_messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            previous_response_id=None,
            caching_enabled=True,  # Enable caching, response will be cached automatically
            caching_prefix=False,  # Do NOT use prefix=True - it returns no output!
        )

        # Store the response_id for future requests
        response_id = result.get("id")
        if response_id:
            self._prefix_cache_registry[prompt_hash] = response_id
            logger.info(f"[CACHE] Created prefix cache {response_id} for hash {prompt_hash}")

        return result

    def invalidate_prefix_cache(self, system_prompt: str) -> None:
        """Remove prefix cache entry (e.g., when cache expired)."""
        prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:16]
        removed = self._prefix_cache_registry.pop(prompt_hash, None)
        if removed:
            logger.info(f"[CACHE] Invalidated prefix cache {removed} for hash {prompt_hash}")

    # ─────────────────── Session Cache Methods ───────────────────

    def create_session_cache(
        self, task_id: str, call_type: str, system_prompt: str,
        user_prompt: str, temperature: float, max_tokens: int
    ) -> Dict[str, Any]:
        """Create a new session cache for a specific call type within a task.

        Called on first LLM call for this task/call_type combination.
        The cache will accumulate context as the task progresses.
        Each call type (reasoning, action_selection, etc.) gets its own session cache.

        IMPORTANT: Do NOT use caching.prefix=True on first call - that tells BytePlus
        to ONLY create a cache without generating output (output_tokens=0).

        Args:
            task_id: Unique identifier for the task.
            call_type: Type of LLM call (e.g., "reasoning", "action_selection").
            system_prompt: Initial system prompt for the session.
            user_prompt: The user prompt for this first request.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.

        Returns:
            Response dict with 'id', 'output', 'usage', etc.
        """
        session_key = self._make_session_key(task_id, call_type)
        if session_key in self._session_cache_registry:
            logger.warning(f"[CACHE] Session cache already exists for {session_key}, using existing")
            return self.chat_with_session(task_id, call_type, user_prompt, temperature, max_tokens)

        logger.info(f"[CACHE] Creating session cache for {session_key}")
        result = self._call_responses_api(
            input_messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            previous_response_id=None,
            caching_enabled=True,  # Enable caching, response will be cached automatically
            caching_prefix=False,  # Do NOT use prefix=True - it returns no output!
        )

        # Store the response_id for session chaining
        response_id = result.get("id")
        if response_id:
            self._session_cache_registry[session_key] = response_id
            logger.info(f"[CACHE] Created session cache {response_id} for {session_key}")

        return result

    def chat_with_session(
        self, task_id: str, call_type: str, user_prompt: str,
        temperature: float, max_tokens: int
    ) -> Dict[str, Any]:
        """Send a message using existing session cache.

        The context grows with each call as we chain responses.
        The response_id is updated after each call to maintain the growing context.

        Args:
            task_id: Unique identifier for the task.
            call_type: Type of LLM call (e.g., "reasoning", "action_selection").
            user_prompt: The user prompt to send.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.

        Returns:
            Response dict with 'id', 'output', 'usage', etc.

        Raises:
            ValueError: If no session cache exists for the given task/call_type.
        """
        session_key = self._make_session_key(task_id, call_type)
        previous_response_id = self._session_cache_registry.get(session_key)

        if not previous_response_id:
            raise ValueError(f"No session cache found for {session_key}")

        logger.debug(f"[CACHE] Using session cache for {session_key}")
        result = self._call_responses_api(
            input_messages=[{"role": "user", "content": user_prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            previous_response_id=previous_response_id,
            caching_enabled=True,  # Keep caching enabled to grow context
            caching_prefix=False,
        )

        # Update the stored response_id to chain the next request
        new_response_id = result.get("id")
        if new_response_id:
            self._session_cache_registry[session_key] = new_response_id
            logger.debug(f"[CACHE] Updated session cache for {session_key}: {new_response_id}")

        return result

    def get_session_cache(self, task_id: str, call_type: str) -> Optional[str]:
        """Get the session response_id for a task and call type, if it exists."""
        session_key = self._make_session_key(task_id, call_type)
        return self._session_cache_registry.get(session_key)

    def end_session(self, task_id: str, call_type: str) -> None:
        """Clean up session cache for a specific call type when task ends."""
        session_key = self._make_session_key(task_id, call_type)
        response_id = self._session_cache_registry.pop(session_key, None)
        if response_id:
            logger.info(f"[CACHE] Ended session cache {response_id} for {session_key}")

    def end_all_sessions_for_task(self, task_id: str) -> None:
        """Clean up ALL session caches for a task (all call types)."""
        keys_to_remove = [k for k in self._session_cache_registry if k.startswith(f"{task_id}:")]
        for key in keys_to_remove:
            response_id = self._session_cache_registry.pop(key, None)
            if response_id:
                logger.info(f"[CACHE] Ended session cache {response_id} for {key}")

    def has_session(self, task_id: str, call_type: str) -> bool:
        """Check if a session cache exists for the given task and call type."""
        session_key = self._make_session_key(task_id, call_type)
        return session_key in self._session_cache_registry
