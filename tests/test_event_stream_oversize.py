# -*- coding: utf-8 -*-
"""
A single oversized event must not cost two blocking summarization passes.

Observed 2026-08-26 in session lui_11e12617: one `grep_files` result of 171,818
chars (~77k tokens) entered the tail verbatim — grep_files/read_file are exempt
from log-time externalization because they ARE the retrieval path for
externalized content. MIN_KEEP_RECENT_EVENTS then pinned it, so the pass it
triggered went 92,735 -> 77,054 tokens (still over threshold, LLM call wasted)
and the next event fired a second pass, 79,117 -> 2,960, that folded it anyway.
Five such events in one 24-minute run; 33 passes totalling 936k uncached input
tokens and 536s of blocking wall-clock.

See _shrink_pinned_oversize / MIN_FOLD_TOKENS in
agent_core/core/impl/event_stream/event_stream.py.
"""

from agent_core.core.impl.event_stream.event_stream import (
    MAX_EVENT_INLINE_CHARS,
    EventStream,
)


class _CountingLLM:
    consecutive_failures = 0
    _max_consecutive_failures = 5

    def __init__(self):
        self.calls = 0

    def generate_response(self, user_prompt=None, prompt_name=None, **kw):
        self.calls += 1
        return "SUMMARY OF OLD EVENTS"


def _stream(tmp_path, llm, event_stream_limits):
    event_stream_limits(30000, 10000)
    return EventStream(llm=llm, temp_dir=tmp_path / "events")


def test_oversized_pinned_event_is_collapsed_without_an_llm_call(tmp_path, event_stream_limits):
    llm = _CountingLLM()
    es = _stream(tmp_path, llm, event_stream_limits)

    for i in range(60):
        es.log("action_end", f"action {i} completed " + "x " * 200)
    assert es._total_tokens < es.summarize_at_tokens
    baseline_calls = llm.calls

    # The grep_files result: exempt from log-time externalization, ~70k tokens,
    # and the newest event in the tail — exactly what the pin used to hold.
    giant = "matched line " + ("y " * 140_000)
    es.log("action_end", giant, action_name="grep_files")

    # Collapsing it in place is enough on its own: zero passes, where the old
    # code paid for two.
    assert llm.calls == baseline_calls
    assert es._total_tokens < es.summarize_at_tokens

    # The record survives so the UI can still pair action_start ↔ action_end...
    grep_rec = next(r for r in es.tail_events if r.event.action_name == "grep_files")
    # ...but its message is now a pointer, and the content is on disk.
    assert len(grep_rec.event.message) <= MAX_EVENT_INLINE_CHARS
    assert "grep_files" in grep_rec.event.message
    written = list((tmp_path / "events").glob("event_grep_files_*.txt"))
    assert written and written[0].read_text(encoding="utf-8") == giant.strip()


def test_a_pass_never_finishes_still_over_threshold(tmp_path, event_stream_limits):
    """The core invariant the double-pass violated.

    A summarization pass that returns with the stream still above
    summarize_at_tokens has bought nothing — the next log() re-triggers it. Drive
    a realistic mix (ordinary events, exempt oversized retrieval results, and
    protected requirements) and assert the stream is back under budget after
    every single append.
    """
    llm = _CountingLLM()
    es = _stream(tmp_path, llm, event_stream_limits)

    es.log("requirements", "[ ] done_when: the ledger reconciles")
    for i in range(300):
        es.log("action_end", f"action {i} completed " + "x " * 200)
        if i % 25 == 0:
            es.log(
                "action_end",
                "matched line " + ("y " * 90_000),
                action_name="grep_files" if i % 50 == 0 else "read_file",
            )
        assert es._total_tokens < es.summarize_at_tokens, (
            f"stream left at {es._total_tokens} tokens after event {i} — "
            "the next append will re-trigger summarization immediately"
        )

    # The protected contract survived all of it.
    assert any(r.event.kind == "requirements" for r in es.tail_events)


def test_tiny_foldable_region_is_pruned_not_summarized(tmp_path, event_stream_limits):
    """The 31,907 -> 31,529 case: a 15s LLM call that reclaimed 378 tokens.

    When the tail is dominated by events summarization is not allowed to touch,
    the foldable remainder can be far too small to be worth a blocking round
    trip. Prune it instead.
    """
    llm = _CountingLLM()
    es = _stream(tmp_path, llm, event_stream_limits)

    # A small foldable prefix...
    for i in range(3):
        es.log("action_end", f"action {i} completed")
    # ...behind a wall of protected events that alone breach the threshold.
    for i in range(80):
        es.log("requirements", f"[ ] requirement {i}: " + "r " * 500)

    assert llm.calls == 0
    assert not any(r.event.kind == "action_end" for r in es.tail_events)
    assert sum(1 for r in es.tail_events if r.event.kind == "requirements") == 80
