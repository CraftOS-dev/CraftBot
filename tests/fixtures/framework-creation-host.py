"""Disposable real CLI/host for creation, re-scaffolding and browser navigation."""
# ruff: noqa: E402 -- isolate the profile before importing CraftBot modules.
import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
STATE = Path(sys.argv[1]).resolve()
os.environ.update(CRAFTBOT_HOME=str(STATE), A2APP_HOME=str(STATE / "registry"), VITE_PORT="7935")

from aiohttp import web
from agent_core.core.state.session import StateSession
from app.agent_app import framework
from app.agent_app.framework_commands import command
from app.agent_app.framework_host import FrameworkHost
from app.agent_app.framework_store import HostStore
from app.ui_layer.adapters.ws_auth import WsAuth
from tests.test_agent_app_framework_host import Sessions


async def main():
    sockets = set()
    sessions = Sessions()
    host = FrameworkHost(SimpleNamespace(
        session_manager=sessions, trigger_service=SimpleNamespace(emit=AsyncMock()),
        request_run_stop=AsyncMock(),
    ), store=HostStore(STATE / "host.sqlite3"))
    created = await host.workflow("create", "A todo list", creation={"name": "Todo list", "authMode": "none"})
    assert Path(created["path"]).resolve().is_relative_to(STATE)

    async def scaffold(blueprint):
        with patch.object(StateSession, "bound", lambda: SimpleNamespace(session_id=created["sessionId"])):
            result = await command("agent-app", [created["path"], "scaffold", "--blueprint", blueprint])
        assert result["status"] == "success", result
        return result["data"]["id"]

    first_id = await scaffold("blueprint-base")
    research_path = str(STATE / "research")
    result = await command("agent-app", [research_path, "scaffold", "--blueprint", "blueprint-base", "--name", "Research Board"])
    assert result["status"] == "success", result
    research = await host.attach(research_path, result["data"]["id"])
    histories = {
        created["sessionId"]: "I am building your Todo list.",
        research["sessionId"]: "This is the Research Board conversation.",
    }

    async def changed():
        if not sockets:
            return
        inventory = await framework.list_apps()
        info = [{
            "id": s.id, "type": s.type, "title": s.title,
            "createdAt": s.created_at, "lastActiveAt": s.last_active_at,
            "agentAppFrameworkKey": s.agent_app_framework_key,
            "agentAppFrameworkPending": s.agent_app_framework_pending,
            "agentAppBuild": host.build_info(s),
        } for s in sessions.sessions.values()]
        for ws in list(sockets):
            await ws.send_json({"type": "session_list", "data": {"sessions": info}})
            await ws.send_json({"type": "agent_app_framework_list", "data": inventory})
            for sid, content in histories.items():
                await ws.send_json({"type": "chat_history", "data": {
                    "sessionId": sid, "hasMore": False, "messages": [{
                        "messageId": sid + "-message", "sender": "CraftBot", "style": "agent",
                        "content": content, "timestamp": 1,
                    }],
                }})

    host.changed = changed
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
                        response = {"status": "success", "result": await host.request(data)}
                    except Exception as exc:
                        response = {"status": "error", "message": str(exc)}
                    await ws.send_json({"type": "agent_app_framework_response", "data": {"requestId": data["requestId"], **response}})
                elif kind == "agent_app_framework_open":
                    result = await framework.open_app_view(data["path"], data["appId"])
                    await ws.send_json({"type": kind, "data": {**data, **result}})
        finally:
            sockets.discard(ws)
        return ws

    async def control(request):
        if request.headers.get("X-Test-Token") != auth.token:
            raise web.HTTPForbidden()
        if request.path == "/shutdown":
            done.set()
            return web.json_response({"ok": True})
        with patch.object(StateSession, "bound", lambda: SimpleNamespace(session_id=created["sessionId"])):
            removed = await command("agent-app", [created["path"], "remove", "--yes"])
        assert removed["status"] == "success", removed
        second_id = await scaffold("blueprint-react-node")
        return web.json_response({"firstId": first_id, "secondId": second_id, "sessions": len(sessions.sessions)})

    app = web.Application()
    app.router.add_get("/ws", socket_handler)
    app.router.add_post("/rescaffold", control)
    app.router.add_post("/shutdown", control)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    auth = WsAuth(port)
    print(json.dumps({"url": f"http://127.0.0.1:{port}", "token": auth.token, **created}), flush=True)
    try:
        await done.wait()
    finally:
        await host.close()
        for ws in list(sockets):
            await ws.close()
        await runner.cleanup()


asyncio.run(main())
