# -*- coding: utf-8 -*-
"""
core.impl.trigger.listener

Lifecycle listener protocol for TriggerQueue.

The queue is an in-memory ordering primitive; when it discards triggers
(same-session "prefer newest" replacement, session removal, full clear) a
durable store layered on top must be told so the corresponding rows are
settled instead of silently resurrecting on the next rehydration. The queue
only knows this protocol — the store implementation lives in the app layer.
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from agent_core.core.trigger import Trigger


@runtime_checkable
class TriggerLifecycleListener(Protocol):
    """Receives notifications when the queue discards triggers.

    Implementations must be synchronous and non-raising; the queue calls
    them while holding its internal lock.
    """

    def on_evicted(
        self, evicted: List[Trigger], replacement: Optional[Trigger]
    ) -> None:
        """Triggers were removed from the queue without being consumed.

        Args:
            evicted: The discarded triggers.
            replacement: The newer same-session trigger that superseded them,
                or None when they were removed outright (session cleanup,
                queue clear).
        """
        ...
