# -*- coding: utf-8 -*-
"""Decision retries and full-request labels (prompt audit T3).

A retry used to reset the session history and resend the whole prompt with
the error appended (the failed call had already marked the stream sent, so
the retry found "no new events"). These tests pin:

* a reply the history holds is corrected with ONE more turn (the feedback,
  after any new events), never a new history;
* a provider error resends the same request, with no error note in it;
* providers without session histories keep resending the full prompt with
  the feedback, as before;
* an exchange the history did not record (a fallback provider served it)
  leaves its events unsent, so the next request carries them;
* every full request is labeled with why its history started anew.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agent_core.core.impl.action import router as router_module
from agent_core.core.impl.event_stream.event_stream import EventStream
from agent_core.core.impl.llm import LLMCallType

ACTION = LLMCallType.ACTION_SELECTION
END_TURN = (
    '{"reasoning": "r", "actions": [{"action_name": "end_turn", "parameters": {}}]}'
)


class _Stream:
    def __init__(self):
        self.synced = False
        self.pending = True
        self.reason = None

    def has_session_sync(self, call_type):
        return self.synced

    def sync_marker(self, call_type):
        return None

    def mark_delivered(self, *args):
        pass

    def get_event_count(self):
        return 0

    def unsynced_reason(self, call_type):
        return self.reason or "first"


class _Context:
    def __init__(self, stream):
        self.stream = stream

    def make_prompt(self, **kwargs):
        return "BASE", ""

    def get_session_state(self, session_id=None):
        return "<session>S</session>"

    def get_event_stream(self, session_id=None, up_to=None):
        return "<event_stream>E</event_stream>"

    def get_event_stream_delta(self, call_type, session_id=None, up_to=None):
        return ("DELTA", True) if self.stream.pending else ("", False)

    def mark_event_stream_synced(self, call_type, session_id=None, up_to=None):
        self.stream.synced = True
        self.stream.pending = False
        self.stream.reason = None

    def reset_event_stream_sync(self, call_type, session_id=None, reason="reset"):
        self.stream.synced = False
        self.stream.reason = reason


class _LLM:
    """Answers from ``replies`` in order: a string, or an exception to raise.
    ``recorded`` says whether each answered call reached the history."""

    def __init__(self, replies, sessions=True, recorded=None):
        self.replies = list(replies)
        self.sessions = sessions
        self.recorded = list(recorded or [])
        self.sent = []
        self.resets = 0
        self._last_recorded = False

    def has_session_cache(self, task_id, call_type):
        return self.sessions

    def fits_context(self, *args):
        return True

    def reset_session_history(self, task_id, call_type):
        self.resets += 1

    def checkpoint_session(self, *args):
        pass

    def session_turn_recorded(self, task_id, call_type):
        return self._last_recorded

    def _answer(self, system, user, metadata):
        self.sent.append({"system": system, "user": user, "metadata": metadata})
        reply = self.replies.pop(0)
        self._last_recorded = False
        if isinstance(reply, Exception):
            raise reply
        self._last_recorded = self.recorded.pop(0) if self.recorded else True
        return reply

    async def generate_response_with_session_async(
        self,
        task_id,
        call_type,
        user_prompt,
        system_prompt_for_new_session,
        prompt_name=None,
        call_metadata=None,
    ):
        return self._answer(system_prompt_for_new_session, user_prompt, call_metadata)

    async def generate_response_async(
        self, system_prompt, user_prompt, call_metadata=None, **kwargs
    ):
        return self._answer(system_prompt, user_prompt, call_metadata)


def _router(monkeypatch, llm, stream):
    manager = SimpleNamespace(get_stream_by_id=lambda session_id: stream)
    monkeypatch.setattr(router_module, "get_event_stream_manager", lambda: manager)
    library = SimpleNamespace(
        retrieve_action=lambda name: SimpleNamespace(
            name=name, parallelizable=True, mode="ALL"
        )
    )
    router = router_module.ActionRouter(library, llm, _Context(stream))
    monkeypatch.setattr(
        router, "_decision_inputs", lambda session_id: ("<session>S</session>", "INSTR")
    )
    return router


def _decide(router):
    return asyncio.run(
        router._prompt_for_decision(
            "FULL",
            is_task=True,
            session_id="s1",
            render_prompt=lambda up_to=None: "FULL",
            instructions="INSTR",
        )
    )


def test_a_reply_that_did_not_parse_is_corrected_in_the_same_history(monkeypatch):
    stream, llm = _Stream(), _LLM(["not json", END_TURN])
    decision = _decide(_router(monkeypatch, llm, stream))

    assert decision["actions"][0]["action_name"] == "end_turn"
    first, retry = llm.sent
    assert first["user"] == "FULL" and first["metadata"] == {
        "request": "full",
        "reason": "first",
    }
    assert retry["user"].startswith("Previous attempt 1 failed to parse")
    assert "RAW RESPONSE:\nnot json" in retry["user"]
    assert retry["metadata"] == {"request": "correction"}
    assert retry["system"] == first["system"]  # the same history continues
    assert llm.resets == 1  # only the first request started a history


def test_the_feedback_follows_events_that_arrived_meanwhile(monkeypatch):
    stream, llm = _Stream(), _LLM(["not json", END_TURN])
    router = _router(monkeypatch, llm, stream)
    mark = router.context_engine.mark_event_stream_synced

    def mark_then_event(call_type, session_id=None, up_to=None):
        mark(call_type, session_id=session_id, up_to=up_to)
        stream.pending = True  # an event lands while the reply is parsed

    router.context_engine.mark_event_stream_synced = mark_then_event
    _decide(router)
    assert llm.sent[1]["user"].startswith("DELTA\n\nPrevious attempt 1 failed")


def test_a_format_error_is_corrected_in_the_same_history(monkeypatch):
    stream = _Stream()
    llm = _LLM(['{"response": "hello"}', END_TURN])
    router = _router(monkeypatch, llm, stream)

    actions = asyncio.run(router.select_action_in_session("hi", session_id="s1"))

    assert [a["action_name"] for a in actions] == ["end_turn"]
    first, retry = llm.sent
    assert first["metadata"]["request"] == "full"
    assert "OUTPUT FORMAT ERROR (Attempt 1/3)" in retry["user"]
    assert "<event_stream>" not in retry["user"]  # not the whole prompt again
    assert retry["metadata"] == {"request": "correction"}
    assert llm.resets == 1


def test_a_provider_error_resends_the_same_request(monkeypatch):
    stream, llm = _Stream(), _LLM([RuntimeError("provider down"), END_TURN])
    _decide(_router(monkeypatch, llm, stream))
    assert [c["user"] for c in llm.sent] == ["FULL", "FULL"]


def test_stateless_retries_resend_the_prompt_with_the_feedback(monkeypatch):
    stream = _Stream()
    llm = _LLM(["not json", END_TURN], sessions=False)
    _decide(_router(monkeypatch, llm, stream))

    first, retry = llm.sent
    assert first["metadata"] == {"request": "stateless"}
    assert retry["user"].startswith("FULL\n\nPrevious attempt 1 failed to parse")


def test_an_unrecorded_exchange_leaves_its_events_unsent(monkeypatch):
    stream = _Stream()
    llm = _LLM([END_TURN, END_TURN], recorded=[False, True])
    router = _router(monkeypatch, llm, stream)

    _decide(router)
    assert not stream.synced  # a fallback provider answered: not in this history
    _decide(router)
    assert [c["user"] for c in llm.sent] == ["FULL", "FULL"]
    assert stream.synced


def test_a_retry_whose_reply_was_not_recorded_resends_with_the_feedback(monkeypatch):
    stream = _Stream()
    llm = _LLM(["not json", END_TURN], recorded=[False, True])
    _decide(_router(monkeypatch, llm, stream))

    retry = llm.sent[1]
    assert retry["user"].startswith("FULL\n\nPrevious attempt 1 failed to parse")
    assert retry["metadata"] == {"request": "full", "reason": "first", "feedback": True}


@pytest.mark.parametrize("reason", ["skill", "workflow_skill", "provider_change"])
def test_a_full_request_carries_the_reason_of_its_reset(monkeypatch, reason):
    stream, llm = _Stream(), _LLM([END_TURN, END_TURN])
    router = _router(monkeypatch, llm, stream)
    _decide(router)
    router.context_engine.reset_event_stream_sync(
        ACTION, session_id="s1", reason=reason
    )
    stream.pending = True
    _decide(router)
    assert llm.sent[1]["metadata"] == {"request": "full", "reason": reason}


def test_no_new_events_starts_a_new_history_labeled_no_delta(monkeypatch):
    stream, llm = _Stream(), _LLM([END_TURN, END_TURN])
    router = _router(monkeypatch, llm, stream)
    _decide(router)
    _decide(router)  # nothing new since the last request
    assert llm.sent[1]["metadata"] == {"request": "full", "reason": "no_delta"}


# ── the event stream's reasons ───────────────────────────────────────────────


def test_the_event_stream_remembers_why_a_sync_point_went():
    stream = EventStream(llm=None, temp_dir=None)
    assert stream.unsynced_reason(ACTION) == "first"

    stream.log("action_end", "one")
    stream.mark_session_synced(ACTION)
    stream.reset_session_sync(ACTION, reason="skill")
    assert stream.unsynced_reason(ACTION) == "skill"

    stream.mark_session_synced(ACTION)
    with stream._lock:
        stream._clear_sync_points("fold")
    assert stream.unsynced_reason(ACTION) == "fold"

    stream.mark_session_synced(ACTION)
    stream.clear()
    assert stream.unsynced_reason(ACTION) == "clear"


def test_a_stream_read_before_a_restart_reports_restart():
    stream = EventStream(llm=None, temp_dir=None)
    stream.log("action_end", "read before the restart")
    stream.mark_delivered()  # what a boot does for a stream without its session
    assert not stream.has_session_sync(ACTION)
    assert stream.unsynced_reason(ACTION) == "restart"


# ── events logged while a request is in flight ───────────────────────────────
#
# Other code paths write to a session's stream at any time (an integration
# connected in Settings, a platform send from another session, an Agent App
# trigger). An event that lands during a decision call was not in its
# request, so it must go with the next one, never be marked sent unread.


class _StreamContext:
    """Routes the router's stream calls to a real EventStream."""

    def __init__(self, stream):
        self.stream = stream

    def make_prompt(self, **kwargs):
        return "BASE", ""

    def get_event_stream_delta(self, call_type, session_id=None, up_to=None):
        delta, has_delta = self.stream.get_delta_events(call_type, up_to=up_to)
        return (delta, True) if has_delta else ("", False)

    def mark_event_stream_synced(self, call_type, session_id=None, up_to=None):
        self.stream.mark_session_synced(call_type, up_to=up_to)

    def reset_event_stream_sync(self, call_type, session_id=None, reason="reset"):
        self.stream.reset_session_sync(call_type, reason=reason)


class _LateEventLLM(_LLM):
    """Logs an event into the stream while each request is in flight."""

    def __init__(self, stream, replies, sessions=True):
        super().__init__(replies, sessions=sessions)
        self.stream = stream

    def _answer(self, system, user, metadata):
        self.stream.log("action_end", f"late event {len(self.sent) + 1}")
        return super()._answer(system, user, metadata)


def _real_router(monkeypatch, llm, stream):
    manager = SimpleNamespace(get_stream_by_id=lambda session_id: stream)
    monkeypatch.setattr(router_module, "get_event_stream_manager", lambda: manager)
    return router_module.ActionRouter(None, llm, _StreamContext(stream))


def _decide_on(router, stream):
    return asyncio.run(
        router._prompt_for_decision(
            stream.to_prompt_snapshot(),
            is_task=True,
            session_id="s1",
            render_prompt=lambda up_to=None: stream.to_prompt_snapshot(up_to=up_to),
            instructions="INSTR",
        )
    )


def test_an_event_logged_during_a_request_goes_with_the_next_one(monkeypatch):
    stream = EventStream(llm=None, temp_dir=None)
    stream.log("action_end", "before the first request")
    llm = _LateEventLLM(stream, [END_TURN, END_TURN, END_TURN])
    router = _real_router(monkeypatch, llm, stream)

    _decide_on(router, stream)  # full request; "late event 1" lands meanwhile
    assert "before the first request" in llm.sent[0]["user"]
    assert "late event 1" not in llm.sent[0]["user"]

    _decide_on(router, stream)  # delta; "late event 2" lands meanwhile
    assert llm.sent[1]["metadata"] == {"request": "delta"}
    assert "late event 1" in llm.sent[1]["user"]
    assert "late event 2" not in llm.sent[1]["user"]

    _decide_on(router, stream)
    assert "late event 2" in llm.sent[2]["user"]
    assert "late event 1" not in llm.sent[2]["user"]  # sent once, not twice


def test_a_stateless_request_marks_only_what_it_carried_delivered(monkeypatch):
    stream = EventStream(llm=None, temp_dir=None)
    stream.log("action_end", "before the request")
    llm = _LateEventLLM(stream, [END_TURN], sessions=False)
    _decide_on(_real_router(monkeypatch, llm, stream), stream)

    carried, late = stream.tail_events[-2:]
    assert "before the request" in carried.event.message and carried.delivered
    assert "late event 1" in late.event.message and not late.delivered


def test_the_stream_renders_and_syncs_up_to_a_point():
    stream = EventStream(llm=None, temp_dir=None)
    for n in range(3):
        stream.log("action_end", f"event {n}")
    point = stream.get_event_count()
    stream.log("action_end", "event 3")

    assert "event 3" not in stream.to_prompt_snapshot(up_to=point)
    delta, _ = stream.get_delta_events(ACTION, up_to=point)
    assert "event 2" in delta and "event 3" not in delta

    stream.mark_session_synced(ACTION, up_to=point)
    delta, has_delta = stream.get_delta_events(ACTION)
    assert has_delta and "event 3" in delta and "event 2" not in delta
