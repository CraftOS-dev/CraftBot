"""External A2App adapter acceptance (spec docs/design/
external-app-a2app-adapter.md): the manifest validator enforces the
external executor contract, and the proxy serves the protocol surface —
identity, describe, _ops, guarded op invocation mapped onto a real
upstream app, passthrough — with native-parity auth and error envelopes.

Run:  python3 -m app.agent_app.test_a2app_external

Style follows test_data_safety.py / test_trigger_plane.py: a module-level
assert script, no pytest. A real aiohttp upstream app stands in for the
adopted third-party codebase; the proxy under test is the production
class, bound to loopback ports.
"""

import asyncio
import json
import tempfile
from pathlib import Path

from app.agent_app.a2app_proxy import (
    ExternalA2AppProxy,
    _fill_template,
    _validate_params,
)
from app.agent_app.ops_manifest import (
    op_route,
    synthesize_params,
    validate_external_manifest,
)
from app.agent_app.ops_verify import verify_external_ops

PROXY_PORT = 18471
UPSTREAM_PORT = 18472
TOKEN = "test-agent-token"


def _op(name, method="POST", upstream=None, params=None, **extra):
    entry = {
        "name": name,
        "description": f"test op {name}",
        "executor": {
            "type": "http",
            "method": method,
            "path": op_route(name),
            "upstream": upstream or {"method": "POST", "path": "/api/todos"},
        },
    }
    if params:
        entry["params"] = params
    entry.update(extra)
    return entry


MANIFEST = {
    "opsVersion": 1,
    "operations": [
        _op(
            "todos.create",
            params={
                "title": {"type": "string", "required": True},
                "done": {"type": "boolean", "default": False},
                "priority": {
                    "type": "string",
                    "enum": ["low", "high"],
                    "default": "low",
                },
            },
            upstream={
                "method": "POST",
                "path": "/api/todos",
                "body": {"title": "{{title}}", "completed": "{{done}}"},
            },
        ),
        _op(
            "todos.list",
            method="GET",
            upstream={"method": "GET", "path": "/api/todos"},
        ),
        _op(
            "todos.get",
            method="GET",
            params={"id": {"type": "number", "required": True}},
            upstream={"method": "GET", "path": "/api/todos/{{id}}"},
        ),
        _op(
            "todos.boom",
            upstream={"method": "POST", "path": "/boom"},
        ),
        _op(
            "todos.wipe",
            destructive=True,
            upstream={"method": "DELETE", "path": "/api/todos"},
        ),
    ],
}


# ── validator ──────────────────────────────────────────────────────────────


def test_validator() -> None:
    assert validate_external_manifest(MANIFEST) == []

    bad = json.loads(json.dumps(MANIFEST))
    bad["operations"][0]["executor"]["path"] = "/api/todos"  # bypasses surface
    bad["operations"][1]["executor"]["type"] = "crud"
    bad["operations"][2]["executor"]["upstream"]["path"] = "no-slash"
    bad["operations"].append(bad["operations"][3])  # duplicate name
    bad["operations"].append(
        {
            "name": "Bad Name!",
            "description": "x",
            "executor": {
                "type": "http",
                "method": "POST",
                "path": "/api/ops/x",
                "upstream": {"method": "POST", "path": "/x"},
            },
        }
    )
    problems = "\n".join(validate_external_manifest(bad))
    assert "executor.path must be '/api/ops/todos/create'" in problems
    assert "not supported for external apps" in problems
    assert "starting with '/'" in problems
    assert "duplicate op name: todos.boom" in problems
    assert "invalid op name" in problems

    # placeholder must name a declared param
    ghost = {
        "opsVersion": 1,
        "operations": [
            _op(
                "a.b",
                upstream={"method": "GET", "path": "/x/{{ghost}}"},
            )
        ],
    }
    ghost["operations"][0]["executor"]["method"] = "GET"
    assert any(
        "names no declared param" in p for p in validate_external_manifest(ghost)
    )
    print("validator: OK")


def test_param_validation() -> None:
    op = MANIFEST["operations"][0]  # todos.create
    values, violations = _validate_params(op, {"title": "x"})
    assert violations == []
    assert values == {"title": "x", "done": False, "priority": "low"}

    _, violations = _validate_params(
        op, {"bogus": 1, "done": "maybe", "priority": "urgent"}
    )
    codes = sorted(v["code"] for v in violations)
    assert codes == [
        "invalid_boolean",
        "invalid_enum",
        "missing_param",
        "unknown_param",
    ], codes

    # query-string numbers coerce; template keeps types
    gop = MANIFEST["operations"][2]  # todos.get
    values, violations = _validate_params(gop, {"id": "7"})
    assert violations == [] and values == {"id": 7}
    body = _fill_template(
        {"title": "{{title}}", "done": "{{done}}", "note": "t={{title}}"},
        {"title": "x", "done": True},
    )
    assert body == {"title": "x", "done": True, "note": "t=x"}

    assert synthesize_params(op) == {
        "title": "a2app verify",
        "done": False,
        "priority": "low",
    }
    print("param validation: OK")


# ── proxy end-to-end ───────────────────────────────────────────────────────


async def _start_upstream():
    from aiohttp import web

    seen = {"todos": []}

    async def root(_request):
        return web.Response(text="UPSTREAM OK", content_type="text/html")

    async def create_todo(request):
        body = await request.json()
        seen["todos"].append(body)
        return web.json_response({"id": len(seen["todos"]), **body})

    async def list_todos(_request):
        return web.json_response(seen["todos"])

    async def get_todo(request):
        idx = int(request.match_info["id"])
        if idx > len(seen["todos"]):
            return web.json_response({"error": "no such todo"}, status=404)
        return web.json_response(seen["todos"][idx - 1])

    async def boom(_request):
        return web.json_response({"error": "kaboom"}, status=500)

    async def wipe(_request):
        seen["todos"] = []
        return web.json_response({"ok": True})

    # The app's native API as a typical adopted codebase ships it: wide-open
    # CORS (the thing the proxy must NOT reflect) and more than one cookie.
    async def echo(request):
        seen.setdefault("echo", []).append(request.method)
        resp = web.json_response({"method": request.method})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Custom"
        resp.headers["Vary"] = "Accept-Encoding"
        resp.set_cookie("app_a", "1")
        resp.set_cookie("app_b", "2")
        return resp

    async def ws_echo(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        seen.setdefault("ws", []).append(request.headers.get("Origin", ""))
        async for msg in ws:
            await ws.send_str("echo:" + msg.data)
        return ws

    app = web.Application()
    app.router.add_route("*", "/api/echo", echo)
    app.router.add_get("/ws", ws_echo)
    app.router.add_get("/", root)
    app.router.add_post("/api/todos", create_todo)
    app.router.add_get("/api/todos", list_todos)
    app.router.add_get("/api/todos/{id}", get_todo)
    app.router.add_post("/boom", boom)
    app.router.add_delete("/api/todos", wipe)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", UPSTREAM_PORT)
    await site.start()
    return runner, seen


class _Project:
    def __init__(self, path: Path):
        self.id, self.name, self.path = "ext123", "ext-test", str(path)
        self.port, self.status = PROXY_PORT, "running"
        self.project_type = "external"


SHARED = "https://shared-demo.trycloudflare.com"
# What cloudflared delivers: Cloudflare's stamps plus the public Host.
VIA_TUNNEL = {
    "Host": "shared-demo.trycloudflare.com",
    "Cf-Ray": "8c0ffee-LHR",
    "Cf-Connecting-Ip": "203.0.113.9",
    "X-Forwarded-For": "203.0.113.9",
}


def _set_cookie(resp) -> "tuple[str, str]":
    """(name, value) from the response's A2App session Set-Cookie."""
    for raw in resp.headers.getall("Set-Cookie", []):
        pair = raw.split(";", 1)[0]
        if pair.startswith("a2app_s_"):
            name, _, value = pair.partition("=")
            return name, value
    raise AssertionError("no a2app session cookie issued")


async def _auth_matrix(http, base: str, tmp: Path, seen) -> None:
    """The auth bypass (allowed Origin skipped the token check) and the
    browser-session design that replaced it. Origin and caller are
    independent: an allowed Origin never authenticates anything."""
    create = f"{base}/api/ops/todos/create"
    loopback = {"Origin": f"http://127.0.0.1:{PROXY_PORT}"}
    before = len(seen["todos"])

    async def post(headers, cookie=None, title="x"):
        h = dict(headers)
        if cookie:
            h["Cookie"] = f"{cookie[0]}={cookie[1]}"
        async with http.post(create, json={"title": title}, headers=h) as r:
            return r.status, await r.json()

    # ── refused ──
    status, body = await post({"Origin": "https://evil.example"})
    assert status == 403 and body["code"] == "forbidden_origin", body
    status, _ = await post({"Origin": "https://evil.example", **{"X-A2App-Token": TOKEN}})
    assert status == 403, "a token does not launder a foreign origin"
    for label, headers in (
        ("no Origin, no token", {}),
        ("no Origin, wrong token", {"X-A2App-Token": "nope"}),
        ("loopback Origin, no token", loopback),
        ("other loopback port, no token", {"Origin": "http://localhost:1"}),
        ("loopback Origin, wrong token", {**loopback, "X-A2App-Token": "nope"}),
        ("token prefix", {"X-A2App-Token": TOKEN[:-1]}),
    ):
        status, body = await post(headers)
        assert status == 401 and body["code"] == "unauthorized", (label, status)
    (tmp / ".tunnel-origin").write_text(SHARED, encoding="utf-8")
    status, _ = await post({"Origin": SHARED})
    assert status == 401, "shared Origin alone must not authenticate"
    status, _ = await post({"Origin": SHARED, "X-A2App-Token": "nope"})
    assert status == 401
    assert len(seen["todos"]) == before, "a refused write reached the app"

    # reads stay open locally
    async with http.get(f"{base}/api/ops/todos/list") as r:
        assert r.status == 200

    # ── the agent: token, with or without an Origin ──
    status, _ = await post({"X-A2App-Token": TOKEN}, title="agent")
    assert status == 200
    status, _ = await post({**loopback, "X-A2App-Token": TOKEN}, title="agent+origin")
    assert status == 200
    status, _ = await post({"X-LUI-Token": TOKEN}, title="legacy")
    assert status == 200, "legacy header still accepted"

    # ── the app's own UI, locally: the page that boots it issues the session
    async with http.get(f"{base}/") as r:
        assert r.status == 200 and (await r.text()) == "UPSTREAM OK"
        local = _set_cookie(r)
        raw = r.headers.getall("Set-Cookie")[0]
        assert "HttpOnly" in raw and "SameSite=Lax" in raw and "Secure" not in raw
    async with http.get(f"{base}/", headers={"Cookie": f"{local[0]}={local[1]}"}) as r:
        assert "Set-Cookie" not in r.headers, "a valid session is not re-issued"
    async with http.get(f"{base}/api/todos") as r:  # JSON: no session minted
        assert "Set-Cookie" not in r.headers
    status, _ = await post(loopback, cookie=local, title="ui")
    assert status == 200
    status, _ = await post(loopback, cookie=(local[0], local[1][:-1] + "0"))
    assert status == 401, "a tampered session is no session"

    # ── through the tunnel ──
    async with http.get(f"{base}/api/_a2app", headers=VIA_TUNNEL) as r:
        body = await r.json()
        assert r.status == 401 and body["code"] == "share_session_required"
    # Either signal alone marks the tunnel: a public Host, or a Cloudflare
    # stamp on a loopback Host.
    for only in ({"Host": VIA_TUNNEL["Host"]}, {"Cf-Ray": VIA_TUNNEL["Cf-Ray"]}):
        async with http.get(f"{base}/api/_a2app", headers=only) as r:
            assert r.status == 401, only
    status, _ = await post({**VIA_TUNNEL, **loopback})
    assert status == 401, "a forged loopback Origin through the tunnel"
    status, _ = await post({**VIA_TUNNEL, "Origin": SHARED}, cookie=local)
    assert status == 401, "a local session is never a tunnel credential"
    async with http.get(f"{base}/", headers=VIA_TUNNEL) as r:
        assert "Set-Cookie" not in r.headers, "tunnel sessions only via the share link"

    secret = "share-secret-for-tests-0123456789abcdef"
    (tmp / ".tunnel-secret").write_text(secret, encoding="utf-8")
    async with http.get(
        f"{base}/?a2app_share=wrong", headers=VIA_TUNNEL, allow_redirects=False
    ) as r:
        assert r.status == 403 and (await r.json())["code"] == "share_link_invalid"
    async with http.get(
        f"{base}/?a2app_share={secret}&tab=2",
        headers=VIA_TUNNEL,
        allow_redirects=False,
    ) as r:
        assert r.status == 302, r.status
        assert r.headers["Location"] == "/?tab=2", "secret must leave the URL"
        shared = _set_cookie(r)
        assert "Secure" in r.headers["Set-Cookie"]
    async with http.get(
        f"{base}/?a2app_share={secret}", allow_redirects=False
    ) as r:
        assert r.status == 200, "locally the parameter means nothing"

    status, _ = await post({**VIA_TUNNEL, "Origin": SHARED}, cookie=shared, title="visitor")
    assert status == 200
    async with http.get(
        f"{base}/api/_a2app",
        headers={**VIA_TUNNEL, "Cookie": f"{shared[0]}={shared[1]}"},
    ) as r:
        assert r.status == 200
    status, _ = await post(loopback, cookie=shared)
    assert status == 401, "a tunnel session is not a local credential"
    status, _ = await post({**VIA_TUNNEL, "X-A2App-Token": TOKEN}, title="remote agent")
    assert status == 200
    async with http.post(
        create, json={"title": "evil"}, headers={**VIA_TUNNEL, "Origin": "https://evil.example",
                                                 "Cookie": f"{shared[0]}={shared[1]}"}
    ) as r:
        assert r.status == 403, "a session does not launder a foreign origin"

    # stopping the tunnel ends every shared session at once
    (tmp / ".tunnel-secret").unlink()
    (tmp / ".tunnel-origin").unlink()
    status, _ = await post({**VIA_TUNNEL, "Origin": SHARED}, cookie=shared)
    assert status in (401, 403)
    titles = [t["title"] for t in seen["todos"][before:]]
    assert titles == ["agent", "agent+origin", "legacy", "ui", "visitor", "remote agent"], titles


async def _passthrough_matrix(http, base: str, tmp: Path, seen) -> None:
    """The app's NATIVE surface (everything not /api/_a2app*, /api/_ops,
    /api/ops/*) under the same guard: it used to be passed through with no
    Origin or caller check, the app's own CORS reflected verbatim, and its
    WebSocket open to any site (browsers apply no CORS to the handshake)."""
    import aiohttp

    echo = f"{base}/api/echo"
    ws_url = f"ws://127.0.0.1:{PROXY_PORT}/ws"
    loopback = {"Origin": f"http://127.0.0.1:{PROXY_PORT}"}
    evil = {"Origin": "https://evil.example"}

    def jar(cookie):
        return {"Cookie": f"{cookie[0]}={cookie[1]}"}

    async def send(method, headers, url=echo):
        before = len(seen.get("echo", []))
        async with http.request(method, url, json={"t": 1}, headers=headers) as r:
            body = await r.json()
            reached = len(seen.get("echo", [])) > before
            return r.status, body, reached

    async def ws(headers):
        """(status, echoed) — status 101 on upgrade, else the refusal."""
        try:
            async with http.ws_connect(ws_url, headers=headers) as w:
                await w.send_str("hi")
                msg = await w.receive(timeout=5)
                return 101, msg.data
        except aiohttp.WSServerHandshakeError as e:
            return e.status, None

    async with http.get(f"{base}/") as r:
        local = _set_cookie(r)

    # ── HTTP writes: foreign origins refused, callers must hold a credential
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        status, body, reached = await send(method, evil)
        assert status == 403 and body["code"] == "forbidden_origin", (method, status)
        assert not reached, f"foreign-origin {method} reached the app"
    status, _, reached = await send("POST", {**evil, "X-A2App-Token": TOKEN})
    assert status == 403 and not reached, "a token does not launder a foreign origin"
    status, _, reached = await send("POST", {**evil, **jar(local)})
    assert status == 403 and not reached, "a session does not launder a foreign origin"
    for label, headers in (
        ("no Origin, no credential", {}),
        ("loopback Origin, no credential", loopback),
        ("wrong token", {"X-A2App-Token": "nope"}),
    ):
        status, body, reached = await send("POST", headers)
        assert status == 401 and body["code"] == "unauthorized", (label, status)
        assert not reached, label
    async with http.post(f"{base}/api/todos", json={"title": "evil"}, headers=evil) as r:
        assert r.status == 403, "a real app route, not just the echo"

    # the app's own UI (loopback page + the session its HTML page issued)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        status, body, reached = await send(method, {**loopback, **jar(local)})
        assert status == 200 and body["method"] == method and reached, method
    # the agent / a local program
    status, _, reached = await send("POST", {"X-A2App-Token": TOKEN})
    assert status == 200 and reached
    # local reads stay open (CORS, below, keeps them from foreign pages)
    status, _, reached = await send("GET", {})
    assert status == 200 and reached

    # ── CORS: the proxy's policy, never the app's `*` ──
    async with http.get(echo, headers=evil) as r:
        acx = [k for k in r.headers if k.lower().startswith("access-control-")]
        assert r.status == 200 and not acx, f"upstream CORS reflected: {acx}"
    other_local = {"Origin": "http://localhost:5173"}
    async with http.get(echo, headers=other_local) as r:
        assert r.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
        assert r.headers["Access-Control-Allow-Credentials"] == "true"
        vary = {v.strip() for v in r.headers["Vary"].split(",")}
        assert vary == {"Accept-Encoding", "Origin"}, vary
        cookies = {c.split("=", 1)[0] for c in r.headers.getall("Set-Cookie")}
        assert {"app_a", "app_b"} <= cookies, "every upstream Set-Cookie survives"
    preflight = {"Access-Control-Request-Method": "PUT"}
    async with http.options(echo, headers={**evil, **preflight}) as r:
        acx = [k for k in r.headers if k.lower().startswith("access-control-")]
        assert not acx, f"foreign preflight granted: {acx}"
    async with http.options(echo, headers={**other_local, **preflight}) as r:
        assert r.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
        assert "PUT" in r.headers["Access-Control-Allow-Methods"]
        assert r.headers["Access-Control-Allow-Headers"] == "Content-Type, X-Custom"

    # ── WebSocket: judged at the handshake, refused before upgrading ──
    ws_seen = len(seen.get("ws", []))
    for label, headers, want in (
        ("foreign Origin", evil, 403),
        ("foreign Origin + token", {**evil, "X-A2App-Token": TOKEN}, 403),
        ("foreign Origin + session", {**evil, **jar(local)}, 403),
        ("no Origin, no credential", {}, 401),
        ("loopback Origin, no credential", loopback, 401),
    ):
        status, _ = await ws(headers)
        assert status == want, (label, status)
    assert len(seen.get("ws", [])) == ws_seen, "a refused handshake reached the app"
    assert await ws({**loopback, **jar(local)}) == (101, "echo:hi"), "the app's own UI"
    assert await ws({"X-A2App-Token": TOKEN}) == (101, "echo:hi"), "the agent"

    # ── through the tunnel ──
    secret = "share-secret-for-passthrough-0123456789"
    (tmp / ".tunnel-origin").write_text(SHARED, encoding="utf-8")
    (tmp / ".tunnel-secret").write_text(secret, encoding="utf-8")
    try:
        async with http.get(f"{base}/", headers=VIA_TUNNEL) as r:
            body = await r.json()
            assert r.status == 401 and body["code"] == "share_session_required", (
                "a bare tunnel URL must not read the app"
            )
        async with http.get(
            f"{base}/?a2app_share={secret}", headers=VIA_TUNNEL, allow_redirects=False
        ) as r:
            assert r.status == 302
            shared = _set_cookie(r)
        visitor = {**VIA_TUNNEL, "Origin": SHARED, **jar(shared)}

        async with http.get(f"{base}/", headers={**VIA_TUNNEL, **jar(shared)}) as r:
            assert r.status == 200 and (await r.text()) == "UPSTREAM OK"
        status, _, reached = await send("POST", visitor)
        assert status == 200 and reached, "the shared UI writes"
        async with http.get(echo, headers=visitor) as r:
            assert r.headers["Access-Control-Allow-Origin"] == SHARED
        assert await ws(visitor) == (101, "echo:hi"), "the shared UI's WebSocket"

        for label, headers, want in (
            ("no session", {**VIA_TUNNEL, "Origin": SHARED}, 401),
            ("forged loopback Origin", {**VIA_TUNNEL, **loopback}, 401),
            ("local session", {**VIA_TUNNEL, "Origin": SHARED, **jar(local)}, 401),
            ("foreign Origin + session", {**VIA_TUNNEL, **evil, **jar(shared)}, 403),
        ):
            status, _, reached = await send("POST", headers)
            assert status == want and not reached, ("http", label, status)
            status, _ = await ws(headers)
            assert status == want, ("ws", label, status)
        status, _, reached = await send("POST", {**VIA_TUNNEL, "X-A2App-Token": TOKEN})
        assert status == 200 and reached, "a remote agent with the token"
    finally:
        (tmp / ".tunnel-secret").unlink(missing_ok=True)
        (tmp / ".tunnel-origin").unlink(missing_ok=True)
    # Let the proxy finish closing its upstream WebSockets while this loop
    # (which also runs the upstream) is still free to answer them.
    await asyncio.sleep(0.3)


async def _proxy_suite(tmp: Path) -> None:
    import aiohttp

    (tmp / "operations.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    (tmp / ".agent-token").write_text(TOKEN, encoding="utf-8")

    upstream_runner, seen = await _start_upstream()
    proxy = ExternalA2AppProxy(
        tmp, PROXY_PORT, UPSTREAM_PORT, "ext123", "ext-test", "python"
    )
    await proxy.start()
    base = f"http://127.0.0.1:{PROXY_PORT}"
    auth = {"X-A2App-Token": TOKEN, "X-A2App-Agent": "test-suite"}

    # No cookie jar: every cookie in this suite is sent deliberately.
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as http:
        # identity: the structural probe
        async with http.get(f"{base}/api/_a2app") as r:
            ident = await r.json()
            assert r.status == 200 and ident["a2app"] is True
            assert ident["flavor"] == "external" and ident["env"] == "live"
            assert ident["app"]["id"] == "ext123"
            assert ident["schemaVersion"].startswith("sv_")

        # describe: ops present, entities deliberately empty
        async with http.get(f"{base}/api/_a2app/describe") as r:
            desc = await r.json()
            assert desc["entities"] == {}
            assert {o["name"] for o in desc["operations"]} == {
                "todos.create",
                "todos.list",
                "todos.get",
                "todos.boom",
                "todos.wipe",
            }
            assert "conventions" in desc

        # _ops: the manifest verbatim
        async with http.get(f"{base}/api/_ops") as r:
            assert (await r.json())["opsVersion"] == 1

        # op invocation: typed body lands upstream via the template
        async with http.post(
            f"{base}/api/ops/todos/create",
            json={"title": "call John"},
            headers=auth,
        ) as r:
            body = await r.json()
            assert r.status == 200, body
            assert body["title"] == "call John"
        assert seen["todos"] == [{"title": "call John", "completed": False}]

        # audit trail written
        audit = (tmp / "logs" / "agent-actions.jsonl").read_text("utf-8")
        entry = json.loads(audit.strip().splitlines()[-1])
        assert entry["agent"] == "test-suite" and entry["op"] == "todos.create"

        # param guard: every violation listed, machine codes
        async with http.post(
            f"{base}/api/ops/todos/create",
            json={"done": "maybe", "bogus": 1},
            headers=auth,
        ) as r:
            body = await r.json()
            assert r.status == 400 and body["a2app"] is True
            codes = sorted(v["code"] for v in body["violations"])
            assert codes == ["invalid_boolean", "missing_param", "unknown_param"]

        # GET op with query params + path placeholder
        async with http.get(f"{base}/api/ops/todos/get", params={"id": "1"}) as r:
            assert r.status == 200 and (await r.json())["title"] == "call John"

        await _auth_matrix(http, base, tmp, seen)
        await _passthrough_matrix(http, base, tmp, seen)

        # unknown op -> 404 envelope, never a silent passthrough
        async with http.post(f"{base}/api/ops/nope", json={}, headers=auth) as r:
            assert r.status == 404
            assert (await r.json())["code"] == "unknown_operation"

        # upstream failure relayed as an envelope, status preserved
        async with http.post(f"{base}/api/ops/todos/boom", json={}, headers=auth) as r:
            body = await r.json()
            assert r.status == 500 and body["code"] == "upstream_error"
            assert body["upstreamStatus"] == 500

        # passthrough: the app's own surface, untouched
        async with http.get(f"{base}/") as r:
            assert r.status == 200 and (await r.text()) == "UPSTREAM OK"
        async with http.get(f"{base}/api/todos") as r:
            assert r.status == 200 and len(await r.json()) == len(seen["todos"])

        # ops_verify drives the real surface: boom must fail the verdict,
        # wipe must be skipped (destructive), the rest pass
        report = await verify_external_ops(_Project(tmp))
        assert report["identity_ok"] is True
        outcomes = {r["op"]: r["outcome"] for r in report["results"]}
        assert outcomes["todos.create"] == "pass"
        assert outcomes["todos.list"] == "pass"
        assert outcomes["todos.wipe"] == "skipped_destructive"
        assert outcomes["todos.boom"] == "upstream_error"
        assert report["status"] == "error"
        assert seen["todos"], "destructive wipe must NOT have been invoked"

        # drop the broken mapping -> clean verdict (the ship gate)
        fixed = {
            "opsVersion": 1,
            "operations": [
                o for o in MANIFEST["operations"] if o["name"] != "todos.boom"
            ],
        }
        (tmp / "operations.json").write_text(json.dumps(fixed), encoding="utf-8")
        report = await verify_external_ops(_Project(tmp))
        assert report["status"] == "success", report["message"]

        # dead upstream -> honest 502 on passthrough, identity still answers
        await upstream_runner.cleanup()
        async with http.get(f"{base}/") as r:
            assert r.status == 502
            assert (await r.json())["code"] == "upstream_unreachable"
        async with http.get(f"{base}/api/_a2app") as r:
            assert r.status == 200

    await proxy.stop()
    print("proxy end-to-end: OK")


def main() -> None:
    test_validator()
    test_param_validation()
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_proxy_suite(Path(tmp)))
    print("ALL EXTERNAL A2APP CHECKS PASSED")


if __name__ == "__main__":
    main()
