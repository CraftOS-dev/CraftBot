"""Disposable real CLI/host service for browser settings regression tests."""
# ruff: noqa: E402 -- isolate the profile before importing CraftBot modules.

import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
STATE = Path(sys.argv[1]).resolve()
os.environ["CRAFTBOT_HOME"] = str(STATE)
os.environ["A2APP_HOME"] = str(STATE / "registry")
os.environ["VITE_PORT"] = "7935"

from aiohttp import web
from app.agent_app import framework
from app.agent_app.framework_commands import command
from app.agent_app.framework_host import FrameworkHost
from app.agent_app.framework_store import HostStore
from app.ui_layer.adapters.ws_auth import WsAuth


class Sessions:
    def __init__(self):
        self.rows = {}

    def get(self, sid):
        return self.rows.get(sid)

    def create_session(self, **kwargs):
        row = SimpleNamespace(id=uuid.uuid4().hex, **kwargs)
        self.rows[row.id] = row
        return row


async def main():
    folder = STATE / "custom-app"
    (folder / ".a2app").mkdir(parents=True)
    (folder / "data").mkdir()
    (folder / "data/state.txt").write_text("original")
    (folder / ".gitignore").write_text("data/\n")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        app_port = sock.getsockname()[1]
    manifest = {
        "id": "settings-fixture",
        "name": "Settings fixture",
        "port": app_port,
        "authMode": "none",
        "capabilities": {},
        "pipeline": {
            "build": "node build.cjs",
            "start": "node server.cjs",
            "health": "/api/_a2app",
        },
    }
    file = folder / "manifest.json"
    file.write_text(json.dumps(manifest))
    (folder / ".a2app/system-hashes.json").write_text(
        json.dumps(
            {"manifest.json": "sha256:" + hashlib.sha256(file.read_bytes()).hexdigest()}
        )
    )
    (folder / ".a2app/toolkit.json").write_text('{"id":"missing-custom-toolkit"}')
    (folder / "framework.lock.json").write_text('{"blueprint":"blueprint-react-node"}')
    (folder / "build.cjs").write_text("console.log('fixture built')")
    (folder / "server.cjs").write_text(
        "const http=require('http');http.createServer((q,s)=>{if(q.url.startsWith('/api/')){s.setHeader('Content-Type','application/json');s.end(JSON.stringify({a2app:true,app:{id:'settings-fixture'}}))}else{s.setHeader('Content-Type','text/html');s.end('<h1>Disposable settings fixture</h1>')}}).listen(Number(process.env.PORT),'127.0.0.1')"
    )
    home = STATE / "registry"
    home.mkdir()
    stale = STATE / "missing-app"
    unowned = STATE / "unowned-app"
    unowned.mkdir()
    (unowned / "manifest.json").write_text(
        json.dumps({"id": "unowned", "name": "Unowned fixture"})
    )
    (unowned / "keep.txt").write_text("Keep this source and data.")
    (home / "registry.json").write_text(
        json.dumps(
            {
                "version": 1,
                "apps": [
                    {
                        "id": manifest["id"],
                        "name": manifest["name"],
                        "port": app_port,
                        "path": str(folder),
                    },
                    {
                        "id": "stale-fixture",
                        "name": "Missing fixture",
                        "path": str(stale),
                    },
                    {"id": "unowned", "name": "Unowned fixture", "path": str(unowned)},
                ],
            }
        )
    )
    sockets = set()

    async def changed():
        snapshot = await framework.list_apps()
        for ws in list(sockets):
            if not ws.closed:
                await ws.send_json(
                    {"type": "agent_app_framework_list", "data": snapshot}
                )

    host = FrameworkHost(
        SimpleNamespace(session_manager=Sessions()),
        changed,
        HostStore(STATE / "host.sqlite3"),
    )
    # No model, agent work, real-user registry or credentials in this fixture.
    if "--board" in sys.argv[2:]:
        installed = await command(
            "agent-app",
            [
                "install",
                "--from",
                str(ROOT / "app/data/default_agent_app/kanban-board-framework.zip"),
                "--port",
                str(app_port),
            ],
        )
        if installed["status"] != "success":
            raise RuntimeError(installed.get("stderr") or "Fixture install failed")
        folder = Path(installed["data"]["dir"])
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    else:
        await framework.change_app_state(str(folder), manifest["id"], "start")
    done = asyncio.Event()
    auth = None

    async def socket_handler(request):
        if auth.check_ws_handshake(request.headers):
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(protocols=["craftbot"])
        await ws.prepare(request)
        sockets.add(ws)
        await changed()
        try:
            async for message in ws:
                data = json.loads(message.data)
                kind = data.get("type")
                if kind == "agent_app_framework_request":
                    try:
                        value = {
                            "status": "success",
                            "result": await host.request(data),
                        }
                    except Exception as exc:
                        value = {"status": "error", "message": str(exc)}
                    await ws.send_json(
                        {
                            "type": "agent_app_framework_response",
                            "data": {"requestId": data["requestId"], **value},
                        }
                    )
                elif kind == "agent_app_framework_open":
                    result = await framework.open_app_view(data["path"], data["appId"])
                    await ws.send_json({"type": kind, "data": {**data, **result}})
                elif kind == "agent_app_framework_lifecycle":
                    result = await framework.change_app_state(
                        data["path"], data["appId"], data["operation"]
                    )
                    await ws.send_json({"type": kind, "data": {**data, **result}})
                    await changed()
        finally:
            sockets.discard(ws)
        return ws

    async def shutdown(request):
        if request.headers.get("X-Test-Token") != auth.token:
            raise web.HTTPForbidden()
        done.set()
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/ws", socket_handler)
    app.router.add_post("/shutdown", shutdown)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    auth = WsAuth(port)
    print(
        json.dumps(
            {
                "url": f"http://127.0.0.1:{port}",
                "token": auth.token,
                "path": str(folder),
                "stale": str(stale),
            }
        ),
        flush=True,
    )
    try:
        await done.wait()
    finally:
        await host.close()
        if folder.exists():
            await framework.change_app_state(str(folder), manifest["id"], "stop")
        for ws in list(sockets):
            await ws.close()
        await runner.cleanup()


asyncio.run(main())
