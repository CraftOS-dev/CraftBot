"""Client for the CraftOS Marketplace server.

The server base URL is the production URL baked in below by default; a
non-empty "marketplace_server_url" in settings.json overrides it (e.g.
pointing at http://127.0.0.1:3000 for local development). Every read has
a GitHub fallback so the marketplace keeps working when the server is
down or unconfigured — responses from the fallback carry degraded=True so
the UI can hide server-only affordances (hero banners, ratings, downloads).
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

import aiohttp
import certifi
import ssl

from app.config import get_settings, get_app_version
from app.marketplace import github_fallback
from app.marketplace.instance_id import get_instance_id

logger = logging.getLogger(__name__)

# Production marketplace server. Shipped installs use this without any
# per-install config. TODO: set to the deployed domain (e.g.
# "https://marketplace.craftos.dev"); empty = GitHub-fallback until deployed.
DEFAULT_MARKETPLACE_SERVER_URL = ""

REQUEST_TIMEOUT_SEC = 5
# Circuit breaker: after this many consecutive failures, skip the server
# entirely (straight to fallback) for the cooldown period.
BREAKER_FAILURE_THRESHOLD = 2
BREAKER_COOLDOWN_SEC = 60


class MarketplaceClient:
    def __init__(self) -> None:
        self._consecutive_failures = 0
        self._skip_server_until = 0.0
        self._ssl_ctx = ssl.create_default_context(cafile=certifi.where())

    @property
    def base_url(self) -> str:
        # settings.json override (dev/self-host) wins; else the baked default.
        url = get_settings().get("marketplace_server_url") or DEFAULT_MARKETPLACE_SERVER_URL
        return url.rstrip("/")

    def _server_available(self) -> bool:
        if not self.base_url:
            return False
        return time.monotonic() >= self._skip_server_until

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= BREAKER_FAILURE_THRESHOLD:
            self._skip_server_until = time.monotonic() + BREAKER_COOLDOWN_SEC
            logger.warning(
                "[MARKETPLACE] Server unreachable %d times — using GitHub fallback "
                "for the next %ds",
                self._consecutive_failures,
                BREAKER_COOLDOWN_SEC,
            )

    def _record_success(self) -> None:
        self._consecutive_failures = 0

    async def _get(self, path: str, params: Optional[Dict[str, str]] = None) -> Any:
        """GET {base_url}{path}; raises on any failure."""
        headers = {
            "X-CraftBot-Instance": get_instance_id(),
            "User-Agent": f"CraftBot/{get_app_version()}",
        }
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SEC)
        connector = aiohttp.TCPConnector(ssl=self._ssl_ctx)
        async with aiohttp.ClientSession(
            timeout=timeout, connector=connector
        ) as session:
            async with session.get(
                f"{self.base_url}{path}", params=params or {}, headers=headers
            ) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                return await resp.json()

    async def get_catalog(
        self,
        *,
        product_type: str = "",
        tag: str = "",
        q: str = "",
        featured: str = "",
        sort: str = "",
        page: str = "",
        page_size: str = "",
    ) -> Dict[str, Any]:
        """Catalog list/search. Falls back to GitHub on server failure."""
        if self._server_available():
            params = {
                k: v
                for k, v in {
                    "type": product_type,
                    "tag": tag,
                    "q": q,
                    "featured": featured,
                    "sort": sort,
                    "page": page,
                    "pageSize": page_size,
                }.items()
                if v
            }
            try:
                data = await self._get("/api/v1/catalog", params)
                self._record_success()
                if data is not None:
                    data.setdefault("degraded", False)
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                logger.warning(f"[MARKETPLACE] Catalog fetch failed: {e}")
                self._record_failure()
        return await github_fallback.get_catalog_fallback(
            q=q, tag=tag, product_type=product_type
        )

    async def get_product(self, slug: str) -> Optional[Dict[str, Any]]:
        """Product detail. Falls back to a catalogue.json lookup."""
        if self._server_available():
            try:
                data = await self._get(f"/api/v1/products/{slug}")
                self._record_success()
                if data is not None:
                    data.setdefault("degraded", False)
                    return data
                # 404 from a healthy server is authoritative — the GitHub
                # catalogue only knows living UIs that predate the server.
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                logger.warning(f"[MARKETPLACE] Product fetch failed: {e}")
                self._record_failure()
                return await github_fallback.get_product_fallback(slug)
            else:
                return data
        return await github_fallback.get_product_fallback(slug)

    async def proxy_json(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
    ) -> tuple:
        """Forward a request to the marketplace server verbatim, attaching the
        instance header. Returns (status, parsed_json). No GitHub fallback —
        used for interactive reads/writes (ratings, comments) that only exist
        on the server. Raises on network failure."""
        headers = {
            "X-CraftBot-Instance": get_instance_id(),
            "User-Agent": f"CraftBot/{get_app_version()}",
        }
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SEC)
        connector = aiohttp.TCPConnector(ssl=self._ssl_ctx)
        try:
            async with aiohttp.ClientSession(
                timeout=timeout, connector=connector
            ) as session:
                async with session.request(
                    method,
                    f"{self.base_url}{path}",
                    json=json_body,
                    params=params or {},
                    headers=headers,
                ) as resp:
                    data = await resp.json(content_type=None)
                    self._record_success()
                    return resp.status, data
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            self._record_failure()
            raise

    async def post_events(self, events: list) -> None:
        """Report engagement events (view/click/install). Best-effort:
        silently dropped when the server is unconfigured or unreachable."""
        if not self._server_available() or not events:
            return
        headers = {
            "X-CraftBot-Instance": get_instance_id(),
            "User-Agent": f"CraftBot/{get_app_version()}",
        }
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SEC)
        connector = aiohttp.TCPConnector(ssl=self._ssl_ctx)
        try:
            async with aiohttp.ClientSession(
                timeout=timeout, connector=connector
            ) as session:
                async with session.post(
                    f"{self.base_url}/api/v1/events",
                    json={"events": events[:50]},
                    headers=headers,
                ) as resp:
                    resp.raise_for_status()
            self._record_success()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.debug(f"[MARKETPLACE] Event report dropped: {e}")
            self._record_failure()

    async def get_banners(self) -> Dict[str, Any]:
        """Hero/shelf banners. No fallback content — degraded mode has no hero."""
        if self._server_available():
            try:
                data = await self._get("/api/v1/banners")
                self._record_success()
                if data is not None:
                    data.setdefault("degraded", False)
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                logger.warning(f"[MARKETPLACE] Banners fetch failed: {e}")
                self._record_failure()
        return {"banners": [], "degraded": True}
