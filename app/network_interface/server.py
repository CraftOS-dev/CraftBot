# -*- coding: utf-8 -*-
"""
app.network_interface.server

Standalone aiohttp server hosting the dashboard-facing pull endpoints
(/__cb/state, /__cb/events, /__cb/healthz). Runs independently of any UI
adapter — the browser adapter owns the user-facing port 7926, this server
owns whatever port the dashboard control plane lives on.

Why separate:
  - The dashboard's surface MUST be reachable in any UI mode (CLI, browser,
    or none at all). Mounting it on the browser adapter's app would mean a
    CLI-mode container has no /__cb/* surface — the dashboard would think
    that container is dead.
  - Browser adapter is user-facing UI; it shouldn't carry control-plane code.
  - Two separate servers = independent failure domains. A bug in the user UI
    can't take down the dashboard's read path (and vice versa).

Port: `CONTAINER_INBOUND_PORT` env var, default 7928. Production deployments
should configure the platform-side reverse proxy (Traefik on craftbot-platform)
to route `/__cb/*` on the customer hostname to this port; the rest of the
hostname routes to the browser adapter's port 7926 as today. For local dev
you can hit the port directly: `curl localhost:7928/__cb/healthz`.

Host: 0.0.0.0 inside the container so Traefik in another container can reach
it. The container's network namespace plus Traefik's route rules are the
real perimeter — binding to localhost would defeat external reachability
without buying us extra safety.
"""

from __future__ import annotations

import os
from typing import Any, Optional, TYPE_CHECKING

from app.network_interface.config import is_enabled
from app.network_interface.inbound import register_routes

try:
    from app.logger import logger
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from aiohttp import web


DEFAULT_PORT = 7928
DEFAULT_HOST = "0.0.0.0"


def _resolve_port() -> int:
    """Read CONTAINER_INBOUND_PORT, fall back to DEFAULT_PORT. Invalid values
    fall back too (with a warning) rather than crashing the agent."""
    raw = os.environ.get("CONTAINER_INBOUND_PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
        if not (0 < port < 65536):
            raise ValueError(f"out of range: {port}")
        return port
    except ValueError as exc:
        logger.warning(
            f"[network_interface] invalid CONTAINER_INBOUND_PORT={raw!r} ({exc}); "
            f"falling back to {DEFAULT_PORT}"
        )
        return DEFAULT_PORT


class InboundServer:
    """Owns the aiohttp app + AppRunner + TCPSite for /__cb/* endpoints.

    Lifecycle is driven from agent_base.boot()/shutdown — there is no global
    singleton because the agent decides when its task_manager + event_stream_manager
    are ready to be served (you can't snapshot state from half-initialised
    managers). Pass them in on construction and the server keeps live refs.
    """

    def __init__(
        self,
        *,
        task_manager: Any,
        event_stream_manager: Any,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        self._task_manager = task_manager
        self._event_stream_manager = event_stream_manager
        self._host = host or DEFAULT_HOST
        self._port = port if port is not None else _resolve_port()
        self._app: Optional["web.Application"] = None
        self._runner: Optional["web.AppRunner"] = None
        self._site: Optional["web.TCPSite"] = None
        self._started: bool = False

    @property
    def port(self) -> int:
        return self._port

    @property
    def host(self) -> str:
        return self._host

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        """Create the aiohttp app, mount the routes, bind the TCP site.

        Best-effort: if the port is already in use (another agent process on
        the same host, perhaps), we log and stay degraded rather than crash
        the agent. The dashboard will see missing /__cb/* responses and fall
        back to its placeholder states.

        Safe to call when the network interface is disabled (no env vars) —
        we still start the server so /__cb/healthz answers; /__cb/state and
        /__cb/events answer 401 until CONTAINER_AUTH_TOKEN is set.
        """
        if self._started:
            return

        try:
            from aiohttp import web
        except ImportError:
            logger.warning("[network_interface] aiohttp not installed; inbound server disabled")
            return

        self._app = web.Application()
        register_routes(
            self._app,
            task_manager=self._task_manager,
            event_stream_manager=self._event_stream_manager,
        )

        self._runner = web.AppRunner(self._app)
        try:
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, self._host, self._port)
            await self._site.start()
        except OSError as exc:
            # Port in use, permission denied, etc. Don't crash the agent — the
            # rest of the runtime is independent of the dashboard reachability.
            logger.warning(
                f"[network_interface] inbound server failed to bind "
                f"{self._host}:{self._port}: {exc}"
            )
            # Best-effort cleanup of the half-built runner.
            try:
                await self._runner.cleanup()
            except Exception:
                pass
            self._runner = None
            self._site = None
            self._app = None
            return

        self._started = True
        if is_enabled():
            logger.info(
                f"[network_interface] inbound server listening on "
                f"http://{self._host}:{self._port}/__cb/*"
            )
        else:
            logger.info(
                f"[network_interface] inbound server listening on "
                f"http://{self._host}:{self._port}/__cb/* "
                "(auth disabled — set CONTAINER_AUTH_TOKEN to enable state/events)"
            )

    async def stop(self) -> None:
        """Tear down the server. Idempotent; safe to call without start()."""
        if not self._started:
            # If start() failed mid-setup we might still have a half-built
            # runner that needs cleanup.
            if self._runner is not None:
                try:
                    await self._runner.cleanup()
                except Exception:
                    pass
                self._runner = None
            return
        try:
            if self._site is not None:
                await self._site.stop()
        except Exception as exc:
            logger.warning(f"[network_interface] inbound site stop error: {exc}")
        try:
            if self._runner is not None:
                await self._runner.cleanup()
        except Exception as exc:
            logger.warning(f"[network_interface] inbound runner cleanup error: {exc}")
        self._site = None
        self._runner = None
        self._app = None
        self._started = False
        logger.info("[network_interface] inbound server stopped")
