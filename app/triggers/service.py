# -*- coding: utf-8 -*-
"""
app.triggers.service

TriggerService — the single producer front door for durable triggers.

``emit()`` writes the trigger to the store FIRST (no LLM call, sub-ms), then
feeds the in-memory TriggerQueue, which stays as the ordering primitive. The
consumer drives the lifecycle through ``next()`` (claim) and ``ack()``/
``nack()`` (settle); ``rehydrate()`` re-delivers everything unfinished at
boot. The service also implements the queue's lifecycle-listener protocol so
triggers the queue discards (same-session replacement, session removal,
clear) settle their rows instead of resurrecting on the next boot.

Producers that still call ``queue.put()`` directly keep working: their
triggers carry no store ``id``, so claim/ack are no-ops for them.

For user messages there is additionally ``park()``: the message is durably
recorded BEFORE the session-routing LLM call, so a crash mid-routing no
longer loses it — the parked row is re-delivered (as a fresh session) by
the next boot's rehydration.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from agent_core.core.trigger import Trigger
from agent_core.core.impl.trigger.queue import TriggerQueue

from app.triggers.sources import TriggerSource
from app.triggers.store import STALE_TRIGGER_HOURS, TriggerStore

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# A trigger rehydrated/fired more than this many seconds late gets a
# catch-up note so the agent can use judgment (generalizes the Phase 0
# scheduler-only behavior to every source).
CATCHUP_THRESHOLD_SECONDS = 120

# Retry policy for triggers whose react cycle raised: exponential backoff
# (30s, 60s, 120s, 240s, capped at 1h), then dead-letter after MAX_ATTEMPTS.
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 3600

# Settled rows older than this are garbage-collected at boot.
GC_TTL_HOURS = 7 * 24


@dataclass
class TriggerSpec:
    """What a producer asks TriggerService to durably schedule."""

    source: Union[TriggerSource, str]
    description: str
    fire_at: Optional[float] = None  # None → now
    priority: int = 50
    session_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    dedup_key: Optional[str] = None
    # Deprecated, ignored: in-queue routing was removed (Phase 3); the queue
    # treats every put identically. Kept so existing call sites don't break.
    skip_merge: bool = False
    waiting_for_reply: bool = False


@dataclass
class EmitResult:
    trigger_id: Optional[int]
    deduped: bool


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        value, unit = seconds, "second"
    elif seconds < 3600:
        value, unit = seconds // 60, "minute"
    elif seconds < 86400:
        value, unit = seconds // 3600, "hour"
    else:
        value, unit = seconds // 86400, "day"
    return f"{value} {unit}{'s' if value != 1 else ''}"


class TriggerService:
    """Durable front door over (TriggerStore, TriggerQueue)."""

    def __init__(self, store: TriggerStore, queue: TriggerQueue) -> None:
        self._store = store
        self._queue = queue
        # Optional callback(trigger, error) invoked when a trigger exhausts
        # its retries and is parked DEAD — the app layer surfaces it to the
        # user (a dead-lettered trigger is work that silently stopped).
        self._on_dead_letter = None
        queue.set_lifecycle_listener(self)

    def set_dead_letter_handler(self, handler) -> None:
        """Register callback(trigger, error) fired on the DEAD transition."""
        self._on_dead_letter = handler

    # ─────────────────────── Producer API ───────────────────────────────────

    async def emit(self, spec: TriggerSpec) -> EmitResult:
        """Durably record a trigger, then enqueue it.

        The store INSERT happens first — from that point a crash anywhere
        loses nothing. A dedup_key collision with an active row means this
        work is already queued or in flight: no enqueue, no double-fire.
        """
        fire_at = spec.fire_at if spec.fire_at is not None else time.time()
        source = (
            spec.source.value
            if isinstance(spec.source, TriggerSource)
            else str(spec.source)
        )

        row_id, created = self._store.insert(
            source=source,
            description=spec.description,
            fire_at=fire_at,
            priority=spec.priority,
            session_id=spec.session_id,
            payload=spec.payload,
            dedup_key=spec.dedup_key,
            waiting_for_reply=spec.waiting_for_reply,
        )
        if not created:
            logger.info(
                f"[TriggerService] Deduped emit (key={spec.dedup_key!r}, "
                f"existing row={row_id})"
            )
            return EmitResult(row_id, True)

        trig = Trigger(
            fire_at=fire_at,
            priority=spec.priority,
            next_action_description=spec.description,
            payload=dict(spec.payload),
            session_id=spec.session_id,
            waiting_for_reply=spec.waiting_for_reply,
            id=row_id,
            source=source,
        )
        await self._queue.put(trig)
        return EmitResult(row_id, False)

    def park(self, spec: TriggerSpec) -> Optional[int]:
        """Durably record a trigger WITHOUT enqueueing it.

        Used for incoming user messages before session routing: the routing
        LLM call takes seconds and a crash during it would otherwise lose
        the message entirely. The caller settles the parked row once the
        message reaches its destination (``settle_parked``); if it never
        does, rehydration re-delivers the row as a fresh session.
        """
        fire_at = spec.fire_at if spec.fire_at is not None else time.time()
        source = (
            spec.source.value
            if isinstance(spec.source, TriggerSource)
            else str(spec.source)
        )
        row_id, _ = self._store.insert(
            source=source,
            description=spec.description,
            fire_at=fire_at,
            priority=spec.priority,
            session_id=spec.session_id,
            payload=spec.payload,
            dedup_key=spec.dedup_key,
            waiting_for_reply=spec.waiting_for_reply,
        )
        return row_id

    def settle_parked(
        self, row_id: Optional[int], delivered_as: Optional[int] = None
    ) -> None:
        """Mark a parked row as delivered to its destination.

        Args:
            row_id: The parked row (None is a no-op for convenience).
            delivered_as: The store row that now carries the work — the new
                session's trigger row, or None when the message was attached
                to an existing session's trigger via fire().
        """
        if row_id is None:
            return
        self._store.supersede([row_id], by_id=delivered_as)

    # ─────────────────────── Consumer API ───────────────────────────────────

    async def next(self) -> Trigger:
        """Wait for the next due trigger and claim its store row."""
        trig = await self._queue.get()
        if trig.id is not None:
            self._store.claim([trig.id])
        return trig

    async def ack(self, trig: Trigger) -> None:
        """The react cycle for this trigger completed."""
        if trig.id is not None:
            self._store.ack([trig.id])

    async def nack(self, trig: Trigger, error: str) -> None:
        """The react cycle raised before completing — retry with backoff.

        attempts < MAX_ATTEMPTS: the row goes back to PENDING with an
        exponential backoff floor and is re-enqueued. Otherwise it is parked
        DEAD and surfaced via the dead-letter handler. (react() handles most
        of its own errors internally; this path covers consumer-level
        failures, so the retry budget is rarely consumed.)
        """
        if trig.id is None:
            return
        row = self._store.get(trig.id)
        attempts = row["attempts"] if row else MAX_ATTEMPTS

        if attempts >= MAX_ATTEMPTS:
            self._store.mark_dead([trig.id], error=error)
            logger.error(
                f"[TriggerService] Trigger {trig.id} ({trig.source}) dead-lettered "
                f"after {attempts} attempts: {error}"
            )
            if self._on_dead_letter:
                try:
                    self._on_dead_letter(trig, error)
                except Exception as e:
                    logger.warning(f"[TriggerService] Dead-letter handler failed: {e}")
            return

        backoff = min(
            BACKOFF_BASE_SECONDS * (2 ** max(attempts - 1, 0)), BACKOFF_CAP_SECONDS
        )
        not_before = time.time() + backoff
        self._store.retry(trig.id, not_before, error=error)
        logger.warning(
            f"[TriggerService] Trigger {trig.id} ({trig.source}) failed "
            f"(attempt {attempts}/{MAX_ATTEMPTS}), retrying in {int(backoff)}s: {error}"
        )
        retry_trig = Trigger(
            fire_at=not_before,
            priority=trig.priority,
            next_action_description=trig.next_action_description,
            payload=dict(trig.payload),
            session_id=trig.session_id,
            waiting_for_reply=trig.waiting_for_reply,
            id=trig.id,
            source=trig.source,
        )
        await self._queue.put(retry_trig)

    # ─────────────────────── fire() pass-through ────────────────────────────

    async def fire(
        self,
        session_id: str,
        *,
        message: Optional[str] = None,
        platform: Optional[str] = None,
        living_ui_id: Optional[str] = None,
    ) -> bool:
        """Retarget a session's trigger to now, durably mirroring the change.

        The store write happens before the in-memory mutation so an attached
        user message survives a crash mid-react (today it would be lost).
        """
        patch: Dict[str, Any] = {}
        if message:
            patch["pending_user_message"] = message
            if platform:
                patch["pending_platform"] = platform
        if living_ui_id:
            patch["living_ui_id"] = living_ui_id
        try:
            self._store.update_for_fire(session_id, time.time(), patch)
        except Exception as e:
            logger.warning(f"[TriggerService] Failed to mirror fire() to store: {e}")
        return await self._queue.fire(
            session_id,
            message=message,
            platform=platform,
            living_ui_id=living_ui_id,
        )

    # ─────────────────────── Boot recovery ──────────────────────────────────

    async def rehydrate(self) -> int:
        """Re-deliver every unfinished trigger from the previous run.

        1. CLAIMED orphans (in flight when the process died) → PENDING.
        2. Load PENDING rows into the queue. Stale rows (> 24h past due,
           mirroring the task TTL) are settled instead of re-fired; overdue
           rows get an agent-judgment catch-up note (generalized Phase 0).

        Must run BEFORE ``_schedule_restored_task_triggers()`` so boot-time
        ``resume:{task_id}`` re-emits hit the dedup index instead of
        double-enqueueing.
        """
        self._store.reclaim_claimed()

        now = time.time()
        stale_ids: List[int] = []
        requeued = 0

        for row in self._store.load_pending():
            overdue = now - row["fire_at"]

            if overdue > STALE_TRIGGER_HOURS * 3600:
                stale_ids.append(row["id"])
                logger.info(
                    f"[TriggerService] Skipping stale trigger {row['id']} "
                    f"({row['source']}, {_format_duration(overdue)} past due)"
                )
                continue

            try:
                payload = json.loads(row["payload_json"])
            except (ValueError, TypeError):
                payload = {}
            description = row["description"]

            if overdue > CATCHUP_THRESHOLD_SECONDS and not payload.get("is_catch_up"):
                note = (
                    f"NOTE: This trigger was due about "
                    f"{_format_duration(overdue)} ago but CraftBot was offline "
                    f"at the time. Use your judgment: if it is only slightly "
                    f"late and still relevant, carry it out normally. If it is "
                    f"significantly late, or the action is time-sensitive or "
                    f"irreversible (e.g. sending a message or email), confirm "
                    f"with the user before proceeding, or skip it if it is no "
                    f"longer relevant."
                )
                payload["is_catch_up"] = True
                payload["overdue_seconds"] = overdue
                description = f"{description}\n\n{note}"

            # A row with no session is a parked user message whose routing
            # never completed (crash mid-route). Re-deliver it as a fresh
            # session — the agent handles it like a newly arrived message.
            session_id = row["session_id"]
            if not session_id:
                session_id = uuid.uuid4().hex[:6]
                self._store.update_session(row["id"], session_id)
                logger.info(
                    f"[TriggerService] Recovered unrouted trigger {row['id']} "
                    f"as new session {session_id}"
                )

            trig = Trigger(
                fire_at=row["fire_at"],
                priority=row["priority"],
                next_action_description=description,
                payload=payload,
                session_id=session_id,
                waiting_for_reply=bool(row["waiting_for_reply"]),
                id=row["id"],
                source=row["source"] or "",
            )
            await self._queue.put(trig)
            requeued += 1

        if stale_ids:
            self._store.mark_stale(stale_ids)
        if requeued:
            logger.info(
                f"[TriggerService] Rehydrated {requeued} pending trigger(s) "
                "from previous run"
            )

        # Boot-time housekeeping: drop settled rows past the TTL.
        try:
            self._store.gc(ttl_hours=GC_TTL_HOURS)
        except Exception as e:
            logger.warning(f"[TriggerService] Trigger GC failed: {e}")

        return requeued

    # ─────────────────────── Session / reset cleanup ────────────────────────

    async def cancel_sessions(self, session_ids: List[str]) -> None:
        """Settle a session's rows and drop its queued triggers."""
        self._store.cancel_sessions(session_ids)
        await self._queue.remove_sessions(session_ids)

    def clear_all(self) -> None:
        """Wipe the store (agent reset path)."""
        self._store.clear_all()

    # ─────────────────────── TriggerLifecycleListener ───────────────────────

    def on_evicted(
        self, evicted: List[Trigger], replacement: Optional[Trigger]
    ) -> None:
        """Queue discarded triggers unconsumed — settle their rows."""
        ids = [t.id for t in evicted if t.id is not None]
        if not ids:
            return
        if replacement is not None:
            self._store.supersede(ids, replacement.id)
        else:
            self._store.cancel(ids)
