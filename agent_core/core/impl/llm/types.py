# -*- coding: utf-8 -*-
"""
Shared types and enums for the LLM interface module.
"""

from __future__ import annotations

from enum import Enum


class LLMCallType(str, Enum):
    """Types of LLM calls for session cache keying.

    Each call type gets its own session cache within a task, so that
    different prompt structures (reasoning vs action selection) don't
    pollute each other's KV cache.
    """
    REASONING = "reasoning"
    ACTION_SELECTION = "action_selection"
    GUI_REASONING = "gui_reasoning"
    GUI_ACTION_SELECTION = "gui_action_selection"
