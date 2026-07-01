# -*- coding: utf-8 -*-
"""
The event stream carries a `datetime` marker (minute-precision wall-clock):
pushed on the first event, refreshed at most every DATETIME_REFRESH_SECONDS, and
re-stamped right after each summarization. It is intentionally NOT protected from
summarization.

See agent_core/core/impl/event_stream/event_stream.py.
"""

import re
from datetime import datetime, timedelta

from agent_core.core.impl.event_stream.event_stream import (
    EventStream,
    DATETIME_REFRESH_SECONDS,
)


class _FakeLLM:
    consecutive_failures = 0
    _max_consecutive_failures = 5

    def generate_response(self, user_prompt=None, prompt_name=None, **kw):
        return "SUMMARY OF OLD EVENTS"


def _kinds(es):
    return [r.event.kind for r in es.tail_events]


def test_first_event_gets_a_datetime_marker():
    es = EventStream(llm=_FakeLLM())
    es.log("action_end", "did a thing")
    kinds = _kinds(es)
    # datetime precedes the first real event, and there's exactly one so far
    assert kinds[0] == "datetime"
    assert "action_end" in kinds
    assert kinds.count("datetime") == 1
    # minute precision (no seconds)
    msg = es.tail_events[0].event.message
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}\b", msg)


def test_no_datetime_spam_within_window():
    es = EventStream(llm=_FakeLLM())
    for i in range(20):
        es.log("action_end", f"event {i}")
    assert _kinds(es).count("datetime") == 1  # only the first


def test_datetime_refreshes_after_interval():
    es = EventStream(llm=_FakeLLM())
    es.log("action_end", "first")
    # Force the last stamp into the past to simulate >30 min elapsed.
    es._last_datetime_ts = datetime.now().astimezone() - timedelta(
        seconds=DATETIME_REFRESH_SECONDS + 1
    )
    es.log("action_end", "second")
    assert _kinds(es).count("datetime") == 2


def test_datetime_restamped_after_summarization():
    es = EventStream(
        llm=_FakeLLM(), summarize_at_tokens=2100, tail_keep_after_summarize_tokens=100
    )
    for i in range(400):
        es.log("action_end", f"action {i} produced some output text to add tokens")
    assert es.head_summary is not None  # summarization happened
    # A current datetime marker is always present (re-stamped post-summary).
    assert any(r.event.kind == "datetime" for r in es.tail_events)
