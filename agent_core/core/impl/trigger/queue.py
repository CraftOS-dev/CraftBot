# -*- coding: utf-8 -*-
"""
core.impl.trigger.queue

TriggerQueue implementation - in-memory ordering primitive for triggers.

The queue holds due-time-ordered triggers and hands them to the single
consumer loop. It is deliberately dumb:

- Durability lives in the app-layer TriggerStore; the queue reports any
  trigger it discards unconsumed through a TriggerLifecycleListener so the
  store can settle the corresponding rows.
- Session routing lives at the producer layer (SessionRouter); triggers
  arrive here with their session already decided. The pre-#321 in-queue LLM
  routing was removed — every producer sets a session_id, so it was dead
  code in practice.
- Same-session ordering: a new trigger for a session replaces any queued
  one ("prefer newest"), so at most one trigger per session is ever queued.
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agent_core.decorators import profile, OperationCategory
from agent_core.core.trigger import Trigger

if TYPE_CHECKING:
    from agent_core.core.impl.trigger.listener import TriggerLifecycleListener

# Logging setup
try:
    from agent_core.utils.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class TriggerQueue:
    """
    Concurrency-safe priority queue for Trigger.
    """

    def __init__(
        self,
        llm: Any = None,
        *,
        route_to_session_prompt: str = "",
        task_manager: Any = None,
        event_stream_manager: Any = None,
    ) -> None:
        """
        Initialize a concurrency-safe trigger queue.

        The queue manages incoming :class:`Trigger` objects using a heap to
        preserve ordering by ``fire_at`` timestamp and priority. A shared
        :class:`asyncio.Condition` coordinates producers and consumers so agent
        loops can await triggers without busy waiting.

        Args:
            llm: Deprecated, ignored. In-queue LLM routing was removed
                ; routing happens at the producer layer.
            route_to_session_prompt: Deprecated, ignored.
            task_manager: Deprecated, ignored.
            event_stream_manager: Deprecated, ignored.
        """
        if llm is not None or route_to_session_prompt:
            logger.debug(
                "[TRIGGER QUEUE] llm/route_to_session_prompt are deprecated "
                "and ignored — routing moved to the producer layer"
            )
        self._heap: List[Trigger] = []
        self._active: Dict[
            str, Trigger
        ] = {}  # Triggers being processed (session_id -> trigger)
        self._cv = asyncio.Condition()
        self._lifecycle_listener: Optional["TriggerLifecycleListener"] = None

    def set_lifecycle_listener(
        self, listener: Optional["TriggerLifecycleListener"]
    ) -> None:
        """Register a listener notified when triggers are discarded unconsumed.

        Used by the durable trigger store to settle rows for triggers the
        queue drops (same-session replacement, session removal, clear) so
        they don't rehydrate on the next boot.

        Args:
            listener: The listener, or None to detach.
        """
        self._lifecycle_listener = listener

    def _notify_evicted(
        self, evicted: List[Trigger], replacement: Optional[Trigger]
    ) -> None:
        """Notify the lifecycle listener, swallowing listener errors."""
        if not self._lifecycle_listener or not evicted:
            return
        try:
            self._lifecycle_listener.on_evicted(evicted, replacement)
        except Exception as e:
            logger.warning(f"[TRIGGER QUEUE] Lifecycle listener failed: {e}")

    # =================================================================
    # Pretty Printer for Debugging
    # =================================================================
    def _print_queue(self, label: str) -> None:
        logger.debug("=" * 70)
        logger.debug(f"[TRIGGER QUEUE] {label}")
        logger.debug("=" * 70)

        if not self._heap:
            logger.debug("(empty)")
            return

        now = time.time()
        for i, t in enumerate(
            sorted(self._heap, key=lambda x: (x.fire_at, x.priority))
        ):
            logger.debug(
                f"{i + 1}. session_id={t.session_id} | "
                f"prio={t.priority} | "
                f"fire_at={t.fire_at:.6f} ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t.fire_at))}) | "
                f"delta={t.fire_at - now:.2f}s\n"
                f"   desc={t.next_action_description}"
            )
        logger.debug("=" * 70 + "\n")

    async def clear(self) -> None:
        """
        Remove all pending and active triggers from the queue.

        The queue is cleared under the protection of the condition variable so
        waiting consumers are notified immediately that the queue state has
        changed.
        """
        async with self._cv:
            discarded = list(self._heap) + list(self._active.values())
            self._heap.clear()
            self._active.clear()
            self._notify_evicted(discarded, None)
            self._cv.notify_all()

    # =================================================================
    # PUT
    # =================================================================

    @profile("trigger_queue_put", OperationCategory.TRIGGER)
    async def put(self, trig: Trigger, skip_merge: bool = False) -> None:
        """
        Insert a trigger into the queue, replacing queued same-session triggers.

        When a trigger arrives for a session that already has queued work,
        the existing triggers are replaced ("prefer newest") and reported to
        the lifecycle listener as superseded.

        Args:
            trig: Trigger instance describing when and why the agent should act.
            skip_merge: Deprecated, ignored — kept for call-site compatibility.
                (It previously skipped the in-queue LLM routing, which was
                removed; same-session replacement was always unconditional.)
        """
        logger.debug(f"\n[PUT] Incoming trigger for session={trig.session_id}")
        self._print_queue("BEFORE PUT")

        async with self._cv:
            # find all triggers in heap with same session_id
            same = [t for t in self._heap if t.session_id == trig.session_id]

            if same:
                logger.debug("[PUT] Existing trigger(s) found → PREFER NEW TRIGGER")
                self._print_queue("BEFORE REPLACE (PUT)")

                # Remove ALL old triggers for this session
                self._heap = [t for t in self._heap if t.session_id != trig.session_id]

                # Tell the durable store the old triggers were superseded so
                # their rows are settled (not silently dropped / rehydrated).
                self._notify_evicted(same, trig)

                # NEW BEHAVIOUR: prefer new → push new trigger only
                heapq.heappush(self._heap, trig)

                logger.debug("[PUT] REPLACED old triggers with NEW trigger")
                self._print_queue("AFTER REPLACE (PUT)")

            else:
                logger.debug("[PUT] No existing session trigger → pushing normally")
                heapq.heappush(self._heap, trig)

            heapq.heapify(self._heap)

            self._print_queue("AFTER PUT")
            self._cv.notify()

    # =================================================================
    # GET
    # =================================================================
    @profile("trigger_queue_get", OperationCategory.TRIGGER)
    async def get(self) -> Trigger:
        """
        Retrieve the next trigger to execute, waiting until one is ready.

        Pops the highest-priority due trigger. If no trigger is ready, waits
        until either the earliest trigger's ``fire_at`` time arrives or a
        producer notifies the condition.

        Same-session replacement in put() guarantees at most one queued
        trigger per session, so no cross-trigger merging is needed here
        (the pre-#321 merge machinery was removed with that invariant).

        Returns:
            The next :class:`Trigger` ready for execution.
        """
        logger.debug("\n[GET] CALLED")
        self._print_queue("QUEUE BEFORE GET")

        async with self._cv:
            while True:
                now = time.time()

                # collect ready triggers
                ready: List[Trigger] = []
                while self._heap and self._heap[0].fire_at <= now:
                    ready.append(heapq.heappop(self._heap))

                if ready:
                    logger.debug(f"[GET] {len(ready)} trigger(s) are ready")

                    ready.sort(key=lambda t: (t.priority, t.fire_at))
                    trig = ready.pop(0)
                    logger.info(
                        f"[TRIGGER FIRED] session={trig.session_id} | desc={trig.next_action_description}"
                    )

                    # requeue leftover
                    for t in ready:
                        heapq.heappush(self._heap, t)

                    # Track as active so fire() can find it while processing
                    if trig.session_id:
                        self._active[trig.session_id] = trig

                    self._print_queue("QUEUE AFTER GET")
                    return trig

                # wait for next trigger
                if self._heap:
                    next_fire = self._heap[0].fire_at
                    delay = next_fire - now
                    if delay <= 0:
                        continue
                    try:
                        await asyncio.wait_for(self._cv.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        continue
                else:
                    await self._cv.wait()

    # =================================================================
    # SIZE / LIST
    # =================================================================
    async def size(self) -> int:
        """
        Count how many triggers are currently queued.

        Returns:
            The number of triggers stored in the heap.
        """
        async with self._cv:
            return len(self._heap)

    async def list_triggers(self) -> List[Trigger]:
        """
        List the triggers currently in the queue without altering order.

        Returns:
            A shallow copy of the internal trigger heap contents.
        """
        async with self._cv:
            return list(self._heap)

    # =================================================================
    # FIRE NOW
    # =================================================================
    async def fire(
        self,
        session_id: str,
        *,
        message: str | None = None,
        platform: str | None = None,
        living_ui_id: str | None = None,
    ) -> bool:
        """
        Mark a trigger for a given session as ready to fire immediately.

        The ``fire_at`` timestamp for matching triggers is updated to the
        current time, and waiting consumers are notified. Also checks active
        triggers (currently being processed) to attach messages.

        Args:
            session_id: Identifier of the session whose trigger should fire
                now.
            message: Optional new user message to append to the trigger's
                description so the reasoning step sees it.
            platform: Optional platform identifier (e.g., "Telegram", "WhatsApp")
                to preserve message source information.
            living_ui_id: Optional Living UI project ID if user is on a Living UI page.

        Returns:
            ``True`` if a trigger was found (queued or active), otherwise ``False``.
        """
        async with self._cv:
            found = False

            # Check queued triggers first
            for t in self._heap:
                if t.session_id == session_id:
                    t.fire_at = time.time()
                    if message:
                        # Store in payload instead of polluting the description
                        t.payload["pending_user_message"] = message
                        if platform:
                            t.payload["pending_platform"] = platform
                    if living_ui_id:
                        t.payload["living_ui_id"] = living_ui_id
                    found = True

            if found:
                heapq.heapify(self._heap)  # restore heap invariant after fire_at change
                self._cv.notify()
                return True

            # Check active triggers (being processed)
            if session_id in self._active:
                t = self._active[session_id]
                if message:
                    # Store in payload instead of polluting the description
                    t.payload["pending_user_message"] = message
                    if platform:
                        t.payload["pending_platform"] = platform
                if living_ui_id:
                    t.payload["living_ui_id"] = living_ui_id
                logger.debug(
                    f"[FIRE] Attached message to active trigger for session {session_id}"
                )
                return True

            return False

    # =================================================================
    # REMOVE SESSIONS
    # =================================================================
    async def remove_sessions(self, session_ids: list[str]) -> None:
        """
        Remove all triggers that belong to the provided session identifiers.

        Args:
            session_ids: Sessions whose queued triggers should be discarded.
                An empty list leaves the queue unchanged.
        """
        if not session_ids:
            return
        async with self._cv:
            removed = [t for t in self._heap if t.session_id in session_ids]
            self._heap = [t for t in self._heap if t.session_id not in session_ids]
            # Also remove from active triggers. Active triggers are NOT
            # reported as evicted — the consumer still holds them and will
            # ack/nack when its react cycle finishes.
            for sid in session_ids:
                self._active.pop(sid, None)
            self._notify_evicted(removed, None)
            heapq.heapify(self._heap)
            self._cv.notify_all()

    def mark_session_inactive(self, session_id: str) -> None:
        """
        Remove a session from active tracking when processing completes.

        This should be called when a task/session ends to clean up the
        _active dict.

        Args:
            session_id: The session that finished processing.
        """
        self._active.pop(session_id, None)

    def pop_pending_user_message(
        self, session_id: str
    ) -> tuple[str | None, str | None]:
        """
        Extract and remove any pending user message from an active trigger.

        When fire() attaches a message to an active trigger's payload,
        this method extracts that message so it can be carried forward
        to the next trigger.

        Args:
            session_id: The session to check for pending messages.

        Returns:
            Tuple of (message, platform). Both are None if no pending message.
        """
        if session_id not in self._active:
            return None, None

        trigger = self._active[session_id]

        # Extract and remove the message from payload
        message = trigger.payload.pop("pending_user_message", None)
        platform = trigger.payload.pop("pending_platform", None)

        if message:
            logger.debug(
                f"[TRIGGER] Extracted pending user message for session {session_id}: {message[:50]}..."
            )

        return message, platform
