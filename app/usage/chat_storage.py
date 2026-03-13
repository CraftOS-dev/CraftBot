# -*- coding: utf-8 -*-
"""
app.usage.chat_storage

SQLite-based storage for chat messages.
Provides local persistence for chat history across agent restarts.
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
class StoredChatMessage:
    """A chat message stored in the database."""

    message_id: str
    sender: str
    content: str
    style: str
    timestamp: float
    attachments: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "messageId": self.message_id,
            "sender": self.sender,
            "content": self.content,
            "style": self.style,
            "timestamp": self.timestamp,
        }
        if self.attachments:
            result["attachments"] = self.attachments
        return result


class ChatStorage:
    """
    SQLite-based storage for chat messages.

    Provides local persistence for chat history.
    Messages are stored in a SQLite database in app/data/.usage.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize chat storage.

        Args:
            db_path: Path to the SQLite database file.
                     If None, uses default location in app/data/.usage.
        """
        if db_path is None:
            from app.config import APP_DATA_PATH
            usage_dir = Path(APP_DATA_PATH) / ".usage"
            usage_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(usage_dir / "chat.db")

        self._db_path = db_path
        self._init_db()
        logger.info(f"[ChatStorage] Initialized at {self._db_path}")

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL UNIQUE,
                    sender TEXT NOT NULL,
                    content TEXT NOT NULL,
                    style TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    attachments TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_timestamp
                ON chat_messages(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_message_id
                ON chat_messages(message_id)
            """)

            conn.commit()

    def insert_message(self, message: StoredChatMessage) -> int:
        """
        Insert a single chat message.

        Args:
            message: The StoredChatMessage to insert.

        Returns:
            The row ID of the inserted message.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO chat_messages
                (message_id, sender, content, style, timestamp, attachments)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                message.message_id,
                message.sender,
                message.content,
                message.style,
                message.timestamp,
                json.dumps(message.attachments) if message.attachments else None,
            ))
            conn.commit()
            return cursor.lastrowid

    def get_messages(
        self,
        limit: int = 500,
        offset: int = 0,
    ) -> List[StoredChatMessage]:
        """
        Get chat messages ordered by timestamp.

        Args:
            limit: Maximum number of messages to return.
            offset: Number of messages to skip.

        Returns:
            List of StoredChatMessage objects.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT message_id, sender, content, style, timestamp, attachments
                FROM chat_messages
                ORDER BY timestamp ASC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            rows = cursor.fetchall()

            return [
                StoredChatMessage(
                    message_id=row[0],
                    sender=row[1],
                    content=row[2],
                    style=row[3],
                    timestamp=row[4],
                    attachments=json.loads(row[5]) if row[5] else None,
                )
                for row in rows
            ]

    def get_recent_messages(self, limit: int = 100) -> List[StoredChatMessage]:
        """
        Get most recent messages.

        Args:
            limit: Maximum number of messages to return.

        Returns:
            List of recent messages ordered by timestamp ascending.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            # Get last N messages ordered by timestamp DESC, then reverse
            cursor.execute("""
                SELECT message_id, sender, content, style, timestamp, attachments
                FROM chat_messages
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()

            messages = [
                StoredChatMessage(
                    message_id=row[0],
                    sender=row[1],
                    content=row[2],
                    style=row[3],
                    timestamp=row[4],
                    attachments=json.loads(row[5]) if row[5] else None,
                )
                for row in rows
            ]
            # Reverse to get chronological order
            messages.reverse()
            return messages

    def clear_messages(self) -> int:
        """
        Clear all messages.

        Returns:
            Number of messages deleted.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM chat_messages")
            count = cursor.fetchone()[0]
            cursor.execute("DELETE FROM chat_messages")
            conn.commit()
            return count

    def delete_message(self, message_id: str) -> bool:
        """
        Delete a message by ID.

        Args:
            message_id: The message ID to delete.

        Returns:
            True if message was deleted, False if not found.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM chat_messages WHERE message_id = ?",
                (message_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_message_count(self) -> int:
        """Get total number of messages."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM chat_messages")
            return cursor.fetchone()[0]

    def get_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dictionary with storage info.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM chat_messages")
            total_messages = cursor.fetchone()[0]

            cursor.execute("""
                SELECT MIN(timestamp), MAX(timestamp) FROM chat_messages
            """)
            row = cursor.fetchone()

            return {
                "db_path": self._db_path,
                "total_messages": total_messages,
                "earliest_message": row[0] if row[0] else None,
                "latest_message": row[1] if row[1] else None,
            }


# Global storage instance
_chat_storage: Optional[ChatStorage] = None


def get_chat_storage() -> ChatStorage:
    """Get the global chat storage instance."""
    global _chat_storage
    if _chat_storage is None:
        _chat_storage = ChatStorage()
    return _chat_storage
