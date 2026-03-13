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
    SELECT_ACTION_IN_TASK_PROMPT,
    SELECT_ACTION_IN_GUI_PROMPT,
    SELECT_ACTION_IN_SIMPLE_TASK_PROMPT,
    GUI_ACTION_SPACE_PROMPT,
    # Context prompts
    AGENT_ROLE_PROMPT,
    AGENT_INFO_PROMPT,
    POLICY_PROMPT,
    USER_PROFILE_PROMPT,
    ENVIRONMENTAL_CONTEXT_PROMPT,
    AGENT_FILE_SYSTEM_CONTEXT_PROMPT,
    # Routing prompts
    ROUTE_TO_SESSION_PROMPT,
    # GUI prompts
    GUI_REASONING_PROMPT,
    GUI_REASONING_PROMPT_OMNIPARSER,
    GUI_QUERY_FOCUSED_PROMPT,
    GUI_PIXEL_POSITION_PROMPT,
    # Skill selection prompts
    SKILLS_AND_ACTION_SETS_SELECTION_PROMPT,
    SKILL_SELECTION_PROMPT,
    ACTION_SET_SELECTION_PROMPT,
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
    "SELECT_ACTION_IN_TASK_PROMPT",
    "SELECT_ACTION_IN_GUI_PROMPT",
    "SELECT_ACTION_IN_SIMPLE_TASK_PROMPT",
    "GUI_ACTION_SPACE_PROMPT",
    # Context prompts
    "AGENT_ROLE_PROMPT",
    "AGENT_INFO_PROMPT",
    "POLICY_PROMPT",
    "USER_PROFILE_PROMPT",
    "ENVIRONMENTAL_CONTEXT_PROMPT",
    "AGENT_FILE_SYSTEM_CONTEXT_PROMPT",
    # Routing prompts
    "ROUTE_TO_SESSION_PROMPT",
    # GUI prompts
    "GUI_REASONING_PROMPT",
    "GUI_REASONING_PROMPT_OMNIPARSER",
    "GUI_QUERY_FOCUSED_PROMPT",
    "GUI_PIXEL_POSITION_PROMPT",
    # Skill selection prompts
    "SKILLS_AND_ACTION_SETS_SELECTION_PROMPT",
    "SKILL_SELECTION_PROMPT",
    "ACTION_SET_SELECTION_PROMPT",
]
