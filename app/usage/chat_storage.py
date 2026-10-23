# -*- coding: utf-8 -*-
"""
app.usage.chat_storage

SQLite-based storage for chat messages, keyed by session.
Provides local persistence for every session's chat history across restarts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_core.core.session import MAIN_SESSION_ID

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# <session key>/<artifact id>/<content hash>.<extension> (store_ui_images).
_UI_IMAGE_PATH = re.compile(
    r"[0-9a-f]{16}/[A-Za-z0-9_-]{1,80}/[0-9a-f]{16}\.(?:png|jpg|gif|webp)"
)


def _ui_session_key(session_id: str) -> str:
    """A session's images folder: any session id, as a fixed safe name."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


_ROW_COLUMNS = (
    "message_id, sender, content, style, timestamp, attachments, "
    "session_id, options, option_selected, continue_work, "
    "is_question, allow_free_text, details, ui_artifact"
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
    # Question with suggested responses (send_message suggested_responses).
    # Persisted so an unanswered question re-pins above the composer after a
    # reload — pending questions ARE the stored question messages with no
    # option_selected.
    is_question: bool = False
    allow_free_text: bool = True
    # Expandable payload behind a disclosure (e.g. the raw body of an
    # incoming integration message on the "📩 Incoming …" system stub).
    details: Optional[str] = None
    ui_artifact: Optional[Dict[str, Any]] = None

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
        if self.is_question:
            result["isQuestion"] = True
            result["allowFreeText"] = self.allow_free_text
        if self.details:
            result["details"] = self.details
        if self.ui_artifact:
            result["uiArtifact"] = self.ui_artifact
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
        is_question=bool(row[10]),
        allow_free_text=bool(row[11]),
        details=row[12],
        ui_artifact=json.loads(row[13]) if row[13] else None,
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
        # Generative UI outputs' images belong to the chat history: they live
        # beside it and go with the messages that show them.
        self._ui_images_dir = Path(db_path).parent / "generative_ui"
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
            if "is_question" not in columns:
                cursor.execute(
                    "ALTER TABLE chat_messages ADD COLUMN is_question "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            if "allow_free_text" not in columns:
                cursor.execute(
                    "ALTER TABLE chat_messages ADD COLUMN allow_free_text "
                    "INTEGER NOT NULL DEFAULT 1"
                )
            if "details" not in columns:
                cursor.execute("ALTER TABLE chat_messages ADD COLUMN details TEXT")
            if "ui_artifact" not in columns:
                cursor.execute("ALTER TABLE chat_messages ADD COLUMN ui_artifact TEXT")

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_session
                ON chat_messages(session_id, timestamp)
            """)

            # Read receipts must outlive a browser process crash. Keep them
            # beside the messages rather than relying on browser disk flushes.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_session_reads (
                    session_id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    message_timestamp REAL NOT NULL,
                    message_row_id INTEGER NOT NULL
                )
            """)

            conn.commit()

    def get_last_seen_message_ids(self) -> Dict[str, str]:
        """Durable read markers for this single-user CraftBot instance."""
        with sqlite3.connect(self._db_path) as conn:
            return dict(
                conn.execute("""
                SELECT r.session_id, r.message_id FROM chat_session_reads r
                JOIN chat_messages m ON m.message_id = r.message_id
                    AND m.session_id = r.session_id
            """)
            )

    def mark_session_seen(self, session_id: str, message_id: str) -> Optional[str]:
        """Commit a read receipt, ignoring unknown IDs and older receipts.

        Return the committed marker so delayed requests from another window
        cannot move the browser's read position backwards.
        """
        with sqlite3.connect(self._db_path) as conn:
            message = conn.execute(
                "SELECT timestamp, id FROM chat_messages "
                "WHERE session_id = ? AND message_id = ?",
                (session_id, message_id),
            ).fetchone()
            if message is None:
                return None
            conn.execute(
                """
                INSERT INTO chat_session_reads
                    (session_id, message_id, message_timestamp, message_row_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    message_id = excluded.message_id,
                    message_timestamp = excluded.message_timestamp,
                    message_row_id = excluded.message_row_id
                WHERE excluded.message_timestamp > chat_session_reads.message_timestamp
                   OR (excluded.message_timestamp = chat_session_reads.message_timestamp
                       AND excluded.message_row_id > chat_session_reads.message_row_id)
            """,
                (session_id, message_id, *message),
            )
            seen = conn.execute(
                "SELECT message_id FROM chat_session_reads WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            conn.commit()
            return seen

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
                (message_id, sender, content, style, timestamp, attachments, session_id, options, option_selected, continue_work, is_question, allow_free_text, details, ui_artifact)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    1 if message.is_question else 0,
                    1 if message.allow_free_text else 0,
                    message.details,
                    json.dumps(message.ui_artifact) if message.ui_artifact else None,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def close_ui_artifact(self, session_id: str, artifact_id: str) -> int:
        """The user closed a Generative UI output: every stored revision of it
        keeps only a closed marker (``closed_artifact``), its code is dropped.
        Returns how many messages carried it."""
        from app.generative_ui import closed_artifact

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT id, ui_artifact FROM chat_messages "
                "WHERE session_id = ? AND ui_artifact IS NOT NULL "
                "AND json_extract(ui_artifact, '$.id') = ?",
                (session_id, artifact_id),
            ).fetchall()
            for row_id, raw in rows:
                conn.execute(
                    "UPDATE chat_messages SET ui_artifact = ? WHERE id = ?",
                    (json.dumps(closed_artifact(json.loads(raw))), row_id),
                )
            conn.commit()
        self._remove_ui_images(_ui_session_key(session_id), artifact_id)
        return len(rows)

    def store_ui_images(
        self,
        session_id: str,
        artifact_id: str,
        images: Dict[str, Tuple[bytes, str]],
    ) -> Dict[str, str]:
        """Keep an output's images (``read_images``) for its revisions.
        Returns name -> path, as /api/generative-ui serves it."""
        key = _ui_session_key(session_id)
        folder = self._ui_images_dir / key / artifact_id
        stored = {}
        for name, (data, kind) in images.items():
            file = f"{hashlib.sha256(data).hexdigest()[:16]}.{kind}"
            target = folder / file
            if not target.exists():
                folder.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            stored[name] = f"{key}/{artifact_id}/{file}"
        return stored

    def ui_image_file(self, path: str) -> Optional[Path]:
        """The stored image at a path ``store_ui_images`` returned, if any."""
        if not _UI_IMAGE_PATH.fullmatch(path):
            return None
        file = self._ui_images_dir / path
        return file if file.is_file() else None

    def _remove_ui_images(self, *parts: str) -> None:
        """Delete the images of one output, one session, or (no parts) all."""
        folder = self._ui_images_dir.joinpath(*parts)
        if not folder.exists():
            return
        try:
            shutil.rmtree(folder)
        except OSError as exc:
            logger.warning(f"[ChatStorage] Could not delete {folder}: {exc}")

    def get_latest_ui_artifact(
        self, session_id: str, artifact_id: str
    ) -> Optional[dict]:
        """Find a revision even after its event has been folded out of context."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT ui_artifact FROM chat_messages "
                "WHERE session_id = ? AND ui_artifact IS NOT NULL "
                "AND json_extract(ui_artifact, '$.id') = ? "
                "ORDER BY json_extract(ui_artifact, '$.revision') DESC LIMIT 1",
                (session_id, artifact_id),
            ).fetchone()
        return json.loads(row[0]) if row else None

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
                cursor.execute(
                    "DELETE FROM chat_session_reads WHERE session_id = ?", (session_id,)
                )
            else:
                cursor.execute("SELECT COUNT(*) FROM chat_messages")
                count = cursor.fetchone()[0]
                cursor.execute("DELETE FROM chat_messages")
                cursor.execute("DELETE FROM chat_session_reads")
            conn.commit()
        if session_id:
            self._remove_ui_images(_ui_session_key(session_id))
        else:
            self._remove_ui_images()
        return count

    def get_pending_questions(self, session_id: str) -> List[Tuple[str, str]]:
        """
        A session's unanswered question messages as (message_id, content),
        oldest first.

        A question is pending until the user answers or dismisses it
        (option_selected set). The first one is the question the UI's box
        is showing; the rest remind the agent which of its questions are
        still pinned so it doesn't re-ask them.
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT message_id, content FROM chat_messages
                WHERE session_id = ? AND is_question = 1
                  AND (option_selected IS NULL OR option_selected = '')
                ORDER BY timestamp ASC
            """,
                (session_id,),
            )
            return [(row[0], row[1]) for row in cursor.fetchall()]

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
