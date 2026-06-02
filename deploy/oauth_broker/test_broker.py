"""Smoke tests for the OAuth broker routing. Run: python test_broker.py"""

import asyncio

from aiohttp.test_utils import TestClient, TestServer

from broker import make_app

CFG = {
    "base_domain": "craft-dev.com",
    "host": "127.0.0.1",
    "port": 0,
    "callback_path": "/oauth/callback",
    "scheme": "https",
}


async def _run():
    client = TestClient(TestServer(make_app(CFG)))
    await client.start_server()
    try:
        # Happy path: tenant parsed from state, full query preserved, 302 to subdomain.
        r = await client.get(
            "/oauth/callback",
            params={"code": "abc123", "state": "user1.RANDXYZ", "scope": "email"},
            allow_redirects=False,
        )
        assert r.status == 302, r.status
        loc = r.headers["Location"]
        assert loc.startswith("https://user1.craft-dev.com/oauth/callback?"), loc
        assert "code=abc123" in loc and "state=user1.RANDXYZ" in loc and "scope=email" in loc, loc
        print("ok: happy path ->", loc)

        # Missing state -> 400, never redirects.
        r = await client.get("/oauth/callback", params={"code": "x"}, allow_redirects=False)
        assert r.status == 400, r.status
        print("ok: missing state -> 400")

        # Hostile first-segment (path/host/scheme injection attempt) -> 400.
        # The tenant is the text before the first dot; anything outside a DNS
        # label there must be rejected. (".tok" -> empty tenant.)
        for bad_state in ["UPPER.tok", "has space.tok", "a/b.tok", "a:b.tok", ".tok"]:
            r = await client.get(
                "/oauth/callback",
                params={"code": "x", "state": bad_state},
                allow_redirects=False,
            )
            assert r.status == 400, (bad_state, r.status)
        print("ok: hostile first-segments rejected")

        # Legitimate multi-dot state: tenant is just the first segment.
        r = await client.get(
            "/oauth/callback",
            params={"code": "x", "state": "user2.a.b.c"},
            allow_redirects=False,
        )
        assert r.status == 302 and r.headers["Location"].startswith(
            "https://user2.craft-dev.com/oauth/callback?"
        ), r.headers.get("Location")
        print("ok: multi-dot state -> tenant = first segment")

        # Health check.
        r = await client.get("/healthz")
        assert r.status == 200 and await r.text() == "ok"
        print("ok: healthz")
    finally:
        await client.close()

    print("\nALL PASSED")


if __name__ == "__main__":
    asyncio.run(_run())
