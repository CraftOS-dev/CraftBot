# -*- coding: utf-8 -*-
"""
Centralised prompt registry for CraftBot.

This module re-exports prompts from agent_core for backward compatibility.
All shared prompts are now maintained in agent_core/core/prompts/.
"""

# Re-export all prompts from agent_core
from agent_core import (
    # Registry
    PromptRegistry,
    prompt_registry,
    get_prompt,
    register_prompt,
    # Event stream
    EVENT_STREAM_SUMMARIZATION_PROMPT,
    # Action prompts
    SELECT_ACTION_PROMPT,
    # Context prompts
    AGENT_ROLE_PROMPT,
    AGENT_INFO_PROMPT,
    POLICY_PROMPT,
    USER_PROFILE_PROMPT,
    ENVIRONMENTAL_CONTEXT_PROMPT,
    AGENT_FILE_SYSTEM_CONTEXT_PROMPT,
)

__all__ = [
    # Registry
    "PromptRegistry",
    "prompt_registry",
    "get_prompt",
    "register_prompt",
    # Event stream
    "EVENT_STREAM_SUMMARIZATION_PROMPT",
    # Action prompts
    "SELECT_ACTION_PROMPT",
    # Context prompts
    "AGENT_ROLE_PROMPT",
    "AGENT_INFO_PROMPT",
    "POLICY_PROMPT",
    "USER_PROFILE_PROMPT",
    "ENVIRONMENTAL_CONTEXT_PROMPT",
    "AGENT_FILE_SYSTEM_CONTEXT_PROMPT",
]
