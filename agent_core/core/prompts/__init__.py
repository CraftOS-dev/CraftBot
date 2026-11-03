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

# The same fold, asked as one more message on the session's own history (the
# cached conversation that already holds every event being folded), so the
# summary call reads its input from the provider's cache instead of sending
# the folded events again. Same rules; the reply is JSON because the
# session's system prompt and request mode ask for JSON.
EVENT_STREAM_SUMMARY_ON_HISTORY_PROMPT = """
<fold_request>
This message is not a turn of the session: no action runs and nothing is shown
to the user. The oldest part of this session's event log is being replaced by a
summary, so the session can continue in a smaller context.

Write that summary, a NEW_HEAD_SUMMARY covering the event log from its
beginning (including the "Summary of folded event stream" at its top, if there
is one, and every later event and reply in this conversation) through this
event, inclusive:
{last_event}
</fold_request>

<rules>
- Keep only durable, decision-relevant facts:
  • final outcomes of tasks/actions and their statuses
  • unresolved items / pending follow-ups / timers / next steps
  • notable errors/warnings and their last known state
  • key entities (files/URLs/IDs/emails/app names) that may be referenced later
  • meaningful metrics/counters if they affect decisions
- Remove noise, duplicates, transient progress messages, or low-value chatter.
- Prefer concise bullets; keep it readable and compact (aim ~400–800 words).
- Do NOT include anything logged after the event above, the latest
  [requirements] event, or [action_schemas] events: they stay in the log
  verbatim.
</rules>

<output_format>
Return ONLY a JSON object: {{"summary": "<the NEW_HEAD_SUMMARY as plain text>"}}
</output_format>
"""

# Action selection prompts
from agent_core.core.prompts.action import (
    SELECT_ACTION_INSTRUCTIONS,
    SELECT_ACTION_PROMPT,
    decision_system_prompt,
)

# Context prompts
from agent_core.core.prompts.context import (
    AGENT_ROLE_PROMPT,
    AGENT_INFO_PROMPT,
    POLICY_PROMPT,
    USER_PROFILE_PROMPT,
    SOUL_PROMPT,
    ENVIRONMENTAL_CONTEXT_PROMPT,
    CURRENT_DATETIME_PROMPT,
    AGENT_FILE_SYSTEM_CONTEXT_PROMPT,
    LANGUAGE_INSTRUCTION,
)

# Reasoning prompts
from agent_core.core.prompts.reasoning import PROMPT_ENHANCE_REASONING_PROMPT

# Entity-judge pipeline prompts
from agent_core.core.prompts.entity_pipeline import (
    ENTITY_JUDGE_SYSTEM_PROMPT,
    ENTITY_JUDGE_USER_PROMPT,
)

# Sub-agent prompts now live alongside the sub-agent runtime, in
# ``app.subagent.definitions`` (per-type system prompts) and
# ``app.subagent.context_engine`` (shared output-format contract).

__all__ = [
    # Registry
    "PromptRegistry",
    "prompt_registry",
    "get_prompt",
    "register_prompt",
    # Event stream
    "EVENT_STREAM_SUMMARIZATION_PROMPT",
    "EVENT_STREAM_SUMMARY_ON_HISTORY_PROMPT",
    # Action prompts
    "SELECT_ACTION_INSTRUCTIONS",
    "SELECT_ACTION_PROMPT",
    "decision_system_prompt",
    # Context prompts
    "AGENT_ROLE_PROMPT",
    "AGENT_INFO_PROMPT",
    "POLICY_PROMPT",
    "USER_PROFILE_PROMPT",
    "SOUL_PROMPT",
    "ENVIRONMENTAL_CONTEXT_PROMPT",
    "CURRENT_DATETIME_PROMPT",
    "AGENT_FILE_SYSTEM_CONTEXT_PROMPT",
    "LANGUAGE_INSTRUCTION",
    # Reasoning prompts
    "PROMPT_ENHANCE_REASONING_PROMPT",
    # Entity-judge pipeline
    "ENTITY_JUDGE_SYSTEM_PROMPT",
    "ENTITY_JUDGE_USER_PROMPT",
]
