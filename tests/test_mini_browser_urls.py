"""Mini Browser URL policy (app/mini_browser/urls.py): pure tests, no browser."""

from __future__ import annotations

import dataclasses

import pytest

from app.mini_browser import urls
from app.mini_browser.errors import MiniBrowserError

UI = frozenset({"localhost:7926", "127.0.0.1:7926", "[::1]:7926", "localhost:7925"})
SEARCH = "https://duckduckgo.com/?q={query}"


def resolve(
    text, *, history=True, search=True, allow_file=False, origins=UI, search_url=SEARCH
):
    return urls.resolve(
        text,
        allow_history=history,
        allow_search=search,
        search_url=search_url,
        allow_file=allow_file,
        ui_origins=origins,
    )


def error_of(text, **kwargs) -> MiniBrowserError:
    with pytest.raises(MiniBrowserError) as info:
        resolve(text, **kwargs)
    return info.value


# ── basics ───────────────────────────────────────────────────────────────────


def test_target_is_frozen():
    target = urls.Target(kind="url", url="https://a.example")
    with pytest.raises(dataclasses.FrozenInstanceError):
        target.url = "x"  # type: ignore[misc]
    assert urls.Target("back") == urls.Target(kind="back", url="")


@pytest.mark.parametrize("text", ["", "   ", "\t\n", None])
def test_empty_input_is_invalid(text):
    assert error_of(text).code == "MINI_BROWSER_INVALID_INPUT"


def test_too_long_and_control_characters_are_invalid():
    assert (
        error_of("a" * (urls.MAX_INPUT_CHARS + 1)).code == "MINI_BROWSER_INVALID_INPUT"
    )
    # URL parsers drop tab/newline inside a scheme: "java\tscript:" must not
    # sneak past the scheme check.
    assert error_of("java\tscript:alert(1)").code == "MINI_BROWSER_INVALID_INPUT"
    assert error_of("https://a.example/\x00").code == "MINI_BROWSER_INVALID_INPUT"


def test_input_is_stripped():
    assert resolve("   https://a.example/x  ").url == "https://a.example/x"


# ── history keywords ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("word", ["back", "forward", "reload", "Back", " RELOAD "])
def test_history_keywords_when_allowed(word):
    assert resolve(word) == urls.Target(kind=word.strip().lower())


def test_history_keywords_are_searched_when_not_allowed():
    target = resolve("back", history=False)
    assert target.kind == "url"
    assert target.url == "https://duckduckgo.com/?q=back"


def test_history_keyword_is_invalid_without_history_or_search():
    assert (
        error_of("reload", history=False, search=False).code
        == "MINI_BROWSER_INVALID_INPUT"
    )


# ── explicit schemes ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("https://example.com/a?b=1#c", "https://example.com/a?b=1#c"),
        ("http://example.com", "http://example.com"),
        ("HTTPS://Example.com/Path", "https://Example.com/Path"),
        ("https:example.com", "https://example.com"),
        ("https:///example.com/x", "https://example.com/x"),
        ("https://user:pw@example.com/", "https://user:pw@example.com/"),
        ("http://localhost:3000/app", "http://localhost:3000/app"),
    ],
)
def test_http_urls_are_kept(text, expected):
    assert resolve(text) == urls.Target(kind="url", url=expected)


def test_http_url_without_host_is_invalid():
    assert error_of("https://").code == "MINI_BROWSER_INVALID_INPUT"
    assert error_of("http://[::1").code == "MINI_BROWSER_INVALID_INPUT"
    assert error_of("http://example.com:99999/").code == "MINI_BROWSER_INVALID_INPUT"


def test_about_blank_only():
    assert resolve("about:blank").url == "about:blank"
    assert resolve("ABOUT:BLANK").url == "about:blank"
    err = error_of("about:config")
    assert err.code == "MINI_BROWSER_BLOCKED_URL"


def test_file_urls_need_permission():
    err = error_of("file:///C:/Windows/win.ini")
    assert err.code == "MINI_BROWSER_BLOCKED_URL"
    assert "file" in err.fields["reason"]
    assert (
        resolve("file:///C:/notes.txt", allow_file=True).url == "file:///C:/notes.txt"
    )
    assert resolve("file:///tmp/a.html", allow_file=True).url == "file:///tmp/a.html"


@pytest.mark.parametrize(
    "text",
    [
        "javascript:alert(1)",
        "JavaScript:void(0)",
        "data:text/html,<b>hi</b>",
        "blob:https://example.com/123",
        "chrome://settings",
        "chrome-extension://abc/page.html",
        "chrome-untrusted://x",
        "devtools://devtools/bundled/inspector.html",
        "view-source:https://example.com",
        "edge://settings",
        "ws://example.com/socket",
        "wss://example.com/socket",
        "mailto:someone@example.com",
        "tel:+123456",
        "intent://scan/#Intent;end",
        "steam://run/10",
        "filesystem:https://example.com/temporary/x",
    ],
)
def test_dangerous_schemes_are_blocked(text):
    err = error_of(text)
    assert err.code == "MINI_BROWSER_BLOCKED_URL"
    assert err.fields["reason"]


def test_unknown_word_colon_text_is_searched():
    target = resolve("note: buy milk")
    assert target.url == "https://duckduckgo.com/?q=note%3A+buy+milk"
    assert resolve("foo:bar").url == "https://duckduckgo.com/?q=foo%3Abar"


# ── no scheme ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("localhost", "http://localhost"),
        ("localhost:3000", "http://localhost:3000"),
        ("localhost:3000/path?q=1", "http://localhost:3000/path?q=1"),
        ("127.0.0.1", "http://127.0.0.1"),
        ("127.0.0.5:8080/x", "http://127.0.0.5:8080/x"),
        ("[::1]:8080", "http://[::1]:8080"),
        ("::1", "http://[::1]"),
        ("10.0.0.7", "http://10.0.0.7"),
        ("172.16.4.2", "http://172.16.4.2"),
        ("192.168.1.10/admin", "http://192.168.1.10/admin"),
        ("printer.local", "http://printer.local"),
        ("app.localhost:5173", "http://app.localhost:5173"),
        ("example.com:8080", "http://example.com:8080"),
        ("example.com:443/a", "https://example.com:443/a"),
    ],
)
def test_local_hosts_and_explicit_ports_use_http(text, expected):
    assert resolve(text) == urls.Target(kind="url", url=expected)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("example.com", "https://example.com"),
        ("www.example.co.uk/path?x=1#top", "https://www.example.co.uk/path?x=1#top"),
        ("sub.domain.example.org", "https://sub.domain.example.org"),
        ("example.com.", "https://example.com."),
        ("8.8.8.8", "https://8.8.8.8"),
        ("日本.jp", "https://日本.jp"),
        ("xn--wgv71a.jp", "https://xn--wgv71a.jp"),
        ("my-site.dev", "https://my-site.dev"),
    ],
)
def test_domains_and_public_ips_use_https(text, expected):
    assert resolve(text) == urls.Target(kind="url", url=expected)


@pytest.mark.parametrize(
    "text,query",
    [
        ("wireless headphones", "wireless+headphones"),
        ("weather", "weather"),
        ("node.js", "node.js"),
        ("report.pdf", "report.pdf"),
        ("1.5", "1.5"),
        ("a&b=c?", "a%26b%3Dc%3F"),
        ("someone@example.com", "someone%40example.com"),
        ("C:\\Users\\me", "C%3A%5CUsers%5Cme"),
        ("東京 天気", "%E6%9D%B1%E4%BA%AC+%E5%A4%A9%E6%B0%97"),
        ("example.com/a b", "example.com%2Fa+b"),
    ],
)
def test_everything_else_is_a_search(text, query):
    assert resolve(text) == urls.Target(
        kind="url", url=f"https://duckduckgo.com/?q={query}"
    )


def test_custom_search_template():
    target = resolve("cats", search_url="https://www.google.com/search?q={query}&hl=en")
    assert target.url == "https://www.google.com/search?q=cats&hl=en"


def test_unusable_search_template_falls_back_to_default():
    assert (
        resolve("cats", search_url="ftp://x/{query}").url
        == "https://duckduckgo.com/?q=cats"
    )
    assert (
        resolve("cats", search_url="https://x/?q=").url
        == "https://duckduckgo.com/?q=cats"
    )


def test_non_address_is_invalid_without_search():
    err = error_of("wireless headphones", search=False)
    assert err.code == "MINI_BROWSER_INVALID_INPUT"
    assert "wireless headphones" in err.fields["detail"]
    assert resolve("example.com", search=False).url == "https://example.com"


# ── CraftBot UI origins ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "http://localhost:7926/",
        "http://localhost:7926/api/session-token",
        "https://localhost:7926/",
        "localhost:7926",
        "localhost:7926/settings",
        "127.0.0.1:7926",
        "http://127.0.0.1:7926",
        "[::1]:7926",
        "http://[::1]:7926/x",
        "http://localhost:7925",
        "HTTP://LOCALHOST:7926/",
        "http://localhost.:7926/",
        "http://%6c%6fcalhost:7926/",
        "http://ＬＯＣＡＬＨＯＳＴ:7926/",
        "http://127.1:7926/",
        "http://0x7f.0.0.1:7926/",
        "http://0177.0.0.1:7926/",
        "http://2130706433:7926/",
        "http://１２７．０．０．１:7926/",
        "http://[0:0:0:0:0:0:0:1]:7926/",
        "http://localhost:07926/",
        "http://user:pw@localhost:7926/",
        "http:\\\\localhost:7926\\",
        "http://localhost:7926\\@evil.example/",
    ],
)
def test_ui_origins_are_blocked_however_spelled(text):
    err = error_of(text)
    assert err.code == "MINI_BROWSER_BLOCKED_URL"
    assert err.fields["reason"] == urls.UI_ORIGIN_REASON


def test_backslash_userinfo_trick_opens_the_real_host():
    # "\" is a path separator for http(s): Chromium sees host evil.example.
    target = resolve("http://evil.example\\@localhost:7926/")
    assert target.url == "http://evil.example/@localhost:7926/"


def test_other_ports_and_unlisted_aliases_are_not_ui():
    assert resolve("http://localhost:7927/").url == "http://localhost:7927/"
    only_localhost = frozenset({"localhost:7926"})
    assert (
        resolve("http://127.0.0.1:7926/", origins=only_localhost).url
        == "http://127.0.0.1:7926/"
    )
    assert error_of("http://localhost:7926/x", origins=only_localhost).code == (
        "MINI_BROWSER_BLOCKED_URL"
    )


def test_default_ports_match_origins():
    origins = frozenset({"localhost:80", "secure.example:443"})
    assert (
        error_of("http://localhost/x", origins=origins).code
        == "MINI_BROWSER_BLOCKED_URL"
    )
    assert error_of("localhost", origins=origins).code == "MINI_BROWSER_BLOCKED_URL"
    assert (
        error_of("secure.example", origins=origins).code == "MINI_BROWSER_BLOCKED_URL"
    )
    assert (
        resolve("http://secure.example/", origins=origins).url
        == "http://secure.example/"
    )


def test_bare_host_origin_matches_every_port():
    origins = frozenset({"craftbot.internal"})
    assert error_of("http://craftbot.internal:1234/", origins=origins).code == (
        "MINI_BROWSER_BLOCKED_URL"
    )


def test_search_pointing_at_ui_is_blocked():
    err = error_of("anything", search_url="http://localhost:7926/?q={query}")
    assert err.code == "MINI_BROWSER_BLOCKED_URL"


# ── blocked_reason (pages that actually load) ────────────────────────────────


def reason(url, allow_file=False, origins=UI):
    return urls.blocked_reason(url, allow_file=allow_file, ui_origins=origins)


def test_blocked_reason_for_loaded_pages():
    assert reason("https://example.com/") is None
    assert reason("http://localhost:3000/") is None
    assert reason("http://localhost:7926/") == urls.UI_ORIGIN_REASON
    assert reason("http://127.0.0.1:7926/x") == urls.UI_ORIGIN_REASON
    assert reason("blob:http://localhost:7926/uuid") == urls.UI_ORIGIN_REASON
    assert reason("blob:https://example.com/uuid") is None
    # Content a page may legitimately show.
    assert reason("about:blank") is None
    assert reason("about:srcdoc") is None
    assert reason("data:text/html,hi") is None
    assert reason("chrome-error://chromewebdata/") is None
    # Local files only when allowed; privileged pages never.
    assert reason("file:///C:/x.html") == urls.FILE_REASON
    assert reason("file:///C:/x.html", allow_file=True) is None
    assert reason("chrome://settings/") is not None
    assert reason("devtools://devtools/x") is not None
    assert reason("") is None
    assert reason("/relative/path") is None


# ── origins and hosts ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("localhost:7926", "localhost:7926"),
        ("LOCALHOST:7926", "localhost:7926"),
        ("http://localhost:7926", "localhost:7926"),
        ("http://localhost:7926/", "localhost:7926"),
        ("https://example.com", "example.com:443"),
        ("http://example.com", "example.com:80"),
        ("[::1]:7926", "[::1]:7926"),
        ("[0:0::1]:7926", "[::1]:7926"),
        ("127.1:7926", "127.0.0.1:7926"),
        ("craftbot.internal", "craftbot.internal"),
        ("", None),
        ("localhost:notaport", None),
        ("localhost:70000", None),
    ],
)
def test_normalize_origin(text, expected):
    assert urls.normalize_origin(text) == expected


@pytest.mark.parametrize(
    "host,expected",
    [
        ("Example.COM", "example.com"),
        ("example.com.", "example.com"),
        ("%65xample.com", "example.com"),
        ("ｅｘａｍｐｌｅ。ｃｏｍ", "example.com"),
        ("127.1", "127.0.0.1"),
        ("0x7f.1", "127.0.0.1"),
        ("2130706433", "127.0.0.1"),
        ("[::FFFF:7F00:1]", "[::ffff:7f00:1]"),
        ("1.2.3.4.5", "1.2.3.4.5"),
        ("example.123", "example.123"),
    ],
)
def test_canonical_host(host, expected):
    assert urls.canonical_host(host) == expected


def test_split_origin():
    assert urls.split_origin("localhost:7926") == ("localhost", 7926)
    assert urls.split_origin("[::1]:7926") == ("[::1]", 7926)
    assert urls.split_origin("craftbot.internal") == ("craftbot.internal", None)


def test_host_and_port_defaults():
    assert urls.host_and_port("https://Example.com/x") == ("example.com", 443)
    assert urls.host_and_port("http://example.com:8080") == ("example.com", 8080)
    assert urls.host_and_port("ws://a.example/") == ("a.example", 80)
    assert urls.host_and_port("about:blank") is None
    assert urls.host_and_port("http://[::1") is None
