"""CraftBot lifecycle binding; all real apps and framework profiles are disposable."""

import asyncio
import hashlib
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.agent_app import framework
from app.agent_app.framework_cli import CLIResult
from app.ui_layer.adapters.browser_adapter import BrowserAdapter


def document(data, code=0, stderr=""):
    return CLIResult(code, json.dumps(data), stderr)


def snapshot(path, status="stopped", **extra):
    return {
        "ok": True,
        "apps": [
            {
                "path": path,
                "id": "same-id",
                "name": "Fixture",
                "status": status,
                **extra,
            }
        ],
        "connected": [],
    }


@pytest.fixture
def cli(tmp_path, monkeypatch):
    client = SimpleNamespace(package_dir=tmp_path, run=AsyncMock())
    monkeypatch.setattr(framework, "configured_cli", lambda: client)
    return client, str(tmp_path / "app with spaces")


@pytest.mark.parametrize(
    "operation,command,status",
    [("start", "serve", "running"), ("stop", "stop", "stopped")],
)
def test_literal_cli_mapping_and_observed_state(cli, operation, command, status):
    client, path = cli
    client.run.side_effect = [
        document(snapshot(path)),
        document({"ok": True, "id": "same-id"}, stderr="Upstream diagnostic"),
        document(snapshot(path, status)),
    ]
    result = asyncio.run(framework.change_app_state(path, "same-id", operation))
    assert result["status"] == "success"
    assert result["stderr"] == "Upstream diagnostic"
    assert result["registry"]["data"]["apps"][0]["status"] == status
    assert [call.args for call in client.run.await_args_list] == [
        ("agent-app", ["list", "--json"]),
        ("agent-app", [path, command]),
        ("agent-app", ["list", "--json"]),
    ]
    assert client.run.await_args_list[1].kwargs["timeout"] == (
        660 if operation == "start" else 30
    )


@pytest.mark.parametrize(
    "change",
    [
        {"id": "replacement"},
        {"path": "/unregistered"},
        {"status": "missing"},
        {"status": "unreachable"},
    ],
)
def test_stale_or_unavailable_selection_cannot_run_lifecycle(cli, change):
    client, path = cli
    data = snapshot(path)
    data["apps"][0].update(change)
    client.run.side_effect = [document(data)]
    assert (
        asyncio.run(framework.change_app_state(path, "same-id", "start"))["status"]
        == "error"
    )
    assert client.run.await_count == 1


@pytest.mark.parametrize(
    "command_result,code",
    [
        (document({"ok": False}, 1, "system-managed files changed"), "command_failed"),
        (CLIResult(124, "", "timeout", timed_out=True), "uncertain"),
        (CLIResult(0, "not JSON", ""), "command_failed"),
        (document({"ok": True, "id": "replacement"}), "identity_changed"),
    ],
)
def test_failed_or_ambiguous_start_is_never_reported_as_success(
    cli, command_result, code
):
    client, path = cli
    client.run.side_effect = [
        document(snapshot(path)),
        command_result,
        document(snapshot(path, "running")),
    ]
    result = asyncio.run(framework.change_app_state(path, "same-id", "start"))
    assert result["code"] == code
    assert result["registry"]["data"]["apps"][0]["status"] == "running"


def test_stop_without_a_record_cannot_claim_a_running_app_stopped(cli):
    client, path = cli
    client.run.side_effect = [
        document(snapshot(path, "running")),
        document({"ok": True, "stopped": None}),
        document(snapshot(path, "running")),
    ]
    result = asyncio.run(framework.change_app_state(path, "same-id", "stop"))
    assert result["status"] == "error"
    assert result["code"] == "state_mismatch"


def test_stop_reports_development_instances_and_bridges_left_running(cli):
    client, path = cli
    client.run.side_effect = [
        document(snapshot(path, "running")),
        document({"ok": True, "stopped": 123}),
        document(snapshot(path, dev={"answering": True}, bridge={"pid": 456})),
    ]
    result = asyncio.run(framework.change_app_state(path, "same-id", "stop"))
    assert result["status"] == "success" and result["remaining"]


def test_failed_followup_query_leaves_outcome_uncertain(cli):
    client, path = cli
    client.run.side_effect = [
        document(snapshot(path)),
        document({"ok": True, "id": "same-id"}),
        RuntimeError("query unavailable"),
    ]
    result = asyncio.run(framework.change_app_state(path, "same-id", "start"))
    assert result["code"] == "uncertain"
    assert result["registry"]["status"] == "error"


def test_binding_serializes_same_app_but_allows_another_app(cli):
    client, path = cli

    async def check():
        started, release = asyncio.Event(), asyncio.Event()
        commands = []

        async def run(surface, args, **kwargs):
            if args == ["list", "--json"]:
                return document(
                    {
                        "ok": True,
                        "apps": [
                            snapshot(path)["apps"][0],
                            snapshot(path + "-other")["apps"][0],
                        ],
                        "connected": [],
                    }
                )
            commands.append(args)
            if args == [path, "serve"]:
                started.set()
                await release.wait()
            return document({"ok": True, "id": "same-id"})

        client.run.side_effect = run
        first = asyncio.create_task(
            framework.change_app_state(path, "same-id", "start")
        )
        await asyncio.wait_for(started.wait(), 1)
        second = asyncio.create_task(
            framework.change_app_state(path, "same-id", "stop")
        )
        await asyncio.wait_for(
            framework.change_app_state(path + "-other", "same-id", "stop"), 1
        )
        assert [path, "stop"] not in commands
        release.set()
        await asyncio.gather(first, second)
        assert commands.index([path, "serve"]) < commands.index([path, "stop"])

    asyncio.run(check())


def test_cancellation_releases_sequence_without_issuing_an_automatic_stop(cli):
    client, path = cli

    async def check():
        started = asyncio.Event()

        async def run(surface, args, **kwargs):
            if args == ["list", "--json"]:
                return document(snapshot(path))
            started.set()
            await asyncio.Event().wait()

        client.run.side_effect = run
        task = asyncio.create_task(framework.change_app_state(path, "same-id", "start"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert all(
            call.args[1] != [path, "stop"] for call in client.run.await_args_list
        )
        client.run.side_effect = [
            document(snapshot(path)),
            document({"ok": True}),
            document(snapshot(path)),
        ]
        assert (
            await asyncio.wait_for(
                framework.change_app_state(path, "same-id", "stop"), 1
            )
        )["status"] == "success"

    asyncio.run(check())


def test_tabs_join_one_operation_and_old_probe_cannot_overwrite_result(monkeypatch):
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter._framework_lifecycle_pending = {}
    adapter._framework_app_list_version = 0
    adapter._agent_app_manager = Mock()
    channel = SimpleNamespace(closed=False, send_json=Mock())
    first_ws, second_ws = object(), object()
    adapter._channels = {first_ws: channel, second_ws: channel}
    adapter._broadcast = AsyncMock()
    request = {
        "type": "agent_app_framework_lifecycle",
        "path": "/app",
        "appId": "same-id",
        "requestId": "one",
        "operation": "start",
    }

    async def check():
        started, release, query_started, query_release = (
            asyncio.Event() for _ in range(4)
        )

        async def query():
            first = not query_started.is_set()
            query_started.set()
            await query_release.wait()
            return {
                "status": "success",
                "data": snapshot("/app", "stopped" if first else "running"),
            }

        async def command(*args):
            started.set()
            await release.wait()
            return {
                "status": "success",
                "registry_version": framework.registry_observation(),
                "registry": {"status": "success", "data": snapshot("/app", "running")},
            }

        mutation = AsyncMock(side_effect=command)
        monkeypatch.setattr(framework, "list_apps", query)
        monkeypatch.setattr(framework, "change_app_state", mutation)
        old_query = asyncio.create_task(adapter._refresh_framework_app_list())
        await query_started.wait()
        task = asyncio.create_task(adapter._handle_ws_message(request, first_ws))
        await started.wait()
        await adapter._handle_ws_message(
            {**request, "requestId": "two", "operation": "stop"}, second_ws
        )
        assert channel.send_json.call_args.args[0]["data"]["requestId"] == "one"
        release.set()
        await task
        query_release.set()
        await old_query
        mutation.assert_awaited_once_with("/app", "same-id", "start")
        messages = [call.args[0] for call in adapter._broadcast.await_args_list]
        lists = [
            m["data"]
            for m in messages
            if m["type"] == "agent_app_framework_list"
            and m["data"]["status"] == "success"
        ]
        assert len(lists) == 2
        assert all(item["data"]["apps"][0]["status"] == "running" for item in lists)
        assert messages[-1]["data"]["status"] == "success"
        assert not adapter._framework_lifecycle_pending
        assert not adapter._agent_app_manager.mock_calls

    asyncio.run(check())


def test_real_bundled_cli_start_stop_restart_and_ownership_guard(tmp_path, monkeypatch):
    from app import node_runtime, paths

    if node_runtime.resolve() is None:
        pytest.skip("CraftBot Node runtime required")
    monkeypatch.setattr(paths, "STATE_ROOT", tmp_path / "state")
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE", raising=False)
    profile, folder = tmp_path / "profile", tmp_path / "local app"
    profile.mkdir()
    folder.mkdir()
    monkeypatch.setenv("A2APP_HOME", str(profile))
    monkeypatch.setenv("AGENT_APP_OPEN_CMD", "does-not-exist")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    manifest = {
        "id": "same-id",
        "name": "Fixture",
        "port": port,
        "pipeline": {
            "build": "node build.cjs",
            "start": "node server.cjs",
            "health": "/api/_a2app",
        },
    }
    manifest_file = folder / "manifest.json"
    manifest_file.write_text(json.dumps(manifest))
    (folder / "build.cjs").write_text(
        "require('fs').appendFileSync('builds.txt', 'build\\n')"
    )
    (folder / "server.cjs").write_text(
        "const http=require('http'); http.createServer((q,s)=>{s.setHeader('content-type','application/json'); s.end(JSON.stringify({a2app:true,app:{id:'same-id'}}))}).listen(Number(process.env.PORT),'127.0.0.1');"
    )
    runtime = folder / ".a2app"
    runtime.mkdir()
    (runtime / "system-hashes.json").write_text(
        json.dumps(
            {
                "manifest.json": "sha256:"
                + hashlib.sha256(manifest_file.read_bytes()).hexdigest()
            }
        )
    )
    (profile / "registry.json").write_text(
        json.dumps(
            {
                "version": 1,
                "apps": [
                    {
                        "path": str(folder),
                        "id": "same-id",
                        "name": "Fixture",
                        "port": port,
                    }
                ],
            }
        )
    )

    async def check():
        try:
            first = await framework.change_app_state(str(folder), "same-id", "start")
            assert first["status"] == "success", first
            pid = json.loads((runtime / "serve.json").read_text())["pid"]
            second = await framework.change_app_state(str(folder), "same-id", "start")
            assert second["status"] == "success", second
            assert json.loads((runtime / "serve.json").read_text())["pid"] == pid
            assert (folder / "builds.txt").read_text().splitlines() == ["build"]
            stopped = await framework.change_app_state(str(folder), "same-id", "stop")
            assert stopped["status"] == "success", stopped
            assert not (runtime / "serve.json").exists()
            assert (await framework.change_app_state(str(folder), "same-id", "stop"))[
                "status"
            ] == "success"
            restarted = await framework.change_app_state(
                str(folder), "same-id", "start"
            )
            assert restarted["status"] == "success", restarted
            assert (folder / "builds.txt").read_text().splitlines() == [
                "build",
                "build",
            ]
            assert (await framework.change_app_state(str(folder), "same-id", "stop"))[
                "status"
            ] == "success"
            manifest_file.write_text(json.dumps({**manifest, "name": "Drifted"}))
            refused = await framework.change_app_state(str(folder), "same-id", "start")
            assert (
                refused["status"] == "error" and "system-managed" in refused["stderr"]
            )
            assert not (runtime / "serve.json").exists()
        finally:
            # Always let the unchanged CLI clean up its own disposable app.
            await framework.change_app_state(str(folder), "same-id", "stop")

    asyncio.run(check())
