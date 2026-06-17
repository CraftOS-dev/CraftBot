# -*- coding: utf-8 -*-
"""
app.triggers.store

Durable trigger store.

SQLite-backed write-ahead store for triggers: a trigger accepted by
TriggerService is INSERTed here as PENDING before it can run, claimed
(CLAIMED) when the consumer picks it up, and settled (DONE/FAILED) when the
react cycle finishes. A boot-time reclaim scan turns orphaned CLAIMED rows
back into PENDING, so a crash anywhere between emit and ack re-delivers
instead of losing work.

Dedup is enforced by the database, not application code: a partial UNIQUE
index on ``dedup_key`` over *active* rows (PENDING/CLAIMED) makes inserting
the same work twice an atomic no-op, while settled rows don't block
legitimate re-fires (e.g. ``resume:{task_id}`` on a later restart).

Same file and idioms as ``app/usage/session_storage.py`` (sessions.db, WAL,
short per-operation connections, sync API).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# Trigger lifecycle states
STATUS_PENDING = "PENDING"
STATUS_CLAIMED = "CLAIMED"
STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"
STATUS_DEAD = "DEAD"

ACTIVE_STATUSES = (STATUS_PENDING, STATUS_CLAIMED)

# How a settled row reached DONE/FAILED — for observability, not logic.
RESOLUTION_COMPLETED = "completed"
RESOLUTION_SUPERSEDED = "superseded"
RESOLUTION_CANCELLED = "cancelled"
RESOLUTION_FAILED = "failed"
RESOLUTION_STALE = "stale"

# PENDING rows whose fire_at is older than this are not rehydrated (mirrors
# the STALE_TASK_HOURS=24 task TTL in session_storage).
STALE_TRIGGER_HOURS = 24


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TriggerStore:
    """Durable persistence for triggers, layered under TriggerQueue."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from app.config import APP_DATA_PATH

            usage_dir = Path(APP_DATA_PATH) / ".usage"
            usage_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(usage_dir / "sessions.db")

        self._db_path = db_path
        self._init_db()
        logger.info(f"[TriggerStore] Initialized at {self._db_path}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        """Create the triggers table, replacing any pre-#321 legacy schema."""
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")

            # A `triggers` table existed in old CraftBot versions with a
            # different schema (session_storage used to DROP it every boot).
            # If a table without our dedup_key column is present, it's that
            # relic — replace it.
            cols = [
                row[1]
                for row in conn.execute("PRAGMA table_info(triggers)").fetchall()
            ]
            # "queue" is the newest column — its absence also catches a table
            # created by an earlier pre-release iteration of this branch.
            if cols and ("dedup_key" not in cols or "queue" not in cols):
                logger.info("[TriggerStore] Dropping legacy triggers table")
                conn.execute("DROP TABLE triggers")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS triggers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL DEFAULT '',
                    dedup_key TEXT,
                    session_id TEXT,
                    queue TEXT NOT NULL DEFAULT 'main',
                    fire_at REAL NOT NULL,
                    not_before REAL,
                    priority INTEGER NOT NULL DEFAULT 50,
                    description TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    waiting_for_reply INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    resolution TEXT,
                    superseded_by INTEGER,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    claimed_by TEXT,
                    lease_until REAL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_triggers_status_fire
                ON triggers(status, fire_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_triggers_session
                ON triggers(session_id)
            """)
            # Dedup is active-rows-only: a DONE resume:{task_id} must not
            # block a legitimate re-resume after the next restart.
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_triggers_dedup_active
                ON triggers(dedup_key)
                WHERE dedup_key IS NOT NULL
                  AND status IN ('PENDING', 'CLAIMED')
            """)
            conn.commit()

    # ─────────────────────── Insert / dedup ─────────────────────────────────

    def insert(
        self,
        *,
        source: str,
        description: str,
        fire_at: float,
        priority: int = 50,
        session_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        dedup_key: Optional[str] = None,
        not_before: Optional[float] = None,
        waiting_for_reply: bool = False,
        queue: str = "main",
    ) -> Tuple[Optional[int], bool]:
        """Durably record a trigger as PENDING.

        Returns:
            (row_id, created). When ``dedup_key`` collides with an active row,
            the insert is a no-op and the existing row's id is returned with
            created=False.
        """
        now = _now_iso()
        payload_json = json.dumps(payload or {}, default=str)
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO triggers (
                        source, dedup_key, session_id, queue, fire_at,
                        not_before, priority, description, payload_json,
                        waiting_for_reply, status, attempts, created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?)
                    """,
                    (
                        source,
                        dedup_key,
                        session_id,
                        queue,
                        fire_at,
                        not_before,
                        priority,
                        description,
                        payload_json,
                        1 if waiting_for_reply else 0,
                        now,
                        now,
                    ),
                )
                conn.commit()
                return cur.lastrowid, True
            except sqlite3.IntegrityError:
                row = conn.execute(
                    """
                    SELECT id FROM triggers
                    WHERE dedup_key = ? AND status IN ('PENDING', 'CLAIMED')
                    """,
                    (dedup_key,),
                ).fetchone()
                return (row[0] if row else None), False

    # ─────────────────────── Lifecycle transitions ───────────────────────────

    def _set_status(
        self,
        ids: List[int],
        status: str,
        *,
        resolution: Optional[str] = None,
        superseded_by: Optional[int] = None,
        last_error: Optional[str] = None,
    ) -> None:
        if not ids:
            return
        now = _now_iso()
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE triggers
                SET status = ?, resolution = ?, superseded_by = ?,
                    last_error = COALESCE(?, last_error),
                    lease_until = NULL, updated_at = ?
                WHERE id = ?
                """,
                [
                    (status, resolution, superseded_by, last_error, now, row_id)
                    for row_id in ids
                ],
            )
            conn.commit()

    def claim(
        self,
        ids: List[int],
        lease_seconds: float = 900.0,
        claimed_by: str = "main",
    ) -> List[int]:
        """Atomically mark rows as being worked on (PENDING → CLAIMED).

        Compare-and-swap semantics: a row is claimed only if it is still
        PENDING, and the list of actually-claimed ids is returned. With
        today's single consumer the claim always wins; with multiple
        sub-agent consumers (future) the database arbitrates — exactly one
        claimant per row.

        The lease exists for crash recovery: with a single consumer the
        boot-time reclaim scan re-delivers orphans; multi-consumer mode adds
        a periodic lease-expiry sweep.
        """
        if not ids:
            return []
        now = _now_iso()
        lease_until = time.time() + lease_seconds
        claimed: List[int] = []
        with self._connect() as conn:
            for row_id in ids:
                cur = conn.execute(
                    """
                    UPDATE triggers
                    SET status = 'CLAIMED', attempts = attempts + 1,
                        claimed_by = ?, lease_until = ?, updated_at = ?
                    WHERE id = ? AND status = 'PENDING'
                    """,
                    (claimed_by, lease_until, now, row_id),
                )
                if cur.rowcount:
                    claimed.append(row_id)
            conn.commit()
        return claimed

    def ack(self, ids: List[int]) -> None:
        """The react cycle completed — settle the rows (→ DONE)."""
        self._set_status(ids, STATUS_DONE, resolution=RESOLUTION_COMPLETED)

    def fail(self, ids: List[int], error: Optional[str] = None) -> None:
        """Settle the rows as FAILED (terminal — retries exhausted or
        explicitly not retryable)."""
        self._set_status(
            ids, STATUS_FAILED, resolution=RESOLUTION_FAILED, last_error=error
        )

    def retry(
        self, row_id: int, not_before: float, error: Optional[str] = None
    ) -> None:
        """A failed attempt gets another chance: back to PENDING with a
        backoff floor. ``attempts`` is preserved (claim increments it)."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE triggers
                SET status = 'PENDING', not_before = ?, fire_at = ?,
                    claimed_by = NULL, lease_until = NULL,
                    last_error = COALESCE(?, last_error), updated_at = ?
                WHERE id = ?
                """,
                (not_before, not_before, error, _now_iso(), row_id),
            )
            conn.commit()

    def mark_dead(self, ids: List[int], error: Optional[str] = None) -> None:
        """Retries exhausted — park the rows as DEAD (dead-letter)."""
        self._set_status(
            ids, STATUS_DEAD, resolution=RESOLUTION_FAILED, last_error=error
        )

    def supersede(self, ids: List[int], by_id: Optional[int]) -> None:
        """Rows replaced by a newer same-session trigger (→ DONE, marked)."""
        self._set_status(
            ids, STATUS_DONE, resolution=RESOLUTION_SUPERSEDED, superseded_by=by_id
        )

    def cancel(self, ids: List[int]) -> None:
        """Rows removed without execution (session cleanup, reset)."""
        self._set_status(ids, STATUS_DONE, resolution=RESOLUTION_CANCELLED)

    def cancel_sessions(self, session_ids: List[str]) -> int:
        """Settle every active row belonging to the given sessions."""
        if not session_ids:
            return 0
        now = _now_iso()
        placeholders = ",".join("?" for _ in session_ids)
        with self._connect() as conn:
            cur = conn.execute(
                f"""
                UPDATE triggers
                SET status = 'DONE', resolution = 'cancelled',
                    lease_until = NULL, updated_at = ?
                WHERE session_id IN ({placeholders})
                  AND status IN ('PENDING', 'CLAIMED')
                """,
                (now, *session_ids),
            )
            conn.commit()
            return cur.rowcount

    # ─────────────────────── Boot recovery ──────────────────────────────────

    def reclaim_claimed(self) -> int:
        """Boot scan: CLAIMED rows are orphans of a crashed run → PENDING.

        Single consumer means any CLAIMED row at boot was in-flight when the
        process died; lease expiry doesn't matter for this scan.
        """
        now = _now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE triggers
                SET status = 'PENDING', claimed_by = NULL,
                    lease_until = NULL, updated_at = ?
                WHERE status = 'CLAIMED'
                """,
                (now,),
            )
            conn.commit()
            if cur.rowcount:
                logger.info(
                    f"[TriggerStore] Reclaimed {cur.rowcount} in-flight trigger(s) "
                    "from previous run"
                )
            return cur.rowcount

    def load_pending(self) -> List[Dict[str, Any]]:
        """Return all PENDING rows (as dicts) ordered by fire_at."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM triggers WHERE status = 'PENDING' ORDER BY fire_at ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_stale(self, ids: List[int]) -> None:
        """Settle rows skipped at rehydration for being too old."""
        self._set_status(ids, STATUS_DONE, resolution=RESOLUTION_STALE)

    # ─────────────────────── fire() mirroring ───────────────────────────────

    def update_for_fire(
        self,
        session_id: str,
        fire_at: float,
        payload_patch: Dict[str, Any],
    ) -> int:
        """Mirror queue.fire() onto the session's active rows.

        Persists the retargeted fire_at and any attached user message BEFORE
        the in-memory mutation, so a crash mid-react keeps the message for
        redelivery.
        """
        now = _now_iso()
        updated = 0
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, payload_json FROM triggers
                WHERE session_id = ? AND status IN ('PENDING', 'CLAIMED')
                """,
                (session_id,),
            ).fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                except (ValueError, TypeError):
                    payload = {}
                payload.update(payload_patch)
                conn.execute(
                    """
                    UPDATE triggers
                    SET fire_at = ?, payload_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (fire_at, json.dumps(payload, default=str), now, row["id"]),
                )
                updated += 1
            conn.commit()
        return updated

    def gc(self, ttl_hours: float = 7 * 24) -> int:
        """Delete settled rows (DONE/FAILED/DEAD) older than the TTL.

        ISO-8601 UTC timestamps compare lexicographically, so a string
        comparison against the cutoff is correct.
        """
        cutoff = datetime.fromtimestamp(
            time.time() - ttl_hours * 3600, tz=timezone.utc
        ).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM triggers
                WHERE status IN ('DONE', 'FAILED', 'DEAD') AND updated_at < ?
                """,
                (cutoff,),
            )
            conn.commit()
            if cur.rowcount:
                logger.info(
                    f"[TriggerStore] GC removed {cur.rowcount} settled trigger row(s)"
                )
            return cur.rowcount

    def update_session(self, row_id: int, session_id: str) -> None:
        """Assign a session to a row (recovery of unrouted parked messages)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE triggers SET session_id = ?, updated_at = ? WHERE id = ?",
                (session_id, _now_iso(), row_id),
            )
            conn.commit()

    # ─────────────────────── Utilities ──────────────────────────────────────

    def get(self, row_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM triggers WHERE id = ?", (row_id,)
            ).fetchone()
        return dict(row) if row else None

    def count_by_status(self) -> Dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM triggers GROUP BY status"
            ).fetchall()
        return {status: count for status, count in rows}

    def clear_all(self) -> None:
        """Wipe the table. Part of the agent reset path — without this a
        reset followed by a restart would resurrect cleared work."""
        with self._connect() as conn:
            conn.execute("DELETE FROM triggers")
            conn.commit()
        logger.info("[TriggerStore] Cleared all trigger rows")


# Global store instance (same pattern as get_session_storage)
_trigger_store: Optional[TriggerStore] = None


def get_trigger_store() -> TriggerStore:
    """Get the global trigger store instance."""
    global _trigger_store
    if _trigger_store is None:
        _trigger_store = TriggerStore()
    return _trigger_store
