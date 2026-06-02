# -*- coding: utf-8 -*-
"""
app.network_interface.heartbeat

Periodic heartbeat loop. Sends one `POST /api/instance-callback/heartbeat`
per interval, carrying the agent's currently-derived state and its uptime.

This is the *only* place that pushes proactively — usage events ride along
with LLM calls, and slice-3 state/events/tasks are pulled by the dashboard.
So the loop's failure modes are simple: if the loop crashes the agent keeps
working and the dashboard just stops seeing fresh state until restart.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from app.network_interface.config import is_enabled
from app.network_interface.outbound import get_dashboard_client
from app.network_interface.snapshot import derive_agent_state, process_uptime_seconds

try:
    from app.logger import logger
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)


DEFAULT_INTERVAL_SECONDS = 30


class HeartbeatLoop:
    """Background task that periodically reports state to the dashboard.

    Holds a weak reference to the task_manager so it can be GC'd if the
    agent ever tears it down — the loop itself never owns task_manager
    lifecycle.
    """

    def __init__(
        self,
        task_manager: Any,
        *,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._task_manager = task_manager
        self._interval = max(5, int(interval_seconds))
        self._task: Optional[asyncio.Task[None]] = None
        self._stopped = asyncio.Event()
        self._last_state: Optional[str] = None

    def start(self) -> None:
        """Schedule the loop on the running event loop. Idempotent — calling
        start() twice is a no-op. No-op when the network interface is
        disabled (no env vars), so dev-mode agents stay quiet."""
        if self._task is not None and not self._task.done():
            return
        if not is_enabled():
            logger.info("[network_interface] heartbeat skipped (no CONTAINER_* env vars)")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("[network_interface] no running loop; heartbeat not started")
            return
        self._stopped.clear()
        self._task = loop.create_task(self._run())
        logger.info(f"[network_interface] heartbeat started ({self._interval}s interval)")

    async def stop(self) -> None:
        """Stop the loop and wait briefly for the current iteration to finish."""
        self._stopped.set()
        if self._task is not None and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        self._task = None

    async def send_now(self) -> None:
        """Send one heartbeat immediately. Used at startup so the dashboard
        sees the agent's state without waiting for the first interval."""
        await self._tick()

    async def _run(self) -> None:
        # Touch the uptime counter so its `started_monotonic` anchor is now,
        # not whenever the first /api/instance-callback/usage call happened.
        process_uptime_seconds()
        # Immediate first send so the dashboard reflects "running" right away.
        await self._tick()
        while not self._stopped.is_set():
            try:
                # Sleep with cancel-aware wait so stop() returns quickly.
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval)
                # If wait returned True the stop event was set — exit.
                break
            except asyncio.TimeoutError:
                pass
            await self._tick()

    async def _tick(self) -> None:
        state = derive_agent_state(self._task_manager)
        uptime = process_uptime_seconds()
        # Only log when state changes — at idle this is one line per agent
        # session, which is what you want for ops.
        if state != self._last_state:
            logger.info(f"[network_interface] agent_state -> {state}")
            self._last_state = state
        try:
            await get_dashboard_client().heartbeat(
                agent_state=state,
                uptime_seconds=uptime,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"[network_interface] heartbeat tick failed: {exc}")


_singleton: Optional[HeartbeatLoop] = None


def get_heartbeat_loop(task_manager: Any) -> HeartbeatLoop:
    """Process-wide singleton. The first call wins on which task_manager
    the loop reads from; subsequent calls return the same loop regardless."""
    global _singleton
    if _singleton is None:
        _singleton = HeartbeatLoop(task_manager)
    return _singleton


def start_heartbeat(task_manager: Any) -> HeartbeatLoop:
    """Convenience: get-or-create the loop and start it."""
    loop = get_heartbeat_loop(task_manager)
    loop.start()
    return loop
