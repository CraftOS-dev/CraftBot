"""Native app-list discovery: independent snapshots, no legacy lifecycle calls."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.agent_app import framework
from app.ui_layer.adapters.browser_adapter import BrowserAdapter


def listing(status="running"):
    return {
        "status": "success",
        "data": {
            "ok": True,
            "apps": [
                {
                    "id": "same-id",
                    "name": "Framework app",
                    "path": "/fixture",
                    "status": status,
                }
            ],
            "connected": [
                {
                    "appId": "remote",
                    "name": "Shared app",
                    "origin": "https://example.test",
                    "status": "offline",
                }
            ],
        },
        "stderr": "",
    }


@pytest.fixture
def adapter():
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    project = SimpleNamespace(
        id="same-id",
        status="running",
        to_dict=lambda: {"id": "same-id", "name": "Legacy app"},
    )
    adapter._agent_app_manager = Mock(spec=["list_projects", "stop_all_projects"])
    adapter._agent_app_manager.list_projects.return_value = [project]
    adapter._agent_app_manager.stop_all_projects = AsyncMock()
    adapter._framework_app_list_task = None
    adapter._agent_app_todos = {}
    adapter._broadcast = AsyncMock()
    return adapter


def test_legacy_list_returns_while_framework_query_is_pending_and_refreshes_coalesce(
    adapter, monkeypatch
):
    async def check():
        started, release = asyncio.Event(), asyncio.Event()

        async def query():
            started.set()
            await release.wait()
            return listing()

        query_mock = AsyncMock(side_effect=query)
        monkeypatch.setattr(framework, "list_apps", query_mock)
        await asyncio.wait_for(adapter._handle_agent_app_list(), 1)
        await asyncio.wait_for(started.wait(), 1)
        task = adapter._framework_app_list_task
        await adapter._handle_agent_app_list()
        assert adapter._framework_app_list_task is task
        messages = [call.args[0] for call in adapter._broadcast.await_args_list]
        assert messages[0]["type"] == "agent_app_list"
        assert messages[0]["data"]["projects"] == [
            {"id": "same-id", "name": "Legacy app"}
        ]
        assert not task.done()
        release.set()
        await task
        query_mock.assert_awaited_once()
        assert adapter._broadcast.await_args.args[0] == {
            "type": "agent_app_framework_list",
            "data": listing(),
        }
        assert all(
            call[0] == "list_projects"
            for call in adapter._agent_app_manager.method_calls
        )

    asyncio.run(check())


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("package unavailable"),
        {"status": "error", "message": "CLI failed", "exit_code": 2},
    ],
)
def test_framework_failure_does_not_replace_the_legacy_snapshot(
    adapter, monkeypatch, failure
):
    query = (
        AsyncMock(side_effect=failure)
        if isinstance(failure, Exception)
        else AsyncMock(return_value=failure)
    )
    monkeypatch.setattr(framework, "list_apps", query)

    async def check():
        await adapter._handle_agent_app_list()
        await adapter._framework_app_list_task
        messages = [call.args[0] for call in adapter._broadcast.await_args_list]
        assert messages[0]["data"]["success"] is True
        assert messages[-1]["type"] == "agent_app_framework_list"
        assert messages[-1]["data"]["status"] == "error"
        assert "apps" not in messages[-1]["data"]

    asyncio.run(check())


def test_legacy_failure_does_not_block_framework_discovery(adapter, monkeypatch):
    adapter._agent_app_manager.list_projects.side_effect = RuntimeError(
        "legacy unavailable"
    )
    monkeypatch.setattr(framework, "list_apps", AsyncMock(return_value=listing()))

    async def check():
        await adapter._handle_agent_app_list()
        await adapter._framework_app_list_task
        assert adapter._broadcast.await_args_list[0].args[0]["data"]["success"] is False
        assert adapter._broadcast.await_args.args[0]["data"] == listing()

    asyncio.run(check())


def test_next_refresh_reads_changed_framework_state(adapter, monkeypatch):
    query = AsyncMock(side_effect=[listing("running"), listing("missing")])
    monkeypatch.setattr(framework, "list_apps", query)

    async def check():
        for status in ("running", "missing"):
            await adapter._handle_agent_app_list()
            await adapter._framework_app_list_task
            assert adapter._broadcast.await_args.args[0]["data"] == listing(status)
        assert query.await_count == 2

    asyncio.run(check())


def test_shutdown_cancels_the_framework_query(adapter, monkeypatch):
    async def check():
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def query():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(framework, "list_apps", query)
        adapter._metrics_task = None
        adapter._loop_monitor = Mock()
        adapter._ws_clients = set()
        adapter._channels = {}
        adapter._runner = None
        adapter._schedule_framework_app_list()
        await asyncio.wait_for(started.wait(), 1)
        await adapter._on_stop()
        assert cancelled.is_set()
        assert adapter._framework_app_list_task is None

    asyncio.run(check())


def test_native_list_reads_the_bundled_cli_in_an_isolated_profile(
    adapter, monkeypatch, tmp_path
):
    from app import node_runtime, paths

    if node_runtime.resolve() is None:
        pytest.skip("CraftBot Node runtime required")
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE", raising=False)
    monkeypatch.setattr(paths, "STATE_ROOT", tmp_path / "state")
    profile = tmp_path / "framework"
    profile.mkdir()
    monkeypatch.setenv("A2APP_HOME", str(profile))
    registry = profile / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "apps": [
                    {
                        "id": "same-id",
                        "name": "Framework app",
                        "path": str(tmp_path / "absent"),
                    }
                ],
            }
        )
    )
    before = registry.read_bytes()

    async def check():
        await adapter._handle_agent_app_list()
        await adapter._framework_app_list_task
        result = adapter._broadcast.await_args.args[0]["data"]
        assert result["status"] == "success", result
        assert result["data"]["apps"][0]["status"] == "missing"
        assert registry.read_bytes() == before
        assert adapter._agent_app_manager.list_projects.call_count == 1

    asyncio.run(check())


def test_connect_pushes_framework_apps_without_blocking_socket_pings(
    adapter, monkeypatch
):
    import aiohttp
    from aiohttp import web
    from aiohttp.test_utils import TestServer
    from app.ui_layer.adapters.ws_auth import WsAuth

    async def check():
        release = asyncio.Event()

        async def query():
            await release.wait()
            return listing()

        monkeypatch.setattr(framework, "list_apps", query)
        adapter._broadcast = BrowserAdapter._broadcast.__get__(adapter)
        adapter._ws_clients = {object()}  # skip unrelated first-client onboarding
        adapter._channels = {}
        adapter._metrics_subscribers = set()
        adapter._lane_locks = {}
        adapter._lane_tasks = set()
        adapter._started_at = 0.0
        adapter._ws_prepare_failures = 0
        adapter._get_initial_state = lambda: {}
        adapter._get_skill_meta = lambda: {}
        operation = {
            "requestId": "in-flight",
            "path": "/fixture",
            "appId": "same-id",
            "operation": "start",
            "status": "running",
        }
        adapter._framework_lifecycle_pending = {"/fixture": operation}
        app = web.Application()
        app.router.add_get("/ws", adapter._websocket_handler)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        adapter._ws_auth = WsAuth(server.port)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    server.make_url("/ws"),
                    origin=f"http://127.0.0.1:{server.port}",
                    protocols=["craftbot", f"craftbot-auth.{adapter._ws_auth.token}"],
                ) as ws:
                    assert (await ws.receive_json(timeout=2))["type"] == "init"
                    assert (await ws.receive_json(timeout=2))["type"] == "skill_meta"
                    assert (await ws.receive_json(timeout=2))[
                        "type"
                    ] == "agent_app_list"
                    replay = await ws.receive_json(timeout=2)
                    assert replay == {
                        "type": "agent_app_framework_lifecycle",
                        "data": operation,
                    }
                    assert (await ws.receive_json(timeout=2))["data"][
                        "status"
                    ] == "loading"
                    await ws.send_json({"type": "ping"})
                    assert (await ws.receive_json(timeout=2))["type"] == "pong"
                    release.set()
                    assert (await ws.receive_json(timeout=2))["data"] == listing()
        finally:
            release.set()
            if adapter._framework_app_list_task:
                await adapter._framework_app_list_task
            await server.close()

    asyncio.run(check())
