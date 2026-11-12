"""Mini Browser settings and where its files live.

Settings come from settings.json ``mini_browser`` through
``app.config.get_mini_browser_settings()`` and are validated again here into a
frozen :class:`MiniBrowserSettings`, so a hand-edited value can never stop the
browser from starting. Both use the same rules (:func:`clean_setting`), so a
value means the same whichever way it is read.

The path helpers never touch the disk. Create a directory with
:func:`ensure_dir` from a worker thread (``asyncio.to_thread``): this module
is used on the Mini Browser event loop, where blocking I/O is not allowed.
"""

from __future__ import annotations

import hashlib
import locale
import math
import os
import re
import sys
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

from app.logger import logger
from app.mini_browser import DEFAULT_OWNER

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
    "max_running_browsers": (1, 12),
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
    sound: bool = True  # False = Chromium starts muted (applies at the next start)
    max_fps: int = 12
    jpeg_quality: int = 70
    search_url: str = DEFAULT_SEARCH_URL
    allow_file_urls: bool = False
    max_agent_tabs: int = 6
    # A session's browser closes this long after its panel was closed and its
    # agent's run ended (0 = never).
    idle_shutdown_minutes: int = 3
    # Session browsers running at once; opening one more closes the one idle
    # the longest (each is a Chromium of its own).
    max_running_browsers: int = 4
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


_DEFAULTS: Dict[str, Any] = MiniBrowserSettings().to_dict()


def clean_setting(name: str, value: Any) -> Tuple[bool, Any]:
    """``(True, cleaned)`` for a usable value of setting ``name``, else
    ``(False, None)``.

    The one set of rules for every way the settings are read or written
    (``app.config`` uses it too):

    - on/off settings: a boolean, 0 / 1, or the words true / false, yes / no,
      on / off, 1 / 0 (any case);
    - numbers: a finite number or a numeric string, rounded and clamped to
      its range (``_RANGES``);
    - ``search_url``: http(s) with exactly one ``{query}`` slot;
    - ``locale``: a language tag such as ``ja-JP`` (``_`` becomes ``-``), or
      "" for the OS locale;
    - ``channel``: one of ``CHANNELS`` (any case).

    Unknown settings and anything else are unusable.
    """
    if name not in _DEFAULTS:
        return False, None
    if isinstance(_DEFAULTS[name], bool):
        flag = _as_bool(value)
        return (flag is not None), flag
    if name in _RANGES:
        number = _as_int(value, *_RANGES[name])
        return (number is not None), number
    if not isinstance(value, str):
        return False, None
    text = value.strip()
    if name == "search_url":
        return (True, text) if _usable_search_url(text) else (False, None)
    if name == "locale":
        text = text.replace("_", "-")
        if text and (len(text) > 35 or not _LOCALE_RE.fullmatch(text)):
            return False, None
        return True, text
    if name == "channel":
        text = text.lower()
        return (True, text) if text in CHANNELS else (False, None)
    return False, None


def _clean(name: str, value: Any, default: Any) -> Any:
    """``value`` made valid for setting ``name``, or ``default``."""
    ok, cleaned = clean_setting(name, value)
    return cleaned if ok else default


def _as_bool(value: Any) -> Optional[bool]:
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
    return None


def _as_int(value: Any, low: int, high: int) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
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


# A session id used as it is for its profile folder name; anything else gets
# a stable hashed name (no path separators, no reserved names, bounded length).
_PLAIN_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_RESERVED_DIR_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
PROFILE_LOCK_SUFFIX = ".lock"


def profiles_root() -> Path:
    """The folder holding every session's Chromium profile.

    Kept out of the agent workspace: a profile holds the session's cookies
    and signed-in sites, which the agent's file tools must never read.
    """
    from app.config import APP_DATA_PATH

    return Path(APP_DATA_PATH) / "mini_browser_profiles"


def profile_dir_name(key: str) -> str:
    """The profile folder name of browser ``key`` (a session id). Pure."""
    text = str(key or "")
    if _PLAIN_KEY_RE.fullmatch(text) and text.lower() not in _RESERVED_DIR_NAMES:
        return text
    digest = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
    return f"s-{digest[:24]}"


def profile_dir(key: str) -> Path:
    """Session ``key``'s persistent Chromium profile (cookies, logins, storage)."""
    return profiles_root() / profile_dir_name(key)


def profile_lock_path(profile: Path) -> Path:
    """The cross-process lock file kept next to ``profile``."""
    return profile.parent / f"{profile.name}{PROFILE_LOCK_SUFFIX}"


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


def session_exists(session_id: Optional[str]) -> Optional[bool]:
    """Whether the agent session ``session_id`` exists; None when unknown
    (no agent runtime here: CLI tools, tests)."""
    try:
        manager = getattr(internal_action_interface(), "session_manager", None)
    except Exception:
        return None
    if manager is None:
        return None
    if not session_id:
        return False
    try:
        return manager.get(session_id) is not None
    except Exception:
        return None


def live_session_ids() -> Optional[FrozenSet[str]]:
    """Ids of the sessions the agent runtime has loaded; None when unknown."""
    try:
        manager = getattr(internal_action_interface(), "session_manager", None)
        sessions = getattr(manager, "sessions", None) if manager is not None else None
        if not isinstance(sessions, Mapping):
            return None
        return frozenset(key for key in list(sessions) if isinstance(key, str))
    except Exception:
        return None


def persisted_session_ids() -> Optional[FrozenSet[str]]:
    """Ids of every session row in session storage; None when it cannot be
    read. Blocking I/O (SQLite): call it from a worker thread."""
    try:
        from app.usage.session_storage import get_session_storage

        rows = get_session_storage().get_all_sessions()
    except Exception as exc:
        logger.debug(f"[MiniBrowser] Session storage unreadable: {type(exc).__name__}")
        return None
    return frozenset(
        row["session_id"]
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("session_id"), str)
    )


# Sub-agent ids (app/subagent/manager.py) start with this; a sub-agent drives
# its parent session's browser.
SUBAGENT_ID_PREFIX = "sub_"
MAIN_SESSION_KEY = DEFAULT_OWNER  # the main session: scheduled runs browse there
_MAX_SUBAGENT_DEPTH = 3


def is_subagent_id(owner: Optional[str]) -> bool:
    return isinstance(owner, str) and owner.startswith(SUBAGENT_ID_PREFIX)


def browser_key(owner: Optional[str]) -> Optional[str]:
    """The session whose browser ``owner`` drives.

    A session drives its own browser; a sub-agent drives its parent
    session's (a sub-agent spawned outside any session, the main one's).
    None for an unknown sub-agent, or one nested deeper than sub-agents can
    be: its browser is never guessed, since a wrong guess would hand it
    another session's cookies and signed-in sites.
    """
    current = owner
    for _depth in range(_MAX_SUBAGENT_DEPTH + 1):
        if not isinstance(current, str) or not current:
            return None
        if not is_subagent_id(current):
            return current
        record = subagent_record(current)
        if record is None:
            return None
        parent = record[0]
        if not parent:
            return MAIN_SESSION_KEY
        current = parent
    return None


def subagent_record(
    owner: Optional[str],
) -> Optional[Tuple[Optional[str], str, Optional[datetime]]]:
    """``(parent_session_id, agent_type, created_at_utc)`` for a sub-agent id.

    None when ``owner`` is not a known sub-agent. Sub-agent ids start with
    ``sub_``; ``created_at`` is naive UTC (as SubAgent stores it).
    """
    if not is_subagent_id(owner):
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
