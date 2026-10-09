"""Shared helpers for the Mini Browser agent-operation tests.

- ``FakeCore``: the few BrowserCore members the operations use.
- ``FakeVault``: an in-memory stand-in for the password vault.
- ``BrowserHarness``: one headless Chromium per test module, running on its
  own event-loop thread (like the real Mini Browser host); tests submit
  coroutines with ``harness.run(...)``. ``launch_browser_or_skip`` skips the
  module cleanly when Playwright or Chromium is not installed.
- ``LocalServer``: a tiny threaded HTTP server serving test pages, for real
  navigations (two origins: 127.0.0.1 and localhost).
"""

from __future__ import annotations

import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pytest

from app.mini_browser.types import Tab


class FakeCore:
    def __init__(
        self,
        *,
        humanlike: bool = False,
        show_cursor: bool = True,
        allow_file_urls: bool = False,
        ui_origins: Iterable[str] = (),
        vault: Any = None,
    ) -> None:
        self.settings = SimpleNamespace(
            humanlike=humanlike,
            show_cursor=show_cursor,
            search_url="https://duckduckgo.com/?q={query}",
            allow_file_urls=allow_file_urls,
        )
        self.viewport = (1280, 800)
        self.pointer: List[Tuple[float, float, str]] = []
        self.events: List[Dict[str, Any]] = []
        self._ui_origins = frozenset(ui_origins)
        self._vault = vault

    async def publish_pointer(self, tab: Tab, x: float, y: float, kind: str) -> None:
        self.pointer.append((x, y, kind))

    def add_event(self, tab: Tab, kind: str, message: str, **extra: Any) -> None:
        self.events.append({"kind": kind, "message": message, **extra})

    def vault(self) -> Any:
        return self._vault

    def tabs_payload(self, owner: Optional[str] = None) -> list:
        return [
            {
                "index": 0,
                "id": "t1",
                "url": "",
                "title": "",
                "mine": True,
                "active": True,
            }
        ]

    def ui_origins(self) -> frozenset:
        return self._ui_origins


class FakeVault:
    """candidates_for_url / mark_used / status like app.mini_browser.vault."""

    def __init__(
        self,
        entries: Optional[List[Dict[str, Any]]] = None,
        *,
        unreadable: bool = False,
        hosts: Optional[Iterable[str]] = None,
    ) -> None:
        self.entries = list(entries or [])
        self.unreadable = unreadable
        self.hosts = set(hosts) if hosts is not None else None
        self.used: List[str] = []
        self.asked: List[str] = []

    def candidates_for_url(self, url: str) -> List[Dict[str, Any]]:
        self.asked.append(url)
        if self.unreadable:
            return []
        if self.hosts is not None:
            from urllib.parse import urlsplit

            if (urlsplit(url).hostname or "") not in self.hosts:
                return []
        return [dict(entry) for entry in self.entries]

    def mark_used(self, entry_id: str) -> None:
        self.used.append(entry_id)

    def status(self) -> Dict[str, Any]:
        return {
            "ok": not self.unreadable,
            "unreadable": self.unreadable,
            "count": len(self.entries),
            "protection": "file",
        }


class BrowserHarness:
    """Headless Chromium on a private event-loop thread."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self.loop.run_forever, name="mini-browser-test", daemon=True
        )
        self.thread.start()
        self.playwright: Any = None
        self.browser: Any = None

    def run(self, coro: Any, timeout: float = 90.0) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def call(self, fn: Callable[[], Any], timeout: float = 90.0) -> Any:
        """Run ``await fn()`` on the browser loop."""

        async def runner() -> Any:
            return await fn()

        return self.run(runner(), timeout)

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)

    async def new_tab(
        self,
        html: Optional[str] = None,
        *,
        url: Optional[str] = None,
        viewport: Tuple[int, int] = (1280, 800),
        owner: str = "sess",
    ) -> Tab:
        context = await self.browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}
        )
        context.set_default_timeout(15000)
        page = await context.new_page()
        if url:
            await page.goto(url, wait_until="domcontentloaded")
        elif html is not None:
            await page.set_content(html)
        return Tab(id="t1", page=page, owner=owner)

    async def close_tab(self, tab: Tab) -> None:
        try:
            await tab.page.context.close()
        except Exception:
            pass

    async def _stop(self) -> None:
        if self.browser is not None:
            await self.browser.close()
        if self.playwright is not None:
            await self.playwright.stop()

    def close(self) -> None:
        try:
            self.run(self._stop(), timeout=30)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=10)


def launch_browser_or_skip() -> BrowserHarness:
    pytest.importorskip("playwright.async_api")
    harness = BrowserHarness()
    try:
        harness.run(harness.start(), timeout=120)
    except Exception as exc:  # Chromium not installed, sandbox issues, ...
        harness.close()
        pytest.skip(f"Chromium is not available: {str(exc).splitlines()[0][:200]}")
    return harness


# status, content type, body, delay (s), extra headers
Route = Tuple[int, str, str, float, Dict[str, str]]


class LocalServer:
    """Serves ``routes[path] = (status, content_type, body, delay, headers)``."""

    def __init__(self) -> None:
        self.routes: Dict[str, Route] = {}
        self.posts: List[Tuple[str, str]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                path = self.path.split("?", 1)[0]
                status, ctype, body, delay, headers = server.routes.get(
                    path,
                    (404, "text/html", "<title>Not found</title>not found", 0.0, {}),
                )
                if delay:
                    time.sleep(delay)
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", f"{ctype}; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802 (http.server API)
                self._serve()

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                server.posts.append(
                    (self.path, self.rfile.read(length).decode("utf-8"))
                )
                self._serve()

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path: str = "/", host: str = "127.0.0.1") -> str:
        return f"http://{host}:{self.port}{path}"

    def add(
        self,
        path: str,
        body: str,
        *,
        status: int = 200,
        ctype: str = "text/html",
        delay: float = 0.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> str:
        self.routes[path] = (status, ctype, body, delay, dict(headers or {}))
        return self.url(path)

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
