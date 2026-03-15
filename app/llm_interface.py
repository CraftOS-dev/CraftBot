# -*- coding: utf-8 -*-
"""
app.llm_interface

All LLM calls have to go through this interface
Currently support llm call to open ai api, google gemini, and remote call to Ollama
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import requests
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from openai import OpenAI


# ─────────────────────────── LLM Call Types for Session Caching ───────────────────────────
class LLMCallType(str, Enum):
    """Types of LLM calls for session cache keying.

    Each call type gets its own session cache within a task, so that
    different prompt structures (reasoning vs action selection) don't
    pollute each other's KV cache.
    """
    REASONING = "reasoning"
    ACTION_SELECTION = "action_selection"
    GUI_REASONING = "gui_reasoning"
    GUI_ACTION_SELECTION = "gui_action_selection"

from app.models.factory import ModelFactory
from app.models.types import InterfaceType
from app.google_gemini_client import GeminiAPIError, GeminiClient
from app.state.agent_state import STATE
from agent_core import profile, OperationCategory

# Logging setup — fall back to a basic logger if the project‑level logger
# is not available (e.g. when running this file standalone).
try:
    from app.logger import logger  # type: ignore
except Exception:  # pragma: no cover
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# ─────────────────────────── Shared Cache Configuration ───────────────────────────
@dataclass
class CacheConfig:
    """Shared cache configuration for all LLM providers.

    This configuration is used by both BytePlus (prefix/session caches) and
    Anthropic (ephemeral cache_control).

    Attributes:
        prefix_cache_ttl: TTL for prefix caches in seconds (BytePlus only).
            Anthropic uses a fixed 5-minute TTL for ephemeral caches.
        session_cache_ttl: TTL for session caches in seconds (BytePlus only).
        min_cache_tokens: Minimum system prompt length (chars) for caching.
            Rough approximation: 500 chars ≈ 1024 tokens.
    """
    prefix_cache_ttl: int = 3600  # 1 hour default
    session_cache_ttl: int = 7200  # 2 hours for long tasks
    min_cache_tokens: int = 500  # ~1024 tokens minimum

    @classmethod
    def from_env(cls) -> "CacheConfig":
        """Load cache configuration from environment variables."""
        return cls(
            prefix_cache_ttl=int(os.getenv("CACHE_PREFIX_TTL", "3600")),
            session_cache_ttl=int(os.getenv("CACHE_SESSION_TTL", "7200")),
            min_cache_tokens=int(os.getenv("CACHE_MIN_TOKENS", "500")),
        )


# Global cache configuration instance
_cache_config: Optional[CacheConfig] = None


def get_cache_config() -> CacheConfig:
    """Get the global cache configuration, initializing from env if needed."""
    global _cache_config
    if _cache_config is None:
        _cache_config = CacheConfig.from_env()
    return _cache_config


# ─────────────────────────── Cache Metrics Tracking ───────────────────────────
@dataclass
class CacheMetricsEntry:
    """Metrics for a single cache operation type."""
    total_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    tokens_cached: int = 0
    tokens_uncached: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate as percentage."""
        if self.total_calls == 0:
            return 0.0
        return (self.cache_hits / self.total_calls) * 100

    @property
    def token_cache_rate(self) -> float:
        """Calculate percentage of tokens served from cache."""
        total = self.tokens_cached + self.tokens_uncached
        if total == 0:
            return 0.0
        return (self.tokens_cached / total) * 100


class CacheMetrics:
    """Tracks cache effectiveness metrics per provider and operation type.

    Usage:
        metrics = CacheMetrics()
        metrics.record_hit("byteplus", "prefix", cached_tokens=500, total_tokens=800)
        metrics.record_miss("byteplus", "session")
        print(metrics.get_summary())
    """

    def __init__(self) -> None:
        # Structure: provider -> cache_type -> CacheMetricsEntry
        self._metrics: Dict[str, Dict[str, CacheMetricsEntry]] = {}

    def _get_entry(self, provider: str, cache_type: str) -> CacheMetricsEntry:
        """Get or create metrics entry for provider/cache_type."""
        if provider not in self._metrics:
            self._metrics[provider] = {}
        if cache_type not in self._metrics[provider]:
            self._metrics[provider][cache_type] = CacheMetricsEntry()
        return self._metrics[provider][cache_type]

    def record_hit(
        self,
        provider: str,
        cache_type: str,
        cached_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        """Record a cache hit with optional token counts."""
        entry = self._get_entry(provider, cache_type)
        entry.total_calls += 1
        entry.cache_hits += 1
        entry.tokens_cached += cached_tokens
        entry.tokens_uncached += max(0, total_tokens - cached_tokens)

        logger.info(
            f"[CACHE METRICS] {provider}/{cache_type}: HIT "
            f"(cached={cached_tokens}, total={total_tokens}, "
            f"hit_rate={entry.hit_rate:.1f}%, token_cache_rate={entry.token_cache_rate:.1f}%)"
        )

    def record_miss(
        self,
        provider: str,
        cache_type: str,
        total_tokens: int = 0,
    ) -> None:
        """Record a cache miss."""
        entry = self._get_entry(provider, cache_type)
        entry.total_calls += 1
        entry.cache_misses += 1
        entry.tokens_uncached += total_tokens

        logger.info(
            f"[CACHE METRICS] {provider}/{cache_type}: MISS "
            f"(total={total_tokens}, hit_rate={entry.hit_rate:.1f}%)"
        )

    def get_summary(self) -> str:
        """Get a formatted summary of all cache metrics."""
        lines = ["=" * 60, "CACHE METRICS SUMMARY", "=" * 60]

        for provider, cache_types in self._metrics.items():
            lines.append(f"\n{provider.upper()}:")
            for cache_type, entry in cache_types.items():
                lines.append(
                    f"  {cache_type}:"
                    f"\n    Calls: {entry.total_calls} "
                    f"(hits={entry.cache_hits}, misses={entry.cache_misses})"
                    f"\n    Hit Rate: {entry.hit_rate:.1f}%"
                    f"\n    Tokens Cached: {entry.tokens_cached:,}"
                    f"\n    Tokens Uncached: {entry.tokens_uncached:,}"
                    f"\n    Token Cache Rate: {entry.token_cache_rate:.1f}%"
                )

        lines.append("=" * 60)
        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all metrics."""
        self._metrics.clear()


# Global cache metrics instance
_cache_metrics: Optional[CacheMetrics] = None


def get_cache_metrics() -> CacheMetrics:
    """Get the global cache metrics instance."""
    global _cache_metrics
    if _cache_metrics is None:
        _cache_metrics = CacheMetrics()
    return _cache_metrics


# ─────────────────────────── BytePlus Constants ───────────────────────────
# Maximum input length for BytePlus API (in tokens)
BYTEPLUS_MAX_INPUT_TOKENS = 229376


class BytePlusContextOverflowError(Exception):
    """Raised when BytePlus API rejects input due to context length exceeding maximum."""
    pass


# ─────────────────────────── BytePlus Cache Manager ───────────────────────────
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
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """Make a request to BytePlus Responses API.

        Args:
            input_messages: List of message dicts with "role" and "content".
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.
            previous_response_id: ID of previous response to chain from (for caching).
            caching_enabled: Whether to enable caching for this request.
            caching_prefix: Whether this is a prefix cache (True) or session cache (False).
            json_mode: Whether to enforce JSON output format.

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

        # Enable JSON mode if requested
        if json_mode:
            payload["text"] = {"format": {"type": "json_object"}}

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
        self, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int,
        call_type: Optional[str] = None
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
            call_type: Type of LLM call (e.g., "reasoning"). Used to enable JSON mode.

        Returns:
            Response dict with 'id', 'output', 'usage', etc.
        """
        prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:16]

        # Always enable JSON mode for all calls
        json_mode = True

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
                json_mode=json_mode,
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
            json_mode=json_mode,
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


# ─────────────────────────── Gemini Cache Manager ───────────────────────────
class GeminiCacheManager:
    """Manages explicit caches for Gemini API.

    Unlike BytePlus which supports session-based caching with growing context,
    Gemini uses explicit cache objects that store system prompts. Each cache
    has a TTL and can be referenced in subsequent requests.

    This manager provides:
    - Prefix caching per call type (reasoning, action_selection, etc.)
    - Each call type's system prompt is cached separately
    - Caches are keyed by hash of system prompt + call type

    Usage:
        manager = GeminiCacheManager(gemini_client, model)
        # First call creates the cache
        result = manager.get_or_create_cache(system_prompt, user_prompt, "reasoning", ...)
        # Subsequent calls with same system prompt use the cache
        result = manager.get_or_create_cache(system_prompt, user_prompt, "reasoning", ...)
    """

    def __init__(self, gemini_client: "GeminiClient", model: str) -> None:
        self._client = gemini_client
        self._model = model
        # Cache registry: "call_type:prompt_hash" -> cache_name
        self._cache_registry: Dict[str, str] = {}
        # Track cache creation time for TTL management
        self._cache_created_at: Dict[str, float] = {}
        self._config = get_cache_config()

    def _make_cache_key(self, system_prompt: str, call_type: str) -> str:
        """Create a unique key for the cache based on system prompt and call type."""
        prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:16]
        return f"{call_type}:{prompt_hash}"

    def get_or_create_cache(
        self,
        system_prompt: str,
        user_prompt: str,
        call_type: str,
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        """Get response using explicit cache, creating cache if needed.

        Args:
            system_prompt: The system prompt to cache.
            user_prompt: The user prompt for this request.
            call_type: Type of LLM call (e.g., "reasoning", "action_selection").
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.

        Returns:
            Response dict with tokens_used, content, cached_tokens, etc.
        """
        import time
        cache_key = self._make_cache_key(system_prompt, call_type)

        # Always enable JSON mode for all calls
        json_mode = True

        # Check if we have an existing cache
        if cache_key in self._cache_registry:
            cache_name = self._cache_registry[cache_key]
            # Check if cache might have expired (TTL is typically 1 hour)
            created_at = self._cache_created_at.get(cache_key, 0)
            if time.time() - created_at < self._config.prefix_cache_ttl - 60:  # 60s buffer
                try:
                    logger.debug(f"[GEMINI CACHE] Using existing cache {cache_name} for {cache_key}")
                    return self._client.generate_text_with_cache(
                        self._model,
                        cache_name=cache_name,
                        prompt=user_prompt,
                        temperature=temperature,
                        max_output_tokens=max_tokens,
                        json_mode=json_mode,
                    )
                except Exception as e:
                    logger.warning(f"[GEMINI CACHE] Cache {cache_name} failed, recreating: {e}")
                    # Cache might have expired or been deleted, remove from registry
                    self._cache_registry.pop(cache_key, None)
                    self._cache_created_at.pop(cache_key, None)

        # Create new cache
        try:
            logger.info(f"[GEMINI CACHE] Creating new cache for {cache_key}")
            cache_result = self._client.create_cache(
                self._model,
                system_prompt=system_prompt,
                display_name=f"agent_{call_type}_{hashlib.sha256(system_prompt.encode()).hexdigest()[:8]}",
                ttl_seconds=self._config.prefix_cache_ttl,
            )
            cache_name = cache_result.get("name")
            if cache_name:
                self._cache_registry[cache_key] = cache_name
                self._cache_created_at[cache_key] = time.time()
                logger.info(f"[GEMINI CACHE] Created cache {cache_name} for {cache_key}")

                # Now generate using the cache
                return self._client.generate_text_with_cache(
                    self._model,
                    cache_name=cache_name,
                    prompt=user_prompt,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    json_mode=json_mode,
                )
        except Exception as e:
            logger.warning(f"[GEMINI CACHE] Failed to create cache for {cache_key}: {e}")
            # Fall back to non-cached generation
            pass

        # Fallback: generate without cache
        logger.debug(f"[GEMINI CACHE] Falling back to non-cached generation for {cache_key}")
        return self._client.generate_text(
            self._model,
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_output_tokens=max_tokens,
            json_mode=json_mode,
        )

    def invalidate_cache(self, system_prompt: str, call_type: str) -> None:
        """Remove a cache entry and optionally delete from Gemini."""
        cache_key = self._make_cache_key(system_prompt, call_type)
        cache_name = self._cache_registry.pop(cache_key, None)
        self._cache_created_at.pop(cache_key, None)
        if cache_name:
            try:
                self._client.delete_cache(cache_name)
                logger.info(f"[GEMINI CACHE] Deleted cache {cache_name} for {cache_key}")
            except Exception as e:
                logger.warning(f"[GEMINI CACHE] Failed to delete cache {cache_name}: {e}")

    def invalidate_all_caches_for_call_type(self, call_type: str) -> None:
        """Remove all caches for a specific call type."""
        keys_to_remove = [k for k in self._cache_registry if k.startswith(f"{call_type}:")]
        for key in keys_to_remove:
            cache_name = self._cache_registry.pop(key, None)
            self._cache_created_at.pop(key, None)
            if cache_name:
                try:
                    self._client.delete_cache(cache_name)
                    logger.info(f"[GEMINI CACHE] Deleted cache {cache_name} for {key}")
                except Exception:
                    pass  # Best effort cleanup

    def cleanup_expired_caches(self) -> None:
        """Clean up caches that may have expired."""
        import time
        current_time = time.time()
        keys_to_remove = []
        for key, created_at in self._cache_created_at.items():
            if current_time - created_at >= self._config.prefix_cache_ttl:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            cache_name = self._cache_registry.pop(key, None)
            self._cache_created_at.pop(key, None)
            if cache_name:
                try:
                    self._client.delete_cache(cache_name)
                except Exception:
                    pass  # Best effort cleanup


class LLMInterface:
    """Simple wrapper to interact with multiple Large-Language-Model back-ends.

    Supported providers
    -------------------
    * ``openai``  – OpenAI Chat Completions API
    * ``remote``  – Local Ollama HTTP endpoint (``/api/generate``)
    * ``gemini``  – Google Generative AI (Gemini) API
    * ``byteplus`` – BytePlus ModelArk Chat Completions API
    * ``anthropic`` – Anthropic Claude API
    """

    _CODE_BLOCK_RE = re.compile(r"^```(?:\w+)?\s*|\s*```$", re.MULTILINE)

    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        db_interface: Optional[Any] = None,
        temperature: float = 0.0,
        max_tokens: int = 8000,
        deferred: bool = False,
    ) -> None:
        self.db_interface = db_interface
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._gemini_client: GeminiClient | None = None
        self._anthropic_client = None
        self._initialized = False
        self._deferred = deferred

        ctx = ModelFactory.create(
            provider=provider,
            interface=InterfaceType.LLM,
            model_override=model,
            deferred=deferred,
        )

        logger.info(f"[LLM FACTORY] {ctx}")

        self.provider = ctx["provider"]
        self.model = ctx["model"]
        self.client = ctx["client"]
        self._gemini_client = ctx["gemini_client"]
        self.remote_url = ctx["remote_url"]
        self._anthropic_client = ctx["anthropic_client"]
        self._initialized = ctx.get("initialized", False)

        # Initialize BytePlus-specific attributes
        self._byteplus_cache_manager: Optional[BytePlusCacheManager] = None
        # Store system prompts for lazy session creation (instance variable)
        self._session_system_prompts: Dict[str, str] = {}

        if ctx["byteplus"]:
            self.api_key = ctx["byteplus"]["api_key"]
            self.byteplus_base_url = ctx["byteplus"]["base_url"]
            # Initialize cache manager for BytePlus (caching always enabled)
            self._byteplus_cache_manager = BytePlusCacheManager(
                api_key=self.api_key,
                base_url=self.byteplus_base_url,
                model=self.model,
            )

        # Initialize Gemini-specific attributes
        self._gemini_cache_manager: Optional[GeminiCacheManager] = None
        if self._gemini_client:
            self._gemini_cache_manager = GeminiCacheManager(
                gemini_client=self._gemini_client,
                model=self.model,
            )

    @property
    def is_initialized(self) -> bool:
        """Check if the LLM client is properly initialized."""
        return self._initialized

    def reinitialize(self, provider: Optional[str] = None) -> bool:
        """Reinitialize the LLM client with current environment variables.

        Args:
            provider: Optional provider override. If None, uses current provider.

        Returns:
            True if initialization was successful, False otherwise.
        """
        target_provider = provider or self.provider
        try:
            logger.info(f"[LLM] Reinitializing with provider: {target_provider}")
            ctx = ModelFactory.create(
                provider=target_provider,
                interface=InterfaceType.LLM,
                model_override=None,
                deferred=False,
            )

            self.provider = ctx["provider"]
            self.model = ctx["model"]
            self.client = ctx["client"]
            self._gemini_client = ctx["gemini_client"]
            self.remote_url = ctx["remote_url"]
            self._anthropic_client = ctx["anthropic_client"]
            self._initialized = ctx.get("initialized", False)

            if ctx["byteplus"]:
                self.api_key = ctx["byteplus"]["api_key"]
                self.byteplus_base_url = ctx["byteplus"]["base_url"]
                # Reinitialize cache manager for BytePlus
                self._byteplus_cache_manager = BytePlusCacheManager(
                    api_key=self.api_key,
                    base_url=self.byteplus_base_url,
                    model=self.model,
                )
                # Reset session system prompts
                self._session_system_prompts = {}
            else:
                self._byteplus_cache_manager = None
                self._session_system_prompts = {}

            # Reinitialize Gemini cache manager
            if self._gemini_client:
                self._gemini_cache_manager = GeminiCacheManager(
                    gemini_client=self._gemini_client,
                    model=self.model,
                )
            else:
                self._gemini_cache_manager = None

            logger.info(f"[LLM] Reinitialized successfully with provider: {self.provider}, model: {self.model}")
            return self._initialized
        except EnvironmentError as e:
            logger.warning(f"[LLM] Failed to reinitialize - missing API key: {e}")
            return False
        except Exception as e:
            logger.error(f"[LLM] Failed to reinitialize - unexpected error: {e}", exc_info=True)
            return False

    # ───────────────────────────  Public helpers  ────────────────────────────
    def _generate_response_sync(
        self,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        log_response: bool = True,
    ) -> str:
        """Synchronous implementation shared by sync/async entry points."""
        if user_prompt is None:
            raise ValueError("`user_prompt` cannot be None.")

        if log_response:
            logger.info(f"[LLM SEND] system={system_prompt} | user={user_prompt}")

        if self.provider == "openai":
            response = self._generate_openai(system_prompt, user_prompt)
        elif self.provider == "remote":
            response = self._generate_ollama(system_prompt, user_prompt)
        elif self.provider == "gemini":
            response = self._generate_gemini(system_prompt, user_prompt)
        elif self.provider == "byteplus":
            response = self._generate_byteplus(system_prompt, user_prompt)
        elif self.provider == "anthropic":
            response = self._generate_anthropic(system_prompt, user_prompt)
        else:  # pragma: no cover
            raise RuntimeError(f"Unknown provider {self.provider!r}")

        cleaned = re.sub(self._CODE_BLOCK_RE, "", response.get("content", "").strip())

        STATE.set_agent_property("token_count", STATE.get_agent_property("token_count", 0) + response.get("tokens_used", 0))
        if log_response:
            logger.info(f"[LLM RECV] {cleaned}")
        return cleaned

    @profile("llm_generate_response", OperationCategory.LLM)
    def generate_response(
        self,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        log_response: bool = True,
    ) -> str:
        """Generate a single response from the configured provider."""
        return self._generate_response_sync(system_prompt, user_prompt, log_response)

    @profile("llm_generate_response_async", OperationCategory.LLM)
    async def generate_response_async(
        self,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        log_response: bool = True,
    ) -> str:
        """Async wrapper that defers the blocking call to a worker thread."""
        return await asyncio.to_thread(
            self._generate_response_sync,
            system_prompt,
            user_prompt,
            log_response,
        )

    # ─────────────────── Session/Explicit Cache Methods ───────────────────

    def create_session_cache(
        self, task_id: str, call_type: str, system_prompt: str
    ) -> Optional[str]:
        """Register a session/cache for a specific call type within a task.

        Supports multiple providers:
        - BytePlus: Uses session caching with Responses API
        - Gemini: Uses explicit caching with per-call-type caches

        The actual cache is created lazily on the first LLM call.
        This method stores the system prompt for later use.

        Should be called at task start. Each call type gets its own cache.

        Args:
            task_id: Unique identifier for the task.
            call_type: Type of LLM call (use LLMCallType enum values).
            system_prompt: Initial system prompt for the session.

        Returns:
            A placeholder ID if successful, None if caching not available.
        """
        # Check if caching is supported for this provider
        supports_caching = (
            (self.provider == "byteplus" and self._byteplus_cache_manager) or
            (self.provider == "gemini" and self._gemini_cache_manager) or
            (self.provider == "openai" and self.client) or  # OpenAI uses automatic caching with prompt_cache_key
            (self.provider == "anthropic" and self._anthropic_client)  # Anthropic uses ephemeral caching with extended TTL
        )

        if not supports_caching:
            logger.debug(f"[SESSION] Session cache not available for provider: {self.provider}")
            return None

        # Store system prompt for lazy session/cache creation
        session_key = f"{task_id}:{call_type}"
        self._session_system_prompts[session_key] = system_prompt
        logger.info(f"[SESSION] Registered session for {session_key} (provider: {self.provider})")
        return session_key  # Return placeholder ID

    def get_session_system_prompt(self, task_id: str, call_type: str) -> Optional[str]:
        """Get the stored system prompt for a session.

        Args:
            task_id: The task ID.
            call_type: Type of LLM call.

        Returns:
            The system prompt if registered, None otherwise.
        """
        session_key = f"{task_id}:{call_type}"
        return self._session_system_prompts.get(session_key)

    def end_session_cache(self, task_id: str, call_type: str) -> None:
        """End a session/explicit cache for a specific call type.

        Should be called at task end to clean up resources.

        Args:
            task_id: The task ID.
            call_type: Type of LLM call (use LLMCallType enum values).
        """
        # Clean up stored system prompt
        session_key = f"{task_id}:{call_type}"
        system_prompt = self._session_system_prompts.pop(session_key, None)

        # Clean up provider-specific caches
        if self.provider == "byteplus" and self._byteplus_cache_manager:
            self._byteplus_cache_manager.end_session(task_id, call_type)
        elif self.provider == "gemini" and self._gemini_cache_manager and system_prompt:
            # Invalidate the explicit cache for this system prompt + call_type
            self._gemini_cache_manager.invalidate_cache(system_prompt, call_type)

    def end_all_session_caches(self, task_id: str) -> None:
        """End ALL session/explicit caches for a task (all call types).

        Convenience method to clean up all caches when a task ends.

        Args:
            task_id: The task whose sessions should be ended.
        """
        # Get all system prompts for this task before removing
        keys_to_remove = [k for k in self._session_system_prompts if k.startswith(f"{task_id}:")]
        prompts_and_types = []
        for key in keys_to_remove:
            system_prompt = self._session_system_prompts.pop(key, None)
            if system_prompt:
                # Extract call_type from key (format: "task_id:call_type")
                call_type = key.split(":", 1)[1] if ":" in key else None
                if call_type:
                    prompts_and_types.append((system_prompt, call_type))

        # Clean up provider-specific caches
        if self.provider == "byteplus" and self._byteplus_cache_manager:
            self._byteplus_cache_manager.end_all_sessions_for_task(task_id)
        elif self.provider == "gemini" and self._gemini_cache_manager:
            # Invalidate all explicit caches for this task's prompts
            for system_prompt, call_type in prompts_and_types:
                self._gemini_cache_manager.invalidate_cache(system_prompt, call_type)

    def has_session_cache(self, task_id: str, call_type: str) -> bool:
        """Check if a session/explicit cache is available for the given task and call type.

        Returns True if:
        - An actual session cache exists (created on previous calls), OR
        - A session has been registered (system prompt stored for lazy creation)

        Supports:
        - BytePlus: Session caching with previous_response_id
        - Gemini: Explicit caching with per-call-type caches

        This allows callers to use session-based generation even on the first call,
        as the session will be created lazily when needed.
        """
        session_key = f"{task_id}:{call_type}"

        # Check if system prompt is registered (works for all providers)
        if session_key in self._session_system_prompts:
            # Also verify the provider supports caching
            if self.provider == "byteplus" and self._byteplus_cache_manager:
                return True
            if self.provider == "gemini" and self._gemini_cache_manager:
                return True
            if self.provider == "openai" and self.client:
                return True
            if self.provider == "anthropic" and self._anthropic_client:
                return True

        # Check provider-specific actual session existence
        if self.provider == "byteplus" and self._byteplus_cache_manager:
            return self._byteplus_cache_manager.has_session(task_id, call_type)

        return False

    def get_cache_stats(self) -> str:
        """Get a summary of cache metrics for all providers.

        Returns a formatted string with cache hit rates, token savings, etc.
        Useful for validating cache effectiveness.

        Example output:
            ============================================================
            CACHE METRICS SUMMARY
            ============================================================

            BYTEPLUS:
              prefix:
                Calls: 10 (hits=8, misses=2)
                Hit Rate: 80.0%
                Tokens Cached: 5000
                Tokens Uncached: 1200
                Token Cache Rate: 80.6%
              session:
                Calls: 25 (hits=22, misses=3)
                Hit Rate: 88.0%
                ...
            ============================================================
        """
        return get_cache_metrics().get_summary()

    def reset_cache_stats(self) -> None:
        """Reset all cache metrics to zero.

        Useful for starting a new measurement period.
        """
        get_cache_metrics().reset()
        logger.info("[CACHE] Cache metrics reset")

    def _generate_response_with_session_sync(
        self,
        task_id: str,
        call_type: str,
        user_prompt: str,
        system_prompt_for_new_session: Optional[str] = None,
        log_response: bool = True,
    ) -> str:
        """Generate response using session/explicit cache for the given task and call type.

        Supports multiple providers:
        - BytePlus: Uses session caching with previous_response_id chaining
        - Gemini: Uses explicit caching with separate caches per call_type
        - Others: Falls back to standard generation

        If no session exists and system_prompt_for_new_session is provided,
        creates a new session cache first. Each call type gets its own session.

        Args:
            task_id: The task ID to use for session cache.
            call_type: Type of LLM call (use LLMCallType enum values).
            user_prompt: The user prompt to send.
            system_prompt_for_new_session: System prompt to use if creating new session.
            log_response: Whether to log the response.

        Returns:
            The cleaned response content.
        """
        if user_prompt is None:
            raise ValueError("`user_prompt` cannot be None.")

        if log_response:
            logger.info(f"[LLM SESSION] task={task_id} call_type={call_type} | user={user_prompt}")

        # Handle Gemini with explicit caching (per call_type)
        if self.provider == "gemini" and self._gemini_cache_manager:
            # Get stored system prompt or use provided one
            session_key = f"{task_id}:{call_type}"
            stored_system_prompt = self._session_system_prompts.get(session_key)
            effective_system_prompt = system_prompt_for_new_session or stored_system_prompt

            if not effective_system_prompt:
                raise ValueError(
                    f"No system prompt for task {task_id}:{call_type}"
                )

            # Use Gemini with explicit caching (call_type passed for cache keying)
            response = self._generate_gemini(effective_system_prompt, user_prompt, call_type=call_type)
            cleaned = re.sub(self._CODE_BLOCK_RE, "", response.get("content", "").strip())
            STATE.set_agent_property(
                "token_count",
                STATE.get_agent_property("token_count", 0) + response.get("tokens_used", 0)
            )
            if log_response:
                logger.info(f"[LLM RECV] {cleaned}")
            return cleaned

        # Handle OpenAI with call_type-based cache routing
        if self.provider == "openai":
            # Get stored system prompt or use provided one
            session_key = f"{task_id}:{call_type}"
            stored_system_prompt = self._session_system_prompts.get(session_key)
            effective_system_prompt = system_prompt_for_new_session or stored_system_prompt

            if not effective_system_prompt:
                raise ValueError(
                    f"No system prompt for task {task_id}:{call_type}"
                )

            # Use OpenAI with call_type for better cache routing via prompt_cache_key
            response = self._generate_openai(effective_system_prompt, user_prompt, call_type=call_type)
            cleaned = re.sub(self._CODE_BLOCK_RE, "", response.get("content", "").strip())
            STATE.set_agent_property(
                "token_count",
                STATE.get_agent_property("token_count", 0) + response.get("tokens_used", 0)
            )
            if log_response:
                logger.info(f"[LLM RECV] {cleaned}")
            return cleaned

        # Handle Anthropic with call_type-based extended TTL caching
        if self.provider == "anthropic" and self._anthropic_client:
            # Get stored system prompt or use provided one
            session_key = f"{task_id}:{call_type}"
            stored_system_prompt = self._session_system_prompts.get(session_key)
            effective_system_prompt = system_prompt_for_new_session or stored_system_prompt

            if not effective_system_prompt:
                raise ValueError(
                    f"No system prompt for task {task_id}:{call_type}"
                )

            # Use Anthropic with call_type for extended 1-hour TTL caching
            response = self._generate_anthropic(effective_system_prompt, user_prompt, call_type=call_type)
            cleaned = re.sub(self._CODE_BLOCK_RE, "", response.get("content", "").strip())
            STATE.set_agent_property(
                "token_count",
                STATE.get_agent_property("token_count", 0) + response.get("tokens_used", 0)
            )
            if log_response:
                logger.info(f"[LLM RECV] {cleaned}")
            return cleaned

        # If not BytePlus (and not Gemini/OpenAI/Anthropic which are handled above), fall back to standard
        if self.provider != "byteplus" or not self._byteplus_cache_manager:
            return self._generate_response_sync(
                system_prompt_for_new_session, user_prompt, log_response=False
            )

        # Use SESSION cache for BytePlus - context grows with each call
        # Round 1: system_prompt + static_prompt + event_1
        # Round 2: event_2 (delta only)
        # Round 3: event_3 (delta only)
        session_key = f"{task_id}:{call_type}"
        stored_system_prompt = self._session_system_prompts.get(session_key)
        effective_system_prompt = system_prompt_for_new_session or stored_system_prompt

        if not effective_system_prompt:
            raise ValueError(
                f"No system prompt for task {task_id}:{call_type}"
            )

        # Store system prompt for future cache recreation if not stored
        if session_key not in self._session_system_prompts:
            self._session_system_prompts[session_key] = effective_system_prompt

        try:
            # Check if session cache exists
            if self._byteplus_cache_manager.has_session(task_id, call_type):
                # Session exists - send only the user_prompt (delta events)
                logger.info(f"[SESSION CACHE] Using existing session for {session_key}, sending delta")
                result = self._byteplus_cache_manager.chat_with_session(
                    task_id=task_id,
                    call_type=call_type,
                    user_prompt=user_prompt,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                response = self._process_session_response(result, task_id, call_type, is_first_call=False)
            else:
                # No session - create one with full prompt (system + user)
                logger.info(f"[SESSION CACHE] Creating new session for {session_key}")
                result = self._byteplus_cache_manager.create_session_cache(
                    task_id=task_id,
                    call_type=call_type,
                    system_prompt=effective_system_prompt,
                    user_prompt=user_prompt,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                response = self._process_session_response(result, task_id, call_type, is_first_call=True)

        except BytePlusContextOverflowError as overflow_exc:
            # Context exceeded maximum length - reset session and retry with fresh context
            logger.warning(f"[SESSION CACHE] Context overflow for {session_key}, resetting session...")

            # End the overflowed session
            self._byteplus_cache_manager.end_session(task_id, call_type)

            # Create a fresh session with system prompt and current user prompt
            logger.info(f"[SESSION CACHE] Creating fresh session for {session_key} after overflow")
            result = self._byteplus_cache_manager.create_session_cache(
                task_id=task_id,
                call_type=call_type,
                system_prompt=effective_system_prompt,
                user_prompt=user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            response = self._process_session_response(result, task_id, call_type, is_first_call=True)

        except Exception as e:
            logger.warning(f"[SESSION CACHE] Failed: {e}, falling back to standard")
            return self._generate_response_sync(
                effective_system_prompt, user_prompt, log_response=False
            )

        cleaned = re.sub(self._CODE_BLOCK_RE, "", response.get("content", "").strip())

        STATE.set_agent_property(
            "token_count",
            STATE.get_agent_property("token_count", 0) + response.get("tokens_used", 0)
        )
        if log_response:
            logger.info(f"[LLM RECV] {cleaned}")
        return cleaned

    def _process_session_response(
        self, result: Dict[str, Any], task_id: str, call_type: str, is_first_call: bool = False
    ) -> Dict[str, Any]:
        """Process response from session cache call and record metrics.

        Args:
            result: Raw response from Responses API.
            task_id: The task ID.
            call_type: Type of LLM call.
            is_first_call: Whether this is the first call (session creation).

        Returns:
            Processed response dict with 'tokens_used' and 'content'.
        """
        session_key = f"{task_id}:{call_type}"

        # Parse content (Responses API format)
        content = self._parse_responses_api_content(result)

        # Token usage from Responses API
        usage = result.get("usage") or {}
        token_count_input = int(usage.get("input_tokens", 0))
        token_count_output = int(usage.get("output_tokens", 0))
        total_tokens = int(usage.get("total_tokens", 0)) or (token_count_input + token_count_output)

        # Log cache info and record metrics
        cached_tokens = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
        metrics = get_cache_metrics()
        if cached_tokens and cached_tokens > 0:
            logger.info(f"[CACHE] BytePlus session cache hit: {cached_tokens}/{token_count_input} tokens cached")
            metrics.record_hit("byteplus", "session", cached_tokens=cached_tokens, total_tokens=token_count_input)
        else:
            # First call in session or cache miss
            metrics.record_miss("byteplus", "session", total_tokens=token_count_input)

        logger.info(f"BYTEPLUS SESSION RESPONSE for {session_key}: {result}")

        self._log_to_db(
            f"[SESSION:{session_key}]",
            "[session_call]",
            content,
            "success",
            token_count_input,
            token_count_output,
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or ""
        }

    def _process_prefix_response(
        self, result: Dict[str, Any], session_key: str
    ) -> Dict[str, Any]:
        """Process response from prefix cache call and record metrics.

        Args:
            result: Raw response from Responses API.
            session_key: The session key for logging.

        Returns:
            Processed response dict with 'tokens_used' and 'content'.
        """
        # Parse content (Responses API format)
        content = self._parse_responses_api_content(result)

        # Token usage from Responses API
        usage = result.get("usage") or {}
        token_count_input = int(usage.get("input_tokens", 0))
        token_count_output = int(usage.get("output_tokens", 0))
        total_tokens = int(usage.get("total_tokens", 0)) or (token_count_input + token_count_output)

        # Log cache info and record metrics
        cached_tokens = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
        metrics = get_cache_metrics()
        if cached_tokens and cached_tokens > 0:
            logger.info(f"[CACHE] BytePlus prefix cache hit: {cached_tokens}/{token_count_input} tokens cached")
            metrics.record_hit("byteplus", "prefix", cached_tokens=cached_tokens, total_tokens=token_count_input)
        else:
            # First call or cache miss
            metrics.record_miss("byteplus", "prefix", total_tokens=token_count_input)

        logger.info(f"BYTEPLUS PREFIX RESPONSE for {session_key}: input={token_count_input}, cached={cached_tokens}")

        self._log_to_db(
            f"[PREFIX:{session_key}]",
            "[prefix_call]",
            content,
            "success",
            token_count_input,
            token_count_output,
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or ""
        }

    def generate_response_with_session(
        self,
        task_id: str,
        call_type: str,
        user_prompt: str,
        system_prompt_for_new_session: Optional[str] = None,
        log_response: bool = True,
    ) -> str:
        """Synchronous session-based response generation.

        Args:
            task_id: The task ID to use for session cache.
            call_type: Type of LLM call (use LLMCallType enum values).
            user_prompt: The user prompt to send.
            system_prompt_for_new_session: System prompt to use if creating new session.
            log_response: Whether to log the response.
        """
        return self._generate_response_with_session_sync(
            task_id, call_type, user_prompt, system_prompt_for_new_session, log_response
        )

    @profile("llm_generate_response_with_session_async", OperationCategory.LLM)
    async def generate_response_with_session_async(
        self,
        task_id: str,
        call_type: str,
        user_prompt: str,
        system_prompt_for_new_session: Optional[str] = None,
        log_response: bool = True,
    ) -> str:
        """Async wrapper for session-based response generation.

        Args:
            task_id: The task ID to use for session cache.
            call_type: Type of LLM call (use LLMCallType enum values).
            user_prompt: The user prompt to send.
            system_prompt_for_new_session: System prompt to use if creating new session.
            log_response: Whether to log the response.
        """
        return await asyncio.to_thread(
            self._generate_response_with_session_sync,
            task_id,
            call_type,
            user_prompt,
            system_prompt_for_new_session,
            log_response,
        )

    def _generate_byteplus_with_session(
        self, task_id: str, call_type: str, user_prompt: str
    ) -> Dict[str, Any]:
        """Use Responses API with session caching for task/GUI calls.

        The context grows with each call as we chain responses via previous_response_id.
        Each call type has its own session to avoid polluting different prompt structures.

        If context overflow is detected, the session is automatically reset and retried
        with a fresh session containing only the system prompt and current user prompt.
        """
        token_count_input = token_count_output = 0
        total_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None
        session_key = f"{task_id}:{call_type}"

        try:
            if not self._byteplus_cache_manager.has_session(task_id, call_type):
                raise ValueError(f"No session cache found for {session_key}")

            result = self._byteplus_cache_manager.chat_with_session(
                task_id=task_id,
                call_type=call_type,
                user_prompt=user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            logger.info(f"BYTEPLUS SESSION RESPONSE: {result}")

            # Parse response (Responses API format)
            content = self._parse_responses_api_content(result)

            # Token usage from Responses API
            usage = result.get("usage") or {}
            token_count_input = int(usage.get("input_tokens", 0))
            token_count_output = int(usage.get("output_tokens", 0))
            total_tokens = int(usage.get("total_tokens", 0)) or (token_count_input + token_count_output)

            # Log cache info and record metrics
            # Responses API uses input_tokens_details instead of prompt_tokens_details
            cached_tokens = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
            metrics = get_cache_metrics()
            if cached_tokens and cached_tokens > 0:
                logger.info(f"[CACHE] BytePlus session cache hit: {cached_tokens}/{token_count_input} tokens cached")
                metrics.record_hit("byteplus", "session", cached_tokens=cached_tokens, total_tokens=token_count_input)
            else:
                # First call in session or growing context
                metrics.record_miss("byteplus", "session", total_tokens=token_count_input)

            status = "success"

        except BytePlusContextOverflowError as overflow_exc:
            # Context exceeded maximum length - reset session and retry with fresh context
            logger.warning(f"[BYTEPLUS] Context overflow for {session_key}, resetting session and retrying...")

            # End the overflowed session
            self._byteplus_cache_manager.end_session(task_id, call_type)

            # Get the stored system prompt for this session
            system_prompt = self._session_system_prompts.get(session_key)
            if not system_prompt:
                exc_obj = ValueError(f"Cannot reset session {session_key}: no system prompt stored")
                logger.error(str(exc_obj))
            else:
                try:
                    # Create a fresh session with system prompt and current user prompt
                    logger.info(f"[BYTEPLUS] Creating fresh session for {session_key} after overflow")
                    result = self._byteplus_cache_manager.create_session_cache(
                        task_id=task_id,
                        call_type=call_type,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )

                    logger.info(f"BYTEPLUS SESSION RESPONSE (after reset): {result}")

                    # Parse response
                    content = self._parse_responses_api_content(result)

                    # Token usage
                    usage = result.get("usage") or {}
                    token_count_input = int(usage.get("input_tokens", 0))
                    token_count_output = int(usage.get("output_tokens", 0))
                    total_tokens = int(usage.get("total_tokens", 0)) or (token_count_input + token_count_output)

                    # Record as cache miss (fresh session)
                    metrics = get_cache_metrics()
                    metrics.record_miss("byteplus", "session_reset", total_tokens=token_count_input)

                    status = "success"
                    logger.info(f"[BYTEPLUS] Successfully recovered from context overflow for {session_key}")

                except Exception as retry_exc:
                    exc_obj = retry_exc
                    logger.error(f"Error retrying BytePlus Session API for {session_key} after reset: {retry_exc}")

        except Exception as exc:
            exc_obj = exc
            logger.error(f"Error calling BytePlus Session API for {session_key}: {exc}")

        self._log_to_db(
            f"[SESSION:{session_key}]",  # Mark as session call in logs with call_type
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
        )
        return {
            "tokens_used": total_tokens or 0,
            "content": content or ""
        }

    # ───────────────────── Provider‑specific private helpers ─────────────────────
    @profile("llm_openai_call", OperationCategory.LLM)
    def _generate_openai(
        self, system_prompt: str | None, user_prompt: str, call_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate response using OpenAI with automatic prompt caching.

        OpenAI's prompt caching is automatic for prompts ≥1024 tokens:
        - No code changes required to enable caching
        - Cached tokens are returned in usage.prompt_tokens_details.cached_tokens
        - 50% discount on cached input tokens
        - Cache retention: 5-10 minutes (up to 1 hour during off-peak)
        - Using prompt_cache_key influences routing for better cache hit rates

        Args:
            system_prompt: The system prompt.
            user_prompt: The user prompt for this request.
            call_type: Optional call type for cache routing (e.g., "reasoning", "action_selection").
                       When provided, generates a prompt_cache_key to improve cache hit rates
                       when alternating between different call types.

        Cache hits are logged when cached_tokens > 0 in the response.
        """
        token_count_input = token_count_output = 0
        cached_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None
        config = get_cache_config()
        cache_type = f"automatic_{call_type}" if call_type else "automatic"

        try:
            messages: List[Dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})

            # Build request kwargs
            request_kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }

            # Always enforce JSON output format
            request_kwargs["response_format"] = {"type": "json_object"}

            # Add prompt_cache_key when call_type is provided for better cache routing
            # This helps when alternating between different call types (reasoning, action_selection)
            if call_type and system_prompt and len(system_prompt) >= config.min_cache_tokens:
                prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:16]
                cache_key = f"{call_type}_{prompt_hash}"
                request_kwargs["extra_body"] = {"prompt_cache_key": cache_key}
                logger.debug(f"[OPENAI] Using prompt_cache_key: {cache_key}")

            response = self.client.chat.completions.create(**request_kwargs)
            content = response.choices[0].message.content.strip()
            token_count_input = response.usage.prompt_tokens
            token_count_output = response.usage.completion_tokens

            # Extract cached tokens from prompt_tokens_details (OpenAI automatic caching)
            # Available for prompts ≥1024 tokens
            prompt_tokens_details = getattr(response.usage, "prompt_tokens_details", None)
            if prompt_tokens_details:
                cached_tokens = getattr(prompt_tokens_details, "cached_tokens", 0) or 0

            # Record cache metrics
            metrics = get_cache_metrics()
            if cached_tokens > 0:
                logger.info(f"[CACHE] OpenAI {cache_type} cache hit: {cached_tokens}/{token_count_input} tokens from cache")
                metrics.record_hit("openai", cache_type, cached_tokens=cached_tokens, total_tokens=token_count_input)
            elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
                # Caching should have been attempted (prompt long enough)
                # This is a miss - either first call or cache expired
                metrics.record_miss("openai", cache_type, total_tokens=token_count_input)

            status = "success"
        except Exception as exc:
            exc_obj = exc
            logger.error(f"Error calling OpenAI API: {exc}")

        total_tokens = token_count_input + token_count_output

        self._log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
        )
        return {
            "tokens_used": total_tokens or 0,
            "content": content or "",
            "cached_tokens": cached_tokens,
        }

    @profile("llm_ollama_call", OperationCategory.LLM)
    def _generate_ollama(self, system_prompt: str | None, user_prompt: str) -> str:
        token_count_input = token_count_output = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None

        try:
            payload = {
                "model": self.model,
                "system": system_prompt,
                "prompt": user_prompt,
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                }
            }
            url: str = f"{self.remote_url.rstrip('/')}/generate"
            response = requests.post(url, json=payload, timeout=600)
            response.raise_for_status()
            result = response.json()

            content = result.get("response", "").strip()
            total_tokens = result.get("usage", {}).get("total_tokens", 0)
            token_count_input = result.get("prompt_eval_count", 0)
            token_count_output = result.get("eval_count", 0)
            status = "success"
        except Exception as exc:  
            exc_obj = exc
            logger.error(f"Error calling Ollama API: {exc}")

        self._log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
        )
        return {
            "tokens_used": total_tokens or 0,
            "content": content or ""
        }

    @profile("llm_gemini_call", OperationCategory.LLM)
    def _generate_gemini(
        self, system_prompt: str | None, user_prompt: str, call_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate response using Gemini with explicit or implicit caching.

        When call_type is provided and system_prompt is long enough, uses explicit
        caching via GeminiCacheManager. This ensures different call types (reasoning,
        action_selection, etc.) get separate caches for optimal cache hit rates.

        Without call_type, falls back to Gemini's implicit caching which may have
        lower hit rates when alternating between different prompt structures.

        Args:
            system_prompt: The system prompt (cached when using explicit caching).
            user_prompt: The user prompt for this request.
            call_type: Optional call type for cache keying (e.g., "reasoning", "action_selection").
                       When provided, enables explicit caching per call type.

        Returns:
            Dict with tokens_used, content, cached_tokens.
        """
        token_count_input = token_count_output = 0
        cached_tokens = 0
        total_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None
        config = get_cache_config()
        cache_type = "implicit"  # Default cache type for metrics

        try:
            if not self._gemini_client:
                raise RuntimeError("Gemini client was not initialised.")

            # Use explicit caching when:
            # 1. call_type is provided
            # 2. system_prompt is long enough
            # 3. cache manager is available
            use_explicit_cache = (
                call_type
                and system_prompt
                and len(system_prompt) >= config.min_cache_tokens
                and self._gemini_cache_manager
            )

            if use_explicit_cache:
                cache_type = f"explicit_{call_type}"
                logger.debug(f"[GEMINI] Using explicit caching for call_type: {call_type}")
                result = self._gemini_cache_manager.get_or_create_cache(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    call_type=call_type,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
            else:
                # Fall back to implicit caching (or no caching for short prompts)
                result = self._gemini_client.generate_text(
                    self.model,
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=self.temperature,
                    max_output_tokens=self.max_tokens,
                    json_mode=True,
                )

            # Extract response data
            content = result.get("content", "")
            total_tokens = result.get("tokens_used", 0)
            token_count_input = result.get("prompt_tokens", 0)
            token_count_output = result.get("completion_tokens", 0)
            cached_tokens = result.get("cached_tokens", 0)

            # Record cache metrics
            metrics = get_cache_metrics()
            if cached_tokens > 0:
                logger.info(f"[CACHE] Gemini {cache_type} cache hit: {cached_tokens}/{token_count_input} tokens from cache")
                metrics.record_hit("gemini", cache_type, cached_tokens=cached_tokens, total_tokens=token_count_input)
            elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
                # Caching should have been attempted (prompt long enough)
                # This is a miss - either first call or cache expired
                metrics.record_miss("gemini", cache_type, total_tokens=token_count_input)

            status = "success"
        except GeminiAPIError as exc:  # pragma: no cover
            exc_obj = exc
            logger.error(f"Gemini API rejected the prompt: {exc}")
        except Exception as exc:  # pragma: no cover
            exc_obj = exc
            logger.error(f"Error calling Gemini API: {exc}")

        self._log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
        )
        return {
            "tokens_used": total_tokens or 0,
            "content": content or "",
            "cached_tokens": cached_tokens,
        }

    @profile("llm_byteplus_call", OperationCategory.LLM)
    def _generate_byteplus(self, system_prompt: str | None, user_prompt: str) -> Dict[str, Any]:
        """Generate response using BytePlus with automatic prefix caching.

        Routes to prefix cache or standard API based on context.
        """
        config = get_cache_config()
        # Use prefix caching if:
        # - System prompt is provided
        # - System prompt is long enough (uses shared config)
        # - Cache manager is available
        if (
            system_prompt
            and len(system_prompt) >= config.min_cache_tokens
            and self._byteplus_cache_manager
        ):
            return self._generate_byteplus_with_prefix_cache(system_prompt, user_prompt)

        # Standard path (no caching)
        return self._generate_byteplus_standard(system_prompt, user_prompt)

    def _generate_byteplus_with_prefix_cache(
        self, system_prompt: str, user_prompt: str
    ) -> Dict[str, Any]:
        """Use Responses API with prefix caching.

        The system prompt is cached and reused across calls with the same content.
        Only the user prompt is processed fresh each time.
        Uses previous_response_id chaining for cache hits.
        """
        token_count_input = token_count_output = 0
        total_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None

        try:
            # Get response using prefix cache (creates cache on first call)
            result = self._byteplus_cache_manager.get_or_create_prefix_cache(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            logger.info(f"BYTEPLUS CACHED RESPONSE: {result}")

            # Parse response (Responses API format)
            content = self._parse_responses_api_content(result)

            # Token usage from Responses API
            usage = result.get("usage") or {}
            token_count_input = int(usage.get("input_tokens", 0))
            token_count_output = int(usage.get("output_tokens", 0))
            total_tokens = int(usage.get("total_tokens", 0)) or (token_count_input + token_count_output)

            # Log cache hit info if available and record metrics
            # Responses API uses input_tokens_details instead of prompt_tokens_details
            cached_tokens = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
            metrics = get_cache_metrics()
            if cached_tokens and cached_tokens > 0:
                logger.info(f"[CACHE] BytePlus prefix cache hit: {cached_tokens}/{token_count_input} tokens cached")
                metrics.record_hit("byteplus", "prefix", cached_tokens=cached_tokens, total_tokens=token_count_input)
            else:
                # First call or cache miss
                metrics.record_miss("byteplus", "prefix", total_tokens=token_count_input)

            status = "success"

        except requests.HTTPError as e:
            # Check if this is a cache-related error (expired, not found)
            if e.response is not None and e.response.status_code in (404, 410):
                logger.warning(f"[CACHE] Cache expired or not found, recreating: {e}")
                # Invalidate and retry once
                self._byteplus_cache_manager.invalidate_prefix_cache(system_prompt)
                try:
                    result = self._byteplus_cache_manager.get_or_create_prefix_cache(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )
                    content = self._parse_responses_api_content(result)
                    usage = result.get("usage") or {}
                    token_count_input = int(usage.get("input_tokens", 0))
                    token_count_output = int(usage.get("output_tokens", 0))
                    total_tokens = int(usage.get("total_tokens", 0)) or (token_count_input + token_count_output)
                    status = "success"
                except Exception as retry_exc:
                    exc_obj = retry_exc
                    logger.error(f"[CACHE] Retry failed, falling back: {retry_exc}")
                    return self._generate_byteplus_standard(system_prompt, user_prompt)
            else:
                exc_obj = e
                logger.error(f"Error calling BytePlus Responses API: {e}")
        except Exception as exc:
            exc_obj = exc
            logger.error(f"Error calling BytePlus Responses API: {exc}")

        self._log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
        )
        return {
            "tokens_used": total_tokens or 0,
            "content": content or ""
        }

    def _parse_responses_api_content(self, result: Dict[str, Any]) -> str:
        """Parse content from BytePlus Responses API response.

        The Responses API uses a different format than chat/completions:
        {
            "output": [
                {"type": "message", "role": "assistant", "content": [
                    {"type": "text", "text": "..."}
                ]}
            ]
        }
        """
        content = ""
        output = result.get("output", [])
        for item in output:
            if item.get("type") == "message" and item.get("role") == "assistant":
                content_blocks = item.get("content", [])
                for block in content_blocks:
                    # Handle both "text" and "output_text" types (BytePlus uses "output_text")
                    if block.get("type") in ("text", "output_text"):
                        content += block.get("text", "")
        return content.strip()

    def _generate_byteplus_standard(
        self, system_prompt: str | None, user_prompt: str
    ) -> Dict[str, Any]:
        """Standard BytePlus API call without caching (uses /chat/completions)."""
        token_count_input = token_count_output = 0
        total_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None

        try:
            # Build OpenAI-compatible messages array
            messages: List[Dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})

            url = f"{self.byteplus_base_url.rstrip('/')}/chat/completions"
            payload = {
                "model": self.model,
                "messages": messages,
                # Wire through sampling + output control
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                # Note: response_format not supported by all BytePlus models (e.g., kimi)
                # "stream": False,  # default is non-streaming
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }

            # Log the request
            logger.info(f"[BYTEPLUS STANDARD REQUEST] URL: {url}")
            logger.info(f"[BYTEPLUS STANDARD REQUEST] Model: {self.model}, Temp: {self.temperature}, MaxTokens: {self.max_tokens}")
            logger.info(f"[BYTEPLUS STANDARD REQUEST] Messages count: {len(messages)}")

            response = requests.post(url, json=payload, headers=headers, timeout=600)

            # Log response status
            logger.info(f"[BYTEPLUS STANDARD RESPONSE] Status: {response.status_code}")

            response.raise_for_status()
            result = response.json()

            logger.info(f"[BYTEPLUS STANDARD RESPONSE] Body: {result}")

            # Non-streaming content location (OpenAI-compatible)
            choices = result.get("choices", [])
            if choices:
                # choices[0].message.content is the OpenAI-compatible field
                content = (
                    choices[0].get("message", {}).get("content")
                    or choices[0].get("delta", {}).get("content", "")
                    or ""
                ).strip()

            total_tokens = int(result.get("usage", {}).get("total_tokens", 0))

            # Token usage (prompt/completion/total)
            usage = result.get("usage") or {}
            token_count_input = int(usage.get("prompt_tokens", 0))
            token_count_output = int(usage.get("completion_tokens", 0))
            status = "success"

        except Exception as exc:  # pragma: no cover
            exc_obj = exc
            logger.error(f"Error calling BytePlus API: {exc}")

        self._log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
        )
        return {
            "tokens_used": total_tokens or 0,
            "content": content or ""
        }

    @profile("llm_anthropic_call", OperationCategory.LLM)
    def _generate_anthropic(
        self, system_prompt: str | None, user_prompt: str, call_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate response using Anthropic with prompt caching.

        Anthropic's prompt caching uses `cache_control` markers on content blocks.
        When the system prompt is long enough (≥1024 tokens), we enable caching.

        TTL Options:
        - Default (5 minutes): Free, uses "ephemeral" type
        - Extended (1 hour): When call_type is provided, uses extended TTL for better
          cache hit rates when alternating between different call types.
          Note: Extended TTL cache writes cost 100% more, but reads are 90% cheaper.

        Args:
            system_prompt: The system prompt (cached when long enough).
            user_prompt: The user prompt for this request.
            call_type: Optional call type (e.g., "reasoning", "action_selection").
                       When provided, uses extended 1-hour TTL for better cache hit rates.

        Cache hits are logged when `cache_read_input_tokens` > 0 in the response.
        """
        token_count_input = token_count_output = 0
        total_tokens = 0
        cached_tokens = 0
        status = "failed"
        content: Optional[str] = None
        exc_obj: Optional[Exception] = None
        config = get_cache_config()
        cache_type = f"ephemeral_{call_type}" if call_type else "ephemeral"

        try:
            if not self._anthropic_client:
                raise RuntimeError("Anthropic client was not initialised.")

            # Always enable JSON mode via prefilling
            json_mode = True

            # Build the message with optional system prompt
            messages = [{"role": "user", "content": user_prompt}]
            # For JSON mode, use prefilling to force JSON output
            if json_mode:
                messages.append({"role": "assistant", "content": "{"})

            message_kwargs: Dict[str, Any] = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": messages,
            }

            if system_prompt:
                # Use caching if system prompt is long enough
                if len(system_prompt) >= config.min_cache_tokens:
                    # Format system as list of content blocks with cache_control
                    # Use extended 1-hour TTL when call_type is provided for better
                    # cache hit rates when alternating between different call types
                    cache_control: Dict[str, str] = {"type": "ephemeral"}
                    if call_type:
                        # Extended TTL: cache writes cost 100% more, reads 90% cheaper
                        # Better for alternating call types where 5-minute TTL might expire
                        cache_control["ttl"] = "1h"
                        logger.debug(f"[ANTHROPIC] Using 1-hour TTL for call_type: {call_type}")

                    message_kwargs["system"] = [
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": cache_control,
                        }
                    ]
                else:
                    # Short prompt - use simple string format (no caching)
                    message_kwargs["system"] = system_prompt

            # Always pass temperature for Anthropic (their default is 1.0, not 0.0)
            message_kwargs["temperature"] = self.temperature

            response = self._anthropic_client.messages.create(**message_kwargs)

            # Extract content from the response
            content = ""
            for block in response.content:
                if block.type == "text":
                    content += block.text

            content = content.strip()

            # If using JSON mode prefilling, prepend the '{' that was used as prefill
            if json_mode:
                content = "{" + content

            # Token usage from Anthropic response
            token_count_input = response.usage.input_tokens
            token_count_output = response.usage.output_tokens
            total_tokens = token_count_input + token_count_output

            # Log cache stats if available (Anthropic returns cache info in usage)
            # cache_creation_input_tokens: tokens written to cache (first call)
            # cache_read_input_tokens: tokens read from cache (subsequent calls)
            cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            cached_tokens = cache_creation + cache_read

            # Record metrics
            metrics = get_cache_metrics()
            if cache_read > 0:
                logger.info(f"[CACHE] Anthropic {cache_type} cache hit: {cache_read}/{token_count_input} tokens from cache")
                metrics.record_hit("anthropic", cache_type, cached_tokens=cache_read, total_tokens=token_count_input)
            elif cache_creation > 0:
                logger.info(f"[CACHE] Anthropic {cache_type} cache created: {cache_creation} tokens cached")
                # Cache creation is a "miss" for the current call but sets up future hits
                metrics.record_miss("anthropic", cache_type, total_tokens=token_count_input)
            elif system_prompt and len(system_prompt) >= config.min_cache_tokens:
                # Caching was attempted but no cache info returned - unexpected
                metrics.record_miss("anthropic", cache_type, total_tokens=token_count_input)

            status = "success"

        except Exception as exc:  # pragma: no cover
            exc_obj = exc
            logger.error(f"Error calling Anthropic API: {exc}")

        self._log_to_db(
            system_prompt,
            user_prompt,
            content if content is not None else str(exc_obj),
            status,
            token_count_input,
            token_count_output,
        )
        return {
            "tokens_used": total_tokens or 0,
            "content": content or "",
            "cached_tokens": cached_tokens,
        }

    # ─────────────────── Internal utilities ───────────────────
    @profile("llm_log_to_db", OperationCategory.DATABASE)
    def _log_to_db(
        self,
        system_prompt: str | None,
        user_prompt: str,
        output: str,
        status: str,
        token_count_input: int,
        token_count_output: int,
    ) -> None:
        """Persist prompt/response metadata using the optional `db_interface`."""
        if not self.db_interface:
            return

        input_data: Dict[str, Optional[str]] = {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }
        config: Dict[str, Any] = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        self.db_interface.log_prompt(
            input_data=input_data,
            output=output,
            provider=self.provider,
            model=self.model,
            config=config,
            status=status,
            token_count_input=token_count_input,
            token_count_output=token_count_output,
        )

    # ─────────────────── CLI helper for ad‑hoc testing ───────────────────
    def _cli(self) -> None:  # pragma: no cover
        """Run a quick interactive shell for manual testing."""
        logger.debug(
            "Provider: {provider!r}, model: {model!r}",
            provider=self.provider,
            model=self.model,
        )
        while True:
            user_prompt = input("\nEnter prompt (or 'exit'): ").strip()
            if user_prompt.lower() in {"exit", "quit"}:
                break
            response = self.generate_response(user_prompt=user_prompt)
            logger.debug(f"AI Response:\n{response}\n")