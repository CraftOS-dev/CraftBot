"""BrowserFleet: one browser per agent session.

Drives real (headless) Chromium against a local ``http.server`` on 127.0.0.1
(no internet): every session's cookies stay its own and survive a restart,
deleting a session deletes its browser and profile, at most
``max_running_browsers`` run at once, sub-agents browse in their parent
session's browser, a session's browsing activity is published once per run,
and a browser picks up where it left off (its pages reopen; its panel shows
the last picture meanwhile). Agent operations come from a FAKE ops registry and every path (profiles,
workspace, settings writes) points into a temp directory. Chromium tests skip
when Playwright or its Chromium is missing.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import types
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.mini_browser import actions_api, bridge, config, lifecycle, resume
from app.mini_browser import core as core_module
from app.mini_browser import host as host_module
from app.mini_browser.config import MiniBrowserSettings
from app.mini_browser.core import RELAUNCH_NOTE, BrowserCore, delete_profile
from app.mini_browser.errors import MiniBrowserError
from app.mini_browser.fleet import BrowserFleet
from app.mini_browser.host import MiniBrowserHost
from tests.mini_browser_fixtures import (
    BROWSER_MISSING_CODES,
    LocalServer,
    import_playwright_or_skip,
    skip_browser_missing,
)


def run(coro, timeout: float = 120.0):
    async def bounded():
        return await asyncio.wait_for(coro, timeout)

    return asyncio.run(bounded())


async def _apply(fn, target):
    return fn(target)


@pytest.fixture(autouse=True)
def _fresh_lifecycle_records():
    lifecycle._reset_for_tests()
    yield
    lifecycle._reset_for_tests()


# ── fakes ────────────────────────────────────────────────────────────────────


async def op_goto(core, tab, *, url):
    await tab.page.goto(url, wait_until="domcontentloaded", timeout=20000)
    return {"status": "success", "message": "navigated", "url": tab.page.url}


async def op_cookies(core, tab):
    cookies = await tab.page.context.cookies()
    return {
        "status": "success",
        "message": "cookies",
        "cookies": sorted(f"{c['name']}={c['value']}" for c in cookies),
    }


async def op_read(core, tab, **params):
    return {"status": "success", "message": "read", "url": tab.page.url}


FAKE_OPS = {"goto": op_goto, "cookies": op_cookies, "read": op_read}


class FakeSink:
    """The UI side of the bridge: records what the browsers publish."""

    def __init__(self) -> None:
        self.viewers: set = set()
        self._lock = threading.Lock()
        self._posts: List[tuple] = []

    def has_viewers(self, key: str) -> bool:
        return key in self.viewers

    def post(self, kind: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._posts.append((kind, dict(payload)))

    def of(self, kind: str, session: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                payload
                for k, payload in self._posts
                if k == kind
                and (session is None or payload.get("sessionId") == session)
            ]


class _Manager:
    """The session / sub-agent manager surface the Mini Browser reads."""

    def __init__(self, items: Dict[str, Any]) -> None:
        self.sessions = items

    def get(self, key: str) -> Any:
        return self.sessions.get(key)


def fake_agent_runtime(
    monkeypatch, sessions: Dict[str, Any], subagents: Optional[Dict[str, Any]] = None
) -> types.SimpleNamespace:
    runtime = types.SimpleNamespace(
        session_manager=_Manager(sessions), subagent_manager=_Manager(subagents or {})
    )

    class InternalActionInterface:
        session_manager = runtime.session_manager
        subagent_manager = runtime.subagent_manager

    module = types.ModuleType("app.internal_action_interface")
    module.InternalActionInterface = InternalActionInterface
    monkeypatch.setitem(sys.modules, "app.internal_action_interface", module)
    return runtime


def session(title: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(title=title, workspace_dir=None)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def site():
    server = LocalServer()
    server.add("/page", "<title>Page</title>hello")
    server.add(
        "/set",
        "<title>Set</title>cookie set",
        headers={"Set-Cookie": "who=alpha; Max-Age=86400; Path=/"},
    )
    server.add(
        "/iconpage", '<title>Icons</title><link rel="icon" href="/icon.svg">icons'
    )
    server.add(
        "/icon.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>',
        ctype="image/svg+xml",
    )
    # A stand-in .ico (only its signature is read).
    server.add("/favicon.ico", "\x00\x00\x01\x00icon", ctype="image/x-icon")
    yield server
    server.close()


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Profiles, workspaces and settings writes in a temp directory."""
    root = tmp_path / "profiles"
    monkeypatch.setattr(config, "profiles_root", lambda: root)
    monkeypatch.setattr(
        config, "workspace_dir", lambda owner: tmp_path / "workspace" / (owner or "_")
    )
    monkeypatch.setattr(config, "save_setting", lambda key, value: None)
    return root


@pytest.fixture
def sink():
    recorder = FakeSink()
    bridge.register_ui_sink(recorder)
    yield recorder
    bridge.unregister_ui_sink(recorder)


def make_host(max_running: int = 4) -> MiniBrowserHost:
    settings = MiniBrowserSettings(
        idle_shutdown_minutes=0, max_running_browsers=max_running
    )
    return MiniBrowserHost(
        lambda: BrowserFleet(settings=settings, ops_registry=FAKE_OPS)
    )


def op(
    host: MiniBrowserHost, owner: str, name: str, key: Optional[str] = None, **params
):
    """Run agent operation ``name`` for ``owner`` in session ``key``'s browser."""
    return run(host.call(key or owner, lambda core: core.agent_op(owner, name, params)))


def inspect(host: MiniBrowserHost, key: str, fn):
    return run(host.call(key, lambda core: _apply(fn, core)))


def fleet_inspect(host: MiniBrowserHost, fn):
    return run(host.call_fleet(lambda fleet: _apply(fn, fleet)))


def first_op(host: MiniBrowserHost, owner: str, url: str) -> Dict[str, Any]:
    """The first operation of a test: skips when Chromium is not installed."""
    result = op(host, owner, "goto", url=url)
    if result.get("error_code") in BROWSER_MISSING_CODES:
        run(host.shutdown(timeout=20))
        skip_browser_missing(f"Chromium unavailable ({result['error_code']})")
    assert result["status"] == "success", result
    return result


def wait_for(predicate, timeout: float = 15.0, what: str = "condition"):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.05)


# ═════════════════════════════════════════════════════════════════════════════
# Real Chromium
# ═════════════════════════════════════════════════════════════════════════════


def test_each_session_keeps_its_own_cookies_across_restarts(site, paths):
    import_playwright_or_skip()
    host = make_host()
    try:
        first_op(host, "chat-a", site.url("/set"))
        assert op(host, "chat-a", "cookies")["cookies"] == ["who=alpha"]
        op(host, "chat-b", "goto", url=site.url("/page"))
        assert op(host, "chat-b", "cookies")["cookies"] == []  # never shared
        assert sorted(p.name for p in paths.iterdir() if p.is_dir()) == [
            "chat-a",
            "chat-b",
        ]
    finally:
        run(host.shutdown(timeout=30))

    # A restart: each session's browser comes back with its own sign-ins.
    again = make_host()
    try:
        op(again, "chat-a", "goto", url=site.url("/page"))
        assert op(again, "chat-a", "cookies")["cookies"] == ["who=alpha"]
        op(again, "chat-b", "goto", url=site.url("/page"))
        assert op(again, "chat-b", "cookies")["cookies"] == []
    finally:
        run(again.shutdown(timeout=30))


def test_deleting_a_session_removes_its_browser_and_profile(
    site, paths, sink, monkeypatch
):
    import_playwright_or_skip()
    runtime = fake_agent_runtime(
        monkeypatch, {"chat-a": session("A"), "chat-b": session("B")}
    )
    host = make_host()
    monkeypatch.setattr(host_module, "_host", host)  # lifecycle reaches it
    try:
        first_op(host, "chat-a", site.url("/set"))
        op(host, "chat-b", "goto", url=site.url("/page"))
        profile = config.profile_dir("chat-a")
        assert profile.is_dir() and config.profile_lock_path(profile).exists()

        del runtime.session_manager.sessions["chat-a"]  # the chat is deleted ...
        lifecycle.stream_removed("chat-a")  # ... and its event stream with it
        wait_for(lambda: not profile.exists(), timeout=40, what="profile deleted")
        assert not config.profile_lock_path(profile).exists()
        assert fleet_inspect(host, lambda fleet: fleet.existing("chat-a")) is None

        # Its browser never comes back: not for a late sub-agent, not for the UI.
        with pytest.raises(MiniBrowserError) as info:
            inspect(host, "chat-a", lambda core: core.status)
        assert info.value.code == "MINI_BROWSER_SESSION_GONE"
        assert not profile.exists()
        # Another session's browser is untouched.
        assert inspect(host, "chat-b", lambda core: core.status) == "ready"
        assert config.profile_dir("chat-b").is_dir()
        assert sink.of("activity", "chat-a")[-1]["status"] == "stopped"
    finally:
        run(host.shutdown(timeout=30))


def test_the_running_limit_closes_the_browser_idle_the_longest(site, paths):
    import_playwright_or_skip()
    host = make_host(max_running=2)
    try:
        first_op(host, "chat-a", site.url("/page"))
        op(host, "chat-b", "goto", url=site.url("/page"))
        inspect(host, "chat-a", lambda core: setattr(core, "_last_activity", 1.0))
        op(host, "chat-c", "goto", url=site.url("/page"))  # no room: a is idlest

        statuses = fleet_inspect(
            host, lambda fleet: {k: c.status for k, c in fleet.cores.items()}
        )
        assert statuses == {"chat-a": "stopped", "chat-b": "ready", "chat-c": "ready"}

        # a comes back (b is now idle the longest) and is told its tabs went.
        inspect(host, "chat-b", lambda core: setattr(core, "_last_activity", 2.0))
        back = op(host, "chat-a", "read")
        assert back["status"] == "success"
        assert back["message"].startswith(RELAUNCH_NOTE)
        running = fleet_inspect(
            host,
            lambda fleet: sorted(k for k, c in fleet.cores.items() if c.is_running()),
        )
        assert running == ["chat-a", "chat-c"]
    finally:
        run(host.shutdown(timeout=30))


def test_the_running_limit_refuses_when_every_browser_is_in_use(site, paths):
    import_playwright_or_skip()
    host = make_host(max_running=1)
    try:
        first_op(host, "chat-a", site.url("/page"))
        lifecycle.record_run_state("chat-a", "running")  # a's run goes on
        refused = op(host, "chat-b", "goto", url=site.url("/page"))
        assert refused["status"] == "error"
        assert refused["error_code"] == "MINI_BROWSER_TOO_MANY_BROWSERS"
        state = inspect(host, "chat-b", lambda core: core.state())
        assert state["status"] == "error"
        assert state["error"]["code"] == "MINI_BROWSER_TOO_MANY_BROWSERS"
        assert inspect(host, "chat-a", lambda core: core.status) == "ready"

        lifecycle.record_run_state("chat-a", "idle")  # now a can make room
        assert op(host, "chat-b", "goto", url=site.url("/page"))["status"] == "success"
        assert inspect(host, "chat-a", lambda core: core.status) == "stopped"
    finally:
        run(host.shutdown(timeout=30))


def test_a_sub_agent_browses_in_its_parent_sessions_browser(site, paths, monkeypatch):
    import_playwright_or_skip()
    fake_agent_runtime(
        monkeypatch,
        {"chat-a": session("Holiday plans")},
        {
            "sub_child001": types.SimpleNamespace(
                parent_task_id="chat-a",
                agent_type="browser_agent",
                created_at=datetime.utcnow().isoformat(),
            )
        },
    )
    host = make_host()
    monkeypatch.setattr(host_module, "_host", host)  # actions_api.get_host() uses it
    try:
        first_op(host, "chat-a", site.url("/set"))
        result = asyncio.run(
            actions_api.run_action("read", {"_session_id": "sub_child001"})
        )
        assert result["status"] == "success", result
        owners = inspect(
            host, "chat-a", lambda core: sorted(t.owner for t in core.tabs.values())
        )
        assert owners == ["chat-a", "sub_child001"]  # its own tab, the chat's browser
        assert fleet_inspect(host, lambda fleet: sorted(fleet.cores)) == ["chat-a"]
        # ... signed in like the chat (one profile).
        cookies = op(host, "sub_child001", "cookies", key="chat-a")
        assert cookies["cookies"] == ["who=alpha"]
    finally:
        run(host.shutdown(timeout=30))


def test_browsing_activity_is_published_once_per_run(site, paths, sink, monkeypatch):
    import_playwright_or_skip()
    host = make_host()
    monkeypatch.setattr(host_module, "_host", host)  # lifecycle hooks reach it
    try:
        first_op(host, "chat-a", site.url("/page"))  # outside a run
        wait_for(
            lambda: [
                a for a in sink.of("activity", "chat-a") if a["status"] == "ready"
            ],
            what="ready activity",
        )
        wait_for(
            lambda: not sink.of("activity", "chat-a")[-1]["browsing"],
            what="not browsing after a lone action",
        )
        before = len(sink.of("activity", "chat-a"))

        lifecycle.on_run_state("chat-a", "running")
        op(host, "chat-a", "read")
        op(host, "chat-a", "read")
        time.sleep(0.3)  # debounced publishing
        during = sink.of("activity", "chat-a")[before:]
        # One switch to browsing for the whole run (it opens the panel once).
        assert [a["browsing"] for a in during] == [True], during

        lifecycle.on_run_state("chat-a", "idle")
        wait_for(
            lambda: sink.of("activity", "chat-a")[-1]["browsing"] is False,
            what="browsing ends with the run",
        )
        # The state goes to the session's viewers only.
        assert sink.of("state", "chat-a") == []
    finally:
        run(host.shutdown(timeout=30))


def test_a_browser_reopens_its_pages_where_it_left_off(site, paths, sink):
    """A session's browser keeps its open pages saved (not a blank tab, not a
    page holding a vault secret) and, on close, a picture of the page on
    screen, which its open panel shows. At its next start the pages reopen as
    the user's tabs on the same page, and the agent is told so."""
    import_playwright_or_skip()
    host = make_host()
    profile = config.profile_dir("chat-a")
    try:
        first_op(host, "chat-a", site.url("/page"))  # the agent's tab
        sink.viewers.add("chat-a")  # the chat's panel is open

        async def open_user_tabs(core):
            leaked = await core.ui_new_tab(site.url("/page?token=s3cret"))
            core.tabs[leaked].filled_secrets.append("s3cret")
            await core.ui_new_tab()  # a blank tab
            return await core.ui_new_tab(site.url("/set"))

        viewed = run(host.call("chat-a", open_user_tabs))
        wait_for(
            lambda: inspect(
                host, "chat-a", lambda core: core.tabs[viewed].url == site.url("/set")
            ),
            what="the viewed tab loaded",
        )
        # Saved while it runs, so even a killed app can pick up from here.
        wait_for(
            lambda: (
                (resume.load_pages(profile) or resume.Pages(pages=())).pages
                == (
                    resume.Page(site.url("/page"), "Page"),
                    resume.Page(site.url("/set"), "Set"),
                )
            ),
            what="the open pages saved",
        )

        run(host.call("chat-a", lambda core: core.close()))
        saved = resume.load_pages(profile)
        assert saved is not None and saved.viewed == 1
        picture = resume.resume_frame(profile)
        assert picture is not None and picture.url == site.url("/set")
        assert picture.width > 0 and picture.height > 0 and picture.image
        shown = sink.of("last_frame", "chat-a")[-1]
        assert shown["image"].startswith("data:image/jpeg;base64,")
        assert shown["url"] == site.url("/set")

        run(host.call("chat-a", lambda core: core.ensure_started()))
        tabs = inspect(
            host,
            "chat-a",
            lambda core: [(tab.url, tab.owner) for tab in core.tabs.values()],
        )
        assert tabs == [(site.url("/page"), None), (site.url("/set"), None)]
        assert inspect(
            host, "chat-a", lambda core: core.tabs[core.viewed_tab_id].url
        ) == site.url("/set")
        # The agent learns its pages came back as the user's tabs, and goes on
        # in the one on screen.
        back = op(host, "chat-a", "read")
        assert back["status"] == "success"
        assert back["message"].startswith(RELAUNCH_NOTE)
        assert back["url"] == site.url("/set")
    finally:
        run(host.shutdown(timeout=30))


def test_tabs_carry_their_site_icons(site, paths):
    """Each tab's state carries its site's icon as an inline image: the one
    the page declares, else the site's /favicon.ico; a blank page has none."""
    import_playwright_or_skip()
    host = make_host()

    def icon(core):
        tab = next(t for t in core.state()["tabs"] if t["owner"] == "chat-a")
        return tab["favicon"] or ""

    try:
        first_op(host, "chat-a", site.url("/iconpage"))
        wait_for(
            lambda: inspect(host, "chat-a", icon).startswith(
                "data:image/svg+xml;base64,"
            ),
            what="the declared icon",
        )
        op(host, "chat-a", "goto", url=site.url("/page"))
        wait_for(
            lambda: inspect(host, "chat-a", icon).startswith(
                "data:image/x-icon;base64,"
            ),
            what="the site's favicon.ico",
        )
        op(host, "chat-a", "goto", url="about:blank")
        wait_for(lambda: inspect(host, "chat-a", icon) == "", what="no icon")
    finally:
        run(host.shutdown(timeout=30))


def test_a_saved_page_no_longer_allowed_is_not_reopened(site, paths):
    import_playwright_or_skip()
    profile = config.ensure_dir(config.profile_dir("chat-a"))
    resume.save_pages(
        profile,
        resume.Pages(
            pages=(
                resume.Page("chrome://settings/", "Settings"),
                resume.Page(site.url("/page"), "Page"),
            ),
            viewed=0,
        ),
    )
    host = make_host()
    try:
        first_op(host, "chat-b", site.url("/page"))  # Chromium is there
        run(host.call("chat-a", lambda core: core.ensure_started()))
        assert inspect(
            host, "chat-a", lambda core: [tab.url for tab in core.tabs.values()]
        ) == [site.url("/page")]
        assert inspect(
            host, "chat-a", lambda core: core.tabs[core.viewed_tab_id].url
        ) == site.url("/page")
    finally:
        run(host.shutdown(timeout=30))


def test_a_new_sessions_browser_starts_on_a_blank_tab_and_keeps_it_unsaved(site, paths):
    """A new chat's browser opens one blank tab of the user's (its panel shows
    what the browser is and what to try over it); a blank tab is never saved,
    so the next start is blank again."""
    import_playwright_or_skip()
    host = make_host()
    profile = config.profile_dir("chat-a")
    try:
        first_op(host, "chat-b", site.url("/page"))  # Chromium is there
        run(host.call("chat-a", lambda core: core.ensure_started()))
        assert inspect(
            host,
            "chat-a",
            lambda core: [(tab.url, tab.owner) for tab in core.tabs.values()],
        ) == [("about:blank", None)]
        assert resume.load_pages(profile) is None
        run(host.call("chat-a", lambda core: core.close()))
        assert resume.load_pages(profile) == resume.Pages(pages=())
        assert resume.resume_frame(profile) is None
    finally:
        run(host.shutdown(timeout=30))


# ═════════════════════════════════════════════════════════════════════════════
# No browser
# ═════════════════════════════════════════════════════════════════════════════


def test_orphaned_profiles_are_swept_and_nothing_else(paths, monkeypatch):
    for name in ("main", "chat-live", "chat-stored", "chat-gone", "chat-locked"):
        (paths / name / "Default").mkdir(parents=True)
    odd_live = "odd id/with spaces"
    (paths / config.profile_dir_name(odd_live)).mkdir()
    (paths / "stray.lock").write_bytes(b"")  # files are never touched
    fake_agent_runtime(
        monkeypatch, {"main": session("Main"), "chat-live": session("L"), odd_live: 1}
    )
    monkeypatch.setattr(
        config, "persisted_session_ids", lambda: frozenset({"chat-stored"})
    )
    lock = core_module._ProfileLock(config.profile_lock_path(paths / "chat-locked"))
    assert lock.acquire()  # another CraftBot still uses it
    try:
        removed = asyncio.run(BrowserFleet().sweep_orphaned_profiles())
    finally:
        lock.release()
    assert removed == ["chat-gone"]
    left = sorted(p.name for p in paths.iterdir())
    assert left == sorted(
        [
            "chat-live",
            "chat-locked",
            "chat-locked.lock",
            "chat-stored",
            "main",
            config.profile_dir_name(odd_live),
            "stray.lock",
        ]
    )


def test_the_sweep_never_guesses_without_the_runtime_or_storage(paths, monkeypatch):
    (paths / "chat-x").mkdir(parents=True)
    monkeypatch.delitem(sys.modules, "app.internal_action_interface", raising=False)
    assert asyncio.run(BrowserFleet().sweep_orphaned_profiles()) == []
    fake_agent_runtime(monkeypatch, {"main": session("Main")})
    monkeypatch.setattr(config, "persisted_session_ids", lambda: None)
    assert asyncio.run(BrowserFleet().sweep_orphaned_profiles()) == []
    assert (paths / "chat-x").is_dir()


def test_delete_profile_leaves_a_profile_in_use_alone(paths):
    profile = paths / "chat-busy"
    (profile / "Default").mkdir(parents=True)
    lock = core_module._ProfileLock(config.profile_lock_path(profile))
    assert lock.acquire()
    try:
        assert delete_profile(profile) is False
        assert profile.is_dir()
    finally:
        lock.release()
    assert delete_profile(profile) is True
    assert not profile.exists() and not config.profile_lock_path(profile).exists()
    assert delete_profile(profile) is True  # nothing left: done


def test_a_deleted_sessions_browser_never_starts_again(paths):
    core = BrowserCore(MiniBrowserSettings(idle_shutdown_minutes=0), key="chat-z")
    core.retired = True
    with pytest.raises(MiniBrowserError) as info:
        run(core.ensure_started())
    assert info.value.code == "MINI_BROWSER_SESSION_GONE"
    assert not config.profile_dir("chat-z").exists()


def test_the_fleet_refuses_browsers_for_sessions_that_do_not_exist(monkeypatch):
    fake_agent_runtime(monkeypatch, {"chat-a": session("A")})
    fleet = BrowserFleet(MiniBrowserSettings(), FAKE_OPS)
    assert fleet.core("chat-a").key == "chat-a"
    assert fleet.core("chat-a") is fleet.core("chat-a")
    for key in ("chat-unknown", "", None, 5):
        with pytest.raises(MiniBrowserError) as info:
            fleet.core(key)
        expected = (
            "MINI_BROWSER_SESSION_GONE"
            if key == "chat-unknown"
            else ("MINI_BROWSER_INVALID_INPUT")
        )
        assert info.value.code == expected
    assert fleet.existing("chat-unknown") is None
    # Tab ids are shared by every browser: a tab id names one tab in the UI.
    other = BrowserFleet(MiniBrowserSettings(), FAKE_OPS)
    assert fleet.core("chat-a")._tab_ids is fleet.tab_ids
    assert other.tab_ids is not fleet.tab_ids


def test_a_launch_failure_hides_the_browser_only_before_any_start():
    lifecycle.note_launch_result("MINI_BROWSER_LAUNCH_FAILED")
    assert lifecycle.unavailable_reason() == "MINI_BROWSER_LAUNCH_FAILED"
    lifecycle.note_launch_result(None)  # a browser started: the machine can run it
    assert lifecycle.unavailable_reason() is None
    lifecycle.note_launch_result("MINI_BROWSER_LAUNCH_FAILED")  # one session's own
    assert lifecycle.unavailable_reason() is None
    lifecycle.note_launch_result("MINI_BROWSER_TOO_MANY_BROWSERS")
    assert lifecycle.unavailable_reason() is None
    lifecycle.note_launch_result("MINI_BROWSER_CHROMIUM_MISSING")  # always
    assert lifecycle.unavailable_reason() == "MINI_BROWSER_CHROMIUM_MISSING"


def test_paths_never_leave_the_profiles_folder(paths):
    for key in ("../../etc", "a/b", "C:\\x", "con", "x" * 300):
        profile = config.profile_dir(key)
        assert profile.parent == paths
        assert Path(profile.name).name == profile.name
