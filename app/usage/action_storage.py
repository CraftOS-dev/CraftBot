# -*- coding: utf-8 -*-
"""
app.usage.action_storage

SQLite-based storage for action panel items (tasks and actions).
Provides local persistence for action history across agent restarts.
"""

from __future__ import annotations

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


@dataclass
class StoredActionItem:
    """An action item stored in the database."""

    id: str
    name: str
    status: str  # "running", "completed", "error", "cancelled", "pending"
    item_type: str  # "task" or "action"
    parent_id: Optional[str] = None
    created_at: float = 0.0
    completed_at: Optional[float] = None
    input_data: Optional[str] = None
    output_data: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def duration(self) -> Optional[int]:
        """Get duration in milliseconds, or None if still running."""
        if self.completed_at is not None and self.created_at:
            return int((self.completed_at - self.created_at) * 1000)
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "itemType": self.item_type,
            "parentId": self.parent_id,
            "createdAt": int(self.created_at * 1000) if self.created_at else 0,
            "duration": self.duration,
            "input": self.input_data,
            "output": self.output_data,
            "error": self.error_message,
        }


class ActionStorage:
    """
    SQLite-based storage for action panel items.

    Provides local persistence for action/task history.
    Items are stored in a SQLite database in app/data/.usage.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize action storage.

        Args:
            db_path: Path to the SQLite database file.
                     If None, uses default location in app/data/.usage.
        """
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
                    parent_id TEXT,
                    created_at REAL NOT NULL,
                    completed_at REAL,
                    input_data TEXT,
                    output_data TEXT,
                    error_message TEXT,
                    db_created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_action_created_at
                ON action_items(created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_action_status
                ON action_items(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_action_item_type
                ON action_items(item_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_action_parent_id
                ON action_items(parent_id)
            """)

            conn.commit()

    def insert_item(self, item: StoredActionItem) -> None:
        """
        Insert or update an action item.

        Args:
            item: The StoredActionItem to insert or update.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO action_items
                (id, name, status, item_type, parent_id, created_at,
                 completed_at, input_data, output_data, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.id,
                item.name,
                item.status,
                item.item_type,
                item.parent_id,
                item.created_at,
                item.completed_at,
                item.input_data,
                item.output_data,
                item.error_message,
            ))
            conn.commit()

    def update_item_status(
        self,
        item_id: str,
        status: str,
        completed_at: Optional[float] = None,
        output_data: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Update an item's status and related fields.

        Args:
            item_id: The item ID to update.
            status: New status value.
            completed_at: Completion timestamp (if applicable).
            output_data: Output data (if any).
            error_message: Error message (if any).

        Returns:
            True if item was updated, False if not found.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            # Build dynamic update query
            updates = ["status = ?"]
            params: List[Any] = [status]

            if completed_at is not None:
                updates.append("completed_at = ?")
                params.append(completed_at)
            if output_data is not None:
                updates.append("output_data = ?")
                params.append(output_data)
            if error_message is not None:
                updates.append("error_message = ?")
                params.append(error_message)

            params.append(item_id)
            query = f"UPDATE action_items SET {', '.join(updates)} WHERE id = ?"

            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount > 0

    def get_items(
        self,
        limit: int = 500,
        include_running: bool = True,
    ) -> List[StoredActionItem]:
        """
        Get action items ordered by created_at.

        Args:
            limit: Maximum number of items to return.
            include_running: Whether to include running items.

        Returns:
            List of StoredActionItem objects.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            query = """
                SELECT id, name, status, item_type, parent_id, created_at,
                       completed_at, input_data, output_data, error_message
                FROM action_items
            """
            if not include_running:
                query += " WHERE status != 'running'"
            query += " ORDER BY created_at ASC LIMIT ?"

            cursor.execute(query, (limit,))
            rows = cursor.fetchall()

            return [
                StoredActionItem(
                    id=row[0],
                    name=row[1],
                    status=row[2],
                    item_type=row[3],
                    parent_id=row[4],
                    created_at=row[5],
                    completed_at=row[6],
                    input_data=row[7],
                    output_data=row[8],
                    error_message=row[9],
                )
                for row in rows
            ]

    def get_recent_items(self, limit: int = 100) -> List[StoredActionItem]:
        """
        Get most recent action items.

        Args:
            limit: Maximum number of items to return.

        Returns:
            List of recent items ordered by created_at ascending.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            # Get last N items ordered by created_at DESC, then reverse
            cursor.execute("""
                SELECT id, name, status, item_type, parent_id, created_at,
                       completed_at, input_data, output_data, error_message
                FROM action_items
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()

            items = [
                StoredActionItem(
                    id=row[0],
                    name=row[1],
                    status=row[2],
                    item_type=row[3],
                    parent_id=row[4],
                    created_at=row[5],
                    completed_at=row[6],
                    input_data=row[7],
                    output_data=row[8],
                    error_message=row[9],
                )
                for row in rows
            ]
            # Reverse to get chronological order
            items.reverse()
            return items

    def get_item(self, item_id: str) -> Optional[StoredActionItem]:
        """
        Get a single item by ID.

        Args:
            item_id: The item ID to retrieve.

        Returns:
            StoredActionItem or None if not found.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, status, item_type, parent_id, created_at,
                       completed_at, input_data, output_data, error_message
                FROM action_items
                WHERE id = ?
            """, (item_id,))
            row = cursor.fetchone()

            if row:
                return StoredActionItem(
                    id=row[0],
                    name=row[1],
                    status=row[2],
                    item_type=row[3],
                    parent_id=row[4],
                    created_at=row[5],
                    completed_at=row[6],
                    input_data=row[7],
                    output_data=row[8],
                    error_message=row[9],
                )
            return None

    def clear_items(self) -> int:
        """
        Clear all items.

        Returns:
            Number of items deleted.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM action_items")
            count = cursor.fetchone()[0]
            cursor.execute("DELETE FROM action_items")
            conn.commit()
            return count

    def clear_terminal_tasks(self) -> List[str]:
        """
        Delete tasks whose status is completed/error/cancelled, plus all
        their child actions. Running/waiting tasks are preserved so the
        user can keep monitoring active work.

        Returns:
            List of removed item IDs (terminal tasks + their child actions).
        """
        terminal_statuses = ("completed", "error", "cancelled")
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            placeholders = ",".join("?" for _ in terminal_statuses)
            cursor.execute(
                f"""
                SELECT id FROM action_items
                WHERE item_type = 'task' AND status IN ({placeholders})
                """,
                terminal_statuses,
            )
            terminal_task_ids = [row[0] for row in cursor.fetchall()]

            if not terminal_task_ids:
                return []

            id_placeholders = ",".join("?" for _ in terminal_task_ids)
            cursor.execute(
                f"""
                SELECT id FROM action_items
                WHERE id IN ({id_placeholders}) OR parent_id IN ({id_placeholders})
                """,
                terminal_task_ids + terminal_task_ids,
            )
            removed_ids = [row[0] for row in cursor.fetchall()]

            cursor.execute(
                f"""
                DELETE FROM action_items
                WHERE id IN ({id_placeholders}) OR parent_id IN ({id_placeholders})
                """,
                terminal_task_ids + terminal_task_ids,
            )
            conn.commit()
            return removed_ids

    def delete_item(self, item_id: str) -> bool:
        """
        Delete an item by ID.

        Args:
            item_id: The item ID to delete.

        Returns:
            True if item was deleted, False if not found.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM action_items WHERE id = ?",
                (item_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def mark_running_as_cancelled(self, exclude: Optional[set] = None) -> int:
        """
        Mark running items as cancelled, optionally excluding some.

        This should be called on startup to clean up stale running items
        from a previous session.

        Args:
            exclude: Set of item IDs to skip (e.g., restored tasks that
                     are still legitimately running).

        Returns:
            Number of items updated.
        """
        import time as time_module
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            if exclude:
                placeholders = ",".join("?" for _ in exclude)
                cursor.execute(f"""
                    UPDATE action_items
                    SET status = 'cancelled', completed_at = ?
                    WHERE status = 'running' AND id NOT IN ({placeholders})
                """, (time_module.time(), *exclude))
            else:
                cursor.execute("""
                    UPDATE action_items
                    SET status = 'cancelled', completed_at = ?
                    WHERE status = 'running'
                """, (time_module.time(),))
            conn.commit()
            return cursor.rowcount

    def get_recent_tasks_with_actions(
        self,
        task_limit: int = 15,
    ) -> List[StoredActionItem]:
        """
        Get the N most recent tasks and all their child actions.

        Args:
            task_limit: Maximum number of tasks to return.

        Returns:
            List of items (tasks + their actions) ordered by created_at ascending.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            # Get recent task IDs
            cursor.execute("""
                SELECT id FROM action_items
                WHERE item_type = 'task'
                ORDER BY created_at DESC
                LIMIT ?
            """, (task_limit,))
            task_ids = [row[0] for row in cursor.fetchall()]

            if not task_ids:
                return []

            # Get those tasks + all their child actions
            placeholders = ','.join('?' * len(task_ids))
            cursor.execute(f"""
                SELECT id, name, status, item_type, parent_id, created_at,
                       completed_at, input_data, output_data, error_message
                FROM action_items
                WHERE id IN ({placeholders}) OR parent_id IN ({placeholders})
                ORDER BY created_at ASC
            """, task_ids + task_ids)
            rows = cursor.fetchall()

            return [
                StoredActionItem(
                    id=row[0],
                    name=row[1],
                    status=row[2],
                    item_type=row[3],
                    parent_id=row[4],
                    created_at=row[5],
                    completed_at=row[6],
                    input_data=row[7],
                    output_data=row[8],
                    error_message=row[9],
                )
                for row in rows
            ]

    def get_tasks_before(
        self,
        before_timestamp: float,
        task_limit: int = 15,
    ) -> List[StoredActionItem]:
        """
        Get tasks (and their actions) older than a given timestamp.

        Args:
            before_timestamp: Unix timestamp upper bound (exclusive), in seconds.
            task_limit: Maximum number of tasks to load.

        Returns:
            List of items (tasks + their actions) ordered by created_at ascending.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            # Get older task IDs
            cursor.execute("""
                SELECT id FROM action_items
                WHERE item_type = 'task' AND created_at < ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (before_timestamp, task_limit))
            task_ids = [row[0] for row in cursor.fetchall()]

            if not task_ids:
                return []

            placeholders = ','.join('?' * len(task_ids))
            cursor.execute(f"""
                SELECT id, name, status, item_type, parent_id, created_at,
                       completed_at, input_data, output_data, error_message
                FROM action_items
                WHERE id IN ({placeholders}) OR parent_id IN ({placeholders})
                ORDER BY created_at ASC
            """, task_ids + task_ids)
            rows = cursor.fetchall()

            return [
                StoredActionItem(
                    id=row[0],
                    name=row[1],
                    status=row[2],
                    item_type=row[3],
                    parent_id=row[4],
                    created_at=row[5],
                    completed_at=row[6],
                    input_data=row[7],
                    output_data=row[8],
                    error_message=row[9],
                )
                for row in rows
            ]

    def get_task_count(self) -> int:
        """Get total number of tasks (not actions)."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM action_items WHERE item_type = 'task'")
            return cursor.fetchone()[0]

    def get_item_count(self) -> int:
        """Get total number of items."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM action_items")
            return cursor.fetchone()[0]

    def get_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dictionary with storage info.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM action_items")
            total_items = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM action_items WHERE item_type = 'task'
            """)
            total_tasks = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM action_items WHERE item_type = 'action'
            """)
            total_actions = cursor.fetchone()[0]

            cursor.execute("""
                SELECT MIN(created_at), MAX(created_at) FROM action_items
            """)
            row = cursor.fetchone()

            return {
                "db_path": self._db_path,
                "total_items": total_items,
                "total_tasks": total_tasks,
                "total_actions": total_actions,
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
