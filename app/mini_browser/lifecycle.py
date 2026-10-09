"""Hooks the agent runtime calls into the Mini Browser.

Called by ``AgentBase`` (run state changes, Stop, deleted chats, finished
sub-agents, settings changes, shutdown), possibly from other threads (a
sub-agent finishing on its worker thread). Every hook is thread-safe, returns
immediately, never starts the browser and never raises: when the Mini
Browser was never used there is nothing to do.

What the hooks report is recorded HERE, process-wide, before it is handed to
a running browser: the run state of every session and the moment each Stop
was pressed. The browser engine reads these records directly, so a hook that
fires while the browser thread is not running (yet) is never lost: a
sub-agent that starts browsing after its parent was stopped is still
refused, and the first browsing run of a session is busy from its start.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, Optional

from app.logger import logger

RUN_STATES = frozenset({"running", "stopping", "idle"})
BUSY_STATES = frozenset({"running", "stopping"})
# A Stop revokes the sub-agents its run had already created. Kept well past
# the longest sub-agent lifetime (30 min), then forgotten.
PARENT_STOP_TTL = timedelta(hours=2)
# Launch failures that mean "the browser cannot run on this machine".
UNAVAILABLE_CODES = frozenset(
    {
        "MINI_BROWSER_CHROMIUM_MISSING",
        "MINI_BROWSER_PLAYWRIGHT_MISSING",
        "MINI_BROWSER_LAUNCH_FAILED",
    }
)

_lock = threading.Lock()
_run_states: Dict[str, str] = {}
_parent_stops: Dict[str, datetime] = {}
_unavailable: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Hooks (AgentBase)
# ─────────────────────────────────────────────────────────────────────────────


def on_run_state(session_id: str, state: str) -> None:
    """A session's run started (``running``), is ``stopping`` or went ``idle``."""
    if not record_run_state(session_id, state):
        return

    async def apply(core: Any) -> None:
        core.run_state_changed(session_id)

    _submit(session_id, apply, "run state")


def release_owner(session_id: str) -> None:
    """A chat was deleted or a sub-agent finished: close its tabs."""
    if not _valid(session_id):
        return
    forget_owner(session_id)

    async def apply(core: Any) -> None:
        core.release_owner(session_id, close_tabs=True)

    _submit(session_id, apply, "release")


def cancel_owner(session_id: str, include_children: bool = True) -> None:
    """The user pressed Stop: cancel the session's browser work (and its sub-agents').

    The moment of the Stop is recorded right here, on the caller's thread:
    sub-agents of this session created before it may never act again, even
    if the browser thread only starts later.
    """
    if not _valid(session_id):
        return
    if include_children:
        record_parent_stop(session_id)

    async def apply(core: Any) -> None:
        await core.cancel_owner_ops(session_id, include_children=include_children)

    _submit(session_id, apply, "cancel")


def reload_settings() -> None:
    """settings.json changed: apply the ``mini_browser`` section.

    Live settings (ad blocking, frame rate and quality, human-like input,
    per-agent tab limit, idle shutdown, search page, file URLs) apply at
    once; launch settings (headless, channel, locale) at the next start.
    A no-op when the browser thread never started: the browser reads the
    settings when it starts.
    """

    async def apply(core: Any) -> None:
        await core.reload_settings_now()

    _submit("settings", apply, "settings reload")


def unavailable_reason() -> Optional[str]:
    """Why the Mini Browser cannot run here, or None.

    ``MINI_BROWSER_CHROMIUM_MISSING`` / ``MINI_BROWSER_PLAYWRIGHT_MISSING`` /
    ``MINI_BROWSER_LAUNCH_FAILED`` after the latest launch attempt failed
    that way; None after a successful launch (or before any launch). Never
    starts anything.
    """
    with _lock:
        return _unavailable


async def shutdown(timeout: float = 15.0) -> None:
    """App exit: close Chromium (flushing cookies and logins) and stop the thread.

    The process-wide browser host stays closed afterwards: later calls get
    MINI_BROWSER_NOT_RUNNING instead of relaunching Chromium during exit
    (``host.restart_process_host()`` opens it again explicitly). Calling it
    again is a no-op.
    """
    try:
        from app.mini_browser.host import shutdown_process_host

        await shutdown_process_host(timeout=timeout)
    except Exception as exc:
        logger.warning(f"[MiniBrowser] Shutdown failed: {type(exc).__name__}")


# ─────────────────────────────────────────────────────────────────────────────
# Process-wide records (read by the browser engine on its own thread)
# ─────────────────────────────────────────────────────────────────────────────


def record_run_state(session_id: Any, state: Any) -> bool:
    """Remember a session's run state (``idle`` forgets it). False for junk."""
    if not _valid(session_id) or state not in RUN_STATES:
        return False
    with _lock:
        if state == "idle":
            _run_states.pop(session_id, None)
        else:
            _run_states[session_id] = state
    return True


def run_state(session_id: Optional[str]) -> Optional[str]:
    """``running`` / ``stopping`` for a busy session, else None."""
    if not session_id:
        return None
    with _lock:
        return _run_states.get(session_id)


def is_run_busy(session_id: Optional[str]) -> bool:
    return run_state(session_id) in BUSY_STATES


def record_parent_stop(session_id: Any, when: Optional[datetime] = None) -> None:
    """Remember that ``session_id``'s run was stopped (naive UTC, now by default)."""
    if not _valid(session_id):
        return
    now = when if isinstance(when, datetime) else datetime.utcnow()
    with _lock:
        _parent_stops[session_id] = now
        expired = [
            sid for sid, at in _parent_stops.items() if now - at > PARENT_STOP_TTL
        ]
        for sid in expired:
            del _parent_stops[sid]


def parent_stop(session_id: Optional[str]) -> Optional[datetime]:
    """When ``session_id``'s run was last stopped (naive UTC), or None."""
    if not session_id:
        return None
    with _lock:
        return _parent_stops.get(session_id)


def forget_owner(session_id: Any) -> None:
    """An owner is gone for good: drop its run state."""
    if not _valid(session_id):
        return
    with _lock:
        _run_states.pop(session_id, None)


def note_launch_result(code: Optional[str]) -> None:
    """The browser engine reports each launch: None = it started.

    Only the failures in ``UNAVAILABLE_CODES`` mark the browser unavailable;
    other failures (a profile in use, a close during the launch) leave the
    previous verdict alone.
    """
    global _unavailable
    with _lock:
        if code is None:
            _unavailable = None
        elif code in UNAVAILABLE_CODES:
            _unavailable = code


def _reset_for_tests() -> None:
    """Forget every record (tests only)."""
    global _unavailable
    with _lock:
        _run_states.clear()
        _parent_stops.clear()
        _unavailable = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _valid(session_id: Any) -> bool:
    return isinstance(session_id, str) and bool(session_id)


def _submit(what_for: Any, fn: Callable[[Any], Awaitable[None]], what: str) -> None:
    """Hand ``fn`` to a running browser thread; nothing happens otherwise."""
    if not _valid(what_for):
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
