"""Incremental event-stream reading for the UI event pump."""

from types import SimpleNamespace

from app.ui_layer.controller.event_cursor import EventStreamCursors, event_dedup_key


def _record(name: str):
    return SimpleNamespace(event=name)


def test_returns_only_events_added_since_the_last_read():
    stream = SimpleNamespace(tail_events=[_record("a"), _record("b")])
    cursors = EventStreamCursors()

    assert cursors.new_events("s", stream) == ["a", "b"]
    assert cursors.new_events("s", stream) == []

    stream.tail_events.append(_record("c"))
    stream.tail_events.append(_record("d"))
    assert cursors.new_events("s", stream) == ["c", "d"]


def test_follows_a_fold_that_keeps_the_last_seen_record():
    keep, last = _record("kept"), _record("last")
    stream = SimpleNamespace(tail_events=[_record("old1"), _record("old2"), keep, last])
    cursors = EventStreamCursors()
    cursors.new_events("s", stream)

    # Folding replaces the list with protected + newest records.
    stream.tail_events = [keep, last, _record("new")]
    assert cursors.new_events("s", stream) == ["new"]


def test_rereads_everything_after_a_clear():
    stream = SimpleNamespace(tail_events=[_record("a")])
    cursors = EventStreamCursors()
    cursors.new_events("s", stream)

    stream.tail_events = [_record("x"), _record("y")]
    assert cursors.new_events("s", stream) == ["x", "y"]


def test_falls_back_to_as_list_for_other_stream_shapes():
    stream = SimpleNamespace(as_list=lambda: ["p", "q"])
    assert EventStreamCursors().new_events("s", stream) == ["p", "q"]


def test_retain_forgets_removed_streams():
    cursors = EventStreamCursors()
    stream = SimpleNamespace(tail_events=[_record("a")])
    cursors.new_events("gone", stream)
    cursors.retain([])
    assert cursors.new_events("gone", stream) == ["a"]


def _pump(cursors, seen, stream):
    """The UI pump's read + dedupe step (ui_controller._watch_agent_events)."""
    emitted = []
    for event in cursors.new_events("s", stream):
        key = event_dedup_key("s", event)
        if key in seen:
            continue
        seen.add(key)
        emitted.append(event)
    return emitted


def test_parallel_action_ends_with_identical_output_are_all_emitted():
    """Six parallel search_gmail calls failing with the same error in the same
    second: every ACTION_END must reach the UI, or those items spin forever."""
    from datetime import datetime, timezone

    from agent_core.core.event_stream.event import Event, EventType

    ts = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)
    message = "Action search_gmail completed with output: {'status': 'error'}."
    ends = [
        SimpleNamespace(
            event=Event(
                message=message,
                kind="action_end",
                severity="INFO",
                ts=ts,
                event_type=EventType.ACTION_END,
                action_name="search_gmail",
                action_id=f"run-{i}",
            )
        )
        for i in range(6)
    ]
    stream = SimpleNamespace(tail_events=list(ends))
    cursors, seen = EventStreamCursors(), set()

    assert [e.action_id for e in _pump(cursors, seen, stream)] == [
        f"run-{i}" for i in range(6)
    ]

    # A fold/clear re-reads the whole stream: nothing is emitted twice.
    stream.tail_events = list(ends)
    assert _pump(EventStreamCursors(), seen, stream) == []
