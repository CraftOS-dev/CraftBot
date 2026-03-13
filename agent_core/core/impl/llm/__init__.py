# -*- coding: utf-8 -*-
"""
LLM implementation module.

This module provides the shared LLMInterface class and related types for LLM operations.
The LLMInterface supports hook-based customization for state access and usage reporting.

Runtime-specific wrappers (CraftBot/app/llm/interface.py, CraftBot/app/llm/interface.py)
inject the appropriate hooks for their state management systems.
"""

from agent_core.core.impl.llm.interface import LLMInterface
from agent_core.core.impl.llm.types import LLMCallType

# Cache management components
from agent_core.core.impl.llm.cache import (
    CacheConfig,
    get_cache_config,
    CacheMetrics,
    CacheMetricsEntry,
    get_cache_metrics,
    BytePlusCacheManager,
    BytePlusContextOverflowError,
    BYTEPLUS_MAX_INPUT_TOKENS,
    GeminiCacheManager,
)

__all__ = [
    # Main interface
    "LLMInterface",
    # Types
    "LLMCallType",
    # Cache Config
    "CacheConfig",
    "get_cache_config",
    # Cache Metrics
    "CacheMetrics",
    "CacheMetricsEntry",
    "get_cache_metrics",
    # BytePlus Cache
    "BytePlusCacheManager",
    "BytePlusContextOverflowError",
    "BYTEPLUS_MAX_INPUT_TOKENS",
    # Gemini Cache
    "GeminiCacheManager",
]
