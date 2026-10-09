"""Agent operations: what an agent actually does in its Mini Browser tab.

``OPS`` maps an operation name to ``async def op(core, tab, **params) ->
dict``. ``BrowserCore.agent_op`` calls them on the host loop while holding
``tab.lock``; params were already cleaned by ``actions_api.validate``. The
"tabs" operation lives in the core, not here.

Every operation that can change the page returns ``{"status": "success",
"message": ..., "page": <compact observation>}`` so the agent rarely needs a
separate read. ``read`` returns the full observation itself. Expected
failures raise :class:`MiniBrowserError`; the core turns them into action
errors (and attaches a fresh observation).

Element ids: the latest observation tagged elements ``data-mb-id="<gen>-<n>"``
(also inside the frames it listed) and the agent passes ``n``. A locator
built from the CURRENT generation either finds exactly that element or
nothing, so a stale id fails loudly instead of clicking something else.

Cancellation: element actions wait for the element first (a trial action
that never acts) and only then act, so a Stop that cancels the wait can
never cause a late click.

Take control: once the user takes control of the tab (``tab.user_control``)
an operation stops sending input at its next step (see ``human.py``) and
fails with MINI_BROWSER_USER_IN_CONTROL. When the tab or the whole browser
is closed under an operation, it fails with MINI_BROWSER_CLOSED instead of
reporting success.
"""

from __future__ import annotations

import asyncio
import functools
import ipaddress
import math
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)
from urllib.parse import urlsplit

from app.logger import logger
from app.mini_browser import human
from app.mini_browser import types as mb_types
from app.mini_browser.errors import (
    ERROR_SPECS,
    MiniBrowserError,
    action_error,
    first_line,
    scrub,
)
from app.mini_browser.observe import (
    JS_COMMON,
    SECRET_RULES_JS,
    UNTRUSTED_NOTE,
    is_context_destroyed,
    observe,
)
from app.mini_browser.types import EVENT_NOTICE

# How long an element may take to become actionable, then the real action.
ACTION_WAIT_MS = 5000
ACT_TIMEOUT_MS = 1500
# How long an action follows a navigation it started.
NAV_WAIT_S = 15.0
# Page "settled" = no DOM mutation for SETTLE_QUIET_MS, or SETTLE_MAX_MS.
SETTLE_QUIET_MS = 400
SETTLE_MAX_MS = 2500
# How long an action waits for the data requests (XHR / fetch) it started.
DATA_WAIT_S = 4.0
# How long an action waits for a new tab it opened to be registered.
POPUP_ADOPT_S = 2.0
EVALUATE_TIMEOUT_S = 10.0
LOCATE_TIMEOUT_S = 5.0
FRAME_LOCATE_TIMEOUT_S = 2.0
SCREENSHOT_TIMEOUT_MS = 15000
FOR_USER_POLL_S = 0.25
TEXT_POLL_S = 0.3
SLEEP_SLICE_S = 0.25
SCROLL_IDLE_MAX_S = 1.5
MAX_KEY_COMBOS = 16
MAX_TAB_EVENTS = 20
# mini_browser_wait stops this long before the core's own limit for the wait
# operation, so the agent gets the specific message rather than a generic one.
WAIT_LIMIT_MARGIN_S = 10.0

HISTORY_TARGETS = ("back", "forward", "reload")
DOWNLOAD_NOTE = " The address started a download (see events)."
ABORTED_NOTE = (
    " The browser stopped loading this address (it may be a download "
    "or a blocked page; see events)."
)
DATA_NOTE = (
    " The page may still be updating (it was still loading data); use "
    "mini_browser_wait (e.g. with text=...) before concluding."
)
POPUP_NOTE = " It opened a new tab."

# Input types whose value is set as a whole (the browser shows a segmented
# editor, a picker or a slider for them, which per-key typing cannot drive).
VALUE_INPUT_TYPES = frozenset(
    {"date", "time", "datetime-local", "month", "week", "color", "range"}
)

# Tab.closed_reason of a tab closed on its own (the browser still runs).
CLOSED_TAB = getattr(mb_types, "CLOSED_TAB", "tab")

Op = Callable[..., Awaitable[Dict[str, Any]]]

# ── page scripts ────────────────────────────────────────────────────────────

SETTLE_JS = r"""
({quietMs, maxMs}) => new Promise((resolve) => {
  const start = performance.now();
  let last = start;
  let count = 0;
  let observer = null;
  try {
    observer = new MutationObserver((records) => { count += records.length; last = performance.now(); });
    observer.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
  } catch (e) {
    resolve({quiet: true, mutations: 0});
    return;
  }
  const tick = () => {
    const now = performance.now();
    if (now - last >= quietMs || now - start >= maxMs) {
      observer.disconnect();
      resolve({quiet: now - last >= quietMs, mutations: count});
      return;
    }
    setTimeout(tick, 50);
  };
  setTimeout(tick, 50);
})
"""

# Called on an element with a point in MAIN-viewport CSS px: true if a click
# there lands on it, null when that cannot be checked from here (a
# cross-origin frame; Playwright's own actionability check covers it).
HITS_JS = (
    r"""
(el, [x, y]) => {
"""
    + JS_COMMON
    + r"""
  let fx = x, fy = y;
  try {
    for (let w = window; w !== w.top; w = w.parent) {
      const fe = w.frameElement;
      if (!fe) return null;
      const r = fe.getBoundingClientRect();
      const cs = w.parent.getComputedStyle(fe);
      fx -= r.left + fe.clientLeft + (parseFloat(cs.paddingLeft) || 0);
      fy -= r.top + fe.clientTop + (parseFloat(cs.paddingTop) || 0);
    }
  } catch (e) { return null; }
  const hit = deepElementFromPoint(fx, fy);
  if (!hit) return false;
  const ctl = (el.tagName === 'LABEL' && el.control) ? el.control : el;
  if (flatContains(el, hit) || flatContains(ctl, hit)) return true;
  if (hit.tagName === 'LABEL' && hit.control === ctl) return true;
  // Text slotted straight into a component hit-tests as its host.
  return isHostOf(hit, el);
}
"""
)

# Called on an element that did not become actionable: a reason the agent
# can act on.
DIAGNOSE_JS = (
    r"""
(el) => {
"""
    + JS_COMMON
    + r"""
  if (!el.isConnected) return 'it is no longer on the page';
  const ctl = (el.tagName === 'LABEL' && el.control) ? el.control : el;
  if (ctl.disabled || ctl.getAttribute('aria-disabled') === 'true') return 'it is disabled';
  const r = el.getBoundingClientRect();
  const opts = {checkOpacity: true, checkVisibilityCSS: true, opacityProperty: true, visibilityProperty: true};
  if (r.width < 1 || r.height < 1 || (el.checkVisibility && !el.checkVisibility(opts))) {
    return 'it is not visible';
  }
  const vw = window.innerWidth, vh = window.innerHeight;
  if (r.bottom <= 0 || r.top >= vh || r.right <= 0 || r.left >= vw) {
    return 'it could not be scrolled into view';
  }
  const x = (Math.max(r.left, 0) + Math.min(r.right, vw)) / 2;
  const y = (Math.max(r.top, 0) + Math.min(r.bottom, vh)) / 2;
  const hit = deepElementFromPoint(x, y);
  if (hit && !flatContains(el, hit) && !flatContains(ctl, hit) && !isHostOf(hit, el)
      && !(hit.tagName === 'LABEL' && hit.control === ctl)) {
    let name = hit.tagName.toLowerCase();
    if (hit.id) name += '#' + hit.id;
    const text = String(hit.innerText || hit.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    const said = text ? ' "' + (text.length > 60 ? text.slice(0, 60) + '…' : text) + '"' : '';
    return 'it is covered by another element (<' + name + '>' + said + '); close or dismiss that first';
  }
  return 'it did not become usable in time (it may be moving or still loading)';
}
"""
)

# Called on an element: what kind of field it is (for type / select / upload).
FIELD_INFO_JS = r"""
(el) => {
  const ctl = (el.tagName === 'LABEL' && el.control) ? el.control : el;
  return {
    tag: ctl.tagName,
    type: ctl.tagName === 'INPUT' ? String(ctl.type || 'text').toLowerCase() : '',
    editable: !!ctl.isContentEditable,
    disabled: !!ctl.disabled || ctl.getAttribute('aria-disabled') === 'true',
    readonly: !!ctl.readOnly,
    multiple: !!ctl.multiple,
  };
}
"""

# Called on an element: whether it (or something inside it) has focus.
HAS_FOCUS_JS = (
    r"""
(el) => {
"""
    + JS_COMMON
    + r"""
  const ctl = (el.tagName === 'LABEL' && el.control) ? el.control : el;
  let a = document.activeElement;
  while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
  for (let n = a; n; n = parentOf(n)) if (n === ctl) return true;
  return false;
}
"""
)

# Called on an element: put the caret at the end without reading the value
# (setSelectionRange clamps an out-of-range index to the value's length).
CARET_END_JS = r"""
(el) => {
  const ctl = (el.tagName === 'LABEL' && el.control) ? el.control : el;
  try {
    if (typeof ctl.setSelectionRange === 'function') {
      ctl.setSelectionRange(1e9, 1e9);
      return true;
    }
  } catch (e) { /* email / number inputs have no selection API */ }
  if (ctl.isContentEditable) {
    const range = document.createRange();
    range.selectNodeContents(ctl);
    range.collapse(false);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    return true;
  }
  return false;
}
"""

# Called on an <input> whose value is set as a whole (date, time, colour,
# slider, ...): sets it the way a user's edit would (the native setter, so
# frameworks such as React notice it), fires input + change, and reports
# what the field holds now. A secret-looking field's value is never returned.
SET_VALUE_JS = (
    r"""
(el, args) => {
"""
    + SECRET_RULES_JS
    + r"""
  const ctl = (el.tagName === 'LABEL' && el.control) ? el.control : el;
  if (ctl.tagName !== 'INPUT') return {ok: false, empty: true, value: null};
  const secret = secretField(ctl) || maskedField(ctl);
  try { ctl.focus({preventScroll: true}); } catch (e) { /* not focusable */ }
  const wanted = String(args.value);
  try {
    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    if (desc && desc.set) desc.set.call(ctl, wanted); else ctl.value = wanted;
  } catch (e) {
    return {ok: false, empty: !ctl.value, value: null};
  }
  ctl.dispatchEvent(new Event('input', {bubbles: true, composed: true}));
  ctl.dispatchEvent(new Event('change', {bubbles: true}));
  const now = String(ctl.value);
  return {ok: now === wanted, empty: now === '', value: secret ? null : now};
}
"""
)

# Called on a text field after typing: 'empty' when nothing stuck, 'ok', or
# 'skip' (not a plain text field, or one whose value must never be read).
TYPED_CHECK_JS = (
    r"""
(el) => {
"""
    + SECRET_RULES_JS
    + r"""
  const ctl = (el.tagName === 'LABEL' && el.control) ? el.control : el;
  if (ctl.tagName !== 'INPUT' && ctl.tagName !== 'TEXTAREA') return 'skip';
  if (secretField(ctl) || maskedField(ctl)) return 'skip';
  return ctl.value ? 'ok' : 'empty';
}
"""
)

# Called on an element: find the <option> matching a value or a visible label.
SELECT_MATCH_JS = r"""
(el, wanted) => {
  const ctl = (el.tagName === 'LABEL' && el.control) ? el.control : el;
  if (ctl.tagName !== 'SELECT') return {native: false};
  const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim().toLowerCase();
  const opts = Array.from(ctl.options);
  const want = norm(wanted);
  let index = opts.findIndex((o) => o.value === wanted);
  if (index < 0) index = opts.findIndex((o) => norm(o.label || o.text) === want);
  if (index < 0) index = opts.findIndex((o) => norm(o.value) === want);
  return {
    native: true,
    index,
    disabled: !!ctl.disabled || (index >= 0 && !!opts[index].disabled),
    label: index >= 0 ? String(opts[index].label || opts[index].text || '').replace(/\s+/g, ' ').trim() : '',
    options: opts.slice(0, 25).map((o) => String(o.label || o.text || o.value).replace(/\s+/g, ' ').trim().slice(0, 40)),
    count: opts.length,
  };
}
"""

SCROLL_STATE_JS = (
    r"""
(p) => {
"""
    + JS_COMMON
    + r"""
  const sc = scrollerAt(p.x, p.y);
  return {doc: docBox(), inner: sc ? scrollBox(sc) : null};
}
"""
)

# Where to put the wheel: the viewport centre, unless a small scroll area
# (a code block, a map) sits there while the page itself scrolls.
WHEEL_POINT_JS = (
    r"""
(p) => {
"""
    + JS_COMMON
    + r"""
  const vw = window.innerWidth, vh = window.innerHeight;
  const doc = docBox();
  const small = (x, y) => {
    const sc = scrollerAt(x, y);
    return !!sc && sc.clientHeight < vh * 0.5 && doc.height > doc.client + 2;
  };
  if (!small(p.x, p.y)) return [p.x, p.y];
  for (const fx of [0.06, 0.94, 0.25, 0.75]) {
    if (!small(vw * fx, p.y)) return [vw * fx, p.y];
  }
  return [p.x, p.y];
}
"""
)

SCROLL_TO_JS = (
    r"""
(p) => {
"""
    + JS_COMMON
    + r"""
  const doc = docBox();
  const sc = scrollerAt(p.x, p.y);
  const page = document.scrollingElement || document.documentElement;
  const target = (doc.height > doc.client + 2 || !sc) ? page : sc;
  const top = p.to === 'top' ? 0 : target.scrollHeight;
  if (target === page) window.scrollTo({top, left: window.scrollX, behavior: 'instant'});
  else target.scrollTo({top, behavior: 'instant'});
  return true;
}
"""
)

TEXT_PRESENT_JS = r"""
(needle) => {
  const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').toLowerCase();
  const want = norm(needle).trim();
  if (!want) return true;
  const top = document.body || document.documentElement;
  if (top && norm(top.innerText).includes(want)) return true;
  const roots = [];
  const walk = (root) => {
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      if (n.shadowRoot) { roots.push(n.shadowRoot); walk(n.shadowRoot); }
    }
  };
  walk(document);
  for (const root of roots) {
    for (const child of root.children) {
      if (norm(child.innerText).includes(want)) return true;
    }
  }
  return false;
}
"""

# ── small helpers ───────────────────────────────────────────────────────────


def _is_pw_timeout(exc: BaseException) -> bool:
    """Playwright's TimeoutError (without importing Playwright here)."""
    return type(exc).__name__ == "TimeoutError" and type(exc).__module__.startswith(
        "playwright"
    )


def _is_gone(exc: BaseException) -> bool:
    """The element (or its document) went away under an action."""
    text = str(exc).lower()
    return is_context_destroyed(exc) or any(
        marker in text
        for marker in (
            "not attached to the dom",
            "element is detached",
            "node is detached",
            "element is not attached",
            "frame was detached",
        )
    )


_CLOSED_MARKERS = (
    "has been closed",
    "target closed",
    "connection closed",
    "browser closed",
    "page closed",
    "context closed",
)


def is_closed_error(exc: BaseException, page: Any = None) -> bool:
    """True when ``exc`` means the tab or the whole browser was closed."""
    text = str(exc).lower()
    if any(marker in text for marker in _CLOSED_MARKERS):
        return True
    if page is not None:
        try:
            return bool(page.is_closed())
        except Exception:
            return False
    return False


def closed_error(core: Any = None, tab: Any = None) -> MiniBrowserError:
    """The error for an operation interrupted by its tab / the browser closing:
    MINI_BROWSER_TAB_CLOSED when only the tab went away (the browser still
    runs), else MINI_BROWSER_CLOSED."""
    reason = getattr(tab, "closed_reason", None)
    if reason is None and tab is not None and getattr(core, "status", None) == "ready":
        reason = CLOSED_TAB
    if reason == CLOSED_TAB and "MINI_BROWSER_TAB_CLOSED" in ERROR_SPECS:
        return MiniBrowserError("MINI_BROWSER_TAB_CLOSED")
    code = (
        "MINI_BROWSER_CLOSED"
        if "MINI_BROWSER_CLOSED" in ERROR_SPECS
        else "MINI_BROWSER_NOT_RUNNING"
    )
    return MiniBrowserError(code)


def tab_gone(core: Any, tab: Any) -> bool:
    """The tab was closed (by the user, the browser closing or dying) while an
    operation was running in it."""
    if getattr(tab, "closed", False):
        return True
    tabs = getattr(core, "tabs", None)
    if isinstance(tabs, dict) and tabs.get(getattr(tab, "id", None)) is not tab:
        return True
    try:
        return bool(tab.page.is_closed())
    except Exception:
        return False


def _setting(core: Any, name: str, default: Any) -> Any:
    try:
        return getattr(core.settings, name)
    except Exception:
        return default


def humanlike_enabled(core: Any) -> bool:
    return bool(_setting(core, "humanlike", True))


def _short(text: str, limit: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _api_message(exc: BaseException) -> str:
    """First line of a Playwright error without its "Page.goto: " prefix."""
    line = first_line(exc)
    return re.sub(r"^[A-Za-z]+\.[A-Za-z_]+:\s*", "", line)


def _secrets(tab: Any) -> List[str]:
    return list(getattr(tab, "filled_secrets", None) or [])


def _page_url(tab: Any) -> str:
    try:
        return str(tab.page.url or "")
    except Exception:
        return str(getattr(tab, "url", "") or "")


def _agent_note(tab: Any, message: str) -> None:
    """Queue a notice for the tab's agent (attached to this op's result)."""
    try:
        events = tab.events
        events.append({"kind": EVENT_NOTICE, "message": message})
        del events[:-MAX_TAB_EVENTS]
    except Exception as exc:
        logger.debug(f"[MiniBrowser] could not queue a notice: {type(exc).__name__}")


async def _evaluate(page: Any, script: str, arg: Any = None) -> Any:
    """page.evaluate with a hard timeout (a busy page never answers)."""
    try:
        return await asyncio.wait_for(page.evaluate(script, arg), EVALUATE_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise MiniBrowserError("MINI_BROWSER_PAGE_UNRESPONSIVE") from None


async def _dom_ready(page: Any, timeout_s: float) -> bool:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_s * 1000)
        return True
    except Exception as exc:
        if not _is_pw_timeout(exc):
            logger.debug(
                f"[MiniBrowser] waiting for the page failed: {type(exc).__name__}"
            )
        return False


async def settle(
    page: Any, *, quiet_ms: int = SETTLE_QUIET_MS, max_ms: int = SETTLE_MAX_MS
) -> bool:
    """Wait until the DOM stops changing; True if a navigation interrupted."""
    try:
        await asyncio.wait_for(
            page.evaluate(SETTLE_JS, {"quietMs": quiet_ms, "maxMs": max_ms}),
            max_ms / 1000.0 + 2.0,
        )
    except asyncio.TimeoutError:
        return False
    except Exception as exc:
        if is_context_destroyed(exc):
            return True
        logger.debug(f"[MiniBrowser] settle failed: {type(exc).__name__}")
    return False


def _is_ad_host(url: str) -> bool:
    try:
        from app.mini_browser import adblock

        return adblock.is_ad_host(urlsplit(url).hostname or "")
    except Exception:
        return False


class NavWatch:
    """Notices what an action set off while (and right after) it runs.

    ``started``: a main-frame navigation request was sent. ``commits``:
    main-frame documents committed (also same-document navigations), not
    counting Chromium error pages, which re-commit while a navigation away
    from them is still pending. ``requests``: XHR / fetch requests sent (a
    form submitted by script); the ones still in flight make ``busy`` true
    (ad / analytics hosts are ignored). ``popups``: pages (new tabs) the page
    opened. Use as a context manager around the action.
    """

    def __init__(self, page: Any) -> None:
        self._page = page
        self.started = False
        self.commits = 0
        self.requests = 0
        self.urls: List[str] = []
        self.popups: List[Any] = []
        self._finished = asyncio.Event()
        self._finished.set()
        # id -> request (keyed by identity: any request object will do)
        self._loading: Dict[int, Any] = {}
        self._data_idle = asyncio.Event()
        self._data_idle.set()

    def _handlers(self) -> Tuple[Tuple[str, Callable[[Any], None]], ...]:
        return (
            ("request", self._on_request),
            ("requestfinished", self._on_request_finished),
            ("requestfailed", self._on_request_failed),
            ("framenavigated", self._on_frame_navigated),
            ("popup", self._on_popup),
        )

    def __enter__(self) -> "NavWatch":
        for event, handler in self._handlers():
            self._page.on(event, handler)
        return self

    def __exit__(self, *_exc: Any) -> None:
        for event, handler in self._handlers():
            try:
                self._page.remove_listener(event, handler)
            except Exception:
                pass

    def _is_main(self, frame: Any) -> bool:
        try:
            return frame == self._page.main_frame
        except Exception:
            return False

    def _is_main_navigation(self, request: Any) -> bool:
        try:
            return bool(request.is_navigation_request()) and self._is_main(
                request.frame
            )
        except Exception:
            return False

    def _on_request(self, request: Any) -> None:
        try:
            if request.resource_type in ("xhr", "fetch"):
                self.requests += 1
                if not _is_ad_host(str(request.url or "")):
                    self._loading[id(request)] = request
                    self._data_idle.clear()
        except Exception:
            pass
        if self._is_main_navigation(request):
            self.started = True
            self._finished.clear()

    def _data_done(self, request: Any) -> None:
        if self._loading.pop(id(request), None) is not None:
            if not self._loading:
                self._data_idle.set()

    def _on_request_finished(self, request: Any) -> None:
        self._data_done(request)

    def _on_request_failed(self, request: Any) -> None:
        self._data_done(request)
        if self._is_main_navigation(request):
            self._finished.set()

    def _on_frame_navigated(self, frame: Any) -> None:
        if not self._is_main(frame):
            return
        try:
            url = str(frame.url or "")
        except Exception:
            url = ""
        self.urls.append(url)
        if url.startswith("chrome-error:"):
            # A failed navigation ends with "requestfailed" instead.
            return
        self.commits += 1
        self._finished.set()

    def _on_popup(self, page: Any) -> None:
        self.popups.append(page)

    @property
    def pending(self) -> bool:
        """A navigation was requested and has neither committed nor failed."""
        return not self._finished.is_set()

    @property
    def navigated(self) -> bool:
        return self.started or self.commits > 0

    @property
    def busy(self) -> bool:
        """XHR / fetch requests the action started are still in flight."""
        return bool(self._loading)

    async def wait_finished(self, timeout_s: float) -> bool:
        try:
            await asyncio.wait_for(self._finished.wait(), timeout_s)
            return True
        except asyncio.TimeoutError:
            return False

    async def wait_data(self, timeout_s: float) -> bool:
        """Wait until no data request of the action is in flight."""
        if timeout_s <= 0:
            return not self._loading
        try:
            await asyncio.wait_for(self._data_idle.wait(), timeout_s)
            return True
        except asyncio.TimeoutError:
            return False


async def _await_adoption(core: Any, popups: Sequence[Any]) -> bool:
    """Give the core a moment to register new tabs the action opened, so the
    result can already describe the tab the agent continues in. True when
    every one of them was registered (or closed again) in time."""
    tabs = getattr(core, "tabs", None)
    if not isinstance(tabs, dict) or not popups:
        return False
    deadline = time.monotonic() + POPUP_ADOPT_S
    while True:
        pages = [getattr(t, "page", None) for t in list(tabs.values())]
        pending = []
        for popup in popups:
            try:
                closed = bool(popup.is_closed())
            except Exception:
                closed = True
            if not closed and not any(p is popup for p in pages):
                pending.append(popup)
        if not pending:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)


async def after_action(
    page: Any,
    watch: NavWatch,
    *,
    baseline: int = 0,
    nav_timeout_s: float = NAV_WAIT_S,
    core: Any = None,
) -> str:
    """Let the page react to an action; returns a note for the message.

    Waits for the DOM to settle; if the action started a navigation, waits
    for the new document (DOMContentLoaded) and lets it settle too. Then
    waits (at most DATA_WAIT_S) for the XHR / fetch requests the action set
    off, so results that arrive a moment later are in the observation; if
    they are still loading, the note says so. ``baseline`` = commits that
    happened before the action's own effects. With ``core``, new tabs the
    action opened are given a moment to be registered.
    """
    interrupted = await settle(page)
    if watch.pending:
        if not await watch.wait_finished(nav_timeout_s):
            return " The next page is still loading."
    if interrupted or watch.commits > baseline:
        if not await _dom_ready(page, nav_timeout_s):
            return " The page is still loading."
        await settle(page)
    note = ""
    deadline = time.monotonic() + DATA_WAIT_S
    while watch.busy:
        if not await watch.wait_data(deadline - time.monotonic()):
            note = DATA_NOTE
            break
        await settle(page, quiet_ms=300, max_ms=1500)
    if watch.popups:
        # Once the core has the new tab, it reports it itself (and shows it
        # as the result's page); otherwise say so here.
        if not await _await_adoption(core, watch.popups):
            note = POPUP_NOTE + note
    return note


async def page_observation(core: Any, tab: Any) -> Dict[str, Any]:
    """Compact observation for a result's "page" (never fails the action)."""
    try:
        return await observe(core, tab, compact=True)
    except MiniBrowserError as exc:
        reason = (
            "the page is not responding"
            if exc.code == "MINI_BROWSER_PAGE_UNRESPONSIVE"
            else exc.code
        )
    except Exception as exc:
        reason = first_line(exc, 200)
    secrets = _secrets(tab)
    return {
        "url": scrub(_page_url(tab), secrets),
        "title": scrub(str(getattr(tab, "title", "") or ""), secrets),
        "elements": [],
        "error": scrub(
            f"Could not read the page ({reason}). Try mini_browser_read.", secrets
        ),
        "tabs": [],
    }


def _success(message: str, page: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {"status": "success", "message": message}
    result.update(extra)
    result["page"] = page
    return result


async def _done(core: Any, tab: Any, message: str, **extra: Any) -> Dict[str, Any]:
    """Success result with a fresh observation; a tab that went away while the
    operation ran fails it with MINI_BROWSER_CLOSED instead."""
    if tab_gone(core, tab):
        raise closed_error(core, tab)
    page = await page_observation(core, tab)
    if tab_gone(core, tab):
        raise closed_error(core, tab)
    return _success(scrub(message, _secrets(tab)), page, **extra)


# ── elements ────────────────────────────────────────────────────────────────


async def _count(locator: Any, page: Any, *, frame: bool) -> Optional[Any]:
    """The locator if it matches (a visible copy if it matches several)."""
    timeout = FRAME_LOCATE_TIMEOUT_S if frame else LOCATE_TIMEOUT_S
    try:
        count = await asyncio.wait_for(locator.count(), timeout)
    except asyncio.TimeoutError:
        if frame:
            return None
        raise MiniBrowserError("MINI_BROWSER_PAGE_UNRESPONSIVE") from None
    except Exception as exc:
        if is_closed_error(exc, page):
            raise closed_error() from None
        if frame or _is_gone(exc):
            return None
        raise
    if count == 0:
        return None
    if count > 1:
        # The page cloned a tagged node (carousels do). Prefer a visible copy.
        logger.debug(f"[MiniBrowser] element matched {count} nodes")
        return locator.filter(visible=True).first
    return locator


async def locate(tab: Any, element_id: int) -> Any:
    """Locator for element ``element_id`` of the latest observation (in the
    page itself or in one of the frames it listed)."""
    selector = f'[data-mb-id="{int(tab.snapshot_gen)}-{int(element_id)}"]'
    page = tab.page
    found = await _count(page.locator(selector), page, frame=False)
    if found is not None:
        return found
    try:
        frames = [f for f in page.frames if f is not page.main_frame]
    except Exception:
        frames = []
    for frame in frames:
        try:
            if frame.is_detached():
                continue
        except Exception:
            continue
        found = await _count(frame.locator(selector), page, frame=True)
        if found is not None:
            return found
    raise MiniBrowserError("MINI_BROWSER_ELEMENT_NOT_FOUND", element_id=element_id)


async def _diagnose(locator: Any) -> str:
    try:
        reason = await locator.evaluate(DIAGNOSE_JS, timeout=2000)
        if isinstance(reason, str) and reason:
            return reason
    except Exception:
        pass
    return "it did not become usable in time"


async def _unusable(
    locator: Any, element_id: int, exc: BaseException
) -> MiniBrowserError:
    """The MiniBrowserError for a failed element action."""
    if isinstance(exc, MiniBrowserError):
        return exc
    try:
        page = locator.page
    except Exception:
        page = None
    if is_closed_error(exc, page):
        return closed_error()
    if _is_pw_timeout(exc):
        return MiniBrowserError(
            "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
            element_id=element_id,
            detail=await _diagnose(locator),
        )
    if _is_gone(exc):
        return MiniBrowserError("MINI_BROWSER_ELEMENT_NOT_FOUND", element_id=element_id)
    return MiniBrowserError(
        "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
        element_id=element_id,
        detail=_api_message(exc),
    )


async def wait_actionable(
    locator: Any, element_id: int, *, hover: bool = False, button: str = "left"
) -> None:
    """Wait (up to ACTION_WAIT_MS) until the element could be clicked/hovered.

    A trial action: Playwright scrolls it into view and checks it is
    visible, stable, enabled and not covered, but does not act.
    """
    try:
        if hover:
            await locator.hover(trial=True, timeout=ACTION_WAIT_MS)
        else:
            await locator.click(trial=True, timeout=ACTION_WAIT_MS, button=button)
    except Exception as exc:
        error = await _unusable(locator, element_id, exc)
        raise error from None


async def _box(locator: Any) -> Optional[Dict[str, float]]:
    try:
        return await locator.bounding_box(timeout=2000)
    except Exception:
        return None


async def _hits(locator: Any, x: float, y: float) -> bool:
    """True if a click at (x, y) (main-viewport CSS px) lands on the element."""
    try:
        hit = await locator.evaluate(HITS_JS, [x, y], timeout=2000)
    except Exception:
        return False
    return hit is None or bool(hit)


def _inside(core: Any, tab: Any, x: float, y: float) -> Tuple[float, float]:
    width, height = human.viewport_of(core, tab)
    return (min(max(0.0, x), width - 1.0), min(max(0.0, y), height - 1.0))


async def _aim(core: Any, tab: Any, locator: Any) -> Optional[Tuple[float, float]]:
    """A human target point on the element that a click would really hit."""
    box = await _box(locator)
    if not box or box["width"] <= 0 or box["height"] <= 0:
        return None
    x, y = _inside(core, tab, *human.target_point(box))
    if await _hits(locator, x, y):
        return (x, y)
    cx, cy = _inside(
        core, tab, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    )
    if await _hits(locator, cx, cy):
        return (cx, cy)
    return None


async def _plain_click(
    core: Any, tab: Any, locator: Any, element_id: int, *, button: str, click_count: int
) -> None:
    """Playwright's own click (re-checks actionability, short timeout)."""
    box = await _box(locator)
    centre = None
    if box:
        centre = _inside(
            core, tab, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        )
        await human.publish(core, tab, centre[0], centre[1], "move")
    human.ensure_control(tab)
    try:
        await locator.click(
            button=button, click_count=click_count, timeout=ACT_TIMEOUT_MS
        )
    except Exception as exc:
        error = await _unusable(locator, element_id, exc)
        raise error from None
    if centre:
        tab.mouse_x, tab.mouse_y = centre
        await human.publish(core, tab, centre[0], centre[1], "click")


async def pointer_click(
    core: Any,
    tab: Any,
    locator: Any,
    element_id: int,
    *,
    button: str = "left",
    click_count: int = 1,
) -> None:
    """Click like a person: curve to a point on the element, press, release.

    The point is verified to hit the element before moving and again right
    before pressing; if something covers it, Playwright's own click is used.
    Stops (MINI_BROWSER_USER_IN_CONTROL) once the user takes control.
    """
    human.ensure_control(tab)
    if humanlike_enabled(core):
        point = await _aim(core, tab, locator)
        if point is not None:
            await human.move_mouse(core, tab, *point)
            if await _hits(locator, *point):
                await human.click_at(
                    core, tab, *point, button=button, click_count=click_count
                )
                return
    await _plain_click(
        core, tab, locator, element_id, button=button, click_count=click_count
    )


async def _field_info(locator: Any, element_id: int) -> Dict[str, Any]:
    try:
        info = await locator.evaluate(FIELD_INFO_JS, timeout=2000)
    except Exception as exc:
        error = await _unusable(locator, element_id, exc)
        raise error from None
    return info if isinstance(info, dict) else {}


async def _has_focus(locator: Any) -> bool:
    try:
        return bool(await locator.evaluate(HAS_FOCUS_JS, timeout=2000))
    except Exception:
        return False


async def _focus(locator: Any, element_id: int) -> None:
    try:
        await locator.focus(timeout=ACT_TIMEOUT_MS)
    except Exception as exc:
        error = await _unusable(locator, element_id, exc)
        raise error from None


def _not_typeable(info: Dict[str, Any]) -> str:
    tag, kind = info.get("tag"), info.get("type")
    if tag == "SELECT":
        return "it is a dropdown list; use mini_browser_select_option"
    if tag == "INPUT" and kind in ("checkbox", "radio"):
        return "it is a checkbox or radio button; use mini_browser_click"
    if tag == "INPUT" and kind == "file":
        return "it is a file picker; use mini_browser_upload_file"
    if tag == "BUTTON" or (
        tag == "INPUT" and kind in ("button", "submit", "reset", "image")
    ):
        return "it is a button; use mini_browser_click"
    if info.get("disabled"):
        return "it is disabled"
    if info.get("readonly"):
        return "it is read-only"
    return ""


# ── navigation ──────────────────────────────────────────────────────────────


def _is_loopback(host: str) -> bool:
    """localhost, *.localhost (Chromium resolves those locally), 127/8, ::1,
    0.0.0.0, :: and IPv4-mapped IPv6 spellings of them."""
    host = host.strip("[]").lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_unspecified


def _loopback_ui_match(host: str, port: int, origins: frozenset) -> bool:
    """The loopback equivalence of ``urls.is_ui_origin``: any loopback spelling
    of the host matches a loopback UI origin, on that origin's port only."""
    if not _is_loopback(host):
        return False
    for origin in origins:
        try:
            parts = urlsplit("//" + origin)
            ui_host, ui_port = (parts.hostname or ""), parts.port
        except ValueError:
            continue
        if ui_port is not None and ui_port != port:
            continue
        if _is_loopback(ui_host):
            return True
    return False


def _is_ui_origin(core: Any, url: str, host: str, port: int) -> bool:
    """True if the URL points at CraftBot's own UI (core.ui_origins()).

    The shared rule lives in ``urls.is_ui_origin`` (canonical host spellings
    and loopback equivalence, port-scoped); the same loopback rule is applied
    here too, so the agent's own navigation never depends on one helper.
    """
    try:
        origins = frozenset(str(o).strip().lower() for o in core.ui_origins())
    except Exception:
        return False
    if not origins:
        return False
    try:
        from app.mini_browser import urls

        if urls.is_ui_origin(url, origins):
            return True
        canonical = urls.host_and_port(url)
        if canonical:
            host, port = canonical[0], canonical[1]
    except Exception as exc:
        logger.debug(f"[MiniBrowser] UI origin check fallback: {type(exc).__name__}")
    return _loopback_ui_match(host, port, origins)


def check_url_allowed(core: Any, url: str) -> None:
    """Defence in depth on top of urls.resolve: schemes and the app's own UI."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme in ("http", "https"):
        host = (parts.hostname or "").lower()
        if not host:
            raise MiniBrowserError(
                "MINI_BROWSER_BLOCKED_URL", reason="the address has no host"
            )
        try:
            port = parts.port or (443 if scheme == "https" else 80)
        except ValueError:
            raise MiniBrowserError(
                "MINI_BROWSER_BLOCKED_URL", reason="the address has an invalid port"
            ) from None
        if _is_ui_origin(core, url, host, port):
            raise MiniBrowserError(
                "MINI_BROWSER_BLOCKED_URL", reason="it is CraftBot's own interface"
            )
        return
    if url.lower().startswith("about:blank"):
        return
    if scheme == "file":
        if _setting(core, "allow_file_urls", False):
            return
        raise MiniBrowserError(
            "MINI_BROWSER_BLOCKED_URL",
            reason="opening local files is turned off in the Mini Browser settings",
        )
    raise MiniBrowserError(
        "MINI_BROWSER_BLOCKED_URL",
        reason=f"{scheme or 'this kind of'} addresses are not supported",
    )


async def _goto(
    page: Any,
    url: str,
    timeout_ms: int,
    watch: Optional[NavWatch],
    *,
    retried: bool = False,
) -> str:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        return ""
    except Exception as exc:
        if is_closed_error(exc, page):
            raise closed_error() from None
        message = _api_message(exc)
        low = message.lower()
        if "download is starting" in low:
            return DOWNLOAD_NOTE
        if _is_pw_timeout(exc):
            if watch is not None and watch.commits:
                return " The page is still loading."
            raise MiniBrowserError(
                "MINI_BROWSER_TIMEOUT",
                what=f"Opening {_short(url)}",
                seconds=round(timeout_ms / 1000),
            ) from None
        if "interrupted by another navigation" in low:
            # A blocked or failed earlier navigation commits Chromium's error
            # page asynchronously, and that late commit can interrupt this
            # one: retry once. Any other interruption is the page moving on
            # by itself (e.g. a client-side redirect), which is fine.
            if "chrome-error://" in low and not retried:
                return await _goto(page, url, timeout_ms, watch, retried=True)
            return ""
        if "net::err_aborted" in low:
            return ABORTED_NOTE
        raise MiniBrowserError(
            "MINI_BROWSER_NAVIGATION_FAILED", url=_short(url), detail=message
        ) from None


async def _history(page: Any, action: str, timeout_ms: int) -> str:
    before = page.url
    try:
        if action == "back":
            response = await page.go_back(
                wait_until="domcontentloaded", timeout=timeout_ms
            )
        elif action == "forward":
            response = await page.go_forward(
                wait_until="domcontentloaded", timeout=timeout_ms
            )
        else:
            response = await page.reload(
                wait_until="domcontentloaded", timeout=timeout_ms
            )
    except Exception as exc:
        if is_closed_error(exc, page):
            raise closed_error() from None
        if _is_pw_timeout(exc):
            return " The page is still loading."
        raise MiniBrowserError(
            "MINI_BROWSER_NAVIGATION_FAILED", url=action, detail=_api_message(exc)
        ) from None
    if action != "reload" and response is None and page.url == before:
        return f" There is no page to go {action} to in this tab."
    return ""


def _same_address(a: str, b: str) -> bool:
    """Same address, ignoring the fragment and a trailing slash."""

    def bare(url: str) -> str:
        return str(url or "").split("#", 1)[0].rstrip("/")

    return bare(a) == bare(b)


async def navigate(
    core: Any, tab: Any, *, url: str, timeout_ms: int = 30000
) -> Dict[str, Any]:
    """Open ``url`` (already resolved by validate) or back/forward/reload."""
    page = tab.page
    target = (url or "").strip()
    action = target.lower()
    with NavWatch(page) as watch:
        if action in HISTORY_TARGETS:
            note = await _history(page, action, timeout_ms)
        else:
            check_url_allowed(core, target)
            note = await _goto(page, target, timeout_ms, watch)
        if tab_gone(core, tab):
            raise closed_error(core, tab)
        note += await after_action(page, watch, baseline=watch.commits, core=core)
    if tab_gone(core, tab):
        raise closed_error(core, tab)
    observation = await page_observation(core, tab)
    if tab_gone(core, tab):
        raise closed_error(core, tab)
    where = observation.get("url") or scrub(_page_url(tab), _secrets(tab))
    title = observation.get("title")
    shown = f"{where}" + (f' ("{title}")' if title else "")
    if note.startswith(DOWNLOAD_NOTE):
        message = f"{DOWNLOAD_NOTE.strip()} The tab still shows {shown}."
    elif note.startswith(ABORTED_NOTE) and not _same_address(_page_url(tab), target):
        rest = note[len(ABORTED_NOTE) :]
        message = (
            f"Did not open {_short(target, 200)}; the tab still shows {shown} "
            f"(a download, a blocked page or a stopped load; see events).{rest}"
        )
    else:
        if note.startswith(ABORTED_NOTE):
            note = note[len(ABORTED_NOTE) :]
        verb = "Reloaded" if action == "reload" else "Opened"
        message = f"{verb} {shown}.{note}"
    return _success(scrub(message, _secrets(tab)), observation)


async def read(
    core: Any,
    tab: Any,
    *,
    max_text_chars: int = 4000,
    max_elements: int = 150,
    text_offset: int = 0,
) -> Dict[str, Any]:
    """Full observation of the page (the observation IS the result)."""
    observation = await observe(
        core,
        tab,
        compact=False,
        max_elements=max_elements,
        max_text_chars=max_text_chars,
        text_offset=text_offset,
    )
    if tab_gone(core, tab):
        raise closed_error(core, tab)
    shown = len(observation.get("elements") or [])
    message = f"Read {observation.get('url') or 'the page'}: {shown} elements"
    if observation.get("elements_truncated"):
        message += (
            f" of {observation.get('element_count')} (the list starts with what is "
            "on screen; scroll to reach the others)"
        )
    message += "."
    if "next_text_offset" in observation:
        message += (
            f" More text follows: call mini_browser_read with "
            f"text_offset={observation['next_text_offset']}."
        )
    result: Dict[str, Any] = {"status": "success", "message": message}
    result.update(observation)
    result["note"] = UNTRUSTED_NOTE
    return result


# ── pointer & keyboard ──────────────────────────────────────────────────────


async def click(
    core: Any, tab: Any, *, element_id: int, button: str = "left", double: bool = False
) -> Dict[str, Any]:
    page = tab.page
    locator = await locate(tab, element_id)
    await wait_actionable(locator, element_id, button=button)
    with NavWatch(page) as watch:
        await pointer_click(
            core,
            tab,
            locator,
            element_id,
            button=button,
            click_count=2 if double else 1,
        )
        note = await after_action(page, watch, core=core)
    what = (
        "Double-clicked"
        if double
        else ("Right-clicked" if button == "right" else "Clicked")
    )
    if button == "middle":
        what = "Middle-clicked"
    return await _done(core, tab, f"{what} element {element_id}.{note}")


async def hover(core: Any, tab: Any, *, element_id: int) -> Dict[str, Any]:
    page = tab.page
    locator = await locate(tab, element_id)
    await wait_actionable(locator, element_id, hover=True)
    with NavWatch(page) as watch:
        point = await _aim(core, tab, locator) if humanlike_enabled(core) else None
        if point is not None:
            await human.move_mouse(core, tab, *point)
            await human.pause(*human.HOVER_PAUSE, core=core)
        else:
            box = await _box(locator)
            human.ensure_control(tab)
            try:
                await locator.hover(timeout=ACT_TIMEOUT_MS)
            except Exception as exc:
                error = await _unusable(locator, element_id, exc)
                raise error from None
            if box:
                x, y = _inside(
                    core, tab, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                )
                tab.mouse_x, tab.mouse_y = x, y
                await human.publish(core, tab, x, y, "move")
        note = await after_action(page, watch, core=core)
    return await _done(core, tab, f"Moved the pointer over element {element_id}.{note}")


async def _clear(page: Any, tab: Any, locator: Any, info: Dict[str, Any]) -> None:
    human.ensure_control(tab)
    if info.get("tag") in ("INPUT", "TEXTAREA") or info.get("editable"):
        try:
            await locator.fill("", timeout=ACT_TIMEOUT_MS)
            return
        except Exception as exc:
            logger.debug(
                f"[MiniBrowser] clearing with fill failed: {type(exc).__name__}"
            )
    # The keyboard fallback acts on whatever has focus: never once the user
    # has taken over (their field would be wiped).
    human.ensure_control(tab)
    await page.keyboard.press("ControlOrMeta+a")
    human.ensure_control(tab)
    await page.keyboard.press("Delete")


# ── whole-value inputs (date, time, colour, slider, ...) ────────────────────

_VALUE_FORMATS = {
    "date": ("a date", "YYYY-MM-DD (for example 2026-10-01)"),
    "time": ("a time", "HH:MM in 24-hour time (for example 14:30)"),
    "datetime-local": (
        "a date and time",
        "YYYY-MM-DDTHH:MM (for example 2026-10-01T14:30)",
    ),
    "month": ("a month", "YYYY-MM (for example 2026-10)"),
    "week": ("a week", "YYYY-Www (for example 2026-W40)"),
    "color": ("a colour", "#rrggbb (for example #1a73e8)"),
    "range": ("a slider", "a number (for example 50)"),
}
_DATE_RE = re.compile(
    r"^(\d{4})\s*(?:[-/.]|年)\s*(\d{1,2})\s*(?:[-/.]|月)\s*(\d{1,2})\s*日?$"
)
_MONTH_RE = re.compile(r"^(\d{4})\s*(?:[-/.]|年)\s*(\d{1,2})\s*月?$")
_WEEK_RE = re.compile(r"^(\d{4})\s*-?\s*W\s*(\d{1,2})$", re.IGNORECASE)
_TIME_RE = re.compile(
    r"^(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?\s*(?:([ap])\.?\s*m\.?)?$",
    re.IGNORECASE,
)
_DATETIME_RE = re.compile(r"^(.+?)(?:T|\s+)(\d{1,2}:\d{2}.*)$", re.IGNORECASE)
_COLOR_RE = re.compile(r"^#?([0-9a-f]{6}|[0-9a-f]{3})$", re.IGNORECASE)


def _norm_date(text: str) -> Optional[str]:
    match = _DATE_RE.match(text)
    if not match:
        return None
    try:
        day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return f"{day.year:04d}-{day.month:02d}-{day.day:02d}"


def _norm_time(text: str) -> Optional[str]:
    match = _TIME_RE.match(text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    second = int(match.group(3)) if match.group(3) else 0
    millis = match.group(4)
    half = (match.group(5) or "").lower()
    if half:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if half == "p" else 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    out = f"{hour:02d}:{minute:02d}"
    if match.group(3) and (second or millis):
        out += f":{second:02d}"
        if millis and int(millis):
            out += "." + millis.ljust(3, "0")
    return out


def normalise_input_value(kind: str, text: str) -> Optional[str]:
    """The HTML value format of ``text`` for an input of type ``kind``, or
    None when it cannot be read unambiguously. Accepts ISO forms (and the
    year-first forms 2026/10/01, 2026年10月1日); never guesses whether
    10/01/2026 is October or January."""
    value = " ".join(str(text or "").split())
    if kind == "date":
        return _norm_date(value)
    if kind == "time":
        return _norm_time(value)
    if kind == "datetime-local":
        match = _DATETIME_RE.match(value)
        if not match:
            return None
        day, clock = _norm_date(match.group(1).strip()), _norm_time(match.group(2))
        return f"{day}T{clock}" if day and clock else None
    if kind == "month":
        match = _MONTH_RE.match(value)
        if not match or not 1 <= int(match.group(2)) <= 12:
            return None
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    if kind == "week":
        match = _WEEK_RE.match(value)
        if not match or not 1 <= int(match.group(2)) <= 53:
            return None
        return f"{int(match.group(1)):04d}-W{int(match.group(2)):02d}"
    if kind == "color":
        match = _COLOR_RE.match(value)
        if not match:
            return None
        digits = match.group(1).lower()
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        return "#" + digits
    if kind == "range":
        try:
            number = float(value)
        except ValueError:
            return None
        if not math.isfinite(number):
            return None
        return str(int(number)) if number.is_integer() else repr(number)
    return None


def _format_error(element_id: int, kind: str, given: str) -> MiniBrowserError:
    name, hint = _VALUE_FORMATS.get(kind, ("a", "the format the field expects"))
    shown = f' "{_short(given, 40)}"' if given else " an empty value"
    return MiniBrowserError(
        "MINI_BROWSER_INVALID_INPUT",
        detail=(
            f"Element {element_id} is {name} field and cannot take{shown}; "
            f"give it as {hint}."
        ),
    )


async def _set_whole_value(
    core: Any,
    tab: Any,
    locator: Any,
    element_id: int,
    kind: str,
    text: str,
    submit: bool,
) -> Dict[str, Any]:
    """Type into a date / time / month / week / colour / slider input: set
    the value as a whole, then check the field really holds it."""
    page = tab.page
    given = " ".join(str(text or "").split())
    if not given and kind in ("color", "range"):
        raise _format_error(element_id, kind, given)
    value = normalise_input_value(kind, given) if given else ""
    if value is None:
        raise _format_error(element_id, kind, given)
    await wait_actionable(locator, element_id)
    with NavWatch(page) as watch:
        if humanlike_enabled(core):
            # Point at it (no click: a click would open a picker or move the
            # slider to wherever it landed).
            point = await _aim(core, tab, locator)
            if point is not None:
                await human.move_mouse(core, tab, *point)
                await human.pause(*human.HOVER_PAUSE, core=core)
        human.ensure_control(tab)
        try:
            result = await locator.evaluate(
                SET_VALUE_JS, {"value": value}, timeout=ACT_TIMEOUT_MS
            )
        except Exception as exc:
            error = await _unusable(locator, element_id, exc)
            raise error from None
        result = result if isinstance(result, dict) else {}
        now = result.get("value")
        if kind != "range" and not result.get("ok"):
            if value and (result.get("empty") or now is None):
                raise _format_error(element_id, kind, given)
            kept = f' (it shows "{_short(now, 40)}" now)' if now else ""
            raise MiniBrowserError(
                "MINI_BROWSER_INVALID_INPUT",
                detail=(
                    f'Element {element_id} did not keep "{value}"{kept}: the page '
                    "changed it. Look at the page for the values it allows."
                ),
            )
        if submit:
            human.ensure_control(tab)
            await page.keyboard.press("Enter")
        note = await after_action(page, watch, core=core)
    if kind == "range":
        actual = now if now is not None else value
        message = f"Set element {element_id} to {actual}"
        if now is not None and now != value:
            message += f" (the nearest value the slider allows to {value})"
    elif not value:
        message = f"Cleared element {element_id}"
    elif now is None:  # a secret-looking field: never echo its value
        message = f"Set element {element_id}"
    else:
        message = f'Set element {element_id} to "{value}"'
    message += " and pressed Enter." if submit else "."
    return await _done(core, tab, message + note)


async def _typed_state(locator: Any) -> str:
    try:
        state = await locator.evaluate(TYPED_CHECK_JS, timeout=2000)
    except Exception:
        return "skip"
    return state if isinstance(state, str) else "skip"


def _interrupted_note(
    tab: Any, element_id: int, exc: MiniBrowserError, total: int, submit: bool
) -> None:
    typed = getattr(exc, "typed", None)
    if typed is None:
        message = (
            f"Nothing was typed into element {element_id}: the user took control "
            "of this tab first."
        )
    else:
        message = (
            f"Typing into element {element_id} stopped after {typed} of {total} "
            "characters because the user took control"
            + ("; Enter was not pressed" if submit else "")
            + ". Check that field after they hand control back."
        )
    _agent_note(tab, message)


async def type_text(
    core: Any,
    tab: Any,
    *,
    element_id: int,
    text: str,
    submit: bool = False,
    clear: bool = True,
) -> Dict[str, Any]:
    """Type into a field like a person (click it, clear it, type, Enter).

    Date, time, month, week, colour and slider inputs are set as a whole in
    their HTML value format instead, and the value is checked. A text field
    still empty after typing is reported as a failure.
    """
    page = tab.page
    locator = await locate(tab, element_id)
    info = await _field_info(locator, element_id)
    problem = _not_typeable(info)
    if problem:
        raise MiniBrowserError(
            "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
            element_id=element_id,
            detail=problem,
        )
    if info.get("tag") == "INPUT" and info.get("type") in VALUE_INPUT_TYPES:
        return await _set_whole_value(
            core, tab, locator, element_id, str(info["type"]), text, submit
        )
    await wait_actionable(locator, element_id)
    failure = ""
    lost: Optional[int] = None
    with NavWatch(page) as watch:
        try:
            if humanlike_enabled(core):
                await pointer_click(core, tab, locator, element_id)
            human.ensure_control(tab)
            if not await _has_focus(locator):
                await _focus(locator, element_id)
                if not await _has_focus(locator):
                    raise MiniBrowserError(
                        "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
                        element_id=element_id,
                        detail="it does not take keyboard input (it could not be focused)",
                    )
            if clear:
                await _clear(page, tab, locator, info)
            else:
                try:
                    moved = await locator.evaluate(CARET_END_JS, timeout=2000)
                except Exception:
                    moved = False
                if not moved:
                    human.ensure_control(tab)
                    await page.keyboard.press("End")
            try:
                await human.type_text(
                    core, tab, text, focus_check=lambda: _has_focus(locator)
                )
                if submit:
                    human.ensure_control(tab, len(text))
                    await page.keyboard.press("Enter")
            except MiniBrowserError:
                raise
            except human.FocusLost as exc:
                lost = exc.typed
            except Exception as exc:
                # Never echo the exception: its text could contain what was typed.
                failure = type(exc).__name__
                if is_closed_error(exc, page):
                    raise closed_error(core, tab) from None
        except MiniBrowserError as exc:
            if exc.code == "MINI_BROWSER_USER_IN_CONTROL":
                _interrupted_note(tab, element_id, exc, len(text), submit)
            raise
        if lost is not None:
            raise MiniBrowserError(
                "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
                element_id=element_id,
                detail=(
                    f"typing stopped after {lost} of {len(text)} characters because "
                    "the field lost keyboard focus (the page moved it); look at the "
                    "page before typing the rest"
                ),
            )
        if failure:
            logger.warning(
                f"[MiniBrowser] typing into element {element_id} failed: {failure}"
            )
            raise MiniBrowserError(
                "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
                element_id=element_id,
                detail="typing was interrupted because the page changed",
            )
        note = await after_action(page, watch, core=core)
        if text.strip() and not submit and not watch.navigated:
            if await _typed_state(locator) == "empty":
                raise MiniBrowserError(
                    "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
                    element_id=element_id,
                    detail=(
                        "the field was still empty after typing (the page did not "
                        "accept the text, e.g. letters in a number field); look at "
                        "the page before trying again"
                    ),
                )
    message = f"Typed {len(text)} characters into element {element_id}"
    if not text and clear:
        message = f"Cleared element {element_id}"
    message += " and pressed Enter." if submit else "."
    return await _done(core, tab, message + note)


_KEY_ALIASES = {
    "ctrl": "Control",
    "control": "Control",
    "cmd": "Meta",
    "command": "Meta",
    "meta": "Meta",
    "win": "Meta",
    "windows": "Meta",
    "super": "Meta",
    "option": "Alt",
    "opt": "Alt",
    "alt": "Alt",
    "shift": "Shift",
    "controlormeta": "ControlOrMeta",
    "mod": "ControlOrMeta",
    "esc": "Escape",
    "escape": "Escape",
    "return": "Enter",
    "enter": "Enter",
    "del": "Delete",
    "delete": "Delete",
    "backspace": "Backspace",
    "tab": "Tab",
    "space": "Space",
    "spacebar": "Space",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "arrowup": "ArrowUp",
    "arrowdown": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "arrowright": "ArrowRight",
    "pgup": "PageUp",
    "pageup": "PageUp",
    "pgdn": "PageDown",
    "pagedown": "PageDown",
    "home": "Home",
    "end": "End",
    "ins": "Insert",
    "insert": "Insert",
}


def _canonical_key(key: str) -> str:
    alias = _KEY_ALIASES.get(key.lower())
    if alias:
        return alias
    if re.fullmatch(r"[fF]([1-9]|1[0-9]|2[0-4])", key):
        return key.upper()
    return key


def parse_keys(keys: str) -> List[str]:
    """``"Control+a"``, ``"Tab Tab Enter"``, ``"ctrl + shift + t"`` → combos.

    Returns Playwright key combos (one per press). Whitespace separates
    presses; ``+`` joins keys of one combo (a trailing ``+`` is the "+" key).
    Raises MiniBrowserError(MINI_BROWSER_INVALID_INPUT) on empty input.
    """
    text = re.sub(r"\s*\+\s*", "+", str(keys or "").strip())
    combos: List[str] = []
    for token in text.split():
        if token != "," and token.endswith(","):
            token = token[:-1]
        if not token:
            continue
        parts = re.split(r"\+(?=.)", token)
        if any(not part for part in parts):
            raise MiniBrowserError(
                "MINI_BROWSER_INVALID_INPUT",
                detail=f'"{_short(token, 40)}" is not a key combination.',
            )
        combos.append("+".join(_canonical_key(part) for part in parts))
    if not combos:
        raise MiniBrowserError(
            "MINI_BROWSER_INVALID_INPUT",
            detail="keys is empty: give a key such as Enter.",
        )
    if len(combos) > MAX_KEY_COMBOS:
        raise MiniBrowserError(
            "MINI_BROWSER_INVALID_INPUT",
            detail=f"Too many key presses at once (max {MAX_KEY_COMBOS}).",
        )
    return combos


async def press_key(
    core: Any, tab: Any, *, keys: str, element_id: Optional[int] = None
) -> Dict[str, Any]:
    """Press keys (combos like "Control+a"; several separated by spaces)."""
    page = tab.page
    combos = parse_keys(keys)
    if element_id is not None:
        locator = await locate(tab, element_id)
        human.ensure_control(tab)
        await _focus(locator, element_id)
    with NavWatch(page) as watch:
        for index, combo in enumerate(combos):
            human.ensure_control(tab)
            unknown = ""
            try:
                await page.keyboard.press(combo)
            except Exception as exc:
                if is_closed_error(exc, page):
                    raise closed_error(core, tab) from None
                if "unknown key" not in str(exc).lower():
                    raise
                unknown = combo
            if unknown:
                raise MiniBrowserError(
                    "MINI_BROWSER_INVALID_INPUT",
                    detail=(
                        f'Unknown key in "{_short(unknown, 40)}". Use key names such as '
                        "Enter, Escape, Tab, ArrowDown, PageDown, Backspace, Control+a "
                        "or Shift+Tab."
                    ),
                )
            if index < len(combos) - 1:
                await human.pause(0.06, 0.16, core=core)
        note = await after_action(page, watch, core=core)
    target = f" in element {element_id}" if element_id is not None else ""
    return await _done(core, tab, f"Pressed {' '.join(combos)}{target}.{note}")


async def select_option(
    core: Any, tab: Any, *, element_id: int, value: str
) -> Dict[str, Any]:
    """Choose an option of a <select> by its value or its visible label."""
    page = tab.page
    locator = await locate(tab, element_id)
    try:
        match = await locator.evaluate(SELECT_MATCH_JS, value, timeout=2000)
    except Exception as exc:
        error = await _unusable(locator, element_id, exc)
        raise error from None
    if not isinstance(match, dict) or not match.get("native"):
        raise MiniBrowserError(
            "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
            element_id=element_id,
            detail=(
                "it is not a dropdown list (<select>); click it to open its "
                "options, then click the option"
            ),
        )
    index = int(match.get("index", -1))
    if index < 0:
        options = ", ".join(str(o) for o in match.get("options") or [])
        more = int(match.get("count") or 0) - len(match.get("options") or [])
        tail = f", +{more} more" if more > 0 else ""
        raise MiniBrowserError(
            "MINI_BROWSER_INVALID_INPUT",
            detail=(
                f'Element {element_id} has no option "{_short(value, 60)}". '
                f"Options: {options}{tail}."
            ),
        )
    if match.get("disabled"):
        raise MiniBrowserError(
            "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
            element_id=element_id,
            detail="it (or that option) is disabled",
        )
    with NavWatch(page) as watch:
        if humanlike_enabled(core):
            point = await _aim(core, tab, locator)
            if point is not None:
                await human.move_mouse(core, tab, *point)
                await human.pause(*human.HOVER_PAUSE, core=core)
        human.ensure_control(tab)
        try:
            # The option was verified above; force also covers native selects
            # hidden behind a custom dropdown, and never waits (so a Stop
            # cannot lead to a late selection).
            await locator.select_option(index=index, force=True, timeout=ACT_TIMEOUT_MS)
        except Exception as exc:
            error = await _unusable(locator, element_id, exc)
            raise error from None
        note = await after_action(page, watch, core=core)
    label = match.get("label") or value
    return await _done(
        core, tab, f'Selected "{_short(label, 60)}" in element {element_id}.{note}'
    )


# ── scrolling & waiting ─────────────────────────────────────────────────────


async def _scroll_state(page: Any, x: float, y: float) -> Dict[str, Any]:
    try:
        state = await _evaluate(page, SCROLL_STATE_JS, {"x": x, "y": y})
    except MiniBrowserError:
        raise
    except Exception as exc:
        if is_closed_error(exc, page):
            raise closed_error() from None
        logger.debug(f"[MiniBrowser] scroll state failed: {type(exc).__name__}")
        state = None
    return state if isinstance(state, dict) else {"doc": None, "inner": None}


def _positions(state: Dict[str, Any]) -> Tuple[Any, Any]:
    doc = state.get("doc") or {}
    inner = state.get("inner") or {}
    return (doc.get("y"), inner.get("y"))


async def _wait_scroll_idle(
    page: Any, x: float, y: float, before: Dict[str, Any]
) -> Dict[str, Any]:
    """Poll until the scroll position stops changing (smooth scrolling).

    A position equal to ``before`` only counts as "done" after a moment, so
    a scroll that has not started yet is not mistaken for no scroll.
    """
    started = time.monotonic()
    deadline = started + SCROLL_IDLE_MAX_S
    origin = _positions(before)
    last = await _scroll_state(page, x, y)
    while time.monotonic() < deadline:
        await asyncio.sleep(0.08)
        current = await _scroll_state(page, x, y)
        position = _positions(current)
        if position == _positions(last) and (
            position != origin or time.monotonic() - started > 0.3
        ):
            return current
        last = current
    return last


def _moved_box(
    before: Dict[str, Any], after: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """The scroll box (inner first, then the page) whose position changed."""
    for key in ("inner", "doc"):
        old, new = before.get(key) or {}, after.get(key) or {}
        if old and new and old.get("y") != new.get("y"):
            return new
    return None


async def scroll(
    core: Any, tab: Any, *, direction: str = "down", amount: Optional[int] = None
) -> Dict[str, Any]:
    """Scroll with human wheel steps at the viewport centre (or jump top/bottom)."""
    page = tab.page
    width, height = human.viewport_of(core, tab)
    cx, cy = width / 2.0, height / 2.0
    before = await _scroll_state(page, cx, cy)
    if direction in ("top", "bottom"):
        human.ensure_control(tab)
        await _evaluate(page, SCROLL_TO_JS, {"x": cx, "y": cy, "to": direction})
        distance = None
    else:
        distance = int(amount) if amount else max(100, int(height * 0.8))
        try:
            point = await _evaluate(page, WHEEL_POINT_JS, {"x": cx, "y": cy})
            px, py = float(point[0]), float(point[1])
        except MiniBrowserError:
            raise
        except Exception:
            px, py = cx, cy
        if humanlike_enabled(core):
            px += human.jitter(0.05) * width
            py += human.jitter(0.05) * height
        await human.move_mouse(core, tab, *_inside(core, tab, px, py))
        await human.wheel(core, tab, distance if direction == "down" else -distance)
    await _wait_scroll_idle(page, cx, cy, before)
    await settle(page, quiet_ms=300, max_ms=1500)
    after = await _scroll_state(page, cx, cy)
    moved = _moved_box(before, after)
    box = moved or after.get("doc") or after.get("inner") or {}
    at_bottom = bool(box.get("at_bottom", False))
    at_top = bool(box.get("at_top", False))

    if moved:
        old = (
            before.get("inner") if moved is after.get("inner") else before.get("doc")
        ) or {}
        delta = abs(int(moved.get("y", 0)) - int(old.get("y", 0)))
        message = f"Scrolled {direction} {delta} px."
        if direction in ("down", "bottom") and at_bottom:
            message += " Reached the bottom."
    elif direction in ("down", "bottom") and at_bottom:
        message = "Did not scroll: already at the bottom."
    elif direction in ("up", "top") and at_top:
        message = "Did not scroll: already at the top."
    else:
        message = "Nothing scrolled here (this part of the page may not scroll)."
    return await _done(
        core,
        tab,
        message,
        scrolled=moved is not None,
        at_bottom=at_bottom,
    )


async def _text_present(page: Any, text: str) -> bool:
    try:
        return bool(await _evaluate(page, TEXT_PRESENT_JS, text))
    except MiniBrowserError:
        return False
    except Exception as exc:
        if is_closed_error(exc, page):
            raise closed_error() from None
        if not is_context_destroyed(exc):
            logger.debug(f"[MiniBrowser] text check failed: {type(exc).__name__}")
        return False


def _wait_limit_s(requested_s: float) -> float:
    """``requested_s``, kept under the core's own time limit for the wait
    operation (when the core declares one)."""
    core_module = sys.modules.get("app.mini_browser.core")
    limit = getattr(core_module, "WAIT_OP_TIMEOUT_S", None)
    if isinstance(limit, (int, float)) and limit > WAIT_LIMIT_MARGIN_S * 2:
        return min(requested_s, float(limit) - WAIT_LIMIT_MARGIN_S)
    return requested_s


async def _wait_for_user(core: Any, tab: Any, timeout_s: float) -> Dict[str, Any]:
    """mini_browser_wait(for_user=true).

    If the user controls the tab: wait until they hand it back. Otherwise
    wait until they TAKE control (any input of theirs on this tab does that
    while the agent waits) and then hand it back. Fails early with
    MINI_BROWSER_CLOSED when the tab or the browser closes.
    """
    page = tab.page
    seconds = _wait_limit_s(timeout_s)
    deadline = time.monotonic() + seconds
    took = bool(tab.user_control)
    while True:
        if tab_gone(core, tab):
            raise closed_error(core, tab)
        if tab.user_control:
            took = True
        elif took:
            break
        if time.monotonic() >= deadline:
            if took:
                raise MiniBrowserError(
                    "MINI_BROWSER_TIMEOUT",
                    what="Waiting for the user to hand back control",
                    seconds=round(seconds),
                )
            result = action_error(
                "MINI_BROWSER_TIMEOUT",
                what="Waiting for the user to take control",
                seconds=round(seconds),
            )
            result["message"] = (
                f"The user did not take control of this tab within {round(seconds)} s. "
                "Ask them in chat what to do, as your final message (for example to "
                "solve the check in the Mini Browser page and press Hand back), and "
                "continue from a fresh mini_browser_read when they reply."
            )
            result["page"] = await page_observation(core, tab)
            return result
        await asyncio.sleep(FOR_USER_POLL_S)
    await settle(page)
    return await _done(
        core,
        tab,
        "The user handed control back. Look at the page before acting: it may "
        "have changed.",
    )


async def wait(
    core: Any,
    tab: Any,
    *,
    seconds: Optional[float] = None,
    text: Optional[str] = None,
    for_user: bool = False,
    timeout_ms: int = 10000,
) -> Dict[str, Any]:
    """Sleep, wait for text to appear, or wait for the user (see
    :func:`_wait_for_user`). Every wait ends early with MINI_BROWSER_CLOSED
    when the tab or the browser closes."""
    page = tab.page
    timeout_s = max(0.0, timeout_ms / 1000.0)
    if for_user:
        return await _wait_for_user(core, tab, timeout_s)
    if text:
        deadline = time.monotonic() + timeout_s
        while not await _text_present(page, text):
            if tab_gone(core, tab):
                raise closed_error(core, tab)
            if time.monotonic() >= deadline:
                raise MiniBrowserError(
                    "MINI_BROWSER_TIMEOUT",
                    what=f'Waiting for the text "{_short(text, 60)}"',
                    seconds=round(timeout_s),
                )
            await asyncio.sleep(TEXT_POLL_S)
        message = f'The text "{_short(text, 60)}" is on the page.'
    elif seconds is not None:
        end = time.monotonic() + max(0.0, float(seconds))
        while True:
            if tab_gone(core, tab):
                raise closed_error(core, tab)
            left = end - time.monotonic()
            if left <= 0:
                break
            await asyncio.sleep(min(SLEEP_SLICE_S, left))
        message = f"Waited {float(seconds):g} s."
    else:
        await settle(page, quiet_ms=500, max_ms=int(min(timeout_s, 10.0) * 1000))
        message = "Waited for the page to settle."
    return await _done(core, tab, message)


# ── files ───────────────────────────────────────────────────────────────────


def _upload_roots(owner: Optional[str]) -> List[Tuple[str, str]]:
    """Allowed roots as (lexical, real) absolute paths. Runs in a thread."""
    roots: List[Path] = []
    try:
        from app.mini_browser import config as mb_config

        workspace = mb_config.workspace_dir(owner)
        if workspace:
            roots.append(Path(workspace))
    except Exception as exc:
        logger.debug(
            f"[MiniBrowser] session workspace unavailable: {type(exc).__name__}"
        )
    try:
        from app.config import AGENT_WORKSPACE_ROOT

        roots.append(Path(AGENT_WORKSPACE_ROOT))
    except Exception as exc:
        logger.debug(f"[MiniBrowser] workspace root unavailable: {type(exc).__name__}")
    out: List[Tuple[str, str]] = []
    for root in roots:
        lexical = os.path.normpath(os.path.abspath(str(root)))
        real = os.path.realpath(lexical)
        if (lexical, real) not in out:
            out.append((lexical, real))
    return out


def _within(path: str, root: str) -> bool:
    try:
        path_c, root_c = os.path.normcase(path), os.path.normcase(root)
        return os.path.commonpath([path_c, root_c]) == root_c
    except ValueError:  # different drives / UNC vs local
        return False


def resolve_upload_paths(paths: Sequence[str], owner: Optional[str]) -> List[str]:
    """Absolute real paths of files inside the agent workspace.

    Synchronous (touches the filesystem): call through asyncio.to_thread.
    Each path is first checked lexically, so a path outside the workspace
    (including UNC shares) is refused without ever touching it; then the
    real path (symlinks resolved) must still be inside.
    """
    roots = _upload_roots(owner)
    if not roots:
        raise MiniBrowserError(
            "MINI_BROWSER_UPLOAD_DENIED", path="no workspace is available"
        )
    resolved: List[str] = []
    for raw in paths:
        given = str(raw).strip()
        if os.path.isabs(given):
            # An absolute path may point into any allowed root.
            candidates = [(os.path.normpath(given), roots)]
        else:
            # A relative path is tried against each root and must stay inside
            # that root ("../" cannot climb out of it).
            candidates = [
                (os.path.normpath(os.path.join(lexical, given)), [(lexical, real)])
                for lexical, real in roots
            ]
        allowed: List[str] = []
        for candidate, bases in candidates:
            if not any(
                _within(candidate, lexical) or _within(candidate, real)
                for lexical, real in bases
            ):
                continue
            real_path = os.path.realpath(candidate)
            if any(_within(real_path, real) for _, real in roots):
                allowed.append(real_path)
        if not allowed:
            raise MiniBrowserError(
                "MINI_BROWSER_UPLOAD_DENIED", path=_short(given, 200)
            )
        chosen = next((p for p in allowed if os.path.isfile(p)), None)
        if chosen is None:
            raise MiniBrowserError(
                "MINI_BROWSER_INVALID_INPUT",
                detail=f"There is no file at {_short(given, 200)} in the agent workspace.",
            )
        resolved.append(chosen)
    return resolved


async def upload_file(
    core: Any, tab: Any, *, element_id: int, paths: List[str]
) -> Dict[str, Any]:
    """Attach workspace files to a file input (or the button that opens one)."""
    page = tab.page
    files = await asyncio.to_thread(resolve_upload_paths, list(paths), tab.owner)
    locator = await locate(tab, element_id)
    info = await _field_info(locator, element_id)
    names = [os.path.basename(p) for p in files]
    with NavWatch(page) as watch:
        if info.get("tag") == "INPUT" and info.get("type") == "file":
            if len(files) > 1 and not info.get("multiple"):
                raise MiniBrowserError(
                    "MINI_BROWSER_INVALID_INPUT",
                    detail=f"Element {element_id} accepts only one file.",
                )
            human.ensure_control(tab)
            try:
                await locator.set_input_files(files, timeout=ACTION_WAIT_MS)
            except Exception as exc:
                error = await _unusable(locator, element_id, exc)
                raise error from None
        else:
            # A styled button / drop zone that opens the file chooser.
            await wait_actionable(locator, element_id)
            try:
                async with page.expect_file_chooser(
                    timeout=ACTION_WAIT_MS
                ) as chooser_info:
                    await pointer_click(core, tab, locator, element_id)
                chooser = await chooser_info.value
            except MiniBrowserError:
                raise
            except Exception as exc:
                if is_closed_error(exc, page):
                    raise closed_error(core, tab) from None
                if not _is_pw_timeout(exc):
                    raise
                raise MiniBrowserError(
                    "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
                    element_id=element_id,
                    detail="clicking it did not open a file chooser; use the file input itself",
                ) from None
            if len(files) > 1 and not chooser.is_multiple():
                raise MiniBrowserError(
                    "MINI_BROWSER_INVALID_INPUT",
                    detail=f"Element {element_id} accepts only one file.",
                )
            human.ensure_control(tab)
            await chooser.set_files(files, timeout=ACTION_WAIT_MS)
        note = await after_action(page, watch, core=core)
    return await _done(
        core,
        tab,
        f"Attached {', '.join(names)} to element {element_id}.{note}",
        files=names,
    )


def _screenshots_dir(owner: Optional[str]) -> Path:
    try:
        from app.mini_browser import config as mb_config

        return Path(mb_config.screenshots_dir(owner))
    except Exception as exc:
        logger.debug(f"[MiniBrowser] screenshots dir fallback: {type(exc).__name__}")
        from app.config import AGENT_WORKSPACE_ROOT

        return Path(AGENT_WORKSPACE_ROOT) / "mini_browser" / "screenshots"


def save_screenshot(owner: Optional[str], data: bytes) -> str:
    """Write PNG bytes to a new file in the owner's screenshots dir (thread)."""
    directory = _screenshots_dir(owner)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    for attempt in range(100):
        suffix = f"_{attempt}" if attempt else ""
        path = directory / f"screenshot_{stamp}{suffix}.png"
        try:
            with open(path, "xb") as handle:
                handle.write(data)
            return str(path)
        except FileExistsError:
            continue
    raise MiniBrowserError(
        "MINI_BROWSER_INTERNAL", detail="could not name the screenshot file"
    )


async def screenshot(core: Any, tab: Any, *, full_page: bool = False) -> Dict[str, Any]:
    """Save a PNG of the tab into the owner's workspace; returns its path."""
    page = tab.page
    try:
        data = await asyncio.wait_for(
            page.screenshot(
                type="png", full_page=bool(full_page), timeout=SCREENSHOT_TIMEOUT_MS
            ),
            SCREENSHOT_TIMEOUT_MS / 1000.0 + 5.0,
        )
    except asyncio.TimeoutError:
        raise MiniBrowserError("MINI_BROWSER_PAGE_UNRESPONSIVE") from None
    except Exception as exc:
        if is_closed_error(exc, page):
            raise closed_error(core, tab) from None
        if not _is_pw_timeout(exc):
            raise
        raise MiniBrowserError(
            "MINI_BROWSER_TIMEOUT",
            what="Taking the screenshot",
            seconds=SCREENSHOT_TIMEOUT_MS // 1000,
        ) from None
    path = await asyncio.to_thread(save_screenshot, tab.owner, data)
    kind = "full-page screenshot" if full_page else "screenshot"
    return await _done(core, tab, f"Saved a {kind} to {path}.", file_path=path)


async def login(
    core: Any, tab: Any, *, username: Optional[str] = None, submit: bool = True
) -> Dict[str, Any]:
    """Sign in with a saved login from the password vault."""
    from app.mini_browser.login import autofill

    return await autofill(core, tab, username=username, submit=submit)


_CLOSED_CODES = frozenset(
    {"MINI_BROWSER_CLOSED", "MINI_BROWSER_TAB_CLOSED", "MINI_BROWSER_NOT_RUNNING"}
)


def _reporting_closes(fn: Op) -> Op:
    """``fn`` with its "closed" errors told apart: the tab alone was closed
    (MINI_BROWSER_TAB_CLOSED) or the whole browser (MINI_BROWSER_CLOSED).
    Helpers deep inside an operation only see the page close under them."""

    @functools.wraps(fn)
    async def op(core: Any, tab: Any, **params: Any) -> Dict[str, Any]:
        try:
            return await fn(core, tab, **params)
        except MiniBrowserError as exc:
            if exc.code in _CLOSED_CODES and tab_gone(core, tab):
                raise closed_error(core, tab) from None
            raise

    return op


OPS: Dict[str, Op] = {
    name: _reporting_closes(fn)
    for name, fn in {
        "navigate": navigate,
        "read": read,
        "click": click,
        "hover": hover,
        "type": type_text,
        "press_key": press_key,
        "select_option": select_option,
        "scroll": scroll,
        "wait": wait,
        "upload_file": upload_file,
        "login": login,
        "screenshot": screenshot,
    }.items()
}
