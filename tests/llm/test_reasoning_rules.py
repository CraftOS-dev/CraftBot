# -*- coding: utf-8 -*-
"""Per-model reasoning, chosen per chat session (agent_core/core/models/reasoning.py).

Five layers:

1. The table: every row is well formed, uses only the levels its wire can
   carry, and renders every possible choice through its provider's
   transport without error.
2. The choice policy: the default level (one level below the strongest,
   never above "high", never below the provider's own default), where new
   sessions start, pi-style clamping of a
   choice the model lacks, provider default, off, and the temperature and
   output-cap consequences of each.
3. Wire rendering: each decision becomes exactly its provider's fields.
4. The transports at CraftBot's real settings (max_tokens 8000), driven by a
   bound session's choice or a per-call choice; a model without a rule is
   untouched (the golden unruled_* snapshots additionally pin those payloads
   byte for byte).
5. Session plumbing: the stored choice, the session binding through sync
   actions, and the picker's WebSocket handlers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from agent_core.core.impl.action.executor import _atomic_action_internal_async
from agent_core.core.impl.llm import reasoning_wire
from agent_core.core.impl.llm.interface import LLMContextOverflowError
from agent_core.core.impl.session.manager import SessionManager
from agent_core.core.llm.google_gemini_client import _thinking_config
from agent_core.core.models.chatgpt_subscription_client import _translate_request
from agent_core.core.models.reasoning import (
    BUDGET_RUNGS,
    BUDGET_WIRES,
    CHOICE_LADDER,
    LEVEL_CEILING,
    REASONING_RULES,
    ReasoningChoice,
    ReasoningDecision,
    ReasoningRule,
    ReasoningWire,
    clamp_choice,
    reasoning_options,
    resolve_reasoning,
    default_choice,
    default_level,
)
from agent_core.core.models.registry import get_registry
from agent_core.core.session.session import Session
from agent_core.core.state.session import StateSession

from .golden.conftest import GOLDEN_SYSTEM_PROMPT, build_interface

C = ReasoningChoice

#: The Anthropic SDK refuses non-streaming requests above this max_tokens.
ANTHROPIC_NON_STREAMING_CEILING = 21_333
#: Anthropic and OpenRouter reject thinking budgets below this.
MIN_THINKING_BUDGET = 1_024
#: CraftBot's app-level LLMInterface output cap (app/llm/interface.py).
APP_MAX_TOKENS = 8_000


def _provider(surface: str) -> str:
    return "openai" if surface == "openai_subscription" else surface


def _auth_mode(surface: str) -> str:
    return "subscription" if surface == "openai_subscription" else "api_key"


def _resolve_default(provider, model, auth_mode="api_key"):
    """The decision for a session holding the model's default choice."""
    return resolve_reasoning(
        provider, model, auth_mode, default_choice(provider, model, auth_mode)
    )


#: Every reasoning level, weakest first (the ladder without "off").
LEVELS = tuple(choice.value for choice in CHOICE_LADDER[1:])


ROWS = [
    (surface, model, rule)
    for surface, rows in REASONING_RULES.items()
    for model, rule in rows.items()
]
ROW_IDS = [f"{surface}/{model}" for surface, model, _ in ROWS]

_RENDERERS = {
    "chat_completions": reasoning_wire.chat_completions_fields,
    "anthropic_messages": reasoning_wire.anthropic_fields,
    "bedrock_converse": reasoning_wire.anthropic_fields,
    "gemini_native": reasoning_wire.gemini_thinking_kwargs,
}


# ─────────────────────────────── 1. the table ───────────────────────────────


@pytest.mark.parametrize("surface, model, rule", ROWS, ids=ROW_IDS)
def test_row_is_well_formed(surface, model, rule):
    assert model == model.strip() and model
    assert rule.levels, "a rule needs at least one level"
    assert len(set(rule.levels)) == len(rule.levels)
    assert all(level in LEVELS for level in rule.levels)
    assert list(rule.levels) == sorted(rule.levels, key=LEVELS.index)
    assert rule.provider_default is None or rule.provider_default in rule.levels
    assert rule.source.startswith("https://")
    assert rule.output_tokens >= 0 and rule.extended_output_tokens >= 0
    if rule.requires_level:
        assert rule.provider_default is not None, "a required level needs a default"
    if rule.wire in BUDGET_WIRES:
        assert rule.levels == BUDGET_RUNGS
        assert len(rule.budgets) == len(rule.levels)
        assert list(rule.budgets) == sorted(set(rule.budgets))
        assert rule.budgets[0] >= MIN_THINKING_BUDGET
        for level in rule.levels:
            # Every rung leaves room for an answer under its own cap.
            assert rule.budget_for(level) < rule.output_tokens_for(level)
    else:
        assert rule.budgets == ()


@pytest.mark.parametrize("surface, model, rule", ROWS, ids=ROW_IDS)
def test_every_choice_renders_on_every_row(surface, model, rule):
    render = _RENDERERS[get_registry().get(_provider(surface)).wire]
    for choice in ReasoningChoice:
        decision = resolve_reasoning(
            _provider(surface), model, _auth_mode(surface), choice
        )
        assert decision.requested is choice
        render(decision)  # raises if the row asks for something unsendable


@pytest.mark.parametrize("surface, model, rule", ROWS, ids=ROW_IDS)
def test_anthropic_caps_stay_below_the_sdk_non_streaming_ceiling(surface, model, rule):
    if rule.wire in (ReasoningWire.ANTHROPIC_ADAPTIVE, ReasoningWire.ANTHROPIC_BUDGET):
        for level in rule.levels:
            assert 0 < rule.output_tokens_for(level) < ANTHROPIC_NON_STREAMING_CEILING


def test_duplicate_model_ids_are_refused():
    from agent_core.core.models import reasoning

    rule = REASONING_RULES["openai"]["gpt-5.2"]
    with pytest.raises(ValueError, match="listed twice"):
        reasoning._surface({"m": rule}, {"m": rule})


def test_subscription_rows_are_exactly_the_models_subscription_auth_runs():
    # Codex requires a level on every request, so a subscription model
    # without a row would run at Codex's fallback, and a row for a model
    # subscription auth never runs would be dead.
    profile = get_registry().get("openai")
    assert set(REASONING_RULES["openai_subscription"]) == set(
        profile.subscription_models
    )
    assert profile.subscription_default_model in profile.subscription_models


def test_subscription_runs_an_unlisted_model_as_the_default(monkeypatch):
    from agent_core.core.models import factory
    from agent_core.core.models.types import InterfaceType

    monkeypatch.setattr(
        factory,
        "_get_oauth_bearer",
        lambda provider: ("token", "https://chatgpt.com/backend-api/codex", {}),
    )
    for requested, runs in (
        ("gpt-6-sol", "gpt-6-sol"),
        ("gpt-5.4", "gpt-6.1-sol"),
        ("gpt-5.2-2025-12-11", "gpt-6.1-sol"),
    ):
        ctx = factory.ModelFactory.create(
            provider="openai", interface=InterfaceType.LLM, model_override=requested
        )
        assert ctx["auth_mode"] == "subscription"
        assert ctx["model"] == runs


# ─────────────────────────────── 2. the policy ──────────────────────────────


@pytest.mark.parametrize(
    "levels, provider_default, expected",
    [
        (("low", "medium", "high"), None, "medium"),
        (("low", "medium", "high", "xhigh"), None, "high"),
        # xhigh would be one below max; the ceiling keeps it at high.
        (("low", "medium", "high", "xhigh", "max"), "medium", "high"),
        (("low", "medium", "high", "max"), "high", "high"),
        # medium would be below the provider's own high: use the strongest.
        (("low", "medium", "high"), "high", "high"),
        (("low", "high", "max"), "max", "max"),
        (("high", "max"), "max", "max"),
        (("low", "high", "max"), "high", "high"),
        (("high",), None, "high"),
        (BUDGET_RUNGS, None, "high"),
        # minimal is selectable but never the default, nor counted for it.
        (("minimal", "low", "medium", "high"), "medium", "medium"),
        (("minimal", "low", "medium", "high"), "minimal", "medium"),
    ],
)
def test_default_level_policy(levels, provider_default, expected):
    rule = ReasoningRule(
        wire=ReasoningWire.EFFORT,
        levels=levels,
        provider_default=provider_default,
        source="https://example.test",
    )
    assert default_level(rule) == expected


@pytest.mark.parametrize("surface, model, rule", ROWS, ids=ROW_IDS)
def test_default_resolves_within_the_policy_on_every_row(surface, model, rule):
    decision = _resolve_default(_provider(surface), model, _auth_mode(surface))
    assert decision is not None
    assert decision.key == f"{surface}/{model}"
    assert decision.choice is decision.requested and not decision.off
    assert decision.requested is C(decision.level)
    ladder = [level for level in rule.levels if level != "minimal"]
    chosen = ladder.index(decision.level)
    if rule.provider_default in ladder:
        # Never weaker than what the provider applies when it is omitted.
        assert chosen >= ladder.index(rule.provider_default)
    if LEVEL_CEILING in ladder and chosen > ladder.index(LEVEL_CEILING):
        # Above the ceiling only when the provider's own default already is.
        assert ladder.index(rule.provider_default) > ladder.index(LEVEL_CEILING)
        assert chosen == len(ladder) - 1
    if decision.budget_tokens is not None:
        assert decision.budget_tokens < decision.output_tokens


@pytest.mark.parametrize(
    "provider, model, auth_mode, expected",
    [
        ("openai", "gpt-5.2-2025-12-11", "api_key", "high"),  # CraftBot's default
        ("openai", "gpt-5.1", "api_key", "medium"),
        ("openai", "gpt-5", "api_key", "medium"),
        ("openai", "gpt-6-sol", "api_key", "high"),  # never xhigh/max
        ("openai", "gpt-5.5", "subscription", "high"),
        ("openai", "gpt-6.1-sol", "subscription", "high"),
        ("anthropic", "claude-sonnet-4-6", "api_key", "high"),
        ("anthropic", "claude-opus-5-5", "api_key", "high"),
        ("anthropic", "claude-fable-5-1", "api_key", "high"),
        ("openrouter", "openai/gpt-5.2", "api_key", "high"),
        ("gemini", "gemini-3.5-flash", "api_key", "medium"),
        ("gemini", "gemini-3.1-pro-preview", "api_key", "high"),
        ("gemini", "gemini-3-flash-preview", "api_key", "high"),
        ("grok", "grok-4.3", "api_key", "high"),
        ("grok", "grok-4.5", "api_key", "high"),
        ("grok", "grok-4.7", "api_key", "high"),
        ("deepseek", "deepseek-flash", "api_key", "high"),
        ("glm", "glm-5.3", "api_key", "max"),
        ("glm", "glm-5.2", "api_key", "max"),
        ("moonshot", "kimi-k3", "api_key", "max"),
        ("groq", "openai/gpt-oss-120b", "api_key", "medium"),
        ("cerebras", "gpt-oss-120b", "api_key", "medium"),
    ],
)
def test_default_levels(provider, model, auth_mode, expected):
    assert _resolve_default(provider, model, auth_mode).level == expected


@pytest.mark.parametrize(
    "provider, model, budget",
    [
        ("anthropic", "claude-haiku-4-5-20251001", 12_288),
        ("bedrock", "us.anthropic.claude-haiku-4-5-20251001-v1:0", 12_288),
        ("openrouter", "anthropic/claude-sonnet-4.5", 12_288),
        ("gemini", "gemini-2.5-pro", 24_576),
        ("gemini", "gemini-2.5-flash", 18_432),
    ],
)
def test_budget_models_default_to_the_high_rung(provider, model, budget):
    decision = _resolve_default(provider, model)
    assert decision.level == "high"
    assert decision.budget_tokens == budget


@pytest.mark.parametrize(
    "provider, model, requested, effective",
    [
        # pi's clampThinkingLevel: nearest available at or above, else below.
        ("openai", "gpt-5.2", C.MAX, C.XHIGH),
        ("openai", "gpt-5.2", C.MINIMAL, C.LOW),
        ("openai", "gpt-5.2", C.OFF, C.OFF),
        ("openai", "gpt-5", C.OFF, C.MINIMAL),
        ("openai", "gpt-5", C.XHIGH, C.HIGH),
        ("openai", "gpt-6.1-sol", C.OFF, C.LOW),
        ("anthropic", "claude-sonnet-4-5", C.XHIGH, C.MAX),
        ("anthropic", "claude-opus-5-5", C.OFF, C.LOW),
        ("gemini", "gemini-3.1-pro-preview", C.MINIMAL, C.LOW),
        ("gemini", "gemini-2.5-pro", C.OFF, C.LOW),
        ("glm", "glm-5.2", C.LOW, C.HIGH),
        ("grok", "grok-4.5", C.OFF, C.LOW),
        ("grok", "grok-4.5", C.XHIGH, C.HIGH),
        # Meta-choices are never clamped, except provider_default on a model
        # whose default is no reasoning, where it IS off.
        ("openai", "gpt-5.5", C.PROVIDER_DEFAULT, C.PROVIDER_DEFAULT),
        ("openai", "gpt-5.2", C.PROVIDER_DEFAULT, C.OFF),
    ],
)
def test_choices_clamp_like_pi(provider, model, requested, effective):
    decision = resolve_reasoning(provider, model, "api_key", requested)
    assert decision.requested is requested
    assert decision.choice is effective
    assert clamp_choice(REASONING_RULES[provider][model], requested) is effective


def test_off_sends_nothing_where_the_default_is_no_reasoning():
    decision = resolve_reasoning("openai", "gpt-5.2", "api_key", C.OFF)
    assert decision.level is None and not decision.off
    assert decision.output_tokens == 0


def test_off_sends_the_disable_form_where_the_model_thinks_by_default():
    decision = resolve_reasoning("openai", "gpt-5.5", "api_key", C.OFF)
    assert decision.off and decision.level is None
    assert decision.output_tokens == 0


def test_provider_default_on_a_model_that_thinks_by_default():
    decision = resolve_reasoning("openai", "gpt-5.5", "api_key", C.PROVIDER_DEFAULT)
    assert decision.level is None and not decision.off
    # It reasons (at the provider's medium), so it needs the room of a
    # reasoning request.
    assert decision.output_tokens == 32_000


def test_temperature_is_dropped_exactly_while_the_request_reasons():
    # OpenRouter forwards an explicit temperature upstream, where reasoning
    # rejects it; without reasoning it is accepted.
    reasoning = resolve_reasoning(
        "openrouter", "openai/gpt-5.5", "api_key", C.PROVIDER_DEFAULT
    )
    assert reasoning.level is None and reasoning.omit_temperature
    off = resolve_reasoning("openrouter", "openai/gpt-5.5", "api_key", C.OFF)
    assert off.off and not off.omit_temperature


def test_provider_default_sends_the_documented_level_where_one_is_required():
    decision = resolve_reasoning(
        "openai", "gpt-6.1-sol", "subscription", C.PROVIDER_DEFAULT
    )
    assert decision.level == "low"


def test_claude_47_rejects_temperature_even_without_thinking():
    decision = resolve_reasoning("anthropic", "claude-opus-4-7", "api_key", C.OFF)
    assert decision.level is None and not decision.off
    assert decision.omit_temperature


def test_claude_46_keeps_temperature_when_not_thinking():
    decision = resolve_reasoning("anthropic", "claude-sonnet-4-6", "api_key", C.OFF)
    assert not decision.omit_temperature


def test_extended_levels_get_the_extended_cap():
    assert (
        resolve_reasoning("openai", "gpt-5.2", "api_key", C.XHIGH).output_tokens
        == 64_000
    )
    assert (
        resolve_reasoning("openai", "gpt-5.2", "api_key", C.HIGH).output_tokens
        == 32_000
    )
    # Anthropic stays under the SDK's non-streaming ceiling at every level.
    assert (
        resolve_reasoning(
            "anthropic", "claude-opus-4-8", "api_key", C.MAX
        ).output_tokens
        == 21_000
    )


@pytest.mark.parametrize(
    "provider, model, auth_mode",
    [
        ("openai", "gpt-4o", "api_key"),
        ("openai", "gpt-5.2", "subscription"),  # not in the Codex catalogue
        ("openai", "GPT-5.2", "api_key"),  # ids are exact
        ("openai", " gpt-5.2", "api_key"),
        ("openai", "gpt-5.2-pro", "api_key"),
        ("grok", "grok-3", "api_key"),
        ("mistral", "mistral-large-latest", "api_key"),
        ("qwen", "qwen-max", "api_key"),
        ("remote", "llama3.2:3b", "api_key"),
        ("", "gpt-5.2", "api_key"),
        ("openai", None, "api_key"),
        (None, "gpt-5.2", "api_key"),
    ],
)
def test_models_without_a_rule_resolve_to_none(provider, model, auth_mode):
    for choice in ReasoningChoice:
        assert resolve_reasoning(provider, model, auth_mode, choice) is None
    assert reasoning_options(provider, model, auth_mode) is None


def test_options_offer_what_the_model_accepts():
    gpt52 = reasoning_options("openai", "gpt-5.2-2025-12-11", "api_key")
    # Omitting the parameter is off on gpt-5.2: no separate provider default.
    assert gpt52.choices == (C.OFF, C.LOW, C.MEDIUM, C.HIGH, C.XHIGH)
    assert gpt52.default_level == "high"
    assert gpt52.provider_default == "off"
    assert set(gpt52.resolution) == set(ReasoningChoice)

    gpt55 = reasoning_options("openai", "gpt-5.5", "api_key")
    assert gpt55.choices[:2] == (C.PROVIDER_DEFAULT, C.OFF)
    assert gpt55.provider_default == "medium"

    pro = reasoning_options("gemini", "gemini-2.5-pro", "api_key")
    assert pro.choices == (C.PROVIDER_DEFAULT, C.LOW, C.MEDIUM, C.HIGH, C.MAX)
    assert pro.provider_default == "dynamic"


def test_output_cap_never_lowers_the_callers_cap():
    decision = _resolve_default("openai", "gpt-5.2")
    assert decision.output_cap(APP_MAX_TOKENS) == 32_000
    assert decision.output_cap(50_000) == 50_000


# ─────────────────────────────── 3. rendering ───────────────────────────────


def _decision(wire, level="high", budget=None, off=False):
    return ReasoningDecision(
        key="test/model",
        requested=C.HIGH,
        choice=C.OFF if off else C.HIGH,
        wire=wire,
        level=level,
        budget_tokens=budget,
        off=off,
        output_tokens=0,
        omit_temperature=False,
    )


def test_chat_completions_fields():
    render = reasoning_wire.chat_completions_fields
    assert render(_decision(ReasoningWire.EFFORT)) == ({"reasoning_effort": "high"}, {})
    assert render(_decision(ReasoningWire.EFFORT, level=None, off=True)) == (
        {"reasoning_effort": "none"},
        {},
    )
    assert render(_decision(ReasoningWire.EFFORT, level=None)) == ({}, {})
    assert render(_decision(ReasoningWire.OPENROUTER_EFFORT)) == (
        {},
        {"reasoning": {"effort": "high"}},
    )
    assert render(_decision(ReasoningWire.OPENROUTER_EFFORT, level=None, off=True)) == (
        {},
        {"reasoning": {"effort": "none"}},
    )
    assert render(_decision(ReasoningWire.OPENROUTER_BUDGET, budget=12_288)) == (
        {},
        {"reasoning": {"max_tokens": 12_288}},
    )


def test_anthropic_fields():
    render = reasoning_wire.anthropic_fields
    assert render(_decision(ReasoningWire.ANTHROPIC_ADAPTIVE)) == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }
    assert render(_decision(ReasoningWire.ANTHROPIC_BUDGET, budget=12_288)) == {
        "thinking": {"type": "enabled", "budget_tokens": 12_288}
    }
    assert render(
        _decision(ReasoningWire.ANTHROPIC_ADAPTIVE, level=None, off=True)
    ) == {"thinking": {"type": "disabled"}}
    assert render(_decision(ReasoningWire.ANTHROPIC_ADAPTIVE, level=None)) == {}


def test_gemini_thinking_kwargs():
    render = reasoning_wire.gemini_thinking_kwargs
    assert render(_decision(ReasoningWire.GEMINI_LEVEL, level="medium")) == {
        "thinking_level": "medium"
    }
    assert render(_decision(ReasoningWire.GEMINI_BUDGET, budget=24_576)) == {
        "thinking_budget": 24_576
    }
    assert render(_decision(ReasoningWire.GEMINI_BUDGET, level=None, off=True)) == {
        "thinking_budget": 0
    }
    assert render(_decision(ReasoningWire.GEMINI_LEVEL, level=None)) == {}


@pytest.mark.parametrize(
    "render, decision",
    [
        (
            reasoning_wire.chat_completions_fields,
            _decision(ReasoningWire.ANTHROPIC_ADAPTIVE),
        ),
        (reasoning_wire.anthropic_fields, _decision(ReasoningWire.EFFORT)),
        (
            reasoning_wire.gemini_thinking_kwargs,
            _decision(ReasoningWire.OPENROUTER_EFFORT),
        ),
        # Wires without a disable form.
        (
            reasoning_wire.gemini_thinking_kwargs,
            _decision(ReasoningWire.GEMINI_LEVEL, level=None, off=True),
        ),
        (
            reasoning_wire.chat_completions_fields,
            _decision(ReasoningWire.OPENROUTER_BUDGET, level=None, off=True),
        ),
    ],
)
def test_what_a_transport_cannot_send_raises(render, decision):
    with pytest.raises(ValueError, match="cannot send"):
        render(decision)


def test_gemini_thinking_config_builder():
    assert _thinking_config(None, None) is None
    assert _thinking_config(512, None) == {"thinkingBudget": 512}
    assert _thinking_config(None, "medium") == {"thinkingLevel": "medium"}
    with pytest.raises(ValueError, match="not both"):
        _thinking_config(512, "medium")


def test_codex_translator_uses_the_resolved_effort():
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    ruled = _translate_request(
        {"model": "gpt-5.5", "messages": messages, "reasoning_effort": "high"}, "k"
    )
    assert ruled["reasoning"] == {"effort": "high", "summary": "auto"}
    # No reasoning_effort (VLM requests send none): the backend still
    # requires the block, so it gets the Codex default.
    unset = _translate_request({"model": "gpt-6.1-sol", "messages": messages}, "k")
    assert unset["reasoning"] == {"effort": "medium", "summary": "auto"}


# ────────────────────── 4. transports at CraftBot's settings ─────────────────


@pytest.fixture()
def bound_session():
    """Register a session with a given reasoning choice and bind to it."""
    registered: List[str] = []

    def _bind(choice: ReasoningChoice, session_id: str = "s-reasoning-test"):
        StateSession.start(
            session_id,
            current_session=Session(id=session_id, reasoning_effort=choice.value),
        )
        registered.append(session_id)
        return StateSession.bind(session_id)

    yield _bind
    for session_id in registered:
        StateSession.end(session_id)


def _one_call(monkeypatch, provider, model, auth_mode="api_key"):
    iface, rec = build_interface(monkeypatch, provider, model)
    iface.max_tokens = APP_MAX_TOKENS
    iface._auth_mode = auth_mode
    iface.generate_response(system_prompt=GOLDEN_SYSTEM_PROMPT, user_prompt="hi")
    assert len(rec.calls) == 1
    return iface, rec.calls[0]["payload"]


def test_openai_default_level(monkeypatch):
    _, payload = _one_call(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    assert payload["reasoning_effort"] == "high"
    assert payload["max_completion_tokens"] == 32_000
    assert "temperature" not in payload
    assert payload["response_format"] == {"type": "json_object"}


def test_openai_unruled_model(monkeypatch, bound_session):
    with bound_session(C.XHIGH):
        _, payload = _one_call(monkeypatch, "openai", "gpt-4o")
    assert "reasoning_effort" not in payload
    assert payload["max_completion_tokens"] == APP_MAX_TOKENS


def test_bound_session_choice_drives_the_request(monkeypatch, bound_session):
    with bound_session(C.XHIGH):
        _, payload = _one_call(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    assert payload["reasoning_effort"] == "xhigh"
    assert payload["max_completion_tokens"] == 64_000


def test_bound_session_off(monkeypatch, bound_session):
    with bound_session(C.OFF):
        _, payload = _one_call(monkeypatch, "openai", "gpt-5.5")
    assert payload["reasoning_effort"] == "none"
    assert payload["max_completion_tokens"] == APP_MAX_TOKENS


def test_per_call_choice_wins_over_the_bound_session(monkeypatch, bound_session):
    iface, rec = build_interface(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    iface.max_tokens = APP_MAX_TOKENS
    with bound_session(C.LOW):
        asyncio.run(
            iface.generate_response_async(
                system_prompt=GOLDEN_SYSTEM_PROMPT,
                user_prompt="hi",
                reasoning_choice=C.MEDIUM,
            )
        )
    assert rec.calls[0]["payload"]["reasoning_effort"] == "medium"


def test_subscription_request_carries_the_codex_row(monkeypatch):
    _, payload = _one_call(monkeypatch, "openai", "gpt-5.5", auth_mode="subscription")
    assert payload["reasoning_effort"] == "high"
    # Codex rows leave the (dropped) output cap alone.
    assert payload["max_completion_tokens"] == APP_MAX_TOKENS
    assert _translate_request(payload, "k")["reasoning"]["effort"] == "high"


def test_groq_cap_is_clamped_by_the_profile_and_temperature_kept(monkeypatch):
    _, payload = _one_call(monkeypatch, "groq", "openai/gpt-oss-120b")
    assert payload["reasoning_effort"] == "medium"
    assert payload["max_completion_tokens"] == 32_000  # <= Groq's 32,768 clamp
    assert payload["temperature"] == 0.0
    assert payload["response_format"] == {"type": "json_object"}


def test_cerebras_cap_is_clamped_by_the_profile(monkeypatch):
    _, payload = _one_call(monkeypatch, "cerebras", "gpt-oss-120b")
    assert payload["reasoning_effort"] == "medium"
    assert payload["max_completion_tokens"] == 32_000


def test_glm_bad_model_is_pinned_at_its_max(monkeypatch):
    _, payload = _one_call(monkeypatch, "glm", "glm-5.3")
    assert payload["reasoning_effort"] == "max"
    assert payload["max_tokens"] == 64_000


def test_openrouter_openai_row(monkeypatch):
    _, payload = _one_call(monkeypatch, "openrouter", "openai/gpt-5.2")
    assert payload["extra_body"]["reasoning"] == {"effort": "high"}
    assert "reasoning_effort" not in payload
    assert "temperature" not in payload
    assert payload["max_tokens"] == 32_000


def test_anthropic_default_level(monkeypatch):
    _, payload = _one_call(monkeypatch, "anthropic", "claude-opus-5-5")
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"] == {"effort": "high"}
    assert payload["max_tokens"] == 21_000
    assert "extra_body" not in payload  # no temperature


def test_anthropic_47_provider_default_still_drops_temperature(
    monkeypatch, bound_session
):
    with bound_session(C.PROVIDER_DEFAULT):
        _, payload = _one_call(monkeypatch, "anthropic", "claude-opus-4-7")
    assert "thinking" not in payload and "output_config" not in payload
    assert "extra_body" not in payload
    assert payload["max_tokens"] == 16_384


def test_anthropic_46_off_keeps_temperature(monkeypatch, bound_session):
    with bound_session(C.OFF):
        _, payload = _one_call(monkeypatch, "anthropic", "claude-sonnet-4-6")
    assert "thinking" not in payload
    assert payload["extra_body"] == {"temperature": 0.0}


def test_anthropic_unruled_model(monkeypatch):
    _, payload = _one_call(monkeypatch, "anthropic", "claude-3-5-haiku-20241022")
    assert "thinking" not in payload and "output_config" not in payload
    assert payload["max_tokens"] == 16_384
    assert payload["extra_body"] == {"temperature": 0.0}


def test_bedrock_adaptive_row(monkeypatch):
    _, payload = _one_call(monkeypatch, "bedrock", "us.anthropic.claude-opus-4-8")
    assert payload["additionalModelRequestFields"] == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }
    assert payload["inferenceConfig"] == {"maxTokens": 21_000}


def test_bedrock_off_disables_thinking(monkeypatch, bound_session):
    with bound_session(C.OFF):
        _, payload = _one_call(monkeypatch, "bedrock", "us.anthropic.claude-opus-5")
    assert payload["additionalModelRequestFields"] == {"thinking": {"type": "disabled"}}
    assert payload["inferenceConfig"] == {"maxTokens": APP_MAX_TOKENS}


def test_bedrock_unruled_model(monkeypatch):
    _, payload = _one_call(monkeypatch, "bedrock", "meta.llama3-3-70b-instruct-v1:0")
    assert "additionalModelRequestFields" not in payload
    assert payload["inferenceConfig"] == {
        "temperature": 0.0,
        "maxTokens": APP_MAX_TOKENS,
    }


def test_gemini_level_row(monkeypatch):
    _, payload = _one_call(monkeypatch, "gemini", "gemini-3.5-flash")
    config = payload["body"]["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingLevel": "medium"}
    assert config["maxOutputTokens"] == 32_768


def test_gemini_off_is_a_zero_budget(monkeypatch, bound_session):
    with bound_session(C.OFF):
        _, payload = _one_call(monkeypatch, "gemini", "gemini-2.5-flash")
    config = payload["body"]["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingBudget": 0}
    assert config["maxOutputTokens"] == APP_MAX_TOKENS


def test_gemini_provider_default_sends_no_thinking_config(monkeypatch, bound_session):
    with bound_session(C.PROVIDER_DEFAULT):
        _, payload = _one_call(monkeypatch, "gemini", "gemini-2.5-pro")
    config = payload["body"]["generationConfig"]
    assert "thinkingConfig" not in config
    # 2.5 Pro still thinks dynamically, so the request keeps the room.
    assert config["maxOutputTokens"] == 32_768


def test_gemini_caller_budget_wins_over_the_session(monkeypatch, bound_session):
    iface, rec = build_interface(monkeypatch, "gemini", "gemini-3.5-flash")
    iface.max_tokens = APP_MAX_TOKENS
    iface._begin_call(thinking_budget=512)
    with bound_session(C.HIGH):
        iface._generate_response_sync(GOLDEN_SYSTEM_PROMPT, "hi")
    config = rec.calls[0]["payload"]["body"]["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingBudget": 512}
    assert config["maxOutputTokens"] == APP_MAX_TOKENS


def test_context_check_reserves_the_requests_reasoning_cap(monkeypatch, bound_session):
    import app.config as app_config

    monkeypatch.setattr(app_config, "get_context_window", lambda: 40_000)
    prompt = "word " * 12_000  # ~12k tokens: fits 40k - 8k, not 40k - 32k

    unruled, _ = build_interface(monkeypatch, "openai", "gpt-4o")
    unruled.max_tokens = APP_MAX_TOKENS
    assert unruled._output_reservation(unruled.reasoning_decision()) == APP_MAX_TOKENS
    unruled._check_context_fits(None, prompt, reasoning=unruled.reasoning_decision())

    ruled, _ = build_interface(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    ruled.max_tokens = APP_MAX_TOKENS
    high = ruled.reasoning_decision()
    assert ruled._output_reservation(high) == 32_000
    with pytest.raises(LLMContextOverflowError, match="32000 reserved for output"):
        ruled._check_context_fits(None, prompt, reasoning=high)
    # The request path refuses it before anything is sent.
    with pytest.raises(LLMContextOverflowError):
        ruled.generate_response(system_prompt=None, user_prompt=prompt)

    # A session that turned reasoning off reserves only the caller's cap.
    with bound_session(C.OFF):
        off = ruled.reasoning_decision()
        assert ruled._output_reservation(off) == APP_MAX_TOKENS
        ruled._check_context_fits(None, prompt, reasoning=off)


def test_each_request_resolves_its_reasoning_once(monkeypatch):
    # The context check and the transport share one decision, so a choice
    # changed mid-request cannot make them disagree.
    iface, rec = build_interface(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    iface.max_tokens = APP_MAX_TOKENS
    resolutions: List[ReasoningDecision] = []
    resolve = iface.reasoning_decision

    def counting_resolve():
        resolutions.append(resolve())
        return resolutions[-1]

    monkeypatch.setattr(iface, "reasoning_decision", counting_resolve)
    iface.generate_response(system_prompt=GOLDEN_SYSTEM_PROMPT, user_prompt="hi")
    assert len(resolutions) == 1

    iface.create_session_cache("task", "action_selection", GOLDEN_SYSTEM_PROMPT)
    iface.generate_response_with_session(
        "task", "action_selection", "hi", log_response=False
    )
    assert len(resolutions) == 2
    assert [call["payload"]["reasoning_effort"] for call in rec.calls] == [
        "high",
        "high",
    ]


def test_each_model_and_choice_is_logged_once(monkeypatch, bound_session):
    import agent_core.core.impl.llm.interface as interface_module

    iface, _ = build_interface(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    with bound_session(C.HIGH, session_id="s-high"):
        pass
    with bound_session(C.LOW, session_id="s-low"):
        pass
    logged: List[str] = []
    monkeypatch.setattr(interface_module, "logger", SimpleNamespace(info=logged.append))
    # Two sessions alternating, as concurrent sessions do.
    for _ in range(3):
        with StateSession.bind("s-high"):
            iface.reasoning_decision()
        with StateSession.bind("s-low"):
            iface.reasoning_decision()
    assert len(logged) == 2
    assert "choice=high" in logged[0] and "choice=low" in logged[1]


def test_fold_check_reserves_the_same_cap_as_the_pre_send_check(
    monkeypatch, bound_session
):
    import app.config as app_config

    # window 128,000 - reserve 16,384 - the output reservation.
    monkeypatch.setattr(app_config, "get_context_window", lambda: 128_000)
    monkeypatch.setattr(app_config, "get_reserve_tokens", lambda: 16_384)

    def assert_folds_after(iface, last_input_tokens: int) -> None:
        key = "task:action_selection"
        iface._last_input_tokens[key] = last_input_tokens
        assert iface.fits_context("task", "action_selection", "s", "")
        iface._last_input_tokens[key] = last_input_tokens + 1
        assert not iface.fits_context("task", "action_selection", "s", "")

    unruled, _ = build_interface(monkeypatch, "openai", "gpt-4o")
    unruled.max_tokens = APP_MAX_TOKENS
    assert_folds_after(unruled, 103_616)  # the caller's 8,000

    ruled, _ = build_interface(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    ruled.max_tokens = APP_MAX_TOKENS
    assert_folds_after(ruled, 79_616)  # default high: 32,000
    with bound_session(C.XHIGH):
        assert_folds_after(ruled, 47_616)  # 64,000
    with bound_session(C.OFF):
        assert_folds_after(ruled, 103_616)  # no reasoning: the caller's 8,000


def test_decision_follows_a_model_switch(monkeypatch):
    iface, _ = build_interface(monkeypatch, "openai", "gpt-4o")
    assert iface.reasoning_decision() is None
    assert iface.reasoning_options() is None
    iface.model = "gpt-5.2"
    assert iface.reasoning_decision().level == "high"
    assert iface.reasoning_options().default_level == "high"


# ──────────────────────────── 5. session plumbing ───────────────────────────


def test_session_round_trips_its_choice():
    session = Session(id="s1", reasoning_effort=C.XHIGH.value)
    assert Session.from_dict(session.to_dict()).reasoning_effort == "xhigh"
    # Absent or no longer valid (the retired "auto"): discarded, so the
    # session manager reseeds it on restore.
    assert Session.from_dict({"id": "s2"}).reasoning_effort is None
    assert (
        Session.from_dict({"id": "s3", "reasoning_effort": "auto"}).reasoning_effort
        is None
    )
    assert (
        Session.from_dict({"id": "s4", "reasoning_effort": "turbo"}).reasoning_effort
        is None
    )


@pytest.mark.parametrize(
    "provider, model, expected",
    [
        ("openai", "gpt-5.2-2025-12-11", C.HIGH),
        ("groq", "openai/gpt-oss-120b", C.MEDIUM),
        ("glm", "glm-5.3", C.MAX),
        # No rule: the default ceiling, clamped once a model with a rule runs.
        ("openai", "gpt-4o", C.HIGH),
        (None, None, C.HIGH),
    ],
)
def test_default_choice_a_new_session_starts_at(provider, model, expected):
    assert default_choice(provider, model) is expected


def test_new_and_restored_sessions_are_seeded_with_the_model_default(
    monkeypatch, tmp_path: Path
):
    iface, _ = build_interface(monkeypatch, "groq", "openai/gpt-oss-120b")
    persisted: List[Dict[str, Any]] = []
    manager = SessionManager(
        event_stream_manager=None,
        llm_interface=iface,
        workspace_root=tmp_path,
        on_session_persist=lambda session: persisted.append(session.to_dict()),
    )
    created = manager.create_session()
    restored = manager.restore_session(
        Session.from_dict({"id": "s-restored", "reasoning_effort": "auto"})
    )
    kept = manager.restore_session(
        Session.from_dict({"id": "s-kept", "reasoning_effort": "xhigh"})
    )
    try:
        assert created.reasoning_effort == "medium"
        # The retired value is discarded and reseeded, and the seed is saved.
        assert restored.reasoning_effort == "medium"
        assert persisted[-1] == {
            **persisted[-1],
            "id": "s-restored",
            "reasoning_effort": "medium",
        }
        # A valid stored choice is kept as is, even one the model lacks.
        assert kept.reasoning_effort == "xhigh"
    finally:
        for session_id in (created.id, "s-restored", "s-kept"):
            StateSession.end(session_id)


def test_work_outside_any_session_uses_the_model_default(monkeypatch):
    iface, _ = build_interface(monkeypatch, "glm", "glm-5.3")
    assert iface.reasoning_choice() is C.MAX
    assert iface.reasoning_decision().level == "max"


def test_session_manager_creates_and_sets_the_choice(tmp_path: Path):
    persisted: List[Dict[str, Any]] = []
    manager = SessionManager(
        event_stream_manager=None,
        workspace_root=tmp_path,
        on_session_persist=lambda session: persisted.append(session.to_dict()),
    )
    session = manager.create_session(reasoning_effort=C.LOW)
    try:
        assert session.reasoning_effort == "low"
        assert manager.set_reasoning_effort(session.id, C.OFF)
        assert manager.get(session.id).reasoning_effort == "off"
        assert persisted[-1]["reasoning_effort"] == "off"
        assert not manager.set_reasoning_effort("no-such-session", C.OFF)
    finally:
        StateSession.end(session.id)


def test_sync_actions_run_in_the_callers_session_binding(bound_session):
    code = (
        "def probe(input_data):\n"
        "    from agent_core.core.state.session import StateSession\n"
        "    state = StateSession.bound()\n"
        "    return {'session': state.session_id if state else None}\n"
    )

    async def _run():
        with bound_session(C.HIGH, session_id="s-sync-action"):
            return await _atomic_action_internal_async("probe", code, {}, "CLI")

    assert asyncio.run(_run()) == {"session": "s-sync-action"}


def _adapter_with(agent) -> Any:
    from app.ui_layer.adapters.browser_adapter import BrowserAdapter

    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter._controller = SimpleNamespace(agent=agent)
    adapter.sent = []
    adapter.broadcasts = []

    async def _send_to(ws, message):
        adapter.sent.append(message)

    async def _broadcast(message):
        adapter.broadcasts.append(message)

    adapter._send_to = _send_to
    adapter._broadcast = _broadcast
    return adapter


def test_reasoning_options_handler(monkeypatch):
    iface, _ = build_interface(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    adapter = _adapter_with(SimpleNamespace(llm=iface))
    asyncio.run(adapter._handle_reasoning_options_get(ws=None))
    data = adapter.sent[0]["data"]
    assert data["configurable"] is True
    assert data["choices"] == ["off", "low", "medium", "high", "xhigh"]
    assert data["defaultLevel"] == "high"
    assert data["providerDefault"] == "off"
    assert data["resolution"]["max"] == "xhigh"

    unruled, _ = build_interface(monkeypatch, "openai", "gpt-4o")
    adapter = _adapter_with(SimpleNamespace(llm=unruled))
    asyncio.run(adapter._handle_reasoning_options_get(ws=None))
    assert adapter.sent[0]["data"] == {
        "success": True,
        "model": "gpt-4o",
        "configurable": False,
    }


def test_session_reasoning_set_handler(tmp_path: Path):
    manager = SessionManager(event_stream_manager=None, workspace_root=tmp_path)
    session = manager.create_session()
    agent = SimpleNamespace(
        session_manager=manager,
        set_session_reasoning_effort=manager.set_reasoning_effort,
    )
    adapter = _adapter_with(agent)
    try:
        asyncio.run(
            adapter._handle_session_reasoning_set(
                {"sessionId": session.id, "reasoningEffort": "minimal"}
            )
        )
        assert session.reasoning_effort == "minimal"
        assert adapter.broadcasts[-1]["data"]["session"]["reasoningEffort"] == "minimal"

        # An unknown value changes nothing.
        asyncio.run(
            adapter._handle_session_reasoning_set(
                {"sessionId": session.id, "reasoningEffort": "turbo"}
            )
        )
        assert session.reasoning_effort == "minimal"
        assert len(adapter.broadcasts) == 1
    finally:
        StateSession.end(session.id)


def test_draft_reasoning_from_a_message():
    from app.ui_layer.adapters.browser_adapter import BrowserAdapter

    assert BrowserAdapter._draft_reasoning({"reasoningEffort": "xhigh"}) is C.XHIGH
    assert BrowserAdapter._draft_reasoning({}) is None
    with pytest.raises(ValueError):
        BrowserAdapter._draft_reasoning({"reasoningEffort": "turbo"})
