# -*- coding: utf-8 -*-
"""Decorators - re-exports from agent_core."""

from agent_core import (
    profiler,
    profile,
    profile_loop,
    OperationCategory,
    ProfileContext,
    enable_profiling,
    disable_profiling,
    log_events,
)

# Re-export AgentProfiler class for type hints
from agent_core.decorators.profiler import (
    AgentProfiler,
    is_profiling_enabled,
    set_auto_save_interval,
    print_profile_report,
    save_profile_report,
    get_profiler,
    get_profiler_config,
)

__all__ = [
    "profiler",
    "profile",
    "profile_loop",
    "OperationCategory",
    "ProfileContext",
    "AgentProfiler",
    "enable_profiling",
    "disable_profiling",
    "is_profiling_enabled",
    "set_auto_save_interval",
    "print_profile_report",
    "save_profile_report",
    "get_profiler",
    "get_profiler_config",
    "log_events",
]
