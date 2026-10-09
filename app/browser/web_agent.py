"""
Web Agent session — a real Chromium browser the agent drives.

This is distinct from ``app/browser/interface.py`` (which is the *CraftBot web
UI* served to the user). Here, "browser" means an actual Playwright Chromium
instance that the agent navigates, clicks, types into, and reads — so the user
can ask the agent to "browse X" or "buy Y" and watch it happen.

Design notes
------------
* A single module-level :class:`WebAgentSession` is reused across every browser
  action within a process (actions are stateless and only get ``input_data``,
  so the live page must live at module scope — see the action framework).
* Control is **accessibility-tree based**: :meth:`snapshot` tags every visible
  interactive element with a ``data-cb-id`` attribute and returns a numbered
  list. The agent then acts by element id (``click(3)``), which is far more
  robust than guessing CSS selectors or clicking pixel coordinates.
* After every action the current screenshot (plus URL + title) is streamed to
  the React "Web Agent" panel over the existing WebSocket via the UI adapter,
  so the user sees the browser live.

The whole module is import-safe even when Playwright's browsers aren't
installed — the error only surfaces when an action actually runs.
"""

from __future__ import annotations

import asyncio
import base64
import os
from typing import Any, Dict, List, Optional

from app.logger import logger

# JavaScript injected into the page to tag and enumerate interactive elements.
# Each match gets a stable ``data-cb-id`` so a later click/type can target it by
# id. We keep only on-screen, non-tiny, visible elements to limit noise.
_SNAPSHOT_JS = r"""
() => {
  const SEL = 'a, button, input, textarea, select, summary, ' +
    '[role=button], [role=link], [role=tab], [role=menuitem], ' +
    '[role=textbox], [role=checkbox], [role=radio], [role=combobox], ' +
    '[onclick], [contenteditable=""], [contenteditable=true]';
  const out = [];
  let id = 0;
  const seen = new Set();
  for (const el of document.querySelectorAll(SEL)) {
    if (seen.has(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') continue;
    // Must be at least partially inside the viewport.
    if (r.bottom < 0 || r.right < 0 || r.top > window.innerHeight || r.left > window.innerWidth) continue;
    seen.add(el);
    el.setAttribute('data-cb-id', String(id));
    const label = (
      el.getAttribute('aria-label') ||
      el.getAttribute('placeholder') ||
      (el.innerText || el.value || el.getAttribute('title') || el.getAttribute('name') || '')
    ).replace(/\s+/g, ' ').trim().slice(0, 80);
    out.push({
      id,
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || el.getAttribute('role') || '').toLowerCase(),
      text: label,
    });
    id += 1;
  }
  return out;
}
"""


# Injected into every page so the agent's actions look like a real person using
# the browser: a cursor that glides to the target and a click "ripple". It lives
# in the page DOM, so it shows up naturally in the streamed screenshots.
_CURSOR_JS = r"""
() => {
  if (window.__cbCursor) return;
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">' +
    '<path d="M4 2 L4 20 L9 15 L12 22 L15.5 20.5 L12.5 14 L19 14 Z" ' +
    'fill="white" stroke="black" stroke-width="1.3" stroke-linejoin="round"/></svg>';
  const c = document.createElement('div');
  c.id = '__cb_cursor';
  c.style.cssText = [
    'position:fixed', 'left:-100px', 'top:-100px', 'width:24px', 'height:24px',
    'z-index:2147483647', 'pointer-events:none',
    'transition:left .30s cubic-bezier(.22,.61,.36,1),top .30s cubic-bezier(.22,.61,.36,1)',
    'background-image:url("data:image/svg+xml;utf8,' + encodeURIComponent(svg) + '")',
    'background-size:contain', 'background-repeat:no-repeat',
    'filter:drop-shadow(0 1px 2px rgba(0,0,0,.55))'
  ].join(';');
  (document.body || document.documentElement).appendChild(c);
  window.__cbCursor = {
    move(x, y) { c.style.left = x + 'px'; c.style.top = y + 'px'; },
    click() {
      const x = parseFloat(c.style.left) || 0, y = parseFloat(c.style.top) || 0;
      const r = document.createElement('div');
      r.style.cssText =
        'position:fixed;left:' + x + 'px;top:' + y + 'px;width:26px;height:26px;' +
        'border-radius:50%;border:2px solid rgba(0,130,255,.95);z-index:2147483646;' +
        'pointer-events:none;transform:translate(-13px,-13px) scale(.25);opacity:.95;' +
        'transition:transform .45s ease-out,opacity .45s ease-out;';
      (document.body || document.documentElement).appendChild(r);
      requestAnimationFrame(() => {
        r.style.transform = 'translate(-13px,-13px) scale(1.7)';
        r.style.opacity = '0';
      });
      setTimeout(() => r.remove(), 480);
    }
  };
}
"""


# Ad / tracker networks blocked when the built-in ad blocker is on. Kept to
# clear ad/analytics networks so we don't break site logins or core features.
_ADBLOCK_DOMAINS = {
    "doubleclick.net", "googlesyndication.com", "googleadservices.com",
    "google-analytics.com", "googletagservices.com", "adservice.google.com",
    "amazon-adsystem.com", "adnxs.com", "adsafeprotected.com",
    "scorecardresearch.com", "taboola.com", "outbrain.com", "criteo.com",
    "criteo.net", "pubmatic.com", "rubiconproject.com", "openx.net",
    "moatads.com", "2mdn.net", "adform.net", "casalemedia.com", "quantserve.com",
    "zedo.com", "yieldmo.com", "doubleverify.com", "teads.tv",
    "smartadserver.com", "3lift.com", "bidswitch.net", "sharethrough.com",
    "gumgum.com", "indexww.com", "adcolony.com", "applovin.com", "mgid.com",
}


class WebAgentSession:
    """A persistent Playwright Chromium page the agent operates on."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._lock = asyncio.Lock()
        # Background task that streams frames continuously so the live view
        # feels smooth (page loads, animations, the user's own clicks) instead
        # of only updating after an agent action.
        self._pump_task: Any = None
        self._viewport = {"width": 1280, "height": 800}
        # When True, logins/cookies are stored in a persistent on-disk profile
        # so the user stays signed in across restarts (real-browser behaviour).
        # Show a moving cursor + typing animation so agent actions look human.
        self._show_cursor = os.getenv("WEB_AGENT_SHOW_CURSOR", "True").lower() not in (
            "0", "false", "no",
        )
        # Built-in ad/tracker blocker (toggleable from the UI).
        self._adblock_enabled = os.getenv("WEB_AGENT_ADBLOCK", "True").lower() not in (
            "0", "false", "no",
        )

    # ── lifecycle ────────────────────────────────────────────────────────────

    @property
    def is_started(self) -> bool:
        return self._page is not None

    async def ensure_started(self) -> None:
        """Lazily launch Chromium. Safe to call repeatedly."""
        if self._page is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "Playwright is not installed. Run `pip install playwright` "
                "and `playwright install chromium`."
            ) from exc

        headless = os.getenv("WEB_AGENT_HEADLESS", "True").lower() not in (
            "0",
            "false",
            "no",
        )
        # device_scale_factor renders the page at higher resolution (crisper but
        # heavier to encode/stream). 1.0 keeps the live view fast; bump via env
        # WEB_AGENT_SCALE for sharpness at the cost of speed.
        scale = float(os.getenv("WEB_AGENT_SCALE", "1.0"))
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        self._playwright = await async_playwright().start()
        try:
            # Persistent context = a real on-disk Chrome profile. Logins,
            # cookies and sessions survive restarts, so the user (or the agent)
            # can sign in to accounts once and stay signed in.
            self._context = await self._playwright.chromium.launch_persistent_context(
                self._profile_dir(),
                headless=headless,
                viewport=dict(self._viewport),
                device_scale_factor=scale,
                user_agent=user_agent,
                accept_downloads=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as exc:  # browser binary missing, profile locked, etc.
            await self._teardown()
            raise RuntimeError(
                f"Failed to launch Chromium: {exc}. "
                "You may need to run `playwright install chromium`."
            ) from exc
        # Inject the human-like cursor into every page that loads.
        if self._show_cursor:
            try:
                await self._context.add_init_script(f"({_CURSOR_JS})()")
            except Exception as exc:
                logger.debug("[WebAgent] cursor init script failed: %s", exc)

        # Built-in ad blocker: intercept every request and abort ad/tracker
        # domains while enabled. The handler checks the flag live, so the toggle
        # works without re-registering.
        try:
            await self._context.route("**/*", self._route_handler)
        except Exception as exc:
            logger.debug("[WebAgent] adblock route failed: %s", exc)
        # Follow popups / new tabs (OAuth & login flows open these) by streaming
        # whichever page is frontmost.
        self._context.on("page", self._on_new_page)
        existing = self._context.pages
        self._page = existing[0] if existing else await self._context.new_page()
        self._track_page(self._page)
        self._start_pump()
        logger.info("[WebAgent] Chromium persistent profile launched (headless=%s)", headless)

    def _profile_dir(self) -> str:
        """Directory holding the persistent browser profile (logins/cookies)."""
        try:
            from app.config import APP_DATA_PATH

            base = APP_DATA_PATH
        except Exception:
            from app.config import AGENT_WORKSPACE_ROOT

            base = AGENT_WORKSPACE_ROOT
        path = os.path.join(str(base), "web_agent_profile")
        os.makedirs(path, exist_ok=True)
        return path

    def _on_new_page(self, page: Any) -> None:
        """A popup/new tab opened — make it the active (streamed) page."""
        logger.info("[WebAgent] new tab/popup opened: %s", getattr(page, "url", "?"))
        self._page = page
        self._track_page(page)
        self._schedule_tabs()

    def _track_page(self, page: Any) -> None:
        """When a page closes, fall back to another open page."""

        def _on_close(_=None) -> None:
            try:
                pages = [p for p in self._context.pages if not p.is_closed()]
            except Exception:
                pages = []
            if self._page is page or self._page is None or self._page.is_closed():
                self._page = pages[-1] if pages else None

        try:
            page.on("close", _on_close)
        except Exception:
            pass

    async def close(self) -> None:
        """Tear down the browser and reset to an unstarted state."""
        async with self._lock:
            await self._teardown()

    async def _teardown(self) -> None:
        if self._pump_task is not None:
            self._pump_task.cancel()
            self._pump_task = None
        for closer in (
            getattr(self._context, "close", None),
            getattr(self._browser, "close", None),
            getattr(self._playwright, "stop", None),
        ):
            if closer is None:
                continue
            try:
                result = closer()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # best-effort cleanup
                pass
        self._playwright = self._browser = self._context = self._page = None

    # ── streaming ────────────────────────────────────────────────────────────

    async def _stream_frame(self) -> None:
        """Push the current page screenshot to the Web Agent panel (best-effort)."""
        from app.internal_action_interface import InternalActionInterface

        adapter = InternalActionInterface.ui_adapter
        if adapter is None or not hasattr(adapter, "_broadcast") or self._page is None:
            return
        try:
            quality = int(os.getenv("WEB_AGENT_QUALITY", "70"))
            png = await self._page.screenshot(type="jpeg", quality=quality, full_page=False)
            b64 = base64.b64encode(png).decode("ascii")
            await adapter._broadcast(
                {
                    "type": "browser_frame",
                    "data": {
                        "image": f"data:image/jpeg;base64,{b64}",
                        "url": self._page.url,
                        "title": await self._page.title(),
                    },
                }
            )
        except Exception as exc:  # streaming must never break an action
            logger.debug("[WebAgent] frame stream failed: %s", exc)

    def _schedule_frame(self) -> None:
        """Stream a frame in the background so the caller doesn't wait on it.

        Used by agent actions: the screenshot/encode/send happens off the
        action's critical path (it re-acquires the lock), so the agent gets the
        result and can think about its next step without waiting for pixels.
        """
        async def _runner() -> None:
            async with self._lock:
                await self._stream_frame()

        try:
            asyncio.ensure_future(_runner())
        except RuntimeError:
            pass

    async def _ensure_cursor(self) -> None:
        """Make sure the virtual cursor element exists on the current page.

        The init-script path can miss (it runs before <body> exists), so we also
        (idempotently) inject after load — the script no-ops if already present.
        """
        if not self._show_cursor or self._page is None:
            return
        try:
            await self._page.evaluate(_CURSOR_JS)
        except Exception:
            pass

    async def _cursor_to(self, x: float, y: float, *, settle: float = 0.32) -> None:
        """Glide the virtual cursor to (x, y) and let the live view show it move."""
        if not self._show_cursor or self._page is None:
            return
        await self._ensure_cursor()
        try:
            await self._page.evaluate(
                "([x,y]) => { if (!window.__cbCursor) return;"
                " window.__cbCursor.move(x,y); }",
                [x, y],
            )
            await asyncio.sleep(settle)  # let the CSS glide play out
            await self._stream_frame()
        except Exception as exc:
            logger.debug("[WebAgent] cursor move failed: %s", exc)

    async def _cursor_click_fx(self) -> None:
        """Play the click ripple where the cursor is."""
        if not self._show_cursor or self._page is None:
            return
        try:
            await self._page.evaluate(
                "() => { if (window.__cbCursor) window.__cbCursor.click(); }"
            )
            await self._stream_frame()
        except Exception as exc:
            logger.debug("[WebAgent] cursor click fx failed: %s", exc)

    async def _cursor_to_element(self, selector: str) -> None:
        """Scroll an element into view and move the cursor onto its centre."""
        if not self._show_cursor or self._page is None:
            return
        try:
            el = await self._page.query_selector(selector)
            if el is None:
                return
            await el.scroll_into_view_if_needed(timeout=3000)
            box = await el.bounding_box()
            if box:
                await self._cursor_to(
                    box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                )
        except Exception as exc:
            logger.debug("[WebAgent] cursor-to-element failed: %s", exc)

    def _start_pump(self) -> None:
        """Start the continuous frame pump on the current event loop."""
        if self._pump_task is not None:
            return
        try:
            self._pump_task = asyncio.ensure_future(self._pump_loop())
        except RuntimeError:
            # No running loop (shouldn't happen — we're always called from one).
            self._pump_task = None

    async def _pump_loop(self) -> None:
        """Stream a frame ~2x/sec while the page is alive and a client is watching."""
        interval = float(os.getenv("WEB_AGENT_STREAM_INTERVAL", "0.5"))
        from app.internal_action_interface import InternalActionInterface

        while True:
            try:
                await asyncio.sleep(interval)
                if self._page is None:
                    continue
                adapter = InternalActionInterface.ui_adapter
                # Only spend cycles when someone is actually viewing.
                if adapter is None or not getattr(adapter, "_ws_clients", None):
                    continue
                # Serialise with actions so we never screenshot mid-operation.
                async with self._lock:
                    await self._stream_frame()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("[WebAgent] pump tick failed: %s", exc)

    # ── responsive viewport + direct user control ────────────────────────────

    async def set_viewport(self, width: int, height: int) -> None:
        """Resize the page to match the panel so the view fills it (no black bars)."""
        w = max(400, min(int(width), 2400))
        h = max(300, min(int(height), 1600))
        if (w, h) == (self._viewport["width"], self._viewport["height"]):
            return
        self._viewport = {"width": w, "height": h}
        if self._page is None:
            return
        async with self._lock:
            try:
                await self._page.set_viewport_size(self._viewport)
                await self._stream_frame()
            except Exception as exc:
                logger.debug("[WebAgent] set_viewport failed: %s", exc)

    async def user_input(self, event: Dict[str, Any]) -> None:
        """Apply a direct user interaction (click/scroll/type/key) to the page.

        Coordinates arrive normalised (0..1 of the displayed view) so they map
        correctly regardless of the panel/viewport size. This is what lets the
        *human* click 'Dismiss', type in a field, or scroll — alongside the agent.
        """
        await self.ensure_started()
        page = self._page
        kind = event.get("kind")
        vw = self._viewport["width"]
        vh = self._viewport["height"]
        async with self._lock:
            try:
                if kind in ("click", "dblclick"):
                    x = float(event.get("nx", 0)) * vw
                    y = float(event.get("ny", 0)) * vh
                    if kind == "dblclick":
                        await page.mouse.dblclick(x, y)
                    else:
                        await page.mouse.click(x, y)
                elif kind == "scroll":
                    x = float(event.get("nx", 0.5)) * vw
                    y = float(event.get("ny", 0.5)) * vh
                    await page.mouse.move(x, y)
                    await page.mouse.wheel(0, float(event.get("dy", 0)))
                elif kind == "key":
                    key = str(event.get("key", ""))
                    if not key:
                        return
                    # Single printable char → type it; named key → press it.
                    if len(key) == 1:
                        await page.keyboard.type(key)
                    else:
                        await page.keyboard.press(key)
                elif kind == "type":
                    await page.keyboard.type(str(event.get("text", "")))
                else:
                    return
                await self._stream_frame()
            except Exception as exc:
                logger.debug("[WebAgent] user_input (%s) failed: %s", kind, exc)

    # ── primitives the actions wrap ──────────────────────────────────────────

    async def navigate(self, target: str, timeout_ms: int = 30000) -> Dict[str, Any]:
        """Go to a URL, or one of the special targets back/forward/reload."""
        async with self._lock:
            await self.ensure_started()
            page = self._page
            cmd = (target or "").strip()
            low = cmd.lower()
            try:
                if low in ("back", "forward", "reload"):
                    if low == "back":
                        await page.go_back(timeout=timeout_ms)
                    elif low == "forward":
                        await page.go_forward(timeout=timeout_ms)
                    else:
                        await page.reload(timeout=timeout_ms)
                else:
                    url = cmd
                    if not url.startswith(("http://", "https://", "about:", "file://")):
                        url = "https://" + url
                    await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                await self._ensure_cursor()
                self._schedule_frame()
                self._schedule_tabs()
                return {
                    "status": "success",
                    "url": page.url,
                    "title": await page.title(),
                    "message": f"Navigated to {page.url}",
                }
            except Exception as exc:
                self._schedule_frame()
                return {"status": "error", "message": str(exc)}

    async def snapshot(self, max_text_chars: int = 2000) -> Dict[str, Any]:
        """Return the interactive-element list + visible page text.

        Kept deliberately compact: a smaller observation means a smaller prompt
        for the agent's next LLM step, which is the main thing that keeps the
        loop fast and cheap.
        """
        async with self._lock:
            await self.ensure_started()
            page = self._page
            try:
                elements: List[Dict[str, Any]] = await page.evaluate(_SNAPSHOT_JS)
                # Cap the element list so very dense pages don't bloat the prompt.
                if len(elements) > 60:
                    elements = elements[:60]
                try:
                    text = await page.inner_text("body")
                except Exception:
                    text = ""
                text = " ".join(text.split())
                truncated = len(text) > max_text_chars
                self._schedule_frame()
                return {
                    "status": "success",
                    "url": page.url,
                    "title": await page.title(),
                    "elements": elements,
                    "element_count": len(elements),
                    "page_text": text[:max_text_chars],
                    "page_text_truncated": truncated,
                }
            except Exception as exc:
                return {"status": "error", "message": str(exc)}

    async def click(self, element_id: int, timeout_ms: int = 10000) -> Dict[str, Any]:
        async with self._lock:
            await self.ensure_started()
            page = self._page
            selector = f'[data-cb-id="{int(element_id)}"]'
            try:
                # Glide the cursor onto the target and ripple — looks human.
                await self._cursor_to_element(selector)
                await self._cursor_click_fx()
                await page.click(selector, timeout=timeout_ms)
                # Let any navigation / DOM update settle before we snapshot.
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
                self._schedule_frame()
                return {
                    "status": "success",
                    "url": page.url,
                    "title": await page.title(),
                    "message": f"Clicked element {element_id}",
                }
            except Exception as exc:
                self._schedule_frame()
                return {
                    "status": "error",
                    "message": (
                        f"Could not click element {element_id}: {exc}. "
                        "Call browser_read to refresh the element list — ids change "
                        "after navigation."
                    ),
                }

    async def type_text(
        self,
        element_id: int,
        text: str,
        submit: bool = False,
        clear: bool = True,
        timeout_ms: int = 10000,
    ) -> Dict[str, Any]:
        async with self._lock:
            await self.ensure_started()
            page = self._page
            sel = f'[data-cb-id="{int(element_id)}"]'
            try:
                # Move the cursor to the field and click it, like a person would.
                await self._cursor_to_element(sel)
                await self._cursor_click_fx()
                await page.click(sel, timeout=timeout_ms)  # focus the field
                if clear:
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Delete")
                # Type in a few chunks, streaming between them, so the live view
                # shows the text appearing letter by letter (human-like).
                delay = int(os.getenv("WEB_AGENT_TYPE_DELAY", "22"))
                chunk = max(1, (len(text) + 5) // 6)
                for i in range(0, len(text), chunk):
                    await page.keyboard.type(text[i:i + chunk], delay=delay)
                    await self._stream_frame()
                if submit:
                    await page.press(sel, "Enter")
                    try:
                        await page.wait_for_load_state(
                            "domcontentloaded", timeout=5000
                        )
                    except Exception:
                        pass
                self._schedule_frame()
                return {
                    "status": "success",
                    "url": page.url,
                    "title": await page.title(),
                    "message": f"Typed into element {element_id}"
                    + (" and submitted" if submit else ""),
                }
            except Exception as exc:
                self._schedule_frame()
                return {
                    "status": "error",
                    "message": (
                        f"Could not type into element {element_id}: {exc}. "
                        "Call browser_read to refresh the element list."
                    ),
                }

    async def login(
        self, site: Optional[str] = None, submit: bool = True
    ) -> Dict[str, Any]:
        """Fill the current page's login form from the saved credential vault.

        The password is typed straight into the field and is NEVER returned, so
        it can't leak into the LLM prompt or logs. Returns only the username.
        """
        from app.browser.credential_vault import get_vault, normalize_domain

        async with self._lock:
            await self.ensure_started()
            page = self._page
            domain = site or page.url
            cred = get_vault().get_for_domain(domain)
            if not cred:
                return {
                    "status": "error",
                    "message": (
                        f"No saved login for '{normalize_domain(domain)}'. "
                        "Ask the user to add it in the Passwords panel."
                    ),
                }
            try:
                # Password field.
                pw_el = await page.query_selector("input[type='password']:visible")
                if pw_el is None:
                    pw_el = await page.query_selector("input[type='password']")
                if pw_el is None:
                    return {
                        "status": "error",
                        "message": (
                            "No password field on this page. Navigate to the "
                            "site's login/sign-in page first, then call browser_login."
                        ),
                    }
                # Username / email field (best-effort).
                user_el = await page.query_selector(
                    ", ".join(
                        [
                            "input[autocomplete='username']:visible",
                            "input[type='email']:visible",
                            "input[name*='user' i]:visible",
                            "input[name*='email' i]:visible",
                            "input[id*='user' i]:visible",
                            "input[id*='email' i]:visible",
                            "input[type='text']:visible",
                        ]
                    )
                )
                if user_el is not None and cred.get("username"):
                    await user_el.fill(cred["username"])
                await pw_el.fill(cred.get("password", ""))
                if submit:
                    await pw_el.press("Enter")
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        pass
                self._schedule_frame()
                return {
                    "status": "success",
                    "site": cred.get("site", ""),
                    "username": cred.get("username", ""),
                    "url": page.url,
                    "message": (
                        f"Filled saved login for {cred.get('username', '')}"
                        + (" and submitted." if submit else ".")
                    ),
                }
            except Exception as exc:
                self._schedule_frame()
                return {"status": "error", "message": str(exc)}

    async def scroll(self, direction: str = "down", amount: int = 600) -> Dict[str, Any]:
        async with self._lock:
            await self.ensure_started()
            page = self._page
            try:
                dy = amount if direction == "down" else -amount
                if direction in ("top", "bottom"):
                    dy = 0
                    await page.evaluate(
                        "(d) => window.scrollTo(0, d === 'bottom' "
                        "? document.body.scrollHeight : 0)",
                        direction,
                    )
                else:
                    await page.evaluate("(y) => window.scrollBy(0, y)", dy)
                self._schedule_frame()
                return {
                    "status": "success",
                    "url": page.url,
                    "message": f"Scrolled {direction}",
                }
            except Exception as exc:
                return {"status": "error", "message": str(exc)}

    async def screenshot(self) -> Dict[str, Any]:
        """Save a full screenshot to the workspace and stream a frame."""
        from datetime import datetime
        from app.config import AGENT_WORKSPACE_ROOT

        async with self._lock:
            await self.ensure_started()
            page = self._page
            try:
                ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
                path = os.path.join(AGENT_WORKSPACE_ROOT, f"web_agent_{ts}.png")
                await page.screenshot(path=path, full_page=True)
                await self._stream_frame()
                return {
                    "status": "success",
                    "url": page.url,
                    "title": await page.title(),
                    "file_path": path,
                    "message": f"Saved screenshot to {path}",
                }
            except Exception as exc:
                return {"status": "error", "message": str(exc)}

    # ── ad blocker ────────────────────────────────────────────────────────────

    async def _route_handler(self, route: Any) -> None:
        """Abort requests to ad/tracker domains while the ad blocker is on."""
        try:
            if self._adblock_enabled:
                from urllib.parse import urlparse

                host = (urlparse(route.request.url).hostname or "").lower()
                if any(
                    host == d or host.endswith("." + d) for d in _ADBLOCK_DOMAINS
                ):
                    await route.abort()
                    return
            await route.continue_()
        except Exception:
            try:
                await route.continue_()
            except Exception:
                pass

    async def _broadcast_adblock(self) -> None:
        from app.internal_action_interface import InternalActionInterface

        adapter = InternalActionInterface.ui_adapter
        if adapter is None or not hasattr(adapter, "_broadcast"):
            return
        try:
            await adapter._broadcast(
                {"type": "browser_adblock", "data": {"enabled": self._adblock_enabled}}
            )
        except Exception as exc:
            logger.debug("[WebAgent] adblock broadcast failed: %s", exc)

    async def broadcast_adblock(self) -> None:
        """Public: report the current ad-blocker state to the UI."""
        await self._broadcast_adblock()

    async def set_adblock(self, enabled: bool) -> Dict[str, Any]:
        """Turn the ad blocker on/off and reload the page so it takes effect."""
        self._adblock_enabled = bool(enabled)
        async with self._lock:
            if self._page is not None:
                try:
                    await self._page.reload(
                        wait_until="domcontentloaded", timeout=15000
                    )
                except Exception:
                    pass
                await self._stream_frame()
        await self._broadcast_adblock()
        return {"status": "success", "enabled": self._adblock_enabled}

    # ── tabs ──────────────────────────────────────────────────────────────────

    def _open_pages(self) -> List[Any]:
        if self._context is None:
            return []
        return [p for p in self._context.pages if not p.is_closed()]

    async def _tabs_payload(self) -> List[Dict[str, Any]]:
        tabs = []
        for i, p in enumerate(self._open_pages()):
            try:
                title = await p.title()
            except Exception:
                title = ""
            tabs.append(
                {
                    "index": i,
                    "url": p.url,
                    "title": title or p.url or "New tab",
                    "active": p is self._page,
                }
            )
        return tabs

    async def _broadcast_tabs(self) -> None:
        from app.internal_action_interface import InternalActionInterface

        adapter = InternalActionInterface.ui_adapter
        if adapter is None or not hasattr(adapter, "_broadcast"):
            return
        try:
            await adapter._broadcast(
                {"type": "browser_tabs", "data": {"tabs": await self._tabs_payload()}}
            )
        except Exception as exc:
            logger.debug("[WebAgent] tabs broadcast failed: %s", exc)

    def _schedule_tabs(self) -> None:
        try:
            asyncio.ensure_future(self._broadcast_tabs())
        except RuntimeError:
            pass

    async def list_tabs(self) -> Dict[str, Any]:
        async with self._lock:
            await self.ensure_started()
            tabs = await self._tabs_payload()
        await self._broadcast_tabs()
        return {"status": "success", "tabs": tabs}

    async def new_tab(self, url: Optional[str] = None) -> Dict[str, Any]:
        async with self._lock:
            await self.ensure_started()
            page = await self._context.new_page()
            self._page = page
            self._track_page(page)
            if url and url.strip():
                u = url.strip()
                if not u.startswith(("http://", "https://", "about:", "file://")):
                    u = "https://" + u
                try:
                    await page.goto(u, timeout=30000, wait_until="domcontentloaded")
                except Exception as exc:
                    logger.debug("[WebAgent] new_tab goto failed: %s", exc)
            await self._ensure_cursor()
            await self._stream_frame()
            await self._broadcast_tabs()
            return {"status": "success", "url": page.url, "title": await page.title()}

    async def switch_tab(self, index: int) -> Dict[str, Any]:
        async with self._lock:
            await self.ensure_started()
            pages = self._open_pages()
            if not (0 <= index < len(pages)):
                return {"status": "error", "message": f"No tab at index {index}"}
            self._page = pages[index]
            try:
                await self._page.bring_to_front()
            except Exception:
                pass
            await self._stream_frame()
            await self._broadcast_tabs()
            return {"status": "success", "url": self._page.url}

    async def close_tab(self, index: int) -> Dict[str, Any]:
        async with self._lock:
            await self.ensure_started()
            pages = self._open_pages()
            if not (0 <= index < len(pages)):
                return {"status": "error", "message": f"No tab at index {index}"}
            target = pages[index]
            was_active = target is self._page
            try:
                await target.close()
            except Exception:
                pass
            remaining = self._open_pages()
            if was_active or self._page is None or self._page.is_closed():
                self._page = remaining[-1] if remaining else None
            if self._page is not None:
                await self._stream_frame()
            await self._broadcast_tabs()
            return {"status": "success"}


# Module-level singleton reused by every browser action.
_session: Optional[WebAgentSession] = None


def get_session() -> WebAgentSession:
    global _session
    if _session is None:
        _session = WebAgentSession()
    return _session
