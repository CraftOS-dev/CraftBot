"""Check MCP packages: OSV malware lookup before an MCP server starts."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.security import audit, osv
from app.security.policy import SecurityStore, set_store_for_tests

SERVER = {"name": "fs", "transport": "stdio", "command": "npx", "args": ["-y", "evil-pkg"]}


@pytest.fixture
def store(tmp_path):
    store = SecurityStore(tmp_path / "security.json")
    set_store_for_tests(store)
    osv.clear_cache()
    yield store
    set_store_for_tests(None)
    osv.clear_cache()


@pytest.fixture
def queries(monkeypatch):
    """Record OSV queries; answer with whatever ``answer`` holds."""
    calls = []
    answer = {"value": []}

    def fake(package, ecosystem, version=None):
        calls.append((package, ecosystem, version))
        if isinstance(answer["value"], Exception):
            raise answer["value"]
        return answer["value"]

    monkeypatch.setattr(osv, "_query_osv", fake)
    return calls, answer


def refusal(server=SERVER):
    return asyncio.run(osv.malware_refusal(server))


def test_off_by_default_makes_no_lookup(store, queries):
    calls, _ = queries
    assert refusal() is None
    assert calls == []


def test_known_malware_is_refused_and_audited(store, queries):
    calls, answer = queries
    store.update({"check_mcp_packages": True})
    answer["value"] = [{"id": "MAL-2026-1", "summary": "steals SSH keys"}]
    why = refusal()
    assert "fs" in why and "MAL-2026-1" in why and "steals SSH keys" in why
    assert calls == [("evil-pkg", "npm", None)]
    events = [e for e in audit.get_log().entries() if e["event"] == "mcp_blocked"]
    assert events and events[-1]["package"] == "evil-pkg"
    assert events[-1]["server"] == "fs"


def test_a_clean_package_starts(store, queries):
    _, answer = queries
    store.update({"check_mcp_packages": True})
    answer["value"] = []
    assert refusal() is None


def test_a_failed_lookup_starts_and_is_not_cached(store, queries):
    calls, answer = queries
    store.update({"check_mcp_packages": True})
    answer["value"] = OSError("no network")
    assert refusal() is None
    assert refusal() is None
    assert len(calls) == 2


def test_verdicts_are_reused(store, queries):
    calls, answer = queries
    store.update({"check_mcp_packages": True})
    answer["value"] = [{"id": "MAL-2026-2"}]
    assert refusal() and refusal()
    assert len(calls) == 1


def test_a_slow_lookup_starts(store, monkeypatch):
    store.update({"check_mcp_packages": True})
    monkeypatch.setattr(osv, "_PREFLIGHT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(
        osv, "check_package_for_malware", lambda *_: time.sleep(0.5) or "malware"
    )
    assert refusal() is None


@pytest.mark.parametrize(
    "command,args,expected",
    [
        ("npx", ["-y", "@scope/server@1.2.3"], ("@scope/server", "npm", "1.2.3")),
        ("npx", ["-y", "pkg@latest"], ("pkg", "npm", None)),
        ("npx", ["--package=real-pkg", "bin"], ("real-pkg", "npm", None)),
        ("npx.cmd", ["-p", "real-pkg", "bin"], ("real-pkg", "npm", None)),
        ("/usr/local/bin/uvx", ["mcp-server-git==0.6.2"], ("mcp-server-git", "PyPI", "0.6.2")),
        ("C:\\tools\\uvx.exe", ["mcp-server-fetch[extra]"], ("mcp-server-fetch", "PyPI", None)),
        ("pipx", ["run", "some-server"], ("some-server", "PyPI", None)),
    ],
)
def test_launchers_and_versions(store, queries, command, args, expected):
    calls, _ = queries
    store.update({"check_mcp_packages": True})
    refusal({"name": "s", "transport": "stdio", "command": command, "args": args})
    assert calls == [expected]


@pytest.mark.parametrize(
    "server",
    [
        {"name": "s", "transport": "stdio", "command": "node", "args": ["server.js"]},
        {"name": "s", "transport": "stdio", "command": "pipx", "args": ["list"]},
        {"name": "s", "transport": "sse", "url": "https://example.com/sse"},
    ],
)
def test_other_servers_are_not_looked_up(store, queries, server):
    calls, _ = queries
    store.update({"check_mcp_packages": True})
    assert refusal(server) is None
    assert calls == []


def test_connect_does_not_start_a_server_with_malware(store, queries, monkeypatch):
    from agent_core.core.impl.mcp.config import MCPServerConfig
    from agent_core.core.impl.mcp.server import MCPServerConnection

    _, answer = queries
    store.update({"check_mcp_packages": True})
    answer["value"] = [{"id": "MAL-2026-3"}]
    connection = MCPServerConnection(
        MCPServerConfig(name="fs", command="npx", args=["-y", "evil-pkg"])
    )

    def no_transport():
        raise AssertionError("the server process must not be started")

    monkeypatch.setattr(connection, "_create_transport", no_transport)
    assert asyncio.run(connection.connect()) is False
