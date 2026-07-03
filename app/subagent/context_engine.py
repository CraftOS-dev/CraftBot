# -*- coding: utf-8 -*-
"""
SubAgentContextEngine — minimal prompt builder for sub-agents.

This is a small, focused replacement for ``ContextEngine.make_prompt()``
that intentionally OMITS:
- agent role / persona prompts
- soul.md
- user profile
- memory retrieval
- selected skills
- environmental context
- conversation history
- main task state / todos
- LANGUAGE_INSTRUCTION

A sub-agent sees only:
- its type-specific system prompt (with the action list and the shared
  output-format contract interpolated)
- its query
- its own per-sub-agent event log snapshot

Prompts are split across three methods so the runner can drive session
caching:

- :meth:`make_system_prompt` — stable across all turns; serves as the
  session-cache "prefix".
- :meth:`make_first_turn_user_prompt` — query + initial event log + nudge.
- :meth:`make_delta_user_prompt` — only the events added since the previous
  turn + nudge. Used on every turn after the first when session caching is
  active.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_core.core.action_framework import format_actions_by_name
from agent_core.core.prompts import ENVIRONMENTAL_CONTEXT_PROMPT
from app.subagent.registry import get_subagent_definition
from app.subagent.types import SubAgent

if TYPE_CHECKING:
    from agent_core.core.impl.action.library import ActionLibrary
    from app.event_stream import EventStreamManager


# Shared output-format contract injected into every sub-agent's system
# prompt via the ``{output_format}`` placeholder. This is the wire format
# the runner expects back on every turn — keep it stable.
SUBAGENT_OUTPUT_FORMAT = """\
On every turn you MUST reply with ONLY a JSON object in this exact shape:

{
  "reasoning": "<one short sentence on why you chose this action>",
  "action_name": "<one of the allowed action names below>",
  "parameters": { <input schema for that action> }
}

No prose, no markdown fences, no extra keys. One action per turn.
"""

_DECIDE_NUDGE = "Decide your next action now. Reply with the JSON object only."

# Appended to the system prompt of any sub-agent type whose action list
# includes the retrieval pair (grep_files / read_file). Oversized action
# outputs are externalized by the event stream (EventStream._externalize_message)
# into files under the sub-agent's temp dir; this note teaches the model the
# retrieval protocol. Kept out of SUBAGENT_OUTPUT_FORMAT because it only
# applies when the retrieval actions are actually available.
_EXTERNALIZED_OUTPUT_NOTE = """
EXTERNALIZED OUTPUTS:
When an action's output is very large, your event log will show a pointer
line ("... saved in <file path> ... | keywords: ...") instead of the content.
The full output is in that file — it is NOT lost and you must NOT re-run the
action to get it back. Use grep_files on the file with the listed keywords
(or your own search terms) to pull just the relevant lines; use read_file
with offset/limit only when you need a specific region in full.
"""

_RETRIEVAL_ACTIONS = ("grep_files", "read_file")


def _render_environment_block() -> str:
    """Render a static environment + current-DATE block for the sub-agent
    system prompt. Date only — no time. A date does not change during a
    short-lived sub-agent's run, so it stays byte-stable across all turns and
    keeps the system-prompt prefix cacheable (a wall-clock time would move the
    prefix every turn and break automatic prefix caching).
    """
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


class SubAgentContextEngine:
    """Builds prompt pieces for sub-agent LLM calls."""

    def __init__(
        self,
        action_library: "ActionLibrary",
        event_stream_manager: "EventStreamManager",
    ):
        self.action_library = action_library
        self.event_stream_manager = event_stream_manager

    # ------------------------------------------------------------------
    # System prompt (stable across all turns — session-cache "prefix")
    # ------------------------------------------------------------------

    def make_system_prompt(self, sub: SubAgent) -> str:
        """Build the type-specific system prompt for ``sub``.

        Pulls the template from the registered :class:`SubAgentDefinition`
        and fills in:
        - ``{action_list}`` — compact JSON description of the allowed actions
        - ``{output_format}`` — shared :data:`SUBAGENT_OUTPUT_FORMAT` block

        Stable across all turns of a given sub-agent; suitable as
        ``system_prompt_for_new_session`` when calling
        ``LLMInterface.generate_response_with_session_async``.
        """
        defn = get_subagent_definition(sub.agent_type)
        action_list_str = format_actions_by_name(
            sub.compiled_actions,
            self.action_library,
            on_missing="[SubAgentContextEngine]",
        )
        prompt = defn.system_prompt.format(
            action_list=action_list_str,
            output_format=SUBAGENT_OUTPUT_FORMAT,
        )
        if any(a in sub.compiled_actions for a in _RETRIEVAL_ACTIONS):
            prompt += _EXTERNALIZED_OUTPUT_NOTE
        prompt += f"\n{_render_environment_block()}"
        return prompt

    # ------------------------------------------------------------------
    # User prompts
    # ------------------------------------------------------------------

    def make_first_turn_user_prompt(self, sub: SubAgent) -> str:
        """First-turn user prompt: query + initial event log + decision nudge."""
        event_log = self._snapshot_event_log(sub.id)
        return (
            f"QUERY FROM SPAWNING AGENT:\n{sub.query}\n\n"
            f"YOUR EVENT LOG SO FAR (most recent last):\n{event_log}\n\n"
            f"{_DECIDE_NUDGE}"
        )

    def make_delta_user_prompt(self, delta_events: str) -> str:
        """Subsequent-turn user prompt: only the new events + decision nudge.

        Used when session caching is active and the LLM interface has the
        prior conversation cached server-side. The original query and earlier
        event log are already in the cached history; we only need to append
        what's new.
        """
        body = delta_events.strip() or "(no new events since last turn)"
        return f"NEW EVENTS SINCE LAST TURN:\n{body}\n\n{_DECIDE_NUDGE}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _snapshot_event_log(self, sub_id: str) -> str:
        return (
            self.event_stream_manager.snapshot_by_id(sub_id, include_summary=True)
            or "(no events yet)"
        )


__all__ = ["SubAgentContextEngine", "SUBAGENT_OUTPUT_FORMAT"]
