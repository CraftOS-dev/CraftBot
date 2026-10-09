"""Mini Browser settings and where its files live.

Settings come from settings.json ``mini_browser`` through
``app.config.get_mini_browser_settings()`` and are validated again here into a
frozen :class:`MiniBrowserSettings`, so a hand-edited value can never stop the
browser from starting.

The path helpers never touch the disk. Create a directory with
:func:`ensure_dir` from a worker thread (``asyncio.to_thread``): this module
is used on the Mini Browser event loop, where blocking I/O is not allowed.
"""

from __future__ import annotations

import locale
import math
import os
import re
import sys
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from app.logger import logger

DEFAULT_SEARCH_URL = "https://duckduckgo.com/?q={query}"

# Playwright browser channels ("" = Playwright's default build).
CHANNELS = frozenset(
    {
        "",
        "chromium",
        "chrome",
        "chrome-beta",
        "chrome-dev",
        "chrome-canary",
        "msedge",
        "msedge-beta",
        "msedge-dev",
        "msedge-canary",
    }
)

# Inclusive range each numeric setting is clamped to.
_RANGES: Dict[str, Tuple[int, int]] = {
    "max_fps": (1, 30),
    "jpeg_quality": (30, 95),
    "max_agent_tabs": (1, 20),
    "idle_shutdown_minutes": (0, 24 * 60),
}
_LOCALE_RE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*")
_MAX_SEARCH_URL_CHARS = 2048
_TRUE_WORDS = frozenset({"true", "1", "yes", "on"})
_FALSE_WORDS = frozenset({"false", "0", "no", "off"})


@dataclass(frozen=True)
class MiniBrowserSettings:
    """Validated Mini Browser settings (see settings.json ``mini_browser``)."""

    headless: bool = True
    adblock: bool = True
    humanlike: bool = True
    show_cursor: bool = True
    max_fps: int = 12
    jpeg_quality: int = 70
    search_url: str = DEFAULT_SEARCH_URL
    allow_file_urls: bool = False
    max_agent_tabs: int = 6
    idle_shutdown_minutes: int = 30  # 0 = never
    locale: str = ""  # "" = the OS locale
    channel: str = "chromium"  # "" = Playwright's default headless shell

    @classmethod
    def from_mapping(cls, data: Optional[Mapping[str, Any]]) -> "MiniBrowserSettings":
        """Settings from a (possibly partial or invalid) mapping.

        Unknown keys are ignored, unusable values fall back to their default
        and numbers are clamped to their range. Never raises.
        """
        defaults = cls()
        if not isinstance(data, Mapping):
            return defaults
        values: Dict[str, Any] = {}
        for name, default in asdict(defaults).items():
            if name in data:
                values[name] = _clean(name, data[name], default)
        return cls(**{**asdict(defaults), **values})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clean(name: str, value: Any, default: Any) -> Any:
    """``value`` made valid for setting ``name``, or ``default``."""
    if isinstance(default, bool):
        return _as_bool(value, default)
    if name in _RANGES:
        low, high = _RANGES[name]
        return _as_int(value, default, low, high)
    if not isinstance(value, str):
        return default
    text = value.strip()
    if name == "search_url":
        return text if _usable_search_url(text) else default
    if name == "locale":
        text = text.replace("_", "-")
        if not text:
            return ""
        return text if len(text) <= 35 and _LOCALE_RE.fullmatch(text) else default
    if name == "channel":
        text = text.lower()
        return text if text in CHANNELS else default
    return default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
    return default


def _as_int(value: Any, default: int, low: int, high: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return default
    if not isinstance(value, (int, float)):
        return default
    if isinstance(value, float) and not math.isfinite(value):
        return default
    return max(low, min(high, int(round(value))))


def _usable_search_url(text: str) -> bool:
    if (
        not text
        or len(text) > _MAX_SEARCH_URL_CHARS
        or not text.isprintable()
        or not text.lower().startswith(("https://", "http://"))
    ):
        return False
    try:
        # Every brace must belong to the {query} slot, and the slot must exist.
        return "\x00" in text.format(query="\x00")
    except (IndexError, KeyError, ValueError):
        return False


def load_settings() -> MiniBrowserSettings:
    """Current settings from settings.json, validated. Never raises.

    May read settings.json (blocking): call it from a worker thread when on an
    event loop.
    """
    data: Any = None
    try:
        from app import config as app_config

        getter = getattr(app_config, "get_mini_browser_settings", None)
        if getter is not None:
            data = getter()
        else:  # older app.config without the Mini Browser section
            data = (app_config.get_settings() or {}).get("mini_browser")
    except Exception as exc:
        logger.warning(
            f"[MiniBrowser] Settings unavailable, using defaults: {type(exc).__name__}"
        )
    return MiniBrowserSettings.from_mapping(data if isinstance(data, Mapping) else None)


def save_setting(key: str, value: Any) -> None:
    """Persist one setting to settings.json (validated first).

    Raises ValueError for an unknown key. Blocking file I/O: from an event
    loop, call it through ``asyncio.to_thread``.
    """
    defaults = MiniBrowserSettings().to_dict()
    if key not in defaults:
        raise ValueError(f"Unknown Mini Browser setting: {key}")
    cleaned = _clean(key, value, defaults[key])
    from app import config as app_config

    setter = getattr(app_config, "set_mini_browser_setting", None)
    if setter is not None:
        setter(key, cleaned)
        return
    settings = dict(app_config.get_settings() or {})
    section = settings.get("mini_browser")
    section = dict(section) if isinstance(section, dict) else {}
    section[key] = cleaned
    settings["mini_browser"] = section
    app_config.save_settings(settings)


# ─────────────────────────────────────────────────────────────────────────────
# Locations
# ─────────────────────────────────────────────────────────────────────────────


def profile_dir() -> Path:
    """The persistent Chromium profile (cookies, logins, local storage)."""
    from app.config import APP_DATA_PATH

    return Path(APP_DATA_PATH) / "mini_browser_profile"


def workspace_dir(owner: Optional[str]) -> Path:
    """Where files the Mini Browser produces for ``owner`` go.

    The owner's session workspace when the session is known (a sub-agent uses
    its parent session's), else ``AGENT_WORKSPACE_ROOT/mini_browser``.
    """
    from app.config import AGENT_WORKSPACE_ROOT

    fallback = Path(AGENT_WORKSPACE_ROOT) / "mini_browser"
    session_id = owner
    if owner:
        record = subagent_record(owner)
        if record is not None:
            session_id = record[0]
    session = session_record(session_id)
    workspace = getattr(session, "workspace_dir", None) if session else None
    if isinstance(workspace, (str, os.PathLike)) and str(workspace):
        return Path(workspace)
    return fallback


def downloads_dir(owner: Optional[str]) -> Path:
    return workspace_dir(owner) / "downloads"


def screenshots_dir(owner: Optional[str]) -> Path:
    return workspace_dir(owner) / "screenshots"


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if missing. Blocking: use a worker thread."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Agent runtime lookups (read-only, every access guarded)
# ─────────────────────────────────────────────────────────────────────────────


def internal_action_interface() -> Any:
    """``InternalActionInterface`` if the agent runtime loaded it, else None.

    Looked up in ``sys.modules`` rather than imported: importing it pulls in
    the whole agent stack, and when nothing imported it there is no session
    or sub-agent manager to ask anyway.
    """
    module = sys.modules.get("app.internal_action_interface")
    return getattr(module, "InternalActionInterface", None) if module else None


def session_record(session_id: Optional[str]) -> Any:
    """The agent session ``session_id`` (title, type, workspace_dir), or None."""
    if not session_id:
        return None
    try:
        manager = getattr(internal_action_interface(), "session_manager", None)
        return manager.get(session_id) if manager is not None else None
    except Exception:
        return None


def subagent_record(
    owner: Optional[str],
) -> Optional[Tuple[Optional[str], str, Optional[datetime]]]:
    """``(parent_session_id, agent_type, created_at_utc)`` for a sub-agent id.

    None when ``owner`` is not a known sub-agent. Sub-agent ids start with
    ``sub_``; ``created_at`` is naive UTC (as SubAgent stores it).
    """
    if not owner or not owner.startswith("sub_"):
        return None
    try:
        manager = getattr(internal_action_interface(), "subagent_manager", None)
        sub = manager.get(owner) if manager is not None else None
    except Exception:
        return None
    if sub is None:
        return None
    parent = getattr(sub, "parent_task_id", None)
    agent_type = getattr(sub, "agent_type", None)
    created: Optional[datetime] = None
    raw = getattr(sub, "created_at", None)
    try:
        if isinstance(raw, datetime):
            created = raw
        elif isinstance(raw, str) and raw:
            created = datetime.fromisoformat(raw)
    except ValueError:
        created = None
    return (
        parent if isinstance(parent, str) and parent else None,
        agent_type if isinstance(agent_type, str) and agent_type else "sub-agent",
        created,
    )


def os_locale() -> str:
    """The OS locale as a BCP 47 tag (e.g. ``ja-JP``), ``en-US`` if unknown."""
    candidates = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            candidates.append(locale.getdefaultlocale()[0])
    except Exception:
        pass
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        candidates.append(os.environ.get(name))
    for raw in candidates:
        if not raw:
            continue
        tag = raw.split(".")[0].split("@")[0].replace("_", "-")
        if tag in ("C", "POSIX"):
            continue
        if len(tag) <= 35 and _LOCALE_RE.fullmatch(tag):
            return tag
    return "en-US"
