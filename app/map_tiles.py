"""Map tiles for Generative UI outputs, fetched by CraftBot itself.

An output's sandboxed page has an opaque origin, so its own tile requests
carry no Referer and cannot say which app they come from; public tile
servers may refuse them (OpenStreetMap's usage policy requires both). The
output panel points Leaflet here instead: CraftBot fetches each tile from the
configured server (``generative_ui.map_tiles_url``) under its own User-Agent
and keeps it on disk for as long as the server's caching headers allow.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

import aiohttp

from app.config import APP_DATA_PATH, get_app_version, get_generative_ui_settings

#: How long a tile stays cached when the server sends no caching headers.
DEFAULT_TILE_SECONDS = 7 * 24 * 3600
#: Tiles fetched from the server at once.
MAX_UPSTREAM_REQUESTS = 4

_cache_root = Path(APP_DATA_PATH) / ".usage" / "map_tiles"
_session: Optional[aiohttp.ClientSession] = None
_upstream = asyncio.Semaphore(MAX_UPSTREAM_REQUESTS)
_in_flight: Dict[Tuple[str, int, int, int], "asyncio.Future[Tuple[bytes, str]]"] = {}


class TileUnavailable(Exception):
    """The tile server did not return an image."""


def valid_tile(z: int, x: int, y: int, max_zoom: int) -> bool:
    return 0 <= z <= max_zoom and 0 <= x < 2**z and 0 <= y < 2**z


def _lifetime(headers: Mapping[str, str]) -> int:
    """Seconds the server lets a tile be reused (Cache-Control, then Expires)."""
    control = headers.get("Cache-Control", "")
    if re.search(r"\b(?:no-store|no-cache)\b", control):
        return 0
    match = re.search(r"\bmax-age=(\d+)", control)
    if match:
        return int(match[1])
    expires = headers.get("Expires")
    if expires:
        try:
            return max(0, int(parsedate_to_datetime(expires).timestamp() - time.time()))
        except (TypeError, ValueError):
            return 0
    return DEFAULT_TILE_SECONDS


def _cached(folder: Path, name: str) -> Optional[Tuple[bytes, str]]:
    meta_file = folder / f"{name}.json"
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if meta["expires"] <= time.time():
            return None
        return (folder / f"{name}.tile").read_bytes(), meta["type"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _store(
    folder: Path, name: str, data: bytes, content_type: str, seconds: int
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.tile").write_bytes(data)
    (folder / f"{name}.json").write_text(
        json.dumps({"expires": time.time() + seconds, "type": content_type}),
        encoding="utf-8",
    )


async def _download(url: str) -> Tuple[bytes, str, int]:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            headers={"User-Agent": f"CraftBot/{get_app_version()}"},
            timeout=aiohttp.ClientTimeout(total=20),
        )
    async with _upstream:
        try:
            async with _session.get(url) as response:
                content_type = response.headers.get("Content-Type", "").split(";")[0]
                if response.status != 200 or not content_type.startswith("image/"):
                    raise TileUnavailable(f"{response.status} {content_type}")
                return await response.read(), content_type, _lifetime(response.headers)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise TileUnavailable(str(exc)) from exc


async def _fetch(template: str, z: int, x: int, y: int) -> Tuple[bytes, str]:
    folder = (
        _cache_root
        / hashlib.sha256(template.encode("utf-8")).hexdigest()[:16]
        / str(z)
        / str(x)
    )
    cached = await asyncio.to_thread(_cached, folder, str(y))
    if cached:
        return cached
    url = template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
    data, content_type, seconds = await _download(url)
    if seconds:
        await asyncio.to_thread(_store, folder, str(y), data, content_type, seconds)
    return data, content_type


async def get_tile(z: int, x: int, y: int) -> Tuple[bytes, str]:
    """One tile from the configured server: (bytes, content type).

    Requests for a tile already on its way share that one download.
    Raises TileUnavailable when the server gives no image.
    """
    template = get_generative_ui_settings()["map_tiles_url"]
    key = (template, z, x, y)
    if key not in _in_flight:
        _in_flight[key] = asyncio.ensure_future(_fetch(template, z, x, y))
        _in_flight[key].add_done_callback(lambda _: _in_flight.pop(key, None))
    return await asyncio.shield(_in_flight[key])
