# -*- coding: utf-8 -*-
"""Render a reasoning decision into request fields, one function per transport.

The table, the choices, and the level policy live in
agent_core/core/models/reasoning.py; this module only knows how each
transport spells a ``ReasoningDecision``. Callers skip these functions
entirely when a model has no rule, so a model without a rule never gains a
field here. A decision that sends nothing (the provider default, or off on a
model whose default is no reasoning) renders as no fields.

A decision whose wire the transport cannot express is a bug in the rules
table (a row filed under the wrong provider, or an explicit off on a wire
without a disable form), so it raises instead of being dropped silently.
tests/llm/test_reasoning_rules.py renders every choice on every row through
its provider's function, so this never reaches production.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from agent_core.core.models.reasoning import ReasoningDecision, ReasoningWire

#: The disable value of the OpenAI-style effort parameter.
EFFORT_OFF = "none"


def _unsupported(decision: ReasoningDecision, transport: str) -> ValueError:
    what = "an explicit off" if decision.off else f"wire {decision.wire.value!r}"
    return ValueError(
        f"Reasoning rule {decision.key!r} asks for {what}, which the "
        f"{transport} transport cannot send. Fix the row in "
        f"agent_core/core/models/reasoning.py."
    )


def chat_completions_fields(
    decision: ReasoningDecision,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Fields for a Chat Completions request: (top-level kwargs, extra_body)."""
    if decision.wire is ReasoningWire.EFFORT:
        if decision.off:
            return {"reasoning_effort": EFFORT_OFF}, {}
        if decision.level is None:
            return {}, {}
        return {"reasoning_effort": decision.level}, {}
    if decision.wire is ReasoningWire.OPENROUTER_EFFORT:
        if decision.off:
            return {}, {"reasoning": {"effort": EFFORT_OFF}}
        if decision.level is None:
            return {}, {}
        return {}, {"reasoning": {"effort": decision.level}}
    if decision.wire is ReasoningWire.OPENROUTER_BUDGET and not decision.off:
        if decision.level is None:
            return {}, {}
        return {}, {"reasoning": {"max_tokens": decision.budget_tokens}}
    raise _unsupported(decision, "chat_completions")


def anthropic_fields(decision: ReasoningDecision) -> Dict[str, Any]:
    """Anthropic Messages fields.

    The same dict is the ``additionalModelRequestFields`` of a Bedrock
    Converse request for Claude, which forwards these keys to the model.
    """
    if decision.wire not in (
        ReasoningWire.ANTHROPIC_ADAPTIVE,
        ReasoningWire.ANTHROPIC_BUDGET,
    ):
        raise _unsupported(decision, "anthropic_messages/bedrock_converse")
    if decision.off:
        return {"thinking": {"type": "disabled"}}
    if decision.level is None:
        return {}
    if decision.wire is ReasoningWire.ANTHROPIC_ADAPTIVE:
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": decision.level},
        }
    return {"thinking": {"type": "enabled", "budget_tokens": decision.budget_tokens}}


def gemini_thinking_kwargs(decision: ReasoningDecision) -> Dict[str, Any]:
    """Keyword arguments for the GeminiClient text-generation methods."""
    if decision.wire is ReasoningWire.GEMINI_BUDGET:
        if decision.off:
            return {"thinking_budget": 0}
        if decision.level is None:
            return {}
        return {"thinking_budget": decision.budget_tokens}
    if decision.wire is ReasoningWire.GEMINI_LEVEL and not decision.off:
        if decision.level is None:
            return {}
        return {"thinking_level": decision.level}
    raise _unsupported(decision, "gemini_native")
