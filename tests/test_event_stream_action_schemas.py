# -*- coding: utf-8 -*-
"""
Action schemas delivered into the event stream (add_action_sets is a read).

A session's <actions> list is fixed by its type. Schemas of any other set
arrive as one ACTION_SCHEMAS event, so the stream must keep them usable:
never externalized to a pointer, never collapsed in place, kept across a fold
while the kept tail still calls one of their actions, and otherwise dropped
without being summarized (they are a copy of the registry), with a note that
tells the agent to load them again.

See summarize_by_LLM / _drop_schemas in
agent_core/core/impl/event_stream/event_stream.py.
"""

from agent_core.core.event_stream.event import Event, EventRecord, EventType
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


def _log_schemas(es, names, body="SCHEMA BODY"):
    es.log(
        "action_schemas",
        f"Schemas for {', '.join(names)}: {body}",
        event_type=EventType.ACTION_SCHEMAS,
        schema_actions=names,
    )


def _log_call(es, name):
    es.log("action_start", f"Running action {name}", action_name=name)
    es.log("action_end", f"Action {name} completed", action_name=name)


def _fill(es, n, tag="work"):
    for i in range(n):
        es.log("action_end", f"{tag} {i} completed " + "x " * 120)


def _schema_records(es):
    return [r for r in es.tail_events if r.event.event_type is EventType.ACTION_SCHEMAS]


def test_large_schemas_stay_inline(tmp_path):
    es, _ = _stream(tmp_path)
    body = "s " * MAX_EVENT_INLINE_CHARS
    _log_schemas(es, ["send_gmail"], body=body)

    (rec,) = _schema_records(es)
    assert body.strip() in rec.event.message
    assert not list((tmp_path / "events").glob("*.txt"))


def test_a_fold_never_collapses_schemas_in_place(tmp_path):
    es, _ = _stream(tmp_path)
    _fill(es, 5)
    _log_schemas(es, ["send_gmail"], body="s " * MAX_EVENT_INLINE_CHARS)
    es.mark_delivered()

    es.summarize_by_LLM(keep_tokens=100_000)

    (rec,) = _schema_records(es)
    assert len(rec.event.message) > MAX_EVENT_INLINE_CHARS


def test_schemas_in_use_survive_a_fold(tmp_path):
    es, llm = _stream(tmp_path)
    _log_schemas(es, ["send_gmail", "list_gmail"])
    _fill(es, 40)
    _log_call(es, "send_gmail")  # newest: in the kept tail
    es.mark_delivered()

    es.summarize_by_LLM(keep_tokens=KEEP_TOKENS)

    assert es.head_summary == "SUMMARY OF OLD EVENTS"
    (rec,) = _schema_records(es)
    assert rec.event.schema_actions == ["send_gmail", "list_gmail"]
    # Kept at the front of the surviving tail, not fed to the summarizer.
    assert es.tail_events[0] is rec
    assert all("SCHEMA BODY" not in p for p in llm.prompts)


def test_unused_schemas_are_dropped_unsummarized_with_a_note(tmp_path):
    es, llm = _stream(tmp_path)
    _log_schemas(es, ["post_discord"])
    _log_call(es, "post_discord")  # used, but long ago
    _fill(es, 40)
    es.mark_delivered()

    es.summarize_by_LLM(keep_tokens=KEEP_TOKENS)

    assert _schema_records(es) == []
    assert all("SCHEMA BODY" not in p for p in llm.prompts)
    notes = [
        r.event
        for r in es.tail_events
        if r.event.event_type is EventType.INTERNAL
        and "post_discord" in r.event.message
    ]
    assert len(notes) == 1 and "add_action_sets" in notes[0].message
    # Token accounting matches what is actually left.
    from agent_core.core.impl.event_stream.event_stream import get_cached_token_count

    assert es._total_tokens == sum(get_cached_token_count(r) for r in es.tail_events)


def test_only_schemas_old_enough_are_dropped_without_an_llm_call(tmp_path):
    es, llm = _stream(tmp_path)
    _log_schemas(es, ["post_discord"], body="s " * 3000)
    _fill(es, 2)
    es.mark_delivered()

    es.summarize_by_LLM(keep_tokens=600)

    assert _schema_records(es) == []
    assert llm.prompts == []
    assert es.head_summary is None


def test_actions_with_schemas_lists_the_live_tail(tmp_path):
    es, _ = _stream(tmp_path)
    assert es.actions_with_schemas() == set()
    _log_schemas(es, ["send_gmail", "list_gmail"])
    _log_schemas(es, ["post_discord"])
    assert es.actions_with_schemas() == {"send_gmail", "list_gmail", "post_discord"}


def test_schema_actions_survive_persistence():
    rec = EventRecord(
        event=Event(
            message="Schemas",
            kind="action_schemas",
            severity="INFO",
            event_type=EventType.ACTION_SCHEMAS,
            schema_actions=["send_gmail"],
        )
    )
    restored = EventRecord.from_dict(rec.to_dict())
    assert restored.event.event_type is EventType.ACTION_SCHEMAS
    assert restored.event.schema_actions == ["send_gmail"]
