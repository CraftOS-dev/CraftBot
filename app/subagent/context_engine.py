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
        return defn.system_prompt.format(
            action_list=action_list_str,
            output_format=SUBAGENT_OUTPUT_FORMAT,
        )

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
        return (
            f"NEW EVENTS SINCE LAST TURN:\n{body}\n\n"
            f"{_DECIDE_NUDGE}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _snapshot_event_log(self, sub_id: str) -> str:
        return (
            self.event_stream_manager.snapshot_by_id(sub_id, include_summary=True)
            or "(no events yet)"
        )


__all__ = ["SubAgentContextEngine", "SUBAGENT_OUTPUT_FORMAT"]
