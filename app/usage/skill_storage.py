# -*- coding: utf-8 -*-
"""
app.usage.skill_storage

SQLite-based storage for skill invocation events.
Provides local persistence for skill usage history across restarts.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class SkillStorage:
    """
    SQLite-based storage for skill invocation events.

    Provides local persistence for skill usage history.
    Events are stored in a SQLite database in app/data/.usage/skills.db.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from app.config import APP_DATA_PATH

            usage_dir = Path(APP_DATA_PATH) / ".usage"
            usage_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(usage_dir / "skills.db")

        self._db_path = db_path
        self._init_db()
        logger.info(f"[SkillStorage] Initialized at {self._db_path}")

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS skill_invocations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp  TEXT    NOT NULL,
                    skill_name TEXT    NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_skill_timestamp
                ON skill_invocations(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_skill_name
                ON skill_invocations(skill_name)
            """)
            conn.commit()

    def insert_invocation(self, skill_name: str) -> int:
        """
        Record a single skill invocation.

        Args:
            skill_name: Name of the skill that was invoked.

        Returns:
            The row ID of the inserted record.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO skill_invocations (timestamp, skill_name) VALUES (?, ?)",
                (datetime.now().isoformat(), skill_name),
            )
            conn.commit()
            return cursor.lastrowid

    def get_skill_totals(self) -> Dict[str, int]:
        """
        Get all-time invocation counts grouped by skill name.

        Returns:
            Dict mapping skill_name -> total invocation count.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT skill_name, COUNT(*) FROM skill_invocations GROUP BY skill_name
            """)
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_stats(self) -> Dict:
        """Get storage statistics."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM skill_invocations")
            total = cursor.fetchone()[0]
            cursor.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM skill_invocations"
            )
            row = cursor.fetchone()
            return {
                "db_path": self._db_path,
                "total_invocations": total,
                "earliest": row[0] if row[0] else None,
                "latest": row[1] if row[1] else None,
            }

    def clear_invocations(self) -> int:
        """Clear all invocation records. Returns number deleted."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM skill_invocations")
            count = cursor.fetchone()[0]
            cursor.execute("DELETE FROM skill_invocations")
            conn.commit()
            logger.info(f"[SkillStorage] Cleared {count} invocation records")
            return count


# Global storage instance
_skill_storage: Optional[SkillStorage] = None


def get_skill_storage() -> SkillStorage:
    """Get the global skill storage instance."""
    global _skill_storage
    if _skill_storage is None:
        _skill_storage = SkillStorage()
    return _skill_storage
