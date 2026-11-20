# -*- coding: utf-8 -*-
"""A side request continues a session's history without joining it
(prompt audit T5, the fold summary written on the history).

For every provider with a session path (through the real interface code,
with recording fakes for the network), these tests pin:

* the side request is sent the session's history plus its own message, so
  the provider serves the history from its cache;
* neither the request nor its reply joins the history: the next session
  request is exactly what it would have been, and BytePlus' server-side
  chain keeps its head;
* the session's last-request readout stays the session's own, and the call
  is captured with its metadata;
* without a history there is nothing to continue.
"""

from __future__ import annotations

import json

import pytest

from agent_core.core.impl.llm import LLMCallType
from agent_core.core.impl.llm.cache import BytePlusContextOverflowError

from .golden.conftest import GOLDEN_SYSTEM_PROMPT, build_interface

ACTION = LLMCallType.ACTION_SELECTION
SIDE = "SIDE REQUEST: write the summary"

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


def _session(monkeypatch, provider, model, turns=2):
    iface, recorder = build_interface(monkeypatch, provider, model)
    iface.create_session_cache("s1", ACTION, GOLDEN_SYSTEM_PROMPT)
    for turn in range(turns):
        iface.generate_response_with_session(
            "s1", ACTION, f"session turn {turn}", log_response=False
        )
    return iface, recorder


def _chain_head(iface):
    manager = iface._byteplus_cache_manager
    return manager.get_session_cache("s1", ACTION) if manager else None


@pytest.mark.parametrize("provider, model", SESSION_PROVIDERS)
def test_a_side_request_reads_the_history_and_does_not_join_it(
    monkeypatch, provider, model
):
    iface, recorder = _session(monkeypatch, provider, model)
    history = json.dumps(iface._session_histories, sort_keys=True, default=str)
    head = _chain_head(iface)
    readout = iface.last_request("s1", ACTION)
    records = []
    iface._record_llm_call = records.append

    reply = iface.generate_side_response_with_session(
        "s1",
        ACTION,
        SIDE,
        GOLDEN_SYSTEM_PROMPT,
        prompt_name="EVENT_STREAM_SUMMARIZATION",
        call_metadata={"request": "summary", "on": "history"},
    )

    assert reply
    sent = json.dumps(recorder.calls[-1]["payload"], default=str)
    assert SIDE in sent
    if provider == "byteplus":
        # The server holds the history; the request continues its chain.
        assert recorder.calls[-1]["payload"]["previous_response_id"] == head
    else:
        assert "session turn 1" in sent  # the history, sent ahead of it
    assert json.dumps(iface._session_histories, sort_keys=True, default=str) == history
    assert _chain_head(iface) == head
    assert iface.last_request("s1", ACTION) == readout
    assert records[-1].metadata == {"request": "summary", "on": "history"}

    # The session goes on as if the side request had never been made.
    iface.generate_response_with_session(
        "s1", ACTION, "session turn 2", log_response=False
    )
    assert SIDE not in json.dumps(recorder.calls[-1]["payload"], default=str)


@pytest.mark.parametrize("provider, model", SESSION_PROVIDERS)
def test_without_a_history_there_is_nothing_to_continue(monkeypatch, provider, model):
    iface, recorder = _session(monkeypatch, provider, model, turns=0)
    calls = len(recorder.calls)
    assert iface.has_session_history("s1", ACTION) is False
    assert (
        iface.generate_side_response_with_session(
            "s1", ACTION, SIDE, GOLDEN_SYSTEM_PROMPT
        )
        is None
    )
    assert len(recorder.calls) == calls


@pytest.mark.parametrize("side_request", [True, False])
def test_byteplus_overflow_only_resets_recorded_turns(monkeypatch, side_request):
    iface, _ = _session(monkeypatch, "byteplus", "seed-2-0-pro-260328")
    manager = iface._byteplus_cache_manager
    head = _chain_head(iface)
    readout = iface.last_request("s1", ACTION)
    original = manager._call_responses_api
    attempts = []

    def overflow_on_existing_history(**kwargs):
        attempts.append(kwargs)
        if kwargs.get("previous_response_id"):
            raise BytePlusContextOverflowError("context limit exceeded")
        return original(**kwargs)

    monkeypatch.setattr(manager, "_call_responses_api", overflow_on_existing_history)

    if side_request:
        # The fold must receive the error so it can summarize the actual
        # events, rather than accepting a reply from a fresh, empty session.
        with pytest.raises(BytePlusContextOverflowError):
            iface.generate_side_response_with_session(
                "s1", ACTION, SIDE, GOLDEN_SYSTEM_PROMPT
            )
        assert len(attempts) == 1
        assert _chain_head(iface) == head
        assert iface.last_request("s1", ACTION) == readout
    else:
        # Ordinary recorded turns retain their existing overflow recovery.
        assert iface.generate_response_with_session(
            "s1", ACTION, "session turn 2", log_response=False
        )
        assert len(attempts) == 2
        assert attempts[1]["previous_response_id"] is None
        assert _chain_head(iface) != head
