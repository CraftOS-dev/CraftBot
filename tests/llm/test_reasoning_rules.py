# -*- coding: utf-8 -*-
"""Per-model reasoning defaults (agent_core/core/models/reasoning.py).

Four layers:

1. The table: every row is well formed, uses only the levels its wire can
   carry, and is filed under a provider whose transport can send it.
2. The level policy: one level below the strongest, never above "high",
   and never below the provider's own default (then the strongest level).
3. Wire rendering: each decision becomes exactly its provider's fields.
4. The transports at CraftBot's real settings (max_tokens 8000): a model with
   a rule gets its fields, output cap, and temperature handling; a model
   without one is untouched (the golden unruled_* snapshots additionally pin
   those payloads byte for byte).
"""

from __future__ import annotations

import pytest

from agent_core.core.impl.llm import reasoning_wire
from agent_core.core.impl.llm.interface import LLMContextOverflowError
from agent_core.core.impl.llm.reasoning_wire import TRANSPORT_WIRES
from agent_core.core.llm.google_gemini_client import _thinking_config
from agent_core.core.models.chatgpt_subscription_client import _translate_request
from agent_core.core.models.reasoning import (
    BUDGET_RUNGS,
    BUDGET_WIRES,
    KNOWN_LEVELS,
    LEVEL_CEILING,
    REASONING_RULES,
    ReasoningDecision,
    ReasoningRule,
    ReasoningWire,
    resolve_reasoning,
    target_level,
)
from agent_core.core.models.registry import get_registry

from .golden.conftest import GOLDEN_SYSTEM_PROMPT, build_interface

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


ROWS = [
    (surface, model, rule)
    for surface, rows in REASONING_RULES.items()
    for model, rule in rows.items()
]
ROW_IDS = [f"{surface}/{model}" for surface, model, _ in ROWS]


# ─────────────────────────────── 1. the table ───────────────────────────────


@pytest.mark.parametrize("surface, model, rule", ROWS, ids=ROW_IDS)
def test_row_is_well_formed(surface, model, rule):
    assert model == model.strip() and model
    assert rule.levels, "a rule needs at least one level"
    assert len(set(rule.levels)) == len(rule.levels)
    assert all(level in KNOWN_LEVELS for level in rule.levels)
    assert list(rule.levels) == sorted(rule.levels, key=KNOWN_LEVELS.index)
    assert rule.provider_default is None or rule.provider_default in rule.levels
    assert rule.source.startswith("https://")
    assert rule.output_tokens >= 0
    if rule.wire in BUDGET_WIRES:
        assert rule.levels == BUDGET_RUNGS
        assert len(rule.budgets) == len(rule.levels)
        assert list(rule.budgets) == sorted(set(rule.budgets))
        assert rule.budgets[0] >= MIN_THINKING_BUDGET
    else:
        assert rule.budgets == ()


@pytest.mark.parametrize("surface, model, rule", ROWS, ids=ROW_IDS)
def test_row_is_sendable_by_its_providers_transport(surface, model, rule):
    profile = get_registry().get(_provider(surface))
    assert profile is not None, f"{surface!r} is not a registered provider"
    assert rule.wire in TRANSPORT_WIRES[profile.wire]


@pytest.mark.parametrize("surface, model, rule", ROWS, ids=ROW_IDS)
def test_anthropic_caps_stay_below_the_sdk_non_streaming_ceiling(surface, model, rule):
    if rule.wire in (ReasoningWire.ANTHROPIC_ADAPTIVE, ReasoningWire.ANTHROPIC_BUDGET):
        assert 0 < rule.output_tokens < ANTHROPIC_NON_STREAMING_CEILING


def test_duplicate_model_ids_are_refused():
    from agent_core.core.models import reasoning

    rule = REASONING_RULES["openai"]["gpt-5.2"]
    with pytest.raises(ValueError, match="listed twice"):
        reasoning._surface({"m": rule}, {"m": rule})


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
    ],
)
def test_target_level_policy(levels, provider_default, expected):
    rule = ReasoningRule(
        wire=ReasoningWire.EFFORT,
        levels=levels,
        provider_default=provider_default,
        source="https://example.test",
    )
    assert target_level(rule) == expected


@pytest.mark.parametrize("surface, model, rule", ROWS, ids=ROW_IDS)
def test_every_row_resolves_within_the_policy(surface, model, rule):
    decision = resolve_reasoning(_provider(surface), model, _auth_mode(surface))
    assert decision is not None
    assert decision.key == f"{surface}/{model}"
    chosen = rule.levels.index(decision.level)
    if rule.provider_default is not None:
        # Never weaker than what the provider applies when it is omitted.
        assert chosen >= rule.levels.index(rule.provider_default)
    if LEVEL_CEILING in rule.levels and chosen > rule.levels.index(LEVEL_CEILING):
        # Above the ceiling only when the provider's own default already is.
        assert rule.provider_default is not None
        assert rule.levels.index(rule.provider_default) > rule.levels.index(
            LEVEL_CEILING
        )
        assert chosen == len(rule.levels) - 1
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
def test_resolved_levels(provider, model, auth_mode, expected):
    assert resolve_reasoning(provider, model, auth_mode).level == expected


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
def test_budget_models_resolve_to_the_high_rung(provider, model, budget):
    decision = resolve_reasoning(provider, model)
    assert decision.level == "high"
    assert decision.budget_tokens == budget


@pytest.mark.parametrize(
    "provider, model, auth_mode",
    [
        ("openai", "gpt-4o", "api_key"),
        ("openai", "gpt-5.2", "subscription"),  # not in the Codex catalogue
        ("openai", "gpt-5.5", "api_key_typo"),  # unknown auth mode: api surface
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
    if auth_mode == "api_key_typo":
        # A non-subscription auth mode reads the public-API surface.
        assert resolve_reasoning(provider, model, auth_mode).key == "openai/gpt-5.5"
        return
    assert resolve_reasoning(provider, model, auth_mode) is None


def test_output_cap_never_lowers_the_callers_cap():
    decision = resolve_reasoning("openai", "gpt-5.2")
    assert decision.output_cap(APP_MAX_TOKENS) == 32_000
    assert decision.output_cap(50_000) == 50_000


# ─────────────────────────────── 3. rendering ───────────────────────────────


def _decision(wire, level="high", budget=None):
    return ReasoningDecision(
        key="test/model",
        wire=wire,
        level=level,
        budget_tokens=budget,
        output_tokens=0,
        omit_temperature=False,
    )


def test_chat_completions_fields():
    assert reasoning_wire.chat_completions_fields(_decision(ReasoningWire.EFFORT)) == (
        {"reasoning_effort": "high"},
        {},
    )
    assert reasoning_wire.chat_completions_fields(
        _decision(ReasoningWire.OPENROUTER_EFFORT)
    ) == ({}, {"reasoning": {"effort": "high"}})
    assert reasoning_wire.chat_completions_fields(
        _decision(ReasoningWire.OPENROUTER_BUDGET, budget=12_288)
    ) == ({}, {"reasoning": {"max_tokens": 12_288}})


def test_anthropic_fields():
    assert reasoning_wire.anthropic_fields(
        _decision(ReasoningWire.ANTHROPIC_ADAPTIVE)
    ) == {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}}
    assert reasoning_wire.anthropic_fields(
        _decision(ReasoningWire.ANTHROPIC_BUDGET, budget=12_288)
    ) == {"thinking": {"type": "enabled", "budget_tokens": 12_288}}


def test_gemini_thinking_kwargs():
    assert reasoning_wire.gemini_thinking_kwargs(
        _decision(ReasoningWire.GEMINI_LEVEL, level="medium")
    ) == {"thinking_level": "medium"}
    assert reasoning_wire.gemini_thinking_kwargs(
        _decision(ReasoningWire.GEMINI_BUDGET, budget=24_576)
    ) == {"thinking_budget": 24_576}


@pytest.mark.parametrize(
    "render, wire",
    [
        (reasoning_wire.chat_completions_fields, ReasoningWire.ANTHROPIC_ADAPTIVE),
        (reasoning_wire.anthropic_fields, ReasoningWire.EFFORT),
        (reasoning_wire.gemini_thinking_kwargs, ReasoningWire.OPENROUTER_EFFORT),
    ],
)
def test_a_wire_the_transport_cannot_send_raises(render, wire):
    with pytest.raises(ValueError, match="wrong provider"):
        render(_decision(wire))


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
    # No rule: the backend still requires the block, so today's medium stays.
    unruled = _translate_request({"model": "gpt-5.4", "messages": messages}, "k")
    assert unruled["reasoning"] == {"effort": "medium", "summary": "auto"}


# ────────────────────── 4. transports at CraftBot's settings ─────────────────


def _one_call(monkeypatch, provider, model, auth_mode="api_key"):
    iface, rec = build_interface(monkeypatch, provider, model)
    iface.max_tokens = APP_MAX_TOKENS
    iface._auth_mode = auth_mode
    iface.generate_response(system_prompt=GOLDEN_SYSTEM_PROMPT, user_prompt="hi")
    assert len(rec.calls) == 1
    return iface, rec.calls[0]["payload"]


def test_openai_ruled_model(monkeypatch):
    _, payload = _one_call(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    assert payload["reasoning_effort"] == "high"
    assert payload["max_completion_tokens"] == 32_000
    assert "temperature" not in payload
    assert payload["response_format"] == {"type": "json_object"}


def test_openai_unruled_model(monkeypatch):
    _, payload = _one_call(monkeypatch, "openai", "gpt-4o")
    assert "reasoning_effort" not in payload
    assert payload["max_completion_tokens"] == APP_MAX_TOKENS


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
    assert payload["max_tokens"] == 32_000


def test_openrouter_openai_row(monkeypatch):
    _, payload = _one_call(monkeypatch, "openrouter", "openai/gpt-5.2")
    assert payload["extra_body"]["reasoning"] == {"effort": "high"}
    assert "reasoning_effort" not in payload
    assert "temperature" not in payload
    assert payload["max_tokens"] == 32_000


def test_anthropic_ruled_model(monkeypatch):
    _, payload = _one_call(monkeypatch, "anthropic", "claude-opus-5-5")
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"] == {"effort": "high"}
    assert payload["max_tokens"] == 21_000
    assert "extra_body" not in payload  # no temperature


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


def test_gemini_caller_budget_wins_over_the_default(monkeypatch):
    iface, rec = build_interface(monkeypatch, "gemini", "gemini-3.5-flash")
    iface.max_tokens = APP_MAX_TOKENS
    iface._begin_call(thinking_budget=512)
    iface._generate_response_sync(GOLDEN_SYSTEM_PROMPT, "hi")
    config = rec.calls[0]["payload"]["body"]["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingBudget": 512}
    assert config["maxOutputTokens"] == APP_MAX_TOKENS


def test_context_check_reserves_the_reasoning_cap(monkeypatch):
    import app.config as app_config

    monkeypatch.setattr(app_config, "get_context_window", lambda: 40_000)
    prompt = "word " * 12_000  # ~12k tokens: fits 40k - 8k, not 40k - 32k

    unruled, _ = build_interface(monkeypatch, "openai", "gpt-4o")
    unruled.max_tokens = APP_MAX_TOKENS
    assert unruled._output_reservation() == APP_MAX_TOKENS
    unruled._check_context_fits(None, prompt)

    ruled, _ = build_interface(monkeypatch, "openai", "gpt-5.2-2025-12-11")
    ruled.max_tokens = APP_MAX_TOKENS
    assert ruled._output_reservation() == 32_000
    with pytest.raises(LLMContextOverflowError, match="32000 reserved for output"):
        ruled._check_context_fits(None, prompt)


def test_decision_follows_a_model_switch(monkeypatch):
    iface, _ = build_interface(monkeypatch, "openai", "gpt-4o")
    assert iface.reasoning_decision() is None
    iface.model = "gpt-5.2"
    assert iface.reasoning_decision().level == "high"
