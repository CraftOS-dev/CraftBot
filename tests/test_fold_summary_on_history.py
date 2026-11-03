# -*- coding: utf-8 -*-
"""A fold's summary is written on the session's history (prompt audit T5).

The summary call used to be a standalone request with no system prompt that
was sent every folded event again, so it was never served from the
provider's cache. When the session has a history (which holds every event
being folded), the summary is now asked for as one more message on it: a
side request that reads the history from the cache and does not join it.
These tests pin:

* the stream takes the summary from that side request, and falls back to
  the standalone call when there is none, it fails, or its reply holds none;
* the router asks on the history the session continues on (its system
  prompt), for a budget fold and a requested (/fold) one; an overflow fold
  stays standalone;
* the summary is read from the JSON reply.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agent_core.core.impl.action import router as router_module
from agent_core.core.impl.event_stream.event_stream import EventStream
from agent_core.core.impl.llm import LLMCallType

ACTION = LLMCallType.ACTION_SELECTION


class _StandaloneLLM:
    """The stream's own LLM: the standalone summary call."""

    consecutive_failures = 0
    _max_consecutive_failures = 5

    def __init__(self):
        self.calls = 0

    def generate_response(self, user_prompt=None, prompt_name=None, **kw):
        self.calls += 1
        return "STANDALONE SUMMARY"


def _stream(llm, events=400):
    es = EventStream(llm=llm, temp_dir=None)
    for i in range(events):
        es.log("action_end", f"action {i} produced output " + "x " * 50)
    es.mark_delivered()
    return es


# ── the stream ───────────────────────────────────────────────────────────────


def test_the_summary_comes_from_the_history_when_there_is_one():
    llm = _StandaloneLLM()
    es = _stream(llm)
    seen = []

    def on_history(last_event):
        seen.append(last_event)
        return "SUMMARY ON HISTORY"

    assert es.summarize_by_LLM(keep_tokens=100, summarizer=on_history) > 0
    assert es.head_summary == "SUMMARY ON HISTORY"
    assert llm.calls == 0
    # It is told where the fold ends: the last event folded, not one kept.
    (last_folded,) = seen
    assert last_folded.event.kind == "action_end"
    assert last_folded not in es.tail_events


def test_the_standalone_call_stands_in_when_the_history_gives_no_summary():
    for summarizer in (lambda e: None, lambda e: "   "):
        llm = _StandaloneLLM()
        es = _stream(llm)
        es.summarize_by_LLM(keep_tokens=100, summarizer=summarizer)
        assert es.head_summary == "STANDALONE SUMMARY" and llm.calls == 1


def test_the_standalone_call_stands_in_when_the_history_call_fails():
    def fails(last_event):
        raise RuntimeError("request too large")

    llm = _StandaloneLLM()
    es = _stream(llm)
    es.summarize_by_LLM(keep_tokens=100, summarizer=fails)
    assert es.head_summary == "STANDALONE SUMMARY" and llm.calls == 1


# ── reading the reply ────────────────────────────────────────────────────────


def test_the_summary_is_read_from_the_json_reply():
    read = router_module._summary_from_reply
    assert read('{"summary": " The user asked X. "}') == "The user asked X."
    assert read('Here: {"summary": "S", "extra": 1}') == "S"
    for reply in (
        None,
        "",
        "plain text",
        '{"reasoning": "r", "actions": []}',
        '{"summary": ""}',
    ):
        assert read(reply) is None


# ── the router ───────────────────────────────────────────────────────────────


class _SessionLLM:
    def __init__(self):
        self.side_requests = []

    def input_budget(self):
        return 900_000

    def generate_side_response_with_session(
        self, task_id, call_type, user_prompt, system_prompt, **kwargs
    ):
        self.side_requests.append(
            {
                "task_id": task_id,
                "call_type": call_type,
                "request": user_prompt,
                "system": system_prompt,
                "metadata": kwargs.get("call_metadata"),
            }
        )
        return json.dumps({"summary": "SUMMARY ON HISTORY"})


def _router(llm, context=None):
    return router_module.ActionRouter(
        None, llm, context or SimpleNamespace(make_prompt=lambda **kw: ("BASE", ""))
    )


def test_a_fold_with_a_history_asks_on_it(monkeypatch):
    from app import config as app_config

    monkeypatch.setattr(app_config, "get_keep_recent_tokens", lambda: 100)
    llm = _SessionLLM()
    es = _stream(_StandaloneLLM())
    _router(llm)._fold(es, "SYSTEM", "", history=("s1", ACTION, "HISTORY SYSTEM"))

    (side,) = llm.side_requests
    assert side["task_id"] == "s1" and side["call_type"] == ACTION
    assert side["system"] == "HISTORY SYSTEM"  # the prompt the history continues on
    assert "<fold_request>" in side["request"] and "[action_end]" in side["request"]
    assert side["metadata"] == {"request": "summary", "on": "history"}
    assert es.head_summary == "SUMMARY ON HISTORY"


def test_a_fold_without_a_history_is_standalone(monkeypatch):
    from app import config as app_config

    monkeypatch.setattr(app_config, "get_keep_recent_tokens", lambda: 100)
    llm, standalone = _SessionLLM(), _StandaloneLLM()
    es = _stream(standalone)
    _router(llm)._fold(es, "SYSTEM", "")
    assert llm.side_requests == [] and standalone.calls == 1


def test_a_requested_fold_asks_on_the_history_the_session_continues_on(monkeypatch):
    from app import config as app_config

    monkeypatch.setattr(app_config, "get_keep_recent_tokens", lambda: 100)
    es = _stream(_StandaloneLLM())
    monkeypatch.setattr(
        router_module,
        "get_event_stream_manager",
        lambda: SimpleNamespace(
            has_stream=lambda sid: True, get_stream_by_id=lambda sid: es
        ),
    )
    llm = _SessionLLM()
    router = _router(llm)
    router._history_instructions[f"s1:{ACTION}"] = "RULES THE HISTORY STARTED WITH"

    assert asyncio.run(router.fold_session("s1")) > 0
    (side,) = llm.side_requests
    assert side["system"] == "BASE\n\nRULES THE HISTORY STARTED WITH"


def test_an_overflow_fold_stays_standalone():
    import inspect

    src = inspect.getsource(router_module.ActionRouter._prompt_for_decision)
    overflow = src[src.index("except LLMContextOverflowError") :]
    overflow = overflow[: overflow.index("continue")]
    assert "self._fold(stream, system_prompt, static_prompt)" in overflow
    assert "history=" not in overflow
