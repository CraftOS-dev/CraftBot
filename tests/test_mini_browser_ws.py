"""Mini Browser WebSocket protocol (app/mini_browser/ws.py) and its plumbing.

Covers the request handlers, viewers and the thread-safe UI sink, the
adapter wiring (dispatch, strict replies, the connection ``finally``), the
error codebook registration and the settings in app/config.py.

The browser host, the vault, the bridge and lifecycle are fakes: nothing here
imports Playwright or starts Chromium.
"""

from __future__ import annotations

import asyncio
import json
import string
import threading
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from loguru import logger as loguru_logger

import app.config as app_config
import app.mini_browser.ws as mbws
import app.ui_layer.adapters.browser_adapter as browser_adapter_module
from app.errors import make_error
from app.mini_browser import ACTION_SET, SESSION_ID, SESSION_TITLE
from app.mini_browser.errors import ERROR_SPECS, MiniBrowserError, ui_error
from app.ui_layer.adapters.browser_adapter import BrowserAdapter
from app.ui_layer.adapters.ws_auth import WsAuth

PASSWORD = "hunter2-Secret!"
TOKEN = "a" * 64


# ─────────────────────────────────────────────────────────────────── fakes


class FakeChannel:
    """ClientChannel stand-in: records what was queued and on which thread."""

    def __init__(self, pending: int = 0) -> None:
        self.pending = pending
        self.closed = False
        self.sent = []
        self.thread_ids = set()

    def send_text(self, text: str) -> None:
        self.thread_ids.add(threading.get_ident())
        self.sent.append(json.loads(text))

    def send_json(self, message) -> None:
        self.send_text(json.dumps(message))

    def of_type(self, msg_type: str):
        return [m for m in self.sent if m["type"] == msg_type]

    def data(self, msg_type: str):
        return [m["data"] for m in self.of_type(msg_type)]


class FakeCore:
    def __init__(self) -> None:
        self.calls = []
        self.fail = {}
        self.status = "ready"
        self.last_error = None
        self.tabs = {}
        self.selection = ""
        self.navigate_gate = None
        # Set to an asyncio.Event to make the page "hang" on live input.
        self.input_gate = None

    def state(self):
        return {
            "status": self.status,
            "error": self.last_error,
            "sessionId": "stale",
            "adblock": True,
            "viewedTabId": "t1",
            "follow": True,
            "viewport": {"width": 1280, "height": 800},
            "tabs": [{"id": "t1", "url": "https://example.com/", "title": "Example"}],
            "settings": {"humanlike": True, "showCursor": True},
        }

    async def _record(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail:
            raise self.fail[name]

    def names(self):
        return [call[0] for call in self.calls]

    async def start(self):
        await self._record("start")

    async def close(self):
        await self._record("close")

    async def ui_navigate(self, tab_id, text):
        await self._record("ui_navigate", tab_id, text)
        if self.navigate_gate is not None:
            await self.navigate_gate.wait()

    async def ui_history(self, tab_id, action):
        await self._record("ui_history", tab_id, action)

    async def ui_input(self, tab_id, event):
        await self._record("ui_input", tab_id, event)
        if self.input_gate is not None:
            await self.input_gate.wait()

    async def ui_new_tab(self, url=None):
        await self._record("ui_new_tab", url)
        return "t2"

    async def ui_switch_tab(self, tab_id):
        await self._record("ui_switch_tab", tab_id)

    async def ui_close_tab(self, tab_id):
        await self._record("ui_close_tab", tab_id)

    async def ui_view(self, tab_id, follow):
        await self._record("ui_view", tab_id, follow)

    async def ui_control(self, tab_id, take):
        await self._record("ui_control", tab_id, take)

    async def ui_copy_selection(self, tab_id):
        await self._record("ui_copy_selection", tab_id)
        return self.selection

    async def set_viewport(self, width, height):
        await self._record("set_viewport", width, height)

    async def set_adblock(self, enabled):
        await self._record("set_adblock", enabled)

    async def set_streaming(self, active):
        await self._record("set_streaming", active)

    async def push_frame_now(self):
        await self._record("push_frame_now")


class FakeHost:
    """The host contract: call() awaits fn(core); submit() is fire-and-forget."""

    def __init__(self, core: FakeCore) -> None:
        self.core = core

    async def call(self, fn):
        return await fn(self.core)

    def submit(self, fn):
        loop = asyncio.get_running_loop()
        return asyncio.run_coroutine_threadsafe(fn(self.core), loop)


class VaultError(MiniBrowserError):
    """The vault's error: a MiniBrowserError whose fields fill the template."""


class PlainVaultError(Exception):
    """Any other exception carrying a vault code (duck-typed path)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class FakeVault:
    def __init__(self) -> None:
        self.calls = []
        self.thread_ids = set()
        self.fail = None
        self.entries = [
            {
                "id": "e1",
                "site": "example.com",
                "username": "jo",
                "label": "",
                "createdAt": "2026-10-09T00:00:00Z",
                "updatedAt": "2026-10-09T00:00:00Z",
                "lastUsedAt": None,
                # A buggy vault leaking a secret must still never reach a tab.
                "password": PASSWORD,
            }
        ]

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        self.thread_ids.add(threading.get_ident())
        if self.fail is not None:
            raise self.fail

    def status(self):
        self._record("status")
        return {"ok": True, "unreadable": False, "count": 1, "protection": "dpapi"}

    def list_entries(self):
        self._record("list_entries")
        return [dict(e) for e in self.entries]

    def add_entry(self, site, username, password, label=""):
        self._record("add_entry", site, username, password, label)
        return {"id": "e2", "site": site, "username": username, "label": label}

    def update_entry(
        self, entry_id, *, site=None, username=None, password=None, label=None
    ):
        self._record(
            "update_entry",
            entry_id,
            site=site,
            username=username,
            password=password,
            label=label,
        )
        return {"id": entry_id}

    def delete_entry(self, entry_id):
        self._record("delete_entry", entry_id)
        return False  # already gone

    def reset_unreadable(self):
        self._record("reset_unreadable")
        return "C:/state/.credentials/mini_browser_vault.enc.unreadable-1"


class FakeBridge:
    def __init__(self) -> None:
        self.sinks = []
        self.unregistered = []
        self.origins = None

    def register_ui_sink(self, sink):
        self.sinks.append(sink)

    def unregister_ui_sink(self, sink):
        self.unregistered.append(sink)

    def set_ui_origins(self, origins):
        self.origins = frozenset(origins)


class FakeLifecycle:
    def __init__(self) -> None:
        self.calls = []
        self.error = None

    async def shutdown(self, timeout: float = 15.0):
        self.calls.append(timeout)
        if self.error is not None:
            raise self.error


class FakeSessionManager:
    def __init__(self, existing=None) -> None:
        self.sessions = dict(existing or {})
        self.created = []

    def get(self, session_id):
        return self.sessions.get(session_id)

    def create_session(self, **kwargs):
        self.created.append(kwargs)
        session = SimpleNamespace(
            id=kwargs["session_id"],
            type=kwargs["session_type"],
            title=kwargs["title"],
            created_at="2026-10-09T00:00:00",
            last_active_at="2026-10-09T00:00:00",
            agent_app_project_id=None,
        )
        self.sessions[session.id] = session
        return session


def make_adapter(session_manager=None) -> BrowserAdapter:
    """A real BrowserAdapter with only what these handlers touch."""
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter._channels = {}
    adapter._ws_auth = WsAuth(7926, token=TOKEN)
    adapter._controller = SimpleNamespace(
        agent=SimpleNamespace(session_manager=session_manager)
    )
    return adapter


@pytest.fixture
def env(monkeypatch):
    e = SimpleNamespace()
    e.core = FakeCore()
    e.host = FakeHost(e.core)
    e.host_started = True
    e.get_host_calls = 0
    e.vault = FakeVault()
    e.bridge = FakeBridge()
    e.lifecycle = FakeLifecycle()
    e.settings = dict(app_config._get_default_settings()["mini_browser"])
    e.saved = []
    e.vault_notices = []
    e.session_notices = []

    def get_host():
        e.get_host_calls += 1
        e.host_started = True
        return e.host

    monkeypatch.setattr(mbws, "_get_host", get_host)
    monkeypatch.setattr(
        mbws, "_host_if_started", lambda: e.host if e.host_started else None
    )
    monkeypatch.setattr(mbws, "_get_vault", lambda: e.vault)
    monkeypatch.setattr(mbws, "_bridge", lambda: e.bridge)
    monkeypatch.setattr(mbws, "_lifecycle", lambda: e.lifecycle)
    monkeypatch.setattr(mbws, "_load_settings", lambda: dict(e.settings))
    monkeypatch.setattr(mbws, "_save_setting", lambda k, v: e.saved.append((k, v)))
    monkeypatch.setattr(mbws, "_preloaded_skills", lambda: [])
    monkeypatch.setattr(
        mbws, "_notify_vault_changed", lambda: e.vault_notices.append(True)
    )
    monkeypatch.setattr(mbws, "_notify_sessions_changed", e.session_notices.append)
    e.sessions = FakeSessionManager()
    e.adapter = make_adapter(e.sessions)
    e.mb = mbws.MiniBrowserWS(e.adapter)
    e.adapter._mini_browser_ws = e.mb
    return e


@pytest.fixture
def captured_logs():
    lines = []
    sink_id = loguru_logger.add(
        lambda message: lines.append(str(message)), level="DEBUG"
    )
    yield lines
    loguru_logger.remove(sink_id)


def connect(e, pending: int = 0):
    ws = object()
    channel = FakeChannel(pending)
    e.adapter._channels[ws] = channel
    return ws, channel


def run(coro_fn):
    return asyncio.run(coro_fn())


async def drain(e, rounds: int = 10):
    """Let background tasks, host submissions and loop callbacks finish."""
    for _ in range(rounds):
        tasks = [t for t in e.mb._tasks if not t.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)


async def until(predicate, timeout: float = 3.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


def all_traffic(*channels) -> str:
    return json.dumps([c.sent for c in channels])


def frame(seq: int):
    return {
        "tabId": "t1",
        "image": "data:image/jpeg;base64,AAAA",
        "width": 1280,
        "height": 800,
        "seq": seq,
    }


# ─────────────────────────────────────────────────────── viewers & state


def test_subscribe_replies_state_to_requester_only(env):
    async def go():
        ws, channel = connect(env)
        _, other = connect(env)
        browser_adapter_module._REQUEST_ID.set("req-1")
        await env.mb.handle(
            ws, "mini_browser_subscribe", {"type": "mini_browser_subscribe"}
        )
        await drain(env)

        [state] = channel.data("mini_browser_state")
        assert state["status"] == "ready"
        assert state["sessionId"] == SESSION_ID  # the dedicated session now exists
        assert state["requestId"] == "req-1"  # strict reply echoes the request
        assert other.of_type("mini_browser_state") == []
        assert env.mb.has_viewers()
        # First viewer: streaming starts and the last frame is pushed.
        assert ("set_streaming", True) in env.core.calls
        assert "push_frame_now" in env.core.names()

    run(go)


def test_subscribe_creates_and_announces_the_session_once(env):
    async def go():
        ws, channel = connect(env)
        _, other = connect(env)
        browser_adapter_module._REQUEST_ID.set("req-9")
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        await drain(env)

        assert len(env.sessions.created) == 1
        created = env.sessions.created[0]
        assert created["session_type"] == "mini_browser"
        assert created["session_id"] == SESSION_ID
        assert created["title"] == SESSION_TITLE
        assert created["action_sets"] == [ACTION_SET]
        # Every tab upserts the new session; the broadcast carries no
        # request id (it is not a reply to anyone).
        for c in (channel, other):
            [announced] = c.data("session_created")
            assert announced["session"]["id"] == SESSION_ID
            assert announced["session"]["type"] == "mini_browser"
            assert announced["clientId"] is None
            assert "requestId" not in announced
        assert env.session_notices == [SESSION_ID]

    run(go)


def test_existing_session_is_reused_not_recreated(env):
    async def go():
        restored = SimpleNamespace(
            id=SESSION_ID, type="mini_browser", title="Mini Browser"
        )
        env.sessions.sessions[SESSION_ID] = restored
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        await drain(env)
        assert env.sessions.created == []
        assert channel.of_type("session_created") == []
        assert env.mb.ensure_session() is restored

    run(go)


def test_state_has_no_session_id_until_the_session_exists(env):
    async def go():
        env.adapter._controller.agent.session_manager = None  # no sessions at all
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        [state] = channel.data("mini_browser_state")
        assert state["sessionId"] is None

    run(go)


def test_passive_messages_never_start_the_browser(env):
    async def go():
        env.host_started = False
        ws, channel = connect(env)
        for msg_type in (
            "mini_browser_subscribe",
            "mini_browser_adblock",
            "mini_browser_vault_list",
            "mini_browser_unsubscribe",
            "mini_browser_view",
            "mini_browser_shutdown",
        ):
            await env.mb.handle(ws, msg_type, {"type": msg_type})
        await env.mb.handle(
            ws,
            "mini_browser_input",
            {"tabId": "t1", "event": {"kind": "key", "key": "a"}},
        )
        await drain(env)

        assert env.get_host_calls == 0 and not env.host_started
        assert env.core.calls == []
        state = channel.data("mini_browser_state")[0]
        assert state["status"] == "stopped"
        assert state["tabs"] == [] and state["viewedTabId"] is None
        assert state["viewport"] == {"width": 1280, "height": 800}
        assert state["settings"] == {"humanlike": True, "showCursor": True}
        assert channel.of_type("mini_browser_event") == []

    run(go)


def test_adblock_query_and_toggle_without_a_browser(env):
    async def go():
        env.host_started = False
        env.settings["adblock"] = False
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_adblock", {})
        assert channel.data("mini_browser_state")[-1]["adblock"] is False

        await env.mb.handle(ws, "mini_browser_adblock", {"enabled": True})
        assert env.saved == [("adblock", True)]  # persisted, no browser needed
        assert not env.host_started

        env.host_started = True
        await env.mb.handle(ws, "mini_browser_adblock", {"enabled": False})
        assert ("set_adblock", False) in env.core.calls

    run(go)


def test_unsubscribe_and_forget_stop_streaming(env):
    async def go():
        a, _ = connect(env)
        b, _ = connect(env)
        await env.mb.handle(a, "mini_browser_subscribe", {})
        await env.mb.handle(b, "mini_browser_subscribe", {})
        await drain(env)
        env.core.calls.clear()

        await env.mb.handle(a, "mini_browser_unsubscribe", {})
        await drain(env)
        assert env.mb.has_viewers()
        assert ("set_streaming", False) not in env.core.calls  # b still watches

        env.mb.forget(b)
        env.mb.forget(object())  # unknown sockets are fine
        await drain(env)
        assert not env.mb.has_viewers()
        assert ("set_streaming", False) in env.core.calls

    run(go)


def test_subscribe_from_a_closed_socket_is_ignored(env):
    async def go():
        ws, channel = connect(env)
        channel.closed = True
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        assert not env.mb.has_viewers()
        assert channel.sent == []

    run(go)


def test_a_host_started_after_subscribe_learns_about_the_viewer(env):
    async def go():
        env.host_started = False
        ws, _ = connect(env)
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        await drain(env)
        assert env.core.calls == []  # nothing to stream yet
        await env.mb.handle(ws, "mini_browser_resize", {"width": 1024, "height": 768})
        await drain(env)
        assert env.host_started
        assert ("set_streaming", True) in env.core.calls
        assert ("set_viewport", 1024, 768) in env.core.calls

    run(go)


# ─────────────────────────────────────────────────────────── the UI sink


def test_frames_go_to_subscribers_only_and_skip_sockets_behind(env):
    async def go():
        env.mb.on_start()
        fresh, fresh_ch = connect(env, pending=0)
        caught_up, caught_up_ch = connect(env, pending=1)
        behind, behind_ch = connect(env, pending=2)
        _, bystander_ch = connect(env)
        for ws in (fresh, caught_up, behind):
            await env.mb.handle(ws, "mini_browser_subscribe", {})

        env.mb.post("frame", frame(1))
        await drain(env)

        assert [d["seq"] for d in fresh_ch.data("mini_browser_frame")] == [1]
        assert [d["seq"] for d in caught_up_ch.data("mini_browser_frame")] == [1]
        assert behind_ch.of_type("mini_browser_frame") == []
        assert bystander_ch.of_type("mini_browser_frame") == []

    run(go)


def test_frames_coalesce_to_the_latest(env):
    async def go():
        env.mb.on_start()
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        flushes = []
        real_flush = env.mb._flush_frame

        def counting_flush():
            flushes.append(1)
            real_flush()

        env.mb._flush_frame = counting_flush
        for seq in range(1, 6):
            env.mb.post("frame", frame(seq))  # all before the loop runs again
        await drain(env)
        assert [d["seq"] for d in channel.data("mini_browser_frame")] == [5]
        assert len(flushes) == 1  # one pending flush at a time, not one per frame

        env.mb.post("frame", frame(6))
        await drain(env)
        assert [d["seq"] for d in channel.data("mini_browser_frame")] == [5, 6]
        assert len(flushes) == 2

    run(go)


def test_post_from_the_browser_thread(env):
    async def go():
        env.mb.on_start()
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        loop_thread = threading.get_ident()
        channel.thread_ids.clear()

        def browser_thread():
            assert env.mb.has_viewers()
            for seq in range(1, 201):
                env.mb.post("frame", frame(seq))
            env.mb.post("pointer", {"tabId": "t1", "x": 0.5, "y": 0.5, "kind": "move"})
            env.mb.post(
                "event", {"kind": "download", "level": "info", "message": "Saved"}
            )
            env.mb.post("state", {**env.core.state(), "status": "starting"})

        worker = threading.Thread(target=browser_thread)
        worker.start()
        worker.join()  # the loop is blocked meanwhile: every frame coalesces
        await until(lambda: channel.of_type("mini_browser_state")[1:])

        assert [d["seq"] for d in channel.data("mini_browser_frame")] == [200]
        assert channel.data("mini_browser_pointer") == [
            {"tabId": "t1", "x": 0.5, "y": 0.5, "kind": "move"}
        ]
        assert channel.data("mini_browser_event")[0]["message"] == "Saved"
        state = channel.data("mini_browser_state")[-1]
        assert state["status"] == "starting"
        assert state["sessionId"] == SESSION_ID  # overlaid on the UI loop
        assert channel.thread_ids == {loop_thread}

    run(go)


def test_sink_messages_carry_no_request_id_and_skip_non_viewers(env):
    async def go():
        env.mb.on_start()
        browser_adapter_module._REQUEST_ID.set("req-7")
        ws, channel = connect(env)
        _, bystander = connect(env)
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        channel.sent.clear()
        env.mb.post("event", {"kind": "notice", "level": "info", "message": "hi"})
        env.mb.post("install", {"line": "Downloading"})
        env.mb.post("bogus", {"x": 1})  # unknown kinds are dropped
        env.mb.post("event", "not a dict")
        await drain(env)
        types = [m["type"] for m in channel.sent]
        assert types == ["mini_browser_event", "mini_browser_install_progress"]
        assert all("requestId" not in m["data"] for m in channel.sent)
        assert bystander.sent == [] or all(
            m["type"] == "session_created" for m in bystander.sent
        )

    run(go)


def test_pointer_moves_skip_a_badly_lagging_socket(env):
    async def go():
        env.mb.on_start()
        ws, channel = connect(env, pending=9)
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        env.mb.post("pointer", {"tabId": "t1", "x": 0.1, "y": 0.1, "kind": "move"})
        env.mb.post("event", {"kind": "notice", "level": "info", "message": "kept"})
        await drain(env)
        assert channel.of_type("mini_browser_pointer") == []
        assert channel.of_type("mini_browser_event")  # state/events always go

    run(go)


def test_post_without_viewers_or_loop_is_a_no_op(env):
    env.mb.post("frame", frame(1))  # never started: no loop
    assert env.mb._frame is None

    async def go():
        env.mb.on_start()
        env.mb.post("frame", frame(1))  # nobody watching
        assert env.mb._frame is None

    run(go)


def test_closed_viewer_is_pruned_on_delivery(env):
    async def go():
        env.mb.on_start()
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        await drain(env)
        env.core.calls.clear()
        channel.closed = True
        env.mb.post("event", {"kind": "notice", "level": "info", "message": "x"})
        await drain(env)
        assert not env.mb.has_viewers()
        assert ("set_streaming", False) in env.core.calls

    run(go)


def test_unserializable_payload_is_dropped_not_raised(env, captured_logs):
    async def go():
        env.mb.on_start()
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        channel.sent.clear()
        env.mb.post(
            "pointer", {"tabId": "t1", "x": float("nan"), "y": 0, "kind": "move"}
        )
        env.mb.post("event", {"kind": "notice", "level": "info", "message": object()})
        await drain(env)
        assert channel.sent == []

    run(go)
    assert any("unserializable" in line for line in captured_logs)


# ──────────────────────────────────────────────────── browser requests


def test_navigation_runs_in_the_background_and_reports(env):
    async def go():
        env.core.navigate_gate = asyncio.Event()
        ws, channel = connect(env)
        browser_adapter_module._REQUEST_ID.set("req-nav")
        await env.mb.handle(
            ws, "mini_browser_navigate", {"tabId": "t1", "url": "  example.com  "}
        )
        await asyncio.sleep(0)
        # handle() returned while the page is still loading: the lane is free.
        assert ("ui_navigate", "t1", "example.com") in env.core.calls
        assert channel.of_type("mini_browser_nav_result") == []

        env.core.navigate_gate.set()
        await drain(env)
        [result] = channel.data("mini_browser_nav_result")
        assert result == {"ok": True, "requestId": "req-nav"}

    run(go)


def test_navigation_failure_is_reported_to_the_requester(env):
    async def go():
        env.core.fail["ui_navigate"] = MiniBrowserError(
            "MINI_BROWSER_NAVIGATION_FAILED", url="https://nope.invalid", detail="DNS"
        )
        ws, channel = connect(env)
        _, other = connect(env)
        await env.mb.handle(ws, "mini_browser_navigate", {"url": "nope.invalid"})
        await drain(env)
        [result] = channel.data("mini_browser_nav_result")
        assert result["ok"] is False
        assert result["error"]["code"] == "MINI_BROWSER_NAVIGATION_FAILED"
        assert result["error"]["title"] == "Page failed to load"
        assert other.sent == []

    run(go)


def test_handler_exceptions_become_error_replies(env, captured_logs):
    async def go():
        env.core.fail["ui_navigate"] = RuntimeError("boom\nCall log: secret stuff")
        env.core.fail["ui_control"] = MiniBrowserError(
            "MINI_BROWSER_TAB_NOT_FOUND", tab="t9"
        )
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_navigate", {"url": "example.com"})
        await env.mb.handle(ws, "mini_browser_control", {"tabId": "t9", "take": True})
        await drain(env)

        [nav] = channel.data("mini_browser_nav_result")
        assert nav["ok"] is False
        assert nav["error"]["code"] == "MINI_BROWSER_INTERNAL"
        assert "boom" in nav["error"]["message"]
        assert "Call log" not in nav["error"]["message"]  # first line only
        [event] = channel.data("mini_browser_event")
        assert event["kind"] == "error"
        assert event["code"] == "MINI_BROWSER_TAB_NOT_FOUND"
        assert event["level"] == "warning"
        assert "t9" in event["message"]

    run(go)
    assert any(
        "mini_browser_navigate failed: RuntimeError: boom" in x for x in captured_logs
    )


def test_missing_host_module_is_an_error_reply_not_an_exception(env, monkeypatch):
    def broken():
        raise ImportError("No module named 'app.mini_browser.host'")

    monkeypatch.setattr(mbws, "_get_host", broken)
    env.host_started = False  # what _host_if_started() reports without the module

    async def go():
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_start", {})
        await env.mb.handle(ws, "mini_browser_resize", {"width": 800, "height": 600})
        await env.mb.handle(ws, "mini_browser_navigate", {"url": "example.com"})
        events = channel.data("mini_browser_event")
        assert [e["code"] for e in events] == ["MINI_BROWSER_INTERNAL"] * 2
        [nav] = channel.data("mini_browser_nav_result")
        assert nav["error"]["code"] == "MINI_BROWSER_INTERNAL"

    run(go)


def test_starting_the_host_never_blocks_the_ui_loop(env, monkeypatch):
    loop_threads = []

    def slow_start():
        loop_threads.append(threading.get_ident())
        env.host_started = True
        return env.host

    monkeypatch.setattr(mbws, "_get_host", slow_start)
    env.host_started = False

    async def go():
        ws, _ = connect(env)
        await env.mb.handle(ws, "mini_browser_resize", {"width": 800, "height": 600})
        assert loop_threads and loop_threads[0] != threading.get_ident()
        assert ("set_viewport", 800, 600) in env.core.calls

    run(go)


def test_adapter_dispatch_never_raises_or_reaches_other_tabs(env):
    async def go():
        env.core.fail["ui_copy_selection"] = RuntimeError("kaput")
        ws, channel = connect(env)
        _, other = connect(env)
        await env.adapter._handle_ws_message(
            {"type": "mini_browser_copy", "tabId": "t1"}, ws
        )
        await env.adapter._handle_ws_message({"type": None}, ws)
        await env.adapter._handle_ws_message({"type": "mini_browser_bogus"}, ws)
        assert [m["type"] for m in channel.sent] == ["mini_browser_event"]
        assert other.sent == []  # nothing broadcast, no "[DEBUG ERROR]" chat line

    run(go)


def test_start_runs_in_the_background_and_publishes_state(env):
    async def go():
        env.host_started = False
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_start", {})
        await drain(env)
        assert env.core.names() == ["start"]
        assert channel.data("mini_browser_state")[-1]["status"] == "ready"

        env.core.fail["start"] = MiniBrowserError("MINI_BROWSER_CHROMIUM_MISSING")
        env.core.status = "error"
        await env.mb.handle(ws, "mini_browser_start", {})
        await drain(env)
        assert channel.data("mini_browser_state")[-1]["status"] == "error"
        assert channel.data("mini_browser_event")[-1]["code"] == (
            "MINI_BROWSER_CHROMIUM_MISSING"
        )

    run(go)


def test_shutdown_closes_chromium_only_when_running(env):
    async def go():
        ws, channel = connect(env)
        env.host_started = False
        await env.mb.handle(ws, "mini_browser_shutdown", {})
        assert env.core.calls == [] and env.get_host_calls == 0
        env.host_started = True
        await env.mb.handle(ws, "mini_browser_shutdown", {})
        assert env.core.names() == ["close"]
        assert len(channel.of_type("mini_browser_state")) == 2

    run(go)


def test_history_tabs_view_control_resize(env):
    async def go():
        ws, channel = connect(env)
        for msg_type, data in (
            ("mini_browser_history", {"action": "back"}),
            ("mini_browser_tab", {"action": "new", "url": "a.com"}),
            ("mini_browser_tab", {"action": "new"}),
            ("mini_browser_tab", {"action": "switch", "tabId": "t2"}),
            ("mini_browser_tab", {"action": "close", "tabId": "t2"}),
            ("mini_browser_view", {"tabId": "t1", "follow": False}),
            ("mini_browser_view", {"follow": True}),
            ("mini_browser_control", {"tabId": "t1", "take": True}),
            ("mini_browser_resize", {"width": 99999, "height": 10.4}),
        ):
            await env.mb.handle(ws, msg_type, data)
            await drain(env)  # history and new tabs run in the background
        assert env.core.calls == [
            ("ui_history", None, "back"),
            ("ui_new_tab", "a.com"),
            ("ui_new_tab", None),
            ("ui_switch_tab", "t2"),
            ("ui_close_tab", "t2"),
            ("ui_view", "t1", False),
            ("ui_view", None, True),
            ("ui_control", "t1", True),
            ("set_viewport", 3840, 240),  # clamped
        ]
        assert channel.of_type("mini_browser_event") == []

    run(go)


def test_copy_replies_to_requester_and_scrubs_autofilled_passwords(env):
    async def go():
        env.core.tabs["t1"] = SimpleNamespace(filled_secrets=[PASSWORD])
        env.core.selection = f"user jo, pass {PASSWORD}"
        ws, channel = connect(env)
        _, other = connect(env)
        await env.mb.handle(ws, "mini_browser_copy", {"tabId": "t1"})
        [clip] = channel.data("mini_browser_clipboard")
        assert clip["text"] == "user jo, pass [redacted]"
        assert other.sent == []

    run(go)


def test_ops_needing_a_browser_report_not_running(env):
    async def go():
        env.host_started = False
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_control", {"tabId": "t1", "take": True})
        await env.mb.handle(ws, "mini_browser_copy", {"tabId": "t1"})
        await env.mb.handle(ws, "mini_browser_history", {"action": "reload"})
        await env.mb.handle(ws, "mini_browser_tab", {"action": "close", "tabId": "t1"})
        codes = [e["code"] for e in channel.data("mini_browser_event")]
        assert codes == ["MINI_BROWSER_NOT_RUNNING"] * 4
        assert not env.host_started

    run(go)


# ─────────────────────────────────────────────────────── input validation


GOOD_EVENTS = [
    (
        {"kind": "mouse", "action": "down", "x": 0.25, "y": 1.5, "clickCount": 7},
        {
            "kind": "mouse",
            "action": "down",
            "x": 0.25,
            "y": 1.0,
            "button": "left",
            "clickCount": 3,
        },
    ),
    (
        {"kind": "mouse", "action": "up", "x": -3, "y": 0, "button": "right"},
        {
            "kind": "mouse",
            "action": "up",
            "x": 0.0,
            "y": 0.0,
            "button": "right",
            "clickCount": 1,
        },
    ),
    (
        {"kind": "wheel", "x": 0.5, "y": 0.5, "dy": 1e9},
        {"kind": "wheel", "x": 0.5, "y": 0.5, "dx": 0.0, "dy": 5000.0},
    ),
    (
        {"kind": "key", "key": "Enter", "modifiers": {"shift": True, "ctrl": 1}},
        {
            "kind": "key",
            "key": "Enter",
            "modifiers": {"shift": True, "ctrl": False, "alt": False, "meta": False},
        },
    ),
    (
        {"kind": "text", "text": "こんにちは\nworld"},
        {"kind": "text", "text": "こんにちは\nworld"},
    ),
]


@pytest.mark.parametrize("event,clean", GOOD_EVENTS)
def test_input_is_validated_and_clamped(env, event, clean):
    async def go():
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_input", {"tabId": "t1", "event": event})
        await drain(env)  # queued input is applied by the socket's drain task
        assert env.core.calls == [("ui_input", "t1", clean)]
        assert channel.sent == []

    run(go)


BAD_INPUTS = [
    {
        "tabId": "t1",
        "event": {"kind": "mouse", "action": "down", "x": float("nan"), "y": 0},
    },
    {
        "tabId": "t1",
        "event": {"kind": "mouse", "action": "down", "x": float("inf"), "y": 0},
    },
    {"tabId": "t1", "event": {"kind": "mouse", "action": "down", "x": 10**400, "y": 0}},
    {"tabId": "t1", "event": {"kind": "mouse", "action": "down", "x": "0.5", "y": 0}},
    {"tabId": "t1", "event": {"kind": "mouse", "action": "down", "x": True, "y": 0}},
    {"tabId": "t1", "event": {"kind": "mouse", "action": "drag", "x": 0, "y": 0}},
    {
        "tabId": "t1",
        "event": {"kind": "mouse", "action": "down", "x": 0, "y": 0, "button": "x"},
    },
    {"tabId": "t1", "event": {"kind": "wheel", "x": 0, "y": 0, "dy": float("nan")}},
    {"tabId": "t1", "event": {"kind": "key", "key": "K" * 33}},
    {"tabId": "t1", "event": {"kind": "key", "key": "\x00"}},
    {"tabId": "t1", "event": {"kind": "key", "key": 13}},
    {"tabId": "t1", "event": {"kind": "text", "text": "x" * 2001}},
    {"tabId": "t1", "event": {"kind": "text", "text": ""}},
    {"tabId": "t1", "event": "click"},
    {"tabId": "t1"},
    {"tabId": 7, "event": {"kind": "key", "key": "a"}},
    {"tabId": "t" * 200, "event": {"kind": "key", "key": "a"}},
    {"event": {"kind": "key", "key": "a"}},
]


@pytest.mark.parametrize("data", BAD_INPUTS)
def test_invalid_input_is_rejected_without_exceptions(env, data):
    async def go():
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_input", data)
        assert env.core.calls == []
        [event] = channel.data("mini_browser_event")
        assert event["code"] == "MINI_BROWSER_INVALID_INPUT"
        assert event["level"] == "warning"

    run(go)


def test_unknown_input_kind_and_unknown_types_are_ignored(env):
    async def go():
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_input", {"event": {"kind": "gamepad"}})
        await env.mb.handle(ws, "mini_browser_teleport", {"to": "mars"})
        assert env.core.calls == [] and channel.sent == []
        await env.mb.handle(ws, "mini_browser_subscribe", "not a dict")
        assert channel.of_type("mini_browser_state")  # treated as {}
        assert channel.of_type("mini_browser_event") == []

    run(go)


@pytest.mark.parametrize(
    "msg_type,data",
    [
        ("mini_browser_resize", {"width": float("nan"), "height": 600}),
        ("mini_browser_resize", {"width": "800", "height": 600}),
        ("mini_browser_resize", {"height": 600}),
        ("mini_browser_history", {"action": "sideways"}),
        ("mini_browser_tab", {"action": "explode"}),
        ("mini_browser_tab", {"action": "switch"}),
        ("mini_browser_view", {"follow": "yes"}),
        ("mini_browser_control", {"tabId": "t1"}),
        ("mini_browser_control", {"tabId": "t1", "take": 1}),
        ("mini_browser_adblock", {"enabled": "off"}),
        ("mini_browser_copy", {}),
    ],
)
def test_invalid_requests_are_rejected(env, msg_type, data):
    async def go():
        ws, channel = connect(env)
        await env.mb.handle(ws, msg_type, data)
        await drain(env)
        assert env.core.calls == []
        [event] = channel.data("mini_browser_event")
        assert event["code"] == "MINI_BROWSER_INVALID_INPUT"

    run(go)


@pytest.mark.parametrize("url", [None, "", "   ", 42, ["a"], "x" * 9000])
def test_invalid_address_gets_a_nav_result(env, url):
    async def go():
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_navigate", {"url": url})
        await drain(env)
        assert env.core.calls == []
        [result] = channel.data("mini_browser_nav_result")
        assert result["ok"] is False
        assert result["error"]["code"] == "MINI_BROWSER_INVALID_INPUT"

    run(go)


def test_mouse_move_failures_are_quiet_but_clicks_report(env):
    async def go():
        env.core.fail["ui_input"] = MiniBrowserError(
            "MINI_BROWSER_TAB_NOT_FOUND", tab="t1"
        )
        ws, channel = connect(env)
        move = {"kind": "mouse", "action": "move", "x": 0.1, "y": 0.1}
        await env.mb.handle(ws, "mini_browser_input", {"tabId": "t1", "event": move})
        await drain(env)
        assert channel.sent == []
        click = {**move, "action": "down"}
        await env.mb.handle(ws, "mini_browser_input", {"tabId": "t1", "event": click})
        await drain(env)
        assert [e["code"] for e in channel.data("mini_browser_event")] == [
            "MINI_BROWSER_TAB_NOT_FOUND"
        ]

    run(go)


def test_typed_text_never_reaches_a_reply_or_a_log(env, captured_logs):
    async def go():
        env.core.fail["ui_input"] = RuntimeError(f"insertText failed for {PASSWORD}")
        ws, channel = connect(env)
        event = {"kind": "text", "text": PASSWORD}
        await env.mb.handle(ws, "mini_browser_input", {"tabId": "t1", "event": event})
        await drain(env)
        [error] = channel.data("mini_browser_event")
        assert error["code"] == "MINI_BROWSER_INTERNAL"
        assert PASSWORD not in json.dumps(channel.sent)

    run(go)
    assert not any(PASSWORD in line for line in captured_logs)


# ──────────────────────────────────────────── live input on a lagging page


def _move(x, tab="t1"):
    return {
        "tabId": tab,
        "event": {"kind": "mouse", "action": "move", "x": x, "y": 0.5},
    }


def _wheel(dy, tab="t1"):
    return {"tabId": tab, "event": {"kind": "wheel", "x": 0.5, "y": 0.5, "dy": dy}}


def _button(action, tab="t1"):
    return {
        "tabId": tab,
        "event": {"kind": "mouse", "action": action, "x": 0.5, "y": 0.5},
    }


def _key(key, tab="t1"):
    return {"tabId": tab, "event": {"kind": "key", "key": key}}


def _applied(core):
    """Every call the page received, in order: live input as (tab, summary),
    anything else as (name, *args)."""
    out = []
    for name, *args in core.calls:
        if name != "ui_input":
            out.append((name, *args))
            continue
        tab_id, event = args
        detail = event.get("action") or event.get("key") or event.get("text")
        if event["kind"] == "mouse" and event["action"] == "move":
            detail = f"move@{event['x']}"
        if event["kind"] == "wheel":
            detail = f"wheel{event['dy']:+g}"
        out.append((tab_id, detail))
    return out


def _typed(core):
    """Summaries of the live input the page received, in order."""
    return [entry[1] for entry in _applied(core) if entry[0] in ("t1", "t2")]


async def _send_while_hung(env, ws, first, *rest):
    """Hang the page on ``first`` (in flight), then send ``rest`` the way the
    network delivers it: one message after another while the page is stuck.
    Returns the gate that thaws the page."""
    gate = env.core.input_gate = asyncio.Event()
    calls_before = len(env.core.calls)
    await asyncio.wait_for(env.mb.handle(ws, "mini_browser_input", first), 0.5)
    await until(lambda: len(env.core.calls) == calls_before + 1)
    for data in rest:
        # Each request returns at once: the input lane is never held up.
        await asyncio.wait_for(env.mb.handle(ws, "mini_browser_input", data), 0.5)
    return gate


def test_input_on_a_hung_page_is_coalesced_in_order(env):
    """LANE-1: moves keep the latest, wheel steps add up, and nothing is
    reordered across a click or a key."""

    async def go():
        ws, channel = connect(env)
        gate = await _send_while_hung(
            env,
            ws,
            _button("down"),
            _move(0.1),
            _move(0.2),
            _move(0.3),
            _wheel(100),
            _wheel(150),
            _key("a"),
            _move(0.7),
            _move(0.8),
            _button("up"),
            _move(0.9),
        )
        assert len(env.core.calls) == 1  # still hung on the first
        gate.set()
        await drain(env)
        assert _applied(env.core) == [
            ("t1", "down"),
            ("t1", "move@0.3"),
            ("t1", "wheel+250"),
            ("t1", "a"),
            ("t1", "move@0.8"),
            ("t1", "up"),
            ("t1", "move@0.9"),
        ]
        assert channel.sent == []

    run(go)


def test_coalescing_never_merges_across_tabs_or_past_the_wheel_limit(env):
    async def go():
        ws, _ = connect(env)
        gate = await _send_while_hung(
            env,
            ws,
            _key("x"),
            _move(0.1),
            _move(0.2, tab="t2"),
            _move(0.3),
            _wheel(4000),
            _wheel(4000),  # the sum would pass the 5000 clamp: kept apart
            _wheel(-500),
        )
        gate.set()
        await drain(env)
        assert _applied(env.core) == [
            ("t1", "x"),
            ("t1", "move@0.1"),
            ("t2", "move@0.2"),
            ("t1", "move@0.3"),
            ("t1", "wheel+4000"),
            ("t1", "wheel+3500"),
        ]

    run(go)


def test_each_socket_keeps_its_own_queue(env):
    async def go():
        env.core.input_gate = gate = asyncio.Event()
        ws1, _ = connect(env)
        ws2, _ = connect(env)
        await env.mb.handle(ws1, "mini_browser_input", _key("a"))
        await env.mb.handle(ws2, "mini_browser_input", _key("b"))
        await until(lambda: len(env.core.calls) == 2)  # neither waits on the other
        gate.set()
        await drain(env)
        assert sorted(_typed(env.core)) == ["a", "b"]

    run(go)


def test_hand_back_waits_for_the_users_last_input(env):
    """Control has its own lane; handing back must not overtake the user's
    queued keystrokes (they would land afterwards and take control again)."""

    async def go():
        ws, channel = connect(env)
        gate = await _send_while_hung(env, ws, _key("a"), _key("b"))
        control = asyncio.ensure_future(
            env.mb.handle(ws, "mini_browser_control", {"tabId": "t1", "take": False})
        )
        await asyncio.sleep(0.05)
        assert not control.done()
        gate.set()
        await asyncio.wait_for(control, 2)
        await drain(env)
        assert _applied(env.core) == [
            ("t1", "a"),
            ("t1", "b"),
            ("ui_control", "t1", False),
        ]
        assert channel.of_type("mini_browser_event") == []

    run(go)


def test_taking_control_never_waits_for_queued_input(env):
    async def go():
        ws, _ = connect(env)
        gate = await _send_while_hung(env, ws, _key("a"), _key("b"))
        await asyncio.wait_for(
            env.mb.handle(ws, "mini_browser_control", {"tabId": "t1", "take": True}),
            0.5,
        )
        assert ("ui_control", "t1", True) in env.core.calls
        gate.set()
        await drain(env)
        assert _typed(env.core) == ["a", "b"]

    run(go)


def test_hand_back_drops_input_a_hung_page_never_took(env, monkeypatch):
    monkeypatch.setattr(mbws, "_INPUT_SETTLE_S", 0.1)

    async def go():
        ws, _ = connect(env)
        gate = await _send_while_hung(env, ws, _key("a"), _key("b"), _key("c"))
        await asyncio.wait_for(
            env.mb.handle(ws, "mini_browser_control", {"tabId": "t1", "take": False}),
            1.0,
        )
        assert ("ui_control", "t1", False) in env.core.calls
        gate.set()  # the page thaws: "a" was in flight, "b"/"c" were dropped
        await drain(env)
        assert _typed(env.core) == ["a"]

    run(go)


def test_copy_waits_for_the_input_that_made_the_selection(env):
    async def go():
        env.core.selection = "picked"
        ws, channel = connect(env)
        gate = await _send_while_hung(
            env, ws, _button("down"), _move(0.9), _button("up")
        )
        copy = asyncio.ensure_future(
            env.mb.handle(ws, "mini_browser_copy", {"tabId": "t1"})
        )
        await asyncio.sleep(0.05)
        assert not copy.done()
        gate.set()
        await asyncio.wait_for(copy, 2)
        assert _applied(env.core) == [
            ("t1", "down"),
            ("t1", "move@0.9"),
            ("t1", "up"),
            ("ui_copy_selection", "t1"),
        ]
        assert channel.data("mini_browser_clipboard") == [{"text": "picked"}]

    run(go)


def test_closing_the_browser_or_a_tab_drops_queued_input(env):
    async def go():
        ws, _ = connect(env)
        gate = await _send_while_hung(
            env, ws, _key("a"), _key("b", tab="t2"), _key("c"), _key("d", tab="t2")
        )
        await env.mb.handle(ws, "mini_browser_tab", {"action": "close", "tabId": "t2"})
        assert [tab for tab, _ in env.mb._input_queues[ws].items] == ["t1"]
        await env.mb.handle(ws, "mini_browser_shutdown", {})
        gate.set()
        await drain(env)
        # "a" was in flight when the browser closed; nothing else arrives.
        assert _typed(env.core) == ["a"]
        assert ("ui_close_tab", "t2") in env.core.calls
        assert "close" in env.core.names()

    run(go)


def test_a_closed_socket_drops_its_queued_input(env):
    async def go():
        ws, _ = connect(env)
        gate = await _send_while_hung(env, ws, _key("a"), _key("b"))
        env.mb.forget(ws)
        assert ws not in env.mb._input_queues
        gate.set()
        await drain(env)
        assert _typed(env.core) == ["a"]

    run(go)


def test_a_full_backlog_reports_once_and_drops_new_input(env, monkeypatch):
    monkeypatch.setattr(mbws, "_MAX_QUEUED_INPUT", 2)

    async def go():
        ws, channel = connect(env)
        # "a" in flight, "b" and "c" queued, the rest dropped.
        gate = await _send_while_hung(env, ws, *(_key(k) for k in "abcdef"))
        codes = [e["code"] for e in channel.data("mini_browser_event")]
        assert codes == ["MINI_BROWSER_PAGE_UNRESPONSIVE"]
        gate.set()
        await drain(env)
        assert _typed(env.core) == ["a", "b", "c"]

    run(go)


def test_controls_are_not_stuck_behind_input_to_a_hung_page(env):
    """LANE-1 through the adapter's real lanes: hovering over a frozen page
    must not hold up Take control or Close browser."""

    async def go():
        env.adapter._lane_locks = {}
        env.adapter._lane_tasks = set()
        env.core.input_gate = gate = asyncio.Event()
        ws, _ = connect(env)

        def send(data):
            env.adapter._dispatch_in_lane(ws, data)

        send({"type": "mini_browser_input", **_move(0.0)})
        await until(lambda: len(env.core.calls) == 1)  # the page hangs on it
        for i in range(1, 31):  # ~2 s of hover moves at 15/s
            send({"type": "mini_browser_input", **_move(i / 100)})
        send({"type": "mini_browser_control", "tabId": "t1", "take": True})
        send({"type": "mini_browser_shutdown"})
        await until(
            lambda: (
                ("ui_control", "t1", True) in env.core.calls
                and "close" in env.core.names()
            ),
            timeout=1.0,
        )
        assert env.core.names().count("ui_input") == 1  # still hung on the first
        gate.set()
        await asyncio.gather(*list(env.adapter._lane_tasks), return_exceptions=True)
        await drain(env)
        # The backlog was coalesced, then dropped with the closed browser.
        assert env.core.names().count("ui_input") == 1

    run(go)


def test_input_without_a_browser_is_ignored(env):
    async def go():
        env.host_started = False
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_input", _key("a"))
        await drain(env)
        assert env.core.calls == [] and channel.sent == []
        assert env.get_host_calls == 0  # input never starts the browser

    run(go)


# ─────────────────────────────────────────────────────────── password vault


def test_vault_list_goes_to_requester_only_without_passwords(env):
    async def go():
        loop_thread = threading.get_ident()
        ws, channel = connect(env)
        _, other = connect(env)
        await env.mb.handle(ws, "mini_browser_vault_list", {})
        [reply] = channel.data("mini_browser_vault_list")
        assert reply["entries"] == [
            {
                "id": "e1",
                "site": "example.com",
                "username": "jo",
                "label": "",
                "createdAt": "2026-10-09T00:00:00Z",
                "updatedAt": "2026-10-09T00:00:00Z",
                "lastUsedAt": None,
            }
        ]
        assert reply["status"] == {
            "ok": True,
            "unreadable": False,
            "protection": "dpapi",
        }
        assert other.sent == []
        assert PASSWORD not in all_traffic(channel, other)
        assert loop_thread not in env.vault.thread_ids  # off the UI loop

    run(go)


def test_vault_add_update_delete_reset(env):
    async def go():
        ws, channel = connect(env)
        await env.mb.handle(
            ws,
            "mini_browser_vault_add",
            {"site": "example.com", "username": "jo", "password": PASSWORD},
        )
        await env.mb.handle(
            ws,
            "mini_browser_vault_update",
            {"id": "e1", "username": "jo2", "password": "", "label": "work"},
        )
        await env.mb.handle(ws, "mini_browser_vault_delete", {"id": "e1"})
        await env.mb.handle(ws, "mini_browser_vault_reset", {})

        assert env.vault.calls == [
            ("add_entry", ("example.com", "jo", PASSWORD, ""), {}),
            (
                "update_entry",
                ("e1",),
                {"site": None, "username": "jo2", "password": None, "label": "work"},
            ),
            ("delete_entry", ("e1",), {}),
            ("reset_unreadable", (), {}),
        ]
        results = channel.data("mini_browser_vault_result")
        assert [(r["op"], r["ok"]) for r in results] == [
            ("add", True),
            ("update", True),
            ("delete", True),  # already gone == done
            ("reset", True),
        ]
        assert results[-1]["backupPath"].endswith(".unreadable-1")
        assert len(env.vault_notices) == 4  # every change refreshes other tabs
        assert PASSWORD not in all_traffic(channel)

    run(go)


def test_vault_errors_are_mapped_and_scrubbed(env, captured_logs):
    async def go():
        ws, channel = connect(env)
        env.vault.fail = VaultError(
            "MINI_BROWSER_VAULT_INVALID", detail=f"password {PASSWORD} is too weak"
        )
        await env.mb.handle(
            ws,
            "mini_browser_vault_add",
            {"site": "example.com", "username": "jo", "password": PASSWORD},
        )
        env.vault.fail = VaultError("MINI_BROWSER_VAULT_UNREADABLE")
        await env.mb.handle(
            ws, "mini_browser_vault_update", {"id": "e1", "password": PASSWORD}
        )
        await env.mb.handle(ws, "mini_browser_vault_list", {})
        env.vault.fail = VaultError("MINI_BROWSER_VAULT_IO", detail="disk full")
        await env.mb.handle(ws, "mini_browser_vault_delete", {"id": "e1"})

        add, update, delete = channel.data("mini_browser_vault_result")
        assert (add["op"], add["ok"]) == ("add", False)
        assert add["error"]["code"] == "MINI_BROWSER_VAULT_INVALID"
        assert "[redacted]" in add["error"]["message"]
        assert update["error"]["code"] == "MINI_BROWSER_VAULT_UNREADABLE"
        assert update["error"]["title"] == "Password vault unreadable"
        assert delete["error"]["code"] == "MINI_BROWSER_VAULT_IO"
        assert "disk full" in delete["error"]["message"]
        [listing] = channel.data("mini_browser_vault_list")
        assert listing["entries"] == []
        assert listing["error"]["code"] == "MINI_BROWSER_VAULT_UNREADABLE"
        assert PASSWORD not in all_traffic(channel)
        assert len(env.vault_notices) == 3  # failed changes still refresh

    run(go)
    assert not any(PASSWORD in line for line in captured_logs)


def test_short_password_in_an_error_masks_the_whole_text(env):
    async def go():
        ws, channel = connect(env)
        env.vault.fail = VaultError(
            "MINI_BROWSER_VAULT_INVALID", detail="bad value q7 given"
        )
        await env.mb.handle(
            ws,
            "mini_browser_vault_add",
            {"site": "example.com", "username": "jo", "password": "q7"},
        )
        [result] = channel.data("mini_browser_vault_result")
        assert result["error"]["code"] == "MINI_BROWSER_VAULT_INVALID"
        assert "q7" not in json.dumps(result)

    run(go)


@pytest.mark.parametrize(
    "error,expected",
    [
        (VaultError("MINI_BROWSER_VAULT_INVALID"), "The login details are not valid."),
        (
            VaultError("MINI_BROWSER_VAULT_INVALID", detail="Enter the site address."),
            "Enter the site address.",
        ),
        (
            PlainVaultError("MINI_BROWSER_VAULT_INVALID"),
            "The login details are not valid.",
        ),
        (
            PlainVaultError("MINI_BROWSER_VAULT_IO", "disk full\nmore"),
            "The password vault could not be saved: disk full",
        ),
    ],
)
def test_vault_error_messages_are_user_facing(env, error, expected):
    async def go():
        ws, channel = connect(env)
        env.vault.fail = error
        await env.mb.handle(ws, "mini_browser_vault_delete", {"id": "e1"})
        [result] = channel.data("mini_browser_vault_result")
        assert result["error"]["code"] == error.code
        assert result["error"]["message"] == expected

    run(go)


def test_unexpected_vault_exception_never_leaks_the_password(env, captured_logs):
    async def go():
        ws, channel = connect(env)
        env.vault.fail = ValueError(f"cannot encrypt {PASSWORD}")
        await env.mb.handle(
            ws,
            "mini_browser_vault_add",
            {"site": "example.com", "username": "jo", "password": PASSWORD},
        )
        [result] = channel.data("mini_browser_vault_result")
        assert result["error"]["code"] == "MINI_BROWSER_INTERNAL"
        assert PASSWORD not in all_traffic(channel)

    run(go)
    assert not any(PASSWORD in line for line in captured_logs)


@pytest.mark.parametrize(
    "msg_type,data",
    [
        (
            "mini_browser_vault_add",
            {"site": "a.com", "username": "jo", "password": 1234},
        ),
        (
            "mini_browser_vault_add",
            {"site": ["a.com"], "username": "jo", "password": "x"},
        ),
        (
            "mini_browser_vault_add",
            {"site": "a.com", "username": "jo", "password": "p" * 5000},
        ),
        ("mini_browser_vault_update", {"password": "x"}),
        ("mini_browser_vault_update", {"id": {"$ne": 1}}),
        ("mini_browser_vault_delete", {}),
    ],
)
def test_malformed_vault_requests_never_reach_the_vault(env, msg_type, data):
    async def go():
        ws, channel = connect(env)
        await env.mb.handle(ws, msg_type, data)
        assert env.vault.calls == []
        [result] = channel.data("mini_browser_vault_result")
        assert result["ok"] is False
        assert result["error"]["code"] == "MINI_BROWSER_INVALID_INPUT"
        assert "p" * 50 not in json.dumps(result)

    run(go)


# ─────────────────────────────────────────────────────────── install


def test_install_streams_progress_and_resets_the_launch_error(env, monkeypatch):
    def fake_install(log):
        log("    $ python -m playwright install chromium")
        log("      Downloading Chromium 145 from https://cdn.example/chromium.zip")
        log("   ")
        return True, "chromium present"

    monkeypatch.setattr(mbws, "_run_install", fake_install)

    async def go():
        env.mb.on_start()
        env.core.status = "error"
        env.core.last_error = ui_error("MINI_BROWSER_CHROMIUM_MISSING")
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        await env.mb.handle(ws, "mini_browser_install", {})
        await drain(env)

        states = channel.data("mini_browser_state")
        assert states[0]["status"] == "error"  # subscribe
        assert states[1]["status"] == "installing"  # while installing
        assert states[1]["error"] is None
        progress = channel.data("mini_browser_install_progress")
        assert [p.get("line") for p in progress[:-1]] == [
            "$ python -m playwright install chromium",
            "Downloading Chromium 145 from https://cdn.example/chromium.zip",
        ]
        assert progress[-1] == {"done": True, "ok": True}
        assert (env.core.status, env.core.last_error) == ("stopped", None)
        assert states[-1]["status"] == "stopped"  # Start works again

    run(go)


@pytest.mark.parametrize("outcome", ["failed", "raised"])
def test_install_failure_is_reported(env, monkeypatch, outcome):
    def fake_install(log):
        if outcome == "raised":
            raise RuntimeError("no network")
        return False, "install failed"

    monkeypatch.setattr(mbws, "_run_install", fake_install)

    async def go():
        env.mb.on_start()
        env.host_started = False
        ws, channel = connect(env)
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        await env.mb.handle(ws, "mini_browser_install", {})
        [done] = channel.data("mini_browser_install_progress")
        assert done["done"] is True and done["ok"] is False
        assert done["error"]["code"] == "MINI_BROWSER_INSTALL_FAILED"
        assert channel.data("mini_browser_state")[-1]["status"] == "stopped"
        assert not env.host_started

    run(go)


def test_second_install_while_one_runs_is_ignored(env, monkeypatch):
    release = threading.Event()
    calls = []

    def slow_install(log):
        calls.append(1)
        release.wait(5)
        return True, ""

    monkeypatch.setattr(mbws, "_run_install", slow_install)

    async def go():
        ws, channel = connect(env)
        first = asyncio.ensure_future(env.mb.handle(ws, "mini_browser_install", {}))
        await until(lambda: calls)
        await env.mb.handle(ws, "mini_browser_install", {})  # returns at once
        release.set()
        await first
        assert calls == [1]
        assert len(channel.data("mini_browser_install_progress")) == 1

    run(go)


# ────────────────────────────────────────────────── adapter lifecycle hooks


def test_on_start_registers_the_sink_with_the_ui_hosts(env):
    async def go():
        env.mb.on_start()
        assert env.bridge.sinks == [env.mb]
        assert env.bridge.origins == env.adapter.ui_hosts
        assert "localhost:7926" in env.bridge.origins
        assert "[::1]:7926" in env.bridge.origins

    run(go)


def test_shutdown_unregisters_cancels_and_closes_the_browser(env):
    async def go():
        env.mb.on_start()
        env.core.navigate_gate = asyncio.Event()  # a page load that never ends
        ws, _ = connect(env)
        await env.mb.handle(ws, "mini_browser_subscribe", {})
        await env.mb.handle(ws, "mini_browser_navigate", {"url": "slow.example"})
        await asyncio.sleep(0)
        await env.mb.shutdown()
        assert env.bridge.unregistered == [env.mb]
        assert env.lifecycle.calls == [mbws._LIFECYCLE_SHUTDOWN_S]
        assert not env.mb.has_viewers()
        assert all(task.done() for task in env.mb._tasks)
        env.mb.post("frame", frame(1))  # after shutdown: dropped silently

    run(go)


def test_shutdown_never_raises(env):
    async def go():
        env.lifecycle.error = RuntimeError("driver died")
        await env.mb.shutdown()  # logged, not raised
        env.host_started = False
        env.lifecycle.calls.clear()
        await env.mb.shutdown()
        assert env.lifecycle.calls == []  # never started: nothing to close

    run(go)


def test_send_only_to_never_broadcasts(env):
    gone = object()
    ws, channel = connect(env)
    _, other = connect(env)
    assert env.adapter._send_only_to(gone, {"type": "x", "data": {}}) is False
    assert env.adapter._send_only_to(None, {"type": "x", "data": {}}) is False
    channel.closed = True
    assert env.adapter._send_only_to(ws, {"type": "x", "data": {}}) is False
    assert channel.sent == [] and other.sent == []
    channel.closed = False
    assert env.adapter._send_only_to(ws, {"type": "x", "data": {"a": 1}}) is True
    assert channel.sent == [{"type": "x", "data": {"a": 1}}]


def test_adapter_without_mini_browser_ignores_its_messages():
    adapter = make_adapter()  # built via __new__: no _mini_browser_ws at all
    asyncio.run(
        adapter._handle_ws_message({"type": "mini_browser_subscribe"}, object())
    )


class RecordingMiniBrowser:
    def __init__(self) -> None:
        self.handled = []
        self.forgotten = []

    async def handle(self, ws, msg_type, data):
        self.handled.append((ws, msg_type, data.get("requestId")))

    def forget(self, ws):
        self.forgotten.append(ws)


def _stub_ws_adapter(mini_browser) -> BrowserAdapter:
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter._ws_clients = {object()}  # not the first client: no onboarding hook
    adapter._channels = {}
    adapter._metrics_subscribers = set()
    adapter._lane_locks = {}
    adapter._lane_tasks = set()
    adapter._started_at = 0.0
    adapter._ws_prepare_failures = 0
    adapter._get_initial_state = lambda: {"stub": True}
    adapter._get_skill_meta = lambda: {}
    adapter._agent_app_manager = SimpleNamespace(list_projects=lambda: [])
    adapter._mini_browser_ws = mini_browser
    return adapter


def test_websocket_routes_to_the_handler_and_forgets_on_close(monkeypatch):
    monkeypatch.setenv("VITE_PORT", "7925")
    recorder = RecordingMiniBrowser()

    async def go():
        adapter = _stub_ws_adapter(recorder)
        app = web.Application()
        app.router.add_get("/ws", adapter._websocket_handler)
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        adapter._ws_auth = WsAuth(server.port, token=TOKEN)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    f"http://127.0.0.1:{server.port}/ws",
                    headers={"Origin": f"http://127.0.0.1:{server.port}"},
                    protocols=("craftbot", f"craftbot-auth.{TOKEN}"),
                ) as ws:
                    await ws.receive()  # init
                    await ws.send_str(
                        json.dumps(
                            {"type": "mini_browser_subscribe", "requestId": "r1"}
                        )
                    )
                    await until(lambda: recorder.handled)
            await until(lambda: recorder.forgotten)
        finally:
            await server.close()

    asyncio.run(go())
    [(server_ws, msg_type, request_id)] = recorder.handled
    assert (msg_type, request_id) == ("mini_browser_subscribe", "r1")
    assert recorder.forgotten == [server_ws]


# ─────────────────────────────────────────────────────── error codebook


@pytest.mark.parametrize("code", sorted(ERROR_SPECS))
def test_every_mini_browser_code_is_in_the_codebook(code):
    category, severity, title, template = ERROR_SPECS[code]
    fields = {name: "x" for _, name, _, _ in string.Formatter().parse(template) if name}
    info = make_error(code, **fields)
    assert info.code == code
    assert info.category.value == category
    assert info.severity.value == severity
    assert info.title == title
    assert "{" not in info.message


def test_ui_errors_keep_their_addresses_and_mask_secrets():
    # Contract C9: messages are formatted from ERROR_SPECS without the
    # codebook's generic redact(), which turned the very URLs and e-mail
    # addresses they are about into "[REDACTED]"; secrets are still masked.
    error = ui_error(
        "MINI_BROWSER_NAVIGATION_FAILED",
        secrets=[PASSWORD],
        url="https://a.example/login",
        detail=f"no account for jo@example.com (tried {PASSWORD})",
    )
    assert error["title"] == "Page failed to load"
    assert "https://a.example/login" in error["message"]
    assert "jo@example.com" in error["message"]
    assert "REDACTED" not in error["message"]
    assert PASSWORD not in error["message"]


# ─────────────────────────────────────────────── settings (app/config.py)


def test_settings_defaults_when_absent(monkeypatch):
    monkeypatch.setattr(app_config, "get_settings", lambda reload=False: {})
    assert app_config.get_mini_browser_settings() == {
        "headless": True,
        "adblock": True,
        "humanlike": True,
        "show_cursor": True,
        "max_fps": 12,
        "jpeg_quality": 70,
        "search_url": "https://duckduckgo.com/?q={query}",
        "allow_file_urls": False,
        "max_agent_tabs": 6,
        "idle_shutdown_minutes": 30,
        "locale": "",
        "channel": "chromium",
    }


def test_settings_are_validated_and_clamped(monkeypatch):
    stored = {
        "headless": "no",
        "adblock": False,
        "humanlike": 0,
        "show_cursor": False,
        "max_fps": 999,
        "jpeg_quality": 5.6,
        "search_url": "ftp://x/?q={query}",
        "allow_file_urls": True,
        "max_agent_tabs": True,
        "idle_shutdown_minutes": float("nan"),
        "locale": " ja_JP ",
        "channel": "MSEdge",
    }
    monkeypatch.setattr(
        app_config, "get_settings", lambda reload=False: {"mini_browser": stored}
    )
    settings = app_config.get_mini_browser_settings()
    assert settings["headless"] is True  # wrong type -> default
    assert settings["adblock"] is False
    assert settings["humanlike"] is True
    assert settings["show_cursor"] is False
    assert settings["max_fps"] == 30
    assert settings["jpeg_quality"] == 30
    assert settings["search_url"] == "https://duckduckgo.com/?q={query}"
    assert settings["allow_file_urls"] is True
    assert settings["max_agent_tabs"] == 6
    assert settings["idle_shutdown_minutes"] == 30
    assert settings["locale"] == "ja-JP"
    assert settings["channel"] == "msedge"


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://www.google.com/search?q={query}", True),
        ("http://localhost:8080/?s={query}&x=1", True),
        ("https://x.example/search", False),  # no slot
        ("https://x.example/?q={query}&t={x}", False),  # stray field
        ("https://x.example/?q={{query}}", False),  # escaped: no slot
        ("javascript:alert({query})", False),
        ("https://x.example/?q={query}\n", True),  # stripped
        ("https://x.example/\x00?q={query}", False),
    ],
)
def test_search_url_validation(monkeypatch, url, ok):
    monkeypatch.setattr(
        app_config,
        "get_settings",
        lambda reload=False: {"mini_browser": {"search_url": url}},
    )
    result = app_config.get_mini_browser_settings()["search_url"]
    assert (result == url.strip()) is ok


@pytest.mark.parametrize("broken", [None, [], "x", 5])
def test_settings_never_raise(monkeypatch, broken):
    monkeypatch.setattr(
        app_config, "get_settings", lambda reload=False: {"mini_browser": broken}
    )
    assert app_config.get_mini_browser_settings()["max_fps"] == 12

    def explode(reload=False):
        raise OSError("disk gone")

    monkeypatch.setattr(app_config, "get_settings", explode)
    assert app_config.get_mini_browser_settings()["channel"] == "chromium"


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(app_config, "SETTINGS_CONFIG_PATH", path)
    monkeypatch.setattr(app_config, "_settings_cache", None)
    return path


def test_set_setting_persists_and_keeps_other_settings(settings_file):
    settings_file.write_text(
        json.dumps({"api_keys": {"openai": "sk-keep"}, "mini_browser": {"max_fps": 5}}),
        encoding="utf-8",
    )
    app_config.set_mini_browser_setting("adblock", False)
    app_config.set_mini_browser_setting("max_fps", 500)
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["api_keys"] == {"openai": "sk-keep"}
    assert saved["mini_browser"] == {"max_fps": 30, "adblock": False}


def test_set_setting_refuses_bad_input(settings_file):
    original = json.dumps({"mini_browser": {"adblock": True}})
    settings_file.write_text(original, encoding="utf-8")
    app_config.set_mini_browser_setting("no_such_key", True)
    app_config.set_mini_browser_setting(["adblock"], True)  # never raises
    app_config.set_mini_browser_setting("adblock", "nope")
    app_config.set_mini_browser_setting("max_fps", float("inf"))
    assert settings_file.read_text(encoding="utf-8") == original


def test_set_setting_never_clobbers_an_unreadable_settings_file(settings_file):
    settings_file.write_text('{"api_keys": {"openai": "sk-keep"', encoding="utf-8")
    app_config.set_mini_browser_setting("adblock", False)  # logged, not raised
    assert settings_file.read_text(encoding="utf-8") == (
        '{"api_keys": {"openai": "sk-keep"'
    )


def test_set_setting_creates_a_missing_settings_file(settings_file):
    app_config.set_mini_browser_setting("locale", "en_US")
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["mini_browser"]["locale"] == "en-US"
    assert "model" in saved  # written from the shipped defaults
