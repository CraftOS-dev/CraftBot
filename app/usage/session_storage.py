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
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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

    Persists every session (main / chat / agent_app) and its event stream so
    they can be restored after an agent restart.

    Every write runs on one writer thread, in call order. The ``*_later``
    methods are for live persists from the event loop: they snapshot the data
    on the caller and return at once (a SQLite write and commit can stall for
    seconds, and on the loop that froze every session and the UI). The other
    write methods wait for their write, and so for every write queued before
    it.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from app.config import APP_DATA_PATH

            usage_dir = Path(APP_DATA_PATH) / ".usage"
            usage_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(usage_dir / "sessions.db")

        self._db_path = db_path
        self._writer = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="session-db"
        )
        self._init_db()
        logger.info(f"[SessionStorage] Initialized at {self._db_path}")

    def _submit(self, write: Callable[..., None], *args: Any) -> "Future[None]":
        return self._writer.submit(write, *args)

    def _submit_later(self, what: str, write: Callable[..., None], *args: Any) -> None:
        def run() -> None:
            try:
                write(*args)
            except Exception as e:
                logger.warning(f"[SessionStorage] Failed to persist {what}: {e}")

        self._writer.submit(run)

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

            # A session's LLM state per call type (LLMInterface.export_session):
            # restored at boot so a restart continues the session on the
            # provider's cached prefix instead of starting a new one.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS llm_sessions (
                    session_id TEXT NOT NULL,
                    call_type TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, call_type)
                )
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
        self._submit(self._write_session, self._session_row(session)).result()

    def persist_session_later(self, session: Session) -> None:
        """persist_session without waiting for the write."""
        self._submit_later(
            f"session {session.id}", self._write_session, self._session_row(session)
        )

    @staticmethod
    def _session_row(session: Session) -> Tuple[Any, ...]:
        now = datetime.now(timezone.utc).isoformat()
        session_json = json.dumps(session.to_dict(), default=str)
        return (
            session.id,
            session.type,
            session.title,
            session_json,
            session.created_at,
            now,
        )

    def _write_session(self, row: Tuple[Any, ...]) -> None:
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
                row,
            )
            conn.commit()

    def remove_session(self, session_id: str) -> None:
        """Remove a session and its associated event stream from persistence."""
        self._submit(self._delete_session, session_id).result()

    def remove_session_later(self, session_id: str) -> None:
        """remove_session without waiting for the write. Queued after every
        earlier persist, so none of them can bring the session back."""
        self._submit_later(f"removal of {session_id}", self._delete_session, session_id)

    def _delete_session(self, session_id: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM event_records WHERE stream_id = ?", (session_id,))
            conn.execute("DELETE FROM event_streams WHERE stream_id = ?", (session_id,))
            conn.execute("DELETE FROM llm_sessions WHERE session_id = ?", (session_id,))
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
            cursor.execute("SELECT session_id, session_json, updated_at FROM sessions")
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
        """Persist an event stream's head_summary and tail_events.

        Called during live operation (run end, session persist hook), not
        just at shutdown, so other threads may be appending events or
        summarizing while this runs. Snapshot the tail BEFORE reading the
        head: summarization writes head_summary first and swaps the tail
        second, so this order can at worst capture a folded chunk twice in
        one snapshot (corrected by the next persist) — never lose it.
        """
        self._submit(
            self._write_event_stream, stream_id, *self._stream_snapshot(stream)
        ).result()

    def persist_event_stream_later(self, stream_id: str, stream: EventStream) -> None:
        """persist_event_stream without waiting for the write: the stream is
        snapshotted now, the snapshot written on the writer thread."""
        self._submit_later(
            f"event stream {stream_id}",
            self._write_event_stream,
            stream_id,
            *self._stream_snapshot(stream),
        )

    @staticmethod
    def _stream_snapshot(stream: EventStream) -> Tuple[Optional[str], List[str]]:
        """(head_summary, encoded tail records). Tail first: see
        persist_event_stream."""
        records = list(stream.tail_events)
        head_summary = stream.head_summary
        return head_summary, [
            json.dumps(record.to_dict(), default=str) for record in records
        ]

    def _write_event_stream(
        self, stream_id: str, head_summary: Optional[str], event_jsons: List[str]
    ) -> None:
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
                (stream_id, head_summary, now),
            )

            # Replace all event records for this stream
            conn.execute("DELETE FROM event_records WHERE stream_id = ?", (stream_id,))

            for position, event_json in enumerate(event_jsons):
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
        self._submit(self._delete_event_stream, stream_id).result()

    def _delete_event_stream(self, stream_id: str) -> None:
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

    # ─────────────────────── LLM Session Persistence ────────────────────────

    def persist_llm_session(
        self, session_id: str, state: Dict[str, Dict[str, Any]]
    ) -> None:
        """Replace a session's saved LLM state with ``state`` (call type ->
        LLMInterface.export_session entry). An empty state removes it."""
        self._submit(
            self._write_llm_session, session_id, self._llm_rows(session_id, state)
        ).result()

    def persist_llm_session_later(
        self, session_id: str, state: Dict[str, Dict[str, Any]]
    ) -> None:
        """persist_llm_session without waiting for the write."""
        self._submit_later(
            f"LLM state of {session_id}",
            self._write_llm_session,
            session_id,
            self._llm_rows(session_id, state),
        )

    @staticmethod
    def _llm_rows(
        session_id: str, state: Dict[str, Dict[str, Any]]
    ) -> List[Tuple[str, str, str, str]]:
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for call_type, entry in state.items():
            try:
                rows.append((session_id, call_type, json.dumps(entry), now))
            except (TypeError, ValueError) as e:
                # A history that is not plain JSON cannot be restored as sent;
                # the session then starts a new prefix after a restart.
                logger.warning(
                    f"[SessionStorage] LLM state for {session_id}:{call_type} "
                    f"is not serializable, not saved: {e}"
                )
        return rows

    def _write_llm_session(
        self, session_id: str, rows: List[Tuple[str, str, str, str]]
    ) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM llm_sessions WHERE session_id = ?", (session_id,))
            conn.executemany(
                """
                INSERT INTO llm_sessions (session_id, call_type, state_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

    def get_llm_session(self, session_id: str) -> Dict[str, Dict[str, Any]]:
        """A session's saved LLM state (call type -> entry)."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT call_type, state_json FROM llm_sessions WHERE session_id = ?",
                (session_id,),
            )
            rows = cursor.fetchall()
        state: Dict[str, Dict[str, Any]] = {}
        for call_type, state_json in rows:
            try:
                state[call_type] = json.loads(state_json)
            except (ValueError, TypeError):
                logger.warning(
                    f"[SessionStorage] Skipping corrupt LLM state for "
                    f"{session_id}:{call_type}"
                )
        return state

    # ─────────────────────── Utilities ───────────────────────────────────────

    def clear_all(self) -> None:
        """Wipe all persisted session data."""
        self._submit(self._delete_all).result()
        logger.info("[SessionStorage] Cleared all session data")

    def _delete_all(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM sessions")
            conn.execute("DELETE FROM event_records")
            conn.execute("DELETE FROM event_streams")
            conn.execute("DELETE FROM llm_sessions")
            conn.commit()

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
