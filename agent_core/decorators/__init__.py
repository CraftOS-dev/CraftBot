# -*- coding: utf-8 -*-
"""Decorators for profiling and logging."""

from agent_core.decorators.profiler import (
    AgentProfiler,
    OperationCategory,
    ProfileContext,
    ProfileRecord,
    OperationStats,
    LoopStats,
    profile,
    profile_loop,
    profiler,
    enable_profiling,
    disable_profiling,
    is_profiling_enabled,
    set_auto_save_interval,
    print_profile_report,
    save_profile_report,
    get_profiler,
    get_profiler_config,
)
from agent_core.decorators.log_events import log_events

__all__ = [
    # Profiler classes
    "AgentProfiler",
    "OperationCategory",
    "ProfileContext",
    "ProfileRecord",
    "OperationStats",
    "LoopStats",
    # Profiler decorators
    "profile",
    "profile_loop",
    # Profiler instance
    "profiler",
    # Profiler utilities
    "enable_profiling",
    "disable_profiling",
    "is_profiling_enabled",
    "set_auto_save_interval",
    "print_profile_report",
    "save_profile_report",
    "get_profiler",
    "get_profiler_config",
    # Log events decorator
    "log_events",
]
