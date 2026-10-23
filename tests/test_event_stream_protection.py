# -*- coding: utf-8 -*-
"""
Summarization must never collapse the newest event of a protected kind (e.g.
`requirements` from set_requirement, which lives only in the event stream and
defines the task's definition-of-done). Each one is a complete snapshot, so the
older ones are superseded and fold like any other event: a long-lived session
must not carry every past task's contract in every prompt (observed
2026-10-16 in lui_9a07529e: 9 pinned snapshots, ~5.3k tokens, back to the
previous day).

See PROTECTED_SUMMARY_KINDS in agent_core/core/impl/event_stream/event_stream.py.
"""

from agent_core.core.impl.event_stream.event_stream import (
    EventStream,
    PROTECTED_SUMMARY_KINDS,
)


class _FakeLLM:
    consecutive_failures = 0
    _max_consecutive_failures = 5

    def __init__(self):
        self.prompts = []

    def generate_response(self, user_prompt=None, prompt_name=None, **kw):
        self.prompts.append(user_prompt)
        return "SUMMARY OF OLD EVENTS"


def test_requirements_survive_summarization():
    assert "requirements" in PROTECTED_SUMMARY_KINDS
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
    es.mark_delivered()

    es.summarize_by_LLM(keep_tokens=100)
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


def test_protected_only_region_is_noop():
    # If the only summarizable-aged content is protected, nothing is collapsed
    # (and it doesn't crash).
    es = EventStream(llm=_FakeLLM())
    es.log("requirements", "\n  [ ] x: y\n         done_when: z")
    es.mark_delivered()
    es.summarize_by_LLM(keep_tokens=100)  # force; region is tiny + protected
    assert any(r.event.kind == "requirements" for r in es.tail_events)


def test_only_the_newest_requirements_snapshot_stays_pinned():
    llm = _FakeLLM()
    es = EventStream(llm=llm)

    # Three tasks in one long-lived session, each with its own contract.
    for task in ("select leads", "send emails", "update crm"):
        es.log(
            "requirements", f"\n  [ ] scope: {task}\n         done_when: {task} done"
        )
        for i in range(100):
            es.log("action_end", f"{task}: step {i} produced some output text")
    es.mark_delivered()

    es.summarize_by_LLM(keep_tokens=100)

    kept = [r for r in es.tail_events if r.event.kind == "requirements"]
    assert len(kept) == 1
    assert "update crm" in kept[0].event.message
    # The superseded contracts went to the summarizer, not to the bin.
    assert "scope: select leads" in llm.prompts[0]
    assert "scope: send emails" in llm.prompts[0]


def test_a_superseded_requirements_update_folds_too():
    """set_requirement re-issues the COMPLETE list on every update (e.g. the
    Verify pass marking items satisfied), so only the latest one is the
    contract."""
    es = EventStream(llm=_FakeLLM())
    es.log("requirements", "\n  [ ] scope: send five emails")
    for i in range(100):
        es.log("action_end", f"step {i} produced some output text to add tokens")
    es.log("requirements", "\n  [SAT] scope: send five emails")
    for i in range(100):
        es.log("action_end", f"later step {i} produced some output text too")
    es.mark_delivered()

    es.summarize_by_LLM(keep_tokens=100)

    kept = [r.event.message for r in es.tail_events if r.event.kind == "requirements"]
    assert kept == ["[SAT] scope: send five emails"]
