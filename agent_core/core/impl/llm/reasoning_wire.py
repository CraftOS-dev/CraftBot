# -*- coding: utf-8 -*-
"""Apply a reasoning decision to one request, one function per transport.

The table, the choices, and the level policy live in
agent_core/core/models/reasoning.py; this module only knows how each
transport carries a ``ReasoningDecision``. The interface resolves the
decision once per request and hands the same decision to its context-window
check and to the transport, whose ``for_*`` function below turns it into the
request's output cap, temperature permission, and reasoning fields.

A request without a decision (the model has no rule) keeps the transport's
own cap and temperature and gains no field, so its payload is exactly the
one sent before per-model rules existed. A decision that sends nothing (the
provider default, or off on a model whose default is no reasoning) renders
as no fields.

A decision whose wire the transport cannot express is a bug in the rules
table (a row filed under the wrong provider, or an explicit off on a wire
without a disable form), so it raises instead of being dropped silently.
tests/llm/test_reasoning_rules.py renders every choice on every row through
its provider's function, so this never reaches production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Generic, Optional, Tuple, TypeVar

from agent_core.core.models.reasoning import ReasoningDecision, ReasoningWire

#: The disable value of the OpenAI-style effort parameter.
EFFORT_OFF = "none"

FieldsT = TypeVar("FieldsT")


@dataclass(frozen=True)
class RequestReasoning(Generic[FieldsT]):
    """How one request carries its reasoning decision on one transport."""

    #: Output-token cap: the transport's own cap, raised while reasoning
    #: (reasoning tokens count against it), never lowered.
    output_cap: int
    #: Whether the request may carry an explicit temperature.
    send_temperature: bool
    #: The transport's reasoning fields; empty when nothing is sent.
    fields: FieldsT


def _for_request(
    decision: Optional[ReasoningDecision],
    base_cap: int,
    render: Callable[[ReasoningDecision], FieldsT],
    no_fields: FieldsT,
) -> RequestReasoning[FieldsT]:
    if decision is None:
        return RequestReasoning(base_cap, True, no_fields)
    return RequestReasoning(
        output_cap=decision.output_cap(base_cap),
        send_temperature=not decision.omit_temperature,
        fields=render(decision),
    )


def for_chat_completions(
    decision: Optional[ReasoningDecision], base_cap: int
) -> RequestReasoning[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Chat Completions; fields are (top-level kwargs, extra_body)."""
    return _for_request(decision, base_cap, chat_completions_fields, ({}, {}))


def for_anthropic(
    decision: Optional[ReasoningDecision], base_cap: int
) -> RequestReasoning[Dict[str, Any]]:
    """Anthropic Messages, and Claude on Bedrock Converse."""
    return _for_request(decision, base_cap, anthropic_fields, {})


def for_gemini(
    decision: Optional[ReasoningDecision], base_cap: int
) -> RequestReasoning[Dict[str, Any]]:
    """Gemini generateContent; fields are GeminiClient keyword arguments."""
    return _for_request(decision, base_cap, gemini_thinking_kwargs, {})


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
