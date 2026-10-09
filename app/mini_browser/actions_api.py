"""Entry point of the ``mini_browser_*`` action stubs: validate, route, answer.

``validate(op, input_data)`` turns the LLM's raw input into clean operation
params (types checked, numbers clamped, URLs resolved) or raises
``MiniBrowserError(MINI_BROWSER_INVALID_INPUT)``. ``run_action(op,
input_data)`` answers ``simulated_mode`` without touching the browser,
works out which agent is calling (its own tab), and runs the operation on
the Mini Browser host loop. It never raises: every failure comes back as a
standard action error dict.
"""

from __future__ import annotations

import asyncio
import math
import re
import sys
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

from app.logger import logger
from app.mini_browser import DEFAULT_OWNER
from app.mini_browser.errors import (
    MiniBrowserError,
    action_error,
    first_line,
    from_exception,
)

OPS = (
    "navigate",
    "read",
    "click",
    "hover",
    "type",
    "press_key",
    "select_option",
    "scroll",
    "wait",
    "upload_file",
    "login",
    "screenshot",
    "tabs",
)
URL_OPS = frozenset({"navigate", "tabs"})

TIMEOUT_MS = (1000, 60000)
NAVIGATE_TIMEOUT_MS = 30000
WAIT_TIMEOUT_MS = 10000
FOR_USER_TIMEOUT_MS = (1000, 300000)
TEXT_CHARS = (500, 8000)
READ_TEXT_CHARS = 4000
READ_ELEMENTS = (1, 500)
READ_DEFAULT_ELEMENTS = 150
MAX_TEXT_OFFSET = 2**31 - 1
SCROLL_AMOUNT = (50, 5000)
WAIT_SECONDS = (0.0, 60.0)
MAX_TYPE_CHARS = 20000
MAX_KEYS_CHARS = 64
MAX_WAIT_TEXT_CHARS = 1000
MAX_VALUE_CHARS = 1000
MAX_USERNAME_CHARS = 256
MAX_URL_CHARS = 8192
MAX_PATHS = 10
MAX_PATH_CHARS = 1024
MAX_ELEMENT_ID = 10**7
MAX_TAB_INDEX = 1000
MAX_OWNER_CHARS = 200

DEFAULT_SEARCH_URL = "https://duckduckgo.com/?q={query}"

# The ContextVar holding the running action's input. Importing its module
# pulls in all of agent_core (seconds), so it is only read when the module
# is already loaded; if it is not, nothing can have set the variable.
_CONTEXT_MODULE = "agent_core.core.impl.action.context"

_MISSING = object()

UrlContext = Dict[str, Any]


# ── value helpers ───────────────────────────────────────────────────────────


def _invalid(detail: str) -> MiniBrowserError:
    return MiniBrowserError("MINI_BROWSER_INVALID_INPUT", detail=detail)


def _get(data: Dict[str, Any], names: Tuple[str, ...]) -> Any:
    for name in names:
        if data.get(name) is not None:
            return data[name]
    return _MISSING


def _blank(value: Any) -> bool:
    return value is _MISSING or (isinstance(value, str) and not value.strip())


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise _invalid(f"{name} must be a number, not true/false.")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            raise _invalid(f"{name} must be a number.") from None
    else:
        raise _invalid(f"{name} must be a number.")
    if not math.isfinite(number):
        raise _invalid(f"{name} must be a finite number.")
    return number


def _clamped_int(
    data: Dict[str, Any],
    name: str,
    default: Optional[int],
    low: int,
    high: int,
    *,
    aliases: Tuple[str, ...] = (),
) -> Optional[int]:
    raw = _get(data, (name,) + aliases)
    if _blank(raw):
        return default
    number = int(round(_number(raw, name)))
    return max(low, min(high, number))


def _clamped_float(
    data: Dict[str, Any], name: str, default: Optional[float], low: float, high: float
) -> Optional[float]:
    raw = _get(data, (name,))
    if _blank(raw):
        return default
    return max(low, min(high, _number(raw, name)))


def _flag(data: Dict[str, Any], name: str, default: bool) -> bool:
    raw = _get(data, (name,))
    if raw is _MISSING:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)) and raw in (0, 1):
        return bool(raw)
    if isinstance(raw, str):
        text = raw.strip().lower()
        if not text:
            return default
        if text in ("true", "yes", "y", "on", "1"):
            return True
        if text in ("false", "no", "n", "off", "0"):
            return False
    raise _invalid(f"{name} must be true or false.")


def _text(
    data: Dict[str, Any],
    name: str,
    *,
    max_chars: int,
    required: bool = False,
    strip: bool = True,
    allow_empty: bool = False,
    aliases: Tuple[str, ...] = (),
) -> Optional[str]:
    raw = _get(data, (name,) + aliases)
    if raw is _MISSING:
        if required:
            raise _invalid(f"{name} is required.")
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = str(raw)
    if not isinstance(raw, str):
        raise _invalid(f"{name} must be text.")
    value = raw.strip() if strip else raw
    if not value.strip() and not allow_empty:
        if required:
            raise _invalid(f"{name} must not be empty.")
        return None
    if len(value) > max_chars:
        raise _invalid(f"{name} is too long (at most {max_chars} characters).")
    return value


def _choice(
    data: Dict[str, Any], name: str, allowed: Tuple[str, ...], default: str
) -> str:
    raw = _get(data, (name,))
    if _blank(raw):
        return default
    value = str(raw).strip().lower() if isinstance(raw, str) else None
    if value not in allowed:
        raise _invalid(f"{name} must be one of: {', '.join(allowed)}.")
    return value


_ELEMENT_ID_RE = re.compile(r"\s*[\[#]?\s*(\d{1,8})\s*\]?\s*")


def _element_id(data: Dict[str, Any], *, required: bool = True) -> Optional[int]:
    raw = _get(data, ("element_id",))
    if _blank(raw):
        if required:
            raise _invalid(
                "element_id is required: the number in brackets in the latest "
                "page observation, e.g. 3 for [3]."
            )
        return None
    value: Optional[int] = None
    if isinstance(raw, bool):
        value = None
    elif isinstance(raw, int):
        value = raw
    elif isinstance(raw, float) and math.isfinite(raw) and raw.is_integer():
        value = int(raw)
    elif isinstance(raw, str):
        match = _ELEMENT_ID_RE.fullmatch(raw)
        value = int(match.group(1)) if match else None
    if value is None or not 0 <= value <= MAX_ELEMENT_ID:
        raise _invalid(
            "element_id must be a whole number from the latest page observation, "
            "e.g. 3 for [3]."
        )
    return value


def _tab_index(data: Dict[str, Any]) -> Optional[int]:
    raw = _get(data, ("tab", "index"))
    if _blank(raw):
        return None
    value: Optional[int] = None
    if isinstance(raw, bool):
        value = None
    elif isinstance(raw, int):
        value = raw
    elif isinstance(raw, float) and math.isfinite(raw) and raw.is_integer():
        value = int(raw)
    elif isinstance(raw, str) and raw.strip().isdigit():
        value = int(raw.strip())
    if value is None or not 0 <= value <= MAX_TAB_INDEX:
        raise _invalid("tab must be the tab's index from the tabs list, e.g. 1.")
    return value


def _paths(data: Dict[str, Any]) -> List[str]:
    raw = _get(data, ("paths", "path"))
    if isinstance(raw, str):
        raw = [raw]
    if raw is _MISSING or not isinstance(raw, (list, tuple)) or not raw:
        raise _invalid(
            "paths is required: a list of file paths in the agent workspace."
        )
    if len(raw) > MAX_PATHS:
        raise _invalid(f"At most {MAX_PATHS} files can be uploaded at once.")
    cleaned: List[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise _invalid("Every entry of paths must be a file path.")
        path = item.strip()
        if len(path) > MAX_PATH_CHARS or "\x00" in path:
            raise _invalid("A file path is too long or contains invalid characters.")
        cleaned.append(path)
    return cleaned


def _resolve_url(
    text: str, context: Optional[UrlContext], *, allow_history: bool
) -> str:
    """Resolve agent text into a URL, or "back" / "forward" / "reload"."""
    from app.mini_browser import urls

    context = context or {}
    target = urls.resolve(
        text,
        allow_history=allow_history,
        allow_search=True,
        search_url=str(context.get("search_url") or DEFAULT_SEARCH_URL),
        allow_file=bool(context.get("allow_file", False)),
        ui_origins=frozenset(context.get("ui_origins") or ()),
    )
    kind = getattr(target, "kind", "")
    url = getattr(target, "url", "")
    if kind in ("back", "forward", "reload"):
        return kind
    if kind == "url" and isinstance(url, str) and url:
        return url
    raise _invalid("Could not understand that address.")


# ── per-operation validators ────────────────────────────────────────────────


def _v_navigate(data: Dict[str, Any], context: Optional[UrlContext]) -> Dict[str, Any]:
    raw = _text(data, "url", max_chars=MAX_URL_CHARS, required=True)
    return {
        "url": _resolve_url(raw, context, allow_history=True),
        "timeout_ms": _clamped_int(
            data, "timeout_ms", NAVIGATE_TIMEOUT_MS, *TIMEOUT_MS, aliases=("timeout",)
        ),
    }


def _v_read(data: Dict[str, Any], _context: Optional[UrlContext]) -> Dict[str, Any]:
    return {
        "max_text_chars": _clamped_int(
            data, "max_text_chars", READ_TEXT_CHARS, *TEXT_CHARS
        ),
        "max_elements": _clamped_int(
            data, "max_elements", READ_DEFAULT_ELEMENTS, *READ_ELEMENTS
        ),
        "text_offset": _clamped_int(data, "text_offset", 0, 0, MAX_TEXT_OFFSET),
    }


def _v_click(data: Dict[str, Any], _context: Optional[UrlContext]) -> Dict[str, Any]:
    return {
        "element_id": _element_id(data),
        "button": _choice(data, "button", ("left", "right", "middle"), "left"),
        "double": _flag(data, "double", False),
    }


def _v_hover(data: Dict[str, Any], _context: Optional[UrlContext]) -> Dict[str, Any]:
    return {"element_id": _element_id(data)}


def _v_type(data: Dict[str, Any], _context: Optional[UrlContext]) -> Dict[str, Any]:
    return {
        "element_id": _element_id(data),
        "text": _text(
            data,
            "text",
            max_chars=MAX_TYPE_CHARS,
            required=True,
            strip=False,
            allow_empty=True,
        ),
        "submit": _flag(data, "submit", False),
        "clear": _flag(data, "clear", True),
    }


def _v_press_key(
    data: Dict[str, Any], _context: Optional[UrlContext]
) -> Dict[str, Any]:
    from app.mini_browser.ops import parse_keys

    keys = _text(
        data, "keys", max_chars=MAX_KEYS_CHARS, required=True, aliases=("key",)
    )
    return {
        "keys": " ".join(parse_keys(keys)),
        "element_id": _element_id(data, required=False),
    }


def _v_select_option(
    data: Dict[str, Any], _context: Optional[UrlContext]
) -> Dict[str, Any]:
    return {
        "element_id": _element_id(data),
        "value": _text(
            data,
            "value",
            max_chars=MAX_VALUE_CHARS,
            required=True,
            strip=False,
            allow_empty=True,
        ),
    }


def _v_scroll(data: Dict[str, Any], _context: Optional[UrlContext]) -> Dict[str, Any]:
    return {
        "direction": _choice(
            data, "direction", ("down", "up", "top", "bottom"), "down"
        ),
        "amount": _clamped_int(data, "amount", None, *SCROLL_AMOUNT),
    }


def _v_wait(data: Dict[str, Any], _context: Optional[UrlContext]) -> Dict[str, Any]:
    for_user = _flag(data, "for_user", False)
    if for_user:
        timeout = _clamped_int(
            data, "timeout_ms", FOR_USER_TIMEOUT_MS[1], *FOR_USER_TIMEOUT_MS
        )
    else:
        timeout = _clamped_int(data, "timeout_ms", WAIT_TIMEOUT_MS, *TIMEOUT_MS)
    return {
        "seconds": _clamped_float(data, "seconds", None, *WAIT_SECONDS),
        "text": _text(data, "text", max_chars=MAX_WAIT_TEXT_CHARS),
        "for_user": for_user,
        "timeout_ms": timeout,
    }


def _v_upload_file(
    data: Dict[str, Any], _context: Optional[UrlContext]
) -> Dict[str, Any]:
    return {"element_id": _element_id(data), "paths": _paths(data)}


def _v_login(data: Dict[str, Any], _context: Optional[UrlContext]) -> Dict[str, Any]:
    return {
        "username": _text(data, "username", max_chars=MAX_USERNAME_CHARS),
        "submit": _flag(data, "submit", True),
    }


def _v_screenshot(
    data: Dict[str, Any], _context: Optional[UrlContext]
) -> Dict[str, Any]:
    return {"full_page": _flag(data, "full_page", False)}


def _v_tabs(data: Dict[str, Any], context: Optional[UrlContext]) -> Dict[str, Any]:
    action = _choice(data, "action", ("list", "new", "switch", "close"), "list")
    tab = _tab_index(data)
    if action == "switch" and tab is None:
        raise _invalid(
            "tab is required for action='switch': the tab's index from the tabs list."
        )
    url = None
    if action == "new":
        raw = _text(data, "url", max_chars=MAX_URL_CHARS)
        if raw:
            url = _resolve_url(raw, context, allow_history=False)
    return {"action": action, "tab": tab, "url": url}


_VALIDATORS: Dict[
    str, Callable[[Dict[str, Any], Optional[UrlContext]], Dict[str, Any]]
] = {
    "navigate": _v_navigate,
    "read": _v_read,
    "click": _v_click,
    "hover": _v_hover,
    "type": _v_type,
    "press_key": _v_press_key,
    "select_option": _v_select_option,
    "scroll": _v_scroll,
    "wait": _v_wait,
    "upload_file": _v_upload_file,
    "login": _v_login,
    "screenshot": _v_screenshot,
    "tabs": _v_tabs,
}


def validate(
    op: str, input_data: dict, url_context: Optional[UrlContext] = None
) -> dict:
    """Clean params for ``op`` (pure; raises MINI_BROWSER_INVALID_INPUT).

    ``url_context`` (``{search_url, allow_file, ui_origins}``) feeds URL
    resolution for navigate / tabs(new); without it the defaults apply
    (DuckDuckGo search, no file: URLs, no UI origins known). Numbers are
    clamped to their ranges; wrong types and over-long text are refused.
    """
    validator = _VALIDATORS.get(op)
    if validator is None:
        raise _invalid(f"Unknown Mini Browser operation: {str(op)[:40]!r}.")
    data = input_data if isinstance(input_data, dict) else {}
    return validator(data, url_context)


# ── running ─────────────────────────────────────────────────────────────────


def _clean_owner(value: Any) -> Optional[str]:
    if isinstance(value, str):
        value = value.strip()
        if 0 < len(value) <= MAX_OWNER_CHARS:
            return value
    return None


def resolve_owner(input_data: Dict[str, Any]) -> str:
    """The calling agent's session id (its tab owner)."""
    owner = _clean_owner(input_data.get("_session_id"))
    if owner:
        return owner
    module = sys.modules.get(_CONTEXT_MODULE)
    if module is not None:
        try:
            current = module.current_input_data.get()
        except Exception:
            current = None
        if isinstance(current, dict):
            owner = _clean_owner(current.get("_session_id"))
            if owner:
                return owner
    return DEFAULT_OWNER


def _load_url_context() -> UrlContext:
    """Settings + UI origins for URL resolution (blocking: run in a thread)."""
    search_url, allow_file = DEFAULT_SEARCH_URL, False
    origins: FrozenSet[str] = frozenset()
    try:
        from app.mini_browser import config

        settings = config.load_settings()
        search_url = str(getattr(settings, "search_url", "") or DEFAULT_SEARCH_URL)
        allow_file = bool(getattr(settings, "allow_file_urls", False))
    except Exception as exc:
        logger.debug(
            f"[MiniBrowser] settings unavailable for URL checks: {type(exc).__name__}"
        )
    try:
        from app.mini_browser import bridge

        origins = frozenset(bridge.ui_origins())
    except Exception as exc:
        logger.debug(f"[MiniBrowser] UI origins unavailable: {type(exc).__name__}")
    return {"search_url": search_url, "allow_file": allow_file, "ui_origins": origins}


_PAGE_STUB: Dict[str, Any] = {
    "url": "about:blank",
    "title": "",
    "elements": [],
    "element_count": 0,
    "elements_truncated": False,
    "text": "",
    "text_offset": 0,
    "text_total": 0,
    "scroll": {"y": 0, "height": 0, "at_bottom": True},
    "tabs": [],
}


def simulated_result(op: str) -> Dict[str, Any]:
    """Canned success for simulated_mode (never touches the browser)."""
    page = {
        **_PAGE_STUB,
        "scroll": dict(_PAGE_STUB["scroll"]),
        "elements": [],
        "tabs": [],
    }
    message = f"Simulated mini_browser {op}."
    if op == "read":
        return {"status": "success", "message": message, **page, "note": "Simulated."}
    if op == "tabs":
        return {"status": "success", "message": message, "tabs": []}
    result: Dict[str, Any] = {"status": "success", "message": message}
    if op == "screenshot":
        result["file_path"] = ""
    if op == "login":
        result.update({"username": "", "site": "", "outcome": "filled"})
    result["page"] = page
    return result


async def run_action(op: str, input_data: dict) -> dict:
    """Run one Mini Browser operation for the calling agent. Never raises.

    Cancellation (the user pressed Stop) still propagates, so the action
    framework can record it.
    """
    data = input_data if isinstance(input_data, dict) else {}
    if data.get("simulated_mode"):
        return simulated_result(op)
    try:
        owner = resolve_owner(data)
        context = await asyncio.to_thread(_load_url_context) if op in URL_OPS else None
        params = validate(op, data, context)
        from app.mini_browser.host import get_host

        host = get_host()
        logger.debug(f"[MiniBrowser] {op} for {owner}")
        result = await host.call(lambda core: core.agent_op(owner, op, params))
    except MiniBrowserError as exc:
        return from_exception(exc)
    except Exception as exc:
        logger.warning(f"[MiniBrowser] {op} failed unexpectedly: {type(exc).__name__}")
        return action_error("MINI_BROWSER_INTERNAL", detail=first_line(exc))
    if not isinstance(result, dict):
        return action_error(
            "MINI_BROWSER_INTERNAL", detail="the browser returned no result"
        )
    return result
