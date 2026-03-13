# -*- coding: utf-8 -*-
"""
State management abstraction layer.

Provides a unified interface for state access that works with both:
- CraftBot's global STATE singleton
- CraftBot's session-based StateSession pattern
"""

from agent_core.core.state.protocols import StateProvider
from agent_core.core.state.base import (
    StateRegistry,
    get_state,
    get_state_or_none,
    get_session,
    get_session_or_none,
)
from agent_core.core.state.session import StateSession
from agent_core.core.state.types import (
    AgentProperties,
    ReasoningResult,
    TaskSummary,
    MainState,
    DEFAULT_MAX_ACTIONS_PER_TASK,
    DEFAULT_MAX_TOKEN_PER_TASK,
)

__all__ = [
    "StateProvider",
    "StateRegistry",
    "get_state",
    "get_state_or_none",
    "get_session",
    "get_session_or_none",
    "StateSession",
    "AgentProperties",
    "ReasoningResult",
    "TaskSummary",
    "MainState",
    "DEFAULT_MAX_ACTIONS_PER_TASK",
    "DEFAULT_MAX_TOKEN_PER_TASK",
]
