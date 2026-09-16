# -*- coding: utf-8 -*-
"""
Per-session caps for the browser adapter's in-memory chat/activity buffers.

The buffers only seed the UI (the ``init`` payload and in-place updates);
storage keeps the full history and the Chat view pages older messages through
``chat_history``. Without a cap they grew with uptime and every connect shipped
all of it (docs/plans/ui-data-freshness-plan.md, RS-1.8 / D17).
"""

from __future__ import annotations

from typing import Callable, Dict, Hashable, List, Optional, Sequence, TypeVar

T = TypeVar("T")

# D17: items kept in memory per session.
SESSION_BUFFER_LIMIT = 200
# Appends allowed past the last trim before trimming again, so trimming stays
# amortized instead of scanning the buffer on every append.
SESSION_BUFFER_SLACK = 50


def trim_per_session(
    items: Sequence[T],
    limit: int,
    session_of: Callable[[T], Hashable],
    keep: Optional[Callable[[T], bool]] = None,
) -> List[T]:
    """The newest ``limit`` items of each session, in their original order.

    ``items`` is oldest-first. Items older than the cap survive only when
    ``keep(item)`` is true (e.g. a still-running action, an unanswered question).
    """
    counts: Dict[Hashable, int] = {}
    kept: List[T] = []
    for item in reversed(items):
        session = session_of(item)
        seen = counts.get(session, 0)
        if seen < limit:
            counts[session] = seen + 1
            kept.append(item)
        elif keep is not None and keep(item):
            kept.append(item)
    kept.reverse()
    return kept
