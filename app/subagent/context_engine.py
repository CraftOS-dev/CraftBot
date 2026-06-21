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
- its type-specific system prompt (with the action list interpolated)
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
from agent_core.core.prompts import (
    get_prompt,
    RESEARCH_AGENT_SYSTEM_PROMPT,
    VALIDATION_AGENT_SYSTEM_PROMPT,
    SUBAGENT_OUTPUT_FORMAT,
)
from app.subagent.types import SubAgent, get_subagent_config

if TYPE_CHECKING:
    from agent_core.core.impl.action.library import ActionLibrary
    from app.event_stream import EventStreamManager


# Default prompt text indexed by registry key. ``get_prompt(key, default)``
# returns whichever ``PromptRegistry`` has registered for ``key``, falling
# back to the value here when nothing is registered.
_DEFAULT_PROMPTS = {
    "RESEARCH_AGENT_SYSTEM_PROMPT": RESEARCH_AGENT_SYSTEM_PROMPT,
    "VALIDATION_AGENT_SYSTEM_PROMPT": VALIDATION_AGENT_SYSTEM_PROMPT,
}


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

        Stable across all turns of a given sub-agent. Suitable as the
        ``system_prompt_for_new_session`` argument when calling
        ``LLMInterface.generate_response_with_session_async``.
        """
        cfg = get_subagent_config(sub.agent_type)
        key = cfg["system_prompt_key"]
        template = get_prompt(key, default=_DEFAULT_PROMPTS.get(key, ""))
        if not template:
            raise RuntimeError(
                f"No system prompt registered for sub-agent type "
                f"{sub.agent_type!r} (registry key {key!r})."
            )

        # Compact action list, same format as ActionRouter._format_candidates.
        action_list_str = format_actions_by_name(
            sub.compiled_actions,
            self.action_library,
            on_missing="[SubAgentContextEngine]",
        )

        return template.format(
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


__all__ = ["SubAgentContextEngine"]
