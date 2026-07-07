"""Direct-GitHub catalogue access (fallback path).

The original marketplace source: catalogue.json in the public
living-ui-marketplace repo. Used when the marketplace server is
unconfigured or unreachable, and by the legacy WS handler so old
frontends keep working.
"""

import asyncio
import json
import logging
import re
import ssl
import urllib.request
from typing import Any, Dict, List, Optional

import certifi

logger = logging.getLogger(__name__)

MARKETPLACE_REPO = "CraftOS-dev/living-ui-marketplace"
RAW_BASE = f"https://raw.githubusercontent.com/{MARKETPLACE_REPO}/main"
CATALOGUE_URL = f"{RAW_BASE}/catalogue.json"


def fetch_catalogue_sync(timeout: int = 15) -> Dict[str, Any]:
    """Fetch and parse catalogue.json from GitHub (blocking).

    Tolerates trailing commas (the catalogue is hand-edited JSON).
    Raises on network/parse failure — callers decide how to degrade.
    """
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    req = urllib.request.Request(CATALOGUE_URL, headers={"User-Agent": "CraftBot"})
    response = urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx)
    raw = response.read().decode()
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    return json.loads(raw)


async def fetch_catalogue(timeout: int = 15) -> Dict[str, Any]:
    """Async wrapper: run the blocking fetch off the event loop."""
    return await asyncio.to_thread(fetch_catalogue_sync, timeout)


def catalogue_app_to_product(app: Dict[str, Any]) -> Dict[str, Any]:
    """Map a catalogue.json entry to the marketplace product card shape.

    Mirrors the server's CardDTO so the frontend renders one shape in
    both normal and degraded mode. Stats are zeroed — the GitHub path
    has no metrics.
    """
    folder = app.get("folder") or app.get("id", "")
    return {
        "slug": app.get("id") or folder,
        "type": "living_ui",
        "name": app.get("name", ""),
        "tagline": app.get("description", ""),
        "descriptionMd": app.get("description", ""),
        "previewUrl": app.get("preview")
        or (f"{RAW_BASE}/{folder}/thumbnail.png" if folder else None),
        "screenshots": [],
        "tags": app.get("tags") or [],
        "approved": False,
        "featured": False,
        "repoPath": folder,
        "customFields": app.get("customizable") or [],
        "latestVersion": app.get("version"),
        "creator": None,
        "versions": [],
        "stats": {
            "views": 0,
            "clicks": 0,
            "downloads": 0,
            "ratingAvg": 0,
            "ratingCount": 0,
        },
    }


def filter_products(
    products: List[Dict[str, Any]],
    *,
    q: str = "",
    tag: str = "",
    product_type: str = "",
) -> List[Dict[str, Any]]:
    """Apply catalog query params client-side (fallback has no DB)."""
    result = products
    if product_type:
        result = [p for p in result if p["type"] == product_type]
    if tag:
        result = [p for p in result if tag in (p.get("tags") or [])]
    if q:
        needle = q.strip().lower()
        result = [
            p
            for p in result
            if needle
            in f"{p.get('name', '')} {p.get('tagline', '')} {' '.join(p.get('tags') or [])}".lower()
        ]
    return result


async def get_catalog_fallback(
    *, q: str = "", tag: str = "", product_type: str = ""
) -> Dict[str, Any]:
    """Catalog response built straight from GitHub, marked degraded."""
    catalogue = await fetch_catalogue()
    products = [catalogue_app_to_product(a) for a in catalogue.get("apps", [])]
    products = filter_products(products, q=q, tag=tag, product_type=product_type)
    return {
        "products": products,
        "total": len(products),
        "page": 1,
        "pageSize": len(products),
        "degraded": True,
    }


async def get_product_fallback(slug: str) -> Optional[Dict[str, Any]]:
    """Product detail from GitHub, or None if the slug isn't in the catalogue."""
    catalogue = await fetch_catalogue()
    for app in catalogue.get("apps", []):
        product = catalogue_app_to_product(app)
        if product["slug"] == slug:
            product["degraded"] = True
            return product
    return None
