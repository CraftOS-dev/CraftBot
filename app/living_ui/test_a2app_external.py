"""External A2App adapter acceptance (spec docs/design/
external-app-a2app-adapter.md): the manifest validator enforces the
external executor contract, and the proxy serves the protocol surface —
identity, describe, _ops, guarded op invocation mapped onto a real
upstream app, passthrough — with native-parity auth and error envelopes.

Run:  python3 -m app.living_ui.test_a2app_external

Style follows test_data_safety.py / test_trigger_plane.py: a module-level
assert script, no pytest. A real aiohttp upstream app stands in for the
adopted third-party codebase; the proxy under test is the production
class, bound to loopback ports.
"""

import asyncio
import json
import tempfile
from pathlib import Path

from app.living_ui.a2app_proxy import (
    ExternalA2AppProxy,
    _fill_template,
    _validate_params,
)
from app.living_ui.ops_manifest import (
    op_route,
    synthesize_params,
    validate_external_manifest,
)
from app.living_ui.ops_verify import verify_external_ops

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

    app = web.Application()
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
    auth = {"X-LUI-Token": TOKEN, "X-LUI-Agent": "test-suite"}

    async with aiohttp.ClientSession() as http:
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

        # auth: mutation without token -> 401; GET needs none
        async with http.post(f"{base}/api/ops/todos/create", json={"title": "x"}) as r:
            assert r.status == 401 and (await r.json())["code"] == "unauthorized"
        async with http.get(f"{base}/api/ops/todos/list") as r:
            assert r.status == 200

        # origin guard: foreign-origin mutation refused outright; loopback ok
        async with http.post(
            f"{base}/api/ops/todos/create",
            json={"title": "evil"},
            headers={"Origin": "https://evil.example"},
        ) as r:
            assert r.status == 403 and (await r.json())["code"] == "forbidden_origin"
        async with http.post(
            f"{base}/api/ops/todos/create",
            json={"title": "ui"},
            headers={"Origin": f"http://127.0.0.1:{PROXY_PORT}"},
        ) as r:
            assert r.status == 200
            assert r.headers["Access-Control-Allow-Origin"] == (
                f"http://127.0.0.1:{PROXY_PORT}"
            )

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
            assert r.status == 200 and len(await r.json()) == 2

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
