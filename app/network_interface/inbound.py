# -*- coding: utf-8 -*-
"""
app.network_interface.inbound

aiohttp handler factories + `register_routes` for the dashboard-facing pull
endpoints. The actual server (Application + AppRunner + TCPSite) lives in
`app.network_interface.server` and is owned by agent_base — running
independently of any UI adapter so the dashboard can reach the agent in CLI
mode too. This file is just the routing/auth layer.

Routes:
    GET /__cb/state                → snapshot.build_state_snapshot
    GET /__cb/events?since=&limit= → snapshot.build_events_snapshot
    GET /__cb/healthz              → unauthenticated liveness probe (safe for
                                     load-balancer health checks; never
                                     returns secrets)

Auth: `Authorization: Bearer <CONTAINER_AUTH_TOKEN>`. The dashboard proxy at
`/api/instances/:id/proxy/*` already injects the same secret on every
request, so the browser → dashboard → container hop authenticates end-to-end
with the per-instance shared secret. Slice-1's `requireInstanceAuth`
middleware on the dashboard side is the mirror of this check.

Why aiohttp and not FastAPI: the agent already depends on aiohttp (the
browser UI uses it), so reusing it costs nothing. Adding FastAPI just to
serve two GETs would double the runtime footprint for no benefit.
"""

from __future__ import annotations

from hmac import compare_digest
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

from app.network_interface.config import get_config, is_enabled
from app.network_interface.snapshot import (
    build_events_snapshot,
    build_state_snapshot,
)

try:
    from app.logger import logger
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from aiohttp import web


# Path prefix for all dashboard-facing endpoints. Matches the `/__cbauth`
# convention from docs/container-access.md — `__cb` marks "craftbot.live
# control plane" and shouldn't collide with anything the user routes to.
INBOUND_PREFIX = "/__cb"


# ───────────────────────────────────────────────────────────────────────────
# Auth helpers
# ───────────────────────────────────────────────────────────────────────────


def _extract_bearer(header: Optional[str]) -> Optional[str]:
    if not header:
        return None
    if not header.lower().startswith("bearer "):
        return None
    return header[7:].strip() or None


def _check_auth(request: "web.Request") -> bool:
    """Constant-time compare against CONTAINER_AUTH_TOKEN. Returns False (and
    the handler should answer 401) when:
      - the network interface is disabled (no env vars) — refusing all calls
        prevents leaking state from a misconfigured deployment;
      - the Authorization header is missing or not bearer;
      - the token doesn't match.
    """
    cfg = get_config()
    if not cfg.enabled:
        return False
    provided = _extract_bearer(request.headers.get("Authorization"))
    if provided is None:
        return False
    # compare_digest needs equal-length inputs; pad on length mismatch so we
    # always do a full constant-time compare and don't leak length info.
    a = provided.encode("utf-8")
    b = cfg.auth_token.encode("utf-8")
    if len(a) != len(b):
        # Compare against itself to keep the timing identical, then fail.
        compare_digest(a, a)
        return False
    return compare_digest(a, b)


# ───────────────────────────────────────────────────────────────────────────
# Handlers
# ───────────────────────────────────────────────────────────────────────────


HandlerFn = Callable[["web.Request"], Awaitable[Any]]


def _make_state_handler(task_manager: Any) -> HandlerFn:
    from aiohttp import web

    async def handler(request: "web.Request") -> "web.Response":
        if not _check_auth(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            body = build_state_snapshot(task_manager)
            return web.json_response(body)
        except Exception as exc:
            logger.warning(f"[network_interface] /state failed: {exc}")
            return web.json_response({"error": "snapshot_failed"}, status=500)

    return handler


def _make_events_handler(event_stream_manager: Any) -> HandlerFn:
    from aiohttp import web

    async def handler(request: "web.Request") -> "web.Response":
        if not _check_auth(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        since = request.rel_url.query.get("since") or None
        limit_raw = request.rel_url.query.get("limit")
        try:
            limit = int(limit_raw) if limit_raw is not None else 50
        except ValueError:
            return web.json_response({"error": "invalid limit"}, status=400)
        try:
            body = build_events_snapshot(
                event_stream_manager,
                since_iso=since,
                limit=limit,
            )
            return web.json_response(body)
        except Exception as exc:
            logger.warning(f"[network_interface] /events failed: {exc}")
            return web.json_response({"error": "snapshot_failed"}, status=500)

    return handler


async def _healthz(request: "web.Request") -> Any:
    """Public liveness probe — no auth, no state. Useful for the dashboard's
    `waitForContainerReady` probe to confirm the agent's HTTP layer is up
    before flipping `Instance.status` to running."""
    from aiohttp import web

    return web.json_response({"ok": True, "enabled": is_enabled()})


# ───────────────────────────────────────────────────────────────────────────
# Registration
# ───────────────────────────────────────────────────────────────────────────


def register_routes(
    app: "web.Application",
    *,
    task_manager: Any,
    event_stream_manager: Any,
) -> None:
    """Attach the dashboard pull endpoints to an existing aiohttp Application.

    Safe to call when the network interface is disabled — the routes are still
    registered, they just answer 401 for /state and /events (healthz stays
    public). That keeps the surface stable across dev and prod so the
    dashboard's probe code can assume the URL exists either way.
    """
    app.router.add_get(f"{INBOUND_PREFIX}/healthz", _healthz)
    app.router.add_get(
        f"{INBOUND_PREFIX}/state",
        _make_state_handler(task_manager),
    )
    app.router.add_get(
        f"{INBOUND_PREFIX}/events",
        _make_events_handler(event_stream_manager),
    )
    if is_enabled():
        logger.info(f"[network_interface] inbound routes mounted at {INBOUND_PREFIX}/*")
    else:
        logger.info(
            f"[network_interface] inbound routes mounted at {INBOUND_PREFIX}/* "
            "(auth disabled — 401 until CONTAINER_AUTH_TOKEN is set)"
        )
