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
and the agent passes ``n``. A locator built from the CURRENT generation
either finds exactly that element or nothing, so a stale id fails loudly
instead of clicking something else.

Cancellation: element actions wait for the element first (a trial action
that never acts) and only then act, so a Stop that cancels the wait can
never cause a late click.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from app.logger import logger
from app.mini_browser import human
from app.mini_browser.errors import MiniBrowserError, first_line
from app.mini_browser.observe import (
    JS_COMMON,
    UNTRUSTED_NOTE,
    is_context_destroyed,
    observe,
)

# How long an element may take to become actionable, then the real action.
ACTION_WAIT_MS = 5000
ACT_TIMEOUT_MS = 1500
# How long an action follows a navigation it started.
NAV_WAIT_S = 15.0
# Page "settled" = no DOM mutation for SETTLE_QUIET_MS, or SETTLE_MAX_MS.
SETTLE_QUIET_MS = 400
SETTLE_MAX_MS = 2500
EVALUATE_TIMEOUT_S = 10.0
LOCATE_TIMEOUT_S = 5.0
SCREENSHOT_TIMEOUT_MS = 15000
FOR_USER_POLL_S = 0.25
TEXT_POLL_S = 0.3
SCROLL_IDLE_MAX_S = 1.5
MAX_KEY_COMBOS = 16

HISTORY_TARGETS = ("back", "forward", "reload")
DOWNLOAD_NOTE = " The address started a download (see events)."

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

# Called on an element: true if a click at (x, y) lands on it.
HITS_JS = r"""
(el, [x, y]) => {
  const root = el.getRootNode();
  const hit = (root && root.elementFromPoint) ? root.elementFromPoint(x, y) : document.elementFromPoint(x, y);
  if (!hit) return false;
  if (hit === el || el.contains(hit)) return true;
  if (el.tagName === 'LABEL' && el.control && (hit === el.control || el.control.contains(hit))) return true;
  if (hit.tagName === 'LABEL' && hit.control === el) return true;
  return false;
}
"""

# Called on an element that did not become actionable: a reason the agent
# can act on.
DIAGNOSE_JS = r"""
(el) => {
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
  const root = el.getRootNode();
  const hit = (root && root.elementFromPoint) ? root.elementFromPoint(x, y) : document.elementFromPoint(x, y);
  if (hit && hit !== el && !el.contains(hit) && !(hit.tagName === 'LABEL' && hit.control === ctl)) {
    let name = hit.tagName.toLowerCase();
    if (hit.id) name += '#' + hit.id;
    const text = String(hit.innerText || hit.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    const said = text ? ' "' + (text.length > 60 ? text.slice(0, 60) + '…' : text) + '"' : '';
    return 'it is covered by another element (<' + name + '>' + said + '); close or dismiss that first';
  }
  return 'it did not become usable in time (it may be moving or still loading)';
}
"""

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
                f"[MiniBrowser] waiting for the page failed: {first_line(exc)}"
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
        logger.debug(f"[MiniBrowser] settle failed: {first_line(exc)}")
    return False


class NavWatch:
    """Notices main-frame navigations while (and right after) an action runs.

    ``started``: a main-frame navigation request was sent. ``commits``:
    main-frame documents committed (also same-document navigations), not
    counting Chromium error pages, which re-commit while a navigation away
    from them is still pending. ``requests``: XHR / fetch requests sent (a
    form submitted by script). Use as a context manager around the action.
    """

    def __init__(self, page: Any) -> None:
        self._page = page
        self.started = False
        self.commits = 0
        self.requests = 0
        self.urls: List[str] = []
        self._finished = asyncio.Event()
        self._finished.set()

    def __enter__(self) -> "NavWatch":
        self._page.on("request", self._on_request)
        self._page.on("requestfailed", self._on_request_failed)
        self._page.on("framenavigated", self._on_frame_navigated)
        return self

    def __exit__(self, *_exc: Any) -> None:
        for event, handler in (
            ("request", self._on_request),
            ("requestfailed", self._on_request_failed),
            ("framenavigated", self._on_frame_navigated),
        ):
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
        except Exception:
            pass
        if self._is_main_navigation(request):
            self.started = True
            self._finished.clear()

    def _on_request_failed(self, request: Any) -> None:
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

    @property
    def pending(self) -> bool:
        """A navigation was requested and has neither committed nor failed."""
        return not self._finished.is_set()

    async def wait_finished(self, timeout_s: float) -> bool:
        try:
            await asyncio.wait_for(self._finished.wait(), timeout_s)
            return True
        except asyncio.TimeoutError:
            return False


async def after_action(
    page: Any, watch: NavWatch, *, baseline: int = 0, nav_timeout_s: float = NAV_WAIT_S
) -> str:
    """Let the page react to an action; returns a note for the message.

    Waits for the DOM to settle; if the action started a navigation, waits
    for the new document (DOMContentLoaded) and lets it settle too.
    ``baseline`` = commits that happened before the action's own effects.
    """
    interrupted = await settle(page)
    if watch.pending:
        if not await watch.wait_finished(nav_timeout_s):
            return " The next page is still loading."
    if interrupted or watch.commits > baseline:
        if not await _dom_ready(page, nav_timeout_s):
            return " The page is still loading."
        await settle(page)
    return ""


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
    try:
        url = tab.page.url
    except Exception:
        url = getattr(tab, "url", "")
    return {
        "url": url,
        "title": getattr(tab, "title", ""),
        "elements": [],
        "error": f"Could not read the page ({reason}). Try mini_browser_read.",
        "tabs": [],
    }


def _success(message: str, page: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {"status": "success", "message": message}
    result.update(extra)
    result["page"] = page
    return result


# ── elements ────────────────────────────────────────────────────────────────


async def locate(tab: Any, element_id: int) -> Any:
    """Locator for element ``element_id`` of the latest observation."""
    selector = f'[data-mb-id="{int(tab.snapshot_gen)}-{int(element_id)}"]'
    locator = tab.page.locator(selector)
    try:
        count = await asyncio.wait_for(locator.count(), LOCATE_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise MiniBrowserError("MINI_BROWSER_PAGE_UNRESPONSIVE") from None
    except Exception as exc:
        if _is_gone(exc):
            raise MiniBrowserError(
                "MINI_BROWSER_ELEMENT_NOT_FOUND", element_id=element_id
            ) from None
        raise
    if count == 0:
        raise MiniBrowserError("MINI_BROWSER_ELEMENT_NOT_FOUND", element_id=element_id)
    if count > 1:
        # The page cloned a tagged node (carousels do). Prefer a visible copy.
        logger.debug(f"[MiniBrowser] element {element_id} matched {count} nodes")
        return locator.filter(visible=True).first
    return locator


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
    try:
        return bool(await locator.evaluate(HITS_JS, [x, y], timeout=2000))
    except Exception:
        return False


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
    """
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
    """localhost, *.localhost (Chromium resolves those locally), 127/8, ::1, 0.0.0.0."""
    host = host.strip("[]").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_unspecified


def _is_ui_origin(core: Any, url: str, host: str, port: int) -> bool:
    """True if the URL points at CraftBot's own UI (core.ui_origins()).

    Uses the canonicalising check of ``urls`` and, on top, treats every
    loopback spelling (localhost, 127.x, ::1, 0.0.0.0) as the same host.
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
            host, port = canonical[0].strip("[]"), canonical[1]
    except Exception as exc:
        logger.debug(f"[MiniBrowser] UI origin check fallback: {type(exc).__name__}")
    for origin in origins:
        try:
            parts = urlsplit("//" + origin)
            ui_host, ui_port = (parts.hostname or ""), parts.port
        except ValueError:
            continue
        if ui_port is not None and ui_port != port:
            continue
        if ui_host == host or (_is_loopback(ui_host) and _is_loopback(host)):
            return True
    return False


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
    page: Any, url: str, timeout_ms: int, watch: NavWatch, *, retried: bool = False
) -> str:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        return ""
    except Exception as exc:
        message = _api_message(exc)
        low = message.lower()
        if "download is starting" in low:
            return DOWNLOAD_NOTE
        if _is_pw_timeout(exc):
            if watch.commits:
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
            return (
                " The browser stopped loading this address (it may be a download "
                "or a blocked page; see events)."
            )
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
        if _is_pw_timeout(exc):
            return " The page is still loading."
        raise MiniBrowserError(
            "MINI_BROWSER_NAVIGATION_FAILED", url=action, detail=_api_message(exc)
        ) from None
    if action != "reload" and response is None and page.url == before:
        return f" There is no page to go {action} to in this tab."
    return ""


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
        note += await after_action(page, watch, baseline=watch.commits)
    observation = await page_observation(core, tab)
    where = observation.get("url") or page.url
    title = observation.get("title")
    shown = f"{where}" + (f' ("{title}")' if title else "")
    if note.startswith(DOWNLOAD_NOTE):
        message = f"{DOWNLOAD_NOTE.strip()} The tab still shows {shown}."
    else:
        verb = "Reloaded" if action == "reload" else "Opened"
        message = f"{verb} {shown}.{note}"
    return _success(message, observation)


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
    shown = len(observation.get("elements") or [])
    message = f"Read {observation.get('url') or 'the page'}: {shown} elements"
    if observation.get("elements_truncated"):
        message += f" of {observation.get('element_count')}"
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
        note = await after_action(page, watch)
    what = (
        "Double-clicked"
        if double
        else ("Right-clicked" if button == "right" else "Clicked")
    )
    if button == "middle":
        what = "Middle-clicked"
    return _success(
        f"{what} element {element_id}.{note}", await page_observation(core, tab)
    )


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
        note = await after_action(page, watch)
    return _success(
        f"Moved the pointer over element {element_id}.{note}",
        await page_observation(core, tab),
    )


async def _clear(page: Any, locator: Any, info: Dict[str, Any]) -> None:
    if info.get("tag") in ("INPUT", "TEXTAREA") or info.get("editable"):
        try:
            await locator.fill("", timeout=ACT_TIMEOUT_MS)
            return
        except Exception as exc:
            logger.debug(
                f"[MiniBrowser] clearing with fill failed: {type(exc).__name__}"
            )
    await page.keyboard.press("ControlOrMeta+a")
    await page.keyboard.press("Delete")


async def type_text(
    core: Any,
    tab: Any,
    *,
    element_id: int,
    text: str,
    submit: bool = False,
    clear: bool = True,
) -> Dict[str, Any]:
    """Type into a field like a person (click it, clear it, type, Enter)."""
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
    await wait_actionable(locator, element_id)
    with NavWatch(page) as watch:
        if humanlike_enabled(core):
            await pointer_click(core, tab, locator, element_id)
        if not await _has_focus(locator):
            await _focus(locator, element_id)
            if not await _has_focus(locator):
                raise MiniBrowserError(
                    "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
                    element_id=element_id,
                    detail="it does not take keyboard input (it could not be focused)",
                )
        if clear:
            await _clear(page, locator, info)
        else:
            try:
                moved = await locator.evaluate(CARET_END_JS, timeout=2000)
            except Exception:
                moved = False
            if not moved:
                await page.keyboard.press("End")
        failure = ""
        try:
            await human.type_text(core, tab, text)
            if submit:
                await page.keyboard.press("Enter")
        except Exception as exc:
            # Never echo the exception: its text could contain what was typed.
            failure = type(exc).__name__
        if failure:
            logger.warning(
                f"[MiniBrowser] typing into element {element_id} failed: {failure}"
            )
            raise MiniBrowserError(
                "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
                element_id=element_id,
                detail="typing was interrupted because the page changed",
            )
        note = await after_action(page, watch)
    message = f"Typed {len(text)} characters into element {element_id}"
    if not text and clear:
        message = f"Cleared element {element_id}"
    message += " and pressed Enter." if submit else "."
    return _success(message + note, await page_observation(core, tab))


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
        await _focus(locator, element_id)
    with NavWatch(page) as watch:
        for index, combo in enumerate(combos):
            unknown = ""
            try:
                await page.keyboard.press(combo)
            except Exception as exc:
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
        note = await after_action(page, watch)
    target = f" in element {element_id}" if element_id is not None else ""
    return _success(
        f"Pressed {' '.join(combos)}{target}.{note}", await page_observation(core, tab)
    )


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
        try:
            # The option was verified above; force also covers native selects
            # hidden behind a custom dropdown, and never waits (so a Stop
            # cannot lead to a late selection).
            await locator.select_option(index=index, force=True, timeout=ACT_TIMEOUT_MS)
        except Exception as exc:
            error = await _unusable(locator, element_id, exc)
            raise error from None
        note = await after_action(page, watch)
    label = match.get("label") or value
    return _success(
        f'Selected "{_short(label, 60)}" in element {element_id}.{note}',
        await page_observation(core, tab),
    )


# ── scrolling & waiting ─────────────────────────────────────────────────────


async def _scroll_state(page: Any, x: float, y: float) -> Dict[str, Any]:
    try:
        state = await _evaluate(page, SCROLL_STATE_JS, {"x": x, "y": y})
    except MiniBrowserError:
        raise
    except Exception as exc:
        logger.debug(f"[MiniBrowser] scroll state failed: {first_line(exc)}")
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
    return _success(
        message,
        await page_observation(core, tab),
        scrolled=moved is not None,
        at_bottom=at_bottom,
    )


async def _text_present(page: Any, text: str) -> bool:
    try:
        return bool(await _evaluate(page, TEXT_PRESENT_JS, text))
    except MiniBrowserError:
        return False
    except Exception as exc:
        if not is_context_destroyed(exc):
            logger.debug(f"[MiniBrowser] text check failed: {first_line(exc)}")
        return False


async def wait(
    core: Any,
    tab: Any,
    *,
    seconds: Optional[float] = None,
    text: Optional[str] = None,
    for_user: bool = False,
    timeout_ms: int = 10000,
) -> Dict[str, Any]:
    """Sleep, wait for text to appear, or wait for the user to hand back."""
    page = tab.page
    timeout_s = max(0.0, timeout_ms / 1000.0)
    if for_user:
        if not tab.user_control:
            message = "The user is not controlling this tab; nothing to wait for."
        else:
            deadline = time.monotonic() + timeout_s
            while tab.user_control:
                if time.monotonic() >= deadline:
                    raise MiniBrowserError(
                        "MINI_BROWSER_TIMEOUT",
                        what="Waiting for the user to hand back control",
                        seconds=round(timeout_s),
                    )
                await asyncio.sleep(FOR_USER_POLL_S)
            message = "The user handed control back."
            await settle(page)
    elif text:
        deadline = time.monotonic() + timeout_s
        while not await _text_present(page, text):
            if time.monotonic() >= deadline:
                raise MiniBrowserError(
                    "MINI_BROWSER_TIMEOUT",
                    what=f'Waiting for the text "{_short(text, 60)}"',
                    seconds=round(timeout_s),
                )
            await asyncio.sleep(TEXT_POLL_S)
        message = f'The text "{_short(text, 60)}" is on the page.'
    elif seconds is not None:
        await asyncio.sleep(max(0.0, float(seconds)))
        message = f"Waited {float(seconds):g} s."
    else:
        await settle(page, quiet_ms=500, max_ms=int(min(timeout_s, 10.0) * 1000))
        message = "Waited for the page to settle."
    return _success(message, await page_observation(core, tab))


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
            await chooser.set_files(files, timeout=ACTION_WAIT_MS)
        note = await after_action(page, watch)
    return _success(
        f"Attached {', '.join(names)} to element {element_id}.{note}",
        await page_observation(core, tab),
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
        if not _is_pw_timeout(exc):
            raise
        raise MiniBrowserError(
            "MINI_BROWSER_TIMEOUT",
            what="Taking the screenshot",
            seconds=SCREENSHOT_TIMEOUT_MS // 1000,
        ) from None
    path = await asyncio.to_thread(save_screenshot, tab.owner, data)
    kind = "full-page screenshot" if full_page else "screenshot"
    return _success(
        f"Saved a {kind} to {path}.", await page_observation(core, tab), file_path=path
    )


async def login(
    core: Any, tab: Any, *, username: Optional[str] = None, submit: bool = True
) -> Dict[str, Any]:
    """Sign in with a saved login from the password vault."""
    from app.mini_browser.login import autofill

    return await autofill(core, tab, username=username, submit=submit)


OPS: Dict[str, Op] = {
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
}
