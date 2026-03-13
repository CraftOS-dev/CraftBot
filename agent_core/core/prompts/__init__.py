# -*- coding: utf-8 -*-
"""
Shared prompts for agent_core.

This module contains prompt templates that are shared across all agent runtimes.
Runtimes can override specific prompts using the PromptRegistry.
"""

# Registry for prompt overrides
from agent_core.core.prompts.registry import (
    PromptRegistry,
    prompt_registry,
    get_prompt,
    register_prompt,
)

# Event Stream summarization prompt
EVENT_STREAM_SUMMARIZATION_PROMPT = """
<objective>
You are summarizing an autonomous agent's per-session event log to reduce token usage while preserving
ALL information that is operationally important for downstream decisions.
</objective>

<rules>
- Produce a NEW_HEAD_SUMMARY that integrates the PREVIOUS_HEAD_SUMMARY with the OLDEST_EVENTS_CHUNK.
- Keep only durable, decision-relevant facts:
  • final outcomes of tasks/actions and their statuses
  • unresolved items / pending follow-ups / timers / next steps
  • notable errors/warnings and their last known state
  • key entities (files/URLs/IDs/emails/app names) that may be referenced later
  • meaningful metrics/counters if they affect decisions
- Remove noise, duplicates, transient progress messages, or low-value chatter.
- Prefer concise bullets; keep it readable and compact (aim ~400–800 words).
- Do NOT include the recent (unsummarized) tail; we only rewrite the head summary.
</rules>

---

<context>
Time window of events to roll up: {window}

You are given:
1) The PREVIOUS_HEAD_SUMMARY (accumulated summary of older events).
2) The OLDEST_EVENTS_CHUNK (events now being rolled up).
</context>

<previous_head_summary>
{previous_summary}
</previous_head_summary>

<events>
OLDEST_EVENTS_CHUNK (compact lines):

{compact_lines}
</events>

<output_format>
Output ONLY the NEW_HEAD_SUMMARY as plain text in paragraph (no JSON, no preface, no list).
</output_format>
"""

# Action selection prompts
from agent_core.core.prompts.action import (
    SELECT_ACTION_PROMPT,
    SELECT_ACTION_IN_TASK_PROMPT,
    SELECT_ACTION_IN_GUI_PROMPT,
    SELECT_ACTION_IN_SIMPLE_TASK_PROMPT,
    GUI_ACTION_SPACE_PROMPT,
)

# Context prompts
from agent_core.core.prompts.context import (
    AGENT_ROLE_PROMPT,
    AGENT_INFO_PROMPT,
    POLICY_PROMPT,
    USER_PROFILE_PROMPT,
    ENVIRONMENTAL_CONTEXT_PROMPT,
    AGENT_FILE_SYSTEM_CONTEXT_PROMPT,
)

# Routing prompts
from agent_core.core.prompts.routing import (
    ROUTE_TO_SESSION_PROMPT,
)


# GUI prompts
from agent_core.core.prompts.gui import (
    GUI_REASONING_PROMPT,
    GUI_REASONING_PROMPT_OMNIPARSER,
    GUI_QUERY_FOCUSED_PROMPT,
    GUI_PIXEL_POSITION_PROMPT,
)

# Skill selection prompts
from agent_core.core.prompts.skill import (
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
