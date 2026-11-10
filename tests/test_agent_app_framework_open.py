"""Open only a freshly verified registry app, through the unchanged CLI."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.agent_app import framework
from app.agent_app.framework_cli import CLIResult
from app.ui_layer.adapters.browser_adapter import BrowserAdapter
from app.ui_layer.adapters.ws_lanes import message_lane


def result(data, code=0):
    return CLIResult(code, json.dumps(data), "")


@pytest.fixture
def cli(tmp_path, monkeypatch):
    path = str(tmp_path / "app with spaces")
    row = {"path": path, "id": "same-id", "name": "Selected", "status": "running"}
    opened = {"ok": True, "id": "same-id", "url": "http://127.0.0.1:8765"}
    client = SimpleNamespace(package_dir=tmp_path, run=AsyncMock())
    client.run.side_effect = [
        result({"ok": True, "apps": [row], "connected": []}),
        result(opened),
    ]
    monkeypatch.setattr(framework, "configured_cli", lambda: client)
    return client, row, opened


def test_open_uses_literal_registered_path_and_print_only(cli):
    client, row, _ = cli
    response = asyncio.run(framework.open_app_view(row["path"], row["id"]))
    assert response == {
        "status": "success",
        "data": {
            **{k: row[k] for k in ("path", "id", "name")},
            "url": "http://127.0.0.1:8765",
        },
    }
    assert [call.args for call in client.run.await_args_list] == [
        ("agent-app", ["list", "--json"]),
        ("agent-app", [row["path"], "open", "--print-only"]),
    ]
    assert client.run.await_args.kwargs == {"cwd": client.package_dir, "timeout": 10}


@pytest.mark.parametrize("status", ["stopped", "missing", "unreachable"])
def test_stale_running_row_is_rechecked_before_open(cli, status):
    client, row, _ = cli
    client.run.side_effect = [
        result({"ok": True, "apps": [{**row, "status": status}], "connected": []})
    ]
    response = asyncio.run(framework.open_app_view(row["path"], row["id"]))
    assert response["code"] == status
    assert client.run.await_count == 1


@pytest.mark.parametrize(
    "change,code", [("path", "not_registered"), ("id", "identity_changed")]
)
def test_registry_membership_and_identity_are_required(cli, change, code):
    client, row, _ = cli
    client.run.side_effect = [
        result({"ok": True, "apps": [{**row, change: "replacement"}], "connected": []})
    ]
    assert asyncio.run(framework.open_app_view(row["path"], row["id"]))["code"] == code
    assert client.run.await_count == 1


def test_duplicate_ids_use_the_selected_path(cli):
    client, row, opened = cli
    client.run.side_effect = [
        result(
            {
                "ok": True,
                "apps": [{**row, "path": "/different", "name": "Copy"}, row],
                "connected": [],
            }
        ),
        result(opened),
    ]
    assert (
        asyncio.run(framework.open_app_view(row["path"], row["id"]))["data"]["name"]
        == "Selected"
    )


@pytest.mark.parametrize(
    "data,exit_code,code",
    [
        ({"ok": False}, 3, "stopped"),
        ({"ok": False, "servingId": "different"}, 1, "unreachable"),
        (
            {"ok": True, "id": "different", "url": "http://127.0.0.1:8765"},
            0,
            "identity_changed",
        ),
    ],
)
def test_app_changes_between_list_and_open_are_refused(cli, data, exit_code, code):
    client, row, _ = cli
    client.run.side_effect = [
        result({"ok": True, "apps": [row], "connected": []}),
        result(data, exit_code),
    ]
    response = asyncio.run(framework.open_app_view(row["path"], row["id"]))
    assert response["code"] == code
    assert "data" not in response


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://example.test",
        "http://user:secret@127.0.0.1:8765",
        "http://127.0.0.1:99999",
        "http://127.0.0.1:8765/?token=secret",
        None,
    ],
)
def test_invalid_view_addresses_are_not_forwarded(cli, url):
    client, row, opened = cli
    client.run.side_effect = [
        result({"ok": True, "apps": [row], "connected": []}),
        result({**opened, "url": url}),
    ]
    assert (
        asyncio.run(framework.open_app_view(row["path"], row["id"]))["code"]
        == "unreachable"
    )


def test_sidecar_control_address_is_not_presented_as_its_ui(cli):
    from pathlib import Path

    client, row, _ = cli
    folder = Path(row["path"])
    folder.mkdir()
    (folder / "sidecar.json").write_text("{}")
    assert (
        asyncio.run(framework.open_app_view(row["path"], row["id"]))["code"]
        == "separate_view"
    )
    assert client.run.await_count == 1


@pytest.mark.parametrize(
    "reply",
    [
        CLIResult(0, "not JSON", ""),
        CLIResult(1, "", "failure"),
        CLIResult(-1, "", "", timed_out=True),
    ],
)
def test_registry_failure_cannot_open_a_cached_url(cli, reply):
    client, row, _ = cli
    client.run.side_effect = [reply]
    assert (
        asyncio.run(framework.open_app_view(row["path"], row["id"]))["code"]
        == "query_failed"
    )
    assert client.run.await_count == 1


def test_cancel_propagates_to_cli(cli):
    client, row, _ = cli
    client.run.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(framework.open_app_view(row["path"], row["id"]))


def test_ws_open_is_requester_only_and_never_calls_legacy_manager(monkeypatch):
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    channel, other = (
        SimpleNamespace(closed=False, send_json=Mock()),
        SimpleNamespace(closed=False, send_json=Mock()),
    )
    ws = object()
    adapter._channels = {ws: channel, object(): other}
    adapter._agent_app_manager = Mock()
    adapter._broadcast = AsyncMock()
    response = {
        "status": "success",
        "data": {
            "id": "same-id",
            "path": "/chosen",
            "url": "http://127.0.0.1:8765",
            "name": "Selected",
        },
    }
    query = AsyncMock(return_value=response)
    monkeypatch.setattr(framework, "open_app_view", query)
    request = {
        "type": "agent_app_framework_open",
        "requestId": "r1",
        "appId": "same-id",
        "path": "/chosen",
    }
    asyncio.run(adapter._handle_ws_message(request, ws))
    query.assert_awaited_once_with("/chosen", "same-id")
    assert channel.send_json.call_args.args[0]["data"] == {
        **response,
        "requestId": "r1",
    }
    other.send_json.assert_not_called()
    assert not adapter._agent_app_manager.mock_calls
    adapter._broadcast.assert_not_called()
    assert message_lane(request) != message_lane(
        {"type": "agent_app_launch", "projectId": "same-id"}
    )


def test_real_bundled_cli_verifies_identity_without_modifying_app_or_registry(
    tmp_path, monkeypatch
):
    from aiohttp import web
    from aiohttp.test_utils import TestServer
    from app import node_runtime, paths

    if node_runtime.resolve() is None:
        pytest.skip("CraftBot Node runtime required")
    monkeypatch.setattr(paths, "STATE_ROOT", tmp_path / "state")
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE", raising=False)
    profile = tmp_path / "home"
    profile.mkdir()
    monkeypatch.setenv("A2APP_HOME", str(profile))
    # If a regression calls the opener, launch a harmless process, not a browser.
    # The CLI's `opened` result still lets the test detect that regression.
    monkeypatch.setenv("AGENT_APP_OPEN_CMD", "node -e process.exit(0)")
    from app.agent_app import framework_host
    from app.agent_app.framework_commands import command
    monkeypatch.setattr(framework_host, "_host", None)
    folder = tmp_path / "registered app"
    folder.mkdir()
    requests = []
    identity = {"id": "fixture"}

    async def handler(request):
        requests.append((request.method, request.path))
        if request.path == "/api/_a2app":
            return web.json_response({"a2app": True, "app": {"id": identity["id"]}})
        return web.Response(status=404)

    async def check():
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        manifest = folder / "manifest.json"
        manifest.write_text(
            json.dumps({"id": "fixture", "name": "Fixture", "port": server.port})
        )
        registry = profile / "registry.json"
        registry.write_text(
            json.dumps(
                {
                    "version": 1,
                    "apps": [{"id": "fixture", "name": "Fixture", "path": str(folder)}],
                }
            )
        )
        before = manifest.read_bytes(), registry.read_bytes()
        try:
            response = await framework.open_app_view(str(folder), "fixture")
            assert response["status"] == "success", response
            assert response["data"]["url"] == f"http://127.0.0.1:{server.port}"
            for flags in ([], ["--if-needed"]):
                opened = await command("agent-app", [str(folder), "open", *flags])
                assert opened["status"] == "success", opened
                assert opened["data"]["opened"] is False
                assert opened["data"]["via"] == "print-only"
                assert "embedded view" in opened["host_note"]
            identity["id"] = "another-app"
            response = await framework.open_app_view(str(folder), "fixture")
            assert response["code"] == "unreachable"
            assert (manifest.read_bytes(), registry.read_bytes()) == before
            assert list(folder.iterdir()) == [manifest]
            assert all(method == "GET" for method, _ in requests)
        finally:
            await server.close()

    asyncio.run(check())
