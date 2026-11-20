# -*- coding: utf-8 -*-
"""A session call reports whether its exchange reached the session history
(prompt audit T3).

The router marks a request's events as sent only when the history recorded
the exchange, and continues a history with a retry's feedback only then.
These tests pin, for every provider with a session path (through the real
interface code, with recording fakes for the network):

* a served session call is recorded, turn after turn;
* a failed call, and a call served from a history of its own (a fallback
  provider), are not;
* the call's metadata reaches the captured record.
"""

from __future__ import annotations

import pytest

from agent_core.core.impl.llm import LLMCallType

from .golden.conftest import GOLDEN_SYSTEM_PROMPT, build_interface

ACTION = LLMCallType.ACTION_SELECTION

SESSION_PROVIDERS = [
    ("anthropic", "claude-sonnet-4-6"),
    ("bedrock", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("openai", "gpt-5.2-2025-12-11"),
    ("deepseek", "deepseek-chat"),
    ("grok", "grok-3"),
    ("openrouter", "anthropic/claude-sonnet-4.5"),
    ("openrouter", "deepseek/deepseek-chat"),
    ("gemini", "gemini-2.5-pro"),
    ("byteplus", "seed-2-0-pro-260328"),
]


def _session(monkeypatch, provider, model):
    iface, recorder = build_interface(monkeypatch, provider, model)
    iface.create_session_cache("s1", ACTION, GOLDEN_SYSTEM_PROMPT)
    assert iface.has_session_cache("s1", ACTION)
    return iface, recorder


@pytest.mark.parametrize("provider, model", SESSION_PROVIDERS)
def test_a_served_session_call_is_recorded(monkeypatch, provider, model):
    iface, _ = _session(monkeypatch, provider, model)
    assert iface.session_turn_recorded("s1", ACTION) is False
    for turn in range(3):
        iface.generate_response_with_session(
            "s1", ACTION, f"turn {turn}", log_response=False
        )
        assert iface.session_turn_recorded("s1", ACTION) is True


@pytest.mark.parametrize("provider, model", SESSION_PROVIDERS)
def test_a_failed_or_fallback_served_call_is_not_recorded(monkeypatch, provider, model):
    iface, _ = _session(monkeypatch, provider, model)
    iface.generate_response_with_session("s1", ACTION, "turn 0", log_response=False)

    def fails(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(iface, "_generate_response_with_session_sync", fails)
    with pytest.raises(RuntimeError):
        iface.generate_response_with_session("s1", ACTION, "turn 1", log_response=False)
    assert iface.session_turn_recorded("s1", ACTION) is False

    # A fallback provider answers from a history of its own: nothing grows here.
    monkeypatch.setattr(
        iface, "_generate_response_with_session_sync", lambda *a, **k: "answer"
    )
    assert (
        iface.generate_response_with_session("s1", ACTION, "turn 2", log_response=False)
        == "answer"
    )
    assert iface.session_turn_recorded("s1", ACTION) is False


@pytest.mark.parametrize("provider, model", SESSION_PROVIDERS)
def test_call_metadata_reaches_the_captured_record(monkeypatch, provider, model):
    iface, _ = _session(monkeypatch, provider, model)
    records = []
    iface._record_llm_call = records.append

    iface.generate_response_with_session(
        "s1",
        ACTION,
        "turn",
        log_response=False,
        call_metadata={"request": "full", "reason": "first"},
    )
    iface.generate_response_with_session("s1", ACTION, "turn", log_response=False)
    assert records[0].metadata == {"request": "full", "reason": "first"}
    assert records[-1].metadata == {}
