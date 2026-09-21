"""/ws handshake guard: Origin/Host allowlist + per-session token.

The integration tests run the real BrowserAdapter handlers (built with
``__new__`` and minimal stubs) behind an aiohttp TestServer.
"""

import asyncio
import json
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.ui_layer.adapters.browser_adapter import BrowserAdapter
from app.ui_layer.adapters.ws_auth import WsAuth

TOKEN = "a" * 64


@pytest.fixture(autouse=True)
def _frontend_port(monkeypatch):
    monkeypatch.setenv("VITE_PORT", "7925")


# ---------------------------------------------------------------- unit


def test_allowlist_covers_frontend_and_backend_ports():
    auth = WsAuth(7926, token=TOKEN)
    for host in ("localhost", "127.0.0.1", "[::1]"):
        for port in (7925, 7926):
            assert auth.origin_ok(f"http://{host}:{port}")
            assert auth.host_ok(f"{host}:{port}")
    assert not auth.origin_ok("https://evil.example")
    assert not auth.origin_ok("http://localhost:3000")  # e.g. an Agent App
    assert not auth.origin_ok("http://192.168.1.50:7925")
    assert not auth.origin_ok("null")
    assert not auth.origin_ok(None)
    assert not auth.host_ok("evil.example:7926")  # DNS rebinding


def test_token_compare():
    auth = WsAuth(7926, token=TOKEN)
    assert auth.token_ok(TOKEN)
    assert not auth.token_ok("b" * 64)
    assert not auth.token_ok("")
    assert not auth.token_ok(None)
    assert WsAuth(7926).token != WsAuth(7926).token  # random per process


def test_token_from_protocols():
    assert WsAuth.token_from_protocols(f"craftbot, craftbot-auth.{TOKEN}") == TOKEN
    assert WsAuth.token_from_protocols("craftbot") is None
    assert WsAuth.token_from_protocols(None) is None


def test_token_request_checks():
    auth = WsAuth(7926, token=TOKEN)
    ok = {"Host": "localhost:7925"}
    assert auth.check_token_request(ok) is None
    assert auth.check_token_request({**ok, "Sec-Fetch-Site": "same-origin"}) is None
    assert auth.check_token_request({**ok, "Sec-Fetch-Site": "cross-site"}) == "fetch-site"
    assert auth.check_token_request({**ok, "Sec-Fetch-Site": "same-site"}) == "fetch-site"
    assert auth.check_token_request({**ok, "Origin": "https://evil.example"}) == "origin"
    assert auth.check_token_request({"Host": "evil.example:7926"}) == "host"


# --------------------------------------------------------- integration


def _stub_adapter() -> BrowserAdapter:
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    # Not the first client, so the soft-onboarding hook (needs a workspace) is skipped.
    adapter._ws_clients = {object()}
    adapter._channels = {}
    adapter._metrics_subscribers = set()
    adapter._lane_locks = {}
    adapter._lane_tasks = set()
    adapter._started_at = 0.0
    adapter._ws_prepare_failures = 0
    adapter._get_initial_state = lambda: {"stub": True}
    adapter._get_skill_meta = lambda: {}
    adapter._agent_app_manager = SimpleNamespace(list_projects=lambda: [])
    return adapter


async def _with_server(fn):
    adapter = _stub_adapter()
    app = web.Application()
    app.router.add_get("/ws", adapter._websocket_handler)
    app.router.add_get("/api/session-token", adapter._session_token_handler)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    adapter._ws_auth = WsAuth(server.port, token=TOKEN)
    try:
        async with aiohttp.ClientSession() as session:
            return await fn(session, server.port)
    finally:
        await server.close()


async def _handshake(session, port, origin, protocols=()):
    headers = {"Origin": origin} if origin else {}
    try:
        async with session.ws_connect(
            f"http://127.0.0.1:{port}/ws", headers=headers, protocols=protocols
        ) as ws:
            first = json.loads((await asyncio.wait_for(ws.receive(), 5)).data)
            return ("open", first["type"], ws.protocol)
    except aiohttp.WSServerHandshakeError as e:
        return ("rejected", e.status, None)


def _run(fn):
    return asyncio.run(_with_server(fn))


def test_foreign_origin_rejected_even_with_token():
    async def go(s, port):
        return await _handshake(
            s, port, "https://evil.example", ("craftbot", f"craftbot-auth.{TOKEN}")
        )

    assert _run(go) == ("rejected", 403, None)


def test_missing_origin_rejected():
    async def go(s, port):
        return await _handshake(s, port, None, ("craftbot", f"craftbot-auth.{TOKEN}"))

    assert _run(go) == ("rejected", 403, None)


def test_missing_token_rejected():
    async def go(s, port):
        return await _handshake(s, port, f"http://127.0.0.1:{port}", ("craftbot",))

    assert _run(go) == ("rejected", 403, None)


def test_wrong_token_rejected():
    async def go(s, port):
        return await _handshake(
            s, port, f"http://127.0.0.1:{port}", ("craftbot", "craftbot-auth." + "b" * 64)
        )

    assert _run(go) == ("rejected", 403, None)


def test_correct_origin_and_token_accepted():
    async def go(s, port):
        # Frontend-port origin (Vite / static server) and backend-port origin.
        return [
            await _handshake(
                s, port, origin, ("craftbot", f"craftbot-auth.{TOKEN}")
            )
            for origin in ("http://localhost:7925", f"http://127.0.0.1:{port}")
        ]

    assert _run(go) == [("open", "init", "craftbot")] * 2


def test_token_endpoint_same_origin_only():
    async def go(s, port):
        url = f"http://127.0.0.1:{port}/api/session-token"
        async with s.get(url, headers={"Sec-Fetch-Site": "same-origin"}) as r:
            ok = (r.status, await r.json(), r.headers.get("Access-Control-Allow-Origin"))
        async with s.get(url, headers={"Origin": "https://evil.example"}) as r:
            foreign = r.status
        async with s.get(url, headers={"Sec-Fetch-Site": "cross-site"}) as r:
            cross = r.status
        async with s.get(url, headers={"Host": "evil.example"}) as r:
            rebind = r.status
        return ok, foreign, cross, rebind

    ok, foreign, cross, rebind = _run(go)
    assert ok == (200, {"token": TOKEN}, None)
    assert (foreign, cross, rebind) == (403, 403, 403)


def test_fetched_token_opens_socket():
    """The flow the UI runs: fetch token, then connect with it."""

    async def go(s, port):
        async with s.get(f"http://127.0.0.1:{port}/api/session-token") as r:
            token = (await r.json())["token"]
        return await _handshake(
            s, port, "http://localhost:7925", ("craftbot", f"craftbot-auth.{token}")
        )

    assert _run(go) == ("open", "init", "craftbot")
