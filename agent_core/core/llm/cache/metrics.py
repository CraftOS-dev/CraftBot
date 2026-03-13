# -*- coding: utf-8 -*-
"""
core.llm.cache.metrics

Cache effectiveness metrics tracking for all LLM providers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional


# Logging setup
try:
    from agent_core.utils.logger import logger
except Exception:  # pragma: no cover
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


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
