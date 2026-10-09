"""Hooks the agent runtime calls into the Mini Browser.

Called by ``AgentBase`` (run state changes, Stop, deleted chats, finished
sub-agents, shutdown), possibly from other threads (a sub-agent finishing on
its worker thread). Every hook is thread-safe, returns immediately, never
starts the browser and never raises: when the Mini Browser was never used
there is nothing to do.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.logger import logger


def on_run_state(session_id: str, state: str) -> None:
    """A session's run started (``running``), is ``stopping`` or went ``idle``."""

    async def apply(core: Any) -> None:
        core.on_run_state(session_id, state)

    _submit(session_id, apply, "run state")


def release_owner(session_id: str) -> None:
    """A chat was deleted or a sub-agent finished: close its tabs."""

    async def apply(core: Any) -> None:
        core.release_owner(session_id, close_tabs=True)

    _submit(session_id, apply, "release")


def cancel_owner(session_id: str, include_children: bool = True) -> None:
    """The user pressed Stop: cancel the session's browser work (and its sub-agents')."""

    async def apply(core: Any) -> None:
        await core.cancel_owner(session_id, include_children=include_children)

    _submit(session_id, apply, "cancel")


async def shutdown(timeout: float = 15.0) -> None:
    """App exit: close Chromium (flushing cookies and logins) and stop the thread."""
    try:
        from app.mini_browser.host import get_host_if_started

        host = get_host_if_started()
        if host is not None:
            await host.shutdown(timeout=timeout)
    except Exception as exc:
        logger.warning(f"[MiniBrowser] Shutdown failed: {type(exc).__name__}")


def _submit(session_id: Any, fn: Callable[[Any], Awaitable[None]], what: str) -> None:
    if not isinstance(session_id, str) or not session_id:
        return
    try:
        from app.mini_browser.host import get_host_if_started

        host = get_host_if_started()
        if host is not None:
            host.submit(fn, start=False)
    except Exception as exc:
        logger.debug(
            f"[MiniBrowser] Lifecycle {what} hook failed: {type(exc).__name__}"
        )
