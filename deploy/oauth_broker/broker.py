"""Shared OAuth callback broker for multi-tenant CraftBot deployments.

Why this exists
---------------
In the hosted setup every user gets their own Docker container running CraftBot,
all behind one apex domain (e.g. ``craft-dev.com``) with per-user subdomains
(``user1.craft-dev.com``). OAuth providers like Google require the redirect URI
to be **registered exactly** and forbid wildcards — so you cannot register one
URI per user. You also can't let Google redirect straight to a subdomain,
because Google's callback would need to know which container started the flow.

The fix: register a **single** redirect URI on the apex —
``https://craft-dev.com/oauth/callback`` — and point it at this broker. Every
container is told to use that same URI (``CRAFTBOT_OAUTH_BROKER_URL``) and to
bake its tenant id into the OAuth ``state`` (``CRAFTBOT_TENANT_ID``). When the
provider calls back, this broker reads the tenant out of ``state`` and 302-
redirects the browser to that tenant's subdomain, where the waiting container
finishes the token exchange.

No database, no shared state: the routing ticket *is* the ``state`` value.

Flow
----
    Google ──> https://craft-dev.com/oauth/callback?code=…&state=user1.<rand>
                       │  (this broker)
                       │  tenant = "user1"  (text before the first dot)
                       ▼
            302 https://user1.craft-dev.com/oauth/callback?code=…&state=user1.<rand>
                       │
                       ▼
            container "user1" matches state, exchanges code → tokens ✓

Config (environment variables)
------------------------------
    BROKER_BASE_DOMAIN   apex domain, e.g. "craft-dev.com"   (required)
    BROKER_PORT          port to listen on                   (default 8788)
    BROKER_HOST          bind interface                      (default 0.0.0.0)
    BROKER_CALLBACK_PATH path the provider calls back on     (default /oauth/callback)
    BROKER_SCHEME        scheme for the subdomain redirect   (default https)

Run
---
    BROKER_BASE_DOMAIN=craft-dev.com python broker.py

Then point the apex proxy so ``craft-dev.com/oauth/callback`` reaches this
process (see README.md for nginx / Caddy snippets).
"""

from __future__ import annotations

import os
import re

from aiohttp import web

# A tenant id is a single DNS label (the subdomain). Restrict it hard so a
# crafted ``state`` can't smuggle a path, port, host, or scheme into the
# redirect target — only ``[a-z0-9-]`` labels (max 63 chars per DNS rules).
_TENANT_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _config() -> dict:
    base_domain = os.environ.get("BROKER_BASE_DOMAIN", "").strip().lower()
    if not base_domain:
        raise SystemExit("BROKER_BASE_DOMAIN is required (e.g. craft-dev.com)")
    return {
        "base_domain": base_domain,
        "host": os.environ.get("BROKER_HOST", "0.0.0.0"),
        "port": int(os.environ.get("BROKER_PORT", "8788")),
        "callback_path": os.environ.get("BROKER_CALLBACK_PATH", "/oauth/callback"),
        "scheme": os.environ.get("BROKER_SCHEME", "https"),
    }


def _error_page(message: str, status: int) -> web.Response:
    body = (
        "<!doctype html><html><head><meta charset='utf-8'><title>CraftBot</title>"
        "<style>body{font-family:system-ui,sans-serif;background:#111;color:#eee;"
        "display:flex;align-items:center;justify-content:center;height:100vh;margin:0}"
        ".card{text-align:center;max-width:420px;padding:2rem}h2{margin:0 0 .5rem}"
        "</style></head><body><div class='card'><h2>Sign-in failed</h2>"
        f"<p>{message}</p></div></body></html>"
    )
    return web.Response(text=body, content_type="text/html", status=status)


def make_app(cfg: dict) -> web.Application:
    async def handle_callback(request: web.Request) -> web.StreamResponse:
        state = request.query.get("state", "")
        if not state:
            return _error_page("Missing sign-in state. Please try connecting again.", 400)

        # The tenant is everything before the first dot; the random CSRF token is
        # the remainder. ``state`` is preserved end-to-end so the container can
        # still validate it.
        tenant = state.split(".", 1)[0]
        if not _TENANT_RE.match(tenant):
            return _error_page("Invalid sign-in state.", 400)

        # Forward the *entire* original query string unchanged (code, state,
        # scope, error, etc.) to the tenant's own callback.
        target = (
            f"{cfg['scheme']}://{tenant}.{cfg['base_domain']}"
            f"{cfg['callback_path']}?{request.query_string}"
        )
        raise web.HTTPFound(target)

    async def health(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get(cfg["callback_path"], handle_callback)
    app.router.add_get("/healthz", health)
    return app


def main() -> None:
    cfg = _config()
    app = make_app(cfg)
    print(
        f"[oauth-broker] listening on {cfg['host']}:{cfg['port']} "
        f"path={cfg['callback_path']} -> {cfg['scheme']}://<tenant>.{cfg['base_domain']}"
    )
    web.run_app(app, host=cfg["host"], port=cfg["port"])


if __name__ == "__main__":
    main()
