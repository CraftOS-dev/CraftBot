# -*- coding: utf-8 -*-
"""
app.usage.session_storage

SQLite-based storage for persistent sessions and their event streams.
Sessions live until the user deletes them, so everything here persists
across agent restarts with no staleness purge.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_core.core.session import Session
from agent_core.core.event_stream.event import EventRecord
from agent_core.core.impl.event_stream.event_stream import EventStream

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class SessionStorage:
    """
    SQLite-based storage for persistent sessions.

    Persists every session (main / chat / living_ui) and its event stream so
    they can be restored after an agent restart.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from app.config import APP_DATA_PATH

            usage_dir = Path(APP_DATA_PATH) / ".usage"
            usage_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(usage_dir / "sessions.db")

        self._db_path = db_path
        self._init_db()
        logger.info(f"[SessionStorage] Initialized at {self._db_path}")

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL DEFAULT 'chat',
                    title TEXT NOT NULL DEFAULT '',
                    session_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS event_streams (
                    stream_id TEXT PRIMARY KEY,
                    head_summary TEXT,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS event_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stream_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    FOREIGN KEY (stream_id) REFERENCES event_streams(stream_id)
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_event_records_stream
                ON event_records(stream_id, position)
            """)

            # Old task-system tables are gone for good.
            cursor.execute("DROP TABLE IF EXISTS active_tasks")
            cursor.execute("DROP TABLE IF EXISTS conversation_history")

            # NOTE: the `triggers` table is owned by app/triggers/store.py
            # (durable trigger store) — do not touch it here.

            conn.commit()

    # ─────────────────────── Session Persistence ────────────────────────────

    def persist_session(self, session: Session) -> None:
        """Upsert a session into the sessions table."""
        now = datetime.now(timezone.utc).isoformat()
        session_json = json.dumps(session.to_dict(), default=str)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO sessions
                    (session_id, type, title, session_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    type = excluded.type,
                    title = excluded.title,
                    session_json = excluded.session_json,
                    updated_at = excluded.updated_at
                """,
                (
                    session.id,
                    session.type,
                    session.title,
                    session_json,
                    session.created_at,
                    now,
                ),
            )
            conn.commit()

    def remove_session(self, session_id: str) -> None:
        """Remove a session and its associated event stream from persistence."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.execute(
                "DELETE FROM event_records WHERE stream_id = ?", (session_id,)
            )
            conn.execute(
                "DELETE FROM event_streams WHERE stream_id = ?", (session_id,)
            )
            conn.commit()

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Look up a single persisted session by id."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT session_json FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            return None

    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Return all persisted sessions."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT session_id, session_json, updated_at FROM sessions"
            )
            rows = cursor.fetchall()

        return [
            {
                "session_id": session_id,
                "session_json": session_json,
                "updated_at": updated_at,
            }
            for session_id, session_json, updated_at in rows
        ]

    # ─────────────────────── Event Stream Persistence ───────────────────────

    def persist_event_stream(self, stream_id: str, stream: EventStream) -> None:
        """Persist an event stream's head_summary and tail_events."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            # Upsert stream metadata
            conn.execute(
                """
                INSERT INTO event_streams (stream_id, head_summary, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(stream_id) DO UPDATE SET
                    head_summary = excluded.head_summary,
                    updated_at = excluded.updated_at
                """,
                (stream_id, stream.head_summary, now),
            )

            # Replace all event records for this stream
            conn.execute("DELETE FROM event_records WHERE stream_id = ?", (stream_id,))

            for position, record in enumerate(stream.tail_events):
                event_json = json.dumps(record.to_dict(), default=str)
                conn.execute(
                    """
                    INSERT INTO event_records (stream_id, event_json, position)
                    VALUES (?, ?, ?)
                    """,
                    (stream_id, event_json, position),
                )

            conn.commit()

    def remove_event_stream(self, stream_id: str) -> None:
        """Remove a persisted event stream and its records."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM event_records WHERE stream_id = ?", (stream_id,))
            conn.execute("DELETE FROM event_streams WHERE stream_id = ?", (stream_id,))
            conn.commit()

    def get_event_stream(
        self, stream_id: str
    ) -> Tuple[Optional[str], List[EventRecord]]:
        """
        Restore an event stream's data.

        Returns:
            Tuple of (head_summary, list of EventRecord objects).
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            # Get head summary
            cursor.execute(
                "SELECT head_summary FROM event_streams WHERE stream_id = ?",
                (stream_id,),
            )
            row = cursor.fetchone()
            head_summary = row[0] if row else None

            # Get event records ordered by position
            cursor.execute(
                """
                SELECT event_json FROM event_records
                WHERE stream_id = ?
                ORDER BY position ASC
                """,
                (stream_id,),
            )
            records = []
            for (event_json,) in cursor.fetchall():
                try:
                    data = json.loads(event_json)
                    records.append(EventRecord.from_dict(data))
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.warning(
                        f"[SessionStorage] Skipping corrupt event record "
                        f"for stream {stream_id}: {e}"
                    )

        return head_summary, records

    # ─────────────────────── Utilities ───────────────────────────────────────

    def clear_all(self) -> None:
        """Wipe all persisted session data."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM event_records")
            conn.execute("DELETE FROM event_streams")
            conn.commit()
        logger.info("[SessionStorage] Cleared all session data")

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sessions")
            session_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM event_streams")
            stream_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM event_records")
            record_count = cursor.fetchone()[0]
            return {
                "db_path": self._db_path,
                "sessions": session_count,
                "event_streams": stream_count,
                "event_records": record_count,
            }


# Global storage instance
_session_storage: Optional[SessionStorage] = None


def get_session_storage() -> SessionStorage:
    """Get the global session storage instance."""
    global _session_storage
    if _session_storage is None:
        _session_storage = SessionStorage()
    return _session_storage
