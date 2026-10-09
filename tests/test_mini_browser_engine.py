"""Mini Browser engine: host, core, stream, bridge, lifecycle and config.

The engine tests drive a real (headless) Chromium against a local
``http.server`` on 127.0.0.1 — no internet. Agent operations come from a
FAKE ops registry (the real ones are tested with the ops), the UI is a fake
sink, and every path (profile, workspace, settings writes) points into a temp
directory. Chromium tests skip when Playwright or its Chromium is missing.
"""

from __future__ import annotations

import asyncio
import collections
import concurrent.futures
import contextvars
import sys
import threading
import time
import types
from dataclasses import replace
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List

import pytest

import app.mini_browser as mini_browser_package
from app.mini_browser import bridge, config, lifecycle
from app.mini_browser import host as host_module
from app.mini_browser.config import MiniBrowserSettings
from app.mini_browser.core import BrowserCore
from app.mini_browser.errors import MiniBrowserError
from app.mini_browser.host import MiniBrowserHost

ORIGINAL_WORKSPACE_DIR = config.workspace_dir
SECRET = "Sup3r-Secret-Passw0rd"
SLOW_RESPONSE_S = 12.0


def run(coro, timeout: float = 60.0):
    async def bounded():
        return await asyncio.wait_for(coro, timeout)

    return asyncio.run(bounded())


async def _apply(fn, core):
    return fn(core)


# ═════════════════════════════════════════════════════════════════════════════
# Pure tests (no browser)
# ═════════════════════════════════════════════════════════════════════════════


def test_settings_are_validated_and_clamped():
    settings = MiniBrowserSettings.from_mapping(
        {
            "headless": "false",
            "adblock": 0,
            "max_fps": 500,
            "jpeg_quality": 5,
            "max_agent_tabs": float("nan"),
            "idle_shutdown_minutes": -3,
            "search_url": "javascript:alert(1)//{query}",
            "locale": "ja_JP",
            "channel": "MSEDGE",
            "unknown": 1,
        }
    )
    assert settings.headless is False
    assert settings.adblock is False
    assert settings.max_fps == 30
    assert settings.jpeg_quality == 30
    assert settings.max_agent_tabs == 6  # unusable -> default
    assert settings.idle_shutdown_minutes == 0
    assert settings.search_url == "https://duckduckgo.com/?q={query}"
    assert settings.locale == "ja-JP"
    assert settings.channel == "msedge"
    assert MiniBrowserSettings.from_mapping(None) == MiniBrowserSettings()
    assert (
        MiniBrowserSettings.from_mapping({"channel": "firefox"}).channel == "chromium"
    )
    assert MiniBrowserSettings.from_mapping(
        {"search_url": "https://x/?q={query}&{x}"}
    ).search_url == ("https://duckduckgo.com/?q={query}")


def test_load_and_save_settings_go_through_app_config(monkeypatch):
    from app import config as app_config

    saved = []
    monkeypatch.setattr(
        app_config,
        "get_mini_browser_settings",
        lambda: {"max_fps": 20, "headless": False},
    )
    monkeypatch.setattr(
        app_config, "set_mini_browser_setting", lambda k, v: saved.append((k, v))
    )
    settings = config.load_settings()
    assert settings.max_fps == 20 and settings.headless is False
    config.save_setting("max_fps", 99)
    assert saved == [("max_fps", 30)]
    with pytest.raises(ValueError):
        config.save_setting("not_a_setting", 1)

    def broken():
        raise RuntimeError("settings.json unreadable")

    monkeypatch.setattr(app_config, "get_mini_browser_settings", broken)
    assert config.load_settings() == MiniBrowserSettings()


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


def test_workspace_paths_follow_the_owner(monkeypatch, tmp_path):
    from app.config import AGENT_WORKSPACE_ROOT, APP_DATA_PATH

    chat_dir = tmp_path / "sessions" / "chat-1"
    _fake_agent_runtime(
        monkeypatch,
        sessions={
            "chat-1": types.SimpleNamespace(title="Chat", workspace_dir=str(chat_dir))
        },
        subagents={
            "sub_1234abcd": types.SimpleNamespace(
                parent_task_id="chat-1",
                agent_type="browser_agent",
                created_at="2026-01-01T00:00:00",
            )
        },
    )
    assert ORIGINAL_WORKSPACE_DIR("chat-1") == chat_dir
    assert (
        ORIGINAL_WORKSPACE_DIR("sub_1234abcd") == chat_dir
    )  # a sub-agent uses its parent's
    fallback = Path(AGENT_WORKSPACE_ROOT) / "mini_browser"
    assert ORIGINAL_WORKSPACE_DIR("unknown-session") == fallback
    assert ORIGINAL_WORKSPACE_DIR(None) == fallback
    assert config.profile_dir() == Path(APP_DATA_PATH) / "mini_browser_profile"
    record = config.subagent_record("sub_1234abcd")
    assert record == ("chat-1", "browser_agent", datetime(2026, 1, 1))
    assert config.subagent_record("chat-1") is None
    assert config.subagent_record("sub_missing") is None


def test_workspace_paths_without_agent_runtime(monkeypatch):
    from app.config import AGENT_WORKSPACE_ROOT

    monkeypatch.delitem(sys.modules, "app.internal_action_interface", raising=False)
    root = Path(AGENT_WORKSPACE_ROOT) / "mini_browser"
    assert ORIGINAL_WORKSPACE_DIR("main") == root
    assert config.subagent_record("sub_x") is None
    assert config.session_record("main") is None


def test_os_locale_is_a_language_tag(monkeypatch):
    tag = config.os_locale()
    assert tag and "_" not in tag and "." not in tag
    monkeypatch.setattr(config.locale, "getdefaultlocale", lambda: ("ja_JP", "cp932"))
    assert config.os_locale() == "ja-JP"


def test_bridge_without_sink_is_silent():
    bridge.unregister_ui_sink(bridge.current_sink())
    bridge.publish("state", {"x": 1})  # no sink: nothing happens
    assert bridge.has_viewers() is False

    class Broken:
        def has_viewers(self):
            raise RuntimeError("boom")

        def post(self, kind, payload):
            raise RuntimeError("boom")

    sink = Broken()
    bridge.register_ui_sink(sink)
    try:
        bridge.publish("frame", {})  # never raises
        assert bridge.has_viewers() is False
    finally:
        bridge.unregister_ui_sink(sink)
    assert bridge.current_sink() is None


def test_bridge_normalises_ui_origins():
    try:
        bridge.set_ui_origins(
            ["LOCALHOST:7926", "http://127.0.0.1:7926", "[::1]:7926", "", "x:bad"]
        )
        assert bridge.ui_origins() == frozenset(
            {"localhost:7926", "127.0.0.1:7926", "[::1]:7926"}
        )
    finally:
        bridge.set_ui_origins([])
    assert bridge.ui_origins() == frozenset()


def test_lifecycle_hooks_never_start_the_browser(monkeypatch):
    monkeypatch.setattr(host_module, "_host", None)
    lifecycle.on_run_state("main", "running")
    lifecycle.release_owner("main")
    lifecycle.cancel_owner("main")
    lifecycle.on_run_state("", "running")  # junk is ignored too
    asyncio.run(lifecycle.shutdown(timeout=1.0))
    assert host_module._host is None
    assert host_module.get_host_if_started() is None


def test_host_runs_calls_on_its_own_thread_and_loop():
    class Probe:
        def __init__(self):
            self.thread = threading.current_thread().name
            self.value = 0

        async def bump(self):
            self.value += 1
            return threading.current_thread().name

    host = MiniBrowserHost(core_factory=Probe)
    marker: contextvars.ContextVar = contextvars.ContextVar("marker", default=None)
    try:
        assert not host.is_running()
        host.start()
        host.start()  # idempotent
        assert host.is_running()
        assert host.core.thread == host_module.THREAD_NAME

        async def from_main_loop():
            marker.set("caller")
            name = await host.call(lambda core: core.bump())
            seen = await host.call(lambda core: _apply(lambda c: marker.get(), core))
            nested = await host.call(lambda core: host.call(lambda again: again.bump()))
            return name, seen, nested

        assert run(from_main_loop()) == ("mini-browser", "caller", "mini-browser")

        def subagent_style():  # a worker thread with its own event loop
            return asyncio.run(host.call(lambda core: core.bump()))

        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            names = list(pool.map(lambda _: subagent_style(), range(4)))
        assert names == ["mini-browser"] * 4
        assert host.core.value == 6

        # submit: fire-and-forget, in a clean context (no caller variables).
        marker.set("leaked?")
        future = host.submit(lambda core: _apply(lambda c: marker.get(), core))
        assert future.result(timeout=5) is None

        async def fails(core):
            raise ValueError("boom")

        with pytest.raises(ValueError):
            host.submit(fails).result(timeout=5)

        async def cancelled_caller():
            started = []

            async def slow(core):
                started.append(True)
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    started.append("cancelled")
                    raise
                return "never"

            task = asyncio.ensure_future(host.call(slow))
            while not started:
                await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            for _ in range(100):
                if "cancelled" in started:
                    break
                await asyncio.sleep(0.02)
            return started

        assert run(cancelled_caller()) == [True, "cancelled"]
    finally:
        asyncio.run(host.shutdown(timeout=5))
    assert not host.is_running()
    with pytest.raises(RuntimeError):
        host.submit(lambda core: core.bump(), start=False).result(timeout=1)


# ═════════════════════════════════════════════════════════════════════════════
# Real Chromium
# ═════════════════════════════════════════════════════════════════════════════


class Site:
    """A local web site with the pages the engine tests need."""

    def __init__(self) -> None:
        self.hits: collections.Counter = collections.Counter()
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path, _, query = self.path.partition("?")
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
                site.hits[(host, path)] += 1
                port = self.server.server_address[1]
                if path == "/page":
                    title = query.split("t=", 1)[1] if "t=" in query else "Page"
                    self.html(f"<title>{title}</title><h1>{title}</h1>")
                elif path == "/slow":
                    time.sleep(SLOW_RESPONSE_S)
                    self.html("<title>Slow</title>slow")
                elif path == "/links":
                    self.html(
                        "<title>Links</title>"
                        "<a id='pop' href='/page?t=Popup' target='_blank'>new tab</a> "
                        "<a id='dl' href='/download'>download</a>"
                    )
                elif path == "/download":
                    body = b"hello download"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header(
                        "Content-Disposition", 'attachment; filename="re:port?.txt"'
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/ui":
                    self.html(
                        "<title>CraftBot UI</title><script>document.title='UI RAN'</script>"
                    )
                elif path == "/to-ui":
                    self.send_response(302)
                    self.send_header("Location", f"http://localhost:{port}/ui")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif path == "/ads":
                    self.html(
                        "<title>Ads</title><script src='/cache-test.js'></script>"
                        f"<img id='ad' src='http://ads.doubleclick.net:{port}/ad.png'>"
                        "<img id='ok' src='/ok.png'>"
                    )
                elif path == "/cache-test.js":
                    self.reply(
                        b"window.__cached = 1;",
                        "application/javascript",
                        "public, max-age=3600",
                    )
                elif path == "/animated":
                    self.html(
                        "<title>Anim</title><div id='box' style='width:80px;height:80px;"
                        "background:#36f;position:absolute'></div><script>let t = 0;"
                        "setInterval(() => { t += 7; box.style.left = (t % 500) + 'px'; }, 16)"
                        "</script>"
                    )
                elif path == "/clicks":
                    self.html(
                        "<title>Clicks</title><body style='margin:0;height:100vh'><script>"
                        "window.clicks = []; document.addEventListener('mousedown', e => "
                        "window.clicks.push([e.clientX, e.clientY, e.button, e.detail]));"
                        "</script></body>"
                    )
                else:
                    self.reply(b"\x89PNG\r\n\x1a\n", "image/png", "no-store")

            def html(self, text: str) -> None:
                self.reply(text.encode("utf-8"), "text/html; charset=utf-8", "no-store")

            def reply(self, body: bytes, content_type: str, cache_control: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", cache_control)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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
    """The UI side of the bridge, recording what the browser publishes."""

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
    await tab.page.goto(url, wait_until="domcontentloaded", timeout=20000)
    return {"status": "success", "message": "navigated", "url": tab.page.url}


async def op_eval(core, tab, *, script):
    value = await tab.page.evaluate(script)
    return {"status": "success", "message": "evaluated", "value": value}


async def op_click(core, tab, *, selector):
    await tab.page.click(selector, timeout=10000)
    return {"status": "success", "message": "clicked"}


async def op_secret(core, tab):
    tab.filled_secrets.append(SECRET)
    return {
        "status": "success",
        "message": f"typed {SECRET}",
        "nested": [{"v": f"<{SECRET}>"}],
    }


async def op_missing(core, tab):
    raise MiniBrowserError("MINI_BROWSER_ELEMENT_NOT_FOUND", element_id=7)


async def op_boom(core, tab):
    raise RuntimeError(f"kaboom {SECRET}\nCall log: fill('{SECRET}')")


async def op_wait(core, tab, *, for_user=False):
    while for_user and tab.user_control:
        await asyncio.sleep(0.05)
    return {"status": "success", "message": "waited"}


async def op_requests(core, tab, *, url, times=3):
    """Load ``url`` ``times`` times and report failed requests."""
    failures: List[tuple] = []
    tab.page.on(
        "requestfailed", lambda request: failures.append((request.url, request.failure))
    )
    for _ in range(times):
        await tab.page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await tab.page.wait_for_function(
            "document.getElementById('ok').complete", timeout=10000
        )
        await asyncio.sleep(0.3)
    return {"status": "success", "message": "loaded", "failures": failures}


FAKE_OPS = {
    "echo": op_echo,
    "goto": op_goto,
    "eval": op_eval,
    "click": op_click,
    "secret": op_secret,
    "missing": op_missing,
    "boom": op_boom,
    "wait": op_wait,
    "requests": op_requests,
}


class Engine:
    def __init__(
        self, host: MiniBrowserHost, sink: FakeSink, site: Site, saved: list, root: Path
    ):
        self.host, self.sink, self.site, self.saved, self.root = (
            host,
            sink,
            site,
            saved,
            root,
        )

    def call(self, fn, timeout: float = 60.0):
        return run(self.host.call(fn), timeout)

    def inspect(self, fn):
        return self.call(lambda core: _apply(fn, core))

    def op(self, owner: str, op: str, timeout: float = 60.0, **params):
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
                tabs = self.inspect(
                    lambda core: [
                        (t.id, t.owner, t.opener_id, t.url, t.crashed)
                        for t in core.tabs.values()
                    ]
                )
                raise AssertionError(f"timed out waiting for {what}; tabs={tabs}")
            time.sleep(0.05)


@pytest.fixture(scope="module")
def site():
    server = Site()
    yield server
    server.close()


@pytest.fixture(scope="module")
def engine(site, tmp_path_factory):
    pytest.importorskip("playwright.async_api")
    patch = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp("mini_browser_engine")
    saved: list = []
    patch.setattr(config, "profile_dir", lambda: root / "profile")
    patch.setattr(
        config, "workspace_dir", lambda owner: root / "workspace" / (owner or "_user")
    )
    patch.setattr(config, "save_setting", lambda key, value: saved.append((key, value)))
    sink = FakeSink()
    bridge.register_ui_sink(sink)
    settings = MiniBrowserSettings(
        idle_shutdown_minutes=0, max_agent_tabs=3, max_fps=10
    )
    host = MiniBrowserHost(
        lambda: BrowserCore(
            settings=settings,
            ops_registry=FAKE_OPS,
            launch_args=("--host-resolver-rules=MAP ads.doubleclick.net 127.0.0.1",),
        )
    )
    patch.setattr(host_module, "_host", host)  # lifecycle.* and the bridge reach it
    engine = Engine(host, sink, site, saved, root)
    try:
        engine.call(lambda core: core.start(), timeout=120)
    except MiniBrowserError as exc:
        asyncio.run(host.shutdown(timeout=10))
        bridge.unregister_ui_sink(sink)
        patch.undo()
        if exc.code in (
            "MINI_BROWSER_CHROMIUM_MISSING",
            "MINI_BROWSER_PLAYWRIGHT_MISSING",
        ):
            pytest.skip(f"Chromium unavailable ({exc.code})")
        raise
    yield engine
    asyncio.run(host.shutdown(timeout=20))
    bridge.unregister_ui_sink(sink)
    bridge.set_ui_origins([])
    patch.undo()


async def _reset(core: BrowserCore) -> None:
    """Back to one idle user tab, default view and viewport."""
    await core.ensure_started()
    for tab in list(core.tabs.values()):
        if tab.user_control:
            await core.ui_control(tab.id, False)
    for owner in {t.owner for t in core.tabs.values() if t.owner}:
        core.on_run_state(owner, "idle")
        core.release_owner(owner, close_tabs=True)
    for _ in range(200):
        if not any(t.owner for t in core.tabs.values()) and core.tabs:
            break
        await asyncio.sleep(0.02)
    for tab in list(core.tabs.values())[1:]:
        await core.ui_close_tab(tab.id)
    await core.set_viewport(1280, 800)
    await core.ui_view(None, True)
    for tab in core.tabs.values():
        tab.last_user_input = 0.0


@pytest.fixture
def eng(engine):
    engine.sink.viewers = False
    engine.call(_reset)
    engine.sink.clear()
    return engine


# ── lifecycle, status, profile ───────────────────────────────────────────────


def test_start_close_are_idempotent_with_clear_status(eng, tmp_path, monkeypatch):
    time.sleep(0.2)  # let the shared engine's debounced state flush land first
    sink = FakeSink()
    bridge.register_ui_sink(sink)
    monkeypatch.setattr(config, "profile_dir", lambda: tmp_path / "own-profile")
    host = MiniBrowserHost(
        lambda: BrowserCore(settings=MiniBrowserSettings(idle_shutdown_minutes=0))
    )
    try:
        state = run(host.call(lambda core: _apply(lambda c: c.state(), core)))
        assert state["status"] == "stopped" and state["tabs"] == []
        with pytest.raises(MiniBrowserError) as info:
            run(host.call(lambda core: core.ui_history(None, "back")))
        assert info.value.code == "MINI_BROWSER_NOT_RUNNING"

        async def start_twice(core):
            await asyncio.gather(core.start(), core.start(), core.ensure_started())
            return core._context, core.status, len(core.tabs)

        context, status, tabs = run(host.call(start_twice), 120)
        assert status == "ready" and tabs == 1
        assert (
            run(host.call(lambda core: _apply(lambda c: c._context, core))) is context
        )
        run(host.call(lambda core: core.start()))  # already running: no-op
        run(host.call(lambda core: core.close()))
        run(host.call(lambda core: core.close()))  # twice is fine
        assert run(
            host.call(lambda core: _apply(lambda c: (c.status, c.tabs), core))
        ) == ("stopped", {})
        # State publishing is debounced (~50 ms): changes inside that window
        # coalesce into the latest state, so give "stopped" time to go out.
        time.sleep(0.2)
        run(host.call(lambda core: core.start()), 120)  # the profile lock was released
        assert run(host.call(lambda core: _apply(lambda c: c.status, core))) == "ready"
        time.sleep(0.2)
        statuses = [s["status"] for s in sink.of("state")]
        remaining = iter(statuses)
        expected = ["starting", "ready", "stopped", "starting", "ready"]
        assert all(status in remaining for status in expected), statuses
        assert statuses[-1] == "ready"
    finally:
        asyncio.run(host.shutdown(timeout=15))
        bridge.register_ui_sink(eng.sink)
    assert not host.is_running()


def test_a_second_browser_on_the_same_profile_is_refused(eng):
    other = MiniBrowserHost(
        lambda: BrowserCore(settings=MiniBrowserSettings(idle_shutdown_minutes=0))
    )
    try:
        with pytest.raises(MiniBrowserError) as info:
            run(other.call(lambda core: core.start()), 60)
        assert info.value.code == "MINI_BROWSER_PROFILE_IN_USE"
        state = run(other.call(lambda core: _apply(lambda c: c.state(), core)))
        assert state["status"] == "error"
        assert state["error"]["code"] == "MINI_BROWSER_PROFILE_IN_USE"
    finally:
        asyncio.run(other.shutdown(timeout=10))
    assert eng.inspect(lambda core: core.status) == "ready"


def test_state_payload_shape(eng):
    eng.op("shape-agent", "goto", url=eng.site.url("/page?t=Shape"))
    state = eng.inspect(lambda core: core.state())
    assert set(state) == {
        "status",
        "error",
        "sessionId",
        "adblock",
        "viewedTabId",
        "follow",
        "viewport",
        "tabs",
        "settings",
    }
    assert state["status"] == "ready" and state["error"] is None
    assert state["sessionId"] == "mini_browser"
    assert state["viewport"] == {"width": 1280, "height": 800}
    assert set(state["settings"]) == {"humanlike", "showCursor"}
    assert state["viewedTabId"] in {t["id"] for t in state["tabs"]}
    for tab in state["tabs"]:
        assert set(tab) == {
            "id",
            "url",
            "title",
            "loading",
            "owner",
            "parentOwner",
            "ownerLabel",
            "ownerKind",
            "busy",
            "userControl",
            "canGoBack",
            "canGoForward",
            "crashed",
        }
    mine = next(t for t in state["tabs"] if t["owner"] == "shape-agent")
    assert mine["ownerKind"] == "session" and mine["ownerLabel"] == "Chat"
    assert mine["parentOwner"] is None
    eng.wait_until(
        lambda core: (
            next(t for t in core.tabs.values() if t.owner == "shape-agent").title
            == "Shape"
        ),
        what="title tracking",
    )
    assert any(
        t["title"] == "Shape" for t in eng.inspect(lambda core: core.state())["tabs"]
    )
    # State changes reach the UI (debounced).
    eng.wait_until(
        lambda core: any(
            t["owner"] == "shape-agent" for s in eng.sink.of("state") for t in s["tabs"]
        ),
        what="state",
    )


# ── owners and tabs ──────────────────────────────────────────────────────────


def test_two_owners_get_separate_tabs_and_pages(eng):
    async def both(core):
        return await asyncio.gather(
            core.agent_op("owner-a", "goto", {"url": eng.site.url("/page?t=A")}),
            core.agent_op("owner-b", "goto", {"url": eng.site.url("/page?t=B")}),
        )

    a, b = eng.call(both)
    assert a["status"] == "success" and b["status"] == "success"
    assert a["tab"]["id"] != b["tab"]["id"]
    again_a = eng.op("owner-a", "echo")
    again_b = eng.op("owner-b", "echo")
    assert again_a["tab"]["id"] == a["tab"]["id"] and again_a["url"].endswith("t=A")
    assert again_b["tab"]["id"] == b["tab"]["id"] and again_b["url"].endswith("t=B")
    listing = eng.op("owner-a", "tabs", action="list")
    mine = [t for t in listing["tabs"] if t["mine"]]
    assert [t["id"] for t in mine] == [a["tab"]["id"]] and mine[0]["active"]
    assert listing["tabs"][a["tab"]["index"]]["id"] == a["tab"]["id"]


def test_viewed_tab_claim_rule(eng):
    user_tab = eng.call(lambda core: core.ui_new_tab())
    eng.inspect(
        lambda core: setattr(
            core.tabs[user_tab], "last_user_input", time.monotonic() - 60
        )
    )
    claimed = eng.op("claimer", "echo")
    assert claimed["tab"]["id"] == user_tab  # an idle user tab in view is claimed

    busy_user_tab = eng.call(lambda core: core.ui_new_tab())  # the user is using it
    other = eng.op("other-agent", "echo")
    assert other["tab"]["id"] not in (user_tab, busy_user_tab)
    assert eng.tab(busy_user_tab).owner is None

    # The claimer goes stale (10 min unused, not running): its tab, in view, is taken.
    def go_stale(core):
        core.tabs[user_tab].last_agent_use = time.monotonic() - 601

    eng.inspect(go_stale)
    eng.call(lambda core: core.ui_switch_tab(user_tab))
    eng.inspect(
        lambda core: setattr(
            core.tabs[user_tab], "last_user_input", time.monotonic() - 60
        )
    )
    eng.inspect(lambda core: core.on_run_state("claimer", "running"))
    blocked = eng.op("third-agent", "echo")
    assert blocked["tab"]["id"] != user_tab  # a running owner keeps its tab
    eng.inspect(lambda core: core.on_run_state("claimer", "idle"))
    eng.call(lambda core: core.ui_switch_tab(user_tab))
    taken = eng.op("fourth-agent", "echo")
    assert taken["tab"]["id"] == user_tab
    assert eng.op("claimer", "echo")["tab"]["id"] != user_tab


def test_max_tabs_per_owner(eng):
    first = eng.op("tabby", "echo")
    second = eng.op("tabby", "tabs", action="new", url=eng.site.url("/page?t=Second"))
    third = eng.op("tabby", "tabs", action="new")
    assert first["status"] == second["status"] == third["status"] == "success"
    assert second["tab"]["id"] != first["tab"]["id"]
    refused = eng.op("tabby", "tabs", action="new")
    assert refused["status"] == "error"
    assert refused["error_code"] == "MINI_BROWSER_TOO_MANY_TABS"
    # Switch / close stay within the owner's own tabs.
    switched = eng.op("tabby", "tabs", action="switch", tab=first["tab"]["index"])
    assert (
        switched["status"] == "success" and switched["tab"]["id"] == first["tab"]["id"]
    )
    assert eng.op("tabby", "echo")["tab"]["id"] == first["tab"]["id"]
    stranger = eng.op("stranger", "tabs", action="close", tab=first["tab"]["index"])
    assert stranger["error_code"] == "MINI_BROWSER_TAB_OWNED"
    closed = eng.op("tabby", "tabs", action="close")
    assert closed["status"] == "success"
    assert all(t["id"] != first["tab"]["id"] for t in closed["tabs"])
    assert (
        eng.op("tabby", "tabs", action="switch", tab=99)["error_code"]
        == "MINI_BROWSER_TAB_NOT_FOUND"
    )


def test_release_owner_closes_its_tabs(eng):
    eng.op("leaver", "echo")
    eng.op("leaver", "tabs", action="new")
    assert (
        eng.inspect(lambda core: sum(t.owner == "leaver" for t in core.tabs.values()))
        == 2
    )
    lifecycle.release_owner("leaver")
    eng.wait_until(
        lambda core: not any(t.owner == "leaver" for t in core.tabs.values()),
        what="release",
    )
    assert eng.inspect(lambda core: len(core.tabs)) >= 1

    # A tab the user is looking at survives as a user tab.
    kept = eng.op("leaver-2", "echo")["tab"]["id"]
    eng.call(lambda core: core.ui_switch_tab(kept))
    eng.sink.viewers = True
    eng.inspect(lambda core: core.release_owner("leaver-2", close_tabs=True))
    tab = eng.tab(kept)
    assert tab is not None and tab.owner is None


def test_owner_labels_and_kinds(eng, monkeypatch):
    _fake_agent_runtime(
        monkeypatch,
        sessions={
            "chat-7": types.SimpleNamespace(title="Holiday plans", workspace_dir=None),
            "main": types.SimpleNamespace(title="Main", workspace_dir=None),
        },
        subagents={
            "sub_label01": types.SimpleNamespace(
                parent_task_id="chat-7",
                agent_type="browser_agent",
                created_at=datetime.utcnow().isoformat(),
            )
        },
    )
    for owner in ("chat-7", "main", "mini_browser", "sub_label01"):
        eng.op(owner, "tabs", action="new")
    tabs = {
        t["owner"]: t
        for t in eng.inspect(lambda core: core.state())["tabs"]
        if t["owner"]
    }
    assert (tabs["chat-7"]["ownerKind"], tabs["chat-7"]["ownerLabel"]) == (
        "session",
        "Holiday plans",
    )
    assert tabs["main"]["ownerKind"] == "main"
    assert (tabs["mini_browser"]["ownerKind"], tabs["mini_browser"]["ownerLabel"]) == (
        "mini_browser",
        "Mini Browser",
    )
    assert tabs["sub_label01"]["ownerKind"] == "subagent"
    assert (
        tabs["sub_label01"]["ownerLabel"]
        == "browser_agent (sub-agent of Holiday plans)"
    )


# ── pages: viewport, dialogs, downloads, popups ──────────────────────────────


def test_viewport_is_applied_to_every_tab_and_maps_input(eng):
    eng.op("viewer-agent", "goto", url=eng.site.url("/clicks"))
    eng.call(lambda core: core.set_viewport(1000, 700))
    new_tab = eng.call(lambda core: core.ui_new_tab(eng.site.url("/clicks")))
    sizes = eng.inspect(
        lambda core: {t.id: t.page.viewport_size for t in core.tabs.values()}
    )
    assert all(size == {"width": 1000, "height": 700} for size in sizes.values()), sizes
    assert eng.inspect(lambda core: core.state()["viewport"]) == {
        "width": 1000,
        "height": 700,
    }
    eng.wait_until(
        lambda core: core.tabs[new_tab].url.endswith("/clicks"), what="page load"
    )

    for event in (
        {"kind": "mouse", "action": "move", "x": 0.25, "y": 0.5},
        {
            "kind": "mouse",
            "action": "down",
            "x": 0.25,
            "y": 0.5,
            "button": "left",
            "clickCount": 1,
        },
        {
            "kind": "mouse",
            "action": "up",
            "x": 0.25,
            "y": 0.5,
            "button": "left",
            "clickCount": 1,
        },
        # Out-of-range coordinates are clamped to the frame.
        {
            "kind": "mouse",
            "action": "down",
            "x": 0.5,
            "y": -3,
            "button": "right",
            "clickCount": 2,
        },
        {
            "kind": "mouse",
            "action": "up",
            "x": 0.5,
            "y": -3,
            "button": "right",
            "clickCount": 2,
        },
        # Junk is ignored, never sent to the driver (NaN would kill it).
        {"kind": "mouse", "action": "down", "x": float("nan"), "y": 0.5},
        {"kind": "mouse", "action": "down", "x": float("inf"), "y": 0.5},
        {"kind": "wheel", "x": "nope", "y": 0.5, "dx": 0, "dy": 100},
        {"kind": "telepathy"},
    ):
        eng.call(lambda core, e=event: core.ui_input(new_tab, e))
    clicks = eng.call(lambda core: core.tabs[new_tab].page.evaluate("window.clicks"))
    assert clicks == [[250, 350, 0, 1], [500, 0, 2, 2]]
    assert eng.op("viewer-agent", "echo")["status"] == "success"  # the driver survived

    eng.call(lambda core: core.ui_input(new_tab, {"kind": "text", "text": "日本語 ok"}))
    eng.call(lambda core: core.ui_input(new_tab, {"kind": "key", "key": "Process"}))
    eng.call(
        lambda core: core.ui_input(
            new_tab, {"kind": "key", "key": "a", "modifiers": {"ctrl": True}}
        )
    )


def test_dialogs_are_answered_and_reported(eng):
    eng.op("dialog-agent", "goto", url=eng.site.url("/page?t=Dialogs"))
    result = eng.op(
        "dialog-agent",
        "eval",
        script="() => { alert('Hello there'); const ok = confirm('Delete it?');"
        " const name = prompt('Your name?', 'x'); return [ok, name]; }",
    )
    assert result["status"] == "success"
    assert result["value"] == [True, None]  # confirm accepted, prompt dismissed
    eng.wait_until(
        lambda core: (
            len([e for e in eng.sink.of("event") if e["kind"] == "dialog"]) >= 3
        ),
        what="dialog events",
    )
    messages = [e["message"] for e in eng.sink.of("event") if e["kind"] == "dialog"]
    assert any(
        "alert" in m and "Hello there" in m and "accepted" in m for m in messages
    )
    assert any("confirm" in m and "Delete it?" in m for m in messages)
    assert any("prompt" in m and "dismissed" in m for m in messages)
    later = eng.op("dialog-agent", "echo")
    agent_events = (result.get("events") or []) + (later.get("events") or [])
    assert sum(e["kind"] == "dialog" for e in agent_events) == 3


def test_download_is_saved_into_the_owners_workspace(eng):
    eng.op("dl-agent", "goto", url=eng.site.url("/links"))
    assert eng.op("dl-agent", "click", selector="#dl")["status"] == "success"
    target = eng.root / "workspace" / "dl-agent" / "downloads"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not any(target.glob("*.txt")):
        time.sleep(0.1)
    files = sorted(target.glob("*.txt"))
    assert len(files) == 1
    name = files[0].name
    assert name.startswith("re") and name.endswith(".txt")
    assert not set(name) & set(':?"<>|*')  # unsafe characters replaced
    eng.wait_until(
        lambda core: any(e["kind"] == "download" for e in eng.sink.of("event")),
        what="download event",
    )
    assert files[0].read_bytes() == b"hello download"
    event = next(e for e in eng.sink.of("event") if e["kind"] == "download")
    assert event["path"] == str(files[0])
    later = eng.op("dl-agent", "echo")
    assert any(
        e["kind"] == "download" and e.get("path") == str(files[0])
        for e in later["events"]
    )
    # A second download with the same name gets a fresh file, never overwrites.
    eng.op("dl-agent", "click", selector="#dl")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and len(list(target.glob("*.txt"))) < 2:
        time.sleep(0.1)
    stem = name[: -len(".txt")]
    assert sorted(p.name for p in target.glob("*.txt")) == [f"{stem} (1).txt", name]


def test_popup_inherits_the_openers_owner(eng):
    opener = eng.op("pop-agent", "goto", url=eng.site.url("/links"))
    eng.op("pop-agent", "click", selector="#pop")
    popup_id = eng.wait_until(
        lambda core: next(
            (
                t.id
                for t in core.tabs.values()
                if t.owner == "pop-agent" and t.id != opener["tab"]["id"]
            ),
            None,
        ),
        what="popup tab",
    )
    eng.wait_until(
        lambda core: core.tabs[popup_id].url.endswith("t=Popup"), what="popup load"
    )
    popup = eng.tab(popup_id)
    assert popup.opener_id == opener["tab"]["id"]
    assert popup.owner_kind == "session"
    after = eng.op("pop-agent", "echo")
    assert after["tab"]["id"] == popup_id  # the agent continues in the new tab
    assert after["url"].endswith("/page?t=Popup")
    assert any(e["kind"] == "popup" for e in after["events"])
    closed = eng.op("pop-agent", "tabs", action="close")
    assert closed["status"] == "success"
    assert (
        eng.op("pop-agent", "echo")["tab"]["id"] == opener["tab"]["id"]
    )  # back to the opener


# ── safety: UI origins, ad blocking, secrets ─────────────────────────────────


def _blocked_events(eng, tab_id):
    return [
        e
        for e in eng.sink.of("event")
        if e["kind"] == "blocked" and e["tabId"] == tab_id
    ]


def test_ui_origin_navigation_redirect_and_popup_are_blocked(eng):
    site = eng.site
    bridge.set_ui_origins([f"localhost:{site.port}"])
    try:
        eng.call(lambda core: core.refresh_network_rules())
        before = site.hits[("localhost", "/ui")]
        with pytest.raises(MiniBrowserError) as info:
            eng.call(lambda core: core.ui_navigate(None, f"localhost:{site.port}/ui"))
        assert info.value.code == "MINI_BROWSER_BLOCKED_URL"

        # An agent (or a page) navigating there anyway: the request never
        # leaves Chromium, the tab shows an error page, a notice is raised.
        agent = eng.op("ui-agent", "goto", url=site.url("/ui", host="localhost"))
        assert agent["status"] == "error"
        tab_id = agent["tab"]["id"]
        eng.wait_until(lambda core: _blocked_events(eng, tab_id), what="blocked event")
        assert eng.inspect(lambda core: core.tabs[tab_id].page.url).startswith(
            "chrome-error:"
        )

        redirected = eng.op("ui-agent", "goto", url=site.url("/to-ui"))
        assert redirected["status"] == "error"
        assert site.hits[("127.0.0.1", "/to-ui")] >= 1
        # Chromium commits its error page a moment after a blocked request
        # fails; navigating before that would be interrupted by it.
        eng.wait_until(
            lambda core: len(_blocked_events(eng, tab_id)) == 2, what="2nd block"
        )

        opener = eng.op("ui-agent", "goto", url=site.url("/page?t=Opener"))
        assert opener["status"] == "success", opener
        opened = eng.op(
            "ui-agent",
            "eval",
            script=f"() => !!window.open('{site.url('/ui', 'localhost')}')",
        )
        assert opened["value"] is True, opened
        popup_id = eng.wait_until(
            lambda core: next(
                (
                    t.id
                    for t in core.tabs.values()
                    if t.owner == "ui-agent" and t.opener_id == tab_id
                ),
                None,
            ),
            what="popup",
        )
        eng.wait_until(
            lambda core: _blocked_events(eng, popup_id), what="popup blocked"
        )
        assert site.hits[("localhost", "/ui")] == before  # the UI was never served
        assert len(_blocked_events(eng, tab_id)) == 2  # one notice per navigation
        eng.wait_until(
            lambda core: core.tabs[popup_id].page.url.startswith("chrome-error:"),
            what="popup error page",
        )
        # Other ports / hosts stay reachable, in the popup tab too.
        fine = eng.op("ui-agent", "goto", url=site.url("/page?t=Fine"))
        assert fine["status"] == "success", fine
    finally:
        bridge.set_ui_origins([])
        eng.call(lambda core: core.refresh_network_rules())


def test_guard_sends_a_loaded_forbidden_page_away(eng, tmp_path):
    local = tmp_path / "local.html"
    local.write_text("<title>Local file</title>secret notes", encoding="utf-8")
    result = eng.op("file-agent", "goto", url=local.as_uri())  # bypasses the URL policy
    tab_id = result["tab"]["id"]
    eng.wait_until(lambda core: _blocked_events(eng, tab_id), what="blocked event")
    eng.wait_until(
        lambda core: core.tabs[tab_id].page.url == "about:blank", what="guard"
    )
    assert "file" in _blocked_events(eng, tab_id)[0]["message"]
    later = eng.op("file-agent", "echo")
    assert any(e["kind"] == "blocked" for e in later["events"])


def test_adblock_blocks_ads_without_disabling_the_cache(eng):
    eng.call(lambda core: core.set_adblock(True))
    assert eng.saved[-1] == ("adblock", True)
    result = eng.op("ad-agent", "requests", url=eng.site.url("/ads"), times=3)
    assert result["status"] == "success"
    blocked = [
        url
        for url, failure in result["failures"]
        if failure and ("inspector" in failure or "BLOCKED_BY_CLIENT" in failure)
    ]
    assert any("ads.doubleclick.net" in url for url in blocked)
    assert eng.site.hits[("127.0.0.1", "/cache-test.js")] == 1  # HTTP cache still on
    assert eng.site.hits[("ads.doubleclick.net", "/ad.png")] == 0

    eng.call(lambda core: core.set_adblock(False))
    assert eng.saved[-1] == ("adblock", False)
    assert eng.inspect(lambda core: core.state()["adblock"]) is False
    off = eng.op("ad-agent", "requests", url=eng.site.url("/ads"), times=1)
    assert not any(
        failure and "inspector" in failure for _url, failure in off["failures"]
    )
    eng.call(lambda core: core.set_adblock(True))


def test_secrets_never_leave_in_results_state_or_events(eng):
    typed = eng.op("secret-agent", "secret")
    assert SECRET not in str(typed)
    assert "[redacted]" in typed["message"] and "[redacted]" in typed["nested"][0]["v"]
    failed = eng.op("secret-agent", "boom")
    assert (
        failed["status"] == "error" and failed["error_code"] == "MINI_BROWSER_INTERNAL"
    )
    assert SECRET not in str(failed) and "Call log" not in failed["message"]
    eng.op("secret-agent", "goto", url=eng.site.url(f"/page?t={SECRET}"))
    tab_id = eng.op("secret-agent", "echo")["tab"]["id"]
    eng.wait_until(lambda core: SECRET in core.tabs[tab_id].title, what="title")
    state = eng.inspect(lambda core: core.state())
    assert SECRET not in str(state) and SECRET not in str(
        eng.op("secret-agent", "tabs", action="list")
    )
    eng.op("secret-agent", "eval", script=f"() => alert('pw is {SECRET}')")
    eng.wait_until(
        lambda core: any("pw is" in e["message"] for e in eng.sink.of("event")),
        what="event",
    )
    assert SECRET not in str(eng.sink.of("event")) and SECRET not in str(
        eng.sink.of("state")
    )


def test_errors_carry_the_tab_and_a_fresh_observation(eng, monkeypatch):
    observed = []

    async def fake_observe(core, tab, *, compact):
        observed.append(compact)
        return {"url": tab.page.url, "elements": []}

    module = types.ModuleType("app.mini_browser.observe")
    module.observe = fake_observe
    monkeypatch.setitem(sys.modules, "app.mini_browser.observe", module)
    monkeypatch.setattr(mini_browser_package, "observe", module, raising=False)
    eng.op("err-agent", "goto", url=eng.site.url("/page?t=Observed"))
    observed.clear()
    result = eng.op("err-agent", "missing")
    assert result["status"] == "error"
    assert result["error_code"] == "MINI_BROWSER_ELEMENT_NOT_FOUND"
    assert "7" in result["message"]
    assert result["page"]["url"].endswith("/page?t=Observed")
    assert observed == [True]
    unknown = eng.op("err-agent", "fly")
    assert unknown["error_code"] == "MINI_BROWSER_INVALID_INPUT"


# ── user control, cancellation, revocation ───────────────────────────────────


def test_user_control_pauses_the_agent(eng):
    tab_id = eng.op("uc-agent", "goto", url=eng.site.url("/clicks"))["tab"]["id"]
    eng.call(lambda core: core.ui_control(tab_id, True))
    refused = eng.op("uc-agent", "echo")
    assert refused["error_code"] == "MINI_BROWSER_USER_IN_CONTROL"
    assert refused["tab"]["id"] == tab_id
    assert eng.inspect(
        lambda core: core.state()["tabs"][core._tab_index(core.tabs[tab_id])][
            "userControl"
        ]
    )

    async def wait_for_user(core):
        waiting = asyncio.ensure_future(
            core.agent_op("uc-agent", "wait", {"for_user": True})
        )
        await asyncio.sleep(0.3)
        assert not waiting.done()
        await core.ui_control(tab_id, False)
        return await asyncio.wait_for(waiting, 5)

    waited = eng.call(wait_for_user)
    assert waited["status"] == "success"
    later = eng.op("uc-agent", "echo")
    assert later["status"] == "success"
    notices = (waited.get("events") or []) + (later.get("events") or [])
    assert any("handed control back" in e["message"] for e in notices)

    # Input on a tab whose agent is running takes control automatically;
    # hovering does not.
    lifecycle.on_run_state("uc-agent", "running")
    eng.wait_until(lambda core: core._run_busy("uc-agent"), what="run state")
    eng.call(
        lambda core: core.ui_input(
            tab_id, {"kind": "mouse", "action": "move", "x": 0.5, "y": 0.5}
        )
    )
    assert eng.tab(tab_id).user_control is False
    eng.call(lambda core: core.ui_input(tab_id, {"kind": "key", "key": "Tab"}))
    assert eng.tab(tab_id).user_control is True
    lifecycle.on_run_state("uc-agent", "idle")


def test_cancel_owner_cancels_the_inflight_operation(eng):
    tab_id = eng.op("stop-agent", "echo")["tab"]["id"]

    async def scenario():
        started = time.monotonic()
        slow = asyncio.ensure_future(
            eng.host.call(
                lambda core: core.agent_op(
                    "stop-agent", "goto", {"url": eng.site.url("/slow")}
                )
            )
        )
        await asyncio.sleep(1.0)
        lifecycle.cancel_owner("stop-agent")
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(slow, 5)
        cancelled_after = time.monotonic() - started
        begun = time.monotonic()
        after = await eng.host.call(
            lambda core: core.agent_op(
                "stop-agent", "goto", {"url": eng.site.url("/page?t=After")}
            )
        )
        return cancelled_after, time.monotonic() - begun, after

    cancelled_after, took, after = run(scenario())
    assert cancelled_after < 4.0
    assert after["status"] == "success" and after["tab"]["id"] == tab_id
    assert after["url"].endswith("t=After")
    assert took < 5.0  # the stopped load does not hold the tab up


def test_revoked_subagents_get_stopped(eng, monkeypatch):
    before = (datetime.utcnow() - timedelta(minutes=1)).isoformat()
    subs = {
        "sub_known001": types.SimpleNamespace(
            parent_task_id="chat-p", agent_type="browser_agent", created_at=before
        ),
        "sub_unseen01": types.SimpleNamespace(
            parent_task_id="chat-p", agent_type="browser_agent", created_at=before
        ),
    }
    _fake_agent_runtime(monkeypatch, sessions={}, subagents=subs)
    assert eng.op("sub_known001", "echo")["status"] == "success"
    eng.call(lambda core: core.cancel_owner("chat-p", include_children=True))
    stopped = eng.op("sub_known001", "echo")
    assert (
        stopped["status"] == "error" and stopped["error_code"] == "MINI_BROWSER_STOPPED"
    )
    assert eng.op("sub_unseen01", "echo")["error_code"] == "MINI_BROWSER_STOPPED"
    # A sub-agent started after the stop (a new run), and the parent itself, carry on.
    subs["sub_later001"] = types.SimpleNamespace(
        parent_task_id="chat-p",
        agent_type="browser_agent",
        created_at=(datetime.utcnow() + timedelta(seconds=1)).isoformat(),
    )
    assert eng.op("sub_later001", "echo")["status"] == "success"
    assert eng.op("chat-p", "echo")["status"] == "success"


# ── live view ────────────────────────────────────────────────────────────────


def _frames(eng):
    return eng.sink.of("frame")


def test_screencast_streams_only_while_someone_watches(eng):
    tab_id = eng.op("anim-agent", "goto", url=eng.site.url("/animated"))["tab"]["id"]
    eng.call(lambda core: core.ui_switch_tab(tab_id))
    eng.call(lambda core: core.set_streaming(True))
    time.sleep(1.0)
    assert _frames(eng) == []  # nobody watching: nothing captured or sent

    eng.sink.viewers = True
    eng.call(lambda core: core.set_streaming(True))
    started = time.monotonic()
    time.sleep(2.0)
    frames = _frames(eng)
    assert len(frames) >= 5
    elapsed = time.monotonic() - started
    assert len(frames) <= 10 * elapsed + 3  # throttled to max_fps (10)
    frame = frames[-1]
    assert set(frame) == {"tabId", "image", "width", "height", "seq"}
    assert frame["tabId"] == tab_id
    assert frame["image"].startswith("data:image/jpeg;base64,")
    assert (frame["width"], frame["height"]) == (1280, 800)
    seqs = [f["seq"] for f in frames]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert eng.inspect(lambda core: core._stream.mode) == "screencast"

    # Viewport change restarts the stream at the new size.
    eng.call(lambda core: core.set_viewport(900, 600))
    eng.wait_until(
        lambda core: any((f["width"], f["height"]) == (900, 600) for f in _frames(eng)),
        what="resized frames",
    )

    eng.sink.viewers = False
    eng.call(lambda core: core.set_streaming(False))
    time.sleep(0.3)
    count = len(_frames(eng))
    time.sleep(1.0)
    assert len(_frames(eng)) == count  # stopped
    assert eng.inspect(lambda core: core._stream.mode) is None
    eng.call(lambda core: core.push_frame_now())
    assert len(_frames(eng)) == count  # nobody to push to

    # A new viewer gets the latest frame at once (before any new capture).
    last_seq = _frames(eng)[-1]["seq"]
    eng.sink.viewers = True
    eng.call(lambda core: core.push_frame_now())
    pushed = _frames(eng)[count]
    assert pushed["tabId"] == tab_id and pushed["seq"] > last_seq
    assert (pushed["width"], pushed["height"]) == (900, 600)
    eng.sink.viewers = False


def test_polling_fallback_skips_identical_frames(eng):
    tab_id = eng.op("poll-agent", "goto", url=eng.site.url("/page?t=Static"))["tab"][
        "id"
    ]
    eng.call(lambda core: core.ui_switch_tab(tab_id))
    saved_cdp = eng.inspect(lambda core: core.tabs[tab_id].cdp)
    eng.inspect(
        lambda core: setattr(core.tabs[tab_id], "cdp", None)
    )  # no screencast possible
    try:
        eng.sink.viewers = True
        eng.call(lambda core: core.set_streaming(True))
        assert eng.inspect(lambda core: core._stream.mode) == "poll"
        eng.wait_until(lambda core: len(_frames(eng)) >= 1, what="first polled frame")
        time.sleep(2.0)
        assert 1 <= len(_frames(eng)) <= 2  # a static page is not re-sent
    finally:
        eng.sink.viewers = False
        eng.inspect(lambda core: setattr(core.tabs[tab_id], "cdp", saved_cdp))
        eng.call(lambda core: core.set_streaming(False))


def test_agent_pointer_is_normalised_and_throttled(eng):
    tab_id = eng.op("pointer-agent", "echo")["tab"]["id"]
    eng.call(lambda core: core.ui_switch_tab(tab_id))
    eng.sink.viewers = True

    async def moves(core):
        tab = core.tabs[tab_id]
        for i in range(30):
            await core.publish_pointer(tab, 640 + i, 400, "move")
        await core.publish_pointer(tab, 1280, 800, "down")
        await core.publish_pointer(tab, float("nan"), 3, "up")

    eng.call(moves)
    pointers = eng.sink.of("pointer")
    assert 1 <= len(pointers) <= 4  # 30 moves in a burst are throttled
    assert pointers[0] == {"tabId": tab_id, "x": 0.5, "y": 0.5, "kind": "move"}
    assert pointers[-1] == {"tabId": tab_id, "x": 1.0, "y": 1.0, "kind": "down"}


# ── failures: crash, browser death, idle shutdown ────────────────────────────


def test_crashed_tab_recovers_on_next_use(eng):
    tab_id = eng.op("crash-agent", "goto", url=eng.site.url("/page?t=Before"))["tab"][
        "id"
    ]

    async def crash(core):
        tab = core.tabs[tab_id]
        core.spawn(tab.cdp.send("Page.crash"))  # never answers: the renderer dies

    eng.call(crash)
    eng.wait_until(lambda core: core.tabs[tab_id].crashed, what="crash event")
    assert any(t["crashed"] for t in eng.inspect(lambda core: core.state())["tabs"])
    after = eng.op("crash-agent", "echo")
    assert after["status"] == "success" and after["tab"]["id"] == tab_id
    assert after["url"].endswith("/page?t=Before")  # reopened where it was
    assert not eng.tab(tab_id).crashed
    assert any(e["kind"] in ("crash", "notice") for e in after["events"])


def test_browser_death_relaunches_cleanly(eng):
    eng.op("death-agent", "echo")

    async def kill(core):
        session = await core._context.browser.new_browser_cdp_session()
        core.spawn(session.send("Browser.close"))

    eng.call(kill)
    eng.wait_until(
        lambda core: core.status == "stopped" and core._context is None,
        timeout=20,
        what="death detected",
    )
    assert eng.inspect(lambda core: core.tabs) == {}
    revived = eng.op("death-agent", "echo", timeout=120)
    assert revived["status"] == "success"
    assert eng.inspect(lambda core: core.status) == "ready"


def test_idle_browser_shuts_down(eng):
    def make_idle(core):
        core.settings = replace(core.settings, idle_shutdown_minutes=1)
        core._last_activity = time.monotonic() - 120

    eng.inspect(make_idle)
    try:
        eng.wait_until(
            lambda core: core.status == "stopped", timeout=15, what="idle shutdown"
        )
    finally:
        eng.inspect(
            lambda core: setattr(
                core, "settings", replace(core.settings, idle_shutdown_minutes=0)
            )
        )
    assert (
        eng.op("idle-agent", "echo", timeout=120)["status"] == "success"
    )  # starts again on use


def test_lifecycle_shutdown_stops_the_host(eng, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "profile_dir", lambda: tmp_path / "shutdown-profile")
    host = MiniBrowserHost(
        lambda: BrowserCore(
            settings=MiniBrowserSettings(idle_shutdown_minutes=0), ops_registry=FAKE_OPS
        )
    )
    monkeypatch.setattr(host_module, "_host", host)
    run(host.call(lambda core: core.agent_op("x", "echo", {})), 120)
    lifecycle.on_run_state("x", "running")
    future = host.submit(lambda core: _apply(lambda c: c._run_busy("x"), core))
    assert future.result(timeout=5) is True
    asyncio.run(lifecycle.shutdown(timeout=15))
    assert not host.is_running()
    assert host_module.get_host_if_started() is None


# ── UI event paths ──────────────────────────────────────────────────────


def test_download_paths_are_workspace_relative_for_the_ui(tmp_path, monkeypatch):
    """The UI's open-file / show-in-folder actions resolve paths against the
    agent workspace, so UI events carry the workspace-relative form."""
    import app.config as app_config
    from app.mini_browser.core import _workspace_relative

    workspace = tmp_path / "workspace"
    inside = workspace / "sessions" / "abc" / "downloads" / "invoice.pdf"
    monkeypatch.setattr(app_config, "AGENT_WORKSPACE_ROOT", workspace)

    assert _workspace_relative(str(inside)) == "sessions/abc/downloads/invoice.pdf"
    outside = tmp_path / "elsewhere" / "file.txt"
    assert _workspace_relative(str(outside)) == str(outside)
    sibling = tmp_path / "workspace_other" / "file.txt"
    assert _workspace_relative(str(sibling)) == str(sibling)
