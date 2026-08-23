# -*- coding: utf-8 -*-
"""
app.usage.action_storage

SQLite-based storage for the per-session activity feed (action and
reasoning items rendered inline in each session's chat).

Write-through, like chat_storage: the browser action panel persists every
item as it happens, so the feed survives restarts and crashes. The
session's event stream stays what it is — LLM context — and is free to
summarize/prune without affecting the UI's history.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


_ROW_COLUMNS = (
    "id, name, status, item_type, session_id, created_at, "
    "completed_at, input_json, output_json, error_message"
)


def _encode(value: Any) -> Optional[str]:
    """JSON-encode an item's input/output payload (None passes through)."""
    if value is None:
        return None
    return json.dumps(value, default=str)


def _decode(value: Optional[str]) -> Any:
    """Decode a JSON payload column (None passes through)."""
    if value is None:
        return None
    return json.loads(value)


@dataclass
class StoredActionItem:
    """An activity feed item stored in the database."""

    id: str
    name: str
    status: str  # "running", "completed", "error"
    item_type: str  # "action" or "reasoning"
    session_id: str
    created_at: float
    completed_at: Optional[float] = None
    input_data: Any = None
    output_data: Any = None
    error_message: Optional[str] = None


def _row_to_item(row) -> StoredActionItem:
    return StoredActionItem(
        id=row[0],
        name=row[1],
        status=row[2],
        item_type=row[3],
        session_id=row[4],
        created_at=row[5],
        completed_at=row[6],
        input_data=_decode(row[7]),
        output_data=_decode(row[8]),
        error_message=row[9],
    )


class ActionStorage:
    """
    SQLite-based storage for activity feed items.

    Every item belongs to a session; reads are grouped per session.
    Items are stored in a SQLite database in app/data/.usage.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from app.config import APP_DATA_PATH

            usage_dir = Path(APP_DATA_PATH) / ".usage"
            usage_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(usage_dir / "actions.db")

        self._db_path = db_path
        self._init_db()
        logger.info(f"[ActionStorage] Initialized at {self._db_path}")

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS action_items (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    completed_at REAL,
                    input_json TEXT,
                    output_json TEXT,
                    error_message TEXT,
                    db_created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_action_session_created
                ON action_items(session_id, created_at)
            """)

            conn.commit()

    def save_item(self, item: StoredActionItem) -> None:
        """Upsert an activity item (full row — used for insert and update)."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO action_items
                (id, name, status, item_type, session_id, created_at,
                 completed_at, input_json, output_json, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.name,
                    item.status,
                    item.item_type,
                    item.session_id,
                    item.created_at,
                    item.completed_at,
                    _encode(item.input_data),
                    _encode(item.output_data),
                    item.error_message,
                ),
            )
            conn.commit()

    def get_recent_items_by_session(
        self, limit_per_session: int = 100
    ) -> List[StoredActionItem]:
        """
        Get each session's most recent items, all together in chronological
        order. Bounds the boot-time feed without a global cutoff that would
        starve older sessions.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT {_ROW_COLUMNS} FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY session_id ORDER BY created_at DESC
                    ) AS recency_rank
                    FROM action_items
                )
                WHERE recency_rank <= ?
                ORDER BY created_at ASC
                """,
                (limit_per_session,),
            )
            items: List[StoredActionItem] = []
            for row in cursor.fetchall():
                try:
                    items.append(_row_to_item(row))
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(
                        f"[ActionStorage] Skipping corrupt activity row {row[0]}: {e}"
                    )
            return items

    def mark_running_interrupted(self) -> int:
        """
        Close out items left 'running' by a previous process. Called once at
        startup, before the feed is loaded: anything still running at that
        point died with the process that started it.

        Returns:
            Number of items updated.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE action_items
                SET status = 'error',
                    error_message = 'Interrupted by restart',
                    completed_at = created_at
                WHERE status = 'running'
                """
            )
            conn.commit()
            return cursor.rowcount

    def clear_items(self, session_id: Optional[str] = None) -> int:
        """
        Clear items — one session's, or all when session_id is None.

        Returns:
            Number of items deleted.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute(
                    "SELECT COUNT(*) FROM action_items WHERE session_id = ?",
                    (session_id,),
                )
                count = cursor.fetchone()[0]
                cursor.execute(
                    "DELETE FROM action_items WHERE session_id = ?", (session_id,)
                )
            else:
                cursor.execute("SELECT COUNT(*) FROM action_items")
                count = cursor.fetchone()[0]
                cursor.execute("DELETE FROM action_items")
            conn.commit()
            return count

    def delete_item(self, item_id: str) -> bool:
        """
        Delete an item by ID.

        Returns:
            True if the item was deleted, False if not found.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM action_items WHERE id = ?", (item_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_item_count(self, session_id: Optional[str] = None) -> int:
        """Get total number of items (optionally for one session)."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute(
                    "SELECT COUNT(*) FROM action_items WHERE session_id = ?",
                    (session_id,),
                )
            else:
                cursor.execute("SELECT COUNT(*) FROM action_items")
            return cursor.fetchone()[0]

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM action_items")
            total_items = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT session_id) FROM action_items")
            total_sessions = cursor.fetchone()[0]

            cursor.execute("SELECT MIN(created_at), MAX(created_at) FROM action_items")
            row = cursor.fetchone()

            return {
                "db_path": self._db_path,
                "total_items": total_items,
                "total_sessions": total_sessions,
                "earliest_item": row[0] if row[0] else None,
                "latest_item": row[1] if row[1] else None,
            }


# Global storage instance
_action_storage: Optional[ActionStorage] = None


def get_action_storage() -> ActionStorage:
    """Get the global action storage instance."""
    global _action_storage
    if _action_storage is None:
        _action_storage = ActionStorage()
    return _action_storage
