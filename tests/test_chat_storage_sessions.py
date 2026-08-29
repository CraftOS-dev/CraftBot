# -*- coding: utf-8 -*-
"""Tests for ChatStorage session scoping and the task_session_id →
session_id migration path."""

import sqlite3
import time

from agent_core.core.session import MAIN_SESSION_ID
from app.usage.chat_storage import ChatStorage, StoredChatMessage


def make_storage(tmp_path):
    return ChatStorage(db_path=str(tmp_path / "chat.db"))


def msg(message_id, session_id, content=None, ts=None):
    return StoredChatMessage(
        message_id=message_id,
        sender="user",
        content=content or f"content-{message_id}",
        style="normal",
        timestamp=ts if ts is not None else time.time(),
        session_id=session_id,
    )


class TestSessionScoping:
    def test_get_recent_messages_isolated_per_session(self, tmp_path):
        storage = make_storage(tmp_path)
        storage.insert_message(msg("a1", "sess-a", ts=1.0))
        storage.insert_message(msg("b1", "sess-b", ts=2.0))
        storage.insert_message(msg("a2", "sess-a", ts=3.0))

        got_a = storage.get_recent_messages(session_id="sess-a")
        got_b = storage.get_recent_messages(session_id="sess-b")

        assert [m.message_id for m in got_a] == ["a1", "a2"]  # chronological
        assert [m.message_id for m in got_b] == ["b1"]
        assert all(m.session_id == "sess-a" for m in got_a)

    def test_unscoped_read_sees_all_sessions(self, tmp_path):
        storage = make_storage(tmp_path)
        storage.insert_message(msg("a1", "sess-a", ts=1.0))
        storage.insert_message(msg("b1", "sess-b", ts=2.0))
        assert [m.message_id for m in storage.get_recent_messages()] == ["a1", "b1"]

    def test_clear_messages_leaves_other_session_intact(self, tmp_path):
        storage = make_storage(tmp_path)
        storage.insert_message(msg("a1", "sess-a"))
        storage.insert_message(msg("a2", "sess-a"))
        storage.insert_message(msg("b1", "sess-b"))

        deleted = storage.clear_messages(session_id="sess-a")

        assert deleted == 2
        assert storage.get_message_count(session_id="sess-a") == 0
        remaining = storage.get_recent_messages(session_id="sess-b")
        assert [m.message_id for m in remaining] == ["b1"]

    def test_message_defaults_to_main_session(self, tmp_path):
        storage = make_storage(tmp_path)
        storage.insert_message(
            StoredChatMessage(
                message_id="m1",
                sender="agent",
                content="hi",
                style="normal",
                timestamp=time.time(),
            )
        )
        got = storage.get_recent_messages(session_id=MAIN_SESSION_ID)
        assert [m.message_id for m in got] == ["m1"]
        assert got[0].session_id == MAIN_SESSION_ID


class TestLegacyMigration:
    def _create_legacy_db(self, db_path):
        """Build a pre-session-era chat DB (task_session_id, no session_id)."""
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL UNIQUE,
                    sender TEXT NOT NULL,
                    content TEXT NOT NULL,
                    style TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    attachments TEXT,
                    task_session_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                """
                INSERT INTO chat_messages
                (message_id, sender, content, style, timestamp, attachments,
                 task_session_id)
                VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                ("legacy-tagged", "user", "task chat", "normal", 1.0, "task-77"),
            )
            conn.execute(
                """
                INSERT INTO chat_messages
                (message_id, sender, content, style, timestamp, attachments,
                 task_session_id)
                VALUES (?, ?, ?, ?, ?, NULL, NULL)
                """,
                ("legacy-untagged", "user", "plain chat", "normal", 2.0),
            )
            conn.commit()

    def test_reopen_backfills_session_id(self, tmp_path):
        db_path = str(tmp_path / "chat.db")
        self._create_legacy_db(db_path)

        storage = ChatStorage(db_path=db_path)  # triggers migration

        tagged = storage.get_recent_messages(session_id="task-77")
        assert [m.message_id for m in tagged] == ["legacy-tagged"]

        untagged = storage.get_recent_messages(session_id=MAIN_SESSION_ID)
        assert [m.message_id for m in untagged] == ["legacy-untagged"]

        # No message lost in migration
        assert storage.get_message_count() == 2

    def test_migrated_db_accepts_new_session_writes(self, tmp_path):
        db_path = str(tmp_path / "chat.db")
        self._create_legacy_db(db_path)
        storage = ChatStorage(db_path=db_path)

        storage.insert_message(msg("new1", "sess-new", ts=3.0))

        got = storage.get_recent_messages(session_id="sess-new")
        assert [m.message_id for m in got] == ["new1"]
        # options/option_selected columns were added by migration too
        assert storage.update_option_selected("new1", "yes") is True


class TestDetails:
    def test_details_round_trip(self, tmp_path):
        """`details` (expandable payload on the "📩 Incoming …" stub)
        survives insert → read and serializes on to_dict (PR #419)."""
        storage = make_storage(tmp_path)
        stored = StoredChatMessage(
            message_id="d1",
            sender="System",
            content="📩 Incoming Telegram message from Ada",
            style="system",
            timestamp=1.0,
            details="hello from telegram\n[Attachment: photo, file_id=big]",
        )
        storage.insert_message(stored)

        got = storage.get_recent_messages()[0]
        assert got.details == stored.details
        assert got.to_dict()["details"] == stored.details

    def test_details_absent_by_default(self, tmp_path):
        storage = make_storage(tmp_path)
        storage.insert_message(msg("p1", "main", ts=1.0))
        got = storage.get_recent_messages()[0]
        assert got.details is None
        assert "details" not in got.to_dict()

    def test_migrated_db_gains_details_column(self, tmp_path):
        db_path = str(tmp_path / "chat.db")
        TestLegacyMigration._create_legacy_db(TestLegacyMigration(), db_path)
        storage = ChatStorage(db_path=db_path)  # triggers migration

        stored = msg("d2", "main", ts=3.0)
        stored.details = "body"
        storage.insert_message(stored)
        got = storage.get_recent_messages(session_id="main")
        assert got[-1].details == "body"
