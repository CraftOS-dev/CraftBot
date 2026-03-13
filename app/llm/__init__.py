# -*- coding: utf-8 -*-
"""
app.llm

LLM interface module providing a unified API for multiple LLM providers.

This module organizes:
- LLMInterface: Main interface class for interacting with LLM providers
- LLMCallType: Enum for session cache keying
- Cache components: Configuration, metrics, and provider-specific cache managers

Usage:
    from app.llm import LLMInterface, LLMCallType

    # Create interface
    llm = LLMInterface(provider="openai")

    # Generate response
    response = llm.generate_response(
        system_prompt="You are a helpful assistant.",
        user_prompt="Hello!"
    )

    # Use session caching
    llm.create_session_cache(task_id, LLMCallType.REASONING, system_prompt)
    response = llm.generate_response_with_session(
        task_id, LLMCallType.REASONING, user_prompt
    )
"""

# Re-export LLMCallType from agent_core
from agent_core import LLMCallType
from .interface import LLMInterface

# Cache components from shared agent_core
from agent_core import (
    CacheConfig,
    CacheMetrics,
    CacheMetricsEntry,
    get_cache_config,
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
    # Cache config
    "CacheConfig",
    "get_cache_config",
    # Cache metrics
    "CacheMetrics",
    "CacheMetricsEntry",
    "get_cache_metrics",
    # BytePlus cache
    "BytePlusCacheManager",
    "BytePlusContextOverflowError",
    "BYTEPLUS_MAX_INPUT_TOKENS",
    # Gemini cache
    "GeminiCacheManager",
]
