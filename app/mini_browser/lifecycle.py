"""Hooks the agent runtime calls into the Mini Browser.

Called by ``AgentBase`` (run state changes, Stop, deleted sessions, finished
sub-agents, settings changes, shutdown), possibly from other threads (a
sub-agent finishing on its worker thread). Every hook is thread-safe, returns
immediately, never starts a browser and never raises: when a session's
browser was never used there is nothing to do. Every session has a browser
of its own (``fleet.py``); a hook about a sub-agent goes to its parent
session's browser.

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
from app.mini_browser import config

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
# A browser started in this process: a later launch failure is that
# session's own trouble (a damaged profile), not "no browser here".
_ever_launched = False


# ─────────────────────────────────────────────────────────────────────────────
# Hooks (AgentBase)
# ─────────────────────────────────────────────────────────────────────────────


def on_run_state(session_id: str, state: str) -> None:
    """A session's run started (``running``), is ``stopping`` or went ``idle``."""
    if not record_run_state(session_id, state):
        return

    async def apply(fleet: Any) -> None:
        core = fleet.existing(config.browser_key(session_id))
        if core is not None:
            core.run_state_changed(session_id)

    _submit(session_id, apply, "run state")


def stream_removed(session_id: str) -> None:
    """A session's event stream was removed: either a sub-agent finished
    (its tabs close) or a session was deleted (its browser and profile go)."""
    if config.is_subagent_id(session_id):
        release_owner(session_id)
    else:
        session_deleted(session_id)


def release_owner(owner: str) -> None:
    """A sub-agent finished: close its tabs in its parent session's browser."""
    if not _valid(owner):
        return
    forget_owner(owner)

    async def apply(fleet: Any) -> None:
        core = fleet.existing(config.browser_key(owner))
        if core is not None:
            core.release_owner(owner, close_tabs=True)

    _submit(owner, apply, "release")


def session_deleted(session_id: str) -> None:
    """A session was deleted: close its browser for good and delete its
    profile (its cookies and signed-in sites). When no browser ran in this
    process, the profile a previous run left is deleted right away."""
    if not _valid(session_id) or session_id == config.MAIN_SESSION_KEY:
        return
    forget_owner(session_id)

    async def apply(fleet: Any) -> None:
        await fleet.remove(session_id)

    if _submit(session_id, apply, "session deletion"):
        return
    threading.Thread(
        target=_delete_profile_now,
        args=(session_id,),
        name="mini-browser-profile-delete",
        daemon=True,
    ).start()


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

    async def apply(fleet: Any) -> None:
        core = fleet.existing(config.browser_key(session_id))
        if core is not None:
            await core.cancel_owner_ops(session_id, include_children=include_children)

    _submit(session_id, apply, "cancel")


def reload_settings() -> None:
    """settings.json changed: apply the ``mini_browser`` section.

    Live settings (ad blocking, frame rate and quality, human-like input,
    per-agent tab limit, idle shutdown, search page, file URLs) apply at
    once; launch settings (headless, channel, locale, sound) at the next start.
    A no-op when the browser thread never started: the browsers read the
    settings when they start.
    """

    async def apply(fleet: Any) -> None:
        await fleet.reload_settings_now()

    _submit("settings", apply, "settings reload")


def unavailable_reason() -> Optional[str]:
    """Why the Mini Browser cannot run on this machine, or None.

    ``MINI_BROWSER_CHROMIUM_MISSING`` / ``MINI_BROWSER_PLAYWRIGHT_MISSING``
    after the latest launch attempt failed that way, and
    ``MINI_BROWSER_LAUNCH_FAILED`` when no browser has started in this
    process yet; None after a successful launch (or before any launch).
    Never starts anything.
    """
    with _lock:
        return _unavailable


async def shutdown(timeout: float = 15.0) -> None:
    """App exit: close every browser (flushing cookies and logins) and stop the thread.

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
    """A session's browser reports each launch: None = it started.

    Only the failures in ``UNAVAILABLE_CODES`` mark the browser unavailable:
    a missing Chromium or Playwright always, a failed launch only while no
    browser has started in this process (once one has, the machine can run
    them and a failure is that session's own, e.g. a damaged profile). Other
    failures (a profile in use, a close during the launch, too many
    browsers) leave the previous verdict alone.
    """
    global _unavailable, _ever_launched
    with _lock:
        if code is None:
            _unavailable = None
            _ever_launched = True
        elif code == "MINI_BROWSER_LAUNCH_FAILED":
            if not _ever_launched:
                _unavailable = code
        elif code in UNAVAILABLE_CODES:
            _unavailable = code


def _reset_for_tests() -> None:
    """Forget every record (tests only)."""
    global _unavailable, _ever_launched
    with _lock:
        _run_states.clear()
        _parent_stops.clear()
        _unavailable = None
        _ever_launched = False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _valid(session_id: Any) -> bool:
    return isinstance(session_id, str) and bool(session_id)


def _submit(what_for: Any, fn: Callable[[Any], Awaitable[None]], what: str) -> bool:
    """Hand ``fn(fleet)`` to a running browser thread; nothing happens
    otherwise. Returns whether it was handed over."""
    if not _valid(what_for):
        return False
    try:
        from app.mini_browser.host import get_host_if_started

        host = get_host_if_started()
        if host is not None:
            host.submit(fn, start=False)
            return True
    except Exception as exc:
        logger.debug(
            f"[MiniBrowser] Lifecycle {what} hook failed: {type(exc).__name__}"
        )
    return False


def _delete_profile_now(session_id: str) -> None:
    """Delete a deleted session's profile while no browser thread runs
    (blocking: runs on a daemon thread). Never raises."""
    try:
        from app.mini_browser.core import delete_profile

        delete_profile(config.profile_dir(session_id))
    except Exception as exc:
        logger.warning(
            f"[MiniBrowser] Could not delete the browser profile of a deleted "
            f"session: {type(exc).__name__}"
        )
