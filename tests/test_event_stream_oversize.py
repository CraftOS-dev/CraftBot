# -*- coding: utf-8 -*-
"""
Oversized retrieval results must not waste summarization passes.

Observed 2026-08-26 in session lui_11e12617: one `grep_files` result of 171,818
chars (~77k tokens) entered the tail verbatim — grep_files/read_file are exempt
from log-time externalization because they ARE the retrieval path for
externalized content. MIN_KEEP_RECENT_EVENTS pinned it, and folds that could
not get under budget were re-triggered on every append.

The stream no longer folds on its own; the router asks for one fold when the
next request would not fit. So a fold must be worth asking for: it collapses
oversized pinned events in place first, then summarizes, and a region too
small to be worth an LLM call is pruned instead.

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
    event_stream_limits(10000)
    return EventStream(llm=llm, temp_dir=tmp_path / "events")


def test_appending_never_folds_on_its_own(tmp_path, event_stream_limits):
    """The decision lives with the router; log() only appends."""
    llm = _CountingLLM()
    es = _stream(tmp_path, llm, event_stream_limits)
    for i in range(400):
        es.log("action_end", f"action {i} completed " + "x " * 200)
    assert llm.calls == 0
    assert es.head_summary is None


def test_oversized_pinned_event_is_collapsed_in_place_by_a_fold(tmp_path, event_stream_limits):
    llm = _CountingLLM()
    es = _stream(tmp_path, llm, event_stream_limits)
    for i in range(60):
        es.log("action_end", f"action {i} completed " + "x " * 200)

    # The grep_files result: exempt from log-time externalization, ~70k tokens,
    # and the newest event in the tail — exactly what the pin holds.
    giant = "matched line " + ("y " * 140_000)
    es.log("action_end", giant, action_name="grep_files")
    before = es._total_tokens

    es.summarize_by_LLM()

    assert es._total_tokens < before
    # The record survives so the UI can still pair action_start <-> action_end...
    grep_rec = next(r for r in es.tail_events if r.event.action_name == "grep_files")
    # ...but its message is now a pointer, and the content is on disk.
    assert len(grep_rec.event.message) <= MAX_EVENT_INLINE_CHARS
    assert "grep_files" in grep_rec.event.message
    written = list((tmp_path / "events").glob("event_grep_files_*.txt"))
    assert written and written[0].read_text(encoding="utf-8") == giant.strip()


def test_a_fold_gets_under_budget_and_a_second_one_is_free(tmp_path, event_stream_limits):
    """One requested fold must leave the stream near keep_recent_tokens, with
    protected events intact; asking again with nothing foldable costs no call."""
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

    es.summarize_by_LLM()
    after_first = es._total_tokens
    assert after_first < 10000 + 4000  # keep_recent_tokens plus a pinned/protected margin
    assert any(r.event.kind == "requirements" for r in es.tail_events)

    calls = llm.calls
    es.summarize_by_LLM()
    assert llm.calls == calls
    assert es._total_tokens <= after_first


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
    # ...behind a wall of protected events.
    for i in range(80):
        es.log("requirements", f"[ ] requirement {i}: " + "r " * 500)

    es.summarize_by_LLM()

    assert llm.calls == 0
    assert not any(r.event.kind == "action_end" for r in es.tail_events)
    assert sum(1 for r in es.tail_events if r.event.kind == "requirements") == 80
