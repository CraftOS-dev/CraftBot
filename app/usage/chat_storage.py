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
    task_session_id: Optional[str] = None
    options: Optional[List[Dict[str, Any]]] = None
    option_selected: Optional[str] = None
    questions: Optional[List[Dict[str, Any]]] = None
    question_answers: Optional[Dict[str, str]] = None
    questions_declined: Optional[bool] = None

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
        if self.task_session_id:
            result["taskSessionId"] = self.task_session_id
        if self.options:
            result["options"] = self.options
        if self.option_selected:
            result["optionSelected"] = self.option_selected
        if self.questions:
            result["questions"] = self.questions
        if self.question_answers:
            result["questionAnswers"] = self.question_answers
        if self.questions_declined:
            result["questionsDeclined"] = self.questions_declined
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

            # Migration: Add new columns if they don't exist
            cursor.execute("PRAGMA table_info(chat_messages)")
            columns = [col[1] for col in cursor.fetchall()]
            if "task_session_id" not in columns:
                cursor.execute("""
                    ALTER TABLE chat_messages
                    ADD COLUMN task_session_id TEXT
                """)
                logger.info("[ChatStorage] Migrated: added task_session_id column")
            if "options" not in columns:
                cursor.execute("""
                    ALTER TABLE chat_messages
                    ADD COLUMN options TEXT
                """)
                logger.info("[ChatStorage] Migrated: added options column")
            if "option_selected" not in columns:
                cursor.execute("""
                    ALTER TABLE chat_messages
                    ADD COLUMN option_selected TEXT
                """)
                logger.info("[ChatStorage] Migrated: added option_selected column")
            if "questions" not in columns:
                cursor.execute("""
                    ALTER TABLE chat_messages
                    ADD COLUMN questions TEXT
                """)
                logger.info("[ChatStorage] Migrated: added questions column")
            if "question_answers" not in columns:
                cursor.execute("""
                    ALTER TABLE chat_messages
                    ADD COLUMN question_answers TEXT
                """)
                logger.info("[ChatStorage] Migrated: added question_answers column")
            if "questions_declined" not in columns:
                cursor.execute("""
                    ALTER TABLE chat_messages
                    ADD COLUMN questions_declined INTEGER
                """)
                logger.info("[ChatStorage] Migrated: added questions_declined column")

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
                (message_id, sender, content, style, timestamp, attachments, task_session_id, options, option_selected, questions, question_answers, questions_declined)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    message.message_id,
                    message.sender,
                    message.content,
                    message.style,
                    message.timestamp,
                    json.dumps(message.attachments) if message.attachments else None,
                    message.task_session_id,
                    json.dumps(message.options) if message.options else None,
                    message.option_selected,
                    json.dumps(message.questions) if message.questions else None,
                    json.dumps(message.question_answers) if message.question_answers else None,
                    message.questions_declined,
                ),
            )
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
            cursor.execute(
                """
                SELECT message_id, sender, content, style, timestamp, attachments, task_session_id, options, option_selected, questions, question_answers, questions_declined
                FROM chat_messages
                ORDER BY timestamp ASC
                LIMIT ? OFFSET ?
            """,
                (limit, offset),
            )
            rows = cursor.fetchall()

            return [
                StoredChatMessage(
                    message_id=row[0],
                    sender=row[1],
                    content=row[2],
                    style=row[3],
                    timestamp=row[4],
                    attachments=json.loads(row[5]) if row[5] else None,
                    task_session_id=row[6],
                    options=json.loads(row[7]) if row[7] else None,
                    option_selected=row[8],
                    questions=json.loads(row[9]) if row[9] else None,
                    question_answers=json.loads(row[10]) if row[10] else None,
                    questions_declined=bool(row[11]) if row[11] is not None else None,
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
            cursor.execute(
                """
                SELECT message_id, sender, content, style, timestamp, attachments, task_session_id, options, option_selected, questions, question_answers, questions_declined
                FROM chat_messages
                ORDER BY timestamp DESC
                LIMIT ?
            """,
                (limit,),
            )
            rows = cursor.fetchall()

            messages = [
                StoredChatMessage(
                    message_id=row[0],
                    sender=row[1],
                    content=row[2],
                    style=row[3],
                    timestamp=row[4],
                    attachments=json.loads(row[5]) if row[5] else None,
                    task_session_id=row[6],
                    options=json.loads(row[7]) if row[7] else None,
                    option_selected=row[8],
                    questions=json.loads(row[9]) if row[9] else None,
                    question_answers=json.loads(row[10]) if row[10] else None,
                    questions_declined=bool(row[11]) if row[11] is not None else None,
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

    def update_question_answers(
        self,
        message_id: str,
        answers: Optional[Dict[str, str]],
        declined: bool,
    ) -> bool:
        """
        Record the resolution of a clarifying-question batch on a message.

        Args:
            message_id: The message ID to update.
            answers: Answer text per question id, or None if declined.
            declined: True if the user escaped out of the batch instead of answering.

        Returns:
            True if the message was updated, False if not found.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE chat_messages SET question_answers = ?, questions_declined = ? WHERE message_id = ?",
                (json.dumps(answers) if answers else None, declined, message_id),
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
        limit: int = 50,
    ) -> List[StoredChatMessage]:
        """
        Get messages older than a given timestamp, ordered newest-first then reversed.

        Args:
            before_timestamp: Unix timestamp upper bound (exclusive).
            limit: Maximum number of messages to return.

        Returns:
            List of messages ordered by timestamp ascending (oldest first).
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT message_id, sender, content, style, timestamp, attachments, task_session_id, options, option_selected, questions, question_answers, questions_declined
                FROM chat_messages
                WHERE timestamp < ?
                ORDER BY timestamp DESC
                LIMIT ?
            """,
                (before_timestamp, limit),
            )
            rows = cursor.fetchall()

            messages = [
                StoredChatMessage(
                    message_id=row[0],
                    sender=row[1],
                    content=row[2],
                    style=row[3],
                    timestamp=row[4],
                    attachments=json.loads(row[5]) if row[5] else None,
                    task_session_id=row[6],
                    options=json.loads(row[7]) if row[7] else None,
                    option_selected=row[8],
                    questions=json.loads(row[9]) if row[9] else None,
                    question_answers=json.loads(row[10]) if row[10] else None,
                    questions_declined=bool(row[11]) if row[11] is not None else None,
                )
                for row in rows
            ]
            messages.reverse()  # Return in chronological order
            return messages

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
