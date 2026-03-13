# -*- coding: utf-8 -*-
"""
core.llm.cache.config

Shared cache configuration for all LLM providers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


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
