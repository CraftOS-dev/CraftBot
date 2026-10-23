# -*- coding: utf-8 -*-
"""
<actions> is derived from the session type; loading a set is a read.

Observed 2026-10-14 in session lui_9a07529e: an agent-app session had
accumulated 14 action sets over earlier runs (gmail, discord, posthog, ...),
so every decision call printed 142 integration actions it never used and the
request overflowed the context budget four times in 30 minutes. A session's
printed list is now a function of its type, and add_action_sets delivers a
set's schemas into the event stream instead of growing the list.
"""

import pytest

from agent_core.core.action_framework.registry import ActionMetadata
from agent_core.core.event_stream.event import EventType
from agent_core.core.impl.event_stream.event_stream import EventStream
from agent_core.core.impl.session.manager import SessionManager
from agent_core.core.session import Session, SessionType
from agent_core.core.state.session import StateSession

_REGISTRY = [
    ActionMetadata(name="send_message", action_sets=["core"]),
    ActionMetadata(name="read_file", action_sets=["core"]),
    ActionMetadata(name="agent_app_notify_ready", action_sets=["agent_app"]),
    ActionMetadata(name="run_python", action_sets=["code_execution"]),
    ActionMetadata(name="find_files", action_sets=["file_operations"]),
    ActionMetadata(
        name="send_gmail",
        description="Send an email.",
        input_schema={"to": {"type": "string", "description": "Recipient."}},
        action_sets=["gmail_mail", "gmail"],
    ),
    ActionMetadata(name="list_gmail", action_sets=["gmail_mail", "gmail"]),
    ActionMetadata(name="get_gmail_settings", action_sets=["gmail_admin"]),
    ActionMetadata(name="list_github_workflows", action_sets=["github_workflows"]),
    ActionMetadata(name="list_stripe_disputes", action_sets=["stripe_disputes"]),
    ActionMetadata(name="add_jira_attachment", action_sets=["jira_attachments"]),
    ActionMetadata(name="read_pdf", action_sets=["document_processing"]),
]


@pytest.fixture
def fake_registry(monkeypatch):
    from app.action.action_set import action_set_manager

    def actions_in_sets(set_names, mode="CLI"):
        wanted = set(set_names)
        return [m for m in _REGISTRY if wanted.intersection(m.action_sets)]

    def list_all_sets():
        return {s: s for m in _REGISTRY for s in m.action_sets}

    monkeypatch.setattr(action_set_manager, "actions_in_sets", actions_in_sets)
    monkeypatch.setattr(action_set_manager, "list_all_sets", list_all_sets)


@pytest.fixture
def sessions(tmp_path, fake_registry):
    manager = SessionManager(event_stream_manager=None, workspace_root=tmp_path)
    yield manager
    for sid in list(manager.sessions):
        StateSession.end(sid)


class _StreamManager:
    """The two calls load_action_sets makes, backed by one real stream."""

    def __init__(self, stream):
        self.stream = stream

    def get_stream_by_id(self, session_id):
        return self.stream

    def log(self, kind, message, severity="INFO", *, task_id=None, **kwargs):
        return self.stream.log(kind, message, severity, **kwargs)


class _StateManager:
    def __init__(self, event_stream_manager):
        self.event_stream_manager = event_stream_manager

    def bump_event_stream(self):
        pass


class _NoLLM:
    consecutive_failures = 0

    def generate_response(self, **kw):  # pragma: no cover - never folds here
        raise AssertionError("no fold expected")


@pytest.fixture
def loader(sessions, tmp_path, monkeypatch):
    import app.internal_action_interface as iai

    stream = EventStream(llm=_NoLLM(), temp_dir=tmp_path / "events")
    monkeypatch.setattr(iai.InternalActionInterface, "session_manager", sessions)
    monkeypatch.setattr(
        iai.InternalActionInterface,
        "state_manager",
        _StateManager(_StreamManager(stream)),
    )
    session = sessions.create_session(
        session_type=SessionType.AGENT_APP, session_id="lui_test"
    )
    return iai.InternalActionInterface, session, stream


def _schema_events(stream):
    return [
        r.event
        for r in stream.tail_events
        if r.event.event_type is EventType.ACTION_SCHEMAS
    ]


def test_actions_follow_the_session_type(sessions):
    chat = sessions.create_session(session_type=SessionType.CHAT, session_id="c1")
    app = sessions.create_session(session_type=SessionType.AGENT_APP, session_id="a1")
    assert chat.compiled_actions == ["send_message", "read_file"]
    assert app.compiled_actions == [
        "send_message",
        "read_file",
        "agent_app_notify_ready",
        "run_python",
        "find_files",
    ]


def test_restore_ignores_an_accumulated_stored_list(sessions):
    stored = Session.from_dict(
        {
            "id": "lui_old",
            "type": SessionType.AGENT_APP,
            "action_sets": ["gmail", "document_processing"],
            "compiled_actions": ["send_gmail", "read_pdf"],
        }
    )
    restored = sessions.restore_session(stored)
    assert "send_gmail" not in restored.compiled_actions
    assert "read_pdf" not in restored.compiled_actions
    assert "agent_app_notify_ready" in restored.compiled_actions


def test_loading_delivers_schemas_without_touching_actions(loader):
    iai, session, stream = loader
    before = list(session.compiled_actions)

    result = iai.load_action_sets(["gmail"], session_id=session.id)

    assert result["success"] is True
    assert result["loaded_sets"] == ["gmail"]
    assert result["actions"] == ["send_gmail", "list_gmail"]
    assert session.compiled_actions == before
    (event,) = _schema_events(stream)
    assert event.schema_actions == ["send_gmail", "list_gmail"]
    assert '"name": "send_gmail"' in event.message
    assert "Recipient." in event.message
    # The integration named in the actions' own sets brings its guidance.
    assert "### gmail" in event.message


def test_a_set_without_an_integration_has_no_guidance(loader):
    iai, session, stream = loader
    iai.load_action_sets(["document_processing"], session_id=session.id)
    (event,) = _schema_events(stream)
    assert event.schema_actions == ["read_pdf"]
    assert "###" not in event.message


@pytest.mark.parametrize(
    "set_name,action_name,provider_id",
    [
        ("github_workflows", "list_github_workflows", "github"),
        ("stripe_disputes", "list_stripe_disputes", "stripe"),
        ("jira_attachments", "add_jira_attachment", "jira"),
    ],
)
def test_subgroup_only_actions_deliver_provider_guidance(
    loader, set_name, action_name, provider_id
):
    iai, session, stream = loader
    result = iai.load_action_sets([set_name], session_id=session.id)

    assert result["success"] is True
    assert result["actions"] == [action_name]
    (event,) = _schema_events(stream)
    assert event.schema_actions == [action_name]
    assert f"### {provider_id}\n" in event.message


def test_new_subgroup_schemas_keep_guidance_after_an_umbrella_load(loader):
    iai, session, stream = loader
    iai.load_action_sets(["gmail"], session_id=session.id)
    result = iai.load_action_sets(["gmail_admin"], session_id=session.id)

    assert result["actions"] == ["get_gmail_settings"]
    first, second = _schema_events(stream)
    assert first.schema_actions == ["send_gmail", "list_gmail"]
    assert second.schema_actions == ["get_gmail_settings"]
    # The first event can be dropped by a fold while this subgroup is in use.
    assert "### gmail\n" in second.message


def test_loading_twice_is_a_no_op(loader):
    iai, session, stream = loader
    iai.load_action_sets(["gmail"], session_id=session.id)

    again = iai.load_action_sets(["gmail_mail"], session_id=session.id)

    assert again["success"] is True
    assert again["actions"] == []
    assert len(_schema_events(stream)) == 1


def test_actions_already_printed_are_not_repeated(loader):
    iai, session, stream = loader
    result = iai.load_action_sets(["agent_app", "core"], session_id=session.id)
    assert result["actions"] == []
    assert _schema_events(stream) == []


def test_unknown_sets_are_reported(loader):
    iai, session, stream = loader
    assert iai.load_action_sets(["nope"], session_id=session.id)["success"] is False

    mixed = iai.load_action_sets(["nope", "document_processing"], session_id=session.id)
    assert mixed["success"] is True
    assert mixed["unknown_sets"] == ["nope"]
    assert mixed["actions"] == ["read_pdf"]
