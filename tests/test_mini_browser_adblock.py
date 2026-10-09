"""Mini Browser ad blocking (app/mini_browser/adblock.py).

Pure tests for the domain list and the pattern builders, plus one real
Chromium check that the CDP ``Network.setBlockedURLs`` patterns block what
they should, leave everything else alone, and keep the HTTP cache working
(the reason the Mini Browser never uses ``context.route``). The Chromium
test skips when Playwright or its Chromium is not installed.
"""

from __future__ import annotations

import asyncio
import collections
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.mini_browser import adblock

PROTECTED = [
    "google.com",
    "accounts.google.com",
    "www.google.com",
    "apis.google.com",
    "gstatic.com",
    "www.gstatic.com",
    "googleapis.com",
    "fonts.googleapis.com",
    "recaptcha.net",
    "www.recaptcha.net",
    "hcaptcha.com",
    "js.hcaptcha.com",
    "cloudflare.com",
    "challenges.cloudflare.com",
    "cdnjs.cloudflare.com",
    "facebook.com",
    "www.facebook.com",
    "connect.facebook.net",
    "apple.com",
    "appleid.apple.com",
    "microsoft.com",
    "login.microsoftonline.com",
    "login.live.com",
    "amazon.com",
    "www.amazon.com",
    "googletagmanager.com",
    "www.googletagmanager.com",
    "cdn.segment.com",
    "linkedin.com",
    "www.linkedin.com",
    "bing.com",
    "www.bing.com",
    "twitter.com",
    "x.com",
    "pinterest.com",
    "tiktok.com",
    "yandex.ru",
    "baidu.com",
    "github.com",
    "jsdelivr.net",
    "unpkg.com",
    "akamaihd.net",
]


def chromium_matches(url: str, pattern: str) -> bool:
    """Chromium's setBlockedURLs matching: the ``*``-separated pieces appear in
    order anywhere in the URL (InspectorNetworkAgent::Matches)."""
    position = 0
    for piece in pattern.split("*"):
        index = url.find(piece, position)
        if index < 0:
            return False
        position = index + len(piece)
    return True


def blocked(url: str, patterns) -> bool:
    return any(chromium_matches(url, pattern) for pattern in patterns)


# ── the domain list ──────────────────────────────────────────────────────────


def test_list_is_a_reasonable_size_and_well_formed():
    assert 90 <= len(adblock.AD_DOMAINS) <= 200
    domain = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
    for entry in adblock.AD_DOMAINS:
        assert entry == entry.strip().lower(), entry
        assert domain.match(entry), entry


@pytest.mark.parametrize("host", PROTECTED)
def test_logins_captchas_and_cdns_are_never_blocked(host):
    assert host not in adblock.AD_DOMAINS
    assert not adblock.is_ad_host(host)
    patterns = adblock.blocked_url_patterns(True, frozenset())
    assert not blocked(f"https://{host}/path/script.js", patterns)


def test_no_entry_is_a_protected_domain_or_its_parent():
    roots = {
        "google.com",
        "gstatic.com",
        "googleapis.com",
        "recaptcha.net",
        "hcaptcha.com",
        "cloudflare.com",
        "facebook.com",
        "facebook.net",
        "apple.com",
        "microsoft.com",
        "amazon.com",
        "microsoftonline.com",
        "live.com",
    }
    for entry in adblock.AD_DOMAINS:
        assert entry not in roots
        assert not any(root.endswith("." + entry) for root in roots), entry


@pytest.mark.parametrize(
    "host,expected",
    [
        ("doubleclick.net", True),
        ("ads.doubleclick.net", True),
        ("securepubads.g.doubleclick.net", True),
        ("DOUBLECLICK.NET.", True),
        ("adservice.google.com", True),
        ("notdoubleclick.net", False),
        ("doubleclick.net.evil.example", False),
        ("doubleclick", False),
        ("net", False),
        ("", False),
        ("google.com", False),
        ("www.google.com", False),
    ],
)
def test_is_ad_host_matches_on_label_boundaries(host, expected):
    assert adblock.is_ad_host(host) is expected


# ── setBlockedURLs patterns ──────────────────────────────────────────────────


def test_patterns_for_ads_and_ui_origins():
    origins = frozenset({"localhost:7926", "127.0.0.1:7926", "[::1]:7926"})
    patterns = adblock.blocked_url_patterns(True, origins)
    for expected in (
        "*://*.doubleclick.net/*",
        "*://doubleclick.net/*",
        "*://*.doubleclick.net:*",
        "*://doubleclick.net:*",
        "*://localhost:7926/*",
        "*://127.0.0.1:7926/*",
        "*://[::1]:7926/*",
    ):
        assert expected in patterns
    assert len(patterns) == len(set(patterns))


def test_ad_patterns_only_when_enabled():
    origins = frozenset({"localhost:7926"})
    patterns = adblock.blocked_url_patterns(False, origins)
    assert patterns == ["*://localhost:7926/*", "*://localhost.:7926/*"]
    assert adblock.blocked_url_patterns(False, frozenset()) == []


def test_extra_domains_are_cleaned():
    patterns = adblock.blocked_url_patterns(
        True,
        frozenset(),
        extra_domains=("Tracker.Example.", "localhost", "bad domain", "*.x", ""),
    )
    assert "*://tracker.example/*" in patterns
    assert "*://localhost:*" in patterns
    assert not any("bad domain" in p or "*.x" in p for p in patterns)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://doubleclick.net/x", True),
        ("https://ads.doubleclick.net/x.js?y=1", True),
        ("http://ads.doubleclick.net:8080/x", True),
        ("https://www.googletagservices.com/tag/js/gpt.js", True),
        ("https://notdoubleclick.net/x", False),
        ("https://doubleclick.network/x", False),
        ("https://www.google.com/recaptcha/api.js", False),
        ("https://www.gstatic.com/x.js", False),
        ("http://localhost:7926/api/session-token", True),
        ("http://localhost:7926/", True),
        ("http://localhost.:7926/", True),
        ("http://localhost:79260/", False),
        ("http://localhost:3000/", False),
        ("http://127.0.0.1:7926/", True),
        ("http://notlocalhost:7926/", False),
    ],
)
def test_pattern_semantics(url, expected):
    patterns = adblock.blocked_url_patterns(
        True, frozenset({"localhost:7926", "127.0.0.1:7926"})
    )
    assert blocked(url, patterns) is expected


def test_default_port_origins():
    patterns = adblock.blocked_url_patterns(
        False, frozenset({"localhost:80", "secure.example:443"})
    )
    assert blocked("http://localhost/x", patterns)
    assert blocked("https://secure.example/x", patterns)
    assert not blocked("https://localhost/x", patterns)
    bare = adblock.blocked_url_patterns(False, frozenset({"craftbot.internal"}))
    assert blocked("http://craftbot.internal:1234/", bare)
    assert blocked("https://craftbot.internal/", bare)


# ── browser-wide Fetch patterns (UI origins) ─────────────────────────────────


def fetch_matches(url: str, pattern: str) -> bool:
    """CDP Fetch urlPattern: the whole URL must match (``*`` / ``?`` wildcards)."""
    regex = "".join(
        ".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern
    )
    return re.fullmatch(regex, url) is not None


def test_ui_fetch_patterns():
    patterns = adblock.ui_fetch_patterns(
        frozenset({"localhost:7926", "[::1]:7926", "x.example:80"})
    )
    assert "http://localhost:7926/*" in patterns
    assert "https://localhost:7926/*" in patterns
    assert "http://[::1]:7926/*" in patterns
    assert "http://x.example/*" in patterns

    def any_match(url):
        return any(fetch_matches(url, p) for p in patterns)

    assert any_match("http://localhost:7926/")
    assert any_match("https://localhost:7926/")
    assert any_match("http://localhost:7926/api/session-token?x=1")
    assert any_match("http://localhost.:7926/")
    assert any_match("http://[::1]:7926/")
    assert any_match("http://x.example/index.html")
    assert any_match("https://x.example:80/index.html")
    assert not any_match("https://x.example/index.html")
    assert not any_match("http://localhost:7927/")
    assert not any_match("https://example.com/?u=http://localhost:7926/")
    assert adblock.ui_fetch_patterns(frozenset()) == []
    bare = adblock.ui_fetch_patterns(frozenset({"craftbot.internal"}))
    assert any(fetch_matches("http://craftbot.internal:1234/a", p) for p in bare)
    assert any(fetch_matches("https://craftbot.internal/a", p) for p in bare)


def test_no_request_interception_anywhere():
    """context/page.route turns Chromium's HTTP cache off: never use it."""
    package = Path(__file__).resolve().parent.parent / "app" / "mini_browser"
    for source in package.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert not re.search(r"\.route\(|route_from_har|\.unroute\(", text), source.name


# ── real Chromium ────────────────────────────────────────────────────────────


@pytest.fixture
def site():
    """A local site: /page loads a cacheable script, two "ad" images and a normal one."""
    hits = collections.Counter()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split("?")[0]
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            hits[(host, path)] += 1
            port = self.server.server_address[1]
            if path == "/page":
                body = (
                    "<html><body><script src='/res.js'></script>"
                    f"<img id='ad1' src='http://localhost:{port}/ad.png'>"
                    f"<img id='ad2' src='http://ads.doubleclick.net:{port}/ad2.png'>"
                    f"<img id='ok' src='http://127.0.0.1:{port}/ok.png'>"
                    "</body></html>"
                ).encode()
                self._send(body, "text/html", "no-store")
            elif path == "/res.js":
                self._send(
                    b"window.__res = 1;",
                    "application/javascript",
                    "public, max-age=3600",
                )
            else:
                self._send(b"\x89PNG\r\n\x1a\n", "image/png", "no-store")

        def _send(self, body, content_type, cache_control):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", cache_control)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], hits
    finally:
        server.shutdown()
        server.server_close()


async def _load_three_times(port: int, profile: Path, patterns):
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        try:
            context = await pw.chromium.launch_persistent_context(
                str(profile),
                channel="chromium",
                headless=True,
                args=["--host-resolver-rules=MAP ads.doubleclick.net 127.0.0.1"],
            )
        except Exception as exc:  # no Chromium build installed
            pytest.skip(f"Chromium unavailable: {str(exc).splitlines()[0][:120]}")
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            failures = []
            page.on(
                "requestfailed",
                lambda request: failures.append((request.url, request.failure)),
            )
            cdp = await context.new_cdp_session(page)
            await cdp.send("Network.enable")
            await cdp.send("Network.setBlockedURLs", {"urls": patterns})
            for _ in range(3):
                await page.goto(
                    f"http://127.0.0.1:{port}/page", wait_until="domcontentloaded"
                )
                await page.wait_for_function(
                    "['ad1', 'ok'].every(id => document.getElementById(id).complete)",
                    timeout=10000,
                )
                await asyncio.sleep(0.2)
            return failures
        finally:
            await context.close()


def test_patterns_block_in_real_chromium_and_keep_the_http_cache(site, tmp_path):
    pytest.importorskip("playwright.async_api")
    port, hits = site
    patterns = adblock.blocked_url_patterns(
        True, frozenset(), extra_domains=("localhost",)
    )
    failures = asyncio.run(_load_three_times(port, tmp_path / "blocking", patterns))

    blocked_urls = {
        url
        for url, failure in failures
        if failure and ("inspector" in failure or "BLOCKED_BY_CLIENT" in failure)
    }
    # "localhost" (an extra domain) and a real AD_DOMAINS entry with a port.
    assert f"http://localhost:{port}/ad.png" in blocked_urls
    assert f"http://ads.doubleclick.net:{port}/ad2.png" in blocked_urls
    assert hits[("localhost", "/ad.png")] == 0
    assert hits[("ads.doubleclick.net", "/ad2.png")] == 0
    # Everything else loads, and the cacheable script came from the HTTP cache
    # on the second and third visit.
    assert hits[("127.0.0.1", "/page")] == 3
    assert hits[("127.0.0.1", "/ok.png")] >= 1
    assert hits[("127.0.0.1", "/res.js")] == 1


def test_without_ad_patterns_the_same_requests_go_through(site, tmp_path):
    pytest.importorskip("playwright.async_api")
    port, hits = site
    patterns = adblock.blocked_url_patterns(False, frozenset())
    failures = asyncio.run(_load_three_times(port, tmp_path / "control", patterns))
    assert hits[("localhost", "/ad.png")] >= 1
    assert not any(failure and "inspector" in failure for _url, failure in failures)
