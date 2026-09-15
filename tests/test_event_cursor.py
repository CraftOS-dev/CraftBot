"""Incremental event-stream reading for the UI event pump."""

from types import SimpleNamespace

from app.ui_layer.controller.event_cursor import EventStreamCursors


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
