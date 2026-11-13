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
    ActionMetadata(name="a2app_command", action_sets=["a2app"]),
    ActionMetadata(name="agent_app_command", action_sets=["agent_app"]),
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
    # Which provider each integration set serves, as the integration adapter
    # declares it for the actions it generates.
    monkeypatch.setattr(
        action_set_manager,
        "integration_sets",
        lambda: {
            "gmail": ["gmail_mail", "gmail", "gmail_admin"],
            "github": ["github_workflows"],
            "stripe": ["stripe_disputes"],
            "jira": ["jira_attachments"],
        },
    )


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
        "a2app_command",
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
    assert "a2app_command" in restored.compiled_actions


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
    assert '{"name":"send_gmail"' in event.message
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
    result = iai.load_action_sets(["a2app", "core"], session_id=session.id)
    assert result["actions"] == []
    assert _schema_events(stream) == []


def test_build_tools_load_separately_from_app_operation(loader):
    iai, session, stream = loader
    assert "a2app_command" in session.compiled_actions
    assert "agent_app_command" not in session.compiled_actions
    result = iai.load_action_sets(["agent_app"], session_id=session.id)
    assert result["actions"] == ["agent_app_command"]
    assert _schema_events(stream)[0].schema_actions == ["agent_app_command"]
    assert "agent_app_command" not in session.compiled_actions


def test_restored_isolated_app_task_has_only_operating_tools(sessions):
    session = Session.from_dict({
        "id": "app-task", "type": SessionType.AGENT_APP,
        "isolated_app_task": True,
        "compiled_actions": ["agent_app_framework_command", "agent_app_command"],
    })
    restored = sessions.restore_session(session)
    assert restored.compiled_actions == ["a2app_command", "send_message", "end_turn"]


@pytest.mark.parametrize("name,surface", [
    ("agent_app_command", "agent-app"), ("a2app_command", "a2app"),
])
def test_native_command_source_binds_the_cli_surface(monkeypatch, name, surface):
    import asyncio
    import inspect
    from unittest.mock import AsyncMock
    from agent_core.core.action_framework.registry import _strip_decorator
    from app.agent_app import framework_commands
    from app.data.action import agent_app_framework_actions as actions

    command = AsyncMock(return_value={"status": "success", "stdout": "upstream result"})
    monkeypatch.setattr(framework_commands, "command", command)
    # Run the extracted function just as CraftBot does, with no module globals.
    namespace = {}
    exec(_strip_decorator(inspect.getsource(getattr(actions, name))), namespace)
    result = asyncio.run(namespace[name]({
        "args": ["--help"], "cwd": "C:/apps", "surface": "wrong-surface",
    }))
    command.assert_awaited_once_with(surface, ["--help"], cwd="C:/apps")
    assert result == command.return_value


def test_unknown_sets_are_reported(loader):
    iai, session, stream = loader
    assert iai.load_action_sets(["nope"], session_id=session.id)["success"] is False

    mixed = iai.load_action_sets(["nope", "document_processing"], session_id=session.id)
    assert mixed["success"] is True
    assert mixed["unknown_sets"] == ["nope"]
    assert mixed["actions"] == ["read_pdf"]


def test_upgrade_retires_legacy_actions_and_rebinds_chat_wizard(tmp_path, monkeypatch):
    from agent_core.core.action_framework.registry import registry_instance
    from app.database_interface import DatabaseInterface, RETIRED_APP_ACTIONS

    monkeypatch.setattr(registry_instance, "_registry", {})
    actions_dir = tmp_path / "action"
    actions_dir.mkdir()
    names = sorted(RETIRED_APP_ACTIONS | {"agent_app_scaffold", "my_custom_action"})
    source = "from agent_core import action\n" + "\n".join(
        f'@action(name="{name}", action_sets=["agent_app"])\n'
        f'async def {name}(input_data):\n    return {{"old": True}}\n'
        for name in names
    )
    saved = actions_dir / "old_app_actions.py"
    saved.write_text(source, encoding="utf-8")
    DatabaseInterface(data_dir=str(tmp_path))
    assert not RETIRED_APP_ACTIONS.intersection(registry_instance._registry)
    assert registry_instance.get_action_implementation("my_custom_action")
    scaffold = registry_instance.get_action_implementation("agent_app_scaffold")
    assert scaffold.handler.__module__ == "app.data.action.agent_app_actions"
    assert saved.read_text(encoding="utf-8") == source
