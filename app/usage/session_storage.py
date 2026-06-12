# -*- coding: utf-8 -*-
"""
app.usage.session_storage

SQLite-based storage for active session state (tasks + event streams).
Provides persistence across agent restarts so that running tasks and their
event context can be restored.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_core.core.task import Task
from agent_core.core.event_stream.event import Event, EventRecord
from agent_core.core.impl.event_stream.event_stream import EventStream

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# Sentinel stream ID for the main (non-task) event stream
MAIN_STREAM_ID = "__main__"

# Tasks older than this (in hours) are considered stale and not restored
STALE_TASK_HOURS = 24


class SessionStorage:
    """
    SQLite-based storage for active session state.

    Persists running tasks and their event streams so they can be restored
    after an agent restart. Completed/cancelled tasks are removed from this
    store (they live in task_storage.py for analytics).
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
                CREATE TABLE IF NOT EXISTS active_tasks (
                    task_id TEXT PRIMARY KEY,
                    task_json TEXT NOT NULL,
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

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_json TEXT NOT NULL,
                    position INTEGER NOT NULL
                )
            """)

            # NOTE: the `triggers` table is owned by app/triggers/store.py
            # (durable trigger store) — do not touch it here.

            conn.commit()

    # ─────────────────────── Task Persistence ───────────────────────────────

    def persist_task(self, task: Task) -> None:
        """Upsert a task into the active_tasks table."""
        now = datetime.now(timezone.utc).isoformat()
        task_json = json.dumps(task.to_dict(), default=str)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO active_tasks (task_id, task_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    task_json = excluded.task_json,
                    updated_at = excluded.updated_at
                """,
                (task.id, task_json, now),
            )
            conn.commit()

    def remove_task(self, task_id: str) -> None:
        """Remove a task and its associated event stream from persistence."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM active_tasks WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM event_records WHERE stream_id = ?", (task_id,))
            conn.execute("DELETE FROM event_streams WHERE stream_id = ?", (task_id,))
            conn.commit()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Look up a single persisted task by id, regardless of status.

        Returns the task's parsed JSON dict or None. Unlike
        ``get_all_active_tasks`` this does not skip terminal tasks — the
        Continue Task flow needs to read them back.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT task_json FROM active_tasks WHERE task_id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            return None

    def get_all_active_tasks(self) -> List[Dict[str, Any]]:
        """Return all active tasks, filtering out terminal/stale ones.

        Terminal-status tasks (completed/error/cancelled) live in the same
        table so the Continue Task flow can read them back by id, but they
        must NOT be auto-restored on startup — that would re-insert an
        already-ended task into ``task_manager.tasks`` as if running.
        """
        terminal_statuses = {"completed", "error", "cancelled"}
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT task_id, task_json, updated_at FROM active_tasks")
            rows = cursor.fetchall()

        now = datetime.now(timezone.utc)
        results = []
        stale_ids = []

        for task_id, task_json, updated_at in rows:
            try:
                updated = datetime.fromisoformat(updated_at)
                # Make timezone-aware if naive
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                age_hours = (now - updated).total_seconds() / 3600
                if age_hours > STALE_TASK_HOURS:
                    stale_ids.append(task_id)
                    logger.info(
                        f"[SessionStorage] Skipping stale task {task_id} "
                        f"(last updated {age_hours:.1f}h ago)"
                    )
                    continue
            except (ValueError, TypeError):
                pass  # If we can't parse the timestamp, include the task

            # Skip terminal tasks: kept on disk for resume, not auto-restored.
            try:
                task_status = json.loads(task_json).get("status")
                if task_status in terminal_statuses:
                    continue
            except (ValueError, TypeError):
                pass

            results.append(
                {
                    "task_id": task_id,
                    "task_json": task_json,
                    "updated_at": updated_at,
                }
            )

        # Clean up stale tasks
        if stale_ids:
            with sqlite3.connect(self._db_path) as conn:
                for tid in stale_ids:
                    conn.execute("DELETE FROM active_tasks WHERE task_id = ?", (tid,))
                    conn.execute(
                        "DELETE FROM event_records WHERE stream_id = ?", (tid,)
                    )
                    conn.execute(
                        "DELETE FROM event_streams WHERE stream_id = ?", (tid,)
                    )
                conn.commit()
            logger.info(f"[SessionStorage] Cleaned up {len(stale_ids)} stale tasks")

        return results

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

    def persist_main_stream(self, stream: EventStream) -> None:
        """Shorthand for persisting the main (non-task) event stream."""
        self.persist_event_stream(MAIN_STREAM_ID, stream)

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

    # ─────────────────────── Conversation History ───────────────────────────

    def persist_conversation_history(self, messages: List[Event]) -> None:
        """Replace persisted conversation history with the current list."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM conversation_history")
            for position, event in enumerate(messages):
                event_json = json.dumps(event.to_dict(), default=str)
                conn.execute(
                    """
                    INSERT INTO conversation_history (event_json, position)
                    VALUES (?, ?)
                    """,
                    (event_json, position),
                )
            conn.commit()

    def get_conversation_history(self) -> List[Event]:
        """Restore conversation history."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT event_json FROM conversation_history ORDER BY position ASC"
            )
            events = []
            for (event_json,) in cursor.fetchall():
                try:
                    data = json.loads(event_json)
                    events.append(Event.from_dict(data))
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.warning(
                        f"[SessionStorage] Skipping corrupt conversation event: {e}"
                    )
            return events

    # ─────────────────────── Trigger Persistence ──────────────────────────────

    # ─────────────────────── Utilities ───────────────────────────────────────

    def clear_all(self) -> None:
        """Wipe all persisted session data."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM active_tasks")
            conn.execute("DELETE FROM event_records")
            conn.execute("DELETE FROM event_streams")
            conn.execute("DELETE FROM conversation_history")
            conn.commit()
        logger.info("[SessionStorage] Cleared all session data")

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM active_tasks")
            task_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM event_streams")
            stream_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM event_records")
            record_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM conversation_history")
            conv_count = cursor.fetchone()[0]
            return {
                "db_path": self._db_path,
                "active_tasks": task_count,
                "event_streams": stream_count,
                "event_records": record_count,
                "conversation_messages": conv_count,
            }


# Global storage instance
_session_storage: Optional[SessionStorage] = None


def get_session_storage() -> SessionStorage:
    """Get the global session storage instance."""
    global _session_storage
    if _session_storage is None:
        _session_storage = SessionStorage()
    return _session_storage
