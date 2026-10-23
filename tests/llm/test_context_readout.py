# -*- coding: utf-8 -*-
"""The reasoning menu's context and cache readout, and the KV cache under it.

The readout shows a session's last decision request (its input against the
budget, how much the provider served from cache, and how long that cache
lasts). These tests pin:

* recording it changes nothing that is sent (payloads stay byte-identical);
* it is recorded on the session path and on the stateless path alike;
* every provider whose profile accumulates a session history takes the
  session path (a hand-kept subset of them used to re-send the whole prompt
  every turn);
* cache facts come from the model catalog, with defaults for what it does
  not list;
* the wire payloads the menu reads.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from agent_core.core.impl.llm import LLMCallType
from agent_core.core.models.catalog import (
    CacheLifetime,
    CacheLifetimeKind,
    ModelLimits,
    reports_cached_tokens,
)
from agent_core.core.models.reasoning import ReasoningChoice
from agent_core.core.models.registry import session_cc_providers

from .golden.conftest import build_interface

ACTION = LLMCallType.ACTION_SELECTION

#: A catalog of made-up models, so these tests pin behavior, not provider data.
FAKE_CATALOG = {
    "surfaces": {"quiet": {"reports_cached_tokens": False}},
    "models": {
        "openai/timed-model": {
            "context_window": 400_000,
            "cache_lifetime": {"kind": "exact", "seconds": 1800},
        },
        "openai/untimed-model": {"context_window": 128_000},
    },
}


@pytest.fixture
def fake_catalog(monkeypatch):
    import agent_core.core.models.catalog as catalog

    monkeypatch.setattr(catalog, "_catalog", lambda: FAKE_CATALOG)


# ──────────────────────── recording the last request ────────────────────────


def test_the_usage_key_changes_nothing_sent(monkeypatch):
    iface, recorder = build_interface(monkeypatch, "openai", "gpt-6-luna")
    asyncio.run(iface.generate_response_async("SYSTEM", "USER"))
    asyncio.run(
        iface.generate_response_async("SYSTEM", "USER", usage_key=f"s1:{ACTION}")
    )
    first, second = recorder.calls
    assert first["payload"] == second["payload"]


def test_a_stateless_decision_records_its_request(monkeypatch):
    iface, _ = build_interface(monkeypatch, "openai", "gpt-6-luna")
    asyncio.run(iface.generate_response_async("SYSTEM", "USER"))
    assert iface.last_request("s1", ACTION) is None  # no key: not a decision

    before = time.time()
    asyncio.run(
        iface.generate_response_async("SYSTEM", "USER", usage_key=f"s1:{ACTION}")
    )
    usage = iface.last_request("s1", ACTION)
    assert usage is not None
    assert (usage.input_tokens, usage.cached_tokens) == (100, 0)
    assert (usage.surface, usage.model) == ("openai", "gpt-6-luna")
    assert before <= usage.started_at <= time.time()


def test_a_session_decision_records_its_request(monkeypatch):
    iface, _ = build_interface(monkeypatch, "openai", "gpt-6-luna")
    iface.create_session_cache("s1", ACTION, "SYSTEM")
    iface.generate_response_with_session("s1", ACTION, "USER", log_response=False)
    usage = iface.last_request("s1", ACTION)
    assert usage is not None and usage.input_tokens == 100


def test_the_record_outlives_a_fold_but_not_the_session(monkeypatch):
    iface, _ = build_interface(monkeypatch, "openai", "gpt-6-luna")
    iface.create_session_cache("s1", ACTION, "SYSTEM")
    iface.generate_response_with_session("s1", ACTION, "USER", log_response=False)
    iface.reset_session_history("s1", ACTION)  # a fold
    assert iface.last_request("s1", ACTION) is not None
    iface.end_all_session_caches("s1")
    assert iface.last_request("s1", ACTION) is None


# ─────────────────────────── the session path ───────────────────────────


@pytest.mark.parametrize("provider", sorted(session_cc_providers()))
def test_every_accumulating_provider_takes_the_session_path(monkeypatch, provider):
    iface, _ = build_interface(monkeypatch, provider, "some-model")
    iface.create_session_cache("s1", ACTION, "SYSTEM")
    assert iface.has_session_cache("s1", ACTION)


# ─────────────────────────── cache facts ───────────────────────────


def test_the_cache_lifetime_comes_from_the_catalog(monkeypatch, fake_catalog):
    timed, _ = build_interface(monkeypatch, "openai", "timed-model")
    assert timed.prompt_cache_lifetime() == CacheLifetime(CacheLifetimeKind.EXACT, 1800)
    # Catalogued without one, or not catalogued at all: no countdown.
    untimed, _ = build_interface(monkeypatch, "openai", "untimed-model")
    assert untimed.prompt_cache_lifetime() is None
    unknown, _ = build_interface(monkeypatch, "openai", "unknown-model")
    assert unknown.prompt_cache_lifetime() is None


def test_cached_input_is_reported_unless_the_catalog_says_not(fake_catalog):
    assert reports_cached_tokens("quiet") is False
    assert reports_cached_tokens("openai") is True  # not listed: the default


# ─────────────────────────── budgets per choice ───────────────────────────


def test_each_choice_has_its_own_budget(monkeypatch):
    import agent_core.core.impl.llm.interface as interface_module

    iface, _ = build_interface(monkeypatch, "openai", "gpt-6-luna")
    iface.max_tokens = 8000
    monkeypatch.setattr(
        interface_module, "model_limits", lambda *a: ModelLimits(200_000)
    )
    assert iface.input_budget_for(ReasoningChoice.OFF) == 192_000
    assert iface.input_budget_for(ReasoningChoice.HIGH) == 168_000
    assert iface.input_budget_for(ReasoningChoice.XHIGH) == 136_000


# ─────────────────────────── wire payloads ───────────────────────────


def _adapter(llm, sent):
    async def send_to(_ws, message):
        sent.append(message)

    return SimpleNamespace(
        _controller=SimpleNamespace(agent=SimpleNamespace(llm=llm)),
        _send_to=send_to,
    )


def test_the_reasoning_options_carry_budgets_and_cache_facts(monkeypatch, fake_catalog):
    from app.ui_layer.adapters.browser_adapter import BrowserAdapter

    iface, _ = build_interface(monkeypatch, "openai", "timed-model")
    sent = []
    asyncio.run(
        BrowserAdapter._handle_reasoning_options_get(_adapter(iface, sent), None)
    )
    data = sent[0]["data"]
    assert data["surface"] == "openai"
    assert set(data["inputBudgets"]) == {choice.value for choice in ReasoningChoice}
    assert data["cacheLifetime"] == {"kind": "exact", "seconds": 1800}
    assert data["reportsCachedTokens"] is True


def test_the_session_info_carries_the_last_request(monkeypatch):
    from agent_core.core.session import Session
    from app.ui_layer.adapters.browser_adapter import BrowserAdapter

    iface, _ = build_interface(monkeypatch, "openai", "gpt-6-luna")
    adapter = _adapter(iface, [])
    session = Session.from_dict({"id": "s1"})
    assert BrowserAdapter._session_info(adapter, session)["lastRequest"] is None

    asyncio.run(
        iface.generate_response_async("SYSTEM", "USER", usage_key=f"s1:{ACTION}")
    )
    last = BrowserAdapter._session_info(adapter, session)["lastRequest"]
    assert last["inputTokens"] == 100 and last["cachedTokens"] == 0
    assert last["surface"] == "openai" and last["model"] == "gpt-6-luna"
    assert abs(last["startedAt"] - time.time() * 1000) < 60_000
