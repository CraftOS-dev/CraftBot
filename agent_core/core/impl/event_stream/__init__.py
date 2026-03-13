# -*- coding: utf-8 -*-
"""
Event stream implementation module.

This module provides the EventStream and EventStreamManager implementations,
as well as re-exports Event and EventRecord from the existing location.
"""

# Re-export data classes from existing location
from agent_core.core.event_stream.event import Event, EventRecord

# Implementation classes
from agent_core.core.impl.event_stream.event_stream import (
    EventStream,
    count_tokens,
    get_cached_token_count,
    SEVERITIES,
    MAX_EVENT_INLINE_CHARS,
)
from agent_core.core.impl.event_stream.manager import (
    EventStreamManager,
    SKIP_UNPROCESSED_TASK_NAMES,
    SKIP_UNPROCESSED_EVENT_TYPES,
)

__all__ = [
    # Data classes
    "Event",
    "EventRecord",
    # Implementation classes
    "EventStream",
    "EventStreamManager",
    # Utilities
    "count_tokens",
    "get_cached_token_count",
    # Constants
    "SEVERITIES",
    "MAX_EVENT_INLINE_CHARS",
    "SKIP_UNPROCESSED_TASK_NAMES",
    "SKIP_UNPROCESSED_EVENT_TYPES",
]
