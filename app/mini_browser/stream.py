"""Live view: frames of the viewed tab, only while someone is watching.

Uses CDP ``Page.startScreencast`` on the viewed tab's CDP session: Chromium
pushes a JPEG whenever the page visibly changes (none while it is idle) and
waits for an ack before sending more. Every frame is acked immediately;
publishing is throttled to ``settings.max_fps`` and always sends the LATEST
frame (a trailing flush delivers the final state of an animation). If the
screencast cannot start, screenshots are polled instead (identical frames are
skipped). The last frame of each tab is kept so a new viewer gets a picture
right away.

Everything here runs on the Mini Browser host loop.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import time
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from app.logger import logger
from app.mini_browser import bridge

if TYPE_CHECKING:
    from app.mini_browser.core import BrowserCore
    from app.mini_browser.types import Tab

_CDP_TIMEOUT_S = 5.0
_ACK_TIMEOUT_S = 3.0
_SCREENSHOT_TIMEOUT_MS = 5000
_POLL_ACTIVE_S = 0.25
_POLL_IDLE_S = 1.0
_POLL_ACTIVE_WINDOW_S = 3.0


class FrameStreamer:
    """Streams the viewed tab of one :class:`BrowserCore` to the UI."""

    def __init__(self, core: "BrowserCore") -> None:
        self._core = core
        self._lock = asyncio.Lock()
        # What is streaming now: (tab id, page id, cdp id, viewport, quality).
        self._key: Optional[Tuple[Any, ...]] = None
        self._mode: Optional[str] = None  # "screencast" | "poll" | None
        self._tab_id: Optional[str] = None
        self._cdp: Any = None
        self._poll_task: Optional[asyncio.Task] = None
        # Tab id -> the CDP session our frame listener is attached to.
        self._listeners: Dict[str, Any] = {}
        # Throttling: the newest frame not yet published, and when we last sent.
        self._pending: Optional[Tuple[str, str, int, int]] = None
        self._flush_handle: Optional[asyncio.TimerHandle] = None
        self._last_publish = 0.0
        self._seq = 0
        self._last_frames: Dict[str, Dict[str, Any]] = {}

    # ── public ───────────────────────────────────────────────────────────────

    @property
    def mode(self) -> Optional[str]:
        return self._mode

    @property
    def streaming_tab_id(self) -> Optional[str]:
        return self._tab_id

    async def sync(self) -> None:
        """Stream the viewed tab iff a viewer exists; restart on any change."""
        async with self._lock:
            tab = self._wanted_tab()
            key = self._key_for(tab) if tab is not None else None
            if key is not None and key == self._key and self._mode is not None:
                return
            await self._stop_locked()
            if tab is None:
                return
            if tab.cdp is None or not await self._start_screencast(tab):
                self._start_polling(tab)
            self._key = key

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    def reset(self) -> None:
        """Forget everything (the browser went away). Synchronous, never raises."""
        self._cancel_flush()
        if self._poll_task is not None:
            self._poll_task.cancel()
        self._poll_task = None
        self._mode = self._tab_id = self._cdp = self._key = None
        self._pending = None
        self._listeners.clear()
        self._last_frames.clear()

    def forget_tab(self, tab_id: str) -> None:
        self._last_frames.pop(tab_id, None)
        self._listeners.pop(tab_id, None)

    async def push_now(self) -> None:
        """Send the viewed tab's latest frame right away (a viewer just arrived)."""
        core = self._core
        tab_id = core.viewed_tab_id
        if not tab_id or not bridge.has_viewers():
            return
        frame = self._last_frames.get(tab_id)
        if frame is not None:
            self._publish({**frame})
            return
        tab = core.tabs.get(tab_id)
        if tab is None or tab.crashed or core.status != "ready" or tab.page.is_closed():
            return
        try:
            jpeg = await tab.page.screenshot(
                type="jpeg", quality=self._quality(), timeout=_SCREENSHOT_TIMEOUT_MS
            )
        except Exception as exc:
            logger.debug(f"[MiniBrowser] Snapshot frame failed: {type(exc).__name__}")
            return
        width, height = self._size(tab)
        self._publish(
            self._frame(tab_id, base64.b64encode(jpeg).decode("ascii"), width, height)
        )

    # ── decisions ────────────────────────────────────────────────────────────

    def _wanted_tab(self) -> Optional["Tab"]:
        core = self._core
        if core.status != "ready" or not bridge.has_viewers():
            return None
        tab = core.tabs.get(core.viewed_tab_id) if core.viewed_tab_id else None
        if tab is None or tab.crashed:
            return None
        try:
            if tab.page.is_closed():
                return None
        except Exception:
            return None
        return tab

    def _key_for(self, tab: "Tab") -> Tuple[Any, ...]:
        return (
            tab.id,
            id(tab.page),
            id(tab.cdp),
            tuple(self._core.viewport),
            self._quality(),
        )

    def _quality(self) -> int:
        return int(self._core.settings.jpeg_quality)

    def _interval(self) -> float:
        return 1.0 / max(1, min(30, int(self._core.settings.max_fps)))

    def _size(self, tab: "Tab") -> Tuple[int, int]:
        size = None
        try:
            size = tab.page.viewport_size
        except Exception:
            size = None
        if size:
            return int(size["width"]), int(size["height"])
        return self._core.viewport

    # ── screencast ───────────────────────────────────────────────────────────

    async def _start_screencast(self, tab: "Tab") -> bool:
        cdp = tab.cdp
        if self._listeners.get(tab.id) is not cdp:
            cdp.on(
                "Page.screencastFrame", functools.partial(self._on_frame, tab.id, cdp)
            )
            self._listeners[tab.id] = cdp
        width, height = self._core.viewport
        self._mode, self._tab_id, self._cdp = "screencast", tab.id, cdp
        try:
            await asyncio.wait_for(
                cdp.send(
                    "Page.startScreencast",
                    {
                        "format": "jpeg",
                        "quality": self._quality(),
                        "maxWidth": int(width),
                        "maxHeight": int(height),
                        "everyNthFrame": 1,
                    },
                ),
                _CDP_TIMEOUT_S,
            )
            return True
        except Exception as exc:
            logger.debug(
                f"[MiniBrowser] Screencast unavailable, polling instead: {type(exc).__name__}"
            )
            self._mode = self._tab_id = self._cdp = None
            return False

    def _on_frame(self, tab_id: str, cdp: Any, params: Dict[str, Any]) -> None:
        """CDP ``Page.screencastFrame`` (host loop). Always acked."""
        session_id = params.get("sessionId") if isinstance(params, dict) else None
        if session_id is not None:
            self._core.spawn(self._ack(cdp, session_id))
        if self._mode != "screencast" or self._cdp is not cdp or self._tab_id != tab_id:
            return
        data = params.get("data")
        if not isinstance(data, str) or not data:
            return
        meta = params.get("metadata") or {}
        width, height = self._core.viewport
        try:
            width = int(round(meta.get("deviceWidth") or width))
            height = int(round(meta.get("deviceHeight") or height))
        except (TypeError, ValueError, OverflowError):
            pass
        self._offer(tab_id, data, width, height)

    @staticmethod
    async def _ack(cdp: Any, session_id: Any) -> None:
        try:
            await asyncio.wait_for(
                cdp.send("Page.screencastFrameAck", {"sessionId": session_id}),
                _ACK_TIMEOUT_S,
            )
        except Exception:
            pass  # the session went away with its page

    # ── polling fallback ─────────────────────────────────────────────────────

    def _start_polling(self, tab: "Tab") -> None:
        self._mode, self._tab_id, self._cdp = "poll", tab.id, None
        self._poll_task = self._core.spawn(self._poll(tab.id, tab.page))

    async def _poll(self, tab_id: str, page: Any) -> None:
        last_digest: Optional[bytes] = None
        changed_at = time.monotonic()
        while self._mode == "poll" and self._tab_id == tab_id:
            if not bridge.has_viewers():
                self._core.spawn(self.sync())
                return
            try:
                jpeg = await page.screenshot(
                    type="jpeg", quality=self._quality(), timeout=_SCREENSHOT_TIMEOUT_MS
                )
            except Exception:
                if page.is_closed():
                    return
                await asyncio.sleep(_POLL_IDLE_S)
                continue
            now = time.monotonic()
            digest = hashlib.sha1(jpeg).digest()
            if digest != last_digest:
                last_digest, changed_at = digest, now
                tab = self._core.tabs.get(tab_id)
                width, height = (
                    self._size(tab) if tab is not None else self._core.viewport
                )
                self._offer(
                    tab_id, base64.b64encode(jpeg).decode("ascii"), width, height
                )
            active = now - changed_at < _POLL_ACTIVE_WINDOW_S
            await asyncio.sleep(_POLL_ACTIVE_S if active else _POLL_IDLE_S)

    # ── throttled publishing ─────────────────────────────────────────────────

    def _offer(self, tab_id: str, data: str, width: int, height: int) -> None:
        """Keep the newest frame; publish now or when the throttle allows."""
        self._pending = (tab_id, data, width, height)
        if self._flush_handle is not None:
            return
        delay = self._last_publish + self._interval() - time.monotonic()
        if delay <= 0:
            self._flush()
        else:
            loop = asyncio.get_running_loop()
            self._flush_handle = loop.call_later(delay, self._flush)

    def _flush(self) -> None:
        self._flush_handle = None
        pending, self._pending = self._pending, None
        if pending is None:
            return
        if not bridge.has_viewers():
            self._core.spawn(self.sync())  # nobody watches: stop capturing
            return
        tab_id, data, width, height = pending
        self._publish(self._frame(tab_id, data, width, height))

    def _frame(self, tab_id: str, data: str, width: int, height: int) -> Dict[str, Any]:
        return {
            "tabId": tab_id,
            "image": "data:image/jpeg;base64," + data,
            "width": width,
            "height": height,
        }

    def _publish(self, frame: Dict[str, Any]) -> None:
        self._seq += 1
        frame["seq"] = self._seq
        self._last_frames[frame["tabId"]] = frame
        self._last_publish = time.monotonic()
        bridge.publish("frame", dict(frame))

    def _cancel_flush(self) -> None:
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None

    async def _stop_locked(self) -> None:
        mode, cdp, task = self._mode, self._cdp, self._poll_task
        self._mode = self._tab_id = self._cdp = self._key = None
        self._poll_task = None
        self._cancel_flush()
        self._pending = None
        if task is not None:
            task.cancel()
        if mode == "screencast" and cdp is not None:
            try:
                await asyncio.wait_for(cdp.send("Page.stopScreencast"), _CDP_TIMEOUT_S)
            except Exception:
                pass  # the page or its session is gone
