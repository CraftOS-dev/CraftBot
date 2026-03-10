# -*- coding: utf-8 -*-
"""
app.usage.storage

SQLite-based storage for usage events.
Provides local persistence for LLM/VLM token usage tracking.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


@dataclass
class UsageEvent:
    """A single usage event for an LLM/VLM operation."""

    service_type: str  # "llm_openai", "vlm_anthropic", etc.
    provider: str      # "openai", "anthropic", "gemini", "byteplus"
    model: str         # "gpt-4o", "claude-sonnet-4-20250514", etc.

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    duration_ms: int = 0

    # Optional metadata
    call_type: Optional[str] = None      # "reasoning", "action_selection", etc.
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    # Timestamp (set on creation)
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.metadata is None:
            self.metadata = {}


class UsageStorage:
    """
    SQLite-based storage for usage events.

    Provides local persistence without requiring a server.
    Events are stored in a SQLite database in app/data.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize usage storage.

        Args:
            db_path: Path to the SQLite database file.
                     If None, uses default location in app/data.
        """
        if db_path is None:
            from app.config import APP_DATA_PATH
            usage_dir = Path(APP_DATA_PATH) / ".usage"
            usage_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(usage_dir / "usage.db")

        self._db_path = db_path
        self._init_db()
        logger.info(f"[UsageStorage] Initialized at {self._db_path}")

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    service_type TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cached_tokens INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    call_type TEXT,
                    session_id TEXT,
                    metadata TEXT
                )
            """)

            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_timestamp
                ON usage_events(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_provider
                ON usage_events(provider)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_model
                ON usage_events(model)
            """)

            conn.commit()

    def insert_event(self, event: UsageEvent) -> int:
        """
        Insert a single usage event.

        Args:
            event: The UsageEvent to insert.

        Returns:
            The row ID of the inserted event.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO usage_events
                (timestamp, service_type, provider, model, input_tokens,
                 output_tokens, cached_tokens, duration_ms, call_type,
                 session_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.timestamp.isoformat() if event.timestamp else datetime.utcnow().isoformat(),
                event.service_type,
                event.provider,
                event.model,
                event.input_tokens,
                event.output_tokens,
                event.cached_tokens,
                event.duration_ms,
                event.call_type,
                event.session_id,
                json.dumps(event.metadata) if event.metadata else None,
            ))
            conn.commit()
            return cursor.lastrowid

    def insert_events_batch(self, events: List[UsageEvent]) -> int:
        """
        Insert multiple usage events in a batch.

        Args:
            events: List of UsageEvent objects to insert.

        Returns:
            The number of events inserted.
        """
        if not events:
            return 0

        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            data = [
                (
                    e.timestamp.isoformat() if e.timestamp else datetime.utcnow().isoformat(),
                    e.service_type,
                    e.provider,
                    e.model,
                    e.input_tokens,
                    e.output_tokens,
                    e.cached_tokens,
                    e.duration_ms,
                    e.call_type,
                    e.session_id,
                    json.dumps(e.metadata) if e.metadata else None,
                )
                for e in events
            ]
            cursor.executemany("""
                INSERT INTO usage_events
                (timestamp, service_type, provider, model, input_tokens,
                 output_tokens, cached_tokens, duration_ms, call_type,
                 session_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)
            conn.commit()
            return len(events)

    def get_usage_summary(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get aggregated usage summary.

        Args:
            start_date: Start of the time range (inclusive).
            end_date: End of the time range (inclusive).

        Returns:
            Dictionary with aggregated usage statistics.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            query = """
                SELECT
                    COUNT(*) as total_calls,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens,
                    SUM(cached_tokens) as total_cached_tokens,
                    SUM(input_tokens + output_tokens) as total_tokens,
                    AVG(input_tokens + output_tokens) as avg_tokens_per_call
                FROM usage_events
                WHERE 1=1
            """
            params = []

            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date.isoformat())
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date.isoformat())

            cursor.execute(query, params)
            row = cursor.fetchone()

            return {
                "total_calls": row[0] or 0,
                "total_input_tokens": row[1] or 0,
                "total_output_tokens": row[2] or 0,
                "total_cached_tokens": row[3] or 0,
                "total_tokens": row[4] or 0,
                "avg_tokens_per_call": round(row[5] or 0, 2),
            }

    def get_usage_by_provider(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get usage breakdown by provider.

        Returns:
            List of dictionaries with per-provider statistics.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            query = """
                SELECT
                    provider,
                    COUNT(*) as total_calls,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens,
                    SUM(cached_tokens) as total_cached_tokens
                FROM usage_events
                WHERE 1=1
            """
            params = []

            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date.isoformat())
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date.isoformat())

            query += " GROUP BY provider ORDER BY total_calls DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [
                {
                    "provider": row[0],
                    "total_calls": row[1],
                    "total_input_tokens": row[2] or 0,
                    "total_output_tokens": row[3] or 0,
                    "total_cached_tokens": row[4] or 0,
                }
                for row in rows
            ]

    def get_usage_by_model(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get usage breakdown by model.

        Returns:
            List of dictionaries with per-model statistics.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            query = """
                SELECT
                    model,
                    provider,
                    COUNT(*) as total_calls,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens,
                    SUM(cached_tokens) as total_cached_tokens
                FROM usage_events
                WHERE 1=1
            """
            params = []

            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date.isoformat())
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date.isoformat())

            query += " GROUP BY model, provider ORDER BY total_calls DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [
                {
                    "model": row[0],
                    "provider": row[1],
                    "total_calls": row[2],
                    "total_input_tokens": row[3] or 0,
                    "total_output_tokens": row[4] or 0,
                    "total_cached_tokens": row[5] or 0,
                }
                for row in rows
            ]

    def get_hourly_distribution(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[int]:
        """
        Get hourly distribution of requests for the given period.

        Args:
            start_date: Start of the time range (inclusive).
            end_date: End of the time range (inclusive).

        Returns:
            List of 24 integers representing request counts per hour (0-23).
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            query = """
                SELECT
                    CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                    COUNT(*) as count
                FROM usage_events
                WHERE 1=1
            """
            params = []

            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date.isoformat())
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date.isoformat())

            query += " GROUP BY hour ORDER BY hour"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            # Initialize 24-hour array
            distribution = [0] * 24
            for row in rows:
                hour = row[0]
                count = row[1]
                if 0 <= hour < 24:
                    distribution[hour] = count

            return distribution

    def get_daily_usage(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get daily usage breakdown for the last N days.

        Args:
            days: Number of days to include.

        Returns:
            List of dictionaries with daily statistics.
        """
        start_date = datetime.utcnow() - timedelta(days=days)

        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    DATE(timestamp) as date,
                    COUNT(*) as total_calls,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens,
                    SUM(cached_tokens) as total_cached_tokens
                FROM usage_events
                WHERE timestamp >= ?
                GROUP BY DATE(timestamp)
                ORDER BY date DESC
            """, (start_date.isoformat(),))

            rows = cursor.fetchall()

            return [
                {
                    "date": row[0],
                    "total_calls": row[1],
                    "total_input_tokens": row[2] or 0,
                    "total_output_tokens": row[3] or 0,
                    "total_cached_tokens": row[4] or 0,
                }
                for row in rows
            ]

    def get_recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get most recent usage events.

        Args:
            limit: Maximum number of events to return.

        Returns:
            List of recent usage events as dictionaries.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    id, timestamp, service_type, provider, model,
                    input_tokens, output_tokens, cached_tokens,
                    duration_ms, call_type, session_id, metadata
                FROM usage_events
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))

            rows = cursor.fetchall()

            return [
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "service_type": row[2],
                    "provider": row[3],
                    "model": row[4],
                    "input_tokens": row[5],
                    "output_tokens": row[6],
                    "cached_tokens": row[7],
                    "duration_ms": row[8],
                    "call_type": row[9],
                    "session_id": row[10],
                    "metadata": json.loads(row[11]) if row[11] else {},
                }
                for row in rows
            ]

    def export_to_csv(self, path: str) -> int:
        """
        Export all usage events to a CSV file.

        Args:
            path: Path to the output CSV file.

        Returns:
            Number of events exported.
        """
        import csv

        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    id, timestamp, service_type, provider, model,
                    input_tokens, output_tokens, cached_tokens,
                    duration_ms, call_type, session_id, metadata
                FROM usage_events
                ORDER BY timestamp DESC
            """)

            rows = cursor.fetchall()

            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'id', 'timestamp', 'service_type', 'provider', 'model',
                    'input_tokens', 'output_tokens', 'cached_tokens',
                    'duration_ms', 'call_type', 'session_id', 'metadata'
                ])
                writer.writerows(rows)

            return len(rows)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dictionary with storage info.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM usage_events")
            total_events = cursor.fetchone()[0]

            cursor.execute("""
                SELECT MIN(timestamp), MAX(timestamp) FROM usage_events
            """)
            row = cursor.fetchone()

            return {
                "db_path": self._db_path,
                "total_events": total_events,
                "earliest_event": row[0] if row[0] else None,
                "latest_event": row[1] if row[1] else None,
            }


# Global storage instance
_usage_storage: Optional[UsageStorage] = None


def get_usage_storage() -> UsageStorage:
    """Get the global usage storage instance."""
    global _usage_storage
    if _usage_storage is None:
        _usage_storage = UsageStorage()
    return _usage_storage
