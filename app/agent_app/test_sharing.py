"""Share channels: the LAN relay's transport and the channel lifecycle.

The guard side of LAN sharing (who gets in) is pinned end to end in
test_a2app_external.py (_lan_matrix) and test_a2app_native_auth.py
(_lan_suite). This file pins what those do not reach: the relay forwards
faithfully (WebSockets, repeated Set-Cookie) while stamping every request as
remote, and a channel's open/close leaves exactly one grant behind or none.

Run:  python -m app.agent_app.test_sharing

Style follows test_data_safety.py: a module-level assert script, no pytest.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.agent_app.sharing import LanChannel, LanRelay, ShareError, SharingService

UPSTREAM_PORT = 18481
RELAY_PORT = 18482


async def _start_upstream():
    from aiohttp import web

    seen = {}

    async def echo(request):
        seen["headers"] = dict(request.headers)
        resp = web.json_response({"ok": True})
        resp.headers.add("Set-Cookie", "a=1; Path=/")
        resp.headers.add("Set-Cookie", "b=2; Path=/")
        return resp

    async def ws(request):
        seen["ws_headers"] = dict(request.headers)
        sock = web.WebSocketResponse()
        await sock.prepare(request)
        async for msg in sock:
            await sock.send_str("echo:" + msg.data)
        return sock

    app = web.Application()
    app.router.add_get("/echo", echo)
    app.router.add_get("/ws", ws)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", UPSTREAM_PORT).start()
    return runner, seen


async def _check_relay() -> None:
    import aiohttp

    upstream, seen = await _start_upstream()
    relay = LanRelay("127.0.0.1", RELAY_PORT, UPSTREAM_PORT)
    port = await relay.start()
    base = f"http://127.0.0.1:{port}"
    try:
        async with aiohttp.ClientSession() as http:
            # The stamp is SET, never appended: nothing a visitor sends survives.
            async with http.get(
                f"{base}/echo",
                headers={"X-Forwarded-For": "127.0.0.1", "Host": "127.0.0.1"},
            ) as r:
                assert r.status == 200
                cookies = r.headers.getall("Set-Cookie")
                assert len(cookies) == 2, f"every Set-Cookie must survive: {cookies}"
            assert seen["headers"]["X-Forwarded-For"] == "127.0.0.1"  # the real peer
            assert seen["headers"]["X-Forwarded-Proto"] == "http"

            # A second relay on a taken port falls back to any free one.
            clash = LanRelay("127.0.0.1", port, UPSTREAM_PORT)
            other = await clash.start()
            assert other != port, "a taken port must not fail the share"
            await clash.stop()

            # WebSockets: relayed both ways, handshake stamped like HTTP.
            async with http.ws_connect(f"{base}/ws") as sock:
                await sock.send_str("hi")
                msg = await sock.receive(timeout=5)
                assert msg.data == "echo:hi", msg
            assert "X-Forwarded-For" in seen["ws_headers"]

        await relay.stop()
        await relay.stop()  # idempotent
        async with aiohttp.ClientSession() as http:
            try:
                await http.get(f"{base}/echo", timeout=aiohttp.ClientTimeout(total=3))
            except aiohttp.ClientError:
                pass
            else:
                raise AssertionError("a stopped relay must stop listening")
    finally:
        await relay.stop()
        await upstream.cleanup()


print_relay = "§1 LAN relay forwards faithfully and stamps every request: OK"


class _Project:
    def __init__(self, path: Path):
        self.id, self.name, self.path = "p1", "T", str(path)


async def _check_lifecycle(tmp: Path) -> None:
    project = _Project(tmp)
    sharing = SharingService(terminate=lambda proc: proc.kill())
    assert sharing.links(project) == {"lan": None, "tunnel": None}

    try:
        await sharing.open(project, "lan", UPSTREAM_PORT)
    except ShareError as e:
        assert "access token" in str(e)
    else:
        raise AssertionError("shared without an agent token")

    try:
        await sharing.open(project, "bogus", UPSTREAM_PORT)
    except ShareError:
        pass
    else:
        raise AssertionError("unknown channel accepted")

    (tmp / ".agent-token").write_text("tok", encoding="utf-8")
    lan: LanChannel = sharing.channels["lan"]  # type: ignore[assignment]
    lan.lan_ip = staticmethod(lambda: "127.0.0.1")  # no real network in tests
    link = await sharing.open(project, "lan", UPSTREAM_PORT)
    secret = (tmp / ".lan-secret").read_text(encoding="utf-8").strip()
    # The relay prefers the app's own port (free here: no upstream running).
    assert link == f"http://127.0.0.1:{UPSTREAM_PORT}/?a2app_share={secret}", link
    assert sharing.links(project) == {"lan": link, "tunnel": None}

    # Re-opening is a fresh share: the old link must stop working.
    again = await sharing.open(project, "lan", UPSTREAM_PORT)
    assert again != link, "re-open must mint a new secret"
    assert len(lan._relays) == 1, "re-open must not leak the old relay"

    await sharing.close_all(project)
    assert sharing.links(project) == {"lan": None, "tunnel": None}
    assert not (tmp / ".lan-origin").exists() and not (tmp / ".lan-secret").exists()
    assert not lan._relays

    # A LAN grant left behind by a previous CraftBot has no relay: revoked.
    (tmp / ".lan-origin").write_text("http://192.168.1.5:3101", encoding="utf-8")
    (tmp / ".lan-secret").write_text("stale", encoding="utf-8")
    lan.restore(project)
    assert not (tmp / ".lan-origin").exists() and not (tmp / ".lan-secret").exists()


print_lifecycle = "§2 channels open, re-open and close to exactly one grant or none: OK"


asyncio.run(_check_relay())
print(print_relay)

with tempfile.TemporaryDirectory() as _tmp:
    asyncio.run(_check_lifecycle(Path(_tmp)))
    print(print_lifecycle)

print("sharing: all checks OK")
