# -*- coding: utf-8 -*-
"""
app.usage.chat_storage

SQLite-based storage for chat messages, keyed by session.
Provides local persistence for every session's chat history across restarts.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.core.session import MAIN_SESSION_ID

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


_ROW_COLUMNS = (
    "message_id, sender, content, style, timestamp, attachments, "
    "session_id, options, option_selected, continue_work, details"
)


@dataclass
class StoredChatMessage:
    """A chat message stored in the database."""

    message_id: str
    sender: str
    content: str
    style: str
    timestamp: float
    attachments: Optional[List[Dict[str, Any]]] = None
    session_id: str = MAIN_SESSION_ID
    options: Optional[List[Dict[str, Any]]] = None
    option_selected: Optional[str] = None
    # Mid-run agent progress update (send_message continue_work=true) — the
    # run kept going after this bubble. Persisted so a reload/reconnect
    # doesn't misread the bubble as a run-ending reply.
    continue_work: bool = False
    # Expandable payload behind a disclosure (e.g. the raw body of an
    # incoming integration message on the "📩 Incoming …" system stub).
    details: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "messageId": self.message_id,
            "sender": self.sender,
            "content": self.content,
            "style": self.style,
            "timestamp": self.timestamp,
            "sessionId": self.session_id,
        }
        if self.attachments:
            result["attachments"] = self.attachments
        if self.options:
            result["options"] = self.options
        if self.option_selected:
            result["optionSelected"] = self.option_selected
        if self.continue_work:
            result["continueWork"] = True
        if self.details:
            result["details"] = self.details
        return result


def _row_to_message(row) -> StoredChatMessage:
    return StoredChatMessage(
        message_id=row[0],
        sender=row[1],
        content=row[2],
        style=row[3],
        timestamp=row[4],
        attachments=json.loads(row[5]) if row[5] else None,
        session_id=row[6] or MAIN_SESSION_ID,
        options=json.loads(row[7]) if row[7] else None,
        option_selected=row[8],
        continue_work=bool(row[9]),
        details=row[10],
    )


class ChatStorage:
    """
    SQLite-based storage for chat messages.

    Every message belongs to a session; reads are session-scoped.
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
                    session_id TEXT NOT NULL DEFAULT 'main',
                    options TEXT,
                    option_selected TEXT,
                    continue_work INTEGER NOT NULL DEFAULT 0,
                    details TEXT,
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

            # Migration from the pre-session schema: rename task_session_id →
            # session_id and map untagged rows to the main session.
            cursor.execute("PRAGMA table_info(chat_messages)")
            columns = [col[1] for col in cursor.fetchall()]
            if "session_id" not in columns:
                cursor.execute(
                    "ALTER TABLE chat_messages ADD COLUMN session_id TEXT NOT NULL DEFAULT 'main'"
                )
                if "task_session_id" in columns:
                    cursor.execute(
                        "UPDATE chat_messages SET session_id = COALESCE(task_session_id, 'main')"
                    )
                logger.info("[ChatStorage] Migrated: added session_id column")
            if "options" not in columns:
                cursor.execute("ALTER TABLE chat_messages ADD COLUMN options TEXT")
            if "option_selected" not in columns:
                cursor.execute(
                    "ALTER TABLE chat_messages ADD COLUMN option_selected TEXT"
                )
            if "continue_work" not in columns:
                cursor.execute(
                    "ALTER TABLE chat_messages ADD COLUMN continue_work "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            if "details" not in columns:
                cursor.execute("ALTER TABLE chat_messages ADD COLUMN details TEXT")

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_session
                ON chat_messages(session_id, timestamp)
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
            cursor.execute(
                """
                INSERT OR REPLACE INTO chat_messages
                (message_id, sender, content, style, timestamp, attachments, session_id, options, option_selected, continue_work, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    message.message_id,
                    message.sender,
                    message.content,
                    message.style,
                    message.timestamp,
                    json.dumps(message.attachments) if message.attachments else None,
                    message.session_id or MAIN_SESSION_ID,
                    json.dumps(message.options) if message.options else None,
                    message.option_selected,
                    1 if message.continue_work else 0,
                    message.details,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_messages(
        self,
        session_id: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[StoredChatMessage]:
        """
        Get chat messages ordered by timestamp.

        Args:
            session_id: Restrict to one session (None = all sessions).
            limit: Maximum number of messages to return.
            offset: Number of messages to skip.

        Returns:
            List of StoredChatMessage objects.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute(
                    f"""
                    SELECT {_ROW_COLUMNS}
                    FROM chat_messages
                    WHERE session_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ? OFFSET ?
                """,
                    (session_id, limit, offset),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT {_ROW_COLUMNS}
                    FROM chat_messages
                    ORDER BY timestamp ASC
                    LIMIT ? OFFSET ?
                """,
                    (limit, offset),
                )
            return [_row_to_message(row) for row in cursor.fetchall()]

    def get_recent_messages(
        self, session_id: Optional[str] = None, limit: int = 100
    ) -> List[StoredChatMessage]:
        """
        Get most recent messages for a session.

        Args:
            session_id: Restrict to one session (None = all sessions).
            limit: Maximum number of messages to return.

        Returns:
            List of recent messages ordered by timestamp ascending.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute(
                    f"""
                    SELECT {_ROW_COLUMNS}
                    FROM chat_messages
                    WHERE session_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """,
                    (session_id, limit),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT {_ROW_COLUMNS}
                    FROM chat_messages
                    ORDER BY timestamp DESC
                    LIMIT ?
                """,
                    (limit,),
                )
            messages = [_row_to_message(row) for row in cursor.fetchall()]
            # Reverse to get chronological order
            messages.reverse()
            return messages

    def clear_messages(self, session_id: Optional[str] = None) -> int:
        """
        Clear messages — one session's, or all when session_id is None.

        Returns:
            Number of messages deleted.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE session_id = ?",
                    (session_id,),
                )
                count = cursor.fetchone()[0]
                cursor.execute(
                    "DELETE FROM chat_messages WHERE session_id = ?", (session_id,)
                )
            else:
                cursor.execute("SELECT COUNT(*) FROM chat_messages")
                count = cursor.fetchone()[0]
                cursor.execute("DELETE FROM chat_messages")
            conn.commit()
            return count

    def update_option_selected(self, message_id: str, option_value: str) -> bool:
        """
        Mark which option was selected on a message.

        Args:
            message_id: The message ID to update.
            option_value: The value of the selected option.

        Returns:
            True if the message was updated, False if not found.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE chat_messages SET option_selected = ? WHERE message_id = ?",
                (option_value, message_id),
            )
            conn.commit()
            return cursor.rowcount > 0

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
                "DELETE FROM chat_messages WHERE message_id = ?", (message_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_messages_before(
        self,
        before_timestamp: float,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[StoredChatMessage]:
        """
        Get messages older than a given timestamp, ordered newest-first then reversed.

        Args:
            before_timestamp: Unix timestamp upper bound (exclusive).
            session_id: Restrict to one session (None = all sessions).
            limit: Maximum number of messages to return.

        Returns:
            List of messages ordered by timestamp ascending (oldest first).
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute(
                    f"""
                    SELECT {_ROW_COLUMNS}
                    FROM chat_messages
                    WHERE timestamp < ? AND session_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """,
                    (before_timestamp, session_id, limit),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT {_ROW_COLUMNS}
                    FROM chat_messages
                    WHERE timestamp < ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """,
                    (before_timestamp, limit),
                )
            messages = [_row_to_message(row) for row in cursor.fetchall()]
            messages.reverse()  # Return in chronological order
            return messages

    def get_message_count(self, session_id: Optional[str] = None) -> int:
        """Get total number of messages (optionally for one session)."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE session_id = ?",
                    (session_id,),
                )
            else:
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
