# -*- coding: utf-8 -*-
"""
Summarization must never collapse protected event kinds (e.g. `requirements`
from set_requirement, which lives only in the event stream and defines the
task's definition-of-done).

See PROTECTED_SUMMARY_KINDS in agent_core/core/impl/event_stream/event_stream.py.
"""

from agent_core.core.impl.event_stream.event_stream import (
    EventStream,
    PROTECTED_SUMMARY_KINDS,
)


class _FakeLLM:
    consecutive_failures = 0
    _max_consecutive_failures = 5

    def generate_response(self, user_prompt=None, prompt_name=None, **kw):
        return "SUMMARY OF OLD EVENTS"


def test_requirements_survive_summarization(event_stream_limits):
    assert "requirements" in PROTECTED_SUMMARY_KINDS

    event_stream_limits(2100, 100)  # min allowed given the 2000 internal buffer
    es = EventStream(llm=_FakeLLM())

    # The protected contract, logged FIRST so it becomes the oldest event.
    req_msg = "\n  [ ] content: must include a chronological version table\n         done_when: a markdown table with one row per version"
    es.log("requirements", req_msg)

    # Flood with filler so summarization fires and the requirements event ages
    # well past the keep-window.
    for i in range(400):
        es.log(
            "action_end",
            f"action {i} completed and produced some output text to add tokens",
        )

    kinds = [r.event.kind for r in es.tail_events]

    # Summarization actually happened (old filler collapsed into the summary)…
    assert es.head_summary is not None
    # …and most early filler is gone from the verbatim tail…
    assert "action 0 completed" not in "\n".join(
        r.event.message for r in es.tail_events
    )
    # …but the requirements event is still present verbatim, intact.
    assert "requirements" in kinds
    kept = [r for r in es.tail_events if r.event.kind == "requirements"]
    assert any("chronological version table" in r.event.message for r in kept)


def test_protected_only_region_is_noop(event_stream_limits):
    # If the only summarizable-aged content is protected, nothing is collapsed
    # (and it doesn't crash).
    event_stream_limits(2100, 100)
    es = EventStream(llm=_FakeLLM())
    es.log("requirements", "\n  [ ] x: y\n         done_when: z")
    es.summarize_by_LLM()  # force; region is tiny + protected
    assert any(r.event.kind == "requirements" for r in es.tail_events)
