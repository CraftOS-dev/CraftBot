"""Per-session caps for the browser adapter's in-memory UI buffers."""

from app.ui_layer.adapters.session_buffer import trim_per_session


def _session(item):
    return item[0]


def test_keeps_newest_items_per_session_in_original_order():
    items = [("a", 1), ("b", 1), ("a", 2), ("a", 3), ("b", 2), ("a", 4)]
    assert trim_per_session(items, 2, _session) == [
        ("b", 1),
        ("a", 3),
        ("b", 2),
        ("a", 4),
    ]


def test_under_the_limit_is_unchanged():
    items = [("a", 1), ("b", 1), ("a", 2)]
    assert trim_per_session(items, 5, _session) == items


def test_keep_preserves_old_items_beyond_the_cap():
    items = [("a", "pinned"), ("a", 1), ("a", 2), ("a", 3)]
    kept = trim_per_session(items, 2, _session, keep=lambda i: i[1] == "pinned")
    assert kept == [("a", "pinned"), ("a", 2), ("a", 3)]


def test_empty_input():
    assert trim_per_session([], 3, _session) == []
