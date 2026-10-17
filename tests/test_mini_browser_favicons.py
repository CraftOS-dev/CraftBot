"""favicons.py: site icons for the tab strip. Which icon a page offers, how it
is loaded (every address vetted, redirects included) and that only real
image bytes become the data: URL the UI shows. The browser sending icons in
its tab state is in test_mini_browser_fleet.py.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Dict, List, Optional

from app.mini_browser import bridge, favicons
from app.mini_browser.config import MiniBrowserSettings
from app.mini_browser.core import BrowserCore

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
ICO = b"\x00\x00\x01\x00" + b"\x01" * 24
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>'


class FakeResponse:
    def __init__(
        self, status: int, body: bytes = b"", headers: Optional[Dict[str, str]] = None
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body
        self.disposed = False

    async def body(self) -> bytes:
        return self._body

    async def dispose(self) -> None:
        self.disposed = True


class FakeRequest:
    """The browser context's APIRequestContext: serves canned responses."""

    def __init__(self, responses: Dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.asked: List[str] = []

    async def get(self, url: str, **options) -> FakeResponse:
        assert options["max_redirects"] == 0  # every hop is vetted here
        self.asked.append(url)
        return self.responses.get(url, FakeResponse(404))


def fetch(request: FakeRequest, url: str, allowed=lambda url: True):
    return asyncio.run(favicons.fetch_icon(request, url, allowed))


def test_candidates_put_the_icon_nearest_32px_first_and_favicon_ico_last():
    links = [
        ["https://a.example/big.png", "192x192", "image/png"],
        ["https://a.example/small.png", "16x16", "image/png"],
        ["https://a.example/exact.png", "32x32", "image/png"],
        ["javascript:alert(1)", "", ""],
        "not a link",
    ]
    assert favicons.candidates("https://a.example/page?q=1", links) == [
        "https://a.example/exact.png",
        "https://a.example/small.png",
        "https://a.example/favicon.ico",
    ]
    # An SVG fits every size; nothing declared: only /favicon.ico.
    svg = [
        ["https://a.example/i.png", "", ""],
        ["https://a.example/i.svg", "", "image/svg+xml"],
    ]
    assert (
        favicons.candidates("https://a.example/", svg)[0] == "https://a.example/i.svg"
    )
    assert favicons.candidates("https://a.example/x", None) == [
        "https://a.example/favicon.ico"
    ]
    assert favicons.candidates("about:blank", None) == []


def test_only_real_image_bytes_within_the_limit_become_a_data_url():
    assert favicons.data_url(PNG).startswith("data:image/png;base64,")
    assert favicons.data_url(ICO).startswith("data:image/x-icon;base64,")
    assert favicons.data_url(SVG).startswith("data:image/svg+xml;base64,")
    assert favicons.data_url(b"<!doctype html><title>Not found</title>") is None
    assert favicons.data_url(b"") is None
    assert favicons.data_url(PNG + b"\x00" * favicons.MAX_ICON_BYTES) is None


def test_an_icon_loads_through_vetted_redirects_only():
    request = FakeRequest(
        {
            "https://a.example/favicon.ico": FakeResponse(
                301, headers={"location": "/static/icon.ico"}
            ),
            "https://a.example/static/icon.ico": FakeResponse(200, ICO),
        }
    )
    icon = fetch(request, "https://a.example/favicon.ico")
    assert icon == "data:image/x-icon;base64," + base64.b64encode(ICO).decode()
    assert request.asked == [
        "https://a.example/favicon.ico",
        "https://a.example/static/icon.ico",
    ]

    # A redirect to an address the browser may not open is never followed.
    request = FakeRequest(
        {
            "https://a.example/favicon.ico": FakeResponse(
                302, headers={"location": "http://localhost:7926/api/secret"}
            )
        }
    )
    assert (
        fetch(request, "https://a.example/favicon.ico", lambda url: "7926" not in url)
        is None
    )
    assert request.asked == ["https://a.example/favicon.ico"]


def test_failed_oversized_or_non_image_answers_give_no_icon():
    big = FakeResponse(200, PNG, {"content-length": str(favicons.MAX_ICON_BYTES + 1)})
    request = FakeRequest(
        {
            "https://a.example/missing.ico": FakeResponse(404, PNG),
            "https://a.example/big.png": big,
            "https://a.example/page.ico": FakeResponse(200, b"<html>soft 404</html>"),
        }
    )
    for url in request.responses:
        assert fetch(request, url) is None, url
    assert big.disposed
    assert fetch(request, "ftp://a.example/icon.ico") is None
    loops = {
        f"https://a.example/{i}": FakeResponse(
            302, headers={"location": f"https://a.example/{i + 1}"}
        )
        for i in range(10)
    }
    assert fetch(FakeRequest(loops), "https://a.example/0") is None


def test_an_icon_inline_in_the_page_needs_no_request():
    request = FakeRequest({})
    inline = "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert fetch(request, inline) == inline
    escaped = "data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%3E%3C%2Fsvg%3E"
    assert fetch(request, escaped).startswith("data:image/svg+xml;base64,")
    assert fetch(request, "data:image/png;base64,***") is None
    assert request.asked == []
    links = [[inline, "32x32", "image/png"]]
    assert favicons.candidates("https://a.example/", links)[0] == inline


def test_the_browser_never_loads_an_icon_from_craftbots_own_ui():
    core = BrowserCore(MiniBrowserSettings(), {}, key="chat-a")
    previous = bridge.ui_origins()
    bridge.set_ui_origins(["localhost:7926"])
    try:
        assert not core._icon_allowed("http://localhost:7926/favicon.ico")
        assert not core._icon_allowed("http://127.0.0.1:7926/favicon.ico")
        assert core._icon_allowed("http://localhost:3000/favicon.ico")
        assert core._icon_allowed("https://example.org/favicon.ico")
    finally:
        bridge.set_ui_origins(previous)
