# -*- coding: utf-8 -*-
"""
Oversized retrieval results must not waste summarization passes.

Observed 2026-08-26 in session agentapp_11e12617: one `grep_files` result of 171,818
chars (~77k tokens) entered the tail verbatim — grep_files/read_file are exempt
from log-time externalization because they ARE the retrieval path for
externalized content. MIN_KEEP_RECENT_EVENTS pinned it, and folds that could
not get under budget were re-triggered on every append.

The stream no longer folds on its own; the router asks for one fold when the
next request would not fit. So a fold must be worth asking for: it collapses
oversized pinned events in place first, then summarizes, and a region too
small to be worth an LLM call is pruned instead. Only events the model has
already received are collapsed or folded (see test_event_stream_delivery.py).

See _shrink_pinned_oversize / MIN_FOLD_TOKENS in
agent_core/core/impl/event_stream/event_stream.py.
"""

from agent_core.core.impl.event_stream.event_stream import (
    MAX_EVENT_INLINE_CHARS,
    EventStream,
)


KEEP_TOKENS = 10000


class _CountingLLM:
    consecutive_failures = 0
    _max_consecutive_failures = 5

    def __init__(self):
        self.calls = 0

    def generate_response(self, user_prompt=None, prompt_name=None, **kw):
        self.calls += 1
        return "SUMMARY OF OLD EVENTS"


def _stream(tmp_path, llm):
    return EventStream(llm=llm, temp_dir=tmp_path / "events")


def test_appending_never_folds_on_its_own(tmp_path):
    """The decision lives with the router; log() only appends."""
    llm = _CountingLLM()
    es = _stream(tmp_path, llm)
    for i in range(400):
        es.log("action_end", f"action {i} completed " + "x " * 200)
    assert llm.calls == 0
    assert es.head_summary is None


def test_oversized_pinned_event_is_collapsed_in_place_by_a_fold(tmp_path):
    llm = _CountingLLM()
    es = _stream(tmp_path, llm)
    for i in range(60):
        es.log("action_end", f"action {i} completed " + "x " * 200)

    # The grep_files result: exempt from log-time externalization, ~70k tokens,
    # and the newest event in the tail — exactly what the pin holds.
    giant = "matched line " + ("y " * 140_000)
    es.log("action_end", giant, action_name="grep_files")
    es.mark_delivered()  # the agent read it last turn
    before = es._total_tokens

    es.summarize_by_LLM(keep_tokens=KEEP_TOKENS)

    assert es._total_tokens < before
    # The record survives so the UI can still pair action_start <-> action_end...
    grep_rec = next(r for r in es.tail_events if r.event.action_name == "grep_files")
    # ...but its message is now a pointer, and the content is on disk.
    assert len(grep_rec.event.message) <= MAX_EVENT_INLINE_CHARS
    assert "grep_files" in grep_rec.event.message
    written = list((tmp_path / "events").glob("event_grep_files_*.txt"))
    assert written and written[0].read_text(encoding="utf-8") == giant.strip()


def test_a_fold_gets_under_budget_and_a_second_one_is_free(tmp_path):
    """One requested fold must leave the stream near its keep target, with
    protected events intact; asking again with nothing foldable costs no call."""
    llm = _CountingLLM()
    es = _stream(tmp_path, llm)

    es.log("requirements", "[ ] done_when: the ledger reconciles")
    for i in range(300):
        es.log("action_end", f"action {i} completed " + "x " * 200)
        if i % 25 == 0:
            es.log(
                "action_end",
                "matched line " + ("y " * 90_000),
                action_name="grep_files" if i % 50 == 0 else "read_file",
            )
    es.mark_delivered()

    es.summarize_by_LLM(keep_tokens=KEEP_TOKENS)
    after_first = es._total_tokens
    assert (
        after_first < KEEP_TOKENS + 4000
    )  # the keep target plus a pinned/protected margin
    assert any(r.event.kind == "requirements" for r in es.tail_events)

    calls = llm.calls
    es.summarize_by_LLM(keep_tokens=KEEP_TOKENS)
    assert llm.calls == calls
    assert es._total_tokens <= after_first


def test_tiny_foldable_region_is_pruned_not_summarized(tmp_path):
    """The 31,907 -> 31,529 case: a 15s LLM call that reclaimed 378 tokens.

    When the tail is dominated by events summarization is not allowed to touch
    (here: results the model has not received yet), the foldable remainder can
    be far too small to be worth a blocking round trip. Prune it instead.
    """
    llm = _CountingLLM()
    es = _stream(tmp_path, llm)

    # A small foldable prefix the model has read...
    for i in range(3):
        es.log("action_end", f"action {i} completed")
    es.mark_delivered()
    # ...behind a wall of results it has not.
    for i in range(80):
        es.log("action_end", f"result {i}: " + "r " * 500)

    es.summarize_by_LLM(keep_tokens=KEEP_TOKENS)

    assert llm.calls == 0
    messages = [r.event.message for r in es.tail_events]
    assert not any(m.startswith("action ") for m in messages)
    assert sum(1 for m in messages if m.startswith("result ")) == 80
