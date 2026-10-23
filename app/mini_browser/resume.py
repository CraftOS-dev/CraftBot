"""Where a chat's browser left off: the pages it had open and the last picture
of the page on screen, kept in the session's profile folder.

The browser reopens those pages when it starts again (``BrowserCore``), and
the chat's browser panel shows the picture, dimmed, while the browser is
starting or off (``ws.py``), so the panel is never blank. Both files are
replaced atomically: a reader sees the old file or the new one, never half
of one. Anything missing, unreadable or malformed counts as nothing saved.
The files go with the profile when the session is deleted.

Blocking file I/O: call these from a worker thread (``asyncio.to_thread``).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.logger import logger

PAGES_FILE = "craftbot_pages.json"
LAST_FRAME_FILE = "craftbot_last_frame.json"

# Pages reopened at most (the one on screen is always among them).
MAX_PAGES = 10
MAX_URL_CHARS = 2048
MAX_TITLE_CHARS = 300
# A last frame larger than this (base64 JPEG) is not kept.
MAX_IMAGE_CHARS = 4_000_000
_MAX_FILE_BYTES = MAX_IMAGE_CHARS + 64_000


@dataclass(frozen=True)
class Page:
    url: str
    title: str


@dataclass(frozen=True)
class Pages:
    """The pages a browser had open, in tab order, and the one on screen."""

    pages: Tuple[Page, ...]
    viewed: int = 0  # index into ``pages`` (0 when there are none)

    @property
    def viewed_page(self) -> Optional[Page]:
        return self.pages[self.viewed] if self.pages else None


@dataclass(frozen=True)
class LastFrame:
    """The last picture of the page on screen (a base64 JPEG) and its page."""

    url: str
    title: str
    width: int
    height: int
    image: str


def save_pages(profile: Path, pages: Pages) -> None:
    """Remember ``pages`` for ``profile``'s browser. Raises OSError."""
    _write_json(
        Path(profile) / PAGES_FILE,
        {
            "pages": [{"url": page.url, "title": page.title} for page in pages.pages],
            "viewed": pages.viewed,
        },
    )


def load_pages(profile: Path) -> Optional[Pages]:
    """The pages ``profile``'s browser had open, or None when none are saved."""
    data = _read_json(Path(profile) / PAGES_FILE)
    if data is None:
        return None
    raw_pages = data.get("pages")
    viewed = data.get("viewed")
    if not isinstance(raw_pages, list) or not isinstance(viewed, int):
        return None
    pages = []
    for item in raw_pages[:MAX_PAGES]:
        if not isinstance(item, dict):
            return None
        url, title = item.get("url"), item.get("title")
        if not _text(url, MAX_URL_CHARS) or not isinstance(title, str):
            return None
        pages.append(Page(url=url, title=title[:MAX_TITLE_CHARS]))
    if pages and not 0 <= viewed < len(pages):
        viewed = 0
    return Pages(pages=tuple(pages), viewed=viewed if pages else 0)


def save_last_frame(profile: Path, frame: LastFrame) -> None:
    """Remember ``frame`` for ``profile``'s browser. Raises OSError."""
    _write_json(
        Path(profile) / LAST_FRAME_FILE,
        {
            "url": frame.url,
            "title": frame.title,
            "width": frame.width,
            "height": frame.height,
            "image": frame.image,
        },
    )


def load_last_frame(profile: Path) -> Optional[LastFrame]:
    """The last picture saved for ``profile``'s browser, or None."""
    data = _read_json(Path(profile) / LAST_FRAME_FILE)
    if data is None:
        return None
    url, title, image = data.get("url"), data.get("title"), data.get("image")
    width, height = data.get("width"), data.get("height")
    if (
        not _text(url, MAX_URL_CHARS)
        or not isinstance(title, str)
        or not _text(image, MAX_IMAGE_CHARS)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        return None
    return LastFrame(
        url=url,
        title=title[:MAX_TITLE_CHARS],
        width=width,
        height=height,
        image=image,
    )


def resume_frame(profile: Path) -> Optional[LastFrame]:
    """The picture to show while ``profile``'s browser starts or is off: the
    last frame, only while it shows the page the browser reopens on screen
    (an agent may have browsed on since, with nobody watching)."""
    pages = load_pages(profile)
    viewed = pages.viewed_page if pages is not None else None
    if viewed is None:
        return None
    frame = load_last_frame(profile)
    if frame is None or frame.url != viewed.url:
        return None
    return frame


def ui_payload(key: str, frame: Optional[LastFrame]) -> Dict[str, Any]:
    """The ``mini_browser_last_frame`` message of session ``key``'s panel
    (``image`` None: there is no picture to show)."""
    if frame is None:
        return {"sessionId": key, "image": None}
    return {
        "sessionId": key,
        "image": "data:image/jpeg;base64," + frame.image,
        "width": frame.width,
        "height": frame.height,
        "url": frame.url,
        "title": frame.title,
    }


def _text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= limit


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.debug(f"[MiniBrowser] {path.name} unreadable: {type(exc).__name__}")
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    """Replace ``path`` atomically (a temporary file next to it, then a rename)."""
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
