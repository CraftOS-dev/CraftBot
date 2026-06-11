# -*- coding: utf-8 -*-
"""
app.triggers.service

TriggerService — the single producer front door for durable triggers
(issue #321, Primitive A).

``emit()`` writes the trigger to the store FIRST (no LLM call, sub-ms), then
feeds the in-memory TriggerQueue, which stays as the ordering primitive. The
consumer drives the lifecycle through ``next()`` (claim) and ``ack()``/
``nack()`` (settle); ``rehydrate()`` re-delivers everything unfinished at
boot. The service also implements the queue's lifecycle-listener protocol so
triggers the queue discards (same-session replacement, session removal,
clear) settle their rows instead of resurrecting on the next boot.

Legacy producers that still call ``queue.put()`` directly keep working:
their triggers carry no ``store_ids``, so claim/ack are no-ops for them.
"""

from __future__ import annotations

import json
import logging
import time
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
        queue.set_lifecycle_listener(self)

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
            store_ids=[row_id] if row_id is not None else [],
        )
        await self._queue.put(trig, skip_merge=spec.skip_merge)
        return EmitResult(row_id, False)

    # ─────────────────────── Consumer API ───────────────────────────────────

    async def next(self) -> Trigger:
        """Wait for the next due trigger and claim its store rows."""
        trig = await self._queue.get()
        if trig.store_ids:
            self._store.claim(trig.store_ids)
        return trig

    async def ack(self, trig: Trigger) -> None:
        """The react cycle for this trigger completed."""
        if trig.store_ids:
            self._store.ack(trig.store_ids)

    async def nack(self, trig: Trigger, error: str) -> None:
        """The react cycle raised before completing."""
        if trig.store_ids:
            self._store.fail(trig.store_ids, error=error)

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

            trig = Trigger(
                fire_at=row["fire_at"],
                priority=row["priority"],
                next_action_description=description,
                payload=payload,
                session_id=row["session_id"],
                waiting_for_reply=bool(row["waiting_for_reply"]),
                id=row["id"],
                source=row["source"] or "",
                store_ids=[row["id"]],
            )
            await self._queue.put(trig, skip_merge=True)
            requeued += 1

        if stale_ids:
            self._store.mark_stale(stale_ids)
        if requeued:
            logger.info(
                f"[TriggerService] Rehydrated {requeued} pending trigger(s) "
                "from previous run"
            )
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
        ids = [row_id for t in evicted for row_id in (t.store_ids or [])]
        if not ids:
            return
        if replacement is not None:
            self._store.supersede(ids, replacement.id)
        else:
            self._store.cancel(ids)
