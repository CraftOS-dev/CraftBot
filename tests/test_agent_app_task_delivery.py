"""How CraftBot works the requests an Agent App sends it (framework_bridge.py)."""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent_app import framework_commands
from app.agent_app.framework_bridge import FrameworkBridge, operator_documents
from app.agent_app.framework_cli import AgentAppCLI, CLIResult
from app.agent_app.framework_commands import TaskAuthority
from app.agent_app.framework_store import HostStore


def _authority(confined):
    authority = TaskAuthority("http://127.0.0.1:3115", "tsk_1", "task-token", app_id="app")
    authority.confined = confined

    async def check():
        return {}

    authority.check = check
    return authority


def _commands(monkeypatch):
    """Record which CLI each command reaches: the chat's own, or the task's."""
    calls = []

    class ChatCLI:
        package_dir = Path(".")

        async def run(self, surface, args, *, cwd, timeout, env_extra=None):
            calls.append(("chat", surface, list(args), dict(env_extra or {})))
            return CLIResult(0, "{}", "")

    async def task_run(self, surface, args, *, cwd, timeout, env_extra=None):
        calls.append(("task", surface, list(args), dict(env_extra or {})))
        return CLIResult(0, "{}", "")

    monkeypatch.setattr("app.agent_app.framework.configured_cli", lambda: ChatCLI())
    monkeypatch.setattr(AgentAppCLI, "run", task_run)
    return calls


def _as(authority, surface, args):
    async def go():
        marker = framework_commands.task_authority.set(authority)
        try:
            return await framework_commands.command(surface, args)
        finally:
            framework_commands.task_authority.reset(marker)

    return asyncio.run(go())


def test_the_owners_own_request_runs_other_commands_as_the_chat_would(monkeypatch):
    calls = _commands(monkeypatch)
    authority = _authority(confined=False)
    _as(authority, "agent-app", ["list", "--json"])
    _as(authority, "a2app", ["http://127.0.0.1:3110", "todo"])
    _as(authority, "a2app", ["http://127.0.0.1:3115", "brief"])
    assert [(c[0], c[1]) for c in calls] == [("chat", "agent-app"), ("chat", "a2app"), ("task", "a2app")]
    assert "A2APP_TOKEN" not in calls[0][3] and "A2APP_TOKEN" not in calls[1][3]
    assert calls[2][3]["A2APP_TOKEN"] == "task-token"  # its own app, with its credential
    # On its own app the task's rules still hold.
    with pytest.raises(PermissionError):
        _as(authority, "a2app", ["http://127.0.0.1:3115", "tasks", "complete", "tsk_other"])


def test_another_persons_request_stays_on_its_own_app(monkeypatch):
    calls = _commands(monkeypatch)
    authority = _authority(confined=True)
    for surface, args in (("agent-app", ["list", "--json"]), ("a2app", ["http://127.0.0.1:3110", "todo"])):
        with pytest.raises(PermissionError):
            _as(authority, surface, args)
    assert calls == []


def _gate(monkeypatch, authority, names):
    """Run the action gate; report whether the batch got past it."""
    from app import agent_base

    class Passed(Exception):
        pass

    def passed(_payload):
        raise Passed

    monkeypatch.setattr("app.telegram_feedback.owner_permission_error", passed)
    logged = []
    agent = agent_base.AgentBase.__new__(agent_base.AgentBase)
    agent.session_manager = SimpleNamespace(get=lambda sid: None)
    agent.event_stream_manager = SimpleNamespace(log=lambda **event: logged.append(event))
    batch = [(SimpleNamespace(name=n), {"file_path": "C:/secrets.txt"}) for n in names]
    trigger = SimpleNamespace(payload={}, is_self_message=False, query="")

    async def go():
        marker = framework_commands.task_authority.set(authority)
        try:
            return await agent._execute_actions(batch, trigger, "", "chat")
        finally:
            framework_commands.task_authority.reset(marker)

    try:
        result = asyncio.run(go())
    except Passed:
        return "passed", logged
    return result, logged


def test_the_owners_own_request_has_the_usual_tools(monkeypatch):
    outcome, logged = _gate(monkeypatch, _authority(confined=False), ["web_search", "read_file", "run_shell"])
    assert outcome == "passed" and logged == []


def test_a_confined_request_is_told_why_an_action_is_refused(monkeypatch):
    result, logged = _gate(monkeypatch, _authority(confined=True), ["web_search"])
    assert result["status"] == "error" and "web_search is not available" in result["message"]
    assert logged and logged[0]["kind"] == "action_error" and logged[0]["action_name"] == "web_search"


def _bridge(tmp_path):
    emitted = []

    async def emit(spec):
        emitted.append(spec)

    async def changed():
        pass

    host = SimpleNamespace(
        store=HostStore(tmp_path / "host.sqlite3"),
        closing=False,
        changed=changed,
        agent=SimpleNamespace(trigger_service=SimpleNamespace(emit=emit)),
    )
    bridge = FrameworkBridge(host)

    async def check(run):
        return {}

    bridge.check = check
    return bridge, emitted


def _run(bridge, key, session="chat", queued=False):
    run = {
        "key": key,
        "sessionId": session,
        "taskId": "tsk_" + key,
        "grantKey": "grant",
        "status": "working",
        "authority": TaskAuthority("http://127.0.0.1:3115", "tsk_" + key, "token", app_id="app"),
        "prompt": f"work {key}",
        "queued": queued,
    }
    bridge.runs[key] = run
    if queued:
        bridge.waiting.setdefault(session, []).append(key)
    return run


def test_a_second_request_waits_until_the_first_is_done(tmp_path):
    bridge, emitted = _bridge(tmp_path)
    first = _run(bridge, "a")
    second = _run(bridge, "b", queued=True)

    asyncio.run(bridge._advance("chat"))
    assert emitted == [] and second["queued"]

    first["authority"].active = False  # the agent completed its task
    asyncio.run(bridge._advance("chat"))
    assert [spec.description for spec in emitted] == ["work b"]
    assert emitted[0].payload["framework_task_key"] == "b"
    assert second["queued"] is False
    assert bridge.waiting == {}


def test_requests_in_other_conversations_do_not_wait(tmp_path):
    bridge, emitted = _bridge(tmp_path)
    _run(bridge, "a", session="one")
    _run(bridge, "b", session="two", queued=True)
    asyncio.run(bridge._advance("two"))
    assert [spec.description for spec in emitted] == ["work b"]


def test_a_request_that_ends_badly_frees_its_conversation(tmp_path):
    bridge, emitted = _bridge(tmp_path)
    first = _run(bridge, "a")
    _run(bridge, "b", queued=True)
    asyncio.run(bridge.terminate(first, "claim_lost", settle=False, cancel=False))
    assert [spec.description for spec in emitted] == ["work b"]


def test_stopping_the_conversation_starts_nothing_else(tmp_path):
    bridge, emitted = _bridge(tmp_path)
    first = _run(bridge, "a")
    _run(bridge, "b", queued=True)
    asyncio.run(bridge.terminate(first, "user_stopped", settle=False, cancel=False))
    assert emitted == []


def test_a_waiting_request_that_lost_its_claim_is_passed_over(tmp_path):
    bridge, emitted = _bridge(tmp_path)
    lost = _run(bridge, "b", queued=True)
    _run(bridge, "c", queued=True)

    async def check(run):
        if run is lost:
            raise PermissionError("This task is no longer held by this run.")
        return {}

    bridge.check = check
    asyncio.run(bridge._advance("chat"))
    assert [spec.description for spec in emitted] == ["work c"]
    assert lost["authority"].active is False


def test_a_task_run_reads_only_the_apps_operator_documents(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    for name in ("AGENT_APP.md", "manifest.json", "operations.json", ".agent-token", "notes.txt"):
        (app / name).write_text("x", encoding="utf-8")
    documents = operator_documents(app)
    assert set(documents) == {"AGENT_APP.md", "manifest.json", "operations.json"}

    authority = TaskAuthority("http://127.0.0.1:3115", "tsk", "token", app_id="app")
    assert authority.may_read(str(app / ".agent-token"))  # no scope: owner tools
    authority.readable = frozenset(os.path.normcase(p) for p in documents.values())
    assert authority.may_read(str(app / "AGENT_APP.md"))
    assert authority.may_read(str(app / "sub" / ".." / "manifest.json"))
    for refused in (
        str(app / ".agent-token"),
        str(app / "notes.txt"),
        "AGENT_APP.md",  # relative
        str(tmp_path / "AGENT_APP.md"),
        None,
    ):
        assert not authority.may_read(refused), refused
