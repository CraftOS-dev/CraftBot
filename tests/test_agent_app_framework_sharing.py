import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.agent_app import framework
from app.agent_app.framework_sharing import ShareGateway, FrameworkSharing
from app.agent_app.sharing import LanChannel


def test_share_requires_link_preserves_account_auth_and_revokes_streams():
    async def check():
        identity = {"a2app": True, "app": {"id": "fixture"}}
        received = []

        async def handle(request):
            if request.path == "/api/_a2app":
                return web.json_response(identity)
            received.append(dict(request.headers))
            if request.path == "/ws":
                ws = web.WebSocketResponse()
                await ws.prepare(request)
                async for msg in ws:
                    await ws.send_str(msg.data)
                return ws
            return web.json_response(
                {
                    "cookie": request.headers.get("Cookie"),
                    "token": request.headers.get("X-A2App-Token"),
                }
            )

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handle)
        upstream = TestServer(app)
        await upstream.start_server()
        gateway = ShareGateway(upstream.port, "fixture")
        port = await gateway.start()
        origin = f"http://127.0.0.1:{port}"
        gateway.origin = origin
        try:
            async with aiohttp.ClientSession(
                cookie_jar=aiohttp.DummyCookieJar()
            ) as client:
                assert (await client.get(origin)).status == 401
                assert (
                    await client.get(origin, headers={"Host": "evil.example"})
                ).status == 403
                exchanged = await client.get(
                    origin + "/?a2app_share=" + gateway.secret, allow_redirects=False
                )
                assert exchanged.status == 303
                assert "a2app_share" not in exchanged.headers["Location"]
                assert exchanged.cookies[gateway.cookie]["httponly"]
                cookie = f"{gateway.cookie}={gateway.secret}; a2app_session_fixture=member-session"
                headers = {
                    "Cookie": cookie,
                    "Origin": origin,
                    "X-Forwarded-Host": "evil.example",
                }
                good = await client.post(origin + "/api", headers=headers)
                assert good.status == 200
                assert await good.json() == {
                    "cookie": "a2app_session_fixture=member-session",
                    "token": None,
                }
                assert received[-1]["Origin"] == f"http://127.0.0.1:{upstream.port}"
                assert "X-Forwarded-Host" not in received[-1]
                assert (
                    await client.post(
                        origin + "/api",
                        headers={**headers, "Origin": "https://evil.example"},
                    )
                ).status == 403
                assert (
                    await client.post(origin + "/api", headers={"Cookie": cookie})
                ).status == 403
                # No cookies/credentials leak between visitors in the relay session.
                other = await client.get(
                    origin + "/api",
                    headers={"Cookie": f"{gateway.cookie}={gateway.secret}"},
                )
                assert (await other.json())["cookie"] is None
                identity["app"]["id"] = "different"
                assert (
                    await client.get(origin + "/api", headers=headers)
                ).status == 502
                identity["app"]["id"] = "fixture"
                ws = await client.ws_connect(origin + "/ws", headers=headers)
                await ws.send_str("hello")
                assert (await ws.receive()).data == "hello"
                await gateway.stop()
                message = await asyncio.wait_for(ws.receive(), 3)
                assert message.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                }
        finally:
            await gateway.stop()
            await upstream.close()

    asyncio.run(check())


def test_share_transports_are_scoped_and_cleaned_up_without_project_writes(
    tmp_path, monkeypatch
):
    host = SimpleNamespace(
        store=SimpleNamespace(path=tmp_path / "state.sqlite3"),
        selected=AsyncMock(return_value={"status": "running"}),
    )
    tunnel = SimpleNamespace(
        _connect=AsyncMock(return_value="https://fixture.example"),
        _disconnect=AsyncMock(),
    )
    sharing = FrameworkSharing(
        host, SimpleNamespace(sharing=SimpleNamespace(channel=lambda _: tunnel))
    )
    monkeypatch.setattr(
        framework,
        "open_app_view",
        AsyncMock(
            return_value={"status": "success", "data": {"url": "http://127.0.0.1:8123"}}
        ),
    )
    monkeypatch.setattr(LanChannel, "lan_ip", lambda: "127.0.0.1")

    async def check():
        try:
            first = await sharing.open("/one", "same-id", "lan")
            second = await sharing.open("/two", "same-id", "lan")
            assert first != second
            await sharing.close_app("/one", "same-id")
            assert sharing.links("/one", "same-id") == {}
            assert sharing.links("/two", "same-id") == second
            public = await sharing.open("/two", "same-id", "tunnel")
            assert public["tunnel"].startswith("https://fixture.example/?a2app_share=")
            await sharing.close("/two", "same-id", "tunnel")
            tunnel._disconnect.assert_awaited_once()
            tunnel._connect.side_effect = RuntimeError("tunnel unavailable")
            with pytest.raises(RuntimeError, match="unavailable"):
                await sharing.open("/two", "same-id", "tunnel")
            assert "tunnel" not in sharing.links("/two", "same-id")
            assert not list(tmp_path.iterdir())
        finally:
            await sharing.shutdown()
        assert not sharing.active

    asyncio.run(check())
