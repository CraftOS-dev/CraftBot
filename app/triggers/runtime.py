# -*- coding: utf-8 -*-
"""
app.triggers.runtime

SessionRuntimeManager — one trigger queue + one serial agent loop per session.

Every session is a standalone agent lane: its triggers are processed strictly
in order by its own consumer loop, while different sessions run their turns
concurrently (bounded by a global turn semaphore so a Living UI build can't
starve the main chat, and N sessions can't stampede the LLM provider).

Durability stays in TriggerService/TriggerStore: the runtime claims a row
when its loop picks the trigger up and acks/nacks when the turn settles.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Dict, Optional, TYPE_CHECKING

from agent_core.core.trigger import Trigger
from agent_core.core.impl.trigger.session_queue import (
    SessionTriggerQueue,
    QueueClosed,
)
from agent_core.core.session import MAIN_SESSION_ID

if TYPE_CHECKING:
    from app.triggers.service import TriggerService

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# How many session turns may run concurrently across all sessions. Serial
# within a session is guaranteed by the per-session loop; this bounds the
# cross-session parallelism (LLM rate limits, local resource pressure).
DEFAULT_MAX_CONCURRENT_TURNS = 3

ReactFn = Callable[[Trigger], Awaitable[None]]


class SessionRuntimeManager:
    """Owns the per-session queues and their serial consumer loops."""

    def __init__(
        self,
        react: ReactFn,
        max_concurrent_turns: int = DEFAULT_MAX_CONCURRENT_TURNS,
    ) -> None:
        self._react = react
        self._queues: Dict[str, SessionTriggerQueue] = {}
        self._loops: Dict[str, asyncio.Task] = {}
        self._turn_semaphore = asyncio.Semaphore(max_concurrent_turns)
        self._running = False
        self._service: Optional["TriggerService"] = None

    def bind_service(self, service: "TriggerService") -> None:
        """Attach the durable TriggerService (claim/ack/nack + row settling)."""
        self._service = service

    # ─────────────────────── Lifecycle ──────────────────────────────────────

    async def start(self) -> None:
        """Start consumer loops for every queue that exists (post-rehydrate)."""
        self._running = True
        for session_id in list(self._queues.keys()):
            self._ensure_loop(session_id)
        logger.info(
            f"[SessionRuntime] Started ({len(self._loops)} session loop(s))"
        )

    async def stop(self) -> None:
        """Cancel all consumer loops (shutdown). Queued triggers stay durable."""
        self._running = False
        for task in self._loops.values():
            task.cancel()
        for task in list(self._loops.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._loops.clear()
        logger.info("[SessionRuntime] Stopped")

    # ─────────────────────── Dispatch ────────────────────────────────────────

    async def dispatch(self, trig: Trigger) -> None:
        """Route a trigger into its session's queue (main when unset)."""
        session_id = trig.session_id or MAIN_SESSION_ID
        trig.session_id = session_id
        queue = self._ensure_queue(session_id)
        try:
            await queue.put(trig)
        except QueueClosed:
            # Session deleted between emit and dispatch — settle the row.
            logger.info(
                f"[SessionRuntime] Dropping trigger for deleted session {session_id}"
            )
            if self._service:
                self._service.on_evicted([trig], None)
            return
        if self._running:
            self._ensure_loop(session_id)

    def has_pending(self, session_id: str) -> bool:
        """Whether a session has queued triggers (non-blocking)."""
        queue = self._queues.get(session_id)
        return queue.has_pending() if queue else False

    async def remove_session(self, session_id: str) -> None:
        """Tear down a deleted session's queue and loop.

        Queued triggers are discarded; the queue reports them to the
        lifecycle listener so their durable rows settle.
        """
        if session_id == MAIN_SESSION_ID:
            logger.warning("[SessionRuntime] Refusing to remove the main session")
            return
        queue = self._queues.pop(session_id, None)
        if queue is not None:
            await queue.close()
        loop_task = self._loops.pop(session_id, None)
        if loop_task is not None:
            loop_task.cancel()
            try:
                await loop_task
            except (asyncio.CancelledError, Exception):
                pass

    # ─────────────────────── Internals ───────────────────────────────────────

    def _ensure_queue(self, session_id: str) -> SessionTriggerQueue:
        queue = self._queues.get(session_id)
        if queue is None:
            queue = SessionTriggerQueue(session_id)
            if self._service is not None:
                queue.set_lifecycle_listener(self._service)
            self._queues[session_id] = queue
        return queue

    def _ensure_loop(self, session_id: str) -> None:
        existing = self._loops.get(session_id)
        if existing is not None and not existing.done():
            return
        queue = self._ensure_queue(session_id)
        self._loops[session_id] = asyncio.create_task(
            self._consume(session_id, queue),
            name=f"session-loop-{session_id}",
        )

    async def _consume(self, session_id: str, queue: SessionTriggerQueue) -> None:
        """The serial agent loop for one session: claim → react → settle."""
        logger.info(f"[SessionRuntime] Loop started for session {session_id}")
        while self._running:
            try:
                trig = await queue.get()
            except QueueClosed:
                break
            except asyncio.CancelledError:
                raise

            if self._service:
                self._service.claim(trig)

            try:
                async with self._turn_semaphore:
                    await self._react(trig)
            except asyncio.CancelledError:
                # Shutdown mid-turn: leave the row CLAIMED — boot-time
                # rehydration reclaims it (at-least-once delivery).
                raise
            except Exception as e:
                logger.error(
                    f"[SessionRuntime] Turn failed for {session_id}: {e}",
                    exc_info=True,
                )
                if self._service:
                    try:
                        await self._service.nack(trig, str(e))
                    except Exception as nack_err:
                        logger.error(
                            f"[SessionRuntime] nack failed: {nack_err}"
                        )
                continue

            if self._service:
                try:
                    await self._service.ack(trig)
                except Exception as e:
                    logger.warning(f"[SessionRuntime] ack failed: {e}")
        logger.info(f"[SessionRuntime] Loop ended for session {session_id}")
