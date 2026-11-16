# -*- coding: utf-8 -*-
"""
SubAgentContextEngine — the context of one sub-agent's decisions.

A sub-agent decides with the main agent's ActionRouter (see
:mod:`app.subagent.runner`); this engine and the two templates below are
what make that router a sub-agent's. The router gets from it:

- the system prompt: the type's own prompt (its definition), the
  externalized-output note when the type has the retrieval actions, and the
  environment with the current DATE. Built once per run, so the cached
  prefix never moves. The router appends SUBAGENT_DECISION_INSTRUCTIONS
  (batching rules, reply format, <actions>).
- the session state: the type and its budget, shown in the first user
  message after the query (SUBAGENT_DECISION_PROMPT).
- the actions: the definition's list (sub_task_end included).
- the event stream: the sub-agent's own (EventStreamContext).

Deliberately absent: persona, soul, user profile, memory, skills, the
capability catalog and anything else of the spawning session. The only
thing a sub-agent knows of its parent is the query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Tuple

from agent_core.core.impl.context.engine import EventStreamContext
from agent_core.core.prompts import ENVIRONMENTAL_CONTEXT_PROMPT
from app.subagent.registry import get_subagent_definition
from app.subagent.types import SubAgent

if TYPE_CHECKING:
    from app.event_stream import EventStreamManager


# The decision instructions ending every sub-agent's system prompt
# (ActionRouter ``instructions``): how to batch, the reply format and the
# type's <actions>. The reply format is the main agent's.
SUBAGENT_DECISION_INSTRUCTIONS = """<parallel_actions>
Batch up to 20 actions in one turn ONLY when none depends on another's output
(e.g. several read_file / grep_files / web_search / web_fetch calls).
A non-parallelizable action MUST be the ONLY action in its turn; sub_task_end
is one.
NEVER batch two write_file/stream_edit actions on the SAME file — they are
planned against one snapshot, so the second's anchor is stale once the first
applies (corrupts the file). Edit the same file in SEPARATE turns.
</parallel_actions>

<output_format>
Return ONLY a valid JSON object with this structure and no extra commentary:
{{
  "reasoning": "<short reasoning about the current state and decision>",
  "actions": [
    {{
      "action_name": "<name of the chosen action>",
      "parameters": {{
        "<parameter name>": <value>
      }}
    }}
  ]
}}

For parallel actions, include multiple entries in the "actions" array.
For a single action, use an array with one entry.
</output_format>

<actions>
Your actions, each with its description and input schema. You cannot use any other:
{action_candidates}
</actions>"""

# The first user message of a sub-agent's session history (ActionRouter
# ``user_prompt``). KV CACHING: the query and the budget are static, the
# event stream is append-only; later turns send only new events.
SUBAGENT_DECISION_PROMPT = """QUERY FROM SPAWNING AGENT:
{query}

{session_state}

{event_stream}

<current_turn>
Reason about where the query stands, then select the next action(s) with
their input parameters, or end with sub_task_end once it is done.
</current_turn>
"""

# Appended to the system prompt of any sub-agent type whose action list
# includes the retrieval pair (grep_files / read_file). Oversized action
# outputs are externalized by the event stream (EventStream._externalize_message)
# into files under the sub-agent's workspace; this note teaches the model the
# retrieval protocol.
_EXTERNALIZED_OUTPUT_NOTE = """EXTERNALIZED OUTPUTS:
When an action's output is very large, your event log will show a pointer
line ("... saved in <file path> ... | keywords: ...") instead of the content.
The full output is in that file — it is NOT lost and you must NOT re-run the
action to get it back. Use grep_files on the file with the listed keywords
(or your own search terms) to pull just the relevant lines; use read_file
with offset/limit only when you need a specific region in full."""

_RETRIEVAL_ACTIONS = ("grep_files", "read_file")


def _render_environment_block() -> str:
    """The environment and current DATE block of a sub-agent's system
    prompt. Date only, no time: a wall-clock time would move the cached
    prefix every turn."""
    import platform
    from datetime import datetime

    from tzlocal import get_localzone

    try:
        from app.config import AGENT_WORKSPACE_ROOT
    except ImportError:
        AGENT_WORKSPACE_ROOT = "."

    local_timezone = get_localzone()
    environment = ENVIRONMENTAL_CONTEXT_PROMPT.format(
        user_location=local_timezone,
        working_directory=AGENT_WORKSPACE_ROOT,
        operating_system=platform.system(),
        os_version=platform.release(),
        os_platform=platform.platform(),
    )
    current_date = f"<current_date>\nCurrent date: {datetime.now(local_timezone).strftime('%Y-%m-%d')}\n</current_date>"
    return f"{environment}\n{current_date}"


class SubAgentContextEngine(EventStreamContext):
    """The context engine of one sub-agent's ActionRouter."""

    def __init__(
        self, sub: SubAgent, event_stream_manager: "EventStreamManager"
    ) -> None:
        self.sub = sub
        self.event_stream_manager = event_stream_manager
        self.definition = get_subagent_definition(sub.agent_type)
        parts = [self.definition.system_prompt.strip()]
        if any(a in sub.compiled_actions for a in _RETRIEVAL_ACTIONS):
            parts.append(_EXTERNALIZED_OUTPUT_NOTE)
        parts.append(_render_environment_block())
        self._system_prompt = "\n\n".join(parts)

    def make_prompt(
        self,
        query: Optional[str] = None,
        expected_format: Optional[str] = None,
        system_flags: Optional[dict] = None,
        user_flags: Optional[dict] = None,
    ) -> Tuple[str, str]:
        """The system prompt, before the decision instructions. A sub-agent's
        has no optional sections, so the flags change nothing; the user
        message is the router's (SUBAGENT_DECISION_PROMPT)."""
        return self._system_prompt, ""

    def get_session_state(self, session_id: Optional[str] = None) -> str:
        """The type and its budget. Models without a stated budget invent
        scarcity: a verifier with 50 turns concluded at turn 8 citing
        'limited turns' (observed 2026-08-05)."""
        definition = self.definition
        return (
            "<subagent>\n"
            f"Type: {definition.name}\n"
            f"Budget: up to {definition.max_iterations} turns and "
            f"{definition.max_wall_seconds // 60} minutes. A turn can batch "
            "several independent actions. Pace yourself by these numbers, not "
            "by guesswork.\n"
            "</subagent>"
        )

    def get_compiled_actions(self, session_id: Optional[str] = None) -> List[str]:
        """The definition's actions, sub_task_end included."""
        return list(self.sub.compiled_actions)


__all__ = [
    "SUBAGENT_DECISION_INSTRUCTIONS",
    "SUBAGENT_DECISION_PROMPT",
    "SubAgentContextEngine",
]
