"""Mini Browser engine: regression tests for the review findings.

One test (or a few) per finding, named after it. Real headless Chromium
against a local ``http.server`` (no internet); agent operations are FAKE ops
(the real ones are tested with the ops), the UI is a fake sink, every path
points into a temp directory. Chromium tests skip when Playwright or its
Chromium is missing.
"""

from __future__ import annotations

import asyncio
import collections
import json
import os
import re
import statistics
import sys
import threading
import time
import types
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

import pytest

import app.mini_browser as mini_browser_package
from app.mini_browser import bridge, config, errors, lifecycle
from app.mini_browser import core as core_module
from app.mini_browser import host as host_module
from app.mini_browser.config import MiniBrowserSettings
from app.mini_browser.core import BrowserCore
from app.mini_browser.errors import MiniBrowserError
from app.mini_browser.host import MiniBrowserHost

SECRET = "a*b~c d!é€Zq9"  # '*', '~', space, non-ASCII: every encoding differs
SLOW_S = 8.0


def run(coro, timeout: float = 90.0):
    async def bounded():
        return await asyncio.wait_for(coro, timeout)

    return asyncio.run(bounded())


async def _apply(fn, core):
    return fn(core)


@pytest.fixture(autouse=True)
def _fresh_lifecycle_records():
    lifecycle._reset_for_tests()
    yield
    lifecycle._reset_for_tests()


def _fake_agent_runtime(
    monkeypatch, sessions: Dict[str, Any], subagents: Dict[str, Any]
):
    class Manager:
        def __init__(self, items):
            self.items = items

        def get(self, key):
            return self.items.get(key)

    class InternalActionInterface:
        session_manager = Manager(sessions)
        subagent_manager = Manager(subagents)

    module = types.ModuleType("app.internal_action_interface")
    module.InternalActionInterface = InternalActionInterface
    monkeypatch.setitem(sys.modules, "app.internal_action_interface", module)


# ═════════════════════════════════════════════════════════════════════════════
# Pure tests (no browser)
# ═════════════════════════════════════════════════════════════════════════════


def _form_encode(text: str, charset: str = "utf-8") -> str:
    """WHATWG application/x-www-form-urlencoded, as Chromium submits a form."""
    safe = set(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789*-._")
    out = []
    for byte in text.encode(charset):
        if byte in safe:
            out.append(chr(byte))
        elif byte == 0x20:
            out.append("+")
        else:
            out.append(f"%{byte:02X}")
    return "".join(out)


@pytest.mark.parametrize(
    "spelled",
    [
        SECRET,
        _form_encode(SECRET),  # Chromium, UTF-8 page
        re.sub("%[0-9A-F]{2}", lambda m: m.group(0).lower(), _form_encode(SECRET)),
        _form_encode("pässwörd€1", "cp1252"),  # Chromium, page without charset
        quote(SECRET, safe=""),
        quote(SECRET, safe="!*'()"),  # encodeURIComponent
        quote(SECRET, safe="!*'();/?:@&=+$,#"),  # encodeURI
        "a*b~c&#x20;",  # not a spelling: a different value
    ],
)
def test_scrub_masks_encoded_secrets(spelled):
    """end-to-end SEC-1 / C9: a secret leaks form-urlencoded via a GET sign-in."""
    secrets = [SECRET, "pässwörd€1"]
    url = f"http://intranet.example/done?user=alice%40example.test&pass={spelled}&x=1"
    out = errors.scrub(url, secrets)
    if spelled == "a*b~c&#x20;":
        assert out == url
        return
    assert spelled not in out
    assert "pass=[redacted]&x=1" in out
    assert "user=alice%40example.test" in out  # nothing else is touched


def test_scrub_masks_html_and_json_escaped_secrets():
    secret = 'x<y>"z&q1'
    import html

    for text in (
        html.escape(secret),
        json.dumps(secret)[1:-1],
        f"<input value='{html.escape(secret)}'>",
    ):
        assert html.escape(secret) not in errors.scrub(text, [secret])
        assert "[redacted]" in errors.scrub(text, [secret])
    data = {"page": {"tabs": [{"url": f"https://x/?p={_form_encode(SECRET)}"}]}}
    assert SECRET not in str(errors.scrub_data(data, [SECRET]))
    assert _form_encode(SECRET) not in str(errors.scrub_data(data, [SECRET]))
    # Short secrets are still never masked (they would blank common text).
    assert errors.scrub("ab and ab", ["ab"]) == "ab and ab"


def test_error_details_are_not_mangled_by_the_codebook():
    """agent-effectiveness ERR-1 / C9: URLs and e-mails in details survive."""
    error = errors.action_error(
        "MINI_BROWSER_LOGIN_FAILED", detail="No account for jo@example.com"
    )
    assert error["message"] == "No account for jo@example.com"
    nav = errors.action_error(
        "MINI_BROWSER_NAVIGATION_FAILED",
        url="http://nonexistent.invalid/",
        detail="net::ERR_NAME_NOT_RESOLVED",
    )
    assert "http://nonexistent.invalid/" in nav["message"]
    assert "REDACTED" not in nav["message"]
    ui = errors.ui_error("MINI_BROWSER_NAVIGATION_FAILED", url="https://a.example/x")
    assert "https://a.example/x" in ui["message"]
    # Secrets are still masked.
    leak = errors.action_error(
        "MINI_BROWSER_INTERNAL", secrets=["hunter22"], detail="pw hunter22"
    )
    assert "hunter22" not in leak["message"]


def test_new_error_codes():
    closed = errors.ui_error("MINI_BROWSER_CLOSED")
    assert closed["title"] == "Browser closed"
    assert closed["message"].startswith("The Mini Browser was closed (by the user,")
    assert errors.ERROR_SPECS["MINI_BROWSER_CLOSED"][:2] == ("not_found", "warning")
    for code in ("MINI_BROWSER_TAB_CLOSED", "MINI_BROWSER_USER_TAB"):
        assert code in errors.ERROR_SPECS
        assert "{" not in errors.action_error(code, tab=3)["message"]


def test_safe_filename_strips_bidi_and_flags_executables():
    """frontend FE-1 / end-to-end SEC-2: names cannot disguise their type."""
    disguised = "invoice\u202efdp.exe"
    name = core_module._safe_filename(disguised)
    assert name == "invoicefdp.exe"
    for control in ("\u061c", "\u200e", "\u200f", "\u202a", "\u2066", "\u2069"):
        assert control not in core_module._safe_filename(f"a{control}b.txt")
    assert core_module._is_dangerous_file(name)
    for dangerous in (
        "setup.EXE",
        "x.msi",
        "run.bat",
        "a.ps1",
        "s.js",
        "l.lnk",
        "d.iso",
        "m.docm",
    ):
        assert core_module._is_dangerous_file(dangerous), dangerous
    for inert in ("report.pdf", "photo.jpg", "data.csv", "notes.txt", "noext"):
        assert not core_module._is_dangerous_file(inert), inert


def test_download_source_locality():
    local = core_module._is_local_source
    assert local("http://127.0.0.1:8000/a.exe", "")
    assert local("http://localhost:8000/a.exe", "")
    assert local("http://[::ffff:127.0.0.1]:8000/a.exe", "")
    assert local("blob:http://localhost:3000/uuid", "")
    assert local("data:application/octet-stream;base64,AA==", "http://127.0.0.1/x")
    assert not local("https://downloads.example/a.exe", "")
    assert not local(
        "data:application/octet-stream;base64,AA==", "https://evil.example/"
    )
    assert not local("blob:https://evil.example/uuid", "")


@pytest.mark.skipif(sys.platform != "win32", reason="Mark-of-the-Web is Windows only")
def test_mark_of_the_web_stream(tmp_path):
    path = tmp_path / "setup.exe"
    path.write_bytes(b"MZ")
    core_module._write_mark_of_the_web(
        path, "https://site.example/page", "https://dl.example/setup.exe\r\nZoneId=0"
    )
    text = Path(f"{path}:Zone.Identifier").read_text(encoding="utf-8")
    assert text.splitlines()[:2] == ["[ZoneTransfer]", "ZoneId=3"]
    assert "ReferrerUrl=https://site.example/page" in text
    assert "HostUrl=https://dl.example/setup.exeZoneId=0" in text  # no injected line
    assert "ZoneId=0" not in text.splitlines()


def test_lifecycle_records_survive_without_a_host(monkeypatch):
    """concurrency CONC-3: hooks before the browser thread starts are kept."""
    monkeypatch.setattr(host_module, "_host", None)
    lifecycle.on_run_state("chat-a", "running")
    lifecycle.cancel_owner("chat-a")
    assert lifecycle.is_run_busy("chat-a")
    assert isinstance(lifecycle.parent_stop("chat-a"), datetime)
    lifecycle.on_run_state("chat-a", "idle")
    assert not lifecycle.is_run_busy("chat-a")
    lifecycle.on_run_state("chat-b", "stopping")
    lifecycle.release_owner("chat-b")
    assert lifecycle.run_state("chat-b") is None
    assert host_module._host is None  # nothing started


def test_unavailable_reason_follows_launch_results():
    """C6: unavailable_reason() after a failure, None after a launch."""
    assert lifecycle.unavailable_reason() is None
    lifecycle.note_launch_result("MINI_BROWSER_CHROMIUM_MISSING")
    assert lifecycle.unavailable_reason() == "MINI_BROWSER_CHROMIUM_MISSING"
    lifecycle.note_launch_result("MINI_BROWSER_PROFILE_IN_USE")  # transient: kept
    assert lifecycle.unavailable_reason() == "MINI_BROWSER_CHROMIUM_MISSING"
    lifecycle.note_launch_result(None)
    assert lifecycle.unavailable_reason() is None


def test_launch_failure_codes_reach_unavailable_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "profile_dir", lambda: tmp_path / "profile")
    core = BrowserCore(settings=MiniBrowserSettings(idle_shutdown_minutes=0))

    async def scenario():
        async def missing():
            raise MiniBrowserError("MINI_BROWSER_PLAYWRIGHT_MISSING")

        core._launch_browser = missing
        with pytest.raises(MiniBrowserError):
            await core.start()
        seen = lifecycle.unavailable_reason()

        async def fine():
            core.status = "ready"

        core._launch_browser = fine
        await core.start()
        return seen, lifecycle.unavailable_reason()

    assert run(scenario()) == ("MINI_BROWSER_PLAYWRIGHT_MISSING", None)


def test_reload_settings_submits_an_awaitable_and_never_starts(monkeypatch):
    """C6 / CFG-1: lifecycle.reload_settings() reaches a running core."""
    monkeypatch.setattr(host_module, "_host", None)
    lifecycle.reload_settings()  # no host: nothing happens, nothing starts
    assert host_module._host is None

    class Core:
        def __init__(self):
            self.reloaded = threading.Event()

        async def reload_settings_now(self):
            self.reloaded.set()

    host = MiniBrowserHost(Core)
    monkeypatch.setattr(host_module, "_host", host)
    warnings: List[str] = []
    from app.logger import logger

    sink_id = logger.add(
        lambda m: warnings.append(m.record["message"]), level="WARNING"
    )
    try:
        host.start()
        lifecycle.reload_settings()
        assert host.core.reloaded.wait(5)
    finally:
        logger.remove(sink_id)
        asyncio.run(host.shutdown(timeout=5))
    assert not any("Background call failed" in w for w in warnings)


# ── host: terminal shutdown (CONC-6) ─────────────────────────────────────────


class SlowCore:
    """A stand-in core whose work unwinds slowly when cancelled."""

    def __init__(self) -> None:
        self.calls = 0

    async def work(self) -> str:
        self.calls += 1
        await asyncio.sleep(0.01)
        return "ok"

    async def stubborn(self) -> str:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            await asyncio.sleep(1.5)  # unwinds slowly, like a launch teardown
            raise
        return "never"

    async def close(self) -> None:
        return None


def test_calls_during_and_after_shutdown_fail_fast():
    """concurrency CONC-6: no hang during shutdown, no restart after it, and
    work the shutdown cancels ends with NOT_RUNNING, not CancelledError."""
    host = MiniBrowserHost(SlowCore)
    host.start()
    outcomes: List[str] = []
    stop = threading.Event()

    def hammer():
        async def loop():
            while not stop.is_set():
                try:
                    outcomes.append(
                        await asyncio.wait_for(host.call(lambda c: c.work()), 20)
                    )
                except MiniBrowserError as exc:
                    outcomes.append(exc.code)
                except asyncio.TimeoutError:
                    outcomes.append("HUNG")
                except BaseException as exc:  # noqa: BLE001
                    outcomes.append(type(exc).__name__)
                await asyncio.sleep(0.005)

        asyncio.run(loop())

    async def scenario():
        stubborn = asyncio.ensure_future(host.call(lambda c: c.stubborn()))
        await asyncio.sleep(0.3)
        started = time.monotonic()
        await host.shutdown(timeout=3)
        took = time.monotonic() - started
        try:
            await asyncio.wait_for(stubborn, 10)
            stubborn_outcome = "returned"
        except MiniBrowserError as exc:
            stubborn_outcome = exc.code
        except asyncio.CancelledError:
            stubborn_outcome = "CancelledError"
        return took, stubborn_outcome

    worker = threading.Thread(target=hammer, daemon=True)
    worker.start()
    time.sleep(0.2)
    took, stubborn_outcome = run(scenario(), 30)
    time.sleep(0.3)
    stop.set()
    worker.join(30)
    assert not worker.is_alive(), "a caller hung on the stopping host"
    assert took < 10
    assert stubborn_outcome == "MINI_BROWSER_NOT_RUNNING"
    assert "HUNG" not in outcomes and "CancelledError" not in outcomes
    assert set(outcomes) <= {"ok", "MINI_BROWSER_NOT_RUNNING"}
    assert outcomes[-1] == "MINI_BROWSER_NOT_RUNNING"
    # After shutdown: refused at once, never a silent restart.
    started = time.monotonic()
    with pytest.raises(MiniBrowserError) as info:
        run(host.call(lambda c: c.work()))
    assert info.value.code == "MINI_BROWSER_NOT_RUNNING"
    assert time.monotonic() - started < 1 and not host.is_running()
    # An explicit restart is possible.
    host.reopen()
    try:
        assert run(host.call(lambda c: c.work())) == "ok"
    finally:
        asyncio.run(host.shutdown(timeout=5))


# ═════════════════════════════════════════════════════════════════════════════
# Real Chromium
# ═════════════════════════════════════════════════════════════════════════════


class Site:
    """A local web site with the pages these tests need."""

    def __init__(self) -> None:
        self.hits: collections.Counter = collections.Counter()
        self.slow_once_seen: set = set()
        site = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def do_GET(self):
                path, _, query = self.path.partition("?")
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
                site.hits[(host, path)] += 1
                if path == "/page":
                    title = (
                        query.split("t=", 1)[1].split("&")[0]
                        if "t=" in query
                        else "Page"
                    )
                    self.html(f"<title>{title}</title><h1>{title}</h1>")
                elif path == "/slow":
                    time.sleep(SLOW_S)
                    self.html("<title>Slow</title>slow")
                elif path == "/slow-once":
                    if query in site.slow_once_seen:
                        time.sleep(SLOW_S)
                    site.slow_once_seen.add(query)
                    self.html("<title>Slow once</title>slow once")
                elif path == "/moves":
                    self.html(
                        "<title>Moves</title><body style='margin:0;height:3000px'>"
                        "<button id='b' style='margin:100px;padding:20px'>Like</button>"
                        "</body>"
                    )
                elif path == "/links":
                    self.html(
                        "<title>Links</title>"
                        "<a id='pop' href='/page?t=Popup' target='_blank'>new tab</a> "
                        "<a id='exe' href='/setup.exe'>exe</a> "
                        "<a id='txt' href='/notes.txt'>txt</a>"
                    )
                elif path in ("/setup.exe", "/notes.txt"):
                    body = b"MZ harmless test bytes, never executed"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    name = path.lstrip("/")
                    self.send_header(
                        "Content-Disposition", f'attachment; filename="{name}"'
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/hang":
                    seconds = float(query.split("s=", 1)[1]) if "s=" in query else 4
                    self.html(
                        "<title>Hang</title><script>setTimeout(() => {"
                        f" const end = Date.now() + {int(seconds * 1000)};"
                        " while (Date.now() < end) {} }, 300)</script>hang"
                    )
                elif path == "/unsaved":
                    self.html(
                        "<title>Draft</title><textarea id='t'></textarea><script>"
                        "window.addEventListener('beforeunload', e => {"
                        " e.preventDefault(); e.returnValue = ''; });</script>"
                    )
                else:
                    self.html("<title>Other</title>other")

            def html(self, text: str) -> None:
                body = text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except Exception:
                    pass

        ThreadingHTTPServer.daemon_threads = True
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path: str, host: str = "127.0.0.1") -> str:
        return f"http://{host}:{self.port}{path}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class FakeSink:
    def __init__(self) -> None:
        self.viewers = False
        self._lock = threading.Lock()
        self._posts: List[tuple] = []

    def has_viewers(self) -> bool:
        return self.viewers

    def post(self, kind: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._posts.append((kind, dict(payload)))

    def of(self, kind: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [payload for k, payload in self._posts if k == kind]

    def clear(self) -> None:
        with self._lock:
            self._posts.clear()


# Fake agent operations: ``async def op(core, tab, **params) -> dict``.


async def op_echo(core, tab):
    return {"status": "success", "message": "echo", "url": tab.page.url}


async def op_goto(core, tab, *, url):
    try:
        await tab.page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as exc:  # the result reports where the tab is
        return {
            "status": "success",
            "message": f"goto raised {type(exc).__name__}",
            "url": tab.page.url,
        }
    return {"status": "success", "message": "navigated", "url": tab.page.url}


async def op_eval(core, tab, *, script):
    return {
        "status": "success",
        "message": "evaluated",
        "value": await tab.page.evaluate(script),
    }


async def op_sleep(core, tab, *, seconds=30.0):
    await asyncio.sleep(seconds)
    return {"status": "success", "message": f"slept {seconds}"}


async def op_wait_user(core, tab, *, for_user=True, timeout=30.0):
    """The old mini_browser_wait(for_user): polls user_control only."""
    deadline = time.monotonic() + timeout
    while tab.user_control:
        if time.monotonic() > deadline:
            raise MiniBrowserError(
                "MINI_BROWSER_TIMEOUT", what="Waiting", seconds=int(timeout)
            )
        await asyncio.sleep(0.05)
    return {"status": "success", "message": "The user handed control back."}


async def op_steps(core, tab, *, steps=60):
    """A cooperative operation (like ops/human.py): checks take-control each step."""
    for _ in range(steps):
        if tab.user_control:
            raise MiniBrowserError("MINI_BROWSER_USER_IN_CONTROL")
        await asyncio.sleep(0.05)
    return {"status": "success", "message": "all steps done"}


async def op_moves(core, tab, *, n=8):
    """A human-style click, then mouse moves; reports the median move latency."""
    page = tab.page
    await page.mouse.move(150, 130)
    await page.mouse.down()
    await asyncio.sleep(0.08)
    await page.mouse.up()
    latencies = []
    for i in range(n):
        started = time.perf_counter()
        await page.mouse.move(300 + i * 9, 300 + i * 4)
        latencies.append(time.perf_counter() - started)
        await asyncio.sleep(0.012)
    return {
        "status": "success",
        "message": "moved",
        "median_ms": statistics.median(latencies) * 1000,
    }


async def op_click_popup(core, tab, *, selector, wait=True):
    """Click a target=_blank link; like ops.after_action, give the core a
    moment to register the new tab before returning (``wait``)."""
    page = tab.page
    before = len(page.context.pages)
    await page.click(selector, timeout=10000)
    if wait:
        for _ in range(150):
            pages = page.context.pages
            if len(pages) > before and all(
                any(t.page is p for t in core.tabs.values()) for p in pages
            ):
                break
            await asyncio.sleep(0.02)
    return {"status": "success", "message": f"Clicked {selector}."}


async def op_secret_nav(core, tab, *, path):
    """Autofill typed SECRET; the site then put it, encoded, into the URL."""
    tab.filled_secrets.append(SECRET)
    await tab.page.goto(path, wait_until="domcontentloaded", timeout=20000)
    return {
        "status": "success",
        "message": f"Now at {tab.page.url}",
        "url": tab.page.url,
    }


async def op_click(core, tab, *, selector):
    await tab.page.click(selector, timeout=10000)
    return {"status": "success", "message": "clicked"}


FAKE_OPS = {
    "echo": op_echo,
    "goto": op_goto,
    "eval": op_eval,
    "sleep": op_sleep,
    "wait": op_wait_user,
    "steps": op_steps,
    "moves": op_moves,
    "click_popup": op_click_popup,
    "secret_nav": op_secret_nav,
    "click": op_click,
}

# downloads.example is a non-local host name served by the local site (no
# system proxy in between).
RESOLVER_RULES = "--host-resolver-rules=MAP downloads.example 127.0.0.1"
LAUNCH_ARGS = (RESOLVER_RULES, "--no-proxy-server")


class Engine:
    def __init__(self, host: MiniBrowserHost, sink: FakeSink, site: Site, root: Path):
        self.host, self.sink, self.site, self.root = host, sink, site, root

    def call(self, fn, timeout: float = 90.0):
        return run(self.host.call(fn), timeout)

    def inspect(self, fn):
        return self.call(lambda core: _apply(fn, core))

    def op(self, owner: str, op: str, timeout: float = 90.0, **params):
        return self.call(lambda core: core.agent_op(owner, op, params), timeout)

    def tab(self, tab_id: str):
        return self.inspect(lambda core: core.tabs.get(tab_id))

    def wait_until(self, predicate, timeout: float = 15.0, what: str = "condition"):
        deadline = time.monotonic() + timeout
        while True:
            value = self.inspect(predicate)
            if value:
                return value
            if time.monotonic() > deadline:
                raise AssertionError(f"timed out waiting for {what}")
            time.sleep(0.05)


def _chromium_or_skip(exc: MiniBrowserError) -> None:
    if exc.code in ("MINI_BROWSER_CHROMIUM_MISSING", "MINI_BROWSER_PLAYWRIGHT_MISSING"):
        pytest.skip(f"Chromium unavailable ({exc.code})")


@pytest.fixture(scope="module")
def site():
    server = Site()
    yield server
    server.close()


@pytest.fixture(scope="module")
def engine(site, tmp_path_factory):
    pytest.importorskip("playwright.async_api")
    patch = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp("mini_browser_fixes")
    patch.setattr(config, "profile_dir", lambda: root / "profile")
    patch.setattr(
        config, "workspace_dir", lambda owner: root / "workspace" / (owner or "_user")
    )
    patch.setattr(config, "save_setting", lambda key, value: None)
    sink = FakeSink()
    bridge.register_ui_sink(sink)
    settings = MiniBrowserSettings(
        idle_shutdown_minutes=0, max_agent_tabs=6, max_fps=10
    )
    host = MiniBrowserHost(
        lambda: BrowserCore(
            settings=settings, ops_registry=FAKE_OPS, launch_args=LAUNCH_ARGS
        )
    )
    engine = Engine(host, sink, site, root)
    try:
        engine.call(lambda core: core.start(), timeout=120)
    except MiniBrowserError as exc:
        asyncio.run(host.shutdown(timeout=10))
        bridge.unregister_ui_sink(sink)
        patch.undo()
        _chromium_or_skip(exc)
        raise
    yield engine
    asyncio.run(host.shutdown(timeout=20))
    bridge.unregister_ui_sink(sink)
    bridge.set_ui_origins([])
    patch.undo()


async def _reset(core: BrowserCore) -> None:
    """Back to one idle user tab, default view."""
    await core.ensure_started()
    for tab in list(core.tabs.values()):
        if tab.user_control:
            await core.ui_control(tab.id, False)
    for owner in {t.owner for t in core.tabs.values() if t.owner}:
        core.release_owner(owner, close_tabs=True)
    for _ in range(200):
        if not any(t.owner for t in core.tabs.values()) and core.tabs:
            break
        await asyncio.sleep(0.02)
    for tab in list(core.tabs.values())[1:]:
        await core.ui_close_tab(tab.id)
    await core.ui_view(None, True)
    for tab in core.tabs.values():
        tab.last_user_input = 0.0
    core._closed_owners.clear()
    core._tab_switches.clear()


@pytest.fixture
def eng(engine, monkeypatch):
    engine.sink.viewers = False
    engine.call(_reset)
    engine.sink.clear()
    # A predictable observation (the real one is tested with observe.py).
    module = types.ModuleType("app.mini_browser.observe")

    async def fake_observe(core, tab, *, compact):
        return {"tabId": tab.id, "url": tab.page.url, "elements": []}

    module.observe = fake_observe
    monkeypatch.setitem(sys.modules, "app.mini_browser.observe", module)
    monkeypatch.setattr(mini_browser_package, "observe", module, raising=False)
    return engine


def _profile_processes(profile: Path) -> list:
    return core_module._profile_processes(profile)


def _lock_free(profile: Path) -> bool:
    lock = core_module._ProfileLock(profile.parent / f"{profile.name}.lock")
    if lock.acquire():
        lock.release()
        return True
    return False


def _wait_for(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return predicate()


# ── CONC-1 / CONC-10 / UX-3 / NAV-1: closing the browser under operations ───


def test_close_during_start_gives_closed_not_cancelled(tmp_path, monkeypatch):
    """concurrency CONC-1: an op waiting for Chromium to start, then the user
    closes the browser: the op returns MINI_BROWSER_CLOSED (never a
    CancelledError its caller did not ask for)."""
    pytest.importorskip("playwright.async_api")
    monkeypatch.setattr(config, "profile_dir", lambda: tmp_path / "profile")
    monkeypatch.setattr(config, "workspace_dir", lambda owner: tmp_path / "ws")
    host = MiniBrowserHost(
        lambda: BrowserCore(
            settings=MiniBrowserSettings(idle_shutdown_minutes=0), ops_registry=FAKE_OPS
        )
    )

    async def scenario(delay):
        caller = asyncio.ensure_future(
            host.call(lambda c: c.agent_op("chat-1", "echo", {}))
        )
        await asyncio.sleep(delay)
        await host.call(lambda c: c.close())
        try:
            result = await asyncio.wait_for(caller, 90)
        except asyncio.CancelledError:
            return "CancelledError"
        return result.get("error_code") or result.get("status")

    try:
        outcomes = [run(scenario(delay), 120) for delay in (0.05, 0.4)]
    except MiniBrowserError as exc:
        _chromium_or_skip(exc)
        raise
    finally:
        asyncio.run(host.shutdown(timeout=20))
    assert "CancelledError" not in outcomes
    assert set(outcomes) <= {"MINI_BROWSER_CLOSED", "success"}
    assert outcomes[0] == "MINI_BROWSER_CLOSED"


def test_close_during_crash_recovery_gives_closed(eng):
    """concurrency CONC-1 (recovery variant)."""
    url = eng.site.url("/slow-once?k=recovery")
    tab_id = eng.op("rec-agent", "goto", url=url)["tab"]["id"]

    async def crash(core):
        core.spawn(core.tabs[tab_id].cdp.send("Page.crash"))

    eng.call(crash)
    eng.wait_until(lambda core: core.tabs[tab_id].crashed, what="crash")

    async def scenario(core):
        op = asyncio.ensure_future(core.agent_op("rec-agent", "echo", {}))
        await asyncio.sleep(1.5)  # recovery is reloading the (now slow) page
        recovering = any(not t.done() for t in core._recoveries.values())
        await core.close()
        try:
            result = await asyncio.wait_for(op, 20)
        except asyncio.CancelledError:
            return recovering, "CancelledError"
        return recovering, result.get("error_code")

    recovering, outcome = eng.call(scenario)
    assert recovering
    assert outcome == "MINI_BROWSER_CLOSED"


def test_closing_the_browser_ends_inflight_ops_and_tells_every_owner(eng):
    """CONC-10 / UX-3 / NAV-1 + C1/C2: the op in flight reports
    MINI_BROWSER_CLOSED (never success); after the relaunch, every other owner
    that had tabs is told once that they are gone."""
    eng.op("idle-owner", "goto", url=eng.site.url("/page?t=Idle"))
    eng.op("busy-owner", "echo")
    slow = eng.site.url("/slow")

    async def scenario(core):
        op = asyncio.ensure_future(core.agent_op("busy-owner", "goto", {"url": slow}))
        await asyncio.sleep(1.0)
        started = time.monotonic()
        await core.close()
        result = await asyncio.wait_for(op, 10)
        return result, time.monotonic() - started

    result, took = eng.call(scenario)
    assert result["status"] == "error" and result["error_code"] == "MINI_BROWSER_CLOSED"
    assert took < 9  # not the slow page's 8 s plus a close
    busy_next = eng.op("busy-owner", "echo")  # relaunches; it was already told
    assert busy_next["status"] == "success"
    assert not busy_next["message"].startswith("Note:")
    idle_next = eng.op("idle-owner", "echo")
    assert idle_next["message"].startswith(core_module.RELAUNCH_NOTE)
    assert not eng.op("idle-owner", "echo")["message"].startswith("Note:")


def test_idle_shutdown_is_announced_to_owners(eng):
    eng.op("sleepy-owner", "goto", url=eng.site.url("/page?t=Sleepy"))

    def make_idle(core):
        core.settings = core_module.replace(core.settings, idle_shutdown_minutes=1)
        core._last_activity = time.monotonic() - 120

    eng.inspect(make_idle)
    try:
        eng.wait_until(
            lambda core: core.status == "stopped", timeout=15, what="idle shutdown"
        )
    finally:
        eng.inspect(
            lambda core: setattr(
                core,
                "settings",
                core_module.replace(core.settings, idle_shutdown_minutes=0),
            )
        )
    after = eng.op("sleepy-owner", "echo", timeout=120)
    assert after["status"] == "success"
    assert after["message"].startswith(core_module.RELAUNCH_NOTE)
    assert after["url"] == "about:blank"


# ── CONC-5: waiting on a tab that closes ────────────────────────────────────


@pytest.mark.parametrize("closer", ["tab", "browser"])
def test_a_wait_ends_at_once_when_its_tab_or_the_browser_closes(eng, closer):
    tab_id = eng.op("waiter", "goto", url=eng.site.url("/page?t=Wait"))["tab"]["id"]
    eng.call(lambda core: core.ui_control(tab_id, True))

    async def scenario(core):
        waits = [
            asyncio.ensure_future(
                core.agent_op("waiter", "wait", {"for_user": True, "timeout": 60})
            ),
        ]
        await asyncio.sleep(0.5)
        started = time.monotonic()
        if closer == "tab":
            await core.ui_close_tab(tab_id)
        else:
            await core.close()
        results = await asyncio.wait_for(asyncio.gather(*waits), 10)
        return results, time.monotonic() - started

    results, took = eng.call(scenario)
    expected = "MINI_BROWSER_TAB_CLOSED" if closer == "tab" else "MINI_BROWSER_CLOSED"
    assert [r["error_code"] for r in results] == [expected]
    assert took < 3


def test_a_long_operation_ends_when_its_tab_closes(eng):
    tab_id = eng.op("sleeper", "echo")["tab"]["id"]

    async def scenario(core):
        op = asyncio.ensure_future(core.agent_op("sleeper", "sleep", {"seconds": 60}))
        await asyncio.sleep(0.5)
        started = time.monotonic()
        await core.ui_close_tab(tab_id)
        result = await asyncio.wait_for(op, 10)
        return result, time.monotonic() - started

    result, took = eng.call(scenario)
    assert result["error_code"] == "MINI_BROWSER_TAB_CLOSED"
    assert took < 4
    assert eng.op("sleeper", "echo")["status"] == "success"  # carries on elsewhere


# ── CONC-9: cancelled while opening a tab ───────────────────────────────────


def test_cancelling_an_op_while_it_opens_its_tab_leaves_no_orphans(eng):
    async def scenario(core):
        for tab in core.tabs.values():
            tab.last_user_input = time.monotonic()  # not claimable: ops open tabs
        before = set(core.tabs)
        for i in range(8):
            task = asyncio.ensure_future(core.agent_op(f"cancel-open-{i}", "echo", {}))
            await asyncio.sleep(0.004 * i)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await asyncio.sleep(2.0)  # tab opening finishes in the background
        new = [t for tab_id, t in core.tabs.items() if tab_id not in before]
        return [(t.owner, t.cdp is not None, t.id in core._main_frames) for t in new]

    rows = eng.call(scenario)
    assert rows, "no op got far enough to open a tab"
    for owner, has_cdp, has_frame in rows:
        assert owner is not None and owner.startswith("cancel-open-"), rows
        assert has_cdp and has_frame, rows


# ── CONC-3: hooks while the browser thread is not running ────────────────────


def test_stop_before_the_host_starts_still_revokes_subagents(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "profile_dir", lambda: tmp_path / "profile")
    monkeypatch.setattr(host_module, "_host", None)
    created = (datetime.utcnow() - timedelta(minutes=1)).isoformat()
    _fake_agent_runtime(
        monkeypatch,
        sessions={},
        subagents={
            "sub_early001": types.SimpleNamespace(
                parent_task_id="chat-x", agent_type="browser_agent", created_at=created
            )
        },
    )
    lifecycle.on_run_state("chat-x", "running")
    lifecycle.cancel_owner("chat-x")  # the user pressed Stop: no browser thread yet
    lifecycle.on_run_state("chat-x", "stopping")
    host = MiniBrowserHost(
        lambda: BrowserCore(
            settings=MiniBrowserSettings(idle_shutdown_minutes=0), ops_registry=FAKE_OPS
        )
    )
    try:
        stopped = run(host.call(lambda core: core.agent_op("sub_early001", "echo", {})))
        busy = run(
            host.call(
                lambda core: _apply(
                    lambda c: (c._run_busy("chat-x"), c._run_busy("sub_early001")), core
                )
            )
        )
    finally:
        asyncio.run(host.shutdown(timeout=10))
    assert stopped["error_code"] == "MINI_BROWSER_STOPPED"
    assert busy == (True, True)


def test_a_hook_during_host_start_is_not_lost(monkeypatch):
    """The gap between building the core and the host being 'started'."""
    monkeypatch.setattr(host_module, "_host", None)

    def factory():
        core = BrowserCore(
            settings=MiniBrowserSettings(idle_shutdown_minutes=0), ops_registry=FAKE_OPS
        )
        lifecycle.on_run_state("chat-y", "running")  # fired while start() runs
        return core

    host = MiniBrowserHost(factory)
    try:
        busy = run(
            host.call(lambda core: _apply(lambda c: c._run_busy("chat-y"), core))
        )
    finally:
        asyncio.run(host.shutdown(timeout=10))
    assert busy is True


# ── CONC-2: close / exit while Chromium is being launched ────────────────────


@pytest.mark.parametrize("delay", [0.3, 1.2])
def test_close_during_launch_is_clean_and_quick(tmp_path, monkeypatch, delay):
    """concurrency CONC-2: no half-cancelled launch, no leftover Chromium on
    the profile, the profile lock is free and an immediate relaunch works."""
    pytest.importorskip("playwright.async_api")
    profile = tmp_path / "profile"
    monkeypatch.setattr(config, "profile_dir", lambda: profile)
    host = MiniBrowserHost(
        lambda: BrowserCore(
            settings=MiniBrowserSettings(idle_shutdown_minutes=0), ops_registry=FAKE_OPS
        )
    )

    async def scenario():
        starting = asyncio.ensure_future(host.call(lambda c: c.start()))
        await asyncio.sleep(delay)
        started = time.monotonic()
        await host.call(lambda c: c.close())
        took = time.monotonic() - started
        try:
            await asyncio.wait_for(starting, 60)
            outcome = "started"
        except MiniBrowserError as exc:
            outcome = exc.code
        return took, outcome

    try:
        took, outcome = run(scenario(), 120)
        if outcome in (
            "MINI_BROWSER_CHROMIUM_MISSING",
            "MINI_BROWSER_PLAYWRIGHT_MISSING",
        ):
            pytest.skip(outcome)
        status = run(host.call(lambda c: _apply(lambda core: core.status, c)))
        gone = _wait_for(lambda: not _profile_processes(profile), 10)
        lock_free = _wait_for(lambda: _lock_free(profile), 5)
        relaunch_started = time.monotonic()
        run(host.call(lambda c: c.start()), 120)
        relaunch_took = time.monotonic() - relaunch_started
        ready = run(host.call(lambda c: _apply(lambda core: core.status, c)))
    finally:
        asyncio.run(host.shutdown(timeout=20))
    assert outcome in ("MINI_BROWSER_CLOSED", "started")
    assert took < 8, took
    assert status == "stopped"
    assert gone, "Chromium still runs on the profile after the close"
    assert lock_free
    assert ready == "ready" and relaunch_took < 30


def test_app_exit_during_launch_is_quick_and_leaves_nothing(tmp_path, monkeypatch):
    pytest.importorskip("playwright.async_api")
    profile = tmp_path / "profile"
    monkeypatch.setattr(config, "profile_dir", lambda: profile)
    host = MiniBrowserHost(
        lambda: BrowserCore(
            settings=MiniBrowserSettings(idle_shutdown_minutes=0), ops_registry=FAKE_OPS
        )
    )

    async def scenario():
        starting = asyncio.ensure_future(host.call(lambda c: c.start()))
        await asyncio.sleep(0.8)
        started = time.monotonic()
        await host.shutdown(timeout=8)
        took = time.monotonic() - started
        try:
            await asyncio.wait_for(starting, 10)
            outcome = "started"
        except MiniBrowserError as exc:
            outcome = exc.code
        except asyncio.CancelledError:
            outcome = "CancelledError"
        return took, outcome

    took, outcome = run(scenario(), 60)
    if outcome in ("MINI_BROWSER_CHROMIUM_MISSING", "MINI_BROWSER_PLAYWRIGHT_MISSING"):
        pytest.skip(outcome)
    assert outcome in ("MINI_BROWSER_CLOSED", "MINI_BROWSER_NOT_RUNNING", "started")
    assert took < 7, took
    assert _wait_for(lambda: not _profile_processes(profile), 10)


def test_an_unclean_close_keeps_the_profile_lock_until_chromium_exits(
    tmp_path, monkeypatch
):
    """concurrency CONC-2: never hand the profile over while Chromium may run."""
    profile = tmp_path / "profile"
    profile.mkdir()
    lock = core_module._ProfileLock(profile.parent / "profile.lock")
    assert lock.acquire()
    core = BrowserCore(settings=MiniBrowserSettings(idle_shutdown_minutes=0))
    alive = {"procs": ["chrome"]}
    monkeypatch.setattr(
        core_module, "_profile_processes", lambda path: list(alive["procs"])
    )

    async def scenario():
        task = core.spawn(core._release_lock_when_free(lock, profile))
        await asyncio.sleep(0.6)
        held = not _lock_free(profile)
        alive["procs"] = []
        await asyncio.wait_for(task, 5)
        return held, _lock_free(profile)

    held, freed = run(scenario())
    assert held and freed


# ── CONC-7: the Playwright driver dies ───────────────────────────────────────


def test_driver_death_is_noticed_and_the_relaunch_is_quick(tmp_path, monkeypatch):
    psutil = pytest.importorskip("psutil")
    pytest.importorskip("playwright.async_api")
    profile = tmp_path / "profile"
    monkeypatch.setattr(config, "profile_dir", lambda: profile)
    host = MiniBrowserHost(
        lambda: BrowserCore(
            settings=MiniBrowserSettings(idle_shutdown_minutes=0), ops_registry=FAKE_OPS
        )
    )
    try:
        try:
            first = run(host.call(lambda c: c.agent_op("chat-d", "echo", {})), 120)
        except MiniBrowserError as exc:
            _chromium_or_skip(exc)
            raise
        if first.get("error_code") in (
            "MINI_BROWSER_CHROMIUM_MISSING",
            "MINI_BROWSER_PLAYWRIGHT_MISSING",
        ):
            pytest.skip(first["error_code"])
        assert first["status"] == "success"
        drivers = set()
        for proc in _profile_processes(profile):
            try:
                parent = proc.parent()
                if parent is not None and parent.name().lower().startswith("node"):
                    drivers.add(parent)
            except psutil.Error:
                pass
        assert drivers, "could not find this browser's driver"
        for driver in drivers:
            driver.kill()
        # Noticed without any agent action (the watchdog probes the connection).
        status = lambda: run(host.call(lambda c: _apply(lambda core: core.status, c)))  # noqa: E731
        assert _wait_for(lambda: status() == "stopped", 8), status()
        started = time.monotonic()
        again = run(host.call(lambda c: c.agent_op("chat-d", "echo", {})), 120)
        took = time.monotonic() - started
    finally:
        asyncio.run(host.shutdown(timeout=20))
    assert again["status"] == "success", again
    assert again["message"].startswith(core_module.RELAUNCH_NOTE)
    assert took < 12, took


# ── CONC-8 / CFG-1: settings ─────────────────────────────────────────────────


def test_settings_apply_at_the_next_start_and_live(tmp_path, monkeypatch):
    pytest.importorskip("playwright.async_api")
    monkeypatch.setattr(config, "profile_dir", lambda: tmp_path / "profile")
    values: Dict[str, Any] = {
        "idle_shutdown_minutes": 0,
        "max_agent_tabs": 2,
        "adblock": True,
    }
    monkeypatch.setattr(config, "load_settings", lambda: MiniBrowserSettings(**values))
    host = MiniBrowserHost(
        lambda: BrowserCore(ops_registry=FAKE_OPS)
    )  # settings.json-backed
    monkeypatch.setattr(host_module, "_host", host)

    def current(name):
        return run(
            host.call(lambda c: _apply(lambda core: getattr(core.settings, name), c))
        )

    try:
        try:
            run(host.call(lambda c: c.start()), 120)
        except MiniBrowserError as exc:
            _chromium_or_skip(exc)
            raise
        assert current("max_agent_tabs") == 2
        values["max_agent_tabs"] = 5
        run(host.call(lambda c: c.close()))
        run(host.call(lambda c: c.start()), 120)  # Close + Start applies edits
        assert current("max_agent_tabs") == 5
        values["adblock"] = False
        values["max_fps"] = 20
        lifecycle.reload_settings()  # settings.json hot reload: live settings
        assert _wait_for(lambda: current("adblock") is False, 5)
        assert current("max_fps") == 20
        assert run(host.call(lambda c: _apply(lambda core: core.status, c))) == "ready"
    finally:
        asyncio.run(host.shutdown(timeout=20))


# ── PERF-1: background tabs ──────────────────────────────────────────────────


FAST_MS = 200.0  # a background tab takes ~1000 ms per mouse move


def test_every_owner_acts_at_full_speed(eng):
    """agent-effectiveness PERF-1: one window per tab, so an owner's tab is
    never a background tab of another owner's; its input is not throttled."""
    url = eng.site.url("/moves")
    a = eng.op("speed-a", "goto", url=url)
    b = eng.op("speed-b", "goto", url=url)
    assert a["tab"]["id"] != b["tab"]["id"]

    async def both(core):
        rounds = []
        for _ in range(3):
            pair = await asyncio.gather(
                core.agent_op("speed-a", "moves", {}),
                core.agent_op("speed-b", "moves", {}),
            )
            rounds.append([r["median_ms"] for r in pair])
        return rounds

    rounds = eng.call(both)
    assert all(ms < FAST_MS for pair in rounds for ms in pair), rounds

    # A second tab, then back to the first one (the skill's compare flow).
    second = eng.op("speed-a", "tabs", action="new", url=url)
    assert second["status"] == "success"
    assert eng.op("speed-a", "moves")["median_ms"] < FAST_MS
    back = eng.op("speed-a", "tabs", action="switch", tab=a["tab"]["index"])
    assert back["tab"]["id"] == a["tab"]["id"]
    assert eng.op("speed-a", "moves")["median_ms"] < FAST_MS
    assert eng.op("speed-b", "moves")["median_ms"] < FAST_MS

    # A popup opens in the owner's window (it takes the front there); back
    # in the opener, the next action brings it to the front again.
    opened = eng.op("speed-a", "eval", script=f"() => !!window.open('{url}')")
    assert opened["value"] is True
    eng.wait_until(
        lambda core: core._owner_current.get("speed-a") != a["tab"]["id"],
        what="popup adopted",
    )
    index = eng.inspect(lambda core: core._tab_index(core.tabs[a["tab"]["id"]]))
    eng.op("speed-a", "tabs", action="switch", tab=index)
    assert eng.op("speed-a", "moves")["median_ms"] < FAST_MS
    # The user opening a tab of their own does not slow agents either.
    eng.call(lambda core: core.ui_new_tab(url))
    assert eng.op("speed-b", "moves")["median_ms"] < FAST_MS


# ── C7 (TABS-1 / POP-1): a tab the action opened ─────────────────────────────


def test_the_result_shows_the_new_tab_an_action_opened(eng):
    opener = eng.op("pop-owner", "goto", url=eng.site.url("/page?t=X"))
    eng.op("pop-owner", "goto", url=eng.site.url("/links"))
    clicked = eng.op("pop-owner", "click_popup", selector="#pop")
    popup_id = eng.inspect(lambda core: core._owner_current["pop-owner"])
    assert popup_id != opener["tab"]["id"]
    index = eng.inspect(lambda core: core._tab_index(core.tabs[popup_id]))
    assert clicked["status"] == "success"
    assert clicked["message"] == (
        f"Clicked #pop. A new tab opened (index {index}) and is now your active tab."
    )
    assert clicked["tab"] == {"id": popup_id, "index": index}
    assert clicked["page"]["tabId"] == popup_id  # an observation of the NEW tab
    assert [e["kind"] for e in clicked.get("events", [])].count("popup") == 1
    later = eng.op("pop-owner", "echo")
    assert later["tab"]["id"] == popup_id
    assert "popup" not in [e["kind"] for e in later.get("events", [])]  # not twice
    assert not later["message"].startswith("A new tab")


def test_a_late_popup_is_announced_on_the_next_result(eng, monkeypatch):
    eng.op("late-owner", "goto", url=eng.site.url("/links"))
    monkeypatch.setattr(core_module, "POPUP_ADOPT_WAIT_S", 0.0)
    original = BrowserCore._adopt_page

    async def slow_adopt(self, page):
        await asyncio.sleep(0.6)  # registered only after the click's result
        await original(self, page)

    monkeypatch.setattr(BrowserCore, "_adopt_page", slow_adopt)
    clicked = eng.op("late-owner", "click", selector="#pop")
    assert "new tab" not in clicked["message"]
    eng.wait_until(
        lambda core: core._tab_switches.get("late-owner") is not None,
        what="late adoption",
    )
    after = eng.op("late-owner", "echo")
    popup_id = eng.inspect(lambda core: core._owner_current["late-owner"])
    index = eng.inspect(lambda core: core._tab_index(core.tabs[popup_id]))
    assert after["tab"]["id"] == popup_id
    assert after["message"].startswith(
        f"A new tab opened (index {index}) and is now your active tab."
    )
    notices = [
        e for r in (clicked, after) for e in r.get("events", []) if e["kind"] == "popup"
    ]
    assert len(notices) == 1


# ── C8 (CTRL-1): taking control under a running operation ────────────────────


def test_taking_control_stops_a_running_operation(eng):
    tab_id = eng.op("ctrl-agent", "goto", url=eng.site.url("/page?t=Form"))["tab"]["id"]

    async def scenario(core):
        tab = core.tabs[tab_id]
        seen_at_dispatch: List[bool] = []
        keyboard = tab.page.keyboard
        real_press = keyboard.press

        async def press(key, **kwargs):
            seen_at_dispatch.append(tab.user_control)
            return await real_press(key, **kwargs)

        keyboard.press = press
        try:
            op = asyncio.ensure_future(
                core.agent_op("ctrl-agent", "steps", {"steps": 100})
            )
            await asyncio.sleep(0.4)
            await core.ui_input(tab_id, {"kind": "key", "key": "a"})
            result = await asyncio.wait_for(op, 10)
        finally:
            del keyboard.press
        return result, seen_at_dispatch

    result, seen = eng.call(scenario)
    assert seen == [True]  # control was taken BEFORE the key reached the page
    assert result["error_code"] == "MINI_BROWSER_USER_IN_CONTROL"
    assert result["page"]["tabId"] == tab_id  # a fresh look at the page
    assert any("took control" in e["message"] for e in result.get("events", []))


# ── C10 (LANE-1): a frozen page and live-view input ──────────────────────────


def test_input_to_a_frozen_page_fails_fast_and_recovers(eng):
    tab_id = eng.call(lambda core: core.ui_new_tab(eng.site.url("/hang?s=5")))
    eng.wait_until(
        lambda core: core.tabs[tab_id].url.endswith("/hang?s=5"), what="load"
    )
    time.sleep(0.8)  # the page's main thread is now busy for 5 s
    move = {"kind": "mouse", "action": "move", "x": 0.5, "y": 0.5}

    def timed():
        started = time.monotonic()
        try:
            eng.call(lambda core: core.ui_input(tab_id, move), timeout=30)
            code = None
        except MiniBrowserError as exc:
            code = exc.code
        return code, time.monotonic() - started

    first, first_took = timed()
    assert first == "MINI_BROWSER_PAGE_UNRESPONSIVE" and first_took < 2.5, first_took
    second, second_took = timed()
    assert second == "MINI_BROWSER_PAGE_UNRESPONSIVE" and second_took < 0.5, second_took
    eng.wait_until(
        lambda core: not core.tabs[tab_id].unresponsive, timeout=15, what="probe"
    )
    third, _ = timed()
    assert third is None


# ── TAB-1: "leave site?" on a page that was the user's ───────────────────────


def test_unsaved_user_page_is_not_left_silently(eng):
    url = eng.site.url("/unsaved")
    tab_id = eng.call(lambda core: core.ui_new_tab(url))
    eng.wait_until(lambda core: core.tabs[tab_id].url.endswith("/unsaved"), what="load")
    for action in ("down", "up"):  # a user gesture: the page may now ask
        eng.call(
            lambda core, a=action: core.ui_input(
                tab_id,
                {"kind": "mouse", "action": a, "x": 0.1, "y": 0.05, "button": "left"},
            )
        )
    eng.inspect(
        lambda core: setattr(
            core.tabs[tab_id], "last_user_input", time.monotonic() - 60
        )
    )
    result = eng.op(
        mini_browser_package.SESSION_ID, "goto", url=eng.site.url("/page?t=Away")
    )
    assert result["tab"]["id"] == tab_id  # the dedicated chat claimed the viewed page
    assert result["url"].endswith("/unsaved")  # ... but did not leave it
    dialogs = [e for e in result.get("events", []) if e["kind"] == "dialog"]
    assert dialogs and dialogs[0]["dialog"] == "beforeunload"
    assert dialogs[0]["accepted"] is False
    assert "ask the user before leaving it" in dialogs[0]["message"]

    # An agent's own page with unsaved changes: it is left, and the agent told.
    own = eng.op("draft-agent", "goto", url=url)
    eng.op("draft-agent", "click", selector="#t")
    away = eng.op("draft-agent", "goto", url=eng.site.url("/page?t=Gone"))
    assert away["url"].endswith("t=Gone"), away
    left = [e for e in away.get("events", []) if e["kind"] == "dialog"]
    assert left and left[0]["accepted"] is True
    assert "confirmed leaving automatically" in left[0]["message"]
    assert own["tab"]["id"] == away["tab"]["id"]


# ── end-to-end SEC-1 (C9): an encoded password in the page address ───────────


def test_an_encoded_password_in_the_address_never_leaves(eng):
    query = f"user=alice%40example.test&pass={_form_encode(SECRET)}"
    path = eng.site.url(f"/page?t=Done&{query}")
    result = eng.op("get-form-agent", "secret_nav", path=path)
    tab_id = result["tab"]["id"]
    leaked = (_form_encode(SECRET), SECRET)
    assert not any(s in json.dumps(result, ensure_ascii=False) for s in leaked)
    assert "pass=[redacted]" in result["url"]
    eng.wait_until(lambda core: "pass=" in core.tabs[tab_id].url, what="url")
    state = eng.inspect(lambda core: core.state())
    listing = eng.op("get-form-agent", "tabs", action="list")
    for blob in (
        json.dumps(state, ensure_ascii=False),
        json.dumps(listing, ensure_ascii=False),
    ):
        assert not any(s in blob for s in leaked)
        assert "pass=[redacted]" in blob


# ── C3 (SEC-2 / FE-1): downloads ─────────────────────────────────────────────


def test_a_downloaded_executable_is_marked_and_flagged(eng):
    page = eng.site.url("/links", host="downloads.example")
    eng.op("dl-owner", "goto", url=page)
    clicked = eng.op("dl-owner", "click", selector="#exe")
    folder = eng.root / "workspace" / "dl-owner" / "downloads"
    assert _wait_for(lambda: any(folder.glob("setup*.exe")), 15)
    path = sorted(folder.glob("setup*.exe"))[0]
    eng.wait_until(
        lambda core: any(e["kind"] == "download" for e in eng.sink.of("event")),
        what="download event",
    )
    event = next(e for e in eng.sink.of("event") if e["kind"] == "download")
    assert event["dangerous"] is True
    agent_events = clicked.get("events", []) + eng.op("dl-owner", "echo").get(
        "events", []
    )
    notice = next(e for e in agent_events if e["kind"] == "download")
    assert "executable file" in notice["message"] and "do not run" in notice["message"]
    if sys.platform == "win32":
        zone = Path(f"{path}:Zone.Identifier").read_text(encoding="utf-8")
        assert "ZoneId=3" in zone
        assert f"HostUrl={eng.site.url('/setup.exe', host='downloads.example')}" in zone
        assert f"ReferrerUrl={page}" in zone

    # An inert file from this machine: no mark, not dangerous.
    eng.sink.clear()
    eng.op("dl-owner", "goto", url=eng.site.url("/links"))
    eng.op("dl-owner", "click", selector="#txt")
    assert _wait_for(lambda: any(folder.glob("notes*.txt")), 15)
    eng.wait_until(
        lambda core: any(e["kind"] == "download" for e in eng.sink.of("event")),
        what="txt event",
    )
    txt_event = next(e for e in eng.sink.of("event") if e["kind"] == "download")
    assert txt_event["dangerous"] is False
    if sys.platform == "win32":
        txt = sorted(folder.glob("notes*.txt"))[0]
        assert not os.path.exists(f"{txt}:Zone.Identifier")


def test_fallback_guard_script_blanks_every_loopback_spelling(eng):
    """security SEC-1: the init-script guard (used when browser-wide request
    interception is unavailable) recognises the same loopback spellings."""
    port = eng.site.port
    script = core_module._UI_GUARD_JS % (
        json.dumps([f"localhost:{port}"]),
        json.dumps([port]),
        "false",
    )
    other_port = core_module._UI_GUARD_JS % (
        json.dumps([f"localhost:{port + 1}"]),
        json.dumps([port + 1]),
        "false",
    )

    async def run_guard(tab, url, guard):
        await tab.page.goto(url, wait_until="domcontentloaded", timeout=10000)
        try:
            await tab.page.evaluate(guard)
        except Exception:
            pass  # the guard navigated away under the evaluation
        for _ in range(40):
            if tab.page.url == "about:blank":
                break
            await asyncio.sleep(0.05)
        return tab.page.url

    async def scenario(core):
        tab = await core.tab_for_owner("guard-agent")
        outcomes = {}
        for host in ("[::ffff:127.0.0.1]", "foo.localhost", "127.0.0.1"):
            url = f"http://{host}:{port}/page?t=UI"
            outcomes[host] = await run_guard(tab, url, script)
        outcomes["other port"] = await run_guard(
            tab, eng.site.url("/page?t=Other"), other_port
        )
        return outcomes

    outcomes = eng.call(scenario)
    for host in ("[::ffff:127.0.0.1]", "foo.localhost", "127.0.0.1"):
        assert outcomes[host] == "about:blank", outcomes
    assert outcomes["other port"].endswith("/page?t=Other"), outcomes


def test_owners_are_told_once_even_while_the_browser_is_stopped(eng):
    """C2: the one-time notice matches the browser's state."""
    eng.op("told-owner", "goto", url=eng.site.url("/page?t=Told"))
    eng.call(lambda core: core.close())
    listed = eng.op("told-owner", "tabs", action="list")
    assert listed["message"].startswith(core_module.CLOSED_NOTE)
    assert "not running" in listed["message"]
    again = eng.op("told-owner", "echo", timeout=120)  # relaunches
    assert again["status"] == "success"
    assert not again["message"].startswith("Note:")
