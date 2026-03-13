# -*- coding: utf-8 -*-
"""
core.llm.cache.gemini

Gemini-specific explicit cache management.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Dict, Optional, TYPE_CHECKING

from .config import get_cache_config

if TYPE_CHECKING:
    from agent_core import GeminiClient


# Logging setup
try:
    from agent_core.utils.logger import logger
except Exception:  # pragma: no cover
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


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

    # Gemini requires at least 1024 tokens for explicit caching
    # Using ~4 characters per token as a rough estimate
    MIN_CACHE_TOKENS = 1024
    CHARS_PER_TOKEN_ESTIMATE = 4

    def __init__(self, gemini_client: "GeminiClient", model: str) -> None:
        self._client = gemini_client
        self._model = model
        # Cache registry: "call_type:prompt_hash" -> cache_name
        self._cache_registry: Dict[str, str] = {}
        # Track cache creation time for TTL management
        self._cache_created_at: Dict[str, float] = {}
        self._config = get_cache_config()

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for a text string.

        Uses a rough estimate of ~4 characters per token for English text.
        This is conservative to avoid hitting the "too small" error.
        """
        return len(text) // self.CHARS_PER_TOKEN_ESTIMATE

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
        # Check if system prompt is large enough for explicit caching
        # Gemini requires at least 1024 tokens; skip explicit cache if too small
        estimated_tokens = self._estimate_tokens(system_prompt)
        if estimated_tokens < self.MIN_CACHE_TOKENS:
            logger.debug(
                f"[GEMINI CACHE] System prompt too small for explicit caching "
                f"({estimated_tokens} estimated tokens < {self.MIN_CACHE_TOKENS} min). "
                f"Using implicit caching instead."
            )
            return self._client.generate_text(
                self._model,
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_output_tokens=max_tokens,
                json_mode=True,
            )

        cache_key = self._make_cache_key(system_prompt, call_type)

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
                        json_mode=True,
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
                    json_mode=True,
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
            json_mode=True,
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
