"""Thread-safe channel from the Mini Browser thread to the UI.

The browsers run on their own thread (see ``host.py``); the UI adapter runs
on the app's main loop. The adapter registers a :class:`UISink` (``ws.py``)
that hops messages onto its own loop; the browsers publish through
:func:`publish`, which is a no-op when no UI is attached (CLI mode, tests).

Every session has a browser of its own, and a UI client watches one
session's browser at a time (that chat's browser panel). So per-session
messages (state, frames, the agent's pointer, events) carry the session id
(``sessionId``) and go only to that session's viewers, while ``activity``
(which session browsers run, and whether an agent is browsing in them) and
``install`` progress go to every client.

The bridge also carries CraftBot's own UI origins (``host:port``), which no
browser may ever open.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, FrozenSet, Iterable, Optional, Protocol

from app.logger import logger
from app.mini_browser.urls import normalize_origin

# kind -> WebSocket message type (the sink does the mapping).
MESSAGE_TYPES: Dict[str, str] = {
    "state": "mini_browser_state",
    "frame": "mini_browser_frame",
    "pointer": "mini_browser_pointer",
    "event": "mini_browser_event",
    "activity": "mini_browser_activity",
    "install": "mini_browser_install_progress",
    "last_frame": "mini_browser_last_frame",
}
# Kinds that concern one session's browser: their payload names it (sessionId).
SESSION_KINDS = frozenset({"state", "frame", "pointer", "event", "last_frame"})


class UISink(Protocol):
    def has_viewers(self, key: str) -> bool:
        """Whether a UI client is watching session ``key``'s browser. Thread-safe."""

    def post(self, kind: str, payload: Dict[str, Any]) -> None:
        """Deliver one message (kind in MESSAGE_TYPES). Thread-safe, non-blocking."""


_lock = threading.Lock()
_sink: Optional[UISink] = None
_origins: FrozenSet[str] = frozenset()


def register_ui_sink(sink: UISink) -> None:
    """Make ``sink`` the UI the browsers publish to (replaces any previous)."""
    global _sink
    with _lock:
        _sink = sink


def unregister_ui_sink(sink: UISink) -> None:
    """Detach ``sink`` if it is the current one."""
    global _sink
    with _lock:
        if _sink is sink:
            _sink = None


def current_sink() -> Optional[UISink]:
    return _sink


def set_ui_origins(origins: Iterable[str]) -> None:
    """Record CraftBot's UI origins (``host:port``); every browser blocks them.

    Applied to the running browsers right away (their network rules refresh).
    """
    global _origins
    normalized = frozenset(
        origin
        for origin in (normalize_origin(str(o)) for o in origins or () if o)
        if origin
    )
    with _lock:
        changed = normalized != _origins
        _origins = normalized
    if changed:
        _refresh_running_browsers()


def ui_origins() -> FrozenSet[str]:
    """Normalised (lowercase) ``host:port`` origins of CraftBot's own UI."""
    return _origins


def publish(kind: str, payload: Dict[str, Any]) -> None:
    """Send a message to the UI. No-op without a sink; never raises."""
    sink = _sink
    if sink is None:
        return
    try:
        sink.post(kind, payload)
    except Exception as exc:
        logger.debug(f"[MiniBrowser] UI publish ({kind}) failed: {type(exc).__name__}")


def has_viewers(key: Optional[str]) -> bool:
    """Whether any UI client is watching session ``key``'s browser. Never raises."""
    sink = _sink
    if sink is None or not key:
        return False
    try:
        return bool(sink.has_viewers(key))
    except Exception:
        return False


def _refresh_running_browsers() -> None:
    try:
        from app.mini_browser.host import get_host_if_started

        host = get_host_if_started()
        if host is not None:
            host.submit(_refresh_rules, start=False)
    except Exception as exc:
        logger.debug(f"[MiniBrowser] UI origin refresh failed: {type(exc).__name__}")


async def _refresh_rules(fleet: Any) -> None:
    await fleet.refresh_network_rules()
