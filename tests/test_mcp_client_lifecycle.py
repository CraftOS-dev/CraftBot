"""MCPClient with several Streamable HTTP servers: isolation and reloads (#185).

Each server has its own connection, headers, credentials and error. A reload
touches only the servers whose connection settings changed; a removed server
takes exactly its own actions with it. Also covers the generated tool handler
treating server-supplied names as data.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Dict, List

import pytest

from agent_core.core.action_framework import registry_instance
from agent_core.core.impl.mcp.adapter import MCPActionAdapter
from agent_core.core.impl.mcp.client import MCPClient
from tests.mcp_http_mock import serve

KEY_A = "key-A-SENTINEL-1111"
KEY_B = "key-B-SENTINEL-2222"


@pytest.fixture
def client():
    """A fresh MCPClient (the module-level one is a singleton)."""
    instance = object.__new__(MCPClient)
    instance._initialized = False
    instance.__init__()
    yield instance
    for names in instance._registered_actions.values():
        MCPActionAdapter.unregister_actions(names)


def entry(name: str, url: str, key: str, **extra) -> Dict:
    data = {
        "name": name,
        "transport": "http",
        "url": url,
        "timeout": 10,
        "headers": {"Authorization": "Bearer ${TOKEN}"},
        "env": {"TOKEN": key},
        "enabled": True,
    }
    data.update(extra)
    return data


def write(path: Path, servers: List[Dict]) -> Path:
    path.write_text(json.dumps({"mcp_servers": servers}), encoding="utf-8")
    return path


def inits(server) -> int:
    return len(server.calls("initialize"))


def deletes(server) -> int:
    return len([r for r in server.requests if r["http"] == "DELETE"])


async def two_servers():
    a, url_a = await serve(name="a")
    b, url_b = await serve(name="b")
    a.required_headers = {"Authorization": f"Bearer {KEY_A}"}
    b.required_headers = {"Authorization": f"Bearer {KEY_B}"}
    return a, url_a, b, url_b


# ───────────────────────── Several servers at once ──────────────────────────


def test_two_servers_connect_with_their_own_credentials_and_tools(client, tmp_path):
    async def scenario():
        a, url_a, b, url_b = await two_servers()
        try:
            path = write(
                tmp_path / "mcp.json",
                [entry("srv_a", url_a, KEY_A), entry("srv_b", url_b, KEY_B)],
            )
            await client.initialize(path)
            client.register_tools_as_actions()
            registered = set(registry_instance._registry)
            ra = await client.call_tool("srv_a", "echo", {"text": "hi"})
            rb = await client.call_tool("srv_b", "echo", {"text": "hi"})
            status = client.get_status()
            await client.disconnect_all()
            after = set(registry_instance._registry)
            return a, b, ra, rb, status, registered, after
        finally:
            await a.stop()
            await b.stop()

    a, b, ra, rb, status, registered, after = asyncio.run(scenario())
    assert ra["result"] == "a:hi"
    assert rb["result"] == "b:hi"
    assert status["servers"]["srv_a"]["connected"] is True
    assert status["servers"]["srv_b"]["connected"] is True
    # No cross-server leakage: each server only ever saw its own key and session.
    for server, own, other in ((a, KEY_A, KEY_B), (b, KEY_B, KEY_A)):
        for request in server.requests:
            assert request["headers"].get("authorization") == f"Bearer {own}"
            assert other not in json.dumps(request["headers"])
    assert {"mcp_srv_a_echo", "mcp_srv_b_echo"} <= registered
    assert deletes(a) == 1 and deletes(b) == 1  # disconnect_all ended both
    # ...and took their actions with them.
    assert not {"mcp_srv_a_echo", "mcp_srv_b_echo"} & after


def test_one_failing_server_does_not_affect_the_other(client, tmp_path):
    async def scenario():
        a, url_a, b, url_b = await two_servers()
        try:
            path = write(
                tmp_path / "mcp.json",
                # srv_b gets srv_a's key: its server refuses it.
                [entry("srv_a", url_a, KEY_A), entry("srv_b", url_b, KEY_A)],
            )
            await client.initialize(path)
            ra = await client.call_tool("srv_a", "echo", {"text": "ok"})
            rb = await client.call_tool("srv_b", "echo", {"text": "ok"})
            status = client.get_status()
            await client.disconnect_all()
            return ra, rb, status
        finally:
            await a.stop()
            await b.stop()

    ra, rb, status = asyncio.run(scenario())
    assert ra["status"] == "success"
    assert rb == {"status": "error", "message": "MCP server 'srv_b' is not connected"}
    failed = status["servers"]["srv_b"]
    assert failed["connected"] is False
    assert "HTTP 401" in failed["error"]
    assert KEY_A not in json.dumps(status)


def test_a_missing_credential_is_reported_per_server(client, tmp_path):
    async def scenario():
        a, url_a, b, url_b = await two_servers()
        try:
            broken = entry("srv_b", url_b, KEY_B)
            broken["env"] = {}
            path = write(tmp_path / "mcp.json", [entry("srv_a", url_a, KEY_A), broken])
            await client.initialize(path)
            status = client.get_status()
            await client.disconnect_all()
            return status, b
        finally:
            await a.stop()
            await b.stop()

    status, b = asyncio.run(scenario())
    assert status["servers"]["srv_a"]["connected"] is True
    assert status["servers"]["srv_b"]["error"] == (
        "Server 'srv_b': set TOKEN in this server's env (referenced by its headers)"
    )
    assert b.requests == []  # never contacted without its credential


# ───────────────────────── Reloads ──────────────────────────────────────────


def test_editing_one_server_reconnects_only_that_server(client, tmp_path):
    async def scenario():
        a, url_a, b, url_b = await two_servers()
        try:
            path = write(
                tmp_path / "mcp.json",
                [entry("srv_a", url_a, KEY_A), entry("srv_b", url_b, "old-key")],
            )
            await client.initialize(path)
            transport_a = client.servers["srv_a"]._transport
            assert "srv_b" not in client.servers  # old key refused
            # Fix srv_b's key and change only srv_a's description.
            write(
                path,
                [
                    entry("srv_a", url_a, KEY_A, description="renamed"),
                    entry("srv_b", url_b, KEY_B),
                ],
            )
            result = await client.reload(path)
            same_a = client.servers["srv_a"]._transport is transport_a
            description = client.servers["srv_a"].config.description
            rb = await client.call_tool("srv_b", "echo", {"text": "x"})
            await client.disconnect_all()
            return result, same_a, description, rb, a
        finally:
            await a.stop()
            await b.stop()

    result, same_a, description, rb, a = asyncio.run(scenario())
    assert result["connected"] == ["srv_b"]
    assert result["reconnected"] == [] and result["disconnected"] == []
    assert same_a and description == "renamed"
    assert inits(a) == 1  # srv_a was never re-initialised
    assert rb["result"] == "b:x"


def test_changing_a_header_reconnects_with_the_new_value(client, tmp_path):
    async def scenario():
        a, url_a, b, url_b = await two_servers()
        b.required_headers = {}
        try:
            path = write(
                tmp_path / "mcp.json",
                [entry("srv_a", url_a, KEY_A), entry("srv_b", url_b, "first")],
            )
            await client.initialize(path)
            write(path, [entry("srv_a", url_a, KEY_A), entry("srv_b", url_b, "second")])
            result = await client.reload(path)
            await client.call_tool("srv_b", "echo", {"text": "x"})
            await client.disconnect_all()
            return result, a, b
        finally:
            await a.stop()
            await b.stop()

    result, a, b = asyncio.run(scenario())
    assert result["reconnected"] == ["srv_b"]
    assert inits(a) == 1 and inits(b) == 2
    assert deletes(b) == 2  # the old session was ended, then the new one
    assert b.calls("tools/call")[0]["headers"]["authorization"] == "Bearer second"


def test_removing_a_server_disconnects_it_and_removes_only_its_actions(
    client, tmp_path
):
    async def scenario():
        a, url_a, b, url_b = await two_servers()
        try:
            # "foo" is a prefix of "foo_bar": removing foo must keep foo_bar's.
            path = write(
                tmp_path / "mcp.json",
                [entry("foo", url_a, KEY_A), entry("foo_bar", url_b, KEY_B)],
            )
            await client.initialize(path)
            client.register_tools_as_actions()
            before = set(registry_instance._registry)
            write(path, [entry("foo_bar", url_b, KEY_B)])
            result = await client.reload(path)
            after = set(registry_instance._registry)
            still = await client.call_tool("foo_bar", "echo", {"text": "y"})
            await client.disconnect_all()
            return before, after, result, still, a
        finally:
            await a.stop()
            await b.stop()

    before, after, result, still, a = asyncio.run(scenario())
    assert {"mcp_foo_echo", "mcp_foo_bar_echo"} <= before
    assert "mcp_foo_echo" not in after
    assert "mcp_foo_bar_echo" in after
    assert result["disconnected"] == ["foo"]
    assert deletes(a) == 1
    assert still["result"] == "b:y"


def test_a_broken_edit_keeps_the_running_server_on_its_last_good_settings(
    client, tmp_path
):
    async def scenario():
        a, url_a, b, url_b = await two_servers()
        try:
            path = write(tmp_path / "mcp.json", [entry("srv_a", url_a, KEY_A)])
            await client.initialize(path)
            write(path, [entry("srv_a", "ftp://not-http/mcp", KEY_A)])
            result = await client.reload(path)
            still = await client.call_tool("srv_a", "echo", {"text": "z"})
            saved = json.loads(path.read_text(encoding="utf-8"))
            await client.disconnect_all()
            return result, still, saved
        finally:
            await a.stop()
            await b.stop()

    result, still, saved = asyncio.run(scenario())
    assert result["kept"] == ["srv_a"]
    assert result["invalid"][0]["name"] == "srv_a"
    assert "http:// or https://" in result["invalid"][0]["error"]
    assert still["result"] == "a:z"
    assert saved["mcp_servers"][0]["url"] == "ftp://not-http/mcp"  # untouched


def test_disabling_a_server_disconnects_it_and_clears_its_error(client, tmp_path):
    async def scenario():
        a, url_a, b, url_b = await two_servers()
        try:
            path = write(
                tmp_path / "mcp.json",
                [entry("srv_a", url_a, KEY_A), entry("srv_b", url_b, "wrong")],
            )
            await client.initialize(path)
            had_error = "srv_b" in client.last_errors
            write(
                path,
                [
                    entry("srv_a", url_a, KEY_A, enabled=False),
                    entry("srv_b", url_b, "wrong", enabled=False),
                ],
            )
            result = await client.reload(path)
            status = client.get_status()
            return had_error, result, status
        finally:
            await a.stop()
            await b.stop()

    had_error, result, status = asyncio.run(scenario())
    assert had_error
    assert result["disconnected"] == ["srv_a"]
    assert status["servers"] == {}


def test_concurrent_reloads_are_serialised(client, tmp_path):
    async def scenario():
        a, url_a, b, url_b = await two_servers()
        try:
            path = write(tmp_path / "mcp.json", [entry("srv_a", url_a, KEY_A)])
            await client.initialize(path)
            write(path, [entry("srv_a", url_a, KEY_A), entry("srv_b", url_b, KEY_B)])
            results = await asyncio.gather(client.reload(path), client.reload(path))
            await client.disconnect_all()
            return results, b
        finally:
            await a.stop()
            await b.stop()

    results, b = asyncio.run(scenario())
    assert inits(b) == 1  # connected once, not by both reloads
    assert sorted(r["connected"] for r in results) == [[], ["srv_b"]]


def test_an_unreadable_config_leaves_connections_alone(client, tmp_path):
    async def scenario():
        a, url_a, b, url_b = await two_servers()
        try:
            path = write(tmp_path / "mcp.json", [entry("srv_a", url_a, KEY_A)])
            await client.initialize(path)
            path.write_text("{ not json", encoding="utf-8")
            result = await client.reload(path)
            connected = client.servers["srv_a"].is_connected
            await client.disconnect_all()
            return result, connected
        finally:
            await a.stop()
            await b.stop()

    result, connected = asyncio.run(scenario())
    assert result["success"] is False
    assert connected


# ───────────────────────── Tool handler ─────────────────────────────────────


def test_handler_timeout_follows_the_http_servers_timeout(client, tmp_path):
    async def scenario():
        path = write(
            tmp_path / "mcp.json",
            [
                {
                    "name": "slow",
                    "transport": "http",
                    "url": "https://h/mcp",
                    "timeout": 120,
                    "enabled": False,
                },
                {
                    "name": "fast",
                    "transport": "http",
                    "url": "https://h/mcp",
                    "timeout": 5,
                    "enabled": False,
                },
                {"name": "local", "command": "x", "enabled": False},
            ],
        )
        await client.initialize(path)

    asyncio.run(scenario())
    assert client.handler_timeout("slow") == 130.0
    assert client.handler_timeout("fast") == 60.0
    assert client.handler_timeout("local") == 60.0
    assert client.handler_timeout("unknown") == 60.0


def test_a_reload_reconnects_a_server_whose_connection_died(client, tmp_path):
    async def scenario():
        a, url_a, b, url_b = await two_servers()
        try:
            path = write(tmp_path / "mcp.json", [entry("srv_a", url_a, KEY_A)])
            await client.initialize(path)
            # The session ends and cannot be renewed: the transport gives up.
            a.expire()
            a.status_for = {"initialize": 503}
            failed = await client.call_tool("srv_a", "echo", {"text": "1"})
            dead = not client.servers["srv_a"].is_connected
            # The server recovers; settings are unchanged.
            a.status_for = {}
            result = await client.reload(path)
            again = await client.call_tool("srv_a", "echo", {"text": "2"})
            await client.disconnect_all()
            return failed, dead, result, again
        finally:
            await a.stop()
            await b.stop()

    failed, dead, result, again = asyncio.run(scenario())
    assert failed["status"] == "error"
    assert dead
    assert result["reconnected"] == ["srv_a"]
    assert again["result"] == "a:2"
