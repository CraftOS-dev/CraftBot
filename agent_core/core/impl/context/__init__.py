# -*- coding: utf-8 -*-
"""
Context engine implementations.

This module provides the ContextEngine class for building LLM prompts
with hook-based customization for runtime-specific behavior, and the
EventStreamContext it shares with every other context engine (a sub-agent's).
"""

from agent_core.core.impl.context.engine import ContextEngine, EventStreamContext

__all__ = [
    "ContextEngine",
    "EventStreamContext",
]
