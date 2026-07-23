# -*- coding: utf-8 -*-
"""
core.impl.trigger.session_queue

SessionTriggerQueue — the per-session ordering primitive for triggers.

Every session owns one queue and one serial consumer loop. Unlike the old
global queue there is NO same-session supersede rule: within a session all
triggers share the session_id, and each one (a user message, a scheduled
fire, a run continuation) is distinct work that must be delivered.

Ordering: a trigger becomes eligible when its ``fire_at`` arrives; among
eligible triggers the lowest ``priority`` number wins (user messages preempt
run continuations), ties broken by ``fire_at`` then insertion order.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import time
from typing import List, Optional, TYPE_CHECKING

from agent_core.core.trigger import Trigger

if TYPE_CHECKING:
    from agent_core.core.impl.trigger.listener import TriggerLifecycleListener

from agent_core.utils.logger import logger


class QueueClosed(Exception):
    """Raised by get() when the queue has been closed (session deleted)."""


class SessionTriggerQueue:
    """Priority queue of triggers for a single session."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        # Heap entries: (fire_at, seq, trigger) — seq keeps ordering stable.
        self._heap: List[tuple] = []
        self._seq = itertools.count()
        self._cv = asyncio.Condition()
        self._closed = False
        self._lifecycle_listener: Optional["TriggerLifecycleListener"] = None

    def set_lifecycle_listener(
        self, listener: Optional["TriggerLifecycleListener"]
    ) -> None:
        """Register a listener notified when triggers are discarded unconsumed."""
        self._lifecycle_listener = listener

    def _notify_evicted(self, evicted: List[Trigger]) -> None:
        if not self._lifecycle_listener or not evicted:
            return
        try:
            self._lifecycle_listener.on_evicted(evicted, None)
        except Exception as e:
            logger.warning(f"[SessionQueue:{self.session_id}] Listener failed: {e}")

    async def put(self, trig: Trigger) -> None:
        """Insert a trigger. Raises QueueClosed if the session was deleted."""
        async with self._cv:
            if self._closed:
                raise QueueClosed(self.session_id)
            heapq.heappush(self._heap, (trig.fire_at, next(self._seq), trig))
            self._cv.notify()

    async def get(self) -> Trigger:
        """Wait for and return the next due trigger.

        Among all currently-due triggers the lowest priority number wins,
        so a user message (priority 3) preempts a queued continuation (5+)
        even when the continuation became due first.
        """
        async with self._cv:
            while True:
                if self._closed:
                    raise QueueClosed(self.session_id)
                now = time.time()

                # Collect all due triggers
                due: List[tuple] = []
                while self._heap and self._heap[0][0] <= now:
                    due.append(heapq.heappop(self._heap))

                if due:
                    due.sort(key=lambda e: (e[2].priority, e[0], e[1]))
                    fire_at, seq, trig = due.pop(0)
                    for entry in due:
                        heapq.heappush(self._heap, entry)
                    logger.info(
                        f"[TRIGGER FIRED] session={trig.session_id} | "
                        f"source={trig.source} | desc={trig.next_action_description[:120]}"
                    )
                    return trig

                if self._heap:
                    delay = self._heap[0][0] - now
                    if delay <= 0:
                        continue
                    try:
                        await asyncio.wait_for(self._cv.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        continue
                else:
                    await self._cv.wait()

    async def pop_due_batch(self, source: str) -> List[Trigger]:
        """Pop ALL currently-due triggers with the given ``source``.

        Non-blocking companion to get(): after the consumer claims one
        trigger, it drains the same-source triggers that piled up while
        the previous turn was running, so they can be aggregated into a
        single turn instead of firing turn-after-turn. Triggers of other
        sources (or not yet due) stay queued untouched.

        Returns the drained triggers in (priority, fire_at, insertion)
        order; empty when nothing matches.
        """
        async with self._cv:
            if self._closed or not self._heap:
                return []
            now = time.time()
            keep: List[tuple] = []
            batch: List[tuple] = []
            while self._heap:
                entry = heapq.heappop(self._heap)
                if entry[0] <= now and entry[2].source == source:
                    batch.append(entry)
                else:
                    keep.append(entry)
            for entry in keep:
                heapq.heappush(self._heap, entry)
            batch.sort(key=lambda e: (e[2].priority, e[0], e[1]))
            return [entry[2] for entry in batch]

    async def close(self) -> List[Trigger]:
        """Close the queue (session deletion) and return discarded triggers.

        Discarded triggers are also reported to the lifecycle listener so
        their durable rows settle instead of rehydrating next boot.
        """
        async with self._cv:
            self._closed = True
            discarded = [entry[2] for entry in self._heap]
            self._heap.clear()
            self._notify_evicted(discarded)
            self._cv.notify_all()
            return discarded

    async def size(self) -> int:
        """Count queued triggers."""
        async with self._cv:
            return len(self._heap)

    async def list_triggers(self) -> List[Trigger]:
        """Snapshot of queued triggers (unordered)."""
        async with self._cv:
            return [entry[2] for entry in self._heap]

    def has_pending(self) -> bool:
        """Non-blocking check whether any trigger is queued."""
        return bool(self._heap)
