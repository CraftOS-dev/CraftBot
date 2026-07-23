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
from app.triggers.sources import TriggerSource

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

# Trigger sources that may be AGGREGATED into a single turn when several
# are due at claim time. User messages that piled up while a run was busy
# are one conversation, not N work items — firing a separate turn for each
# makes the agent grind through redundant turns (and re-answer spam
# one-by-one). Scheduler jobs, Living UI builds, continuations, and the
# special workflows stay one-trigger-one-turn: each is a distinct unit of
# work with its own semantics.
AGGREGATABLE_SOURCES = frozenset({TriggerSource.USER_MESSAGE.value})

ReactFn = Callable[[Trigger], Awaitable[None]]


def _merge_triggers(base: Trigger, extras: list[Trigger]) -> Trigger:
    """Fold queued same-source triggers into `base` for one aggregated turn.

    The merged description is ONE clean instruction: the raw user messages
    as a numbered checklist plus an explicit rule for how corrections
    interact — without it, the LLM reads a batch like "shanghai too /
    londong / kuala lumpur / I mean london*" as the user changing their
    mind and settling on the last item, dropping the rest (observed in
    production). Payload user_message fields are joined; routing fields
    (platform/contact/channel) take the most recent non-empty value;
    workflow skill/action-set lists union.
    """
    group = [base] + extras
    total = len(group)

    # Prefer the raw message text (payload.user_message) for the checklist;
    # fall back to the trigger description for triggers without one.
    items: list[str] = []
    for t in group:
        raw = ((t.payload or {}).get("user_message") or "").strip()
        items.append(raw if raw else t.next_action_description)

    numbered = "\n".join(f"{i}. {text}" for i, text in enumerate(items, start=1))
    base.next_action_description = (
        f"The user sent {total} messages while you were busy. Address EVERY "
        f"message below. A later message supersedes an earlier one ONLY if it "
        f"explicitly corrects or withdraws that specific message; otherwise "
        f"each one is separate work (e.g. multiple items to look up).\n"
        f"{numbered}\n"
        f"Before ending the run, verify each message above was handled or "
        f"answered."
    )

    base.payload = base.payload or {}
    messages = [base.payload.get("user_message") or ""]
    for t in extras:
        p = t.payload or {}
        m = p.get("user_message") or ""
        if m:
            messages.append(m)
        for key in ("platform", "contact_id", "channel_id"):
            if p.get(key):
                base.payload[key] = p[key]
        if p.get("is_self_message"):
            base.payload["is_self_message"] = True
        for list_key in ("workflow_skills", "workflow_action_sets"):
            incoming = p.get(list_key)
            if incoming:
                current = list(base.payload.get(list_key) or [])
                base.payload[list_key] = list(dict.fromkeys(current + list(incoming)))
    joined = "\n\n".join(m for m in messages if m)
    if joined:
        base.payload["user_message"] = joined
    return base


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
        """The serial agent loop for one session: claim → react → settle.

        Aggregation: after claiming a trigger of an aggregatable source,
        any same-source triggers already due (they piled up while the
        previous turn was running) are drained and merged into the SAME
        turn. All merged rows are claimed together and settle together.
        """
        logger.info(f"[SessionRuntime] Loop started for session {session_id}")
        while self._running:
            try:
                trig = await queue.get()
            except QueueClosed:
                break
            except asyncio.CancelledError:
                raise

            extras: list[Trigger] = []
            if trig.source in AGGREGATABLE_SOURCES:
                try:
                    extras = await queue.pop_due_batch(trig.source)
                except Exception as e:
                    logger.warning(f"[SessionRuntime] Batch drain failed: {e}")
            group = [trig] + extras

            if self._service:
                for t in group:
                    self._service.claim(t)

            if extras:
                logger.info(
                    f"[SessionRuntime] Aggregated {len(group)} queued "
                    f"'{trig.source}' triggers into one turn for {session_id}"
                )
                trig = _merge_triggers(trig, extras)

            try:
                async with self._turn_semaphore:
                    await self._react(trig)
            except asyncio.CancelledError:
                # Shutdown mid-turn: leave the rows CLAIMED — boot-time
                # rehydration reclaims them (at-least-once delivery).
                raise
            except Exception as e:
                logger.error(
                    f"[SessionRuntime] Turn failed for {session_id}: {e}",
                    exc_info=True,
                )
                if self._service:
                    for t in group:
                        try:
                            await self._service.nack(t, str(e))
                        except Exception as nack_err:
                            logger.error(
                                f"[SessionRuntime] nack failed: {nack_err}"
                            )
                continue

            if self._service:
                for t in group:
                    try:
                        await self._service.ack(t)
                    except Exception as e:
                        logger.warning(f"[SessionRuntime] ack failed: {e}")
        logger.info(f"[SessionRuntime] Loop ended for session {session_id}")
