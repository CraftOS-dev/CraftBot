"""Settings > Security > Network ("Block local network") in the Mini Browser.

A port of OpenClaw's browser navigation guard: with the setting on, every
document the browser is about to load (typed or agent-opened addresses,
redirect hops, links, form posts, scripted navigations, pop-ups, frames) is
checked like the web tools' requests; subresources are not, as in OpenClaw.
With the setting off nothing is intercepted or looked up.

The browser tests drive a real headless Chromium against a local server.
Chromium maps the made-up public host names below to that server, while the
guard's own resolver says they are public, so "public" pages and the local
"intranet" (127.0.0.1) are both served by the same test server.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlsplit

import pytest

from app.mini_browser import bridge, config, lifecycle, netguard
from app.mini_browser import host as host_module
from app.mini_browser.config import MiniBrowserSettings
from app.mini_browser.errors import MiniBrowserError
from app.mini_browser.fleet import BrowserFleet
from app.mini_browser.host import MiniBrowserHost
from app.security import net
from app.security.policy import SecurityStore, set_store_for_tests
from tests.mini_browser_fixtures import import_playwright_or_skip, skip_browser_missing

SESSION = "netguard-chat"
PUBLIC_DNS = {
    "public.test": ("93.184.216.34",),
    "other.test": ("93.184.216.35",),
    "localhost": ("127.0.0.1",),
    "intranet.test": ("10.1.2.3",),
    "metadata.test": ("169.254.169.254",),
}


def _fake_resolve(host: str, port: int) -> Tuple[str, ...]:
    try:
        return (str(ipaddress.ip_address(host)),)  # an IP literal is itself
    except ValueError:
        pass
    try:
        return PUBLIC_DNS[host]
    except KeyError:
        raise socket.gaierror(f"unknown host {host}") from None


@pytest.fixture(autouse=True)
def _fresh_cache():
    netguard.clear_cache()
    yield
    netguard.clear_cache()


# ═════════════════════════════════════════════════════════════════════════════
# Without a browser
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = SecurityStore(tmp_path / "security.json")
    set_store_for_tests(store)
    monkeypatch.setattr(net, "_resolve", _fake_resolve)
    yield store
    set_store_for_tests(None)


def test_off_looks_nothing_up(store, monkeypatch):
    def boom(host, port):
        raise AssertionError("resolved with the setting off")

    monkeypatch.setattr(net, "_resolve", boom)
    assert netguard.refusal("http://127.0.0.1/") is None
    assert asyncio.run(netguard.check("http://10.0.0.1/")) is None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://127.0.0.1:8080/", "127.0.0.1 is on this computer"),
        ("http://localhost/", "localhost (127.0.0.1) is on this computer"),
        ("https://intranet.test/", "intranet.test (10.1.2.3) is on the local network"),
        ("http://metadata.test/", "metadata.test (169.254.169.254) is on the local network"),
        ("http://169.254.169.254/latest/", "169.254.169.254 is on the local network"),
        ("http://[::1]/", "::1 is on this computer"),
        ("http://nowhere.test/", "nowhere.test could not be resolved"),
    ],
)
def test_on_refuses_non_public_addresses_with_a_short_reason(store, url, expected):
    store.update({"network_guard": True})
    reason = netguard.refusal(url)
    assert reason is not None and reason.startswith(expected), reason
    assert "Settings > Security > Network" in reason
    with pytest.raises(MiniBrowserError) as info:
        asyncio.run(netguard.ensure_allowed(url))
    assert info.value.code == "MINI_BROWSER_BLOCKED_URL"


def test_on_lets_public_and_non_http_addresses_through(store):
    store.update({"network_guard": True})
    assert netguard.refusal("https://public.test/a?b=c") is None
    for url in ("about:blank", "data:text/html,hi", "chrome-error://chromewebdata/"):
        assert netguard.refusal(url) is None


def test_allowed_domains_apply_to_the_browser(store):
    store.update({"network_guard": True, "allowed_domains": ["public.test"]})
    assert netguard.refusal("https://public.test/") is None
    assert "not in the allowed domains" in netguard.refusal("https://other.test/")


def test_one_lookup_answers_repeated_checks_until_the_setting_changes(store, monkeypatch):
    calls: List[str] = []

    def counting(host, port):
        calls.append(host)
        return _fake_resolve(host, port)

    monkeypatch.setattr(net, "_resolve", counting)
    store.update({"network_guard": True})
    for _ in range(5):
        assert netguard.refusal("https://public.test/page") is None
    assert calls == ["public.test"]
    # A new allowlist is a new question.
    store.update({"allowed_domains": ["public.test"]})
    assert netguard.refusal("https://public.test/page") is None
    assert calls == ["public.test", "public.test"]


def test_the_web_tools_messages_are_unchanged(store):
    store.update({"network_guard": True})
    assert net.url_refusal("http://127.0.0.1/") == (
        "Blocked: 127.0.0.1 resolves to 127.0.0.1 is this computer (loopback). "
        "The agent's web tools only reach the public internet "
        "(Settings > Security > Network)."
    )
    assert net.url_refusal("ftp://public.test/") == (
        "Only http and https URLs can be fetched, not ftp."
    )


# ═════════════════════════════════════════════════════════════════════════════
# A real Chromium
# ═════════════════════════════════════════════════════════════════════════════


class Site:
    """Serves every page; records hits by (host, path)."""

    def __init__(self) -> None:
        self.hits: Dict[Tuple[str, str], int] = {}
        self._lock = threading.Lock()
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _record(self) -> Tuple[str, Dict[str, List[str]]]:
                parts = urlsplit(self.path)
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
                with site._lock:
                    key = (host, parts.path)
                    site.hits[key] = site.hits.get(key, 0) + 1
                return parts.path, parse_qs(parts.query)

            def _send(self, status: int, body: str, headers: Dict[str, str] = {}) -> None:
                data = body.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                self._record()
                self._send(200, "<title>posted</title>posted")

            def do_GET(self) -> None:
                path, query = self._record()
                to = (query.get("to") or [""])[0]
                if path == "/redirect":
                    self._send(302, "", {"Location": to})
                elif path == "/link":
                    self._send(200, f'<title>link</title><a id="a" href="{to}">go</a>')
                elif path == "/form":
                    self._send(
                        200,
                        f'<title>form</title><form id="f" method="post" action="{to}">'
                        f'<input name="x" value="1"></form>',
                    )
                elif path == "/frame":
                    self._send(200, f'<title>frame</title><iframe src="{to}"></iframe>')
                elif path == "/img":
                    self._send(200, f'<title>img</title><img id="i" src="{to}">')
                else:
                    self._send(200, f"<title>{path}</title><p>ok {path}</p>")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def url(self, path: str, host: str = "public.test") -> str:
        return f"http://{host}:{self.port}{path}"

    def count(self, path: str, host: str = "127.0.0.1") -> int:
        with self._lock:
            return self.hits.get((host, path), 0)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class FakeSink:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.posts: List[Tuple[str, Dict[str, Any]]] = []

    def has_viewers(self, key: str) -> bool:
        return False

    def post(self, kind: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self.posts.append((kind, dict(payload)))

    def blocked(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [p for k, p in self.posts if k == "event" and p.get("kind") == "blocked"]


async def op_eval(core, tab, *, script):
    value = await tab.page.evaluate(script)
    return {"status": "success", "message": "evaluated", "value": value}


def _run(coro, timeout: float = 60.0):
    async def bounded():
        return await asyncio.wait_for(coro, timeout)

    return asyncio.run(bounded())


class Browser:
    def __init__(self, host: MiniBrowserHost, sink: FakeSink, site: Site, store) -> None:
        self.host, self.sink, self.site, self.store = host, sink, site, store

    def call(self, fn, timeout: float = 60.0):
        return _run(self.host.call(SESSION, fn), timeout)

    def inspect(self, fn):
        async def apply(core):
            return fn(core)

        return self.call(apply)

    def op(self, op: str, **params):
        return self.call(lambda core: core.agent_op("agent", op, params))

    def wait_until(self, predicate, timeout: float = 10.0, what: str = "condition"):
        deadline = time.monotonic() + timeout
        while True:
            value = predicate()
            if value:
                return value
            if time.monotonic() > deadline:
                raise AssertionError(f"timed out waiting for {what}")
            time.sleep(0.05)

    def guard(self, on: bool) -> None:
        self.store.update({"network_guard": on})
        # The running browser hears of the change without an agent action.
        self.wait_until(
            lambda: self.inspect(lambda core: core._netguard_applied) is on,
            what="the interception to follow the setting",
        )


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    import_playwright_or_skip()
    patch = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp("mini_browser_netguard")
    store = SecurityStore(root / "security.json")
    set_store_for_tests(store)
    patch.setattr(net, "_resolve", _fake_resolve)
    patch.setattr(config, "profile_dir", lambda key: root / "profiles" / key)
    patch.setattr(config, "workspace_dir", lambda owner: root / "workspace" / (owner or "_user"))
    patch.setattr(config, "save_setting", lambda key, value: None)
    site = Site()
    sink = FakeSink()
    bridge.register_ui_sink(sink)
    from app.mini_browser.ops import OPS

    rules = ", ".join(f"MAP {name} 127.0.0.1" for name in ("public.test", "other.test"))
    host = MiniBrowserHost(
        lambda: BrowserFleet(
            settings=MiniBrowserSettings(idle_shutdown_minutes=0, max_agent_tabs=4),
            ops_registry={**OPS, "eval": op_eval},
            launch_args=(f"--host-resolver-rules={rules}",),
        )
    )
    patch.setattr(host_module, "_host", host)  # the setting's change notice reaches it
    lifecycle._reset_for_tests()
    result = Browser(host, sink, site, store)
    try:
        result.call(lambda core: core.start(), timeout=120)
    except MiniBrowserError as exc:
        asyncio.run(host.shutdown(timeout=10))
        bridge.unregister_ui_sink(sink)
        site.close()
        set_store_for_tests(None)
        patch.undo()
        if exc.code in ("MINI_BROWSER_CHROMIUM_MISSING", "MINI_BROWSER_PLAYWRIGHT_MISSING"):
            skip_browser_missing(f"Chromium unavailable ({exc.code})")
        raise
    yield result
    asyncio.run(host.shutdown(timeout=20))
    bridge.unregister_ui_sink(sink)
    site.close()
    lifecycle._reset_for_tests()
    set_store_for_tests(None)
    patch.undo()


@pytest.fixture
def guarded(browser):
    browser.guard(True)
    browser.sink.posts.clear()
    yield browser
    browser.guard(False)


def _settle():
    time.sleep(0.6)  # a refused request would have reached the server by now


def test_off_the_browser_opens_local_addresses_as_today(browser):
    # Turned on and off again: nothing is intercepted any more.
    browser.guard(True)
    browser.guard(False)
    site = browser.site
    result = browser.op("navigate", url=site.url("/off-local", "127.0.0.1"))
    assert result["status"] == "success", result
    assert site.count("/off-local") == 1
    # The pages the guarded tests use do reach the local address when off.
    target = site.url("/off-link", "127.0.0.1")
    opened = browser.op("navigate", url=site.url(f"/link?to={target}"))
    assert opened["status"] == "success", opened
    browser.op("eval", script="() => { document.getElementById('a').click(); return true; }")
    browser.wait_until(lambda: site.count("/off-link") == 1, what="the link to load")
    redirected = browser.op(
        "navigate", url=site.url(f"/redirect?to={site.url('/off-redirect', '127.0.0.1')}")
    )
    assert redirected["status"] == "success", redirected
    assert site.count("/off-redirect") == 1


def test_a_local_address_is_refused_before_it_is_requested(guarded):
    site = guarded.site
    result = guarded.op("navigate", url=site.url("/direct", "127.0.0.1"))
    assert result["status"] == "error"
    assert result["error_code"] == "MINI_BROWSER_BLOCKED_URL", result
    assert "this computer" in str(result)
    _settle()
    assert site.count("/direct") == 0
    fine = guarded.op("navigate", url=site.url("/fine"))
    assert fine["status"] == "success", fine
    assert site.count("/fine", "public.test") == 1


def test_a_redirect_into_the_local_network_is_stopped_at_the_hop(guarded):
    site = guarded.site
    target = site.url("/after-redirect", "127.0.0.1")
    before = site.count("/redirect", "public.test")
    result = guarded.op("navigate", url=site.url(f"/redirect?to={target}"))
    assert result["error_code"] == "MINI_BROWSER_BLOCKED_URL", result
    assert "led to http://127.0.0.1" in result["message"], result
    assert "this computer" in result["message"], result
    _settle()
    assert site.count("/redirect", "public.test") > before  # the public hop loaded
    assert site.count("/after-redirect") == 0
    guarded.wait_until(guarded.sink.blocked, what="a blocked notice")


@pytest.mark.parametrize(
    "page,script,path",
    [
        ("/link", "() => { document.getElementById('a').click(); return true; }", "/by-link"),
        ("/form", "() => { document.getElementById('f').submit(); return true; }", "/by-form"),
        ("/page", "() => { window.location.href = %r; return true; }", "/by-script"),
    ],
)
def test_navigations_a_page_makes_are_checked(guarded, page, script, path):
    site = guarded.site
    target = site.url(path, "127.0.0.1")
    opened = guarded.op("navigate", url=site.url(f"{page}?to={target}"))
    assert opened["status"] == "success", opened
    guarded.op("eval", script=script % target if "%r" in script else script)
    _settle()
    assert site.count(path) == 0
    guarded.wait_until(guarded.sink.blocked, what="a blocked notice")


def test_a_popup_into_the_local_network_is_refused(guarded):
    site = guarded.site
    opened = guarded.op("navigate", url=site.url("/opener"))
    assert opened["status"] == "success", opened
    target = site.url("/by-popup", "127.0.0.1")
    guarded.op("eval", script=f"() => !!window.open({target!r})")
    _settle()
    assert site.count("/by-popup") == 0


def test_frames_are_checked_but_subresources_are_not(guarded):
    site = guarded.site
    framed = guarded.op("navigate", url=site.url(f"/frame?to={site.url('/in-frame', '127.0.0.1')}"))
    assert framed["status"] == "success", framed
    # As in OpenClaw, images, scripts and fetches are not documents.
    pictured = guarded.op("navigate", url=site.url(f"/img?to={site.url('/pixel', '127.0.0.1')}"))
    assert pictured["status"] == "success", pictured
    guarded.wait_until(lambda: site.count("/pixel") >= 1, what="the image request")
    _settle()
    assert site.count("/in-frame") == 0


def test_the_url_bar_and_new_tabs_are_checked_too(guarded):
    site = guarded.site
    with pytest.raises(MiniBrowserError) as info:
        guarded.call(lambda core: core.ui_navigate(None, site.url("/typed", "127.0.0.1")))
    assert info.value.code == "MINI_BROWSER_BLOCKED_URL"
    _settle()
    assert site.count("/typed") == 0


def test_allowed_domains_limit_the_browser(guarded):
    site = guarded.site
    guarded.store.update({"allowed_domains": ["public.test"]})
    try:
        guarded.wait_until(lambda: True)
        allowed = guarded.op("navigate", url=site.url("/allowed"))
        assert allowed["status"] == "success", allowed
        refused = guarded.op("navigate", url=site.url("/elsewhere", "other.test"))
        assert refused["status"] == "error", refused
        assert "allowed domains" in str(refused)
        _settle()
        assert site.count("/elsewhere", "other.test") == 0
    finally:
        guarded.store.update({"allowed_domains": []})
