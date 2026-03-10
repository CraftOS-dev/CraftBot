# -*- coding: utf-8 -*-
"""
app.usage.task_storage

SQLite-based storage for task events.
Provides local persistence for task execution history.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


@dataclass
class TaskEvent:
    """A single task execution event."""

    task_id: str
    task_name: str
    status: str  # "completed", "error", "cancelled"

    start_time: datetime
    end_time: datetime
    duration_ms: int = 0

    total_cost: float = 0.0
    llm_call_count: int = 0

    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        # Calculate duration if not set
        if self.duration_ms == 0 and self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            self.duration_ms = int(delta.total_seconds() * 1000)


class TaskStorage:
    """
    SQLite-based storage for task events.

    Provides local persistence for task execution history.
    Events are stored in a SQLite database in app/data.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize task storage.

        Args:
            db_path: Path to the SQLite database file.
                     If None, uses default location in app/data.
        """
        if db_path is None:
            from app.config import APP_DATA_PATH
            usage_dir = Path(APP_DATA_PATH) / ".usage"
            usage_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(usage_dir / "tasks.db")

        self._db_path = db_path
        self._init_db()
        logger.info(f"[TaskStorage] Initialized at {self._db_path}")

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    task_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    total_cost REAL NOT NULL DEFAULT 0.0,
                    llm_call_count INTEGER NOT NULL DEFAULT 0,
                    session_id TEXT,
                    metadata TEXT
                )
            """)

            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_end_time
                ON task_events(end_time)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_status
                ON task_events(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_task_id
                ON task_events(task_id)
            """)

            conn.commit()

    def insert_task(self, task: TaskEvent) -> int:
        """
        Insert a single task event.

        Args:
            task: The TaskEvent to insert.

        Returns:
            The row ID of the inserted task.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO task_events
                (task_id, task_name, status, start_time, end_time,
                 duration_ms, total_cost, llm_call_count, session_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id,
                task.task_name,
                task.status,
                task.start_time.isoformat() if isinstance(task.start_time, datetime) else task.start_time,
                task.end_time.isoformat() if isinstance(task.end_time, datetime) else task.end_time,
                task.duration_ms,
                task.total_cost,
                task.llm_call_count,
                task.session_id,
                json.dumps(task.metadata) if task.metadata else None,
            ))
            conn.commit()
            return cursor.lastrowid

    def get_task_summary(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get aggregated task summary.

        Args:
            start_date: Start of the time range (inclusive).
            end_date: End of the time range (inclusive).

        Returns:
            Dictionary with aggregated task statistics.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            query = """
                SELECT
                    COUNT(*) as total_tasks,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_tasks,
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as failed_tasks,
                    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled_tasks,
                    SUM(total_cost) as total_cost,
                    AVG(duration_ms) as avg_duration_ms,
                    SUM(llm_call_count) as total_llm_calls
                FROM task_events
                WHERE 1=1
            """
            params = []

            if start_date:
                query += " AND end_time >= ?"
                params.append(start_date.isoformat())
            if end_date:
                query += " AND end_time <= ?"
                params.append(end_date.isoformat())

            cursor.execute(query, params)
            row = cursor.fetchone()

            total = row[0] or 0
            completed = row[1] or 0
            failed = row[2] or 0

            # Calculate success rate
            finished = completed + failed
            success_rate = (completed / finished * 100) if finished > 0 else 100.0

            return {
                "total_tasks": total,
                "completed_tasks": completed,
                "failed_tasks": failed,
                "cancelled_tasks": row[3] or 0,
                "success_rate": round(success_rate, 1),
                "total_cost": round(row[4] or 0, 4),
                "avg_duration_ms": round(row[5] or 0, 2),
                "total_llm_calls": row[6] or 0,
            }

    def get_recent_tasks(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get most recent task events.

        Args:
            limit: Maximum number of tasks to return.

        Returns:
            List of recent task events as dictionaries.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    id, task_id, task_name, status, start_time, end_time,
                    duration_ms, total_cost, llm_call_count, session_id, metadata
                FROM task_events
                ORDER BY end_time DESC
                LIMIT ?
            """, (limit,))

            rows = cursor.fetchall()

            return [
                {
                    "id": row[0],
                    "task_id": row[1],
                    "task_name": row[2],
                    "status": row[3],
                    "start_time": row[4],
                    "end_time": row[5],
                    "duration_ms": row[6],
                    "total_cost": row[7],
                    "llm_call_count": row[8],
                    "session_id": row[9],
                    "metadata": json.loads(row[10]) if row[10] else {},
                }
                for row in rows
            ]

    def get_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dictionary with storage info.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM task_events")
            total_tasks = cursor.fetchone()[0]

            cursor.execute("""
                SELECT MIN(end_time), MAX(end_time) FROM task_events
            """)
            row = cursor.fetchone()

            return {
                "db_path": self._db_path,
                "total_tasks": total_tasks,
                "earliest_task": row[0] if row[0] else None,
                "latest_task": row[1] if row[1] else None,
            }


# Global storage instance
_task_storage: Optional[TaskStorage] = None


def get_task_storage() -> TaskStorage:
    """Get the global task storage instance."""
    global _task_storage
    if _task_storage is None:
        _task_storage = TaskStorage()
    return _task_storage
