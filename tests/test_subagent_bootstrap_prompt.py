"""T18: render an exact bootstrap duplicate by reference, without mutating it."""

import json
from unittest.mock import Mock

import pytest

from agent_core.core.event_stream.event import EventRecord
from agent_core.core.impl.event_stream.manager import EventStreamManager
from app.subagent.context_engine import SubAgentContextEngine
from app.subagent.manager import SubAgentManager
from app.subagent.runner import SubAgentRunner, _SUBAGENT_CALL_TYPE


@pytest.fixture
def runtime():
    llm = Mock()
    events = EventStreamManager(llm=llm)
    manager = SubAgentManager(events, llm)
    query = "\n".join(
        f"Constraint {i}: preserve C:/sources/{i}.txt and /tmp/source-{i}; do not send messages."
        for i in range(40)
    )
    sub = manager.spawn("general_agent", query)
    runner = SubAgentRunner(manager, Mock(), Mock(), events, llm)
    return sub, events, runner


def test_initial_prompt_keeps_query_once_and_records_remain_complete(runtime):
    sub, events, runner = runtime
    stream = events.get_stream_by_id(sub.id)
    before = [r.to_dict() for r in stream.tail_events]
    prompt, first = runner._build_user_prompt(sub, stream)
    assert first and prompt.count(sub.query) == 1
    assert "Query: see QUERY FROM SPAWNING AGENT above." in prompt
    assert [r.to_dict() for r in stream.tail_events] == before
    assert sub.bootstrap_message in events.snapshot_by_id(sub.id)


@pytest.mark.parametrize(
    "phase",
    ["restore", "fold_removed_bootstrap", "fold_retained_bootstrap", "no_delta"],
)
def test_every_fresh_context_contains_the_complete_query(runtime, phase):
    sub, events, runner = runtime
    stream = events.get_stream_by_id(sub.id)
    stream.mark_session_synced(_SUBAGENT_CALL_TYPE)
    if phase == "restore":
        records = [
            EventRecord.from_dict(json.loads(json.dumps(r.to_dict())))
            for r in stream.tail_events
        ]
        stream.clear()
        stream.tail_events = records
    elif phase.startswith("fold"):
        stream.head_summary = "Previous work, with open items."
        if phase == "fold_removed_bootstrap":
            stream.tail_events = []
        stream.reset_session_sync(_SUBAGENT_CALL_TYPE, "fold")
    prompt, first = runner._build_user_prompt(sub, stream)
    assert first and prompt.count(sub.query) == 1
    assert all(f"Constraint {i}:" in prompt for i in range(40))
    if phase.startswith("fold"):
        assert "Previous work, with open items." in prompt


def test_different_bootstrap_is_never_abbreviated(runtime):
    sub, events, runner = runtime
    stream = events.get_stream_by_id(sub.id)
    record = next(r for r in stream.tail_events if r.event.kind == "subagent_start")
    record.event.message += "\nDo not modify any source files."
    original = record.event.message
    prompt = runner.context_engine.make_first_turn_user_prompt(sub)
    assert original in prompt
    assert "Query: see QUERY" not in prompt
    assert sub.query in prompt


def test_matching_text_in_another_event_is_not_rewritten(runtime):
    sub, events, runner = runtime
    events.log("quotation", sub.bootstrap_message, task_id=sub.id)
    prompt = runner.context_engine.make_first_turn_user_prompt(sub)
    assert sub.bootstrap_message in prompt
    assert "Query: see QUERY" in prompt


def test_delta_does_not_resend_query_or_change_the_cached_first_turn(runtime):
    sub, events, runner = runtime
    stream = events.get_stream_by_id(sub.id)
    first, _ = runner._build_user_prompt(sub, stream)
    stream.mark_session_synced(_SUBAGENT_CALL_TYPE)
    events.log("progress", "Read the source", task_id=sub.id)
    delta, is_first = runner._build_user_prompt(sub, stream)
    assert not is_first and sub.query not in delta
    assert "Read the source" in delta
    assert first.count(sub.query) == 1


def test_long_query_needs_no_retrieval_and_keeps_every_constraint():
    events = EventStreamManager(llm=None)
    manager = SubAgentManager(events, Mock())
    query = "\n".join(
        f"Constraint {i}: " + ("source evidence, " * 25) for i in range(120)
    ).rstrip()
    sub = manager.spawn("general_agent", query)
    engine = SubAgentContextEngine(Mock(), events)
    prompt = engine.make_first_turn_user_prompt(sub)
    assert len(query) > 42059
    assert prompt.count(query) == 1
    assert sub.query == query
    assert sub.bootstrap_message in events.snapshot_by_id(sub.id)


def test_query_whitespace_is_not_normalized_to_force_a_match():
    events = EventStreamManager(llm=None)
    manager = SubAgentManager(events, Mock())
    sub = manager.spawn("general_agent", "Preserve this exact query.\n\n")
    prompt = SubAgentContextEngine(Mock(), events).make_first_turn_user_prompt(sub)
    # Event logging strips surrounding whitespace. Equality cannot be proved,
    # so keep its text and the complete standalone query, including newlines.
    assert sub.query in prompt
    assert "Query: see QUERY" not in prompt
    assert prompt.count("Preserve this exact query.") == 2
