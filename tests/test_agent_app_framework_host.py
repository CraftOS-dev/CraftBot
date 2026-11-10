"""Host workflows and receipts; never touch an actual user registry or app."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent_app import framework, framework_host
from app.agent_app.framework_cli import CLIResult
from app.agent_app.framework_commands import TaskAuthority, command, task_authority
from app.agent_app.framework_host import FrameworkHost
from app.agent_app.framework_store import HostStore
from agent_core.core.session import Session, SessionType
from agent_core.core.impl.session.manager import SessionManager


class Sessions:
    def __init__(self):
        self.sessions = {}
        self.persisted = []

    def get(self, sid):
        return self.sessions.get(sid)

    def create_session(self, **kwargs):
        sid = kwargs.pop("session_id", None) or str(len(self.sessions) + 1)
        kind = kwargs.pop("session_type", SessionType.CHAT)
        self.sessions[sid] = Session(id=sid, type=kind, **kwargs)
        return self.sessions[sid]

    bind_framework_app = SessionManager.bind_framework_app
    mark_framework_creation = SessionManager.mark_framework_creation
    _compile_actions = staticmethod(SessionManager._compile_actions)

    def _persist(self, session):
        self.persisted.append(session.to_dict())


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    path = str(tmp_path / "app with spaces")
    Path(path).mkdir()
    Path(path, "manifest.json").write_text(
        '{"id":"app","capabilities":{"summarize":{}}}'
    )
    row = {
        "id": "app",
        "name": "Fixture",
        "path": path,
        "status": "running",
        "port": 8123,
    }
    cli = SimpleNamespace(package_dir=tmp_path, home=tmp_path / "home", run=AsyncMock())
    monkeypatch.setattr(framework, "configured_cli", lambda: cli)
    monkeypatch.setattr(
        framework,
        "list_apps",
        AsyncMock(
            return_value={
                "status": "success",
                "data": {"ok": True, "apps": [row], "connected": []},
            }
        ),
    )
    agent = SimpleNamespace(
        session_manager=Sessions(),
        trigger_service=SimpleNamespace(emit=AsyncMock()),
        request_run_stop=AsyncMock(),
    )
    previous = framework_host._host
    host = FrameworkHost(agent, AsyncMock(), HostStore(tmp_path / "host.sqlite3"))
    # Host routing tests isolate filesystem backup mechanics (tested separately).
    monkeypatch.setattr(host.maintenance, "before_remove", AsyncMock())
    yield host, cli, row
    asyncio.run(host.close())
    framework_host._host = previous


def test_attachment_reuses_dedicated_app_session_and_never_registers_legacy_project(fixture):
    host, cli, row = fixture

    async def check():
        first = await host.attach(row["path"], row["id"])
        second = await host.attach(row["path"], row["id"])
        assert first == second
        assert len(host.agent.session_manager.sessions) == 1
        session = host.agent.session_manager.get(first["sessionId"])
        assert session.type == SessionType.AGENT_APP
        assert session.agent_app_framework_key == first["key"]
        assert session.agent_app_project_id is None
        assert session.base_action_sets == ["file_operations", "code_execution", "agent_app_framework"]
        assert "agent_app_framework_command" in host.note(first["sessionId"])
        assert not cli.run.called
        host.changed.assert_awaited_once()  # Reopening is not a registry mutation.

    asyncio.run(check())


def test_attachment_reports_actual_status_changes_but_not_repeated_reads(fixture):
    host, _, row = fixture

    async def check():
        await host.attach(row["path"], row["id"])
        host.changed.reset_mock()
        await host.attach(row["path"], row["id"])
        host.changed.assert_not_awaited()
        row["status"] = "stopped"
        await host.attach(row["path"], row["id"])
        host.changed.assert_awaited_once()
        await host.attach(row["path"], row["id"])
        host.changed.assert_awaited_once()
        host.changed.reset_mock()
        row["port"] = 9000
        await host.attach(row["path"], row["id"])
        host.changed.assert_awaited_once()

    asyncio.run(check())


@pytest.mark.parametrize("surface,args,expected", [
    ("agent-app", ["research", "open", "--if-needed"], ["research", "open", "--if-needed", "--print-only"]),
    ("agent-app", ["research", "open", "--print-only"], ["research", "open", "--print-only"]),
    ("agent-app", ["research", "serve", "--install", "--open"], ["research", "serve", "--install"]),
    ("agent-app", ["install", "board", "--open"], ["install", "board"]),
    ("agent-app", ["research", "import", "--from", "source", "--open"], ["research", "import", "--from", "source"]),
    ("agent-app", ["research", "open", "--help"], ["research", "open", "--help"]),
    ("a2app", ["research", "open"], ["research", "open"]),
])
def test_host_uses_upstream_non_opening_modes_for_embedded_apps(fixture, surface, args, expected):
    _, cli, _ = fixture
    cli.run.return_value = CLIResult(0, '{"ok":true}', "")
    original = list(args)
    result = asyncio.run(command(surface, args))
    assert result["status"] == "success"
    assert cli.run.await_args.args == (surface, expected)
    assert args == original
    if surface == "agent-app" and "--help" not in args:
        assert "embedded view" in result["host_note"]


def test_attachment_cannot_be_replaced_by_main_or_unrelated_chat(fixture):
    host, _, row = fixture
    main = host.agent.session_manager.create_session(session_id="main", session_type="main")
    other = host.agent.session_manager.create_session(title="Unrelated work")
    host.store.put("conversation", main.id, {"path": row["path"], "appId": row["id"]})

    async def check():
        first = await host.attach(row["path"], row["id"], main.id)
        assert first["sessionId"] not in {main.id, other.id}
        assert await host.attach(row["path"], row["id"], other.id) == first
        assert host.note(main.id) == host.note(other.id) == ""
        assert main.type == "main" and other.type == "chat"
        host.agent.trigger_service.emit.assert_not_called()

    asyncio.run(check())


@pytest.mark.parametrize("startup", [False, True])
def test_old_app_chat_is_upgraded_in_place_preserving_history(fixture, startup):
    host, cli, row = fixture

    async def check():
        attached = await host.attach(row["path"], row["id"])
        session = host.agent.session_manager.get(attached["sessionId"])
        # Simulate the ordinary chat persisted by the previous implementation.
        session.type = SessionType.CHAT
        session.agent_app_framework_key = None
        session.total_input_tokens = 1234
        session.selected_skills = ["framework-operator"]
        session.workspace_dir = "/existing/conversation/history"
        if startup:
            host.bridge.restore = AsyncMock()
            await host.startup()
        else:
            assert await host.attach(row["path"], row["id"]) == attached
        assert session.type == SessionType.AGENT_APP
        assert session.agent_app_framework_key == attached["key"]
        assert session.total_input_tokens == 1234
        assert session.selected_skills == ["framework-operator"]
        assert session.workspace_dir == "/existing/conversation/history"
        assert len(host.agent.session_manager.sessions) == 1
        assert host.agent.session_manager.persisted[-1]["id"] == session.id
        assert not cli.run.called

    asyncio.run(check())


def test_creation_belongs_to_apps_before_scaffolding_and_keeps_its_session(fixture):
    host, cli, row = fixture

    async def check():
        result = await host.workflow(
            "create", "A notes app", creation={"name": "Shared notes", "authMode": "none"}
        )
        session = host.agent.session_manager.get(result["sessionId"])
        assert session.type == SessionType.AGENT_APP
        assert session.title == "Shared notes"
        assert session.agent_app_framework_pending
        assert session.agent_app_framework_key is None
        assert session.base_action_sets == ["file_operations", "code_execution", "agent_app_framework"]
        restored = Session.from_dict(session.to_dict())
        assert restored.agent_app_framework_pending and restored.base_action_sets == session.base_action_sets
        assert not Path(result["path"]).exists()
        row["path"] = result["path"]  # Scaffold registered the allocated destination.
        attached = await host.attach(row["path"], row["id"], session.id)
        assert attached["sessionId"] == session.id
        assert not session.agent_app_framework_pending
        assert session.agent_app_framework_key == attached["key"]
        assert len(host.agent.session_manager.sessions) == 1
        cli.run.assert_not_awaited()

    asyncio.run(check())


def test_construction_lasts_through_scaffold_and_verification_until_live_serve(fixture):
    from agent_core.core.session.todo import TodoItem

    host, _, row = fixture

    async def check():
        result = await host.workflow("create", "A notes app")
        session = host.agent.session_manager.get(result["sessionId"])
        session.todos = [TodoItem(content="Build notes", status="in_progress", active_form="Building notes")]
        assert host.build_info(session)["todos"][0]["active_form"] == "Building notes"
        assert host.scaffold_arguments(session.id, [result["path"], "scaffold"]) == [result["path"], "scaffold"]
        row.update(path=result["path"], status="stopped")
        await host.attach(row["path"], row["id"], session.id)
        assert not session.agent_app_framework_pending
        assert host.build_info(session)["building"]
        host.store.put("verification", str(Path(row["path"]).resolve()), {"verdict": "pass"})
        assert host.build_info(session)["building"]  # A verdict is not serving.
        row["status"] = "running"
        await host.attach(row["path"], row["id"], session.id)
        assert host.build_info(session) is None
        row["status"] = "stopped"
        await host.attach(row["path"], row["id"], session.id)
        assert host.build_info(session) is None  # Stop never starts construction again.

    asyncio.run(check())


@pytest.mark.parametrize("existing_empty_chat", [False, True])
def test_rescaffold_keeps_the_builder_when_reopening_and_restoring(fixture, existing_empty_chat):
    host, cli, row = fixture

    async def check():
        created = await host.workflow("create", "A todo app", creation={"name": "Todo list", "authMode": "none"})
        builder = host.agent.session_manager.get(created["sessionId"])
        builder.workspace_dir = "/history/original-builder"
        builder.total_input_tokens = 1234
        row.update(path=created["path"], status="stopped")
        # Opening the row can race the scaffold command's attachment callback.
        original = await host.attach(row["path"], row["id"])
        assert original["sessionId"] == builder.id
        host.store.put("attachment", original["key"], {**original, "tasksAllowed": True})
        row["id"] = "new-scaffold-id"
        if existing_empty_chat:
            # Reproduce the broken state already saved by the previous code.
            key = framework_host.app_key(cli.home, row["path"], row["id"])
            empty = host.agent.session_manager.create_session(
                session_type=SessionType.AGENT_APP, agent_app_framework_key=key,
            )
            host.store.put("attachment", key, {
                **original, "key": key, "appId": row["id"], "sessionId": empty.id,
            })
        attached = await host.attach(row["path"], row["id"])
        assert attached["sessionId"] == builder.id
        assert builder.agent_app_framework_key == attached["key"]
        assert host.build_info(builder)["building"]
        assert not attached.get("tasksAllowed")  # A new identity gets no old permissions.
        assert host.store.get("conversation", builder.id)["appId"] == row["id"]
        assert not host.store.get("attachment", original["key"])
        # Reload the persisted session and receipts as a restart would.
        restored = Session.from_dict(host.agent.session_manager.persisted[-1])
        host.agent.session_manager.sessions[builder.id] = restored
        host.store = HostStore(host.store.path)
        assert (await host.attach(row["path"], row["id"]))["sessionId"] == builder.id
        assert restored.workspace_dir == "/history/original-builder"
        assert restored.total_input_tokens == 1234
        assert host.build_info(restored)["building"]
        row["status"] = "running"
        await host.attach(row["path"], row["id"])
        assert host.build_info(restored) is None

    asyncio.run(check())


@pytest.mark.parametrize("change", ["completed", "different-path", "different-profile"])
def test_only_an_unfinished_creation_at_its_allocated_destination_can_rebind(fixture, change):
    host, cli, row = fixture

    async def check():
        created = await host.workflow("create", "A todo app")
        row.update(path=created["path"], status="stopped")
        original = await host.attach(row["path"], row["id"], created["sessionId"])
        builder = host.agent.session_manager.get(created["sessionId"])
        if change == "completed":
            row["status"] = "running"
            await host.attach(row["path"], row["id"])
            row["status"] = "stopped"
        elif change == "different-path":
            row["path"] += "-other"
        else:
            cli.home = cli.home / "other-profile"
        row["id"] = "replacement"
        attached = await host.attach(row["path"], row["id"], builder.id)
        assert attached["sessionId"] != builder.id
        assert builder.agent_app_framework_key == original["key"]

    asyncio.run(check())


@pytest.mark.parametrize("running", [False, True])
def test_startup_repairs_a_replaced_creation_before_finishing_its_build(fixture, monkeypatch, running):
    host, cli, row = fixture

    async def check():
        created = await host.workflow("create", "Todo")
        row.update(path=created["path"], status="stopped")
        original = await host.attach(row["path"], row["id"], created["sessionId"])
        row.update(id="replacement", status="running" if running else "stopped")
        key = framework_host.app_key(cli.home, row["path"], row["id"])
        empty = host.agent.session_manager.create_session(session_type=SessionType.AGENT_APP, agent_app_framework_key=key)
        host.store.put("attachment", key, {**original, "key": key, "appId": row["id"], "sessionId": empty.id})
        monkeypatch.setattr(host.bridge, "restore", AsyncMock())
        monkeypatch.setattr(host.maintenance, "start", lambda: None)
        await host.startup()
        assert host.store.get("attachment", key)["sessionId"] == created["sessionId"]
        builder = host.agent.session_manager.get(created["sessionId"])
        assert builder.agent_app_framework_key == key
        assert bool(host.build_info(builder)) is not running
        assert host.agent.session_manager.get(empty.id) is empty  # No chats are deleted.

    asyncio.run(check())


def test_framework_build_todos_use_the_existing_feed_without_a_legacy_project(monkeypatch):
    from app.agent_app import broadcast

    sent = []
    monkeypatch.setattr(broadcast, "_dispatch_todos", lambda key, todos: sent.append((key, todos)))
    session = Session(id="builder", type=SessionType.AGENT_APP, agent_app_framework_pending=True)
    todos = [{"id": "one", "content": "Build", "status": "in_progress"}]
    hook = broadcast.make_todo_broadcast_hook()
    hook(session, todos)
    session.agent_app_framework_pending = False
    session.agent_app_framework_key = "registered"
    hook(session, todos)
    assert sent == [("framework-build:builder", todos)] * 2


@pytest.mark.parametrize("running,passed,gate,explicit,building", [
    (False, False, False, None, True),
    (False, True, True, None, True),
    (False, True, False, None, False),
    (False, True, False, True, True),
    (True, False, False, True, False),
])
def test_startup_restores_construction_without_rebuilding_completed_apps(fixture, monkeypatch, running, passed, gate, explicit, building):
    host, cli, row = fixture
    row["status"] = "running" if running else "stopped"

    async def check():
        attached = await host.attach(row["path"], row["id"])
        creation = {"path": row["path"], "name": row["name"]}
        if explicit is not None:
            creation["building"] = explicit
        host.store.put("creation", attached["sessionId"], creation)
        if passed:
            host.store.put("verification", str(Path(row["path"]).resolve()), {"verdict": "pass"})
        if gate:
            stamp = Path(row["path"], ".a2app", "gate-pass.json")
            stamp.parent.mkdir()
            stamp.write_text('{"fingerprint":"candidate"}')
        monkeypatch.setattr(host.bridge, "restore", AsyncMock())
        monkeypatch.setattr(host.maintenance, "start", lambda: None)
        await host.startup()
        assert host.store.get("creation", attached["sessionId"])["building"] is building

    asyncio.run(check())


def test_startup_moves_recorded_pending_builds_without_reclassifying_unrelated_chats(fixture, monkeypatch):
    host, cli, row = fixture
    builder = host.agent.session_manager.create_session(title="Agent App: create")
    unrelated = host.agent.session_manager.create_session(title="Agent App: create")
    host.store.put("conversation", builder.id, {"path": row["path"], "home": str(cli.home), "appId": None, "sessionId": builder.id})
    host.store.put("creation", builder.id, {"name": "My app", "path": row["path"]})
    monkeypatch.setattr(host.bridge, "restore", AsyncMock())
    monkeypatch.setattr(host.maintenance, "start", lambda: None)
    asyncio.run(host.startup())
    assert builder.type == SessionType.AGENT_APP and builder.agent_app_framework_pending
    assert builder.title == "My app"
    assert unrelated.type == SessionType.CHAT


def test_creation_workflow_becomes_app_chat_but_another_app_cannot_adopt_it(fixture):
    host, cli, row = fixture
    builder = host.agent.session_manager.create_session(title="Agent App: create")
    host.store.put("conversation", builder.id, {"path": row["path"], "home": str(cli.home), "appId": None})

    async def check():
        attached = await host.attach(row["path"], row["id"], builder.id)
        assert attached["sessionId"] == builder.id
        assert builder.type == SessionType.AGENT_APP
        first_key = attached["key"]
        row["id"] = "replacement-id"
        replacement = await host.attach(row["path"], row["id"], builder.id)
        assert replacement["sessionId"] != builder.id
        assert builder.agent_app_framework_key == first_key

    asyncio.run(check())


@pytest.mark.parametrize(
    "args,expected",
    [
        (["stop"], "stop"),
        (["serve"], "start"),
        (["stop", "--dev"], None),
        (["stop", "--help"], None),
        (["serve", "-h"], None),
        (["promote", "--help"], None),
    ],
)
def test_development_stop_and_help_do_not_change_live_task_authority(
    fixture, monkeypatch, args, expected
):
    host, cli, row = fixture
    cli.run.return_value = CLIResult(0, '{"ok":true}', "")
    monkeypatch.setattr(
        framework,
        "_list_apps",
        AsyncMock(return_value={"status": "success", "data": {"apps": [row]}}),
    )
    host.bridge.lifecycle_changed = AsyncMock()

    async def check():
        result = await command("agent-app", [row["path"], *args])
        assert result["status"] == "success"
        if expected:
            host.bridge.lifecycle_changed.assert_awaited_once_with(
                row["path"], row["id"], expected
            )
        else:
            host.bridge.lifecycle_changed.assert_not_awaited()
        if "--help" in args or "-h" in args:
            assert not host.store.all("attachment")

    asyncio.run(check())


def test_startup_respects_preferences_and_restores_tasks_without_browser(
    fixture, monkeypatch
):
    host, cli, row = fixture
    start = AsyncMock(return_value={"status": "success"})
    monkeypatch.setattr(framework, "change_app_state", start)
    host.bridge.restore = AsyncMock()

    async def check():
        attachment = await host.request(
            {
                "operation": "preference",
                "path": row["path"],
                "appId": row["id"],
                "autoStart": True,
            }
        )
        row["status"] = "stopped"
        await host.startup()
        start.assert_awaited_once_with(row["path"], row["id"], "start")
        host.bridge.restore.assert_awaited_once()
        assert not host.agent.trigger_service.emit.called
        start.side_effect = RuntimeError("port unavailable")
        await host.startup()
        assert (
            "port unavailable"
            in host.store.get("attachment", attachment["key"])["startError"]
        )
        await host.request(
            {
                "operation": "preference",
                "path": row["path"],
                "appId": row["id"],
                "autoStart": False,
            }
        )
        start.reset_mock()
        await host.startup()
        start.assert_not_called()

    asyncio.run(check())


def test_ui_verification_queues_subagent_work_in_existing_app_conversation(fixture):
    host, _, row = fixture
    Path(row["path"], ".a2app").mkdir()
    stamp_path = Path(row["path"], ".a2app", "gate-pass.json")
    stamp_path.write_text(
        '{"fingerprint":"candidate", "budgetChecked":true, "at":"now"}'
    )

    async def check():
        attached = await host.attach(row["path"], row["id"])
        result = await host.workflow(
            "verify", "Verify requirements", row["path"], row["id"]
        )
        assert result["sessionId"] == attached["sessionId"]
        assert result["queued"] is True
        assert len(host.agent.session_manager.sessions) == 1
        spec = host.agent.trigger_service.emit.await_args.args[0]
        assert spec.session_id == attached["sessionId"]
        assert spec.payload["workflow_skills"] == []
        assert "independent subagent" in spec.description
        assert "agent_app_framework_workflow" in spec.description
        with pytest.raises(PermissionError):
            host.report_verification(
                attached["sessionId"], "pass", "builder claims pass"
            )
        with pytest.raises(ValueError):
            host.require_verified(row["path"])

    asyncio.run(check())


def test_verification_without_a_valid_candidate_leaves_no_session(fixture):
    host, _, row = fixture

    async def check():
        with pytest.raises(ValueError, match="Validate"):
            await host.workflow("verify", "Verify", row["path"], row["id"])
        assert not host.agent.session_manager.sessions
        host.agent.trigger_service.emit.assert_not_awaited()

    asyncio.run(check())


def test_verifier_commands_do_not_replace_the_builders_chat(fixture, monkeypatch):
    from agent_core.core.state.session import StateSession

    host, cli, row = fixture

    async def check():
        attached = await host.attach(row["path"], row["id"])
        verifier = host.agent.session_manager.create_session(title="Verifier")
        host.store.put("verification_session", verifier.id, {"path": row["path"]})
        monkeypatch.setattr(
            StateSession, "bound", lambda: SimpleNamespace(session_id=verifier.id)
        )
        monkeypatch.setattr(
            framework, "_list_apps", AsyncMock(return_value={"data": {"apps": [row]}})
        )
        cli.run.return_value = CLIResult(0, '{"ok":true}', "")
        await command("agent-app", [row["path"], "dev"])
        assert (
            host.store.get("attachment", attached["key"])["sessionId"]
            == attached["sessionId"]
        )

    asyncio.run(check())


def test_install_streams_persists_and_deduplicates_without_agent_calls(fixture):
    host, cli, row = fixture

    async def run(surface, args, **kwargs):
        assert surface == "agent-app" and args == ["install", "board", "--events"]
        kwargs["on_stdout_line"](
            json.dumps({"event": "step", "step": "acquire", "status": "done"})
        )
        assert host.store.get("install", "job")["steps"][0]["step"] == "acquire"
        kwargs["on_stdout_line"](
            json.dumps(
                {
                    "event": "result",
                    "ok": True,
                    "id": row["id"],
                    "dir": row["path"],
                    "served": True,
                }
            )
        )
        return CLIResult(0, "", "")

    cli.run.side_effect = run

    async def check():
        await host.start_install({"id": "board"}, "job")
        await host.jobs["job"]
        result = await host.start_install({"id": "board"}, "job")
        assert result["status"] == "success" and result["sessionId"]
        assert cli.run.await_count == 1
        host.agent.trigger_service.emit.assert_not_awaited()
        with pytest.raises(ValueError):
            await host.start_install({"id": "different"}, "job")

    asyncio.run(check())


def test_interrupted_installs_are_not_replayed(fixture):
    host, cli, _ = fixture
    host.store.put("install", "unfinished", {"id": "unfinished", "status": "running"})
    FrameworkHost(host.agent, host.changed, host.store)
    assert host.store.get("install", "unfinished")["status"] == "interrupted"
    cli.run.assert_not_called()


def test_task_authority_cannot_change_surface_or_target(fixture):
    _, cli, _ = fixture

    async def check():
        authority = TaskAuthority(
            "http://127.0.0.1:8123", "task", "secret", check=AsyncMock()
        )
        marker = task_authority.set(authority)
        try:
            for surface, args in [
                ("agent-app", ["list"]),
                ("a2app", ["/another/app"]),
                ("a2app", [authority.target, "login"]),
                ("a2app", [authority.target, "logout"]),
                ("a2app", [authority.target, "credential"]),
            ]:
                with pytest.raises(PermissionError):
                    await command(surface, args)
            cli.run.assert_not_called()
            cli.run.return_value = CLIResult(0, "module screen", "")
            result = await command("a2app", [authority.target, "promote"])
            assert result["stdout"] == "module screen"
            assert cli.run.await_args.args[0] == "a2app"
            assert cli.run.await_args.kwargs["env_extra"] == {"A2APP_TOKEN": "secret"}
            cli.run.return_value = CLIResult(0, '{"a2app":true,"view":"notes","selected":[]}', "")
            result = await command("a2app", [authority.target, "context"])
            assert result["data"]["view"] == "notes"
            assert cli.run.await_args.args[1] == [authority.target, "context"]
            assert cli.run.await_args.kwargs["env_extra"] == {"A2APP_TOKEN": "secret"}
            assert authority.check.await_count == 2
            authority.active = False
            with pytest.raises(PermissionError):
                await command("a2app", [authority.target])
        finally:
            task_authority.reset(marker)
        assert task_authority.get() is None and "secret" not in repr(authority)

    asyncio.run(check())


@pytest.mark.parametrize("confirm", [None, "another-app"])
def test_sidebar_remove_requires_confirmation_before_stopping(
    fixture, monkeypatch, confirm
):
    host, cli, row = fixture
    stop = AsyncMock()
    monkeypatch.setattr(framework, "change_app_state", stop)

    async def check():
        with pytest.raises(ValueError, match="Confirm"):
            await host.request(
                {
                    "operation": "manage",
                    "verb": "remove",
                    "path": row["path"],
                    "appId": row["id"],
                    "confirm": confirm,
                    "stopFirst": True,
                }
            )
        stop.assert_not_awaited()
        cli.run.assert_not_awaited()

    asyncio.run(check())


@pytest.mark.parametrize("status", ["running", "stopped"])
def test_sidebar_remove_uses_upstream_and_retires_startup_and_task_grants(
    fixture, monkeypatch, status
):
    host, cli, row = fixture
    row["status"] = status
    events = []

    async def stop(*args):
        events.append("stop")
        assert args == (row["path"], row["id"], "stop")
        row["status"] = "stopped"
        return {"status": "success"}

    async def invoke(surface, args, **kwargs):
        assert surface == "agent-app"
        if args == ["list", "--json"]:
            return CLIResult(0, '{"ok":true,"apps":[],"connected":[]}', "")
        if args == [row["path"], "stop", "--dev"]:
            events.append("stop dev")
            return CLIResult(0, '{"ok":true,"stopped":null}', "")
        events.append("remove")
        assert args == [row["path"], "remove", "--yes"]
        return CLIResult(
            0,
            json.dumps({"ok": True, "removed": {"id": row["id"], "path": row["path"]}}),
            "data archived",
        )

    monkeypatch.setattr(framework, "change_app_state", stop)
    cli.run.side_effect = invoke

    async def check():
        attachment = await host.attach(row["path"], row["id"])
        attachment.update(autoStart=True, tasksAllowed=True, ownerToolsAllowed=True)
        host.store.put("attachment", attachment["key"], attachment)
        result = await host.request(
            {
                "operation": "manage",
                "verb": "remove",
                "path": row["path"],
                "appId": row["id"],
                "confirm": row["id"],
                "stopFirst": True,
            }
        )
        assert result["status"] == "success"
        assert "host_warning" not in result
        assert events == ["stop", "stop dev", "remove"]
        host.maintenance.before_remove.assert_awaited_once_with(row["path"], row["id"])
        retained = host.store.get("attachment", attachment["key"])
        assert (
            not retained["autoStart"]
            and not retained["tasksAllowed"]
            and not retained["ownerToolsAllowed"]
        )
        assert retained["sessionId"] in host.agent.session_manager.sessions
        host.agent.trigger_service.emit.assert_not_awaited()

    asyncio.run(check())


@pytest.mark.parametrize("failure", ["stop", "identity", "backup", "dev", "remove"])
def test_sidebar_remove_keeps_grants_and_never_removes_after_failed_stop_or_identity_change(
    fixture, monkeypatch, failure
):
    host, cli, row = fixture

    async def stop(*_args):
        if failure == "stop":
            return {"status": "error", "message": "Still running"}
        if failure == "identity":
            row["id"] = "replacement"
        return {"status": "success"}

    monkeypatch.setattr(framework, "change_app_state", stop)
    async def invoke(surface, args, **kwargs):
        if args == [row["path"], "stop", "--dev"]:
            return CLIResult(1, '{"ok":false}', "Dev still running") if failure == "dev" else CLIResult(0, '{"ok":true,"stopped":null}', "")
        if args == ["list", "--json"]:
            return CLIResult(0, '{"ok":true,"apps":[],"connected":[]}', "")
        return CLIResult(1, '{"ok":false}', "Could not archive data")

    cli.run.side_effect = invoke
    if failure == "backup":
        host.maintenance.before_remove.side_effect = RuntimeError(
            "Could not archive data"
        )

    async def check():
        attachment = await host.attach(row["path"], row["id"])
        attachment.update(autoStart=True, tasksAllowed=True)
        host.store.put("attachment", attachment["key"], attachment)
        request = {
            "operation": "manage",
            "verb": "remove",
            "path": row["path"],
            "appId": "app",
            "confirm": "app",
            "stopFirst": True,
        }
        if failure == "remove":
            assert (await host.request(request))["status"] == "error"
        else:
            with pytest.raises((RuntimeError, ValueError)):
                await host.request(request)
            if failure == "dev":
                assert cli.run.await_args_list[0].args == ("agent-app", [row["path"], "stop", "--dev"])
                assert all(call.args[1] != [row["path"], "remove", "--yes"] for call in cli.run.await_args_list)
            else:
                cli.run.assert_not_awaited()
        assert host.store.get("attachment", attachment["key"])["tasksAllowed"]
        assert host.store.get("attachment", attachment["key"])["autoStart"]

    asyncio.run(check())


def test_forget_missing_app_uses_registry_only_command_and_clears_preferences(fixture):
    host, cli, row = fixture

    async def check():
        attachment = await host.attach(row["path"], row["id"])
        attachment.update(
            autoStart=True,
            tasksAllowed=True,
            backupsEnabled=True,
            maintenanceResume=True,
        )
        host.store.put("attachment", attachment["key"], attachment)
        row["status"] = "missing"
        cli.run.side_effect = [
            CLIResult(0, json.dumps({"ok": True, "forgot": row}), ""),
            CLIResult(0, '{"ok":true,"apps":[],"connected":[]}', ""),
        ]
        result = await host.request(
            {
                "operation": "manage",
                "verb": "forget",
                "path": row["path"],
                "appId": row["id"],
                "confirm": row["id"],
            }
        )
        assert result["status"] == "success"
        assert [call.args for call in cli.run.await_args_list] == [
            ("agent-app", [row["path"], "forget"]),
            ("agent-app", ["list", "--json"]),
        ]
        assert "host_warning" not in result
        # The command only removes a registry entry; existing files are untouched.
        assert Path(row["path"], "manifest.json").exists()
        retained = host.store.get("attachment", attachment["key"])
        assert not any(
            retained[name] for name in ("autoStart", "tasksAllowed", "backupsEnabled")
        )
        assert "maintenanceResume" not in retained

    asyncio.run(check())


@pytest.mark.parametrize(
    "status,confirm",
    [("missing", None), ("missing", "other"), ("stopped", "app"), ("running", "app")],
)
def test_forget_requires_current_missing_identity_and_confirmation(
    fixture, status, confirm
):
    host, cli, row = fixture
    row["status"] = status

    async def check():
        with pytest.raises(ValueError, match="Confirm"):
            await host.request(
                {
                    "operation": "manage",
                    "verb": "forget",
                    "path": row["path"],
                    "appId": row["id"],
                    "confirm": confirm,
                }
            )
        cli.run.assert_not_awaited()

    asyncio.run(check())


def test_forget_existing_app_requires_keep_files_and_uses_no_force(
    fixture, monkeypatch
):
    host, cli, row = fixture
    row["status"] = "stopped"
    stop = AsyncMock(return_value={"status": "success"})
    monkeypatch.setattr(framework, "change_app_state", stop)
    cli.run.side_effect = [
        CLIResult(0, json.dumps({"ok": True, "forgot": row}), ""),
        CLIResult(0, '{"ok":true,"apps":[],"connected":[]}', ""),
    ]

    async def check():
        result = await host.request(
            {
                "operation": "manage",
                "verb": "forget",
                "path": row["path"],
                "appId": row["id"],
                "confirm": row["id"],
                "keepFiles": True,
                "stopFirst": True,
            }
        )
        assert result["status"] == "success"
        stop.assert_awaited_once_with(row["path"], row["id"], "stop")
        assert cli.run.await_args_list[0].args == ("agent-app", [row["path"], "forget"])
        host.maintenance.before_remove.assert_not_awaited()
        assert Path(row["path"], "manifest.json").exists()

    asyncio.run(check())
