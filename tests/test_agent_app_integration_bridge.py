"""Host services for the Agent Apps CraftBot launches (integration_bridge.py)."""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.agent_app import integration_bridge as bridge
from app.agent_app.framework_store import HostStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = HostStore(tmp_path / "host.sqlite3")
    monkeypatch.setattr(bridge, "_store", s)
    monkeypatch.setattr(bridge, "_url", None)
    return s


def _app(root, capabilities=None):
    root.mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps({"id": "abc", "name": "App", "capabilities": capabilities or {}}),
        encoding="utf-8",
    )
    return root


def test_a_folder_keeps_its_token_and_the_token_names_the_folder(tmp_path, store):
    one, two = _app(tmp_path / "one"), _app(tmp_path / "two")
    token = bridge.issue(one)
    assert bridge.issue(one) == token  # apps outlive CraftBot: never rotate
    assert bridge.issue(two) != token
    assert bridge.folder_of(token) == one.resolve()
    assert bridge.folder_of("not-a-token") is None
    assert bridge.folder_of("") is None


def test_an_install_token_is_bound_to_the_folder_it_reports(tmp_path, store):
    folder = _app(tmp_path / "installed")
    stdout = "\n".join(
        [
            json.dumps({"event": "step", "step": "place"}),
            json.dumps({"event": "result", "ok": True, "dir": str(folder), "id": "abc"}),
        ]
    )
    bridge.bind_installed(stdout, "install-token")
    assert bridge.folder_of("install-token") == folder.resolve()
    # The folder's own token stays the one it was given first.
    assert bridge.issue(folder) == "install-token"


def test_only_commands_that_start_an_app_carry_the_bridge(tmp_path, store):
    app = _app(tmp_path / "app")
    home = tmp_path / "home"
    home.mkdir()
    (home / "registry.json").write_text(
        json.dumps({"apps": [{"id": "abc", "path": str(app)}]}), encoding="utf-8"
    )
    # No bridge is serving: nothing is handed out.
    assert bridge.launch_env([str(app), "serve"], home) == ({}, None)

    bridge.configure(7926)
    env, pending = bridge.launch_env([str(app), "serve"], home)
    assert env["CRAFTBOT_BRIDGE_URL"] == "http://127.0.0.1:7926"
    assert bridge.folder_of(env["CRAFTBOT_BRIDGE_TOKEN"]) == app.resolve()
    assert pending is None
    assert bridge.launch_env([str(app), "dev"], home)[0] == env
    assert bridge.launch_env(["abc", "serve"], home)[0] == env  # by registry id
    assert bridge.launch_env([str(app), "import"], home)[0] == env
    assert bridge.launch_env(["install", "--from", "x", "--into", str(app)], home)[0] == env

    env, pending = bridge.launch_env(["install", "kanban-board"], home)
    assert env["CRAFTBOT_BRIDGE_TOKEN"] == pending

    for argv in (
        [str(app), "validate"],
        [str(app), "stop"],
        [str(app), "import", "--no-start"],
        ["install", "kanban-board", "--no-start"],
        ["list", "--json"],
        ["unknown-id", "serve"],
        ["relative/path", "serve"],
    ):
        assert bridge.launch_env(argv, home) == ({}, None), argv


def test_the_cli_passes_the_bridge_to_a_launch_only(tmp_path, store, monkeypatch):
    from app import node_runtime
    from app.agent_app.framework_cli import AgentAppCLI

    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/agent-app.js").touch()
    monkeypatch.setattr(
        node_runtime, "resolve", lambda: SimpleNamespace(node=sys.executable, version="v24.0.0")
    )
    monkeypatch.setattr(node_runtime, "child_env", lambda: {})
    monkeypatch.setattr("app.config.get_framework_toolkits_dir", lambda: "toolkits")
    cli = AgentAppCLI(tmp_path, home=tmp_path / "home")
    app = _app(tmp_path / "app")
    bridge.configure(7926)
    seen = []

    class Stop(Exception):
        pass

    def prepare(surface, extra, new_app=False):
        seen.append(dict(extra))
        raise Stop

    monkeypatch.setattr(cli, "_prepare", prepare)
    for args in ([str(app), "serve"], [str(app), "validate"]):
        with pytest.raises(Stop):
            asyncio.run(cli.run("agent-app", args, cwd=tmp_path))
    assert bridge.folder_of(seen[0]["CRAFTBOT_BRIDGE_TOKEN"]) == app.resolve()
    assert "CRAFTBOT_BRIDGE_TOKEN" not in seen[1]


def test_destinations_stay_on_the_integrations_own_hosts():
    assert bridge.resolve_destination("stripe", "/v1/subscriptions") == (
        True,
        "https://api.stripe.com/v1/subscriptions",
    )
    assert bridge.resolve_destination("github", "https://api.github.com/repos/a/b")[0]
    for integration, url in (
        ("github", "https://api.github.com.evil.com/x"),
        ("github", "//evil.com/x"),
        ("github", "http://api.github.com/x"),
        ("unknown", "/x"),
        ("stripe", ""),
    ):
        assert not bridge.resolve_destination(integration, url)[0], url


async def _call(store, folder, method, path, body=None, token=None):
    service = bridge.IntegrationBridge(7926)
    app = web.Application()
    service.register_routes(app)
    headers = {}
    if token is not False:
        headers["Authorization"] = f"Bearer {token or bridge.issue(folder)}"
    async with TestClient(TestServer(app)) as client:
        response = await client.request(method, path, json=body, headers=headers)
        payload = await response.json()
    await service.cleanup()
    return response.status, payload


def test_an_unknown_caller_is_refused(tmp_path, store):
    folder = _app(tmp_path / "app")
    for token in (False, "forged"):
        status, _ = asyncio.run(
            _call(store, folder, "POST", "/api/bridge/llm", {"prompt": "hi"}, token)
        )
        assert status == 401
    # A token whose folder no longer holds an app is refused too.
    token = bridge.issue(folder)
    (folder / "manifest.json").unlink()
    status, _ = asyncio.run(
        _call(store, folder, "POST", "/api/bridge/llm", {"prompt": "hi"}, token)
    )
    assert status == 401


def test_the_language_model_answers_a_launched_app(tmp_path, store, monkeypatch):
    from app.internal_action_interface import InternalActionInterface

    folder = _app(tmp_path / "app")
    asked = []

    async def use_llm(prompt, system_message=None, json_mode=False):
        asked.append((prompt, system_message, json_mode))
        return {"llm_response": '{"summary": "ok"}'}

    monkeypatch.setattr(InternalActionInterface, "use_llm", use_llm)
    status, payload = asyncio.run(
        _call(
            store,
            folder,
            "POST",
            "/api/bridge/llm",
            {"prompt": "notes", "system_message": "terse", "json_mode": True},
        )
    )
    assert (status, payload) == (200, {"content": '{"summary": "ok"}'})
    assert asked == [("notes", "terse", True)]


def _action(monkeypatch, *, sets=("google_calendar",), irreversible=False):
    from agent_core.core.action_framework.registry import ActionRegistry

    calls = []

    async def handler(params):
        calls.append(params)
        return {"status": "success", "events": []}

    impl = SimpleNamespace(
        handler=handler,
        metadata=SimpleNamespace(action_sets=list(sets), irreversible=irreversible, input_schema={}),
    )
    monkeypatch.setattr(
        ActionRegistry,
        "get_action_implementation",
        lambda self, name: impl if name == "list_google_calendar_events" else None,
    )
    return calls


def test_an_app_runs_only_the_actions_its_manifest_declares(tmp_path, store, monkeypatch):
    calls = _action(monkeypatch)
    granted = _app(tmp_path / "granted", {"actions": ["list_google_calendar_events"]})
    body = {"action": "list_google_calendar_events", "params": {"calendar_id": "primary"}}
    status, payload = asyncio.run(_call(store, granted, "POST", "/api/integrations/action", body))
    assert (status, payload["data"]) == (200, {"status": "success", "events": []})
    assert calls == [{"calendar_id": "primary"}]

    other = _app(tmp_path / "other")
    status, _ = asyncio.run(_call(store, other, "POST", "/api/integrations/action", body))
    assert status == 403
    status, _ = asyncio.run(
        _call(store, granted, "POST", "/api/integrations/action", {"action": "nope", "params": {}})
    )
    assert status == 404
    assert len(calls) == 1


def test_an_irreversible_action_needs_its_confirmation(tmp_path, store, monkeypatch):
    calls = _action(monkeypatch, irreversible=True)
    folder = _app(tmp_path / "app", {"actions": ["list_google_calendar_events"]})
    body = {"action": "list_google_calendar_events", "params": {}}
    status, _ = asyncio.run(_call(store, folder, "POST", "/api/integrations/action", body))
    assert status == 400 and calls == []
    status, _ = asyncio.run(
        _call(store, folder, "POST", "/api/integrations/action", {**body, "confirm_irreversible": True})
    )
    assert status == 200 and len(calls) == 1


def test_a_non_integration_action_is_never_reachable(tmp_path, store, monkeypatch):
    calls = _action(monkeypatch, sets=("file_operations",))
    folder = _app(tmp_path / "app", {"actions": ["list_google_calendar_events"]})
    body = {"action": "list_google_calendar_events", "params": {}}
    status, _ = asyncio.run(_call(store, folder, "POST", "/api/integrations/action", body))
    assert status == 403 and calls == []


def test_a_request_needs_the_integration_declared(tmp_path, store, monkeypatch):
    monkeypatch.setattr(bridge, "_auth_headers", lambda platform, account: pytest.fail("no credentials may be read"))
    folder = _app(tmp_path / "app", {"integrations": ["github"]})
    body = {"integration": "stripe", "method": "GET", "url": "/v1/subscriptions"}
    status, _ = asyncio.run(_call(store, folder, "POST", "/api/integrations/proxy", body))
    assert status == 403
    body = {"integration": "github", "method": "GET", "url": "https://evil.example/x"}
    status, _ = asyncio.run(_call(store, folder, "POST", "/api/integrations/proxy", body))
    assert status == 403
