# -*- coding: utf-8 -*-
"""
app.event_stream

Event stream module for logging and managing agent events.
Re-exports from agent_core.
"""

# Re-export everything from agent_core
from agent_core import (
    Event,
    EventRecord,
    EventStream,
    EventStreamManager,
)

__all__ = [
    "Event",
    "EventRecord",
    "EventStream",
    "EventStreamManager",
]
