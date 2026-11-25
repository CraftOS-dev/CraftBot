"""Block local network (Settings > Security > Network) in the Mini Browser.

A port of OpenClaw's browser navigation guard
(extensions/browser/src/browser/navigation-guard.ts and
pw-session-navigation-fence.ts, MIT). With the setting on, every document
the browser is about to load is checked before Chromium sends the request:
an address typed in the URL bar or opened by the agent, each redirect hop,
links, form posts, scripted navigations, pop-ups and frames. The rules are
the web tools' (app/security/net.py): the host must resolve only to public
internet addresses, and with allowed domains set it must be one of them.
A refused document never leaves Chromium; the tab shows an error page and
the agent is told why.

As in OpenClaw, a page's subresources (images, scripts, fetch/XHR) are not
checked, and Chromium resolves the host again itself, so a name that
changes its address between the two lookups (DNS rebinding) is not
covered (OpenClaw only closes that in its opt-in IP-literal mode).

With the setting off nothing is intercepted and nothing is looked up.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from typing import Optional, Tuple
from urllib.parse import urlsplit

from app.mini_browser.errors import MiniBrowserError

# Chromium pauses only top-level and frame documents for this pattern (CDP
# Fetch), the request kinds OpenClaw's fence checks.
DOCUMENT_PATTERN = {"urlPattern": "*", "resourceType": "Document", "requestStage": "Request"}

# A page's frames and the tab's own refreshes ask about the same host many
# times in a row; one lookup answers them for a few seconds.
_CACHE_S = 10.0
_CACHE_SIZE = 256
_cache: "OrderedDict[Tuple, Tuple[float, Optional[str]]]" = OrderedDict()
_cache_lock = threading.Lock()


def active() -> bool:
    """Whether the setting is on. One attribute read."""
    from app.security.policy import get_policy

    return get_policy().network_guard


def _key(url: str) -> Optional[Tuple]:
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https"):
            return None
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError:
        return (url,)  # invalid port: let net.py word the refusal
    from app.security.policy import get_policy

    return (scheme, parts.hostname or "", port, get_policy().allowed_domains)


def refusal(url: str) -> Optional[str]:
    """Why ``url`` must not load, or None. Blocking (a DNS lookup): call it
    off the event loop, or use :func:`check`."""
    if not active():
        return None
    key = _key(url)
    if key is None:
        return None  # not http(s): the browser's own scheme rules apply
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < _CACHE_S:
            return hit[1]
    from app.security.net import navigation_refusal

    reason = navigation_refusal(url)
    with _cache_lock:
        _cache[key] = (now, reason)
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return reason


async def check(url: str) -> Optional[str]:
    """:func:`refusal`, without blocking the event loop."""
    if not active() or _key(url) is None:
        return None
    return await asyncio.to_thread(refusal, url)


async def ensure_allowed(url: str) -> None:
    """Raise MINI_BROWSER_BLOCKED_URL when the setting refuses ``url``."""
    reason = await check(url)
    if reason:
        raise MiniBrowserError("MINI_BROWSER_BLOCKED_URL", reason=reason)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


_watched = None
_watch_lock = threading.Lock()


def watch_policy() -> None:
    """Re-apply the browsers' interception when the setting changes, so a
    running browser starts or stops checking at once."""
    global _watched
    from app.security.policy import get_store

    store = get_store()
    with _watch_lock:
        if _watched is store:
            return
        _watched = store
    last = [store.policy.network_guard, store.policy.allowed_domains]

    def changed(policy) -> None:
        now = [policy.network_guard, policy.allowed_domains]
        if now == last:
            return
        last[:] = now
        clear_cache()
        from app.mini_browser.bridge import _refresh_running_browsers

        _refresh_running_browsers()

    store.subscribe(changed)
