# -*- coding: utf-8 -*-
"""
A fold must never collapse an event the model has not received.

Observed 2026-10-16 in lui_9a07529e: the router asks for a fold right after
actions return, before their results are sent. The fold kept the newest
events but externalized every oversized one to a "saved to file, read it"
pointer, and summarized the rest. So the read_file results the agent had just
asked for reached it as pointers or a summary line; it read them again, the
request overflowed again, and the session folded 13 times in 16 minutes
(63 read_file calls, NOTE.md 10 times) until it hit the action limit.

Records now carry `delivered`, set once a request carrying them is answered.
A fold only summarizes or shrinks delivered records. When the new events alone
do not fit any request, the router collapses the oversized ones to pointers as
a last resort.

See _fold_cutoff / mark_delivered / collapse_undelivered_oversize in
agent_core/core/impl/event_stream/event_stream.py and the overflow handler in
agent_core/core/impl/action/router.py.
"""

import asyncio

import pytest

from agent_core.core.impl.event_stream.event_stream import (
    MAX_EVENT_INLINE_CHARS,
    EventStream,
)


KEEP_TOKENS = 2000


class _RecordingLLM:
    consecutive_failures = 0
    _max_consecutive_failures = 5

    def __init__(self):
        self.prompts = []

    def generate_response(self, user_prompt=None, prompt_name=None, **kw):
        self.prompts.append(user_prompt)
        return "SUMMARY OF OLD EVENTS"


def _stream(tmp_path):
    llm = _RecordingLLM()
    return EventStream(llm=llm, temp_dir=tmp_path / "events"), llm


def _history(es, n=60):
    for i in range(n):
        es.log("action_end", f"old step {i} completed " + "x " * 120)


def _read_result(i, size):
    return f"READ RESULT {i}: " + ("line of file content " * size)


def test_new_events_start_undelivered_and_mark_delivered_covers_the_tail(tmp_path):
    es, _ = _stream(tmp_path)
    _history(es, 3)
    assert not any(r.delivered for r in es.tail_events)

    es.mark_delivered()
    es.log("action_end", "arrived after the request")

    assert all(r.delivered for r in es.tail_events[:-1])
    assert not es.tail_events[-1].delivered


def test_a_session_sync_marks_delivery(tmp_path):
    es, _ = _stream(tmp_path)
    _history(es, 3)
    es.mark_session_synced("action_selection")
    assert all(r.delivered for r in es.tail_events)


def test_a_fold_leaves_unread_results_verbatim(tmp_path):
    """The log's case: the agent's parallel reads return, then the fold runs."""
    es, llm = _stream(tmp_path)
    _history(es)
    es.mark_delivered()

    # Larger than the keep target together, and each one oversized: before
    # the fix, every one of them became a pointer or a summary line.
    results = [_read_result(i, 1200) for i in range(3)]
    assert all(len(r) > MAX_EVENT_INLINE_CHARS for r in results)
    for r in results:
        es.log("action_end", r, action_name="read_file")

    es.summarize_by_LLM(keep_tokens=KEEP_TOKENS)

    messages = [r.event.message for r in es.tail_events]
    for r in results:
        assert r.strip() in messages
    assert not list((tmp_path / "events").glob("event_read_file_*.txt"))
    assert all("READ RESULT" not in p for p in llm.prompts)
    # The history the agent had read is what got folded.
    assert es.head_summary == "SUMMARY OF OLD EVENTS"
    assert not any(m.startswith("old step") for m in messages)


def test_read_results_collapse_once_the_model_has_them(tmp_path):
    # A keep window the read result fits in, so it stays in the tail.
    es, _ = _stream(tmp_path)
    _history(es)
    es.mark_delivered()
    es.log("action_end", _read_result(0, 1200), action_name="read_file")
    es.summarize_by_LLM(keep_tokens=6000)
    assert not list((tmp_path / "events").glob("event_read_file_*.txt"))

    es.mark_session_synced("action_selection")  # the agent's next turn
    es.summarize_by_LLM(keep_tokens=6000)

    rec = next(r for r in es.tail_events if r.event.action_name == "read_file")
    assert len(rec.event.message) <= MAX_EVENT_INLINE_CHARS
    assert list((tmp_path / "events").glob("event_read_file_*.txt"))


def test_collapse_undelivered_oversize_only_touches_new_events(tmp_path):
    es, _ = _stream(tmp_path)
    read_before = _read_result(0, 1200)
    es.log("action_end", read_before, action_name="read_file")
    es.mark_delivered()
    es.log("action_end", _read_result(1, 1200), action_name="read_file")
    es.log("action_end", "small new result", action_name="list_folder")

    assert es.collapse_undelivered_oversize() > 0

    old, new, small = [r for r in es.tail_events if r.event.action_name]
    assert old.event.message == read_before.strip()
    assert len(new.event.message) <= MAX_EVENT_INLINE_CHARS
    assert small.event.message == "small new result"
    # Nothing left to shrink: the router gives up instead of looping.
    assert es.collapse_undelivered_oversize() == 0


# ------------------------------------------------- router overflow handling


class _Manager:
    def __init__(self, stream):
        self.stream = stream

    def get_stream_by_id(self, _session_id):
        return self.stream


class _ContextEngine:
    def make_prompt(self, user_flags=None, system_flags=None):
        return "SYSTEM", None

    def reset_event_stream_sync(self, call_type, session_id=None):
        pass


class _StatelessLLM:
    """No session cache: every request carries the whole rendered stream.
    Refuses any request that still holds a read result in full."""

    def __init__(self):
        self.sent = []

    def has_session_cache(self, task_id, call_type):
        return False

    def reset_session_history(self, task_id, call_type):
        pass

    def input_budget(self):
        # Room to spare, so each fold keeps context.keep_recent_tokens.
        return 1_000_000

    async def generate_response_async(self, system_prompt, user_prompt, **kw):
        from agent_core.core.impl.llm.interface import LLMContextOverflowError

        self.sent.append(user_prompt)
        if "line of file content line of file content" in user_prompt:
            raise LLMContextOverflowError("request too large")
        return '{"action_name": "end_turn", "parameters": {}}'


def _router(monkeypatch, stream, llm):
    import agent_core.core.impl.action.router as router_module
    from app import config as app_config

    monkeypatch.setattr(
        router_module, "get_event_stream_manager", lambda: _Manager(stream)
    )
    monkeypatch.setattr(app_config, "get_keep_recent_tokens", lambda: KEEP_TOKENS)
    return router_module.ActionRouter(None, llm, _ContextEngine())


def _decide(router, stream):
    return asyncio.run(
        router._prompt_for_decision(
            stream.to_prompt_snapshot(),
            is_task=True,
            session_id="lui_test",
            render_prompt=stream.to_prompt_snapshot,
        )
    )


def test_router_folds_then_collapses_new_events_that_cannot_fit(tmp_path, monkeypatch):
    es, summarizer = _stream(tmp_path)
    _history(es)
    es.mark_delivered()
    es.log("action_end", _read_result(0, 1200), action_name="read_file")
    llm = _StatelessLLM()

    decision = _decide(_router(monkeypatch, es, llm), es)

    assert decision["action_name"] == "end_turn"
    assert len(llm.sent) == 3  # refused, refused after the fold, sent
    assert len(summarizer.prompts) == 1  # one fold
    assert list((tmp_path / "events").glob("event_read_file_*.txt"))
    # The answered request delivered everything that is in the tail now.
    assert all(r.delivered for r in es.tail_events)


def test_router_gives_up_when_nothing_is_left_to_shrink(tmp_path, monkeypatch):
    from agent_core.core.impl.llm.interface import LLMContextOverflowError

    es, _ = _stream(tmp_path)
    _history(es)
    es.mark_delivered()
    # Many new results, each just under the externalization threshold.
    for i in range(3):
        es.log("action_end", _read_result(i, 700), action_name="read_file")
    llm = _StatelessLLM()

    with pytest.raises(LLMContextOverflowError):
        _decide(_router(monkeypatch, es, llm), es)
    assert len(llm.sent) == 2  # refused, refused after the fold, then gave up


def test_a_stateless_answer_marks_the_stream_delivered(tmp_path, monkeypatch):
    es, _ = _stream(tmp_path)
    _history(es, 3)
    llm = _StatelessLLM()

    _decide(_router(monkeypatch, es, llm), es)

    assert all(r.delivered for r in es.tail_events)
