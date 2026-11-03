# -*- coding: utf-8 -*-
"""
A fold the user asks for (/fold, the chat input's context menu): the fold a
request that would not fit gets, made early. It never drops events without a
summary, never lands while a decision request is in flight, and the session
info tells the chat input how far it shrank the stream.

See ActionRouter.fold_session and EventStream.summarize_by_LLM(prune=False).
"""

import asyncio
from types import SimpleNamespace

import pytest

from agent_core.core.impl.event_stream.event_stream import EventStream


class _LLM:
    consecutive_failures = 0
    _max_consecutive_failures = 5

    def __init__(self, reply="SUMMARY", error=None):
        self.reply, self.error, self.calls = reply, error, 0

    def generate_response(self, user_prompt=None, prompt_name=None, **kw):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.reply


def _stream(llm, events=400):
    es = EventStream(llm=llm, temp_dir=None)
    for i in range(events):
        es.log("action_end", f"action {i} produced output " + "x " * 50)
    es.mark_delivered()
    return es


# ───────────────────────────── the stream ─────────────────────────────


def test_a_fold_reports_and_records_how_far_it_shrank_the_stream():
    es = _stream(_LLM())
    assert es.last_fold is None
    freed = es.summarize_by_LLM(keep_tokens=100, prune=False)
    assert freed > 0 and es.head_summary == "SUMMARY"
    assert es.last_fold is not None and es.last_fold.freed_tokens == freed


def test_a_requested_fold_does_not_prune_what_is_too_small_to_summarize():
    llm = _LLM()
    es = _stream(llm, events=8)
    events = list(es.tail_events)
    assert es.summarize_by_LLM(keep_tokens=0, prune=False) == 0
    assert llm.calls == 0 and es.tail_events == events and es.last_fold is None


def test_a_requested_fold_that_fails_raises_and_keeps_the_stream():
    es = _stream(_LLM(error=RuntimeError("provider down")))
    events = list(es.tail_events)
    with pytest.raises(RuntimeError, match="provider down"):
        es.summarize_by_LLM(keep_tokens=100, prune=False)
    assert es.tail_events == events and es.head_summary is None


def test_a_requested_fold_given_an_empty_summary_raises_and_keeps_the_stream():
    es = _stream(_LLM(reply="  "))
    events = list(es.tail_events)
    with pytest.raises(RuntimeError):
        es.summarize_by_LLM(keep_tokens=100, prune=False)
    assert es.tail_events == events


def test_a_budget_fold_still_prunes_when_the_summary_fails():
    es = _stream(_LLM(error=RuntimeError("provider down")))
    before = len(es.tail_events)
    assert es.summarize_by_LLM(keep_tokens=100) > 0
    assert len(es.tail_events) < before


def test_clearing_the_stream_forgets_its_fold():
    es = _stream(_LLM())
    es.summarize_by_LLM(keep_tokens=100, prune=False)
    es.clear()
    assert es.last_fold is None


# ───────────────────────────── the router ─────────────────────────────


class _Streams:
    def __init__(self, stream):
        self.stream = stream

    def has_stream(self, session_id):
        return session_id == "s1"

    def get_stream_by_id(self, session_id):
        return self.stream


def _router(monkeypatch, stream):
    from agent_core.core.impl.action import router as router_module

    monkeypatch.setattr(
        router_module, "get_event_stream_manager", lambda: _Streams(stream)
    )
    context = SimpleNamespace(make_prompt=lambda **kw: ("SYSTEM", ""))
    # No session history: the summary goes to the standalone call.
    llm = SimpleNamespace(
        input_budget=lambda: 900_000,
        generate_side_response_with_session=lambda *a, **k: None,
    )
    return router_module.ActionRouter(None, llm, context)


def test_a_requested_fold_waits_for_the_decision_in_flight(monkeypatch):
    stream = _stream(_LLM(), events=1000)
    router = _router(monkeypatch, stream)

    async def scenario():
        lock = router._decision_lock("s1")
        await lock.acquire()  # a decision request is in flight
        fold = asyncio.create_task(router.fold_session("s1"))
        await asyncio.sleep(0.05)
        assert not fold.done() and stream.head_summary is None
        lock.release()
        return await fold

    assert asyncio.run(scenario()) > 0
    assert stream.head_summary == "SUMMARY"


def test_a_session_without_its_own_stream_has_nothing_to_fold(monkeypatch):
    llm = _LLM()
    router = _router(monkeypatch, _stream(llm))
    assert asyncio.run(router.fold_session("other")) == 0
    assert llm.calls == 0


# ─────────────────────────── the chat input ───────────────────────────


def test_the_session_info_carries_the_fold_and_its_progress():
    from agent_core.core.session import Session
    from app.ui_layer.adapters.browser_adapter import BrowserAdapter

    stream = _stream(_LLM())
    agent = SimpleNamespace(
        llm=SimpleNamespace(last_request=lambda *a: None),
        event_stream_manager=_Streams(stream),
        folding_sessions={"s1"},
    )
    adapter = SimpleNamespace(_controller=SimpleNamespace(agent=agent))
    session = Session.from_dict({"id": "s1"})

    info = BrowserAdapter._session_info(adapter, session)
    assert info["folding"] is True and info["lastFold"] is None

    freed = stream.summarize_by_LLM(keep_tokens=100, prune=False)
    agent.folding_sessions.clear()
    info = BrowserAdapter._session_info(adapter, session)
    assert info["folding"] is False
    assert info["lastFold"]["freedTokens"] == freed
    assert info["lastFold"]["at"] == round(stream.last_fold.at * 1000)


def test_fold_says_when_there_is_nothing_to_fold():
    from app.ui_layer.commands.builtin.fold import FoldCommand

    messages = []

    async def fold_session(session_id):
        return 0

    agent = SimpleNamespace(folding_sessions=set(), fold_session=fold_session)
    command = FoldCommand(SimpleNamespace(agent=agent))
    command.emit_message = lambda message, kind, session_id=None: messages.append(
        (message, kind, session_id)
    )

    async def scenario():
        result = await command.execute([], session_id="s1")
        await asyncio.sleep(0)
        return result

    assert asyncio.run(scenario()).success
    assert messages == [
        ("Nothing to fold yet: recent events always stay in full.", "system", "s1")
    ]
