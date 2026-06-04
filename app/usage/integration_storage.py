# -*- coding: utf-8 -*-
"""
app.usage.integration_storage

SQLite-based storage for integration call events.
Provides local persistence for integration usage history across restarts.
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


class IntegrationStorage:
    """
    SQLite-based storage for integration call events.

    Provides local persistence for integration usage history.
    Events are stored in a SQLite database in app/data/.usage/integrations.db.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from app.config import APP_DATA_PATH

            usage_dir = Path(APP_DATA_PATH) / ".usage"
            usage_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(usage_dir / "integrations.db")

        self._db_path = db_path
        self._init_db()
        logger.info(f"[IntegrationStorage] Initialized at {self._db_path}")

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS integration_calls (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp        TEXT    NOT NULL,
                    integration_name TEXT    NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_integration_timestamp
                ON integration_calls(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_integration_name
                ON integration_calls(integration_name)
            """)
            conn.commit()

    def insert_call(self, integration_name: str) -> int:
        """
        Record a single integration call.

        Args:
            integration_name: Name of the integration that was called.

        Returns:
            The row ID of the inserted record.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO integration_calls (timestamp, integration_name) VALUES (?, ?)",
                (datetime.now().isoformat(), integration_name),
            )
            conn.commit()
            return cursor.lastrowid

    def get_integration_totals(self) -> Dict[str, int]:
        """
        Get all-time call counts grouped by integration name.

        Returns:
            Dict mapping integration_name -> total call count.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT integration_name, COUNT(*) FROM integration_calls GROUP BY integration_name
            """)
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_stats(self) -> Dict:
        """Get storage statistics."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM integration_calls")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM integration_calls")
            row = cursor.fetchone()
            return {
                "db_path": self._db_path,
                "total_calls": total,
                "earliest": row[0] if row[0] else None,
                "latest": row[1] if row[1] else None,
            }

    def clear_calls(self) -> int:
        """Clear all call records. Returns number deleted."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM integration_calls")
            count = cursor.fetchone()[0]
            cursor.execute("DELETE FROM integration_calls")
            conn.commit()
            logger.info(f"[IntegrationStorage] Cleared {count} call records")
            return count


# Global storage instance
_integration_storage: Optional[IntegrationStorage] = None


def get_integration_storage() -> IntegrationStorage:
    """Get the global integration storage instance."""
    global _integration_storage
    if _integration_storage is None:
        _integration_storage = IntegrationStorage()
    return _integration_storage
