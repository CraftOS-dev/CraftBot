# -*- coding: utf-8 -*-
"""
app.network_interface.outbound

DashboardClient — the only place the agent writes to the dashboard.

Authentication (mirrors apps/backend/src/middleware/requireInstanceAuth.ts):

    Authorization: Bearer <CONTAINER_AUTH_TOKEN>
    X-Instance-Id:  <CONTAINER_INSTANCE_ID>

Slice 1 only implements `report_usage`. The contract — including the body
shape — must match the dashboard side at
apps/backend/src/api/instance-callback/index.ts.

Resilience policy: outbound calls MUST NOT block LLM work. Every public
method is fire-and-forget — it schedules an async task with bounded retry +
exponential backoff and drops events on a backpressure threshold so a long
dashboard outage cannot grow memory without bound.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from agent_core.core.hooks.types import UsageEventData
from app.network_interface.config import (
    NetworkInterfaceConfig,
    dashboard_endpoint,
    get_config,
)

try:
    from app.logger import logger
except Exception:  # pragma: no cover - import-time fallback for tooling
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# How big the in-memory queue can grow before we start dropping the *oldest*
# event to keep memory bounded. ~30 minutes of LLM activity at one event/sec.
MAX_QUEUE = 2048

# Retry policy for a single event. After this many attempts we drop the event
# and log a warning — the local SQLite mirror still has it, so the truth isn't
# lost; only the dashboard's view of it is.
MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0

# HTTP timeouts (connect, read) — kept short so a wedged dashboard cannot
# stall the worker.
REQUEST_TIMEOUT_SECONDS = 10.0


def _start_of_current_hour_iso() -> str:
    """The dashboard upserts usage rows keyed by (instanceId, periodStart,
    provider, model) where periodStart is the start-of-hour. Defaulting here
    means a client that doesn't supply `period_start` still aggregates into
    the same row as the dashboard's own default."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return now.isoformat()


class DashboardClient:
    """Async outbound client. Singleton via `get_dashboard_client()`."""

    def __init__(self, config: Optional[NetworkInterfaceConfig] = None) -> None:
        self._config: NetworkInterfaceConfig = config or get_config()
        self._client: Optional[httpx.AsyncClient] = None
        # Coarse backpressure counter — number of currently-queued events.
        self._queued: int = 0
        # One warning per outage instead of per failed call, to avoid log floods.
        self._outage_logged: bool = False
        # The agent's long-lived main event loop, captured on the first heartbeat
        # tick (which runs on it). Usage is reported from short-lived LLM
        # worker-thread loops that get torn down immediately, so sends are
        # dispatched onto this loop instead. None until the first heartbeat.
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    async def report_usage(
        self,
        event: UsageEventData,
        *,
        period_start: Optional[str] = None,
        requests: int = 1,
        compute_seconds: int = 0,
        storage_gb: Optional[float] = None,
    ) -> None:
        """Forward a single LLM/VLM usage event to the dashboard.

        BYOK filter: only `provider="craftbot"` events reach the dashboard.
        Every other provider — including BYOK `bedrock` where the user supplies
        their own AWS credentials — is paid for upstream by the user, and
        craftbot.live MUST NOT count those tokens against their plan budget
        or display them in the dashboard's "Managed usage" surfaces. The
        agent's local UsageReporter (SQLite) keeps logging all calls regardless,
        so per-container analytics remain complete.

        Maps `UsageEventData` to the `POST /api/instance-callback/usage` body.
        `requests` defaults to 1 because each event corresponds to one LLM call.

        Fire-and-forget — returns immediately, the actual HTTP call happens
        in a background task. Returns without scheduling anything if the
        interface is disabled OR the event is from a non-managed provider.
        """
        if not self._config.enabled:
            return
        # Single point of truth for the managed-LLM allowlist. Keep in sync
        # with apps/backend/prisma/seed-llm-rates.sql — any provider added
        # there must be added here too.
        if (event.provider or "").lower() != "craftbot":
            return

        body: Dict[str, Any] = {
            "periodStart": period_start or _start_of_current_hour_iso(),
            "provider": event.provider or None,
            "model": event.model or None,
            "requests": requests,
            "tokensInput": int(event.input_tokens or 0),
            "tokensOutput": int(event.output_tokens or 0),
            "tokensCached": int(event.cached_tokens or 0),
            "computeSeconds": int(compute_seconds or 0),
        }
        if storage_gb is not None:
            body["storageGb"] = float(storage_gb)

        self._schedule("/api/instance-callback/usage", body)

    async def heartbeat(
        self,
        *,
        agent_state: Optional[str] = None,
        uptime_seconds: Optional[int] = None,
    ) -> None:
        """Liveness ping. Slice 2 will fill in agent state; for now the
        endpoint already accepts the empty body and just bumps lastActiveAt."""
        if not self._config.enabled:
            return
        
        self._loop = asyncio.get_running_loop()
        body: Dict[str, Any] = {}
        if agent_state is not None:
            body["agentState"] = agent_state
        if uptime_seconds is not None:
            body["uptimeSeconds"] = int(uptime_seconds)
        self._schedule("/api/instance-callback/heartbeat", body)

    async def aclose(self) -> None:
        """Close the HTTP client at agent shutdown. Sends are dispatched
        fire-and-forget onto the main loop, and the local SQLite mirror is the
        source of truth, so we don't block shutdown draining the last few."""
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _schedule(self, path: str, body: Dict[str, Any]) -> None:
        """Dispatch a background send onto the agent's long-lived main loop.

        Usage is reported from short-lived LLM worker-thread loops (asyncio.run)
        that are torn down before a task created on them could POST, so we
        always dispatch onto the main loop captured on the first heartbeat via
        run_coroutine_threadsafe — non-blocking, and it survives the report's
        own loop teardown.

        Drops the event when queued >= MAX_QUEUE so a downed dashboard cannot
        grow memory without bound. Logs at most once per outage.
        """
        if self._queued >= MAX_QUEUE:
            if not self._outage_logged:
                logger.warning(
                    "[network_interface] outbound queue saturated "
                    f"({self._queued}/{MAX_QUEUE}); dropping events until dashboard recovers"
                )
                self._outage_logged = True
            return

        loop = self._loop
        if loop is None or loop.is_closed():
            # The heartbeat binds the main loop at startup, before any usage is
            # reported, so this is effectively a startup-only guard.
            if not self._outage_logged:
                logger.warning("[network_interface] main loop not bound yet; dropping send")
                self._outage_logged = True
            return

        self._queued += 1
        fut = asyncio.run_coroutine_threadsafe(self._send_with_retry(path, body), loop)
        fut.add_done_callback(lambda _f: self._on_send_done())

    def _on_send_done(self) -> None:
        self._queued = max(0, self._queued - 1)

    async def _client_get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS),
                headers={
                    "Authorization": f"Bearer {self._config.auth_token}",
                    "X-Instance-Id": self._config.instance_id,
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def _send_with_retry(self, path: str, body: Dict[str, Any]) -> None:
        url = dashboard_endpoint(path)
        if not url:
            return  # config disabled mid-flight; nothing to do

        for attempt in range(MAX_RETRIES):
            try:
                client = await self._client_get()
                resp = await client.post(url, json=body)
                if 200 <= resp.status_code < 300:
                    if self._outage_logged:
                        logger.info("[network_interface] dashboard reachable again")
                        self._outage_logged = False
                    # Parse the response body to pull out any quota-lock state
                    # the dashboard included. Defensive — failure here MUST NOT
                    # break the retry/queue contract; the call already
                    # succeeded as far as the dashboard is concerned.
                    self._absorb_response_body(resp)
                    return

                # 4xx is the dashboard rejecting our payload — retrying won't
                # help and would mask a bug. Log and drop.
                if 400 <= resp.status_code < 500:
                    logger.warning(
                        "[network_interface] dashboard rejected request "
                        f"{path}: {resp.status_code} {resp.text[:200]}"
                    )
                    return

                # 5xx / unexpected — fall through to retry below.
                last_err: Any = f"HTTP {resp.status_code}"
            except (httpx.HTTPError, OSError) as exc:
                last_err = exc

            # Backoff with jitter. Cap so a long outage doesn't sleep forever
            # while still holding a slot in the queue.
            delay = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** attempt))
            delay = delay * (0.5 + random.random() * 0.5)
            await asyncio.sleep(delay)

        if not self._outage_logged:
            logger.warning(
                f"[network_interface] giving up on {path} after {MAX_RETRIES} attempts: {last_err}"
            )
            self._outage_logged = True

    def _absorb_response_body(self, resp: "httpx.Response") -> None:
        """Pull dashboard-side state out of a 2xx response body.

        Today the only field of interest is `usageLockedUntil` — the dashboard
        includes it on /heartbeat and /usage so the agent can refuse Bedrock
        calls in-process when the user's monthly budget is exhausted. The cache
        update is delegated to app.network_interface.state, which is what the
        LLM/VLM hot path consults via `is_quota_locked()` (zero I/O).

        Defensive at every step: a missing field, malformed JSON, even a body
        that isn't a dict, all become no-ops. We never want a response-shape
        bug to break the outbound retry/queue contract.
        """
        try:
            data = resp.json()
        except Exception:
            return
        if not isinstance(data, dict):
            return
        # Use sentinel so we can distinguish "field present with value null"
        # (explicit clear) from "field absent" (no info — keep current state).
        sentinel = object()
        raw = data.get("usageLockedUntil", sentinel)
        if raw is sentinel:
            return
        try:
            from app.network_interface.state import set_quota_lock
            set_quota_lock(raw if isinstance(raw, str) else None)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"[network_interface] failed to update quota cache: {exc}")


_singleton: Optional[DashboardClient] = None


def get_dashboard_client() -> DashboardClient:
    """Process-wide singleton."""
    global _singleton
    if _singleton is None:
        _singleton = DashboardClient()
    return _singleton


async def report_usage_to_dashboard(event: UsageEventData) -> None:
    """Convenience hook with the exact `ReportUsageHook` signature.

    Use this when you only need usage reporting and don't want to import the
    client class. It just delegates to `get_dashboard_client().report_usage`.
    """
    await get_dashboard_client().report_usage(event)
