# -*- coding: utf-8 -*-
"""Reasoning effort ("thinking") per model, chosen per chat session.

Why this exists
---------------
Reasoning models need an explicit request parameter to think at a useful
depth, and several of them do no reasoning at all when it is omitted
(OpenAI gpt-5.1 through gpt-5.4 default to ``none``; Claude Sonnet 4.6 and
Opus 4.6-4.8 run without thinking unless it is requested). The parameter is
also model-specific: its name, shape, and accepted values differ between
models of the SAME provider, and a value a model does not accept is a hard
HTTP 400 on the first request.

So the capabilities live in a hard-coded table keyed by provider and EXACT
model id (no prefix or substring matching). A model that is not in the table
gets no reasoning parameter at all, whatever the session picked, and its
request stays byte-identical to the one sent before this module existed
(pinned by the ``unruled_*`` golden payload snapshots under tests/llm/golden/).

Choices
-------
Each chat session stores a ``ReasoningChoice`` (``Session.reasoning_effort``,
picked in the chat input), following the pi agent harness: a concrete level,
``off``, or ``provider_default`` (no reasoning parameter, so the provider's
own default applies; on a backend that always needs a level, its documented
default level is sent). A session whose user never picked stores no choice
(None) and runs at the default level of whichever model serves each request
(see "The default level"), which the picker marks as "Default"; so it follows
a model switch.

A model offers its levels, plus ``off`` when it can stop reasoning. A stored
choice the current model lacks is clamped the way pi does it: the nearest
available choice at or above the request, else the nearest below, along
``CHOICE_LADDER``. The session keeps the REQUESTED choice, so it re-applies
after a model switch.

The default level
-----------------
``ReasoningRule.levels`` lists the levels that turn reasoning on, weakest
first. Values a provider silently maps onto another level are left out, so
the tuple holds only levels that behave differently. ``minimal`` is listed
where a model accepts it (it is selectable) but is never the default. The
default level is:

1. one level below the model's strongest level (``LEVELS_BELOW_MAX``);
2. never stronger than ``LEVEL_CEILING`` (``high``);
3. but if that is weaker than the level the provider already applies when
   the parameter is omitted (``provider_default``), the model's strongest
   level is used instead, so a default is never lowered.

Token-budget models (Claude 4.5, Gemini 2.5) have no named levels; their
rows name four budget rungs ``BUDGET_RUNGS`` so the same rules pick the
third rung ("high").

Adding a model
--------------
Add its exact id (every alias and dated snapshot the provider accepts) to a
rule below, with the ordered levels, default, and off behavior from the
provider's documentation and the documentation URL in ``source``. The unit
tests in tests/llm/test_reasoning_rules.py validate every row.

The keys follow the ``<provider>/<model_id>`` shape of the model catalog
planned in docs/PROVIDER_LAYER_CATCHUP.md section 10, so the rows can move
into that catalog as a column without a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict, Mapping, Optional, Tuple

# ─────────────────────────────── choices ──────────────────────────────


class ReasoningChoice(str, Enum):
    """What a chat session asks for (stored as ``Session.reasoning_effort``)."""

    PROVIDER_DEFAULT = "provider_default"
    OFF = "off"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


#: Clamping ladder, weakest first (pi's EXTENDED_THINKING_LEVELS).
CHOICE_LADDER: Tuple[ReasoningChoice, ...] = (
    ReasoningChoice.OFF,
    ReasoningChoice.MINIMAL,
    ReasoningChoice.LOW,
    ReasoningChoice.MEDIUM,
    ReasoningChoice.HIGH,
    ReasoningChoice.XHIGH,
    ReasoningChoice.MAX,
)

# ─────────────────────────────── policy ───────────────────────────────

#: How many levels below the model's strongest level the default sits.
LEVELS_BELOW_MAX = 1

#: The strongest default level (unless the provider's own default is already
#: stronger; see rule 3 in the module docstring).
LEVEL_CEILING = "high"

#: Levels that are never the default: "minimal" barely reasons.
DEFAULT_EXCLUDED_LEVELS = frozenset({"minimal"})

#: Levels whose thinking needs the rule's extended output cap.
EXTENDED_LEVELS = frozenset({"xhigh", "max"})

#: Rung names for token-budget models, weakest first.
BUDGET_RUNGS: Tuple[str, ...] = ("low", "medium", "high", "max")

#: The auth mode whose OpenAI requests go to the ChatGPT-subscription Codex
#: backend, which serves a different model catalogue with different levels.
SUBSCRIPTION_AUTH_MODE = "subscription"


class ReasoningWire(str, Enum):
    """How reasoning is expressed in a request."""

    #: Top-level ``reasoning_effort: <level>`` on a Chat Completions request
    #: (off: ``"none"``). The ChatGPT-subscription translator maps it to
    #: ``reasoning.effort``.
    EFFORT = "effort"
    #: Anthropic ``thinking: {"type": "adaptive"}`` plus
    #: ``output_config: {"effort": <level>}`` (Claude 4.6 and later; off:
    #: ``thinking: {"type": "disabled"}``).
    ANTHROPIC_ADAPTIVE = "anthropic_adaptive"
    #: Anthropic ``thinking: {"type": "enabled", "budget_tokens": <n>}``
    #: (Claude 4.5 generation).
    ANTHROPIC_BUDGET = "anthropic_budget"
    #: Gemini ``thinkingConfig: {"thinkingLevel": <level>}`` (Gemini 3.x).
    GEMINI_LEVEL = "gemini_level"
    #: Gemini ``thinkingConfig: {"thinkingBudget": <n>}`` (Gemini 2.5; off:
    #: budget 0).
    GEMINI_BUDGET = "gemini_budget"
    #: OpenRouter ``reasoning: {"effort": <level>}`` (off: ``"none"``).
    OPENROUTER_EFFORT = "openrouter_effort"
    #: OpenRouter ``reasoning: {"max_tokens": <n>}``.
    OPENROUTER_BUDGET = "openrouter_budget"


#: Wires whose rows carry token budgets instead of named levels.
BUDGET_WIRES = frozenset(
    {
        ReasoningWire.ANTHROPIC_BUDGET,
        ReasoningWire.GEMINI_BUDGET,
        ReasoningWire.OPENROUTER_BUDGET,
    }
)


class ReasoningOff(str, Enum):
    """How a model stops reasoning (a rule without one cannot)."""

    #: The provider's default is no reasoning: off sends nothing.
    OMIT = "omit"
    #: Off sends the wire's explicit disable form.
    EXPLICIT = "explicit"


class TemperaturePolicy(str, Enum):
    """When a model rejects an explicit ``temperature``."""

    KEEP = "keep"
    OMIT_WHILE_THINKING = "omit_while_thinking"
    OMIT_ALWAYS = "omit_always"


@dataclass(frozen=True)
class ReasoningRule:
    """Reasoning capabilities of one model (or of models that share them)."""

    #: How reasoning is expressed in the request.
    wire: ReasoningWire
    #: Levels that turn reasoning on, weakest first (``BUDGET_RUNGS`` for
    #: budget wires).
    levels: Tuple[str, ...]
    #: Level the provider applies when the parameter is omitted, when that
    #: is one of ``levels``. None when omitting it means no reasoning or a
    #: provider-chosen (dynamic or undocumented) amount.
    provider_default: Optional[str]
    #: Documentation the row was taken from.
    source: str
    #: Budget-wire rows: token budget per rung, aligned with ``levels``.
    budgets: Tuple[int, ...] = ()
    #: Output-token cap to request while reasoning. Reasoning tokens count
    #: against the provider's output cap, so it must leave room for the
    #: answer. 0 keeps the caller's cap unchanged.
    output_tokens: int = 0
    #: Output-token cap at ``EXTENDED_LEVELS``; 0 means ``output_tokens``.
    extended_output_tokens: int = 0
    #: How the model stops reasoning; None when it cannot.
    off: Optional[ReasoningOff] = None
    #: When the model rejects an explicit temperature.
    temperature: TemperaturePolicy = TemperaturePolicy.KEEP
    #: The backend requires a level on every request (the Codex backend), so
    #: ``provider_default`` sends the documented default level explicitly.
    requires_level: bool = False

    def ladder_choices(self) -> Tuple[ReasoningChoice, ...]:
        """The ladder choices this model accepts, weakest first."""
        return tuple(
            choice
            for choice in CHOICE_LADDER
            if (choice is ReasoningChoice.OFF and self.off is not None)
            or choice.value in self.levels
        )

    def output_tokens_for(self, level: Optional[str]) -> int:
        """Output cap while reasoning at ``level`` (None: the provider's)."""
        if level in EXTENDED_LEVELS and self.extended_output_tokens:
            return self.extended_output_tokens
        return self.output_tokens

    def budget_for(self, level: str) -> int:
        """Token budget of a budget-wire rung."""
        return self.budgets[self.levels.index(level)]


@dataclass(frozen=True)
class ReasoningDecision:
    """What one request sends, resolved from a model's rule and a choice."""

    #: ``<surface>/<model_id>`` of the row that produced this decision.
    key: str
    #: The choice the session asked for.
    requested: ReasoningChoice
    #: The choice in effect after clamping it to this model.
    choice: ReasoningChoice
    wire: ReasoningWire
    #: Level sent, or None when no level is sent (off, provider default).
    level: Optional[str]
    #: Token budget for budget wires, else None.
    budget_tokens: Optional[int]
    #: Send the wire's explicit disable form.
    off: bool
    #: Output cap the request needs; 0 keeps the caller's cap.
    output_tokens: int
    omit_temperature: bool

    def output_cap(self, base: int) -> int:
        """Output-token cap for a request whose cap is otherwise ``base``.

        Never lowers ``base``: reasoning only ever adds room.
        """
        return max(base, self.output_tokens)

    def describe(self) -> str:
        """One-line human-readable summary for logs."""
        choice = self.requested.value
        if self.choice is not self.requested:
            choice = f"{choice} (clamped to {self.choice.value})"
        if self.off:
            sent = "disable"
        elif self.level is None and self.choice is ReasoningChoice.OFF:
            sent = "nothing (the model does not reason by default)"
        elif self.level is None:
            sent = "nothing (provider default)"
        elif self.budget_tokens is not None:
            sent = f"budget={self.budget_tokens} ({self.level})"
        else:
            sent = f"level={self.level}"
        return f"choice={choice}, {self.wire.value} {sent}"


@dataclass(frozen=True)
class ReasoningOptions:
    """What the chat-input picker offers for one model."""

    #: Selectable choices, in display order.
    choices: Tuple[ReasoningChoice, ...]
    #: The model's default level (marked "Default" in the picker).
    default_level: str
    #: What ``provider_default`` does: "off", a level, or "dynamic".
    provider_default: str
    #: Effective choice for every possible stored choice.
    resolution: Mapping[ReasoningChoice, ReasoningChoice]


def default_level(rule: ReasoningRule) -> str:
    """The default level for ``rule`` (see the module docstring)."""
    ladder = tuple(
        level for level in rule.levels if level not in DEFAULT_EXCLUDED_LEVELS
    )
    index = max(len(ladder) - 1 - LEVELS_BELOW_MAX, 0)
    if LEVEL_CEILING in ladder:
        index = min(index, ladder.index(LEVEL_CEILING))
    if rule.provider_default in ladder and index < ladder.index(rule.provider_default):
        index = len(ladder) - 1
    return ladder[index]


def clamp_choice(rule: ReasoningRule, choice: ReasoningChoice) -> ReasoningChoice:
    """The choice that takes effect for ``rule`` when a session asks for ``choice``.

    Ladder choices the model lacks move to the nearest available choice at or
    above the request, else the nearest below (pi's ``clampThinkingLevel``).
    """
    if choice is ReasoningChoice.PROVIDER_DEFAULT:
        # Omitting the parameter IS off on these models.
        return ReasoningChoice.OFF if rule.off is ReasoningOff.OMIT else choice
    available = rule.ladder_choices()
    if choice in available:
        return choice
    requested = CHOICE_LADDER.index(choice)
    for candidate in CHOICE_LADDER[requested:]:
        if candidate in available:
            return candidate
    for candidate in reversed(CHOICE_LADDER[:requested]):
        if candidate in available:
            return candidate
    raise ValueError(f"Reasoning rule has no levels: {rule!r}")


def reasoning_surface(provider: str, auth_mode: str) -> str:
    """Table surface for a provider and auth mode.

    OpenAI requests made with a ChatGPT-subscription login go to the Codex
    backend, whose model catalogue and levels differ from the public API.
    """
    if provider == "openai" and auth_mode == SUBSCRIPTION_AUTH_MODE:
        return "openai_subscription"
    return provider


def _lookup(
    provider: Optional[str], model: Optional[str], auth_mode: str
) -> Tuple[Optional[str], Optional[ReasoningRule]]:
    if not provider or not model:
        return None, None
    surface = reasoning_surface(provider, auth_mode)
    return f"{surface}/{model}", REASONING_RULES.get(surface, {}).get(model)


def default_choice(
    provider: Optional[str], model: Optional[str], auth_mode: str = "api_key"
) -> ReasoningChoice:
    """The choice a request runs at with this model in use when its session
    has no choice of its own (the user never picked one).

    The model's default level; ``LEVEL_CEILING`` when the model has no rule
    (its requests then carry no reasoning parameter anyway).
    """
    _, rule = _lookup(provider, model, auth_mode)
    return ReasoningChoice(default_level(rule) if rule is not None else LEVEL_CEILING)


def resolve_reasoning(
    provider: Optional[str],
    model: Optional[str],
    auth_mode: str,
    choice: ReasoningChoice,
) -> Optional[ReasoningDecision]:
    """Resolve what a request sends for ``choice``, or None if the model has
    no row."""
    key, rule = _lookup(provider, model, auth_mode)
    if rule is None:
        return None
    effective = clamp_choice(rule, choice)
    if effective is ReasoningChoice.PROVIDER_DEFAULT:
        level = rule.provider_default if rule.requires_level else None
    elif effective is ReasoningChoice.OFF:
        level = None
    else:
        level = effective.value

    if level is not None:
        thinking = True
    elif effective is ReasoningChoice.PROVIDER_DEFAULT:
        thinking = rule.off is not ReasoningOff.OMIT
    else:
        thinking = False

    return ReasoningDecision(
        key=key,
        requested=choice,
        choice=effective,
        wire=rule.wire,
        level=level,
        budget_tokens=(
            rule.budget_for(level)
            if level is not None and rule.wire in BUDGET_WIRES
            else None
        ),
        off=effective is ReasoningChoice.OFF and rule.off is ReasoningOff.EXPLICIT,
        output_tokens=rule.output_tokens_for(level) if thinking else 0,
        omit_temperature=(
            rule.temperature is TemperaturePolicy.OMIT_ALWAYS
            or (rule.temperature is TemperaturePolicy.OMIT_WHILE_THINKING and thinking)
        ),
    )


def reasoning_options(
    provider: Optional[str], model: Optional[str], auth_mode: str
) -> Optional[ReasoningOptions]:
    """What the picker offers for a model, or None if the model has no row."""
    _, rule = _lookup(provider, model, auth_mode)
    if rule is None:
        return None
    if rule.off is ReasoningOff.OMIT:
        # Omitting the parameter is off: provider default and off coincide.
        meta: Tuple[ReasoningChoice, ...] = ()
        provider_default = ReasoningChoice.OFF.value
    else:
        meta = (ReasoningChoice.PROVIDER_DEFAULT,)
        provider_default = rule.provider_default or "dynamic"
    return ReasoningOptions(
        choices=meta + rule.ladder_choices(),
        default_level=default_level(rule),
        provider_default=provider_default,
        resolution={choice: clamp_choice(rule, choice) for choice in ReasoningChoice},
    )


def _models(rule: ReasoningRule, *model_ids: str) -> Dict[str, ReasoningRule]:
    return {model_id: rule for model_id in model_ids}


def _surface(*groups: Dict[str, ReasoningRule]) -> Dict[str, ReasoningRule]:
    """Merge one provider's ``_models`` groups, refusing duplicate ids.

    A plain dict merge would let a second listing of an id silently replace
    the first, sending a value its real model may reject.
    """
    merged: Dict[str, ReasoningRule] = {}
    for group in groups:
        for model_id, rule in group.items():
            if model_id in merged:
                raise ValueError(
                    f"Model id {model_id!r} is listed twice in the reasoning table."
                )
            merged[model_id] = rule
    return merged


def _bedrock_ids(base_id: str, *profile_prefixes: str) -> Tuple[str, ...]:
    """A Bedrock base model id plus its documented inference-profile ids.

    ``profile_prefixes`` are the geo/global prefixes the model's AWS model
    card lists (for example ``us`` gives ``us.<base_id>``); each resulting
    id is matched exactly like any other row.
    """
    return (base_id, *(f"{prefix}.{base_id}" for prefix in profile_prefixes))


# ─────────────────────────────── rules ────────────────────────────────
#
# Output caps. Non-streaming Anthropic requests are refused by the Anthropic
# SDK above 21,333 max_tokens (anthropic/_base_client.py
# _calculate_nonstreaming_timeout), so Anthropic-family rows stay just below
# it at every level. OpenAI-style effort rows use 32,000 (OpenAI recommends
# reserving at least 25,000 tokens for reasoning plus output,
# https://developers.openai.com/api/docs/guides/reasoning) and 64,000 at
# xhigh/max, where thinking alone can pass 32,000; every such model's
# documented output limit is above that.

_ANTHROPIC_OUTPUT_TOKENS = 21_000
_EFFORT_OUTPUT_TOKENS = 32_000
_EFFORT_EXTENDED_OUTPUT_TOKENS = 64_000

# ── OpenAI public API (Chat Completions ``reasoning_effort``) ──
# Values and defaults: https://developers.openai.com/api/docs/models/<id>.
# Models before gpt-5.1 reject "none"; gpt-5.1+ reject "minimal" and default
# to no reasoning through gpt-5.4. xhigh arrived with gpt-5.2. "max" exists
# only on the Responses API: Chat Completions rejects it on gpt-5.6 and GPT-6
# ("Supported values are: 'none', 'low', 'medium', 'high', and 'xhigh'", live
# API error, 2026-10-02; GPT-6 Astra and 6.1 Sol list the same without 'none').
# Temperature is the OpenAI profile's: it omits it on every request.

_OPENAI_DOCS = "https://developers.openai.com/api/docs/models"

_OPENAI_GPT5 = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("minimal", "low", "medium", "high"),
    provider_default="medium",
    source=f"{_OPENAI_DOCS}/gpt-5",
    output_tokens=_EFFORT_OUTPUT_TOKENS,
)
_OPENAI_O_SERIES = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "medium", "high"),
    provider_default="medium",
    source="https://developers.openai.com/api/docs/guides/reasoning",
    output_tokens=_EFFORT_OUTPUT_TOKENS,
)
_OPENAI_GPT51 = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "medium", "high"),
    provider_default=None,
    source=f"{_OPENAI_DOCS}/gpt-5.1",
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    off=ReasoningOff.OMIT,
)
_OPENAI_GPT52_TO_54 = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "medium", "high", "xhigh"),
    provider_default=None,
    source=f"{_OPENAI_DOCS}/gpt-5.2",
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    extended_output_tokens=_EFFORT_EXTENDED_OUTPUT_TOKENS,
    off=ReasoningOff.OMIT,
)
_OPENAI_GPT55 = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "medium", "high", "xhigh"),
    provider_default="medium",
    source=f"{_OPENAI_DOCS}/gpt-5.5",
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    extended_output_tokens=_EFFORT_EXTENDED_OUTPUT_TOKENS,
    off=ReasoningOff.EXPLICIT,
)
_OPENAI_GPT56_PLUS = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "medium", "high", "xhigh"),
    provider_default="medium",
    source=f"{_OPENAI_DOCS}/gpt-6-sol",
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    extended_output_tokens=_EFFORT_EXTENDED_OUTPUT_TOKENS,
    off=ReasoningOff.EXPLICIT,
)
#: GPT-6 Astra and GPT-6.1 Sol reject "none" and always reason.
_OPENAI_GPT6_ALWAYS_REASONING = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "medium", "high", "xhigh"),
    provider_default=None,
    source=f"{_OPENAI_DOCS}/gpt-6-astra",
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    extended_output_tokens=_EFFORT_EXTENDED_OUTPUT_TOKENS,
)
_OPENAI_GPT61_SOL = replace(
    _OPENAI_GPT6_ALWAYS_REASONING,
    provider_default="medium",
    source=f"{_OPENAI_DOCS}/gpt-6.1-sol",
)

# ── ChatGPT subscription (Codex backend ``reasoning.effort``) ──
# The translator always sends a reasoning block and drops output caps and
# temperature, so output_tokens stays 0. Levels are the catalogue's
# supported_reasoning_levels minus the client-side "ultra" alias; no model
# lists "none", so none can be turned off
# (https://github.com/openai/codex/blob/main/codex-rs/models-manager/models.json).
# The rows are exactly the OpenAI profile's subscription_models, the only
# models subscription auth runs.

_CODEX_CATALOG = (
    "https://github.com/openai/codex/blob/main/codex-rs/models-manager/models.json"
)
_CODEX_GPT55 = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "medium", "high", "xhigh"),
    provider_default="medium",
    source=_CODEX_CATALOG,
    requires_level=True,
)
_CODEX_MAX_LADDER_LOW_DEFAULT = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "medium", "high", "xhigh", "max"),
    provider_default="low",
    source=_CODEX_CATALOG,
    requires_level=True,
)
_CODEX_MAX_LADDER_MEDIUM_DEFAULT = replace(
    _CODEX_MAX_LADDER_LOW_DEFAULT, provider_default="medium"
)

# ── OpenRouter (``reasoning`` object) ──
# Levels: live GET https://openrouter.ai/api/v1/models ``reasoning``
# (supported_efforts; "mandatory" models cannot be turned off, the others
# take effort "none"). Claude 4.5 slugs expose no effort selector, only a
# token budget, which must be >= 1024 and strictly below the request
# max_tokens (https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).
# Upstream Claude does not think unless asked. Explicitly sent sampling
# parameters are forwarded upstream, where thinking rejects them.

_OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
_OPENROUTER_CLAUDE_BUDGET = ReasoningRule(
    wire=ReasoningWire.OPENROUTER_BUDGET,
    levels=BUDGET_RUNGS,
    provider_default=None,
    source="https://openrouter.ai/docs/guides/best-practices/reasoning-tokens",
    budgets=(4_096, 8_192, 12_288, 16_384),
    output_tokens=_ANTHROPIC_OUTPUT_TOKENS,
    off=ReasoningOff.OMIT,
    temperature=TemperaturePolicy.OMIT_WHILE_THINKING,
)
_OPENROUTER_CLAUDE_46 = ReasoningRule(
    wire=ReasoningWire.OPENROUTER_EFFORT,
    levels=("low", "medium", "high", "max"),
    provider_default=None,
    source=_OPENROUTER_MODELS,
    output_tokens=_ANTHROPIC_OUTPUT_TOKENS,
    off=ReasoningOff.OMIT,
    temperature=TemperaturePolicy.OMIT_WHILE_THINKING,
)
_OPENROUTER_OPENAI_GPT5 = ReasoningRule(
    wire=ReasoningWire.OPENROUTER_EFFORT,
    levels=("minimal", "low", "medium", "high"),
    provider_default="medium",
    source=_OPENROUTER_MODELS,
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    temperature=TemperaturePolicy.OMIT_ALWAYS,
)
_OPENROUTER_OPENAI_GPT51 = ReasoningRule(
    wire=ReasoningWire.OPENROUTER_EFFORT,
    levels=("low", "medium", "high"),
    provider_default=None,
    source=_OPENROUTER_MODELS,
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    off=ReasoningOff.OMIT,
    temperature=TemperaturePolicy.OMIT_WHILE_THINKING,
)
_OPENROUTER_OPENAI_XHIGH = ReasoningRule(
    wire=ReasoningWire.OPENROUTER_EFFORT,
    levels=("low", "medium", "high", "xhigh"),
    provider_default="medium",
    source=_OPENROUTER_MODELS,
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    extended_output_tokens=_EFFORT_EXTENDED_OUTPUT_TOKENS,
    off=ReasoningOff.EXPLICIT,
    temperature=TemperaturePolicy.OMIT_WHILE_THINKING,
)
_OPENROUTER_OPENAI_MAX = replace(
    _OPENROUTER_OPENAI_XHIGH, levels=("low", "medium", "high", "xhigh", "max")
)
_OPENROUTER_OPENAI_MAX_MANDATORY = replace(
    _OPENROUTER_OPENAI_MAX, off=None, temperature=TemperaturePolicy.OMIT_ALWAYS
)

# ── Google Gemini (generateContent ``thinkingConfig``) ──
# https://ai.google.dev/gemini-api/docs/generate-content/thinking. 2.5 models
# take a token budget only (thinkingLevel is a 400 on them); flash and
# flash-lite can turn thinking off with budget 0, pro cannot. 3.x models take
# a lowercase thinkingLevel and cannot turn thinking off; "minimal" is an
# error on 3.1-pro, 3.7-flash, and 3.8-flash. Thinking tokens count toward
# maxOutputTokens (65,536 on every model below), so each cap leaves 8,192
# tokens of answer on top of the largest budget it covers.

_GEMINI_THINKING_DOCS = (
    "https://ai.google.dev/gemini-api/docs/generate-content/thinking"
)
_GEMINI_ANSWER_TOKENS = 8_192
_GEMINI_25_PRO = ReasoningRule(
    wire=ReasoningWire.GEMINI_BUDGET,
    levels=BUDGET_RUNGS,
    provider_default=None,  # dynamic thinking
    source=_GEMINI_THINKING_DOCS,
    budgets=(8_192, 16_384, 24_576, 32_768),
    output_tokens=24_576 + _GEMINI_ANSWER_TOKENS,
    extended_output_tokens=32_768 + _GEMINI_ANSWER_TOKENS,
)
_GEMINI_25_FLASH = ReasoningRule(
    wire=ReasoningWire.GEMINI_BUDGET,
    levels=BUDGET_RUNGS,
    provider_default=None,  # dynamic thinking
    source=_GEMINI_THINKING_DOCS,
    budgets=(6_144, 12_288, 18_432, 24_576),
    output_tokens=18_432 + _GEMINI_ANSWER_TOKENS,
    extended_output_tokens=24_576 + _GEMINI_ANSWER_TOKENS,
    off=ReasoningOff.EXPLICIT,
)
#: flash-lite does not think unless given a budget.
_GEMINI_25_FLASH_LITE = replace(_GEMINI_25_FLASH, off=ReasoningOff.OMIT)
_GEMINI_3_OUTPUT_TOKENS = 32_768
_GEMINI_3_WITH_MINIMAL = ReasoningRule(
    wire=ReasoningWire.GEMINI_LEVEL,
    levels=("minimal", "low", "medium", "high"),
    provider_default="medium",
    source=_GEMINI_THINKING_DOCS,
    output_tokens=_GEMINI_3_OUTPUT_TOKENS,
)
_GEMINI_3_WITHOUT_MINIMAL = replace(
    _GEMINI_3_WITH_MINIMAL, levels=("low", "medium", "high")
)

# ── xAI (Chat Completions ``reasoning_effort``) ──
# https://docs.x.ai/developers/models/<id>. No Grok model accepts "max";
# "none" (off) is documented only for grok-4.3. grok-4.5 treats "xhigh" as
# "high", so its distinct levels stop at high.

_XAI_DOCS = "https://docs.x.ai/developers/models"
_XAI_REASONING_DOCS = "https://docs.x.ai/developers/model-capabilities/text/reasoning"
_XAI_GROK_43 = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "medium", "high", "xhigh"),
    provider_default="low",
    source=f"{_XAI_DOCS}/grok-4.3",
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    extended_output_tokens=_EFFORT_EXTENDED_OUTPUT_TOKENS,
    off=ReasoningOff.EXPLICIT,
)
_XAI_GROK_45 = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "medium", "high"),
    provider_default="high",
    source=_XAI_REASONING_DOCS,
    output_tokens=_EFFORT_OUTPUT_TOKENS,
)
_XAI_GROK_46_PLUS = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "medium", "high", "xhigh"),
    provider_default="high",
    source=_XAI_REASONING_DOCS,
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    extended_output_tokens=_EFFORT_EXTENDED_OUTPUT_TOKENS,
)

# ── DeepSeek (``reasoning_effort``) ──
# https://api-docs.deepseek.com/api/create-chat-completion: none/low/high/max
# (minimal maps to low, medium/xhigh to high), default high, "none" disables
# thinking; max_tokens up to 393,216. Thinking mode ignores temperature
# without an error.

_DEEPSEEK_V4 = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "high", "max"),
    provider_default="high",
    source="https://api-docs.deepseek.com/api/create-chat-completion",
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    extended_output_tokens=_EFFORT_EXTENDED_OUTPUT_TOKENS,
    off=ReasoningOff.EXPLICIT,
)

# ── Z.ai GLM (``reasoning_effort``, standard route) ──
# https://docs.z.ai/api-reference/llm/chat-completion, default max, 128K
# output. glm-5.3 accepts only low/high/max and cannot stop thinking;
# glm-5.2 maps low/medium to high and xhigh to max (distinct levels: high and
# max), and "none" skips thinking.

_GLM_DOCS = "https://docs.z.ai/api-reference/llm/chat-completion"
_GLM_53 = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "high", "max"),
    provider_default="max",
    source=_GLM_DOCS,
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    extended_output_tokens=_EFFORT_EXTENDED_OUTPUT_TOKENS,
)
_GLM_52 = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("high", "max"),
    provider_default="max",
    source=_GLM_DOCS,
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    extended_output_tokens=_EFFORT_EXTENDED_OUTPUT_TOKENS,
    off=ReasoningOff.EXPLICIT,
)

# ── Moonshot Kimi (``reasoning_effort``) ──
# https://platform.kimi.ai/docs/guide/kimi-k3-quickstart: low/high/max,
# default max; always thinks. Temperature is fixed (the profile omits it).

_KIMI_K3 = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "high", "max"),
    provider_default="max",
    source="https://platform.kimi.ai/docs/guide/kimi-k3-quickstart",
    output_tokens=_EFFORT_OUTPUT_TOKENS,
    extended_output_tokens=_EFFORT_EXTENDED_OUTPUT_TOKENS,
)

# ── gpt-oss on Groq / Cerebras (``reasoning_effort``) ──
# low/medium/high, default medium; always reasons; out-of-set values are a
# 400. Output caps are clamped further by each provider profile's
# max_output_tokens.

_GPT_OSS_GROQ = ReasoningRule(
    wire=ReasoningWire.EFFORT,
    levels=("low", "medium", "high"),
    provider_default="medium",
    source="https://console.groq.com/docs/api-reference",
    output_tokens=_EFFORT_OUTPUT_TOKENS,
)
_GPT_OSS_CEREBRAS = replace(
    _GPT_OSS_GROQ, source="https://inference-docs.cerebras.ai/capabilities/reasoning"
)

# ── Anthropic Claude (Messages API) ──
# https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting:
# Claude 4.5/4.6/4.7/4.8 do not think unless asked; Sonnet 5 and Opus 5 think
# by default and accept {"type": "disabled"}; Sonnet 5.5, Opus 5.5, Fable,
# and Mythos always think. Temperature is incompatible with thinking on 4.5
# and 4.6 and rejected outright from 4.7 on.

_CLAUDE_DOCS = "https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking"
_CLAUDE_BUDGET_DOCS = (
    "https://platform.claude.com/docs/en/build-with-claude/extended-thinking"
)

#: Claude 4.6: adaptive thinking off unless requested; effort has no xhigh.
_CLAUDE_46 = ReasoningRule(
    wire=ReasoningWire.ANTHROPIC_ADAPTIVE,
    levels=("low", "medium", "high", "max"),
    provider_default=None,
    source=_CLAUDE_DOCS,
    output_tokens=_ANTHROPIC_OUTPUT_TOKENS,
    off=ReasoningOff.OMIT,
    temperature=TemperaturePolicy.OMIT_WHILE_THINKING,
)
#: Claude Opus 4.7 / 4.8: adaptive only, off unless requested.
_CLAUDE_47_48 = ReasoningRule(
    wire=ReasoningWire.ANTHROPIC_ADAPTIVE,
    levels=("low", "medium", "high", "xhigh", "max"),
    provider_default=None,
    source=_CLAUDE_DOCS,
    output_tokens=_ANTHROPIC_OUTPUT_TOKENS,
    off=ReasoningOff.OMIT,
    temperature=TemperaturePolicy.OMIT_ALWAYS,
)
#: Claude Sonnet 5 / Opus 5: adaptive by default at effort high; disabling
#: is accepted at effort high or below (no effort is sent with it).
_CLAUDE_5 = replace(_CLAUDE_47_48, provider_default="high", off=ReasoningOff.EXPLICIT)
#: Claude Sonnet 5.5, Fable, Mythos: always think at effort high by default.
_CLAUDE_ALWAYS_THINKING = replace(_CLAUDE_47_48, provider_default="high", off=None)
#: Claude Opus 5.5: always thinks; its effort default is medium.
_CLAUDE_OPUS_55 = replace(_CLAUDE_ALWAYS_THINKING, provider_default="medium")
#: Claude 4.5 generation: manual budget thinking only (adaptive is a 400,
#: and effort is a 400 on Sonnet 4.5 / Haiku 4.5, so it is never sent).
#: budget_tokens must be >= 1024 and < max_tokens.
_CLAUDE_45_BUDGET = ReasoningRule(
    wire=ReasoningWire.ANTHROPIC_BUDGET,
    levels=BUDGET_RUNGS,
    provider_default=None,
    source=_CLAUDE_BUDGET_DOCS,
    budgets=(4_096, 8_192, 12_288, 16_384),
    output_tokens=_ANTHROPIC_OUTPUT_TOKENS,
    off=ReasoningOff.OMIT,
    temperature=TemperaturePolicy.OMIT_WHILE_THINKING,
)

#: Claude on AWS Bedrock Converse takes the same thinking/effort keys through
#: additionalModelRequestFields, with the same per-model rules
#: (https://docs.aws.amazon.com/bedrock/latest/userguide/claude-messages-adaptive-thinking.html,
#: .../claude-messages-extended-thinking.html). Ids and inference-profile
#: prefixes come from each model's AWS model card.
_BEDROCK_DOCS = (
    "https://docs.aws.amazon.com/bedrock/latest/userguide/"
    "claude-messages-adaptive-thinking.html"
)
_BEDROCK_CLAUDE_46 = replace(_CLAUDE_46, source=_BEDROCK_DOCS)
_BEDROCK_CLAUDE_47_48 = replace(_CLAUDE_47_48, source=_BEDROCK_DOCS)
_BEDROCK_CLAUDE_5 = replace(_CLAUDE_5, source=_BEDROCK_DOCS)
_BEDROCK_CLAUDE_ALWAYS_THINKING = replace(_CLAUDE_ALWAYS_THINKING, source=_BEDROCK_DOCS)
_BEDROCK_CLAUDE_OPUS_55 = replace(_CLAUDE_OPUS_55, source=_BEDROCK_DOCS)
_BEDROCK_CLAUDE_45_BUDGET = replace(
    _CLAUDE_45_BUDGET,
    source=(
        "https://docs.aws.amazon.com/bedrock/latest/userguide/"
        "claude-messages-extended-thinking.html"
    ),
)


REASONING_RULES: Mapping[str, Mapping[str, ReasoningRule]] = {
    "openai": _surface(
        _models(
            _OPENAI_GPT5,
            "gpt-5",
            "gpt-5-2025-08-07",
            "gpt-5-mini",
            "gpt-5-mini-2025-08-07",
            "gpt-5-nano",
            "gpt-5-nano-2025-08-07",
        ),
        _models(
            _OPENAI_O_SERIES,
            "o3",
            "o3-2025-04-16",
            "o3-mini",
            "o3-mini-2025-01-31",
            "o4-mini",
            "o4-mini-2025-04-16",
        ),
        _models(_OPENAI_GPT51, "gpt-5.1", "gpt-5.1-2025-11-13"),
        _models(
            _OPENAI_GPT52_TO_54,
            "gpt-5.2",
            "gpt-5.2-2025-12-11",
            "gpt-5.4",
            "gpt-5.4-2026-03-05",
            "gpt-5.4-mini",
            "gpt-5.4-mini-2026-03-17",
            "gpt-5.4-nano",
            "gpt-5.4-nano-2026-03-17",
        ),
        _models(_OPENAI_GPT55, "gpt-5.5", "gpt-5.5-2026-04-23"),
        _models(
            _OPENAI_GPT56_PLUS,
            "gpt-5.6",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "gpt-5.6-luna",
            "gpt-6-sol",
            "gpt-6-luna",
        ),
        _models(_OPENAI_GPT6_ALWAYS_REASONING, "gpt-6-astra"),
        _models(_OPENAI_GPT61_SOL, "gpt-6.1-sol"),
    ),
    "openai_subscription": _surface(
        _models(_CODEX_GPT55, "gpt-5.5"),
        _models(
            _CODEX_MAX_LADDER_LOW_DEFAULT, "gpt-5.6-sol", "gpt-6-astra", "gpt-6.1-sol"
        ),
        _models(
            _CODEX_MAX_LADDER_MEDIUM_DEFAULT,
            "gpt-5.6-terra",
            "gpt-5.6-luna",
            "gpt-6-sol",
            "gpt-6-luna",
        ),
    ),
    "openrouter": _surface(
        _models(
            _OPENROUTER_CLAUDE_BUDGET,
            "anthropic/claude-sonnet-4.5",
            "anthropic/claude-haiku-4.5",
            "anthropic/claude-opus-4.5",
        ),
        _models(
            _OPENROUTER_CLAUDE_46,
            "anthropic/claude-sonnet-4.6",
            "anthropic/claude-opus-4.6",
        ),
        _models(_OPENROUTER_OPENAI_GPT5, "openai/gpt-5", "openai/gpt-5-mini"),
        _models(_OPENROUTER_OPENAI_GPT51, "openai/gpt-5.1"),
        _models(
            _OPENROUTER_OPENAI_XHIGH,
            "openai/gpt-5.2",
            "openai/gpt-5.4",
            "openai/gpt-5.5",
        ),
        _models(
            _OPENROUTER_OPENAI_MAX,
            "openai/gpt-5.6-sol",
            "openai/gpt-5.6-terra",
            "openai/gpt-5.6-luna",
            "openai/gpt-6-sol",
            "openai/gpt-6-luna",
        ),
        _models(
            _OPENROUTER_OPENAI_MAX_MANDATORY,
            "openai/gpt-6-astra",
            "openai/gpt-6.1-sol",
        ),
    ),
    "gemini": _surface(
        _models(_GEMINI_25_PRO, "gemini-2.5-pro"),
        _models(_GEMINI_25_FLASH, "gemini-2.5-flash"),
        _models(_GEMINI_25_FLASH_LITE, "gemini-2.5-flash-lite"),
        _models(
            replace(_GEMINI_3_WITH_MINIMAL, provider_default="high"),
            "gemini-3-flash-preview",
        ),
        _models(
            replace(_GEMINI_3_WITHOUT_MINIMAL, provider_default="high"),
            "gemini-3.1-pro-preview",
            "gemini-3.1-pro-preview-customtools",
        ),
        _models(_GEMINI_3_WITH_MINIMAL, "gemini-3.5-flash", "gemini-3.6-flash"),
        _models(_GEMINI_3_WITHOUT_MINIMAL, "gemini-3.7-flash", "gemini-3.8-flash"),
        _models(
            replace(_GEMINI_3_WITH_MINIMAL, provider_default="minimal"),
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
        ),
    ),
    "grok": _surface(
        _models(_XAI_GROK_43, "grok-4.3", "grok-4.3-latest"),
        _models(_XAI_GROK_45, "grok-4.5", "grok-4.5-latest"),
        _models(_XAI_GROK_46_PLUS, "grok-4.6", "grok-4.7"),
    ),
    "deepseek": _surface(
        _models(
            _DEEPSEEK_V4,
            "deepseek-flash",
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "deepseek-v4-flash-vision-exp",
        ),
    ),
    "glm": _surface(
        _models(_GLM_53, "glm-5.3", "glm-5.3-flash"),
        _models(_GLM_52, "glm-5.2"),
    ),
    "moonshot": _surface(
        _models(_KIMI_K3, "kimi-k3"),
    ),
    "groq": _surface(
        _models(
            _GPT_OSS_GROQ,
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "openai/gpt-oss-safeguard-20b",
        ),
    ),
    "cerebras": _surface(
        _models(_GPT_OSS_CEREBRAS, "gpt-oss-120b"),
    ),
    "anthropic": _surface(
        _models(_CLAUDE_46, "claude-sonnet-4-6", "claude-opus-4-6"),
        _models(_CLAUDE_47_48, "claude-opus-4-7", "claude-opus-4-8"),
        _models(_CLAUDE_5, "claude-sonnet-5", "claude-opus-5"),
        _models(
            _CLAUDE_ALWAYS_THINKING,
            "claude-sonnet-5-5",
            "claude-fable-5",
            "claude-fable-5-1",
            "claude-mythos-5",
            "claude-mythos-5-1",
        ),
        _models(_CLAUDE_OPUS_55, "claude-opus-5-5"),
        _models(
            _CLAUDE_45_BUDGET,
            "claude-haiku-4-5",
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-5",
            "claude-sonnet-4-5-20250929",
            "claude-opus-4-5",
            "claude-opus-4-5-20251101",
        ),
    ),
    "bedrock": _surface(
        _models(
            _BEDROCK_CLAUDE_45_BUDGET,
            *_bedrock_ids(
                "anthropic.claude-haiku-4-5-20251001-v1:0",
                "us",
                "eu",
                "au",
                "jp",
                "in",
                "global",
            ),
            *_bedrock_ids(
                "anthropic.claude-sonnet-4-5-20250929-v1:0",
                "us",
                "eu",
                "au",
                "jp",
                "global",
            ),
            *_bedrock_ids(
                "anthropic.claude-opus-4-5-20251101-v1:0", "us", "eu", "global"
            ),
        ),
        _models(
            _BEDROCK_CLAUDE_46,
            *_bedrock_ids(
                "anthropic.claude-sonnet-4-6", "us", "eu", "au", "jp", "global"
            ),
            *_bedrock_ids("anthropic.claude-opus-4-6-v1", "us", "eu", "au", "global"),
        ),
        _models(
            _BEDROCK_CLAUDE_47_48,
            *_bedrock_ids(
                "anthropic.claude-opus-4-7", "us", "eu", "jp", "au", "global"
            ),
            *_bedrock_ids(
                "anthropic.claude-opus-4-8", "us", "eu", "jp", "au", "global"
            ),
        ),
        _models(
            _BEDROCK_CLAUDE_5,
            *_bedrock_ids(
                "anthropic.claude-sonnet-5", "us", "eu", "au", "in", "global"
            ),
            *_bedrock_ids("anthropic.claude-opus-5", "us", "eu", "au", "in", "global"),
        ),
        _models(
            _BEDROCK_CLAUDE_ALWAYS_THINKING,
            *_bedrock_ids("anthropic.claude-fable-5", "us", "global"),
            *_bedrock_ids("anthropic.claude-fable-5-1", "us", "global"),
        ),
        _models(
            _BEDROCK_CLAUDE_OPUS_55,
            *_bedrock_ids(
                "anthropic.claude-opus-5-5", "us", "eu", "au", "jp", "global"
            ),
        ),
    ),
}
