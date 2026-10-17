"""Site icons (favicons) for the tab strip.

After a page loads, :data:`ICON_LINKS_JS` reads the icons it declares
(``<link rel="icon">`` and friends); :func:`candidates` orders them (the one
nearest 32 px first, ``/favicon.ico`` of the page's origin last) and
:func:`fetch_icon` reads one (an icon inline in the page as a ``data:``
address needs no request) or loads it through the browser context's own
request client, so the site sees its own cookies, as with a real browser's icon
request. Every hop, redirects included, must be an http(s) address the
browser may open (never CraftBot's own UI). Only real image bytes are kept
(checked by their content, not the server's content type), at most
:data:`MAX_ICON_BYTES`, as a ``data:`` URL the UI shows as is: the UI never
fetches a remote address itself.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Callable, List, Optional
from urllib.parse import unquote_to_bytes, urljoin, urlsplit

from app.logger import logger

MAX_ICON_BYTES = 16 * 1024
FETCH_TIMEOUT_MS = 4000
MAX_REDIRECTS = 3
# Declared icons tried before /favicon.ico.
MAX_DECLARED = 2

# The icons a page declares: [href, sizes, type] in document order (an icon
# for another color scheme or media, per its media attribute, left out).
ICON_LINKS_JS = """() => Array.from(document.querySelectorAll('link[rel~="icon" i]'))
  .filter(link => link.href && (!link.media || matchMedia(link.media).matches))
  .slice(0, 12)
  .map(link => [link.href, link.getAttribute('sizes') || '', link.type || ''])"""

_SIZE_RE = re.compile(r"(\d+)x(\d+)", re.IGNORECASE)
_SVG_RE = re.compile(rb"<svg[\s>]", re.IGNORECASE)


def candidates(page_url: str, links: Any) -> List[str]:
    """Icon addresses to try for a page at ``page_url``, best first: the
    declared icons nearest 32 px (an SVG counts as any size), then the
    origin's ``/favicon.ico``. http(s) addresses, and icons inline in the
    page (``data:``)."""
    declared = []
    if isinstance(links, list):
        for index, item in enumerate(links):
            if not isinstance(item, list) or len(item) != 3:
                continue
            href, sizes, kind = (str(value) for value in item)
            if not (is_web(href) or _is_inline(href)):
                continue
            declared.append((_size_penalty(sizes, kind), index, href))
    ordered = [href for _penalty, _index, href in sorted(declared)][:MAX_DECLARED]
    if is_web(page_url):
        parts = urlsplit(page_url)
        fallback = f"{parts.scheme}://{parts.netloc}/favicon.ico"
        if fallback not in ordered:
            ordered.append(fallback)
    return ordered


async def fetch_icon(
    request: Any, url: str, allowed: Callable[[str], bool]
) -> Optional[str]:
    """The icon at ``url`` as a ``data:`` URL, or None (not allowed, not an
    image, too large, or it failed). ``request`` is the browser context's
    APIRequestContext; ``allowed`` vets every address, redirects included.
    Never raises."""
    if _is_inline(url):
        body = _inline_bytes(url)
        return data_url(body) if body is not None else None
    current = url
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            if not is_web(current) or not allowed(current):
                return None
            response = await request.get(
                current,
                timeout=FETCH_TIMEOUT_MS,
                max_redirects=0,
                fail_on_status_code=False,
            )
            try:
                location = response.headers.get("location")
                if 300 <= response.status < 400 and location:
                    current = urljoin(current, location)
                    continue
                if response.status != 200:
                    return None
                length = response.headers.get("content-length", "")
                if length.isdigit() and int(length) > MAX_ICON_BYTES:
                    return None
                body = await response.body()
            finally:
                await response.dispose()
            return data_url(body)
    except Exception as exc:
        logger.debug(f"[MiniBrowser] Site icon not loaded: {type(exc).__name__}")
    return None


def data_url(body: bytes) -> Optional[str]:
    """``body`` as an image ``data:`` URL, or None when it is no image (an
    error page, say) or larger than MAX_ICON_BYTES."""
    if not body or len(body) > MAX_ICON_BYTES:
        return None
    mime = sniff(body)
    if mime is None:
        return None
    return f"data:{mime};base64,{base64.b64encode(body).decode('ascii')}"


def sniff(body: bytes) -> Optional[str]:
    """The image type of ``body`` by its content, or None."""
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    head = body[:1024].lstrip()
    if head.startswith((b"<svg", b"<?xml", b"<!--")) and _SVG_RE.search(head):
        return "image/svg+xml"
    return None


def _is_inline(url: str) -> bool:
    return url[:11].lower() == "data:image/"


def _inline_bytes(url: str) -> Optional[bytes]:
    """The bytes of a ``data:`` address, or None when malformed or too large."""
    header, separator, payload = url.partition(",")
    if not separator or len(payload) > MAX_ICON_BYTES * 3:
        return None
    try:
        if header.lower().endswith(";base64"):
            return base64.b64decode(payload, validate=True)
        return unquote_to_bytes(payload)
    except (binascii.Error, ValueError):
        return None


def is_web(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _size_penalty(sizes: str, kind: str) -> int:
    """How far an icon is from 32 px (smaller is better)."""
    if "svg" in kind.lower() or sizes.strip().lower() == "any":
        return 0
    best = None
    for match in _SIZE_RE.finditer(sizes):
        distance = abs(int(match.group(1)) - 32)
        best = distance if best is None else min(best, distance)
    return 16 if best is None else best
