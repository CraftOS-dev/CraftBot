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


# ------------------------------------------------ /api/* over plain HTTP
#
# The same cross-site threat as /ws: a multipart POST is a CORS "simple"
# request, so any page can send one without a preflight and the write
# happens even though the response is unreadable.


def test_api_request_checks():
    auth = WsAuth(7926, token=TOKEN)
    ui = {"Host": "localhost:7925", "Origin": "http://localhost:7925"}
    assert auth.check_api_request("POST", ui) is None
    assert auth.check_api_request("POST", {"Host": "localhost:7926"}) is None, (
        "no Origin = non-browser caller (the agent-app bridge)"
    )
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert auth.check_api_request(
            method, {**ui, "Origin": "https://evil.example"}
        ) == "origin", method
    assert auth.check_api_request("POST", {**ui, "Origin": "null"}) == "origin"
    assert auth.check_api_request("POST", {**ui, "Origin": "http://127.0.0.1:3100"}) == (
        "origin"
    ), "an Agent App page is not the CraftBot UI"
    # reads: Origin is the browser's business (no CORS grant), Host is ours
    assert auth.check_api_request("GET", {**ui, "Origin": "https://evil.example"}) is None
    assert auth.check_api_request("GET", {"Host": "evil.example:7926"}) == "host"
    assert auth.check_api_request("POST", {"Host": "evil.example:7925"}) == "host"


async def _with_upload_server(fn, workspace):
    import app.ui_layer.adapters.browser_adapter as ba

    adapter = _stub_adapter()
    broadcasts = []

    async def _broadcast(msg):
        broadcasts.append(msg)

    adapter._broadcast = _broadcast
    app = web.Application(middlewares=[adapter._api_guard()])
    app.router.add_post("/api/workspace/upload", adapter._workspace_upload_handler)
    app.router.add_post(
        "/api/chat-attachments/upload", adapter._chat_attachment_upload_handler
    )
    app.router.add_get("/api/workspace/{path:.*}", adapter._workspace_file_handler)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    adapter._ws_auth = WsAuth(server.port, token=TOKEN)
    old_root = ba.AGENT_WORKSPACE_ROOT
    ba.AGENT_WORKSPACE_ROOT = str(workspace)
    try:
        async with aiohttp.ClientSession() as session:
            return await fn(session, server.port)
    finally:
        ba.AGENT_WORKSPACE_ROOT = old_root
        await server.close()


def _upload_form(payload=b"pwned"):
    form = aiohttp.FormData()
    form.add_field("file", payload, filename="f.txt")
    return form


def test_upload_foreign_origin_refused(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()

    async def go(s, port):
        results = {}
        for label, headers in (
            ("evil", {"Origin": "https://evil.example"}),
            ("rebind", {"Host": "evil.example:7926"}),
            ("ui", {"Origin": f"http://localhost:{port}"}),
        ):
            async with s.post(
                f"http://127.0.0.1:{port}/api/workspace/upload?path={label}.txt",
                data=_upload_form(),
                headers=headers,
            ) as r:
                results[label] = r.status
        return results

    assert asyncio.run(_with_upload_server(go, ws)) == {
        "evil": 403,
        "rebind": 403,
        "ui": 200,
    }
    assert sorted(p.name for p in ws.iterdir()) == ["ui.txt"], "a refused upload wrote"


def test_upload_cannot_escape_workspace(tmp_path):
    """`startswith` passed "../workspace_x/..." (a sibling sharing the prefix),
    and mkdir(parents=True) then created the escape directory itself."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "keep.txt").write_text("original")

    async def go(s, port):
        statuses = []
        for path in (
            "../workspace_x/payload",
            "../workspace/../outside.txt",
            "../../outside.txt",
            "/../outside.txt",
        ):
            async with s.post(
                f"http://127.0.0.1:{port}/api/workspace/upload",
                params={"path": path},
                data=_upload_form(),
                headers={"Origin": f"http://localhost:{port}"},
            ) as r:
                statuses.append(r.status)
        async with s.post(
            f"http://127.0.0.1:{port}/api/workspace/upload",
            params={"path": "sub/dir/ok.txt"},
            data=_upload_form(b"fine"),
            headers={"Origin": f"http://localhost:{port}"},
        ) as r:
            statuses.append(r.status)
        return statuses

    assert asyncio.run(_with_upload_server(go, ws)) == [400, 400, 400, 400, 200]
    assert not (tmp_path / "workspace_x").exists(), "escape dir was created"
    assert not (tmp_path / "outside.txt").exists()
    assert (ws / "sub" / "dir" / "ok.txt").read_bytes() == b"fine"
    assert (ws / "keep.txt").read_text() == "original"


def test_attachment_name_is_not_a_path(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()

    async def go(s, port):
        names = []
        for name in ("../../../escaped.txt", r"..\..\escaped2.txt", "..", "ok.txt"):
            async with s.post(
                f"http://127.0.0.1:{port}/api/chat-attachments/upload",
                params={"name": name},
                data=_upload_form(),
                headers={"Origin": f"http://localhost:{port}"},
            ) as r:
                assert r.status == 200, (name, r.status)
                names.append((await r.json())["name"])
        return names

    names = asyncio.run(_with_upload_server(go, ws))
    assert names == ["escaped.txt", "escaped2.txt", "attachment", "ok.txt"]
    written = sorted(p.name.split("_", 1)[1] for p in (ws / "download").iterdir())
    assert written == ["attachment", "escaped.txt", "escaped2.txt", "ok.txt"]
    assert not list(tmp_path.glob("escaped*")), "attachment escaped the workspace"
