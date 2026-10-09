"""Thread-safe channel from the Mini Browser thread to the UI.

The browser runs on its own thread (see ``host.py``); the UI adapter runs on
the app's main loop. The adapter registers a :class:`UISink` (``ws.py``) that
hops messages onto its own loop; the browser publishes through
:func:`publish`, which is a no-op when no UI is attached (CLI mode, tests).

The bridge also carries CraftBot's own UI origins (``host:port``), which the
Mini Browser must never open.
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
    "install": "mini_browser_install_progress",
}


class UISink(Protocol):
    def has_viewers(self) -> bool:
        """Whether a UI client is watching the Mini Browser. Thread-safe."""

    def post(self, kind: str, payload: Dict[str, Any]) -> None:
        """Deliver one message (kind in MESSAGE_TYPES). Thread-safe, non-blocking."""


_lock = threading.Lock()
_sink: Optional[UISink] = None
_origins: FrozenSet[str] = frozenset()


def register_ui_sink(sink: UISink) -> None:
    """Make ``sink`` the UI the browser publishes to (replaces any previous)."""
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
    """Record CraftBot's UI origins (``host:port``); the browser blocks them.

    Applied to a running browser right away (its network rules refresh).
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
        _refresh_running_browser()


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


def has_viewers() -> bool:
    """Whether any UI client is watching the Mini Browser. Never raises."""
    sink = _sink
    if sink is None:
        return False
    try:
        return bool(sink.has_viewers())
    except Exception:
        return False


def _refresh_running_browser() -> None:
    try:
        from app.mini_browser.host import get_host_if_started

        host = get_host_if_started()
        if host is not None:
            host.submit(_refresh_rules, start=False)
    except Exception as exc:
        logger.debug(f"[MiniBrowser] UI origin refresh failed: {type(exc).__name__}")


async def _refresh_rules(core: Any) -> None:
    await core.refresh_network_rules()
