# -*- coding: utf-8 -*-
"""Render a reasoning default into request fields, one function per transport.

The table and the level policy live in agent_core/core/models/reasoning.py;
this module only knows how each transport spells a ``ReasoningDecision``.
Callers skip these functions entirely when a model has no rule, so a model
without a rule never gains a field here.

A decision whose wire the transport cannot express is a bug in the rules
table (a row filed under the wrong provider), so it raises instead of being
dropped silently. tests/llm/test_reasoning_rules.py checks every row against
``TRANSPORT_WIRES`` so this never reaches production.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Mapping, Tuple

from agent_core.core.models.reasoning import ReasoningDecision, ReasoningWire

#: Reasoning wires each transport (ProviderProfile.wire) can express.
TRANSPORT_WIRES: Mapping[str, FrozenSet[ReasoningWire]] = {
    "chat_completions": frozenset(
        {
            ReasoningWire.EFFORT,
            ReasoningWire.OPENROUTER_EFFORT,
            ReasoningWire.OPENROUTER_BUDGET,
        }
    ),
    "anthropic_messages": frozenset(
        {ReasoningWire.ANTHROPIC_ADAPTIVE, ReasoningWire.ANTHROPIC_BUDGET}
    ),
    "bedrock_converse": frozenset(
        {ReasoningWire.ANTHROPIC_ADAPTIVE, ReasoningWire.ANTHROPIC_BUDGET}
    ),
    "gemini_native": frozenset(
        {ReasoningWire.GEMINI_LEVEL, ReasoningWire.GEMINI_BUDGET}
    ),
}


def _unsupported(decision: ReasoningDecision, transport: str) -> ValueError:
    return ValueError(
        f"Reasoning rule {decision.key!r} uses wire {decision.wire.value!r}, "
        f"which the {transport} transport cannot send. The row is filed under "
        f"the wrong provider in agent_core/core/models/reasoning.py."
    )


def chat_completions_fields(
    decision: ReasoningDecision,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Fields for a Chat Completions request: (top-level kwargs, extra_body)."""
    if decision.wire is ReasoningWire.EFFORT:
        return {"reasoning_effort": decision.level}, {}
    if decision.wire is ReasoningWire.OPENROUTER_EFFORT:
        return {}, {"reasoning": {"effort": decision.level}}
    if decision.wire is ReasoningWire.OPENROUTER_BUDGET:
        return {}, {"reasoning": {"max_tokens": decision.budget_tokens}}
    raise _unsupported(decision, "chat_completions")


def anthropic_fields(decision: ReasoningDecision) -> Dict[str, Any]:
    """Anthropic Messages fields.

    The same dict is the ``additionalModelRequestFields`` of a Bedrock
    Converse request for Claude, which forwards these keys to the model.
    """
    if decision.wire is ReasoningWire.ANTHROPIC_ADAPTIVE:
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": decision.level},
        }
    if decision.wire is ReasoningWire.ANTHROPIC_BUDGET:
        return {
            "thinking": {"type": "enabled", "budget_tokens": decision.budget_tokens}
        }
    raise _unsupported(decision, "anthropic_messages/bedrock_converse")


def gemini_thinking_kwargs(decision: ReasoningDecision) -> Dict[str, Any]:
    """Keyword arguments for the GeminiClient text-generation methods."""
    if decision.wire is ReasoningWire.GEMINI_LEVEL:
        return {"thinking_level": decision.level}
    if decision.wire is ReasoningWire.GEMINI_BUDGET:
        return {"thinking_budget": decision.budget_tokens}
    raise _unsupported(decision, "gemini_native")
