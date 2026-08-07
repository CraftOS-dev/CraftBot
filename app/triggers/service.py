# -*- coding: utf-8 -*-
"""
app.triggers.service

TriggerService — the single producer front door for durable triggers.

``emit()`` writes the trigger to the store FIRST (no LLM call, sub-ms), then
dispatches it to the owning session's runtime queue. Each session's serial
loop drives the lifecycle through ``claim()`` and ``ack()``/``nack()``;
``rehydrate()`` re-delivers everything unfinished at boot. The service also
implements the queues' lifecycle-listener protocol so triggers a queue
discards (session deletion, clear) settle their rows instead of resurrecting
on the next boot.

There is no routing: every producer names its destination session at emit
time (external input and background workflows target the main session; UI
messages target the session they were typed in).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

from agent_core.core.trigger import Trigger
from agent_core.core.session import MAIN_SESSION_ID

from app.triggers.sources import TriggerSource
from app.triggers.store import STALE_TRIGGER_HOURS, TriggerStore

if TYPE_CHECKING:
    from app.triggers.runtime import SessionRuntimeManager

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# A trigger rehydrated/fired more than this many seconds late gets a
# catch-up note so the agent can use judgment.
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
    session_id: Optional[str] = None  # None → main session
    payload: Dict[str, Any] = field(default_factory=dict)
    dedup_key: Optional[str] = None


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
    """Durable front door over (TriggerStore, SessionRuntimeManager)."""

    def __init__(self, store: TriggerStore, runtime: "SessionRuntimeManager") -> None:
        self._store = store
        self._runtime = runtime
        # Optional callback(trigger, error) invoked when a trigger exhausts
        # its retries and is parked DEAD — the app layer surfaces it to the
        # user (a dead-lettered trigger is work that silently stopped).
        self._on_dead_letter = None
        runtime.bind_service(self)

    def set_dead_letter_handler(self, handler) -> None:
        """Register callback(trigger, error) fired on the DEAD transition."""
        self._on_dead_letter = handler

    # ─────────────────────── Producer API ───────────────────────────────────

    async def emit(self, spec: TriggerSpec) -> EmitResult:
        """Durably record a trigger, then dispatch it to its session queue.

        The store INSERT happens first — from that point a crash anywhere
        loses nothing. A dedup_key collision with an active row means this
        work is already queued or in flight: no dispatch, no double-fire.
        """
        fire_at = spec.fire_at if spec.fire_at is not None else time.time()
        source = (
            spec.source.value
            if isinstance(spec.source, TriggerSource)
            else str(spec.source)
        )
        session_id = spec.session_id or MAIN_SESSION_ID

        row_id, created = self._store.insert(
            source=source,
            description=spec.description,
            fire_at=fire_at,
            priority=spec.priority,
            session_id=session_id,
            payload=spec.payload,
            dedup_key=spec.dedup_key,
            waiting_for_reply=False,
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
            session_id=session_id,
            id=row_id,
            source=source,
        )
        await self._runtime.dispatch(trig)
        return EmitResult(row_id, False)

    # ─────────────────────── Consumer API (session loops) ───────────────────

    def claim(self, trig: Trigger) -> None:
        """A session loop picked this trigger up — claim its store row."""
        if trig.id is not None:
            self._store.claim([trig.id])

    async def ack(self, trig: Trigger) -> None:
        """The turn for this trigger completed."""
        if trig.id is not None:
            self._store.ack([trig.id])

    async def nack(self, trig: Trigger, error: str) -> None:
        """The turn raised before completing — retry with backoff.

        attempts < MAX_ATTEMPTS: the row goes back to PENDING with an
        exponential backoff floor and is re-dispatched. Otherwise it is
        parked DEAD and surfaced via the dead-letter handler.
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
            id=trig.id,
            source=trig.source,
        )
        await self._runtime.dispatch(retry_trig)

    # ─────────────────────── Boot recovery ──────────────────────────────────

    async def rehydrate(self) -> int:
        """Re-deliver every unfinished trigger from the previous run.

        1. CLAIMED orphans (in flight when the process died) → PENDING.
        2. Load PENDING rows into the session queues. Stale rows (> 24h past
           due) are settled instead of re-fired; overdue rows get an
           agent-judgment catch-up note.
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

            # Rows from deleted or unknown sessions deliver to main so no
            # durable work is silently lost.
            session_id = row["session_id"] or MAIN_SESSION_ID

            trig = Trigger(
                fire_at=row["fire_at"],
                priority=row["priority"],
                next_action_description=description,
                payload=payload,
                session_id=session_id,
                id=row["id"],
                source=row["source"] or "",
            )
            await self._runtime.dispatch(trig)
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
        """Settle a session's rows and tear down its runtime lane."""
        self._store.cancel_sessions(session_ids)
        for session_id in session_ids:
            await self._runtime.remove_session(session_id)

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
