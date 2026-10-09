"""SessionType.MINI_BROWSER: the dedicated chat behind the Mini Browser page.

It must behave like a chat session everywhere that matters (creation,
persistence, restore, deletion) while staying distinct from Agent App
sessions, and ``MiniBrowserWS.ensure_session`` must create it exactly once —
also across a restart, where the session is restored instead.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import app.mini_browser.ws as mbws
from agent_core.core.session import MAIN_SESSION_ID, Session, SessionType
from agent_core.core.state import StateSession
from app.mini_browser import ACTION_SET, SESSION_ID, SESSION_TITLE, SKILL_NAME
from app.usage.session_storage import SessionStorage


class _Streams:
    """The event-stream manager surface SessionManager touches."""

    def get_stream_by_id(self, session_id):
        return None


@pytest.fixture
def storage(tmp_path):
    return SessionStorage(db_path=str(tmp_path / "sessions.db"))


@pytest.fixture
def make_manager(tmp_path, storage):
    from agent_core.core.impl.session.manager import SessionManager

    created = []

    def make():
        manager = SessionManager(
            _Streams(),
            workspace_root=tmp_path / "workspace",
            on_session_persist=storage.persist_session,
        )
        created.append(manager)
        return manager

    yield make
    for manager in created:  # StateSession is process-global
        for session_id in list(manager.sessions):
            StateSession.end(session_id)


def test_session_type_constant():
    assert SessionType.MINI_BROWSER == "mini_browser"
    assert SessionType.MINI_BROWSER in SessionType.ALL
    assert set(SessionType.ALL) == {"main", "chat", "agent_app", "mini_browser"}


def test_round_trip_keeps_the_type(storage):
    session = Session(
        id=SESSION_ID,
        type=SessionType.MINI_BROWSER,
        title=SESSION_TITLE,
        action_sets=[ACTION_SET],
        selected_skills=[SKILL_NAME],
    )
    assert Session.from_dict(session.to_dict()).to_dict() == session.to_dict()

    storage.persist_session(session)
    [row] = storage.get_all_sessions()
    restored = Session.from_dict(json.loads(row["session_json"]))
    assert restored.type == SessionType.MINI_BROWSER
    assert restored.action_sets == [ACTION_SET]
    assert restored.agent_app_project_id is None  # no Agent App branch applies


def test_manager_creates_lists_and_deletes_it_like_a_chat(make_manager):
    manager = make_manager()
    manager.ensure_main()
    chat = manager.create_session(session_type=SessionType.CHAT)
    app_session = manager.create_session(
        session_type=SessionType.AGENT_APP,
        title="Todo app",
        session_id="agentapp_p1",
        agent_app_project_id="p1",
    )
    browser = manager.create_session(
        session_type=SessionType.MINI_BROWSER,
        title=SESSION_TITLE,
        session_id=SESSION_ID,
        action_sets=[ACTION_SET],
    )

    assert browser.type == SessionType.MINI_BROWSER
    assert browser.title == SESSION_TITLE  # never the "New chat" placeholder
    assert browser.workspace_dir and browser.workspace_dir.endswith(SESSION_ID)
    assert [s.id for s in manager.list_sessions()] == [
        MAIN_SESSION_ID,
        SESSION_ID,
        app_session.id,
        chat.id,
    ]
    # Fixed id: creating it again returns the same session.
    assert (
        manager.create_session(
            session_type=SessionType.MINI_BROWSER, session_id=SESSION_ID
        )
        is browser
    )
    # Unlike main, it can be deleted (the page recreates it on demand).
    assert manager.delete_session(SESSION_ID) is True
    assert manager.get(SESSION_ID) is None


def test_unknown_types_are_still_refused(make_manager):
    with pytest.raises(ValueError):
        make_manager().create_session(session_type="browser")


def _adapter(manager):
    adapter = SimpleNamespace(
        _controller=SimpleNamespace(agent=SimpleNamespace(session_manager=manager)),
        broadcasts=[],
    )
    adapter._session_info = lambda s: {"id": s.id, "type": s.type, "title": s.title}

    async def _broadcast(message):
        adapter.broadcasts.append(message)

    adapter._broadcast = _broadcast
    return adapter


def test_ensure_session_creates_it_once_and_restores_it_after_restart(
    make_manager, storage, monkeypatch
):
    monkeypatch.setattr(mbws, "_preloaded_skills", lambda: [SKILL_NAME])
    monkeypatch.setattr(mbws, "_notify_sessions_changed", lambda session_id: None)
    manager = make_manager()
    handler = mbws.MiniBrowserWS(_adapter(manager))

    session = handler.ensure_session()
    assert session.id == SESSION_ID
    assert session.type == SessionType.MINI_BROWSER
    assert session.title == SESSION_TITLE
    assert session.action_sets == [ACTION_SET]
    assert session.selected_skills == [SKILL_NAME]
    assert handler.ensure_session() is session  # idempotent

    # "Restart": a new manager restores the persisted session from storage.
    restarted = make_manager()
    for row in storage.get_all_sessions():
        restarted.restore_session(Session.from_dict(json.loads(row["session_json"])))
    calls = []
    original_create = restarted.create_session
    restarted.create_session = lambda **kw: calls.append(kw) or original_create(**kw)
    restored = mbws.MiniBrowserWS(_adapter(restarted)).ensure_session()
    assert calls == []  # restored, not recreated
    assert restored.type == SessionType.MINI_BROWSER
    assert restored.selected_skills == [SKILL_NAME]


@pytest.mark.parametrize(
    "skill,expected",
    [
        (None, []),
        (SimpleNamespace(enabled=False, is_system=False), []),
        (SimpleNamespace(enabled=True, is_system=False), [SKILL_NAME]),
        (SimpleNamespace(enabled=False, is_system=True), [SKILL_NAME]),
    ],
)
def test_skill_is_preloaded_only_when_installed_and_enabled(
    monkeypatch, skill, expected
):
    from app.skill import skill_manager

    monkeypatch.setattr(
        skill_manager, "get_skill", lambda name: skill if name == SKILL_NAME else None
    )
    assert mbws._preloaded_skills() == expected
