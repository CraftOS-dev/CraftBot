# -*- coding: utf-8 -*-
"""
app.triggers.activity_log

Activity ledger for irreversible actions.

One row per attempted irreversible side effect, keyed by a deterministic
idempotency key (session + action + content hash of the inputs):

- INTENT  — written BEFORE the side effect runs
- DONE    — written after success, with the stored output + provider ref
- FAILED  — written after a failed run (a retake re-records INTENT)

Lifecycle answers "did this already run?" as a database check instead of
LLM prose-reading:

- fresh key            → record INTENT, execute
- DONE row             → return the stored output, skip the handler
- stale INTENT row     → a previous attempt was interrupted mid-flight; the
  side effect MAY have happened. Refuse once with a warning (the LLM should
  verify or confirm with the user), and mark the row so a deliberate retry
  afterwards is allowed through.
- FAILED row           → retake (re-record INTENT, execute)

Honest limitation (same as Temporal's): if the LLM regenerates the call
with different wording, the content hash differs and the ledger can't link
the attempts — the guard catches the common case (the same step re-executed
with the same inputs after a crash/redelivery), and the stale-INTENT warning
covers the rest. No current provider accepts an idempotency key, so dedup
is enforced at this ledger, with the provider's returned id stored as an
audit ref.

Same file and idioms as the trigger store (sessions.db, WAL, short
per-operation connections).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from agent_core.core.impl.action.idempotency import GuardDecision

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


STATUS_INTENT = "INTENT"
STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"

# Stored outputs larger than this are replaced by a stub (the ledger is for
# dedup + audit, not bulk storage).
MAX_STORED_OUTPUT_BYTES = 50_000

# A DONE row only short-circuits an identical call for this long. The guard
# exists to absorb crash-resume and duplicate-turn re-execution, which happen
# within minutes; an identical call after the window is a deliberate repeat
# ("send the same message again") and must go through. Dedup-forever is why
# the guard was originally disabled (#404).
DONE_DEDUP_WINDOW_SECONDS = 600.0

# Output keys commonly carrying the provider's id for the side effect
# (email message id, chat message ts, post id) — stored for audit.
PROVIDER_REF_KEYS = ("message_id", "messageId", "id", "ts", "post_id", "email_id")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_idem_key(
    action_name: str, input_data: Dict[str, Any], session_id: Optional[str]
) -> str:
    """Deterministic identity of one irreversible side effect.

    Internal keys (``_``-prefixed, injected by the executor) are excluded so
    the hash reflects only the user-visible content of the action.
    """
    content = {k: v for k, v in (input_data or {}).items() if not k.startswith("_")}
    canonical = json.dumps(content, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{session_id or 'conv'}:{action_name}:{digest}"


class ActivityLog:
    """SQLite persistence for the irreversible-action ledger."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from app.config import APP_DATA_PATH

            usage_dir = Path(APP_DATA_PATH) / ".usage"
            usage_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(usage_dir / "sessions.db")

        self._db_path = db_path
        self._init_db()
        logger.info(f"[ActivityLog] Initialized at {self._db_path}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    idem_key TEXT PRIMARY KEY,
                    task_id TEXT,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider_ref TEXT,
                    output_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def get(self, idem_key: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM activity_log WHERE idem_key = ?", (idem_key,)
            ).fetchone()
        return dict(row) if row else None

    def record_intent(self, idem_key: str, action: str, task_id: Optional[str]) -> None:
        """Upsert the row to INTENT (fresh attempt or deliberate retake)."""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO activity_log
                    (idem_key, task_id, action, status, created_at, updated_at)
                VALUES (?, ?, ?, 'INTENT', ?, ?)
                ON CONFLICT(idem_key) DO UPDATE SET
                    status = 'INTENT',
                    provider_ref = NULL,
                    output_json = NULL,
                    updated_at = excluded.updated_at
                """,
                (idem_key, task_id, action, now, now),
            )
            conn.commit()

    def record_outcome(
        self,
        idem_key: str,
        status: str,
        provider_ref: Optional[str],
        output_json: Optional[str],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE activity_log
                SET status = ?, provider_ref = ?, output_json = ?, updated_at = ?
                WHERE idem_key = ?
                """,
                (status, provider_ref, output_json, _now_iso(), idem_key),
            )
            conn.commit()

    def mark_uncertain_surfaced(self, idem_key: str) -> None:
        """A stale INTENT was surfaced to the LLM once — downgrade to FAILED
        so a subsequent deliberate retry is allowed through (retake)."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE activity_log
                SET status = 'FAILED', updated_at = ?
                WHERE idem_key = ? AND status = 'INTENT'
                """,
                (_now_iso(), idem_key),
            )
            conn.commit()

    def gc(
        self,
        intent_ttl_hours: float = 7 * 24,
        done_ttl_hours: float = 30 * 24,
    ) -> int:
        """Boot-time housekeeping for the ledger.

        Stale INTENT rows (an interrupted attempt nobody ever retried) are
        downgraded to FAILED so they stop blocking, then aged out with the
        rest. Settled rows are deleted after the TTL — ledger payloads can
        contain message content, so they must not accumulate forever.
        """
        now = time.time()
        intent_cutoff = datetime.fromtimestamp(
            now - intent_ttl_hours * 3600, tz=timezone.utc
        ).isoformat()
        done_cutoff = datetime.fromtimestamp(
            now - done_ttl_hours * 3600, tz=timezone.utc
        ).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE activity_log SET status = 'FAILED', updated_at = ?
                WHERE status = 'INTENT' AND updated_at < ?
                """,
                (_now_iso(), intent_cutoff),
            )
            cur = conn.execute(
                """
                DELETE FROM activity_log
                WHERE status IN ('DONE', 'FAILED') AND updated_at < ?
                """,
                (done_cutoff,),
            )
            conn.commit()
            if cur.rowcount:
                logger.info(
                    f"[ActivityLog] GC removed {cur.rowcount} settled ledger row(s)"
                )
            return cur.rowcount

    def clear_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM activity_log")
            conn.commit()


class ActivityLogGuard:
    """IdempotencyGuard implementation backed by the activity ledger."""

    def __init__(self, log: ActivityLog):
        self._log = log

    def begin(
        self,
        action_name: str,
        input_data: Dict[str, Any],
        session_id: Optional[str],
    ) -> GuardDecision:
        idem_key = make_idem_key(action_name, input_data, session_id)
        row = self._log.get(idem_key)

        if row is None or row["status"] == STATUS_FAILED:
            # Fresh attempt, or deliberate retake after a failed/uncertain
            # run — record intent BEFORE the side effect.
            self._log.record_intent(idem_key, action_name, session_id)
            return GuardDecision(proceed=True, idem_key=idem_key)

        if row["status"] == STATUS_DONE:
            # Outside the dedup window, an identical call is a deliberate
            # repeat, not a crash-resume duplicate — let it through.
            try:
                done_at = datetime.fromisoformat(row["updated_at"]).timestamp()
            except (ValueError, TypeError):
                done_at = 0.0
            if time.time() - done_at > DONE_DEDUP_WINDOW_SECONDS:
                self._log.record_intent(idem_key, action_name, session_id)
                return GuardDecision(proceed=True, idem_key=idem_key)
            # This exact side effect just completed — return its stored
            # output instead of doing it again.
            try:
                stored = json.loads(row["output_json"]) if row["output_json"] else {}
            except (ValueError, TypeError):
                stored = {}
            stored["_idempotent_replay"] = True
            stored["_idempotent_note"] = (
                f"{action_name} was NOT re-executed: an identical run already "
                f"completed (provider ref: {row['provider_ref'] or 'n/a'}). "
                f"The original output is returned. Do not retry."
            )
            logger.info(f"[ActivityLog] Skipped duplicate {action_name} ({idem_key})")
            return GuardDecision(proceed=False, idem_key=idem_key, stored_output=stored)

        # Stale INTENT: a previous attempt was interrupted between starting
        # the side effect and recording its outcome. Surface once; the next
        # identical attempt (if the LLM/user decides to retry) is allowed.
        self._log.mark_uncertain_surfaced(idem_key)
        note = (
            f"{action_name} was NOT executed. A previous attempt with these "
            f"exact inputs was interrupted before its outcome could be "
            f"recorded — the side effect (e.g. the message or email) MAY "
            f"have already reached the recipient. Verify first (check the "
            f"sent folder / channel history) or confirm with the user. If "
            f"you determine it did not go out, run the action again — it "
            f"will be allowed through."
        )
        logger.warning(
            f"[ActivityLog] Uncertain prior attempt for {action_name} "
            f"({idem_key}) — surfaced to the agent"
        )
        return GuardDecision(proceed=False, idem_key=idem_key, note=note)

    def complete(
        self,
        idem_key: str,
        status: str,
        outputs: Optional[Dict[str, Any]],
    ) -> None:
        ledger_status = STATUS_DONE if status == "success" else STATUS_FAILED

        provider_ref = None
        output_json = None
        if isinstance(outputs, dict):
            for key in PROVIDER_REF_KEYS:
                if outputs.get(key):
                    provider_ref = str(outputs[key])
                    break
            output_json = json.dumps(outputs, default=str)
            if len(output_json) > MAX_STORED_OUTPUT_BYTES:
                output_json = json.dumps(
                    {
                        "status": outputs.get("status", status),
                        "note": "output too large for the activity ledger",
                    }
                )

        self._log.record_outcome(idem_key, ledger_status, provider_ref, output_json)


# Global instance (same pattern as get_session_storage / get_trigger_store)
_activity_log: Optional[ActivityLog] = None


def get_activity_log() -> ActivityLog:
    global _activity_log
    if _activity_log is None:
        _activity_log = ActivityLog()
    return _activity_log
