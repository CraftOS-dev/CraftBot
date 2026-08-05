# -*- coding: utf-8 -*-
"""Tests for the Session dataclass serialization and SessionStorage
persist/restore round-trips."""

import json

from agent_core.core.session import (
    MAIN_SESSION_ID,
    Session,
    SessionType,
    TodoItem,
)
from app.usage.session_storage import SessionStorage


def make_storage(tmp_path):
    return SessionStorage(db_path=str(tmp_path / "sessions.db"))


def make_session(session_id="sess-1", **overrides):
    session = Session(
        id=session_id,
        type=SessionType.CHAT,
        title="Plan the trip",
        action_sets=["core", "web_research"],
        compiled_actions=["send_message", "web_search"],
        selected_skills=["trip-planner"],
        todos=[
            TodoItem(content="Book flights", status="completed", id="todo-1"),
            TodoItem(
                content="Reserve hotel",
                status="in_progress",
                active_form="Reserving hotel",
                id="todo-2",
            ),
            TodoItem(content="Pack bags", id="todo-3"),
        ],
        workspace_dir="/tmp/sess-1",
        gui_mode=True,
        action_count=4,
        token_count=1234,
        input_tokens=1000,
        output_tokens=200,
        cache_tokens=34,
    )
    for key, value in overrides.items():
        setattr(session, key, value)
    return session


class TestSessionDataclass:
    def test_to_dict_from_dict_round_trip(self):
        session = make_session()
        restored = Session.from_dict(session.to_dict())
        assert restored.to_dict() == session.to_dict()
        assert restored.id == "sess-1"
        assert restored.type == SessionType.CHAT
        assert restored.action_sets == ["core", "web_research"]
        assert restored.gui_mode is True
        assert restored.input_tokens == 1000

    def test_todos_round_trip(self):
        session = make_session()
        restored = Session.from_dict(session.to_dict())
        assert [t.id for t in restored.todos] == ["todo-1", "todo-2", "todo-3"]
        assert restored.todos[1].status == "in_progress"
        assert restored.todos[1].active_form == "Reserving hotel"
        # behavior survives round-trip: next actionable todo is in_progress one
        assert restored.get_current_todo().id == "todo-2"
        assert not restored.all_todos_completed()

    def test_from_dict_defaults_for_minimal_payload(self):
        restored = Session.from_dict({"id": MAIN_SESSION_ID, "type": "main"})
        assert restored.id == MAIN_SESSION_ID
        assert restored.type == SessionType.MAIN
        assert restored.todos == []
        assert restored.archived is False
        assert restored.action_count == 0


class TestSessionStorage:
    def test_persist_and_get_all_round_trip(self, tmp_path):
        storage = make_storage(tmp_path)
        session = make_session()
        storage.persist_session(session)

        rows = storage.get_all_sessions()
        assert len(rows) == 1
        assert rows[0]["session_id"] == "sess-1"
        restored = Session.from_dict(json.loads(rows[0]["session_json"]))
        assert restored.to_dict() == session.to_dict()

    def test_persist_is_upsert(self, tmp_path):
        storage = make_storage(tmp_path)
        session = make_session()
        storage.persist_session(session)

        session.title = "Renamed"
        session.todos.append(TodoItem(content="New step", id="todo-4"))
        storage.persist_session(session)

        rows = storage.get_all_sessions()
        assert len(rows) == 1  # updated, not duplicated
        restored = Session.from_dict(json.loads(rows[0]["session_json"]))
        assert restored.title == "Renamed"
        assert [t.id for t in restored.todos][-1] == "todo-4"

    def test_get_session_by_id(self, tmp_path):
        storage = make_storage(tmp_path)
        storage.persist_session(make_session("sess-a"))
        storage.persist_session(make_session("sess-b"))

        data = storage.get_session("sess-b")
        assert data is not None
        assert Session.from_dict(data).id == "sess-b"
        assert storage.get_session("nope") is None

    def test_remove_session(self, tmp_path):
        storage = make_storage(tmp_path)
        storage.persist_session(make_session("sess-a"))
        storage.persist_session(make_session("sess-b"))

        storage.remove_session("sess-a")

        remaining = {row["session_id"] for row in storage.get_all_sessions()}
        assert remaining == {"sess-b"}
        assert storage.get_session("sess-a") is None

    def test_reopen_preserves_sessions(self, tmp_path):
        storage = make_storage(tmp_path)
        session = make_session()
        storage.persist_session(session)

        reopened = make_storage(tmp_path)  # same db file
        rows = reopened.get_all_sessions()
        assert len(rows) == 1
        restored = Session.from_dict(json.loads(rows[0]["session_json"]))
        assert restored.to_dict() == session.to_dict()

    def test_clear_all(self, tmp_path):
        storage = make_storage(tmp_path)
        storage.persist_session(make_session())
        storage.clear_all()
        assert storage.get_all_sessions() == []
