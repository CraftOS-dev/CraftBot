"""BrowserCore: the Mini Browser engine.

One persistent Chromium profile, shared by every agent and the user, each
agent owner in its own tab(s). Lives entirely on the Mini Browser host loop
(see ``host.py``): never call into it from another loop or thread except
through ``MiniBrowserHost.call`` / ``submit``.

What the core takes care of:

- lifecycle: single-flight launch with clear error codes, a cross-process
  profile lock (never two browsers on one profile, never released while
  Chromium may still run on it), clean relaunch after the browser or the
  Playwright driver dies, idle shutdown, a close that never cuts a launch
  in half;
- tabs: per-owner tabs and claims, owner labels, popups inheriting their
  opener's owner, crash recovery in the same tab slot, at least one tab open;
  every tab it opens gets a browser window of its own, so no agent's tab is
  ever a background tab of another owner's (background tabs get their input
  throttled to ~1 s per event);
- pages: viewport on every page, dialogs answered and reported, downloads
  saved into the owner's workspace (marked as coming from the Internet),
  network blocking (ads + CraftBot's own UI) without request interception, a
  main-frame guard;
- UI: state publishing (debounced), the live-view stream, raw user input and
  "take control";
- agents: :meth:`agent_op` runs one operation from ``ops.OPS`` under the tab
  lock and turns every outcome into a clean action result. An operation
  whose tab (or the whole browser) goes away ends at once with
  MINI_BROWSER_TAB_CLOSED / MINI_BROWSER_CLOSED, never with a success it did
  not have, and never with a CancelledError its caller did not ask for.

No password ever leaves through here: every result, event and state payload
is scrubbed with the secrets autofill typed into a tab.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import itertools
import json
import math
import os
import re
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any, Awaitable, Dict, List, Mapping, Optional, Set, Tuple
from urllib.parse import urlsplit

from app.logger import logger
from app.mini_browser import (
    DEFAULT_OWNER,
    SESSION_ID,
    SESSION_TITLE,
    adblock,
    bridge,
    config,
    lifecycle,
    urls,
)
from app.mini_browser.errors import (
    MiniBrowserError,
    action_error,
    first_line,
    from_exception,
    scrub,
    scrub_data,
    ui_error,
)
from app.mini_browser.stream import FrameStreamer
from app.mini_browser.types import (
    CLOSED_BROWSER,
    CLOSED_TAB,
    EVENT_BLOCKED,
    EVENT_CRASH,
    EVENT_DIALOG,
    EVENT_DOWNLOAD,
    EVENT_ERROR,
    EVENT_NOTICE,
    EVENT_POPUP,
    OWNER_KIND_MAIN,
    OWNER_KIND_MINI_BROWSER,
    OWNER_KIND_SESSION,
    OWNER_KIND_SUBAGENT,
    OWNER_KIND_USER,
    Tab,
)

DEFAULT_VIEWPORT: Tuple[int, int] = (1280, 800)
VIEWPORT_WIDTH = (320, 3840)
VIEWPORT_HEIGHT = (240, 2160)

DEFAULT_TIMEOUT_MS = 15_000
NAVIGATION_TIMEOUT_MS = 30_000
DRIVER_START_TIMEOUT_S = 60.0
LAUNCH_TIMEOUT_S = 90.0
CLOSE_TIMEOUT_S = 10.0
CONTEXT_CLOSE_TIMEOUT_S = 5.0
CDP_TIMEOUT_S = 5.0
PAGE_CALL_TIMEOUT_S = 5.0
TITLE_TIMEOUT_S = 2.0
EVALUATE_TIMEOUT_S = 10.0
NEW_PAGE_TIMEOUT_S = 15.0
STOP_LOADING_TIMEOUT_S = 2.0
OBSERVE_TIMEOUT_S = 15.0
DOWNLOAD_TIMEOUT_S = 30 * 60.0
OP_TIMEOUT_S = 150.0
WAIT_OP_TIMEOUT_S = 930.0  # mini_browser_wait(for_user) may wait 900 s
ABANDON_WAIT_S = 2.0  # how long a cancelled operation may take to unwind
LIVENESS_TIMEOUT_S = 1.0  # driver / browser connection probe

# Live-view input: continuous input (mouse moves, wheel) gets a short timeout
# and a per-tab circuit breaker, so a frozen page cannot queue it up.
INPUT_MOVE_TIMEOUT_S = 1.0
PROBE_TIMEOUT_S = 1.0
PROBE_INTERVAL_S = 0.5

# After an unclean close (driver died, a launch abandoned half-way) the
# profile lock is kept until no Chromium runs on the profile any more.
PROFILE_FREE_WAIT_S = 15.0
PROFILE_KILL_WAIT_S = 3.0
PROFILE_POLL_S = 0.25
PROFILE_RETRY_WINDOW_S = 60.0  # our own Chromium may still be exiting...
PROFILE_RETRY_DELAY_S = 2.0  # ... so a PROFILE_IN_USE launch is retried once

USER_ACTIVE_S = 5.0  # a user tab touched this recently is not claimed
RECENT_USER_TAB_S = (
    60.0  # "leave site?" on a tab that was the user's this recently: stay
)
FOLLOW_HOLD_S = 4.0  # follow-view does not leave a tab an agent just used
USER_HOLD_S = 10.0  # ... or one the user just used
OWN_PAGE_WAIT_S = 2.0
POPUP_ADOPT_WAIT_S = 1.0  # an action's popup still being registered
MAX_TOTAL_TABS = 40
POPUP_SLACK = 2  # popups an owner may have beyond max_agent_tabs (OAuth flows)
EVENTS_PER_TAB = 20
RETIRED_SECRETS = 50
POINTER_INTERVAL_S = 1.0 / 30
STATE_DEBOUNCE_S = 0.05
WATCHDOG_INTERVAL_S = 2.0
TITLE_REFRESH_S = 4.0
MAX_COPY_CHARS = 20_000
MAX_TEXT_INPUT = 2000
WHEEL_LIMIT = 5000.0
# Our own CDP session keeps (almost) no response bodies: Playwright's has them.
NETWORK_ENABLE = {"maxTotalBufferSize": 1_000_000, "maxResourceBufferSize": 100_000}

RUN_STATES = lifecycle.RUN_STATES

# Told once to every owner that had tabs when the browser closed (C2).
RELAUNCH_NOTE = (
    "Note: the Mini Browser was closed (by the user, an idle shutdown or a crash) "
    "after your last action and has started again; your earlier tabs and pages "
    "are gone."
)
CLOSED_NOTE = (
    "Note: the Mini Browser was closed (by the user, an idle shutdown or a crash) "
    "after your last action; your earlier tabs and pages are gone."
)

_EVENT_LEVELS = {
    EVENT_DIALOG: "info",
    EVENT_DOWNLOAD: "info",
    EVENT_POPUP: "info",
    EVENT_NOTICE: "info",
    EVENT_BLOCKED: "warning",
    EVENT_CRASH: "error",
    EVENT_ERROR: "error",
}
# Errors after which the agent gets a fresh look at the page.
_OBSERVE_ON_ERROR = frozenset(
    {
        "MINI_BROWSER_ELEMENT_NOT_FOUND",
        "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
        "MINI_BROWSER_NAVIGATION_FAILED",
        "MINI_BROWSER_TIMEOUT",
        "MINI_BROWSER_LOGIN_FAILED",
        "MINI_BROWSER_NO_SAVED_LOGIN",
        "MINI_BROWSER_UPLOAD_DENIED",
        "MINI_BROWSER_BLOCKED_URL",
        "MINI_BROWSER_USER_IN_CONTROL",
    }
)
_CLOSED_CODES = frozenset({"MINI_BROWSER_CLOSED", "MINI_BROWSER_TAB_CLOSED"})
_MODIFIERS = (("ctrl", "Control"), ("alt", "Alt"), ("shift", "Shift"), ("meta", "Meta"))
_IGNORED_KEYS = frozenset({"Process", "Dead", "Unidentified", "Compose"})
_RESERVED_FILE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
_API_PREFIX_RE = re.compile(r"^[A-Za-z]+\.[A-Za-z_]+: ")
# Playwright appends " at <url>" to navigation errors; the message names the
# address already.
_AT_URL_SUFFIX_RE = re.compile(r"\s+at\s+\S+\s*$")
# Unicode bidi / format controls that can disguise a file name
# ("invoice<RLO>fdp.exe" shows as "invoiceexe.pdf").
_BIDI_CONTROLS_RE = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_LINE_BREAKS_RE = re.compile(r"[\r\n\x00]")
# Errors that mean the Playwright connection or the browser is gone.
_DISCONNECTED_MARKERS = (
    "Connection closed",
    "Browser has been closed",
    "browser has been closed",
    "Target page, context or browser has been closed",
    "Target closed",
)

# Downloads a page can push that run code when opened (Windows, macOS and
# Linux executables, scripts, shortcuts, installers, disk images and
# macro-enabled Office documents).
_DANGEROUS_EXTENSIONS = frozenset(
    {
        "ade", "adp", "app", "appimage", "appinstaller", "application",
        "appref-ms", "appx", "appxbundle", "bas", "bat", "chm", "cmd", "com",
        "command", "cpl", "crt", "csh", "deb", "desktop", "diagcab", "dll",
        "dmg", "docm", "dotm", "exe", "gadget", "hlp", "hta", "htt", "inf",
        "ins", "iqy", "isp", "iso", "img", "jar", "jnlp", "js", "jse", "ksh",
        "library-ms", "lnk", "mad", "maf", "mag", "mam", "maq", "mar", "mas",
        "mat", "mau", "mav", "maw", "mda", "mdb", "mde", "mdt", "mdw", "mdz",
        "mht", "mhtml", "msc", "msh", "msh1", "msh2", "mshxml", "msh1xml",
        "msh2xml", "msi", "msix", "msixbundle", "msp", "mst", "ops", "osd",
        "pcd", "pif", "pkg", "pl", "plg", "potm", "ppam", "ppsm", "pptm",
        "prf", "prg", "ps1", "ps1xml", "ps2", "ps2xml", "psc1", "psc2",
        "psd1", "psm1", "pst", "py", "pyc", "pyo", "pyw", "pyz", "pyzw", "rb",
        "reg", "rpm", "run", "scf", "scr", "sct", "search-ms",
        "settingcontent-ms", "sh", "shb", "shs", "slk", "sldm", "sys", "tmp",
        "u3p", "url", "vb", "vbe", "vbp", "vbs", "vhd", "vhdx", "vsmacros",
        "vsw", "webloc", "ws", "wsc", "wsf", "wsh", "xbap", "xla", "xlam",
        "xll", "xlm", "xlsb", "xlsm", "xltm", "xnk",
    }
)  # fmt: skip

# The selected text, also inside text fields; never from a password field.
_SELECTION_JS = """() => {
  const el = document.activeElement;
  if (el && typeof el.value === 'string' && typeof el.selectionStart === 'number'
      && (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT'
          && /^(text|search|url|tel|email|)$/i.test(el.getAttribute('type') || '')))) {
    return el.value.substring(el.selectionStart, el.selectionEnd || el.selectionStart);
  }
  const sel = window.getSelection();
  return sel ? sel.toString() : '';
}"""

# Fallback UI guard when browser-wide request interception is unavailable:
# blanks any document from CraftBot's own UI before its scripts run. A
# loopback UI origin is matched under every loopback spelling of its port.
_UI_GUARD_JS = (
    "(() => { try { const blocked = %s, ports = %s, anyPort = %s;"
    " const h = String(location.hostname).toLowerCase();"
    " const host = String(location.host).toLowerCase();"
    " const port = Number(location.port || (location.protocol === 'https:' ? 443 : 80));"
    " const loop = h === 'localhost' || h.endsWith('.localhost') || /^127\\./.test(h)"
    " || h === '[::1]' || h.startsWith('[::ffff:7f') || h === '0.0.0.0' || h === '[::]';"
    " if (blocked.includes(host) || (loop && (anyPort || ports.includes(port)))) {"
    " try { window.stop(); } catch (e) {} location.replace('about:blank'); }"
    " } catch (e) {} })()"
)


class BrowserCore:
    """The Mini Browser engine (host loop only)."""

    def __init__(
        self,
        settings: Optional[config.MiniBrowserSettings] = None,
        ops_registry: Optional[Mapping[str, Any]] = None,
        *,
        launch_args: Tuple[str, ...] = (),
    ) -> None:
        """``ops_registry`` defaults to ``app.mini_browser.ops.OPS`` (imported on
        first use); ``launch_args`` are extra Chromium switches (diagnostics,
        tests). Without explicit ``settings``, settings.json is read now and
        again before every launch."""
        self._settings_from_config = settings is None
        self.settings: config.MiniBrowserSettings = (
            settings if settings is not None else config.load_settings()
        )
        self.status = "stopped"
        self.last_error: Optional[Dict[str, str]] = None
        self.tabs: Dict[str, Tab] = {}
        self.viewed_tab_id: Optional[str] = None
        self.follow = True
        self.viewport: Tuple[int, int] = DEFAULT_VIEWPORT

        self._ops_registry = ops_registry
        self._launch_args = tuple(launch_args)

        self._pw: Any = None
        self._context: Any = None
        self._dead_context: Any = None  # a context whose browser already went away
        self._browser_cdp: Any = None
        self._profile_lock: Optional[_ProfileLock] = None
        self._profile_path: Optional[Path] = None
        self._lock_release: Optional[asyncio.Task] = None
        self._start_task: Optional[asyncio.Task] = None
        self._close_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._closing = False
        # A close arrived during a launch: it stops at its next step.
        self._abort_launch = False
        # Chromium may still run on the profile although we let go of it
        # (a launch abandoned half-way, the driver died): see _teardown.
        self._unclean = False
        self._generation = 0
        self._last_close_at = 0.0

        self._tasks: Set[asyncio.Task] = set()
        self._page_tabs: Dict[Any, Tab] = {}
        self._own_pages_pending = 0  # context.new_page() calls in flight
        self._creating = 0  # Target.createTarget calls awaiting their reply
        self._own_targets: Dict[str, asyncio.Future] = {}
        self._abandoned_targets: Set[str] = set()
        self._adoptions: Set[asyncio.Task] = set()
        self._front_tab: Dict[int, str] = {}  # window id -> its active tab id
        self._tab_ids = itertools.count(1)
        self._owner_current: Dict[str, str] = {}
        self._owner_ops: Dict[str, Set[asyncio.Task]] = {}
        self._tab_switches: Dict[str, str] = {}  # owner -> popup now its tab
        self._closed_owners: Set[str] = set()  # had tabs when the browser closed
        self._parents: Dict[str, str] = {}
        self._revoked: Set[str] = set()
        self._retired_secrets: List[str] = []
        self._main_frames: Dict[str, str] = {}
        self._pending_docs: Dict[str, Any] = {}
        # Bumped on every main-frame navigation start/commit, so a refresh that
        # read navigation state before a newer navigation never acts on it.
        self._nav_seq: Dict[str, int] = {}
        self._blocks_reported: Dict[str, Tuple[int, str]] = {}
        self._nav_refresh: Dict[str, asyncio.Task] = {}
        self._nav_dirty: Set[str] = set()
        self._recoveries: Dict[str, asyncio.Task] = {}
        self._probes: Dict[str, asyncio.Task] = {}
        self._pointer_sent: Dict[str, float] = {}
        self._blocked_patterns: List[str] = []
        self._fetch_patterns: List[str] = []
        self._guard_script_origins: frozenset = frozenset()
        self._state_handle: Optional[asyncio.TimerHandle] = None
        self._last_activity = time.monotonic()
        self._last_title_refresh = 0.0
        self._downloads_active = 0
        self._stream = FrameStreamer(self)

    # ═════════════════════════════════════════════════════════════════════════
    # Lifecycle
    # ═════════════════════════════════════════════════════════════════════════

    async def start(self) -> None:
        """Start Chromium (single-flight). Raises MiniBrowserError on failure."""
        await self.ensure_started()

    async def ensure_started(self) -> None:
        """Make sure Chromium runs; concurrent callers share one launch.

        Waits for a close in progress, then (re)launches. Raises the launch's
        MiniBrowserError, or MINI_BROWSER_CLOSED when a close aborted the
        launch this call waited for. Only the caller's own cancellation ever
        raises a CancelledError here.
        """
        for _attempt in range(4):
            close_task = self._close_task
            if close_task is not None and not close_task.done():
                await asyncio.wait({close_task})
                continue
            if self._context is not None and self.status == "ready":
                if (
                    self._context is not self._dead_context
                    and await self._check_alive()
                ):
                    return
                self._request_close()  # the browser or its driver died
                continue
            task = self._start_task
            if task is None or task.done():
                task = self._start_task = self.spawn(self._launch())
            await _wait_shared(task, "MINI_BROWSER_CLOSED")
            return
        raise MiniBrowserError("MINI_BROWSER_NOT_RUNNING")

    async def close(self) -> None:
        """Close Chromium and forget its tabs. Safe to call repeatedly."""
        task = self._request_close()
        await asyncio.wait({task})
        if not task.cancelled() and task.exception() is not None:
            logger.debug(
                f"[MiniBrowser] Close failed: {type(task.exception()).__name__}"
            )

    def _request_close(self) -> asyncio.Task:
        """Start closing the browser now (one close at a time)."""
        task = self._close_task
        if task is None or task.done():
            task = self._close_task = self.spawn(self._close())
        return task

    def reload_settings(self) -> None:
        """Re-read settings.json (in the background) and apply it.

        Live settings (ad blocking, stream quality and frame rate, human-like
        input, the per-agent tab limit, idle shutdown, search page, file
        URLs) apply at once; launch settings (headless, channel, locale) at
        the next start of the browser. Open tabs are never closed.
        """
        try:
            self.spawn(self.reload_settings_now())
        except RuntimeError:  # no running loop (not on the host loop)
            self._apply_settings(config.load_settings())

    async def reload_settings_now(self) -> None:
        """:meth:`reload_settings`, awaitable (``lifecycle.reload_settings``)."""
        self._apply_settings(await asyncio.to_thread(config.load_settings))

    def _apply_settings(self, settings: config.MiniBrowserSettings) -> None:
        old, self.settings = self.settings, settings
        if self._context is not None:
            if old.adblock != settings.adblock:
                self.spawn(self.refresh_network_rules())
            if old.jpeg_quality != settings.jpeg_quality:
                self.spawn(self._stream.sync())
        self._schedule_state()

    async def _launch(self) -> None:
        if self._context is not None:
            self._set_status("ready")
            return
        self._set_status("starting")
        try:
            if self._settings_from_config:
                # Close + Start applies what changed in settings.json.
                self._apply_settings(await asyncio.to_thread(config.load_settings))
            await self._launch_browser()
        except MiniBrowserError as exc:
            await self._teardown()
            if exc.code == "MINI_BROWSER_CLOSED":
                self._set_status("stopped")
                logger.info(
                    "[MiniBrowser] Browser start stopped: the browser was closed"
                )
            else:
                lifecycle.note_launch_result(exc.code)
                self._set_status("error", ui_error(exc.code, **exc.fields))
                logger.warning(f"[MiniBrowser] Browser did not start: {exc.code}")
            raise
        except asyncio.CancelledError:
            await self._teardown()
            self._set_status("stopped")
            raise
        except Exception as exc:
            await self._teardown()
            detail = _clip(first_line(exc), 200)
            lifecycle.note_launch_result("MINI_BROWSER_LAUNCH_FAILED")
            self._set_status(
                "error", ui_error("MINI_BROWSER_LAUNCH_FAILED", detail=detail)
            )
            logger.warning(
                f"[MiniBrowser] Browser launch failed: {type(exc).__name__}: {detail}"
            )
            raise MiniBrowserError(
                "MINI_BROWSER_LAUNCH_FAILED", detail=detail
            ) from None
        except BaseException:
            await self._teardown()
            self._set_status("stopped")
            raise
        lifecycle.note_launch_result(None)

    async def _launch_browser(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise MiniBrowserError("MINI_BROWSER_PLAYWRIGHT_MISSING") from None

        profile = config.profile_dir()
        self._profile_path = profile
        await asyncio.to_thread(config.ensure_dir, profile)
        await self._await_lock_release()
        lock = _ProfileLock(profile.parent / f"{profile.name}.lock")
        if not await _acquire_profile_lock(lock):
            raise MiniBrowserError("MINI_BROWSER_PROFILE_IN_USE")
        self._profile_lock = lock
        self._check_abort()

        self._pw = await self._start_driver(async_playwright)
        self._check_abort()
        channel = self.settings.channel or None
        if channel == "chromium":
            full_build = await asyncio.to_thread(
                os.path.exists, self._pw.chromium.executable_path
            )
            # Without the full build, the bundled headless shell may still be there.
            attempts: List[Optional[str]] = ["chromium", None] if full_build else [None]
        elif channel:
            attempts = [channel, None]
        else:
            attempts = [None]
        version = await asyncio.to_thread(_bundled_chromium_version)

        context = None
        for attempt in attempts:
            kwargs = self._launch_kwargs(profile, attempt, version)
            try:
                context = await self._launch_context(kwargs)
                break
            except asyncio.TimeoutError:
                raise MiniBrowserError(
                    "MINI_BROWSER_LAUNCH_FAILED",
                    detail="Chromium did not start in time",
                ) from None
            except Exception as exc:
                if _is_missing_executable(exc):
                    logger.info(
                        f"[MiniBrowser] Browser build for channel {attempt or 'default'} not installed"
                    )
                    continue
                if not _is_profile_in_use(exc):
                    raise
                if time.monotonic() - self._last_close_at > PROFILE_RETRY_WINDOW_S:
                    raise MiniBrowserError("MINI_BROWSER_PROFILE_IN_USE") from None
            # Our own previous Chromium may still be exiting: one more try.
            await asyncio.sleep(PROFILE_RETRY_DELAY_S)
            self._check_abort()
            try:
                context = await self._launch_context(kwargs)
                break
            except asyncio.TimeoutError:
                raise MiniBrowserError(
                    "MINI_BROWSER_LAUNCH_FAILED",
                    detail="Chromium did not start in time",
                ) from None
            except Exception as exc:
                if _is_profile_in_use(exc):
                    raise MiniBrowserError("MINI_BROWSER_PROFILE_IN_USE") from None
                raise
        if context is None:
            raise MiniBrowserError("MINI_BROWSER_CHROMIUM_MISSING")

        self._context = context  # from now on _teardown closes it
        context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        context.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
        context.on("close", _safely(functools.partial(self._on_context_close, context)))
        context.on("page", _safely(self._on_context_page))
        self._check_abort()
        self._compute_patterns()
        await self._apply_ui_guard()
        for page in list(context.pages):
            if page not in self._page_tabs and not page.is_closed():
                await self._setup_page(self._register_tab(page, None))
        if not self.tabs:
            await self._open_tab(None)
        self._check_abort()
        self._set_status("ready")
        self._touch()
        self._watchdog_task = self.spawn(self._watchdog())
        await self._stream.sync()
        logger.info(
            f"[MiniBrowser] Chromium started (headless={self.settings.headless}, "
            f"channel={self.settings.channel or 'default'})"
        )

    def _check_abort(self) -> None:
        """A close arrived during the launch: stop it here (cleanly)."""
        if self._abort_launch:
            raise MiniBrowserError("MINI_BROWSER_CLOSED")

    async def _start_driver(self, factory: Any) -> Any:
        """Start the Playwright driver in a task of its own.

        It is never cancelled half-way (that leaks the node driver): if we
        stop waiting for it, it is stopped as soon as it has started.
        """
        task = asyncio.ensure_future(factory().start())
        try:
            done, _ = await asyncio.wait({task}, timeout=DRIVER_START_TIMEOUT_S)
        except asyncio.CancelledError:
            task.add_done_callback(self._stop_abandoned_driver)
            raise
        if not done:
            task.add_done_callback(self._stop_abandoned_driver)
            raise MiniBrowserError(
                "MINI_BROWSER_LAUNCH_FAILED",
                detail="the browser driver did not start in time",
            )
        return task.result()

    def _stop_abandoned_driver(self, task: "asyncio.Future[Any]") -> None:
        if task.cancelled() or task.exception() is not None:
            return
        self._spawn_safe(_stop_driver_quietly(task.result()))

    async def _launch_context(self, kwargs: Dict[str, Any]) -> Any:
        """``launch_persistent_context`` (bounded). If we stop waiting for it,
        Chromium may still come up on the profile: the close is unclean."""
        try:
            return await asyncio.wait_for(
                self._pw.chromium.launch_persistent_context(**kwargs),
                LAUNCH_TIMEOUT_S,
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._unclean = True
            raise

    async def _await_lock_release(self) -> None:
        """An earlier unclean close may still hold the profile lock while its
        Chromium exits: wait for it (bounded, a close stops the wait)."""
        task = self._lock_release
        deadline = time.monotonic() + PROFILE_FREE_WAIT_S + PROFILE_KILL_WAIT_S + 5.0
        while task is not None and not task.done() and time.monotonic() < deadline:
            self._check_abort()
            await asyncio.wait({task}, timeout=PROFILE_POLL_S)
        self._check_abort()

    def _launch_kwargs(
        self, profile: Path, channel: Optional[str], version: Optional[str]
    ) -> Dict[str, Any]:
        args = ["--disable-blink-features=AutomationControlled"]
        if sys.platform.startswith("linux"):
            args.append("--disable-dev-shm-usage")
        args.extend(self._launch_args)
        kwargs: Dict[str, Any] = {
            "user_data_dir": str(profile),
            "headless": bool(self.settings.headless),
            "viewport": {"width": self.viewport[0], "height": self.viewport[1]},
            "locale": self.settings.locale or config.os_locale(),
            "accept_downloads": True,
            "args": args,
            "timeout": LAUNCH_TIMEOUT_S * 1000,
        }
        if channel:
            kwargs["channel"] = channel
        if channel in (None, "chromium"):
            # Headless Chromium says "HeadlessChrome/x.y.z.w"; sites treat that
            # as a bot. Present the real version the way Chrome does.
            user_agent = _reduced_user_agent(version)
            if user_agent:
                kwargs["user_agent"] = user_agent
        return kwargs

    async def _close(self) -> None:
        self._closing = True
        try:
            start = self._start_task
            if start is not None and not start.done():
                # Never cancel a launch half-way (Chromium may be starting on
                # the profile): it stops at its next step and cleans up.
                self._abort_launch = True
                await asyncio.wait({start})
            had_browser = self._context is not None
            await self._teardown()
            self._set_status("stopped")
            if had_browser:
                logger.info("[MiniBrowser] Chromium closed")
        finally:
            self._closing = False
            self._abort_launch = False

    async def _teardown(self) -> None:
        """Release Chromium, the driver and the profile lock. Never raises."""
        self._stream.reset()
        current = asyncio.current_task()
        tasks = [
            self._watchdog_task,
            *self._nav_refresh.values(),
            *self._recoveries.values(),
            *self._probes.values(),
        ]
        for task in tasks:
            if task is not None and task is not current and not task.done():
                task.cancel()
        self._watchdog_task = None
        self._nav_refresh.clear()
        self._nav_dirty.clear()
        self._recoveries.clear()
        self._probes.clear()
        gone = list(self.tabs.values())
        for tab in gone:
            self._retire_secrets(tab)
            if tab.owner:
                self._closed_owners.add(tab.owner)
            tab.mark_closed(CLOSED_BROWSER)  # operations on it end at once
        self.tabs.clear()
        self._page_tabs.clear()
        self._owner_current.clear()
        self._tab_switches.clear()
        self._front_tab.clear()
        self._main_frames.clear()
        self._pending_docs.clear()
        self._nav_seq.clear()
        self._blocks_reported.clear()
        self._pointer_sent.clear()
        for waiter in self._own_targets.values():
            if not waiter.done():
                waiter.set_exception(MiniBrowserError("MINI_BROWSER_CLOSED"))
        self._own_targets.clear()
        self._abandoned_targets.clear()
        self.viewed_tab_id = None
        context, self._context = self._context, None
        pw, self._pw = self._pw, None
        session, self._browser_cdp = self._browser_cdp, None
        self._guard_script_origins = frozenset()
        clean = not self._unclean
        if context is not None and context is not self._dead_context:
            clean = await self._close_context(context, session) and clean
        self._dead_context = None
        if pw is not None:
            try:
                await asyncio.wait_for(pw.stop(), CLOSE_TIMEOUT_S)
            except Exception as exc:
                clean = False  # the driver (and its Chromium) may live on
                logger.debug(f"[MiniBrowser] Playwright stop: {type(exc).__name__}")
        self._unclean = False
        lock, self._profile_lock = self._profile_lock, None
        if lock is not None:
            if clean:
                try:
                    await asyncio.to_thread(lock.release)
                except Exception as exc:
                    logger.debug(f"[MiniBrowser] Profile unlock: {type(exc).__name__}")
            else:
                # Never hand the profile to a new browser while Chromium may
                # still run on it.
                self._lock_release = self.spawn(
                    self._release_lock_when_free(lock, self._profile_path)
                )
        if context is not None or gone:
            self._generation += 1
            self._last_close_at = time.monotonic()
        self._schedule_state()

    async def _release_lock_when_free(
        self, lock: "_ProfileLock", profile: Optional[Path]
    ) -> None:
        """Release the profile lock once no Chromium runs on the profile.

        Waits up to PROFILE_FREE_WAIT_S for our earlier Chromium to exit,
        then ends it (only processes started on THIS profile, which we hold
        the lock for, are touched).
        """
        try:
            if profile is not None:
                deadline = time.monotonic() + PROFILE_FREE_WAIT_S
                while True:
                    left = await asyncio.to_thread(_profile_processes, profile)
                    if not left:
                        break
                    if time.monotonic() >= deadline:
                        logger.warning(
                            f"[MiniBrowser] Ending {len(left)} leftover Chromium process(es) on the profile"
                        )
                        await asyncio.to_thread(
                            _kill_processes, left, PROFILE_KILL_WAIT_S
                        )
                        break
                    await asyncio.sleep(PROFILE_POLL_S)
        except asyncio.CancelledError:
            lock.release()  # the loop is going away: a local unlock, instant
            raise
        except Exception as exc:
            logger.debug(f"[MiniBrowser] Profile wait: {type(exc).__name__}")
        try:
            await asyncio.to_thread(lock.release)
        except Exception as exc:
            logger.debug(f"[MiniBrowser] Profile unlock: {type(exc).__name__}")

    async def _close_context(self, context: Any, session: Any) -> bool:
        """Close Chromium quickly without losing profile data; True if it closed.

        ``context.close()`` waits for the browser process to exit, and full
        Chromium with a persistent profile lingers ~30 s after it has already
        flushed and released the profile. So ask it to close over CDP and
        wait only for the disconnect; stopping the driver then ends the
        process (cookies and storage verified to survive). Without a CDP
        session, fall back to a bounded ``context.close()``.
        """
        if session is not None:
            closed = asyncio.Event()
            context.on("close", _safely(lambda *_: closed.set()))
            self.spawn(self._cdp_send(session, "Browser.close"))
            try:
                await asyncio.wait_for(closed.wait(), CONTEXT_CLOSE_TIMEOUT_S)
                return True
            except asyncio.TimeoutError:
                logger.debug("[MiniBrowser] Browser.close did not disconnect in time")
        try:
            await asyncio.wait_for(context.close(), CONTEXT_CLOSE_TIMEOUT_S)
            return True
        except Exception as exc:
            logger.debug(f"[MiniBrowser] Context close: {type(exc).__name__}")
            return False

    def _on_context_close(self, context: Any, *_: Any) -> None:
        """The browser went away (crash, killed, window closed)."""
        self._dead_context = context
        if context is self._context and not self._closing:
            logger.warning(
                "[MiniBrowser] Chromium closed unexpectedly; it restarts on next use"
            )
            self._unclean = True  # make sure it really exited before relaunching
            self._request_close()

    def _note_failure(self, exc: Any, page: Any = None) -> bool:
        """Notice a dead driver/browser behind an error and drop it.

        Returns True when the browser is gone (a close is under way).
        """
        if self._context is None or self._closing:
            return False
        text = exc if isinstance(exc, str) else str(exc)
        dead = "Connection closed" in text or "Browser has been closed" in text
        if not dead and "has been closed" in text and page is not None:
            try:
                dead = not page.is_closed()  # the page is fine: its browser is not
            except Exception:
                dead = True
        if dead:
            logger.warning(
                "[MiniBrowser] Lost the browser connection; it restarts on next use"
            )
            self._mark_dead()
        return dead

    def _mark_dead(self) -> None:
        """The browser or its driver is gone: close without talking to it."""
        if self._context is not None:
            self._dead_context = self._context
            self._unclean = True
            self._request_close()

    async def _check_alive(self) -> bool:
        """A cheap round trip to the browser; False (and a close) if it is gone."""
        session = self._browser_cdp
        if session is None:
            return True
        try:
            await asyncio.wait_for(
                session.send("Browser.getVersion"), LIVENESS_TIMEOUT_S
            )
            return True
        except asyncio.TimeoutError:
            return True  # busy, not gone
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _looks_disconnected(str(exc)) and self._context is not None:
                logger.warning(
                    "[MiniBrowser] The browser connection is gone; restarting it"
                )
                self._mark_dead()
                return False
            return True

    # ═════════════════════════════════════════════════════════════════════════
    # State for the UI
    # ═════════════════════════════════════════════════════════════════════════

    def state(self) -> Dict[str, Any]:
        """The ``mini_browser_state`` payload."""
        secrets = self._secrets()
        tabs = []
        for tab in self.tabs.values():
            tabs.append(
                {
                    "id": tab.id,
                    "url": _clip(scrub(tab.url, secrets), 2048),
                    "title": _clip(scrub(tab.title, secrets), 300),
                    "loading": tab.loading,
                    "owner": tab.owner,
                    "parentOwner": tab.parent_owner,
                    "ownerLabel": tab.owner_label,
                    "ownerKind": tab.owner_kind,
                    "busy": self._tab_busy(tab),
                    "userControl": tab.user_control,
                    "canGoBack": tab.can_go_back,
                    "canGoForward": tab.can_go_forward,
                    "crashed": tab.crashed,
                }
            )
        return {
            "status": self.status,
            "error": self.last_error,
            "sessionId": SESSION_ID,
            "adblock": bool(self.settings.adblock),
            "viewedTabId": self.viewed_tab_id,
            "follow": self.follow,
            "viewport": {"width": self.viewport[0], "height": self.viewport[1]},
            "tabs": tabs,
            "settings": {
                "humanlike": bool(self.settings.humanlike),
                "showCursor": bool(self.settings.show_cursor),
            },
        }

    def _set_status(self, status: str, error: Optional[Dict[str, str]] = None) -> None:
        self.status = status
        self.last_error = error
        self._schedule_state()

    def _schedule_state(self) -> None:
        """Publish the state soon (changes within ~50 ms coalesce)."""
        if self._state_handle is not None or bridge.current_sink() is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._state_handle = loop.call_later(STATE_DEBOUNCE_S, self._flush_state)

    def _flush_state(self) -> None:
        self._state_handle = None
        try:
            bridge.publish("state", self.state())
        except Exception as exc:
            logger.debug(f"[MiniBrowser] State publish failed: {type(exc).__name__}")

    # ═════════════════════════════════════════════════════════════════════════
    # Streaming
    # ═════════════════════════════════════════════════════════════════════════

    async def set_streaming(self, active: bool) -> None:
        """Re-check the live view: it streams the viewed tab while a viewer exists."""
        if active:
            self._touch()
        await self._stream.sync()

    async def push_frame_now(self) -> None:
        """Send the viewed tab's latest frame (a viewer just subscribed)."""
        self._touch()
        await self._stream.push_now()

    # ═════════════════════════════════════════════════════════════════════════
    # UI controls
    # ═════════════════════════════════════════════════════════════════════════

    async def ui_navigate(self, tab_id: Optional[str], text: str) -> None:
        """The URL bar: open an address or search for the text."""
        target = self._resolve(text, allow_search=True)
        await self.ensure_started()
        if tab_id:
            tab = self._ui_tab(tab_id)
        else:
            tab = (
                self.tabs.get(self.viewed_tab_id or "") or await self._ensure_one_tab()
            )
        try:
            await self._recover_if_crashed(tab)
            self._note_user_input(tab)
            await self._goto(tab, target.url)
        except MiniBrowserError as exc:
            raise _for_ui(exc, tab) from None

    async def ui_history(self, tab_id: Optional[str], action: str) -> None:
        """Back / forward / reload / stop on a tab."""
        tab = self._ui_tab(tab_id)
        if action == "stop":
            await self._stop_loading(tab)
            return
        if action not in ("back", "forward", "reload"):
            raise MiniBrowserError(
                "MINI_BROWSER_INVALID_INPUT",
                detail="action must be back, forward, reload or stop.",
            )
        if tab.crashed:
            await self._recover_if_crashed(tab)
            if action == "reload":
                return
        self._note_user_input(tab)
        if action == "reload":
            tab.unresponsive = False  # a fresh document: give input a chance
        page = tab.page
        try:
            if action == "back":
                step = page.go_back(wait_until="commit", timeout=NAVIGATION_TIMEOUT_MS)
            elif action == "forward":
                step = page.go_forward(
                    wait_until="commit", timeout=NAVIGATION_TIMEOUT_MS
                )
            else:
                step = page.reload(wait_until="commit", timeout=NAVIGATION_TIMEOUT_MS)
            await asyncio.wait_for(step, NAVIGATION_TIMEOUT_MS / 1000 + 5)
        except Exception as exc:
            try:
                self._raise_navigation_error(exc, tab, tab.url)
            except MiniBrowserError as error:
                raise _for_ui(error, tab) from None
        finally:
            self._schedule_nav_refresh(tab)

    async def ui_input(self, tab_id: str, event: dict) -> None:
        """Raw user input from the live view (coordinates are 0..1 of the frame).

        Continuous input (mouse moves, wheel) gets a short timeout; once a
        page stops answering it, further continuous input on that tab is
        dropped at once (MINI_BROWSER_PAGE_UNRESPONSIVE) until a probe sees
        the page respond again, it navigates, reloads or recovers.
        """
        tab = self._ui_tab(tab_id)
        if not isinstance(event, Mapping):
            return
        if tab.crashed:
            await self._recover_if_crashed(tab)
            return
        page = tab.page
        kind = event.get("kind")
        continuous = kind == "wheel" or (
            kind == "mouse" and event.get("action") == "move"
        )
        if continuous and tab.unresponsive:
            raise MiniBrowserError("MINI_BROWSER_PAGE_UNRESPONSIVE")
        limit = INPUT_MOVE_TIMEOUT_S if continuous else PAGE_CALL_TIMEOUT_S
        try:
            if kind == "mouse":
                action = event.get("action")
                point = self._point(tab, event)
                if action not in ("down", "up", "move") or point is None:
                    return
                button = event.get("button")
                button = button if button in ("left", "middle", "right") else "left"
                clicks = _clamp_int(event.get("clickCount"), 1, 3, 1)
                # Take control (if it does) BEFORE the input reaches the page,
                # so a running agent operation stops at its next step.
                self._note_user_input(tab, takes_control=action != "move")
                await _within(page.mouse.move(point[0], point[1]), limit)
                if action == "down":
                    await _within(
                        page.mouse.down(button=button, click_count=clicks), limit
                    )
                elif action == "up":
                    await _within(
                        page.mouse.up(button=button, click_count=clicks), limit
                    )
            elif kind == "wheel":
                point = self._point(tab, event)
                if point is None:
                    return
                dx = _finite(event.get("dx"), WHEEL_LIMIT)
                dy = _finite(event.get("dy"), WHEEL_LIMIT)
                self._note_user_input(tab)
                await _within(page.mouse.move(point[0], point[1]), limit)
                await _within(page.mouse.wheel(dx, dy), limit)
            elif kind == "key":
                combo = _key_combo(event)
                if combo is None:
                    return
                self._note_user_input(tab)
                await _within(page.keyboard.press(combo), limit)
            elif kind == "text":
                text = event.get("text")
                if not isinstance(text, str) or not text:
                    return
                self._note_user_input(tab)
                await _within(page.keyboard.insert_text(text[:MAX_TEXT_INPUT]), limit)
        except asyncio.TimeoutError:
            self._mark_unresponsive(tab)
            raise MiniBrowserError("MINI_BROWSER_PAGE_UNRESPONSIVE") from None
        except Exception as exc:
            if kind == "key" and "Unknown key" in str(exc):
                logger.debug("[MiniBrowser] Ignored a key Playwright does not know")
                return
            if tab.closed:
                raise _for_ui(self._closed_error(tab), tab) from None
            if self._note_failure(exc, page):
                raise MiniBrowserError("MINI_BROWSER_CLOSED") from None
            raise MiniBrowserError(
                "MINI_BROWSER_INTERNAL", detail=_clip(first_line(exc), 200)
            ) from None

    def _mark_unresponsive(self, tab: Tab) -> None:
        """Trip the tab's input circuit breaker; a probe resets it."""
        if tab.closed or self.tabs.get(tab.id) is not tab:
            return
        tab.unresponsive = True
        probe = self._probes.get(tab.id)
        if probe is None or probe.done():
            self._probes[tab.id] = self.spawn(self._probe_responsive(tab))

    async def _probe_responsive(self, tab: Tab) -> None:
        try:
            while (
                tab.unresponsive
                and not tab.closed
                and not tab.crashed
                and self.tabs.get(tab.id) is tab
            ):
                page = tab.page
                try:
                    await asyncio.wait_for(page.evaluate("1"), PROBE_TIMEOUT_S)
                except asyncio.TimeoutError:
                    await asyncio.sleep(PROBE_INTERVAL_S)
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception:
                    if _page_closed(page):
                        return
                    await asyncio.sleep(PROBE_INTERVAL_S)
                    continue
                if tab.page is page:
                    tab.unresponsive = False
        finally:
            if self._probes.get(tab.id) is asyncio.current_task():
                del self._probes[tab.id]

    async def ui_new_tab(self, url: Optional[str] = None) -> str:
        """Open a user tab (optionally at ``url``), view it, return its id."""
        wanted = isinstance(url, str) and bool(url.strip())
        target = self._resolve(url, allow_search=True) if wanted else None
        await self.ensure_started()
        tab = await self._open_tab(None)
        tab.touch_user()
        self.viewed_tab_id = tab.id
        self.follow = False
        self._schedule_state()
        await self._stream.sync()
        await self._bring_to_front(tab)
        if target is not None:
            self.spawn(self._open_in_background(tab, target.url))
        return tab.id

    async def ui_switch_tab(self, tab_id: str) -> None:
        """View ``tab_id``; the view stops following agents."""
        tab = self._ui_tab(tab_id)
        self.viewed_tab_id = tab.id
        self.follow = False
        self._schedule_state()
        await self._stream.sync()
        await self._bring_to_front(tab)

    async def ui_close_tab(self, tab_id: str) -> None:
        """Close a tab (any tab: the user decides). One tab always stays open."""
        tab = self._ui_tab(tab_id)
        if len(self.tabs) == 1:
            await self._open_tab(None)
        page = tab.page
        await self._close_page(page)
        self._on_page_close(page)

    async def ui_view(self, tab_id: Optional[str], follow: Optional[bool]) -> None:
        """Which tab the UI shows; ``follow`` makes the view track agent activity."""
        if follow is not None:
            self.follow = bool(follow)
        if tab_id:
            tab = self.tabs.get(tab_id)
            if tab is None:
                raise MiniBrowserError("MINI_BROWSER_TAB_NOT_FOUND", tab=tab_id)
            self.viewed_tab_id = tab.id
        elif follow:
            latest = self._latest_agent_tab()
            if latest is not None:
                self.viewed_tab_id = latest.id
        self._schedule_state()
        await self._stream.sync()
        viewed = self.tabs.get(self.viewed_tab_id or "")
        if viewed is not None:
            await self._bring_to_front(viewed)

    async def ui_control(self, tab_id: str, take: bool) -> None:
        """The user takes control of a tab (agents pause on it) or hands it back."""
        tab = self._ui_tab(tab_id)
        take = bool(take)
        if tab.user_control == take:
            return
        tab.user_control = take
        if take:
            tab.touch_user()
            self._agent_notice(
                tab,
                EVENT_NOTICE,
                "The user took control of this tab; agent actions here wait until they hand it back.",
            )
        else:
            self._agent_notice(
                tab,
                EVENT_NOTICE,
                f"The user handed control back. The tab now shows {_clip(tab.url, 200)}; "
                "look at the page again before acting.",
            )
        self._schedule_state()

    async def ui_copy_selection(self, tab_id: str) -> str:
        """The text selected in a tab (never from a password field)."""
        tab = self._ui_tab(tab_id)
        try:
            text = await asyncio.wait_for(
                tab.page.evaluate(_SELECTION_JS), EVALUATE_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            raise MiniBrowserError("MINI_BROWSER_PAGE_UNRESPONSIVE") from None
        except Exception as exc:
            self._note_failure(exc, tab.page)
            return ""
        if not isinstance(text, str):
            return ""
        return scrub(text[:MAX_COPY_CHARS], self._secrets())

    async def set_viewport(self, width: int, height: int) -> None:
        """The CSS viewport of every tab (and of tabs opened later)."""
        size = (
            _clamp_int(width, *VIEWPORT_WIDTH, self.viewport[0]),
            _clamp_int(height, *VIEWPORT_HEIGHT, self.viewport[1]),
        )
        if size == self.viewport:
            return
        self.viewport = size
        if self._context is not None:
            await asyncio.gather(
                *(self._apply_viewport(tab) for tab in list(self.tabs.values()))
            )
            await self._stream.sync()
        self._schedule_state()

    async def set_adblock(self, enabled: bool) -> None:
        """Turn ad blocking on/off for every tab (no reload) and remember it."""
        enabled = bool(enabled)
        self.settings = replace(self.settings, adblock=enabled)
        try:
            await asyncio.to_thread(config.save_setting, "adblock", enabled)
        except Exception as exc:
            logger.warning(
                f"[MiniBrowser] Could not save the ad-block setting: {type(exc).__name__}"
            )
        await self.refresh_network_rules()
        self._schedule_state()

    def _ui_tab(self, tab_id: Optional[str]) -> Tab:
        if self._context is None or self.status != "ready":
            raise MiniBrowserError("MINI_BROWSER_NOT_RUNNING")
        key = tab_id or self.viewed_tab_id
        tab = self.tabs.get(key) if key else None
        if tab is None:
            raise MiniBrowserError("MINI_BROWSER_TAB_NOT_FOUND", tab=tab_id or "")
        return tab

    def _point(
        self, tab: Tab, event: Mapping[str, Any]
    ) -> Optional[Tuple[float, float]]:
        """Normalised (0..1) frame coordinates -> CSS px of the tab's own viewport."""
        x, y = _unit(event.get("x")), _unit(event.get("y"))
        if x is None or y is None:
            return None
        width, height = self._page_size(tab)
        return x * width, y * height

    def _note_user_input(self, tab: Tab, takes_control: bool = True) -> None:
        """The user used a tab. Input on a tab whose agent is busy pauses that agent.

        Runs BEFORE the input is dispatched to the page: an agent operation
        in flight on the tab sees ``user_control`` at its next step and stops.
        """
        tab.touch_user()
        self._touch()
        if (
            takes_control
            and tab.owner
            and not tab.user_control
            and self._owner_busy(tab.owner)
        ):
            tab.user_control = True
            self._agent_notice(
                tab,
                EVENT_NOTICE,
                "The user took control of this tab; agent actions here wait until they hand it back.",
            )
            self._schedule_state()

    async def _open_in_background(self, tab: Tab, url: str) -> None:
        try:
            await self._goto(tab, url)
        except MiniBrowserError as exc:
            if tab.closed:
                return
            message = ui_error(exc.code, self._secrets(), **exc.fields)["message"]
            self.add_event(tab, EVENT_ERROR, message)

    # ═════════════════════════════════════════════════════════════════════════
    # Agents
    # ═════════════════════════════════════════════════════════════════════════

    async def agent_op(self, owner: str, op: str, params: dict) -> dict:
        """Run one agent operation in the owner's tab; always returns a result dict.

        The operation runs in a task of its own, raced against its tab
        closing: when the tab or the browser goes away the operation is
        abandoned at once and the result is MINI_BROWSER_TAB_CLOSED /
        MINI_BROWSER_CLOSED, whatever the operation would have reported.
        """
        owner = owner if isinstance(owner, str) and owner else DEFAULT_OWNER
        params = dict(params or {})
        task = asyncio.current_task()
        owner_tasks = self._owner_ops.setdefault(owner, set())
        if task is not None:
            owner_tasks.add(task)
        self._touch()
        tab: Optional[Tab] = None
        # A popup an earlier action opened that became this owner's tab after
        # that action's result had gone out: this result says so first.
        late_switch = self._tab_switches.pop(owner, None)
        try:
            if self._is_revoked(owner):
                return action_error("MINI_BROWSER_STOPPED")
            if op == "tabs":
                result, tab = await self._op_tabs(owner, params)
                if tab is not None and tab.closed:
                    raise self._closed_error(tab)
                return self._finish(
                    result,
                    tab,
                    owner=owner,
                    notes=self._switch_note(owner, late_switch),
                )
            fn = self._lookup_op(op)
            result: Any = None
            for _attempt in range(3):
                tab = await self.tab_for_owner(owner)
                refused = self._control_refusal(tab, op, params)
                if refused is not None:
                    return self._finish(refused, tab, owner=owner)
                if task is not None:
                    tab.ops.add(task)
                try:
                    async with tab.lock:
                        if self.tabs.get(tab.id) is tab:
                            refused = self._control_refusal(tab, op, params)
                            if refused is not None:
                                return self._finish(refused, tab, owner=owner)
                            await self._recover_if_crashed(tab)
                            self._follow(tab)
                            await self._agent_front(tab)
                            result = await self._run_op(
                                tab, fn, params, self._op_timeout(op)
                            )
                            break
                finally:
                    if task is not None:
                        tab.ops.discard(task)
                if tab.closed_reason == CLOSED_BROWSER:
                    # The browser closed while this operation waited its turn.
                    raise MiniBrowserError("MINI_BROWSER_CLOSED")
            else:
                raise MiniBrowserError("MINI_BROWSER_TAB_NOT_FOUND", tab="")
            if tab.closed:
                raise self._closed_error(tab)
            tab.touch_agent()
            self._follow(tab)
            result, tab, drained = await self._after_op(owner, tab, result)
            return self._finish(
                result,
                tab,
                owner=owner,
                notes=self._switch_note(owner, late_switch),
                extra_tabs=drained,
            )
        except asyncio.CancelledError:
            if tab is not None and self.tabs.get(tab.id) is tab:
                self.spawn(self._stop_loading(tab))
            raise
        except asyncio.TimeoutError:
            if tab is not None and self.tabs.get(tab.id) is tab:
                self.spawn(self._stop_loading(tab))
            seconds = int(self._op_timeout(op))
            error = MiniBrowserError(
                "MINI_BROWSER_TIMEOUT", what=f"The {op} action", seconds=seconds
            )
            return await self._error_result(error, tab, owner)
        except MiniBrowserError as exc:
            return await self._error_result(self._refine_error(exc, tab), tab, owner)
        except Exception as exc:
            return self._finish(self._unexpected(op, exc, tab), tab, owner=owner)
        finally:
            owner_tasks.discard(task)
            if not owner_tasks and self._owner_ops.get(owner) is owner_tasks:
                self._owner_ops.pop(owner, None)
            self._schedule_state()

    async def _run_op(
        self, tab: Tab, fn: Any, params: Dict[str, Any], timeout: float
    ) -> Any:
        """``fn(self, tab, **params)`` in a task, raced against the tab closing."""
        child = asyncio.ensure_future(fn(self, tab, **params))
        closed = asyncio.ensure_future(tab.closed_event.wait())
        try:
            done, _ = await asyncio.wait(
                {child, closed}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            closed.cancel()
            await _abandon(child)
            raise
        closed.cancel()
        if child in done:
            return child.result()
        await _abandon(child)
        if tab.closed:
            raise self._closed_error(tab)
        raise asyncio.TimeoutError()

    async def _after_op(
        self, owner: str, tab: Tab, result: Any
    ) -> Tuple[Any, Tab, List[Tab]]:
        """The action opened a tab that is now the owner's active tab.

        The result then shows that NEW tab (observation, ``tab``) and says
        so; the opener's notices are delivered too.
        """
        pending = {t for t in self._adoptions if not t.done()}
        if pending:
            await asyncio.wait(pending, timeout=POPUP_ADOPT_WAIT_S)
        switched = self._tab_switches.pop(owner, None)
        if switched is None or switched == tab.id:
            return result, tab, []
        new = self.tabs.get(switched)
        if (
            new is None
            or new.owner != owner
            or self._owner_current.get(owner) != new.id
        ):
            return result, tab, []
        page = None
        async with new.lock:
            if self.tabs.get(new.id) is new and not new.crashed:
                page = await self._observe(new)
        result = (
            dict(result)
            if isinstance(result, dict)
            else {
                "status": "success",
                "message": "Done." if result is None else str(result),
            }
        )
        if page is not None:
            result["page"] = page
        note = f"A new tab opened (index {self._tab_index(new)}) and is now your active tab."
        result["message"] = (
            f"{str(result.get('message') or '').rstrip()} {note}".strip()
        )
        new.touch_agent()
        self._follow(new)
        return result, new, [tab]

    def _switch_note(self, owner: str, tab_id: Optional[str]) -> List[str]:
        """'A new tab opened ...' if ``tab_id`` is still the owner's active tab."""
        if not tab_id:
            return []
        tab = self.tabs.get(tab_id)
        if (
            tab is None
            or tab.owner != owner
            or self._owner_current.get(owner) != tab_id
        ):
            return []
        return [
            f"A new tab opened (index {self._tab_index(tab)}) and is now your active tab."
        ]

    def _closed_error(self, tab: Tab) -> MiniBrowserError:
        if tab.closed_reason == CLOSED_TAB:
            return MiniBrowserError("MINI_BROWSER_TAB_CLOSED")
        return MiniBrowserError("MINI_BROWSER_CLOSED")

    def _refine_error(
        self, exc: MiniBrowserError, tab: Optional[Tab]
    ) -> MiniBrowserError:
        """Name a tab / browser that went away under the operation precisely."""
        if tab is not None and tab.closed:
            return self._closed_error(tab)
        text = " ".join(str(v) for v in exc.fields.values())
        if exc.code not in _CLOSED_CODES and not _looks_disconnected(text):
            return exc
        page = tab.page if tab is not None else None
        if self._context is None or self._note_failure(text or exc.code, page):
            return MiniBrowserError("MINI_BROWSER_CLOSED")
        if page is not None and _page_closed(page):
            return MiniBrowserError("MINI_BROWSER_TAB_CLOSED")
        return exc

    async def tab_for_owner(self, owner: str) -> Tab:
        """The tab ``owner`` acts in, claiming or opening one if needed.

        1) the owner's current tab (else its most recently used one);
        2) else the viewed tab if the owner may claim it: a blank user tab,
           or any idle user tab for the dedicated Mini Browser chat (other
           agents' tabs are never claimed);
        3) else a new tab, in a window of its own (at most
           ``settings.max_agent_tabs`` per owner).
        """
        await self.ensure_started()
        tab = self.tabs.get(self._owner_current.get(owner, ""))
        if tab is None:
            mine = [t for t in self.tabs.values() if t.owner == owner]
            if mine:
                tab = max(mine, key=lambda t: t.last_agent_use)
        if tab is None:
            viewed = self.tabs.get(self.viewed_tab_id or "")
            if viewed is not None and self._claimable(viewed, owner):
                tab = viewed
        if tab is None:
            count = self._owner_tab_count(owner)
            if count >= self.settings.max_agent_tabs:
                raise MiniBrowserError("MINI_BROWSER_TOO_MANY_TABS", count=count)
            tab = await self._open_tab(owner)
        self._claim(tab, owner)
        return tab

    def tabs_payload(self, owner: Optional[str] = None) -> List[Dict[str, Any]]:
        """Agent-facing tab list.

        The caller's own tabs: ``{index, id, url, title, mine: true, active}``.
        Other agents' tabs: ``{index, mine: false, owner: "agent",
        ownerLabel}``. The user's tabs: ``{index, mine: false, owner: "user",
        host, viewed}`` (host name only). Nobody sees the address or title of
        a tab that is not theirs.
        """
        current = self._owner_current.get(owner) if owner else None
        secrets = self._secrets()
        out: List[Dict[str, Any]] = []
        for index, tab in enumerate(self.tabs.values()):
            if owner is not None and tab.owner == owner:
                out.append(
                    {
                        "index": index,
                        "id": tab.id,
                        "url": _clip(scrub(tab.url, secrets), 300),
                        "title": _clip(scrub(tab.title, secrets), 120),
                        "mine": True,
                        "active": tab.id == current,
                    }
                )
            elif tab.owner is not None:
                out.append(
                    {
                        "index": index,
                        "mine": False,
                        "owner": "agent",
                        "ownerLabel": _clip(
                            scrub(tab.owner_label or "another agent", secrets), 80
                        ),
                    }
                )
            else:
                out.append(
                    {
                        "index": index,
                        "mine": False,
                        "owner": "user",
                        "host": _clip(scrub(_host_of(tab.url), secrets), 120),
                        "viewed": tab.id == self.viewed_tab_id,
                    }
                )
        return out

    async def _op_tabs(
        self, owner: str, params: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Optional[Tab]]:
        """``mini_browser_tabs``: list / new / switch / close, scoped to the owner.

        Returns the result and the tab it concerns (None if none).
        """
        action = str(params.get("action") or "list").strip().lower()
        ref = next(
            (
                params[k]
                for k in ("tab", "tab_id", "id", "index")
                if params.get(k) is not None
            ),
            None,
        )
        if action == "list":
            if self._context is None:
                return {
                    "status": "success",
                    "message": "The Mini Browser is not running; it starts with your first navigation.",
                    "tabs": [],
                }, None
            tabs = self.tabs_payload(owner)
            mine = sum(1 for t in tabs if t["mine"])
            return {
                "status": "success",
                "message": f"{len(tabs)} tab(s) open, {mine} of them yours.",
                "tabs": tabs,
            }, None
        if action == "new":
            url = params.get("url")
            target: Optional[urls.Target] = None
            if isinstance(url, urls.Target):
                target = url if url.kind == urls.KIND_URL else None
            elif isinstance(url, str) and url.strip():
                target = self._resolve(url, allow_search=True)
            await self.ensure_started()
            count = self._owner_tab_count(owner)
            if count >= self.settings.max_agent_tabs:
                raise MiniBrowserError("MINI_BROWSER_TOO_MANY_TABS", count=count)
            tab = await self._open_tab(owner)
            self._claim(tab, owner)
            self._follow(tab)
            async with tab.lock:
                try:
                    if target is not None:
                        await self._goto(tab, target.url)
                except MiniBrowserError as exc:
                    if tab.closed:
                        raise self._closed_error(tab) from None
                    result = from_exception(exc, self._secrets())
                    result["tabs"] = self.tabs_payload(owner)
                    return result, tab
                page = await self._observe(tab)
            return {
                "status": "success",
                "message": f"Opened tab {self._tab_index(tab)} and made it your active tab.",
                "tabs": self.tabs_payload(owner),
                "page": page,
            }, tab
        if action == "switch":
            if ref is None:
                raise MiniBrowserError(
                    "MINI_BROWSER_INVALID_INPUT",
                    detail="Say which tab to switch to (its index).",
                )
            if self._context is None:
                raise MiniBrowserError("MINI_BROWSER_NOT_RUNNING")
            tab = self._find_tab(ref)
            if tab.owner != owner and not self._claimable(tab, owner, explicit=True):
                if tab.owner is not None:
                    raise MiniBrowserError(
                        "MINI_BROWSER_TAB_OWNED",
                        tab=self._tab_index(tab),
                        owner=tab.owner_label or "another agent",
                    )
                if (
                    tab.user_control
                    or time.monotonic() - tab.last_user_input < USER_ACTIVE_S
                ):
                    # The user is working in it right now.
                    return action_error("MINI_BROWSER_USER_IN_CONTROL"), None
                raise MiniBrowserError(
                    "MINI_BROWSER_USER_TAB", tab=self._tab_index(tab)
                )
            self._claim(tab, owner)
            self._follow(tab)
            async with tab.lock:
                await self._recover_if_crashed(tab)
                await self._agent_front(tab)
                page = await self._observe(tab)
            return {
                "status": "success",
                "message": f"Switched to tab {self._tab_index(tab)}.",
                "tabs": self.tabs_payload(owner),
                "page": page,
            }, tab
        if action == "close":
            if self._context is None:
                raise MiniBrowserError("MINI_BROWSER_NOT_RUNNING")
            if ref is not None:
                tab = self._find_tab(ref)
            else:
                tab = self.tabs.get(self._owner_current.get(owner, ""))
                if tab is None:
                    raise MiniBrowserError("MINI_BROWSER_TAB_NOT_FOUND", tab="")
            if tab.owner is None:
                raise MiniBrowserError(
                    "MINI_BROWSER_INVALID_INPUT",
                    detail="That tab belongs to the user; close only your own tabs.",
                )
            if tab.owner != owner:
                raise MiniBrowserError(
                    "MINI_BROWSER_TAB_OWNED",
                    tab=self._tab_index(tab),
                    owner=tab.owner_label or "another agent",
                )
            index = self._tab_index(tab)
            if len(self.tabs) == 1:
                await self._open_tab(None)
            page = tab.page
            await self._close_page(page)
            self._on_page_close(page)
            return {
                "status": "success",
                "message": f"Closed tab {index}.",
                "tabs": self.tabs_payload(owner),
            }, None
        raise MiniBrowserError(
            "MINI_BROWSER_INVALID_INPUT",
            detail="action must be list, new, switch or close.",
        )

    def _lookup_op(self, op: Any) -> Any:
        if not isinstance(op, str) or not op:
            raise MiniBrowserError(
                "MINI_BROWSER_INVALID_INPUT", detail="Unknown operation."
            )
        registry = self._ops_registry
        if registry is None:
            try:
                from app.mini_browser.ops import OPS
            except Exception as exc:
                logger.error(
                    f"[MiniBrowser] Agent operations failed to load: {type(exc).__name__}"
                )
                raise MiniBrowserError(
                    "MINI_BROWSER_INTERNAL",
                    detail="the browser operations are unavailable",
                ) from None
            registry = self._ops_registry = OPS
        fn = registry.get(op)
        if fn is None:
            raise MiniBrowserError(
                "MINI_BROWSER_INVALID_INPUT",
                detail=f"Unknown Mini Browser operation: {op}",
            )
        return fn

    @staticmethod
    def _control_refusal(
        tab: Tab, op: str, params: Mapping[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if tab.user_control and not (op == "wait" and params.get("for_user")):
            return action_error("MINI_BROWSER_USER_IN_CONTROL")
        return None

    @staticmethod
    def _op_timeout(op: str) -> float:
        return WAIT_OP_TIMEOUT_S if op == "wait" else OP_TIMEOUT_S

    async def _error_result(
        self, exc: MiniBrowserError, tab: Optional[Tab], owner: Optional[str] = None
    ) -> Dict[str, Any]:
        result = from_exception(exc, self._secrets())
        if (
            exc.code in _OBSERVE_ON_ERROR
            and tab is not None
            and self.tabs.get(tab.id) is tab
            and not tab.crashed
        ):
            async with tab.lock:
                page = await self._observe(tab)
            if page is not None:
                result["page"] = page
        return self._finish(result, tab, owner=owner)

    def _unexpected(
        self, op: str, exc: BaseException, tab: Optional[Tab]
    ) -> Dict[str, Any]:
        secrets = self._secrets()
        line = _clip(scrub(first_line(exc), secrets), 200)
        logger.warning(f"[MiniBrowser] {op} failed: {type(exc).__name__}: {line}")
        logger.debug("[MiniBrowser] " + "".join(traceback.format_tb(exc.__traceback__)))
        dead = self._note_failure(exc, tab.page if tab is not None else None)
        if tab is not None and tab.closed:
            return action_error(self._closed_error(tab).code)
        if dead or self._context is None or self._closing:
            return action_error("MINI_BROWSER_CLOSED")
        if tab is not None and self.tabs.get(tab.id) is not tab:
            return action_error("MINI_BROWSER_TAB_CLOSED")
        return action_error("MINI_BROWSER_INTERNAL", secrets=secrets, detail=line)

    def _finish(
        self,
        result: Any,
        tab: Optional[Tab],
        *,
        owner: Optional[str] = None,
        notes: Any = (),
        extra_tabs: Any = (),
    ) -> Dict[str, Any]:
        """Attach the tab and its pending notices; scrub every string.

        ``notes`` lead the message. An owner whose tabs were lost when the
        browser closed is told so once, on its first result afterwards.
        """
        if isinstance(result, dict):
            result = dict(result)
        else:
            result = {
                "status": "success",
                "message": "Done." if result is None else str(result),
            }
        lead = list(notes or ())
        if owner and owner in self._closed_owners:
            self._closed_owners.discard(owner)
            if result.get("error_code") not in _CLOSED_CODES:
                running = self._context is not None and self.status == "ready"
                lead.insert(0, RELAUNCH_NOTE if running else CLOSED_NOTE)
        if lead:
            result["message"] = " ".join(
                [*lead, str(result.get("message") or "")]
            ).strip()
        events = self._drain_events([tab, *extra_tabs])
        if events:
            result["events"] = list(result.get("events") or []) + events
        if tab is not None:
            index = self._tab_index(tab)
            if index is not None:
                result["tab"] = {"id": tab.id, "index": index}
        return scrub_data(result, self._secrets())

    def _drain_events(self, tabs: List[Optional[Tab]]) -> List[Dict[str, Any]]:
        """Take the pending notices of ``tabs``; a notice queued on two tabs
        (a popup's, on the popup and its opener) is delivered once."""
        out: List[Dict[str, Any]] = []
        keys: Set[str] = set()
        seen: Set[int] = set()
        for tab in tabs:
            if tab is None or id(tab) in seen or not tab.events:
                continue
            seen.add(id(tab))
            events, tab.events[:] = list(tab.events), []
            for event in events:
                key = event.get("_key")
                if key:
                    if key in keys:
                        continue
                    keys.add(key)
                out.append({k: v for k, v in event.items() if k != "_key"})
        if keys:
            for other in self.tabs.values():
                if other.events:
                    other.events[:] = [
                        e for e in other.events if e.get("_key") not in keys
                    ]
        return out

    async def _observe(self, tab: Tab) -> Optional[Dict[str, Any]]:
        """A compact observation of the tab, or None if it cannot be taken."""
        try:
            from app.mini_browser import observe as observe_module
        except Exception:
            return None
        try:
            return await asyncio.wait_for(
                observe_module.observe(self, tab, compact=True), OBSERVE_TIMEOUT_S
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug(f"[MiniBrowser] Observation failed: {type(exc).__name__}")
            return None

    def _find_tab(self, ref: Any) -> Tab:
        """A tab by its index (as listed) or its id."""
        if not isinstance(ref, bool):
            if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
                ordered = list(self.tabs.values())
                index = int(ref)
                if 0 <= index < len(ordered):
                    return ordered[index]
            elif isinstance(ref, str) and ref.strip() in self.tabs:
                return self.tabs[ref.strip()]
        raise MiniBrowserError("MINI_BROWSER_TAB_NOT_FOUND", tab=_clip(str(ref), 40))

    # ── owners ───────────────────────────────────────────────────────────────

    def _claimable(self, tab: Tab, owner: str, *, explicit: bool = False) -> bool:
        """May ``owner`` take ``tab`` over?

        Its own tab always. Another agent's tab never. A user tab only when
        the user is not using it (no input for USER_ACTIVE_S, no take
        control) and either it is blank (about:blank with no history), or it
        is the tab the user is viewing and the owner is the dedicated Mini
        Browser chat, or the owner asked for it (``mini_browser_tabs``
        action='switch', ``explicit``).
        """
        if tab.user_control or tab.ops:
            return False
        if tab.owner == owner:
            return True
        if tab.owner is not None:
            return False
        if time.monotonic() - tab.last_user_input < USER_ACTIVE_S:
            return False
        if _is_blank(tab):
            return True
        return tab.id == self.viewed_tab_id and (owner == SESSION_ID or explicit)

    def _claim(self, tab: Tab, owner: str) -> None:
        previous = tab.owner
        if previous != owner:
            if previous is None:
                if not _is_blank(tab):
                    # The user's page (possibly with unsaved work) is still here.
                    tab.left_user_at = time.monotonic()
                    tab.left_user_nav = self._nav_seq.get(tab.id, 0)
            elif self._owner_current.get(previous) == tab.id:
                self._owner_current.pop(previous, None)
            # Notices about what happened before belong to the previous owner.
            tab.events.clear()
        self._apply_owner(tab, owner)
        self._owner_current[owner] = tab.id
        tab.touch_agent()
        self._schedule_state()

    def _apply_owner(self, tab: Tab, owner: Optional[str]) -> None:
        if owner is None:
            tab.owner, tab.owner_label, tab.owner_kind, tab.parent_owner = (
                None,
                "",
                OWNER_KIND_USER,
                None,
            )
            return
        label, kind, parent = self._owner_info(owner)
        tab.owner, tab.owner_label, tab.owner_kind, tab.parent_owner = (
            owner,
            label,
            kind,
            parent,
        )

    def _owner_info(self, owner: str, depth: int = 0) -> Tuple[str, str, Optional[str]]:
        """``(label, kind, parent)`` for an owner id, from the agent runtime."""
        if owner == SESSION_ID:
            return (
                self._session_title(owner) or SESSION_TITLE,
                OWNER_KIND_MINI_BROWSER,
                None,
            )
        if owner == DEFAULT_OWNER:
            return self._session_title(owner) or "Main", OWNER_KIND_MAIN, None
        if owner.startswith("sub_"):
            record = config.subagent_record(owner)
            parent = record[0] if record else None
            if parent:
                self._parents[owner] = parent
            agent_type = record[1] if record else "sub-agent"
            parent_label = (
                self._owner_info(parent, depth + 1)[0] if parent and depth < 3 else ""
            )
            label = (
                f"{agent_type} (sub-agent of {parent_label})"
                if parent_label
                else agent_type
            )
            return _clip(label, 80), OWNER_KIND_SUBAGENT, parent
        return self._session_title(owner) or "Chat", OWNER_KIND_SESSION, None

    @staticmethod
    def _session_title(session_id: str) -> str:
        title = getattr(config.session_record(session_id), "title", "")
        return _clip(title, 80) if isinstance(title, str) else ""

    def _parent_of(self, owner: Optional[str]) -> Optional[str]:
        if not owner or not owner.startswith("sub_"):
            return None
        parent = self._parents.get(owner)
        if parent is None:
            record = config.subagent_record(owner)
            if record is not None and record[0]:
                parent = self._parents[owner] = record[0]
        return parent

    def _is_revoked(self, owner: str) -> bool:
        """A sub-agent whose parent run was stopped may never act again.

        Stops are recorded process-wide by ``lifecycle.cancel_owner`` (also
        while this browser thread was not running), at the moment of Stop.
        """
        if owner in self._revoked:
            return True
        if not owner.startswith("sub_"):
            return False
        record = config.subagent_record(owner)
        if record is None or not record[0]:
            return False
        stopped = lifecycle.parent_stop(record[0])
        if stopped is None:
            return False
        created = record[2]
        if created is None or created <= stopped:
            self._revoked.add(owner)
            return True
        return False

    def _run_busy(self, owner: Optional[str]) -> bool:
        """The owner's run (or its parent's) is running or stopping.

        Read from the process-wide records of ``lifecycle``, so a run that
        started before this browser thread existed counts as busy too.
        """
        if not owner:
            return False
        if lifecycle.is_run_busy(owner):
            return True
        parent = self._parent_of(owner)
        return parent is not None and lifecycle.is_run_busy(parent)

    def _owner_busy(self, owner: str) -> bool:
        if self._run_busy(owner) or self._owner_ops.get(owner):
            return True
        return any(t.ops for t in self.tabs.values() if t.owner == owner)

    def _tab_busy(self, tab: Tab) -> bool:
        return bool(tab.ops) or self._run_busy(tab.owner)

    def _owner_tab_count(self, owner: str) -> int:
        return sum(1 for t in self.tabs.values() if t.owner == owner)

    def _agent_busy(self) -> bool:
        return any(self._owner_ops.values()) or any(t.ops for t in self.tabs.values())

    def _latest_agent_tab(self) -> Optional[Tab]:
        used = [
            t
            for t in self.tabs.values()
            if t.owner is not None and t.last_agent_use > 0
        ]
        return max(used, key=lambda t: t.last_agent_use) if used else None

    def _follow(self, tab: Tab) -> None:
        """Follow-view: show the tab an agent works in, unless the viewed tab
        is itself in use (by another agent or the user)."""
        if (
            not self.follow
            or self.viewed_tab_id == tab.id
            or self.tabs.get(tab.id) is not tab
        ):
            return
        viewed = self.tabs.get(self.viewed_tab_id or "")
        if viewed is not None:
            now = time.monotonic()
            if (
                viewed.ops
                or now - viewed.last_agent_use < FOLLOW_HOLD_S
                or now - viewed.last_user_input < USER_HOLD_S
            ):
                return
        self.viewed_tab_id = tab.id
        self._schedule_state()
        self.spawn(self._stream.sync())

    # ── lifecycle hooks (via lifecycle.py) ───────────────────────────────────

    def on_run_state(self, owner: str, state: str) -> None:
        """An agent run started / is stopping / went idle (recorded process-wide)."""
        if lifecycle.record_run_state(owner, state):
            self._schedule_state()

    def run_state_changed(self, owner: str) -> None:
        """``lifecycle.on_run_state`` recorded a change: republish busy flags."""
        self._schedule_state()

    def release_owner(self, owner: str, close_tabs: bool) -> None:
        """An owner is gone (chat deleted, sub-agent finished).

        Its tabs close, except one the user is working in or looking at, which
        becomes a user tab (as do all of them with ``close_tabs=False``). The
        last open tab is never closed: it becomes a user tab too.
        """
        if not owner:
            return
        viewing = bridge.has_viewers()
        owned = [tab for tab in self.tabs.values() if tab.owner == owner]
        closing = [
            tab
            for tab in owned
            if close_tabs
            and not tab.user_control
            and not (viewing and tab.id == self.viewed_tab_id)
        ]
        if closing and len(closing) == len(self.tabs):
            keep_last = self.tabs.get(self.viewed_tab_id or "") or closing[-1]
            closing.remove(keep_last)
        for tab in owned:
            if tab in closing:
                self.spawn(self._close_page(tab.page))
            else:
                self._apply_owner(tab, None)
                tab.user_control = False
        self._owner_current.pop(owner, None)
        self._tab_switches.pop(owner, None)
        self._closed_owners.discard(owner)
        lifecycle.forget_owner(owner)
        self._schedule_state()

    async def cancel_owner(self, owner: str, include_children: bool = True) -> None:
        """The user pressed Stop: cancel the owner's in-flight operations.

        With ``include_children``, its sub-agents are cancelled too and revoked
        for good (their later operations get MINI_BROWSER_STOPPED). Pages stop
        loading. User tabs are never touched.
        """
        if not owner:
            return
        if include_children:
            lifecycle.record_parent_stop(owner)
        await self.cancel_owner_ops(owner, include_children=include_children)

    async def cancel_owner_ops(self, owner: str, include_children: bool = True) -> None:
        """:meth:`cancel_owner` once the Stop is recorded (``lifecycle`` hook)."""
        if not owner:
            return
        owners = {owner}
        if include_children:
            known = set(self._owner_ops) | {
                t.owner for t in self.tabs.values() if t.owner
            }
            for other in known:
                if other != owner and self._parent_of(other) == owner:
                    self._revoked.add(other)
                    owners.add(other)
        for name in owners:
            for task in list(self._owner_ops.get(name, ())):
                task.cancel()
        for tab in list(self.tabs.values()):
            if tab.owner in owners:
                for task in list(tab.ops):
                    task.cancel()
                self.spawn(self._stop_loading(tab))
        self._schedule_state()

    # ── helpers for ops ──────────────────────────────────────────────────────

    async def publish_pointer(self, tab: Tab, x: float, y: float, kind: str) -> None:
        """Show the agent's pointer (CSS px) in the live view (≤ 30 moves/s)."""
        try:
            px, py = float(x), float(y)
        except (TypeError, ValueError):
            return
        if not (math.isfinite(px) and math.isfinite(py)):
            return
        tab.mouse_x, tab.mouse_y = px, py
        if tab.id != self.viewed_tab_id or not bridge.has_viewers():
            return
        kind = kind if kind in ("move", "down", "up", "click") else "move"
        now = time.monotonic()
        if (
            kind == "move"
            and now - self._pointer_sent.get(tab.id, 0.0) < POINTER_INTERVAL_S
        ):
            return
        self._pointer_sent[tab.id] = now
        width, height = self._page_size(tab)
        bridge.publish(
            "pointer",
            {
                "tabId": tab.id,
                "x": _clamp_unit(px / width),
                "y": _clamp_unit(py / height),
                "kind": kind,
            },
        )

    def add_event(self, tab: Tab, kind: str, message: str, **extra: Any) -> None:
        """A notice for the tab's agent (attached to its next result) and a UI toast."""
        event = self._agent_notice(tab, kind, message, **extra)
        payload = {
            "kind": event["kind"],
            "level": event.pop("_level"),
            "message": event["message"],
            "tabId": tab.id,
        }
        if isinstance(event.get("path"), str):
            # The UI's open-file/show-in-folder actions resolve paths against
            # the agent workspace, so it gets the workspace-relative form
            # (the agent's notice keeps the absolute path).
            payload["path"] = _workspace_relative(event["path"])
        if kind == EVENT_DOWNLOAD:
            # An executable the page pushed: the UI offers no one-click "Open".
            payload["dangerous"] = bool(event.get("dangerous"))
        bridge.publish("event", payload)

    def _agent_notice(
        self, tab: Tab, kind: str, message: str, **extra: Any
    ) -> Dict[str, Any]:
        """Queue a notice for the tab's agent only (no UI toast)."""
        secrets = self._secrets()
        level = extra.pop("level", None)
        event: Dict[str, Any] = {
            "kind": kind,
            "message": _clip(scrub(str(message), secrets), 500),
        }
        for key, value in extra.items():
            if isinstance(value, str):
                event[key] = _clip(scrub(value, secrets), 500)
            elif isinstance(value, (bool, int, float)) or value is None:
                event[key] = value
        tab.events.append(dict(event))
        del tab.events[:-EVENTS_PER_TAB]
        event["_level"] = (
            level
            if level in ("info", "warning", "error")
            else _EVENT_LEVELS.get(kind, "info")
        )
        return event

    def vault(self) -> Any:
        """The credential vault (``vault.get_vault()``)."""
        from app.mini_browser.vault import get_vault

        return get_vault()

    def ui_origins(self) -> frozenset:
        """CraftBot's own UI origins (``host:port``), never opened in the browser."""
        return bridge.ui_origins()

    def spawn(self, coro: Awaitable[Any], name: Optional[str] = None) -> asyncio.Task:
        """Run ``coro`` as a tracked background task in a clean context."""
        loop = asyncio.get_running_loop()
        task = contextvars.Context().run(loop.create_task, coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None and not isinstance(exc, MiniBrowserError):
            line = _clip(scrub(first_line(exc), self._secrets()), 200)
            logger.warning(
                f"[MiniBrowser] Background task failed: {type(exc).__name__}: {line}"
            )

    # ═════════════════════════════════════════════════════════════════════════
    # Tabs and pages
    # ═════════════════════════════════════════════════════════════════════════

    async def _open_tab(self, owner: Optional[str]) -> Tab:
        """A new tab for ``owner`` (None = the user), in a window of its own.

        Opening runs in a task of its own: a caller cancelled half-way (the
        user pressed Stop) never leaves an ownerless or half-set-up tab
        behind; the tab is finished and kept for its owner.
        """
        if self._context is None:
            raise self._not_running_error()
        task = self.spawn(self._open_tab_now(owner))
        return await _wait_shared(task, "MINI_BROWSER_CLOSED")

    def _not_running_error(self) -> MiniBrowserError:
        """No browser: closed under the caller's feet, or simply not started."""
        if self._closing:
            return MiniBrowserError("MINI_BROWSER_CLOSED")
        return MiniBrowserError("MINI_BROWSER_NOT_RUNNING")

    async def _open_tab_now(self, owner: Optional[str]) -> Tab:
        context = self._context
        if context is None:
            raise self._not_running_error()
        if len(self.tabs) >= MAX_TOTAL_TABS:
            raise MiniBrowserError("MINI_BROWSER_TOO_MANY_TABS", count=len(self.tabs))
        try:
            page, cdp, target_id, own_window = await self._create_page(context)
        except MiniBrowserError:
            raise
        except asyncio.TimeoutError:
            raise MiniBrowserError(
                "MINI_BROWSER_TIMEOUT", what="Opening a tab", seconds=15
            ) from None
        except Exception as exc:
            if self._note_failure(exc):
                raise MiniBrowserError("MINI_BROWSER_CLOSED") from None
            raise MiniBrowserError(
                "MINI_BROWSER_INTERNAL", detail=_clip(first_line(exc), 200)
            ) from None
        if self._context is not context:
            await self._close_page(page)
            raise MiniBrowserError("MINI_BROWSER_CLOSED")
        tab = self._page_tabs.get(page)
        if tab is None:
            tab = self._register_tab(page, owner)
        elif tab.owner != owner:
            self._apply_owner(tab, owner)
        await self._setup_page(tab, cdp, target_id, own_window=own_window)
        return tab

    async def _create_page(self, context: Any) -> Tuple[Any, Any, Optional[str], bool]:
        """A new blank page: ``(page, cdp session or None, target id, own window)``.

        Opened through the browser's CDP ``Target.createTarget`` with
        ``newWindow``, so it is the front tab of a window of its own, and
        adopted from the context's 'page' event by its target id. Falls back
        to ``context.new_page()`` (which opens a tab in the last active
        window) when that is not available.
        """
        session = self._browser_cdp
        if session is not None:
            self._creating += 1
            try:
                created = await self._cdp_send(
                    session,
                    "Target.createTarget",
                    {"url": "about:blank", "newWindow": True},
                    timeout=NEW_PAGE_TIMEOUT_S,
                )
            finally:
                self._creating -= 1
            target_id = (created or {}).get("targetId")
            if isinstance(target_id, str) and target_id:
                waiter = self._own_targets.get(target_id)
                if waiter is None:
                    waiter = asyncio.get_running_loop().create_future()
                    self._own_targets[target_id] = waiter
                try:
                    page, cdp = await asyncio.wait_for(waiter, NEW_PAGE_TIMEOUT_S)
                except asyncio.TimeoutError:
                    self._abandoned_targets.add(target_id)  # closed if it shows up
                    raise
                finally:
                    self._own_targets.pop(target_id, None)
                return page, cdp, target_id, True
            if self._context is not context:
                raise MiniBrowserError("MINI_BROWSER_CLOSED")
            logger.debug("[MiniBrowser] New window unavailable; opening a plain tab")
        self._own_pages_pending += 1
        try:
            page = await asyncio.wait_for(context.new_page(), NEW_PAGE_TIMEOUT_S)
        finally:
            self._own_pages_pending -= 1
        return page, None, None, False

    async def _ensure_one_tab(self) -> Tab:
        """At least one tab stays open (a headed window would close otherwise)."""
        if self.tabs:
            return next(iter(self.tabs.values()))
        tab = await self._open_tab(None)
        self.viewed_tab_id = tab.id
        self._schedule_state()
        self.spawn(self._stream.sync())
        return tab

    def _register_tab(self, page: Any, owner: Optional[str]) -> Tab:
        tab = Tab(id=f"t{next(self._tab_ids)}", page=page)
        self._apply_owner(tab, owner)
        self.tabs[tab.id] = tab
        self._attach_page(tab, page)
        if self.viewed_tab_id not in self.tabs:
            self.viewed_tab_id = tab.id
        self._schedule_state()
        return tab

    def _attach_page(self, tab: Tab, page: Any) -> None:
        tab.page = page
        self._page_tabs[page] = tab
        safely = _safely
        page.on("close", safely(lambda *_: self._on_page_close(page)))
        page.on("crash", safely(lambda *_: self._on_page_crash(page)))
        page.on(
            "dialog",
            safely(lambda dialog: self._spawn_safe(self._handle_dialog(page, dialog))),
        )
        page.on(
            "download",
            safely(
                lambda download: self._spawn_safe(self._handle_download(page, download))
            ),
        )
        page.on(
            "framenavigated",
            safely(lambda frame: self._on_frame_navigated(page, frame)),
        )
        page.on("load", safely(lambda *_: self._on_page_load(page)))

    def _spawn_safe(self, coro: Any) -> Optional[asyncio.Task]:
        try:
            return self.spawn(coro)
        except Exception as exc:  # only without a running loop (teardown)
            coro.close()
            logger.debug(
                f"[MiniBrowser] Could not schedule a handler: {type(exc).__name__}"
            )
            return None

    async def _setup_page(
        self,
        tab: Tab,
        cdp: Any = None,
        target_id: Optional[str] = None,
        *,
        own_window: bool = False,
    ) -> None:
        """Viewport, CDP session (blocking rules, loading tracking) and window
        bookkeeping for a page. ``own_window``: we opened it in a new window."""
        page = tab.page
        await self._apply_viewport(tab)
        if cdp is None and self._context is not None:
            try:
                cdp = await asyncio.wait_for(
                    self._context.new_cdp_session(page), CDP_TIMEOUT_S
                )
            except Exception as exc:
                logger.debug(
                    f"[MiniBrowser] No CDP session for {tab.id}: {type(exc).__name__}"
                )
        if tab.page is not page:
            return  # replaced meanwhile (crash recovery)
        tab.cdp = cdp
        if cdp is not None:
            cdp.on(
                "Network.requestWillBeSent",
                _safely(functools.partial(self._on_request, page)),
            )
            cdp.on(
                "Network.loadingFinished",
                _safely(functools.partial(self._on_request_done, page)),
            )
            cdp.on(
                "Network.loadingFailed",
                _safely(functools.partial(self._on_request_done, page)),
            )
            await self._cdp_send(cdp, "Network.enable", NETWORK_ENABLE)
            await self._cdp_send(
                cdp, "Network.setBlockedURLs", {"urls": self._blocked_patterns}
            )
            tree = await self._cdp_send(cdp, "Page.getFrameTree")
            frame = ((tree or {}).get("frameTree") or {}).get("frame") or {}
            if isinstance(frame.get("id"), str):
                self._main_frames[tab.id] = frame["id"]
            if not target_id:
                target_id = await _target_id(self, cdp)
        tab.target_id = target_id or tab.target_id
        await self._locate_window(tab, own_window=own_window)
        self._schedule_nav_refresh(tab)

    async def _locate_window(self, tab: Tab, *, own_window: bool) -> None:
        """Which browser window holds the tab, and is it that window's front tab."""
        session = self._browser_cdp
        if session is None or not tab.target_id:
            return
        found = await self._cdp_send(
            session, "Browser.getWindowForTarget", {"targetId": tab.target_id}
        )
        window = (found or {}).get("windowId")
        if not isinstance(window, int) or isinstance(window, bool):
            return
        for other, tab_id in list(self._front_tab.items()):
            if tab_id == tab.id and other != window:
                del self._front_tab[other]
        tab.window_id = window
        if own_window:
            self._front_tab[window] = tab.id
        elif self._front_tab.get(window) != tab.id:
            # A tab that appeared in an existing window (a popup) is in front
            # there now, or not: unknown until the next agent action decides.
            self._front_tab.pop(window, None)

    async def _apply_viewport(self, tab: Tab) -> None:
        try:
            size = tab.page.viewport_size
            if size and (size["width"], size["height"]) == tuple(self.viewport):
                return
            await asyncio.wait_for(
                tab.page.set_viewport_size(
                    {"width": self.viewport[0], "height": self.viewport[1]}
                ),
                PAGE_CALL_TIMEOUT_S,
            )
        except Exception as exc:
            logger.debug(
                f"[MiniBrowser] Viewport not applied to {tab.id}: {type(exc).__name__}"
            )

    def _page_size(self, tab: Tab) -> Tuple[int, int]:
        try:
            size = tab.page.viewport_size
        except Exception:
            size = None
        if size and size.get("width") and size.get("height"):
            return int(size["width"]), int(size["height"])
        return self.viewport

    async def _bring_to_front(self, tab: Tab) -> None:
        """UI view changes: headed windows only paint their front tab; headless
        needs nothing (the live view streams any tab), and bringing a tab to
        the front there would push an agent's tab into the background."""
        if self.settings.headless:
            return
        try:
            await asyncio.wait_for(tab.page.bring_to_front(), PAGE_CALL_TIMEOUT_S)
        except Exception as exc:
            logger.debug(f"[MiniBrowser] bring_to_front: {type(exc).__name__}")
            return
        if tab.window_id is not None:
            self._front_tab[tab.window_id] = tab.id

    async def _agent_front(self, tab: Tab) -> None:
        """Make an agent's tab the active tab of its window before it acts.

        Chromium throttles input to a window's background tabs (~1 s per
        mouse event). Every tab we open has a window of its own, so this is
        only needed after a popup took the front of the window (or for a tab
        whose window is unknown).
        """
        window = tab.window_id
        if window is not None and self._front_tab.get(window) == tab.id:
            return
        try:
            await asyncio.wait_for(tab.page.bring_to_front(), PAGE_CALL_TIMEOUT_S)
        except Exception as exc:
            logger.debug(f"[MiniBrowser] bring_to_front: {type(exc).__name__}")
            return
        if window is not None:
            self._front_tab[window] = tab.id

    async def _close_page(self, page: Any) -> None:
        try:
            await asyncio.wait_for(page.close(), CLOSE_TIMEOUT_S)
        except Exception as exc:
            logger.debug(f"[MiniBrowser] Page close: {type(exc).__name__}")

    def _on_page_close(self, page: Any) -> None:
        tab = self._page_tabs.pop(page, None)
        if tab is None or tab.page is not page or self.tabs.get(tab.id) is not tab:
            return
        self._remove_tab(tab)

    def _remove_tab(self, tab: Tab) -> None:
        order = list(self.tabs)
        position = order.index(tab.id)
        del self.tabs[tab.id]
        tab.mark_closed(CLOSED_TAB)  # an operation on it ends at once
        self._retire_secrets(tab)
        self._stream.forget_tab(tab.id)
        self._main_frames.pop(tab.id, None)
        self._pending_docs.pop(tab.id, None)
        self._nav_seq.pop(tab.id, None)
        self._blocks_reported.pop(tab.id, None)
        self._pointer_sent.pop(tab.id, None)
        self._nav_dirty.discard(tab.id)
        refresh = self._nav_refresh.pop(tab.id, None)
        if refresh is not None and refresh is not asyncio.current_task():
            refresh.cancel()
        probe = self._probes.pop(tab.id, None)
        if probe is not None and probe is not asyncio.current_task():
            probe.cancel()
        if tab.window_id is not None and self._front_tab.get(tab.window_id) == tab.id:
            del self._front_tab[tab.window_id]
        for owner, tab_id in list(self._tab_switches.items()):
            if tab_id == tab.id:
                del self._tab_switches[owner]
        opener = self.tabs.get(tab.opener_id or "")
        if tab.owner and self._owner_current.get(tab.owner) == tab.id:
            mine = [t for t in self.tabs.values() if t.owner == tab.owner]
            fallback = (
                opener if opener is not None and opener.owner == tab.owner else None
            )
            if fallback is None and mine:
                fallback = max(mine, key=lambda t: t.last_agent_use)
            if fallback is not None:
                self._owner_current[tab.owner] = fallback.id
            else:
                self._owner_current.pop(tab.owner, None)
        if self.viewed_tab_id == tab.id:
            neighbours = [t for t in order if t != tab.id]
            following = order[position + 1 :] if position + 1 < len(order) else []
            pick = opener.id if opener is not None else None
            if pick is None and following:
                pick = following[0]
            if pick is None and neighbours:
                pick = neighbours[-1]
            self.viewed_tab_id = pick
            self.spawn(self._stream.sync())
        if (
            not self.tabs
            and self._context is not None
            and not self._closing
            and self.status == "ready"
        ):
            self.spawn(self._ensure_one_tab())
        self._schedule_state()

    def _on_page_crash(self, page: Any) -> None:
        tab = self._page_tabs.get(page)
        if tab is None or tab.crashed:
            return
        tab.crashed = True
        tab.loading = False
        self._pending_docs.pop(tab.id, None)
        self.add_event(
            tab,
            EVENT_CRASH,
            "This tab crashed. It reopens automatically the next time it is used.",
        )
        self.spawn(self._stream.sync())
        self._schedule_state()

    async def _recover_if_crashed(self, tab: Tab) -> None:
        if not tab.crashed:
            return
        task = self._recoveries.get(tab.id)
        if task is None or task.done():
            task = self._recoveries[tab.id] = self.spawn(self._recover(tab))
        # A recovery cut short by the browser closing is not our cancellation.
        await _wait_shared(task, "MINI_BROWSER_CLOSED")

    async def _recover(self, tab: Tab) -> None:
        """Replace a crashed page with a fresh one in the same tab slot."""
        context = self._context
        if context is None:
            raise MiniBrowserError("MINI_BROWSER_CLOSED")
        old = tab.page
        url = tab.url  # before the new page's own about:blank overwrites it
        try:
            page, cdp, target_id, own_window = await self._create_page(context)
        except MiniBrowserError:
            raise
        except Exception:
            raise MiniBrowserError("MINI_BROWSER_PAGE_UNRESPONSIVE") from None
        if self.tabs.get(tab.id) is not tab or self._context is not context:
            await self._close_page(page)
            if self._context is not context:
                raise MiniBrowserError("MINI_BROWSER_CLOSED")
            return
        self._page_tabs.pop(old, None)
        self._attach_page(tab, page)
        tab.crashed = False
        tab.cdp = None
        tab.loading = False
        tab.unresponsive = False
        self._main_frames.pop(tab.id, None)
        self._pending_docs.pop(tab.id, None)
        self.spawn(self._close_page(old))
        await self._setup_page(tab, cdp, target_id, own_window=own_window)
        reason = urls.blocked_reason(
            url, allow_file=self.settings.allow_file_urls, ui_origins=self.ui_origins()
        )
        if url.startswith(("http://", "https://")) and not reason:
            try:
                await self._goto(tab, url)
            except MiniBrowserError:
                if tab.closed:
                    raise
                self.add_event(
                    tab,
                    EVENT_ERROR,
                    f"Could not reload {_clip(url, 200)} after the crash.",
                )
        self._agent_notice(
            tab,
            EVENT_NOTICE,
            "The tab was reopened after a crash; look at the page again before acting.",
        )
        self.spawn(self._stream.sync())
        self._schedule_state()

    def _on_context_page(self, page: Any) -> None:
        task = self._spawn_safe(self._adopt_page(page))
        if task is not None:
            self._adoptions.add(task)
            task.add_done_callback(self._adoptions.discard)

    async def _adopt_page(self, page: Any) -> None:
        """A page that appeared on its own: one we opened in a new window
        (handed to its waiting opener by target id), a popup (inherits its
        opener's owner) or a window a page or the user opened."""
        context = self._context
        if page in self._page_tabs or context is None or _page_closed(page):
            return
        cdp = None
        target_id: Optional[str] = None
        try:
            cdp = await asyncio.wait_for(context.new_cdp_session(page), CDP_TIMEOUT_S)
            target_id = await _target_id(self, cdp)
        except Exception as exc:
            logger.debug(f"[MiniBrowser] New page not inspected: {type(exc).__name__}")
        handed_over = False
        try:
            deadline = time.monotonic() + OWN_PAGE_WAIT_S
            while True:
                if (
                    page in self._page_tabs
                    or self._context is not context
                    or _page_closed(page)
                ):
                    return
                if target_id and target_id in self._abandoned_targets:
                    self._abandoned_targets.discard(target_id)
                    await self._close_page(page)  # its opener gave up on it
                    return
                waiter = self._own_targets.get(target_id) if target_id else None
                if waiter is not None:
                    if not waiter.done():
                        waiter.set_result((page, cdp))
                        handed_over = True
                    return
                if (
                    self._creating == 0 and self._own_pages_pending == 0
                ) or time.monotonic() >= deadline:
                    break
                await asyncio.sleep(0.02)  # our own new page registers itself
            try:
                opener = await asyncio.wait_for(page.opener(), PAGE_CALL_TIMEOUT_S)
            except Exception:
                opener = None
            if (
                page in self._page_tabs
                or self._context is not context
                or _page_closed(page)
            ):
                return
            opener_tab = self._page_tabs.get(opener) if opener is not None else None
            owner = opener_tab.owner if opener_tab is not None else None
            if len(self.tabs) >= MAX_TOTAL_TABS or (
                owner is not None
                and self._owner_tab_count(owner)
                >= self.settings.max_agent_tabs + POPUP_SLACK
            ):
                if opener_tab is not None:
                    self.add_event(
                        opener_tab,
                        EVENT_BLOCKED,
                        "A pop-up was closed: too many tabs are open.",
                    )
                await self._close_page(page)
                return
            tab = self._register_tab(page, owner)
            if opener_tab is not None:
                tab.opener_id = opener_tab.id
                if self.viewed_tab_id == opener_tab.id:
                    self.viewed_tab_id = tab.id  # like a browser focusing a new tab
            if owner is not None:
                self._owner_current[owner] = tab.id
                self._tab_switches[owner] = tab.id
                tab.touch_agent()
                notice = (
                    f"The page opened a new tab (index {self._tab_index(tab)}); your "
                    "next actions use it. Switch back or close it with mini_browser_tabs."
                )
                key = f"popup:{tab.id}"
                self._agent_notice(tab, EVENT_POPUP, notice, _key=key)
                if opener_tab is not None and opener_tab.owner == owner:
                    # Where the owner's action in flight collects its notices.
                    self._agent_notice(opener_tab, EVENT_POPUP, notice, _key=key)
            handed_over = True
            await self._setup_page(tab, cdp, target_id)
            self.spawn(self._stream.sync())
            self._schedule_state()
        finally:
            if not handed_over and cdp is not None:
                self._spawn_safe(_detach_quietly(cdp))

    def _tab_index(self, tab: Tab) -> Optional[int]:
        for index, tab_id in enumerate(self.tabs):
            if tab_id == tab.id:
                return index
        return None

    def _retire_secrets(self, tab: Tab) -> None:
        if tab.filled_secrets:
            self._retired_secrets.extend(tab.filled_secrets)
            del self._retired_secrets[:-RETIRED_SECRETS]

    def _secrets(self) -> List[str]:
        found = list(self._retired_secrets)
        for tab in self.tabs.values():
            found.extend(tab.filled_secrets)
        return found

    # ── navigation ───────────────────────────────────────────────────────────

    def _resolve(self, text: Any, *, allow_search: bool) -> urls.Target:
        return urls.resolve(
            text if isinstance(text, str) else "",
            allow_history=False,
            allow_search=allow_search,
            search_url=self.settings.search_url,
            allow_file=self.settings.allow_file_urls,
            ui_origins=self.ui_origins(),
        )

    async def _goto(self, tab: Tab, url: str) -> None:
        """Navigate and wait for the DOM. Raises MiniBrowserError."""
        try:
            await asyncio.wait_for(
                tab.page.goto(
                    url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS
                ),
                NAVIGATION_TIMEOUT_MS / 1000 + 5,
            )
        except Exception as exc:
            self._raise_navigation_error(exc, tab, url)
        finally:
            self._schedule_nav_refresh(tab)
        if tab.closed:
            raise self._closed_error(tab)

    def _raise_navigation_error(self, exc: BaseException, tab: Tab, url: str) -> None:
        if tab.closed:
            raise self._closed_error(tab) from None
        if (
            isinstance(exc, asyncio.TimeoutError)
            or type(exc).__name__ == "TimeoutError"
        ):
            raise MiniBrowserError(
                "MINI_BROWSER_TIMEOUT",
                what="Loading the page",
                seconds=NAVIGATION_TIMEOUT_MS // 1000,
            ) from None
        line = first_line(exc)
        if self._note_failure(exc, tab.page):
            raise MiniBrowserError("MINI_BROWSER_CLOSED") from None
        if _is_benign_navigation(line):
            return
        detail = _AT_URL_SUFFIX_RE.sub("", _API_PREFIX_RE.sub("", line))
        raise MiniBrowserError(
            "MINI_BROWSER_NAVIGATION_FAILED",
            url=_clip(url, 200),
            detail=_clip(detail, 200),
        ) from None

    async def _stop_loading(self, tab: Tab) -> None:
        """Stop a tab's page load (CDP Page.stopLoading, else window.stop())."""
        if tab.closed:
            return
        if tab.cdp is not None:
            if (
                await self._cdp_send(
                    tab.cdp, "Page.stopLoading", timeout=STOP_LOADING_TIMEOUT_S
                )
                is not None
            ):
                self._schedule_nav_refresh(tab)
                return
        try:
            await asyncio.wait_for(
                tab.page.evaluate("window.stop()"), STOP_LOADING_TIMEOUT_S
            )
        except Exception:
            pass
        self._schedule_nav_refresh(tab)

    def _on_frame_navigated(self, page: Any, frame: Any) -> None:
        tab = self._page_tabs.get(page)
        if tab is None:
            return
        try:
            if frame.parent_frame is not None:
                return
            url = frame.url
        except Exception:
            return
        if isinstance(url, str) and url and not url.startswith("chrome-error:"):
            tab.url = url
        tab.unresponsive = False  # a committed document answers again
        self._bump_nav(tab)
        self._schedule_nav_refresh(tab)
        self._schedule_state()

    def _bump_nav(self, tab: Tab) -> None:
        self._nav_seq[tab.id] = self._nav_seq.get(tab.id, 0) + 1

    def _on_page_load(self, page: Any) -> None:
        tab = self._page_tabs.get(page)
        if tab is not None:
            self._schedule_nav_refresh(tab)

    def _on_request(self, page: Any, params: Any) -> None:
        """CDP Network.requestWillBeSent: a main-frame document starts loading."""
        tab = self._page_tabs.get(page)
        if (
            tab is None
            or not isinstance(params, dict)
            or params.get("type") != "Document"
        ):
            return
        if params.get("frameId") != self._main_frames.get(tab.id):
            return
        self._pending_docs[tab.id] = params.get("requestId")
        self._bump_nav(tab)
        if not tab.loading:
            tab.loading = True
            self._schedule_state()

    def _on_request_done(self, page: Any, params: Any) -> None:
        tab = self._page_tabs.get(page)
        if tab is None or not isinstance(params, dict):
            return
        if (
            tab.id in self._pending_docs
            and params.get("requestId") == self._pending_docs[tab.id]
        ):
            del self._pending_docs[tab.id]
            self._schedule_nav_refresh(tab)

    def _schedule_nav_refresh(self, tab: Tab) -> None:
        """Refresh a tab's url/title/loading/history soon (coalesced per tab)."""
        if self.tabs.get(tab.id) is not tab:
            return
        running = self._nav_refresh.get(tab.id)
        if running is not None and not running.done():
            self._nav_dirty.add(tab.id)
            return
        try:
            self._nav_refresh[tab.id] = self.spawn(self._nav_refresh_loop(tab))
        except RuntimeError:
            pass  # no running loop (teardown)

    async def _nav_refresh_loop(self, tab: Tab) -> None:
        try:
            while True:
                self._nav_dirty.discard(tab.id)
                await self._refresh_nav(tab)
                if tab.id not in self._nav_dirty or self.tabs.get(tab.id) is not tab:
                    return
        finally:
            if self._nav_refresh.get(tab.id) is asyncio.current_task():
                del self._nav_refresh[tab.id]

    async def _refresh_nav(self, tab: Tab) -> None:
        page = tab.page
        try:
            if tab.crashed or page.is_closed():
                return
        except Exception:
            return
        seq = self._nav_seq.get(tab.id, 0)
        entry_url = None
        if tab.cdp is not None:
            history = await self._cdp_send(
                tab.cdp, "Page.getNavigationHistory", timeout=TITLE_TIMEOUT_S
            )
            if isinstance(history, dict):
                entries = history.get("entries") or []
                index = history.get("currentIndex", -1)
                if isinstance(index, int) and 0 <= index < len(entries):
                    tab.can_go_back = index > 0
                    tab.can_go_forward = index < len(entries) - 1
                    entry_url = entries[index].get("url") or None
        title, ready = await asyncio.gather(_page_title(page), _ready_state(page))
        if tab.page is not page or self.tabs.get(tab.id) is not tab:
            return
        if self._nav_seq.get(tab.id, 0) != seq:
            return  # a newer navigation happened meanwhile: its refresh decides
        url = page.url or ""
        # A failed navigation shows Chromium's error page; the tab shows the
        # address that failed, as a browser does.
        error_page = url.startswith("chrome-error:")
        shown = entry_url if error_page and entry_url else url
        if shown:
            tab.url = shown
        if title is not None:
            tab.title = _clip(title, 300)
        pending = tab.id in self._pending_docs
        tab.loading = pending or (tab.loading if ready is None else ready != "complete")
        reason = urls.blocked_reason(
            tab.url,
            allow_file=self.settings.allow_file_urls,
            ui_origins=self.ui_origins(),
        )
        if reason and tab.url != "about:blank":
            self._report_block(tab, tab.url, reason)
            # Blocked requests never load (an error page shows instead); only a
            # page that really loaded is sent away, never during a newer navigation.
            if not error_page and not pending:
                await self._leave_page(tab)
        self._schedule_state()

    def _report_block(self, tab: Tab, url: str, reason: str) -> None:
        """One notice per blocked navigation (refreshes repeat)."""
        key = (self._nav_seq.get(tab.id, 0), url)
        if self._blocks_reported.get(tab.id) == key:
            return
        self._blocks_reported[tab.id] = key
        self.add_event(
            tab,
            EVENT_BLOCKED,
            f"Blocked {_clip(url, 120)}: {reason}.",
            url=_clip(url, 300),
        )
        logger.info(f"[MiniBrowser] Blocked a navigation in {tab.id}: {reason}")

    async def _leave_page(self, tab: Tab) -> None:
        """Main-frame guard: a page that must not be shown goes to about:blank."""
        try:
            await asyncio.wait_for(
                tab.page.goto("about:blank"), PAGE_CALL_TIMEOUT_S * 2
            )
        except Exception as exc:
            logger.debug(
                f"[MiniBrowser] Could not blank {tab.id}: {type(exc).__name__}"
            )
        tab.url = "about:blank"
        tab.title = ""

    # ── dialogs & downloads ──────────────────────────────────────────────────

    async def _handle_dialog(self, page: Any, dialog: Any) -> None:
        """Answer every dialog at once (an open dialog blocks the page).

        alert, confirm and beforeunload ("leave site?") are accepted, prompt
        is dismissed, and the agent and the UI are told exactly what was
        answered. One exception: a "leave site?" on a tab that was the user's
        own tab until moments ago is declined (the user may have unsaved
        work there) and reported.
        """
        try:
            kind = str(dialog.type)
        except Exception:
            kind = "dialog"
        try:
            message = _clip(str(dialog.message or ""), 300)
        except Exception:
            message = ""
        tab = self._page_tabs.get(page)
        accept = kind != "prompt"
        guarded = (
            kind == "beforeunload"
            and tab is not None
            and tab.owner is not None
            and tab.left_user_at > 0
            and time.monotonic() - tab.left_user_at < RECENT_USER_TAB_S
            # still the very page the user had (not one the agent opened since)
            and self._nav_seq.get(tab.id, 0) == tab.left_user_nav
        )
        if guarded:
            accept = False
        if tab is not None:
            # Told BEFORE answering: the dialog holds the page (and the
            # operation that raised it) until then, so the notice always
            # reaches that operation's own result.
            self.add_event(
                tab,
                EVENT_DIALOG,
                _dialog_notice(kind, message, accept, guarded),
                dialog=kind,
                accepted=accept,
            )
        try:
            if accept:
                await asyncio.wait_for(dialog.accept(), PAGE_CALL_TIMEOUT_S)
            else:
                await asyncio.wait_for(dialog.dismiss(), PAGE_CALL_TIMEOUT_S)
        except Exception as exc:
            logger.debug(f"[MiniBrowser] Dialog answer: {type(exc).__name__}")

    async def _handle_download(self, page: Any, download: Any) -> None:
        """Save a download into the owner's workspace ``downloads`` folder.

        The file is marked as coming from the Internet (Windows
        Mark-of-the-Web, unless the source is this machine), so Windows and
        Office treat it with their usual care, and an executable type is
        flagged (``dangerous``) for the agent and the UI.
        """
        tab = self._page_tabs.get(page)
        owner = tab.owner if tab is not None else None
        page_url = tab.url if tab is not None else ""
        self._downloads_active += 1
        path: Optional[Path] = None
        try:
            name = _safe_filename(getattr(download, "suggested_filename", "") or "")
            dangerous = _is_dangerous_file(name)
            path = await asyncio.to_thread(
                _reserve_download_path, config.downloads_dir(owner), name
            )
            await asyncio.wait_for(download.save_as(str(path)), DOWNLOAD_TIMEOUT_S)
            source = str(getattr(download, "url", "") or "")
            if sys.platform == "win32" and not _is_local_source(source, page_url):
                secrets = self._secrets()
                await asyncio.to_thread(
                    _write_mark_of_the_web,
                    path,
                    scrub(page_url, secrets),
                    scrub(source, secrets),
                )
            size = await asyncio.to_thread(os.path.getsize, path)
            if tab is not None:
                message = f"Downloaded {path.name} ({_human_size(size)}) to {path}"
                if dangerous:
                    message += (
                        ". It is an executable file — do not run or open it (and do "
                        "not ask the user to): a web page sent it."
                    )
                self.add_event(
                    tab, EVENT_DOWNLOAD, message, path=str(path), dangerous=dangerous
                )
            logger.info(f"[MiniBrowser] Download saved: {path.name}")
        except Exception as exc:
            if path is not None:
                await asyncio.to_thread(_remove_quietly, path)
            if tab is not None:
                self.add_event(
                    tab,
                    EVENT_ERROR,
                    f"A download failed: {_clip(first_line(exc), 200)}",
                )
            logger.warning(f"[MiniBrowser] Download failed: {type(exc).__name__}")
        finally:
            self._downloads_active -= 1

    # ═════════════════════════════════════════════════════════════════════════
    # Network rules (ads + CraftBot's own UI)
    # ═════════════════════════════════════════════════════════════════════════

    async def refresh_network_rules(self) -> None:
        """Re-apply blocking after the ad-block setting or the UI origins changed."""
        self._compute_patterns()
        if self._context is None:
            return
        await self._apply_ui_guard()
        await asyncio.gather(
            *(
                self._cdp_send(
                    tab.cdp, "Network.setBlockedURLs", {"urls": self._blocked_patterns}
                )
                for tab in list(self.tabs.values())
                if tab.cdp is not None
            )
        )

    def _compute_patterns(self) -> None:
        origins = self.ui_origins()
        self._blocked_patterns = adblock.blocked_url_patterns(
            self.settings.adblock, origins
        )
        self._fetch_patterns = adblock.ui_fetch_patterns(origins)

    async def _apply_ui_guard(self) -> None:
        """Block CraftBot's UI origins browser-wide, navigations and popups included.

        ``Network.setBlockedURLs`` (per page) misses main-frame navigations and
        a popup's first load, so requests to the UI origins are also failed
        through browser-level ``Fetch`` interception. Only matching requests
        are intercepted, so the HTTP cache stays on.
        """
        context = self._context
        if context is None:
            return
        if self._browser_cdp is None:
            browser = getattr(context, "browser", None)
            if browser is not None:
                try:
                    session = await asyncio.wait_for(
                        browser.new_browser_cdp_session(), CDP_TIMEOUT_S
                    )
                    session.on(
                        "Fetch.requestPaused",
                        _safely(functools.partial(self._on_fetch_paused, session)),
                    )
                    self._browser_cdp = session
                except Exception as exc:
                    logger.warning(
                        f"[MiniBrowser] Browser-wide UI guard unavailable: {type(exc).__name__}"
                    )
        if self._browser_cdp is not None:
            if self._fetch_patterns:
                params = {
                    "patterns": [
                        {"urlPattern": pattern, "requestStage": "Request"}
                        for pattern in self._fetch_patterns
                    ]
                }
                done = await self._cdp_send(self._browser_cdp, "Fetch.enable", params)
            else:
                done = await self._cdp_send(self._browser_cdp, "Fetch.disable")
            if done is not None:
                return
        await self._install_guard_script()

    def _on_fetch_paused(self, session: Any, params: Any) -> None:
        self._spawn_safe(self._answer_paused(session, params))

    async def _answer_paused(self, session: Any, params: Any) -> None:
        if not isinstance(params, dict) or not params.get("requestId"):
            return
        url = str((params.get("request") or {}).get("url") or "")
        if urls.is_ui_origin(url, self.ui_origins()):
            await self._cdp_send(
                session,
                "Fetch.failRequest",
                {"requestId": params["requestId"], "errorReason": "BlockedByClient"},
            )
        else:  # a wildcard caught something else, or patterns changed: let it through
            await self._cdp_send(
                session, "Fetch.continueRequest", {"requestId": params["requestId"]}
            )

    async def _install_guard_script(self) -> None:
        origins = self.ui_origins()
        context = self._context
        if context is None or not origins or origins <= self._guard_script_origins:
            return
        hosts = set()
        loopback_ports: Set[int] = set()
        any_port = False
        for origin in origins:
            host, port = urls.split_origin(origin)
            if not host:
                continue
            if port is None or port in (80, 443):
                hosts.add(host)
            if port is not None:
                hosts.add(f"{host}:{port}")
            if urls.is_loopback_host(host):
                if port is None:
                    any_port = True
                else:
                    loopback_ports.add(port)
        script = _UI_GUARD_JS % (
            json.dumps(sorted(hosts)),
            json.dumps(sorted(loopback_ports)),
            "true" if any_port else "false",
        )
        try:
            await asyncio.wait_for(context.add_init_script(script), CDP_TIMEOUT_S)
            self._guard_script_origins = self._guard_script_origins | origins
        except Exception as exc:
            logger.warning(
                f"[MiniBrowser] UI guard script not installed: {type(exc).__name__}"
            )

    @staticmethod
    async def _cdp_send(
        session: Any,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = CDP_TIMEOUT_S,
    ) -> Optional[Dict[str, Any]]:
        """``session.send`` with a timeout; None on any failure, the result otherwise."""
        try:
            result = await asyncio.wait_for(session.send(method, params or {}), timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug(f"[MiniBrowser] CDP {method} failed: {type(exc).__name__}")
            return None
        return result if isinstance(result, dict) else {}

    # ═════════════════════════════════════════════════════════════════════════
    # Housekeeping
    # ═════════════════════════════════════════════════════════════════════════

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    async def _watchdog(self) -> None:
        """Every couple of seconds: notice a dead driver, keep the live view in
        sync, refresh titles while someone watches, and close an idle browser."""
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL_S)
            if self._context is None or self.status != "ready":
                continue
            try:
                if not await self._check_alive():
                    return  # the browser is gone: a close is under way
                await self._stream.sync()
                now = time.monotonic()
                if bridge.has_viewers():
                    self._last_activity = now
                    if now - self._last_title_refresh >= TITLE_REFRESH_S:
                        self._last_title_refresh = now
                        for tab in list(self.tabs.values()):
                            self._schedule_nav_refresh(tab)
                elif self._idle_expired(now):
                    minutes = self.settings.idle_shutdown_minutes
                    logger.info(
                        f"[MiniBrowser] Closing Chromium after {minutes} idle minute(s)"
                    )
                    self._request_close()
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug(f"[MiniBrowser] Watchdog: {type(exc).__name__}")

    def _idle_expired(self, now: float) -> bool:
        minutes = self.settings.idle_shutdown_minutes
        return (
            minutes > 0
            and not self._agent_busy()
            and self._downloads_active == 0
            and now - self._last_activity >= minutes * 60
        )


# ═════════════════════════════════════════════════════════════════════════════
# Module helpers
# ═════════════════════════════════════════════════════════════════════════════


class _ProfileLock:
    """Exclusive, cross-process lock next to the profile: one browser per profile.

    Chromium's own singleton lock is not reliable here (the headless shell
    happily starts a second instance on a profile in use). Blocking I/O: call
    ``acquire`` / ``release`` from a worker thread.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: Any = None

    def acquire(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()


async def _acquire_profile_lock(lock: _ProfileLock) -> bool:
    """``lock.acquire()`` in a worker thread, safe against cancellation.

    If the caller is cancelled while the thread is still acquiring, a lock it
    then obtains is released again instead of being held forever.
    """
    loop = asyncio.get_running_loop()
    attempt = loop.run_in_executor(None, lock.acquire)
    try:
        return await asyncio.shield(attempt)
    except asyncio.CancelledError:

        def release_if_acquired(done: "asyncio.Future[bool]") -> None:
            if not done.cancelled() and done.exception() is None and done.result():
                loop.run_in_executor(None, lock.release)

        attempt.add_done_callback(release_if_acquired)
        raise


async def _wait_shared(task: "asyncio.Future[Any]", cancelled_code: str) -> Any:
    """Await a task other callers share, without inheriting its cancellation.

    Only the caller's own cancellation raises CancelledError; a shared task
    cancelled by someone else (a close, the loop shutting down) raises
    MiniBrowserError(``cancelled_code``) instead.
    """
    await asyncio.wait({task})
    if task.cancelled():
        raise MiniBrowserError(cancelled_code)
    return task.result()


async def _abandon(task: "asyncio.Future[Any]") -> None:
    """Cancel an operation task and give it a moment to unwind (bounded)."""
    task.cancel()
    try:
        await asyncio.wait({task}, timeout=ABANDON_WAIT_S)
    finally:
        if task.done():
            _retrieve(task)
        else:
            task.add_done_callback(_retrieve)


def _retrieve(task: "asyncio.Future[Any]") -> None:
    """Mark a finished task's outcome as seen (no 'never retrieved' warning)."""
    if not task.cancelled():
        task.exception()


async def _stop_driver_quietly(pw: Any) -> None:
    try:
        await asyncio.wait_for(pw.stop(), CLOSE_TIMEOUT_S)
    except Exception as exc:
        logger.debug(f"[MiniBrowser] Abandoned driver stop: {type(exc).__name__}")


async def _detach_quietly(cdp: Any) -> None:
    try:
        await asyncio.wait_for(cdp.detach(), CDP_TIMEOUT_S)
    except Exception:
        pass


async def _target_id(core: BrowserCore, cdp: Any) -> Optional[str]:
    """The CDP target id of the page behind a page session."""
    info = await core._cdp_send(cdp, "Target.getTargetInfo")
    target = ((info or {}).get("targetInfo") or {}).get("targetId")
    return target if isinstance(target, str) and target else None


def _page_closed(page: Any) -> bool:
    try:
        return bool(page.is_closed())
    except Exception:
        return True


def _is_blank(tab: Tab) -> bool:
    """A tab showing nothing: about:blank with no history behind it."""
    return tab.url == "about:blank" and not tab.can_go_back


def _for_ui(error: MiniBrowserError, tab: Tab) -> MiniBrowserError:
    """The UI's wording for an error: the agent-facing MINI_BROWSER_TAB_CLOSED
    ("your next action uses ...") becomes MINI_BROWSER_TAB_NOT_FOUND."""
    if error.code == "MINI_BROWSER_TAB_CLOSED":
        return MiniBrowserError("MINI_BROWSER_TAB_NOT_FOUND", tab=tab.id)
    return error


def _looks_disconnected(text: str) -> bool:
    return any(marker in (text or "") for marker in _DISCONNECTED_MARKERS)


def _safely(fn: Any) -> Any:
    """Wrap an event handler so it can never raise into Playwright's dispatcher."""

    def handler(*args: Any) -> None:
        try:
            fn(*args)
        except Exception as exc:
            logger.debug(f"[MiniBrowser] Event handler failed: {type(exc).__name__}")

    return handler


async def _within(awaitable: Awaitable[Any], seconds: float) -> Any:
    return await asyncio.wait_for(awaitable, seconds)


async def _page_title(page: Any) -> Optional[str]:
    try:
        title = await asyncio.wait_for(page.title(), TITLE_TIMEOUT_S)
    except Exception:
        return None
    return title if isinstance(title, str) else None


async def _ready_state(page: Any) -> Optional[str]:
    try:
        state = await asyncio.wait_for(
            page.evaluate("document.readyState"), TITLE_TIMEOUT_S
        )
    except Exception:
        return None
    return state if isinstance(state, str) else None


def _clip(text: Any, limit: int) -> str:
    value = text if isinstance(text, str) else ("" if text is None else str(text))
    return value if len(value) <= limit else value[: max(0, limit - 1)] + "…"


def _host_of(url: str) -> str:
    """The host name of an http(s) address ('' for anything else)."""
    try:
        parts = urlsplit(url or "")
        if parts.scheme.lower() not in ("http", "https"):
            return ""
        return parts.hostname or ""
    except ValueError:
        return ""


def _workspace_relative(path: str) -> str:
    """``path`` relative to the agent workspace (POSIX separators) when it
    lies inside it; otherwise ``path`` unchanged. Pure path arithmetic, no
    filesystem access."""
    try:
        from app.config import AGENT_WORKSPACE_ROOT

        rel = os.path.relpath(
            os.path.abspath(path), os.path.abspath(AGENT_WORKSPACE_ROOT)
        )
    except (ImportError, ValueError):  # ValueError: different drive on Windows
        return path
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        return path
    return rel.replace(os.sep, "/")


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, int(round(number))))


def _unit(value: Any) -> Optional[float]:
    """A finite number clamped to 0..1, else None (NaN would kill the driver)."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return _clamp_unit(number) if math.isfinite(number) else None


def _clamp_unit(number: float) -> float:
    return 0.0 if number < 0 else 1.0 if number > 1 else number


def _finite(value: Any, limit: float) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(-limit, min(limit, number))


def _key_combo(event: Mapping[str, Any]) -> Optional[str]:
    """``{key, modifiers}`` -> Playwright's ``"Control+Shift+X"``, None to ignore."""
    key = event.get("key")
    if not isinstance(key, str) or not key or len(key) > 32 or not key.isprintable():
        return None
    if key in _IGNORED_KEYS:
        return None
    modifiers = event.get("modifiers")
    flags = modifiers if isinstance(modifiers, Mapping) else {}
    names = [
        name for flag, name in _MODIFIERS if flags.get(flag) is True and name != key
    ]
    return "+".join([*names, key])


def _is_missing_executable(exc: BaseException) -> bool:
    text = str(exc)
    return "Executable doesn't exist" in text or "is not found at" in text


def _is_profile_in_use(exc: BaseException) -> bool:
    text = str(exc)
    return any(
        marker in text
        for marker in (
            "Target page, context or browser has been closed",
            "ProcessSingleton",
            "profile appears to be in use",
            "user data directory is already in use",
            "SingletonLock",
        )
    )


def _is_benign_navigation(line: str) -> bool:
    """Navigation "errors" that are not failures (superseded, became a download)."""
    return any(
        marker in line
        for marker in (
            "interrupted by another navigation",
            "Download is starting",
            "net::ERR_ABORTED",
        )
    )


def _dialog_notice(kind: str, message: str, accepted: bool, guarded: bool) -> str:
    """What a page's dialog said and exactly how the Mini Browser answered it."""
    quoted = f' ("{message}")' if message else ""
    if kind == "alert":
        return f"The page showed an alert{quoted}; the Mini Browser closed it automatically."
    if kind == "confirm":
        return (
            f"The page asked for confirmation{quoted} and the Mini Browser answered OK "
            "automatically, so whatever it guarded went ahead (agents cannot decline "
            "such a dialog: ask the user before clicking anything destructive)."
        )
    if kind == "prompt":
        return (
            f"The page asked for input{quoted}; the Mini Browser cancelled the prompt "
            "automatically, so nothing was entered."
        )
    if kind == "beforeunload":
        if guarded:
            return (
                "The page warned that leaving it may lose unsaved changes. This tab "
                "was the user's own tab until moments ago, so the Mini Browser stayed "
                "on the page: ask the user before leaving it."
            )
        return (
            "The page warned that leaving it may lose unsaved changes; the Mini "
            "Browser confirmed leaving automatically, so anything unsaved there "
            "is gone."
        )
    verb = "accepted" if accepted else "dismissed"
    return f"The page showed a {kind} dialog{quoted}, which was {verb} automatically."


def _bundled_chromium_version() -> Optional[str]:
    """Version of Playwright's bundled Chromium (its browsers.json). Blocking I/O."""
    try:
        import playwright

        path = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for browser in data.get("browsers", []):
            if browser.get("name") == "chromium":
                return str(browser.get("browserVersion") or "") or None
    except Exception:
        return None
    return None


def _reduced_user_agent(version: Optional[str]) -> Optional[str]:
    """Chrome's reduced desktop UA for ``version`` (major.0.0.0, no "Headless")."""
    major = (version or "").split(".")[0]
    if not major.isdigit():
        return None
    if sys.platform == "win32":
        platform = "Windows NT 10.0; Win64; x64"
    elif sys.platform == "darwin":
        platform = "Macintosh; Intel Mac OS X 10_15_7"
    else:
        platform = "X11; Linux x86_64"
    return (
        f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.0.0 Safari/537.36"
    )


def _safe_filename(name: str) -> str:
    """A download name that is safe on every OS (no paths, no reserved names,
    no bidi / format controls that disguise its real extension)."""
    base = re.split(r"[\\/]", _BIDI_CONTROLS_RE.sub("", str(name or "")))[-1]
    base = re.sub(r'[\x00-\x1f\x7f<>:"|?*]', "_", base).strip(" .")
    if not base:
        return "download"
    stem, ext = os.path.splitext(base)
    if len(ext) > 16 or not re.fullmatch(r"\.[A-Za-z0-9_-]+", ext or ".x"):
        stem, ext = base, ""
    if stem.split(".")[0].strip().lower() in _RESERVED_FILE_NAMES:
        stem = f"_{stem}"
    stem = stem[: 150 - len(ext)].rstrip(" .") or "download"
    return stem + ext


def _is_dangerous_file(name: str) -> bool:
    """True for a file type that runs code when opened."""
    _stem, ext = os.path.splitext(str(name or ""))
    return ext[1:].lower() in _DANGEROUS_EXTENSIONS


def _source_host(url: str) -> Optional[str]:
    value = (url or "").strip()
    if value.lower().startswith("blob:"):
        value = value[5:]
    parsed = urls.host_and_port(value)
    return parsed[0] if parsed else None


def _is_local_source(source: str, page_url: str) -> bool:
    """The download came from this machine (no Mark-of-the-Web for it)."""
    host = _source_host(source)
    if host is None:  # data: / about: downloads come from the page itself
        host = _source_host(page_url)
    return host is not None and urls.is_loopback_host(host)


def _write_mark_of_the_web(path: Path, referrer: str, host_url: str) -> None:
    """Windows Mark-of-the-Web: an Internet-zone ``Zone.Identifier`` stream.

    What Chromium writes onto its own downloads (Playwright's ``save_as``
    copies the file without it). Blocking I/O. Volumes without alternate
    data streams (FAT, exFAT, some network shares) are skipped.
    """

    def clean(url: str) -> str:
        value = _LINE_BREAKS_RE.sub("", url or "")
        if value.lower().startswith("data:"):
            return "about:internet"
        return value[:2048]

    lines = ["[ZoneTransfer]", "ZoneId=3"]
    for key, value in (("ReferrerUrl", clean(referrer)), ("HostUrl", clean(host_url))):
        if value:
            lines.append(f"{key}={value}")
    try:
        with open(f"{path}:Zone.Identifier", "w", encoding="utf-8", newline="") as fh:
            fh.write("\r\n".join(lines) + "\r\n")
    except OSError as exc:
        logger.debug(f"[MiniBrowser] Mark-of-the-Web not written: {type(exc).__name__}")


def _profile_processes(profile: Path) -> List[Any]:
    """Processes (psutil) running Chromium on ``profile``. Blocking I/O."""
    try:
        import psutil
    except ImportError:
        return []
    wanted = os.path.normcase(os.path.abspath(str(profile)))
    found = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
        except Exception:
            continue
        for arg in cmdline:
            if isinstance(arg, str) and arg.startswith("--user-data-dir="):
                value = arg.split("=", 1)[1].strip().strip('"')
                try:
                    same = os.path.normcase(os.path.abspath(value)) == wanted
                except (TypeError, ValueError):
                    same = False
                if same:
                    found.append(proc)
                break
    return found


def _kill_processes(procs: List[Any], wait: float) -> None:
    """End leftover Chromium processes on our profile. Blocking I/O."""
    try:
        import psutil
    except ImportError:
        return
    for proc in procs:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        psutil.wait_procs(procs, timeout=wait)
    except Exception:
        pass


def _reserve_download_path(directory: Path, name: str) -> Path:
    """Create an empty, not-yet-used file for a download. Blocking I/O."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem, ext = os.path.splitext(name)
    for attempt in range(1000):
        candidate = directory / (name if attempt == 0 else f"{stem} ({attempt}){ext}")
        try:
            handle = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        os.close(handle)
        return candidate
    raise OSError("No free file name for the download")


def _remove_quietly(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} bytes"
