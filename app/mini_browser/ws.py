# -*- coding: utf-8 -*-
"""WebSocket side of the chat browser panels, and the browsers' UI sink.

Every agent session has a browser of its own (``fleet.py``), shown in that
chat's browser panel. ``MiniBrowserWS`` lives in the browser UI adapter, on
the UI event loop, and has three jobs.

**Requests.** ``handle`` takes every ``mini_browser_*`` message from a
browser tab, validates and clamps it, and turns it into a call on the
browser host (``app.mini_browser.host``; the browsers run on their own
thread) or on the password vault. Requests about a session's browser name
the session (``sessionId``); tab ids are unique across every session's
browser. A handler never raises: an unhandled error would be broadcast into
every tab's main chat, so each failure is answered to the requesting socket
only, as ``{code, title, message}``. Page loads, history moves, new tabs and
starts run as background tasks, so a slow site never blocks the socket's
message lane. Live-view input is queued per socket and applied in order by
one drain task; while the page lags, mouse moves coalesce (latest wins) and
wheel steps add up, so a hung page never builds a backlog in front of the
user's keystrokes, and closing a browser or taking and handing back control
(their own lanes) never wait behind it. Replies (``{type, data}``):

- ``mini_browser_navigate`` -> ``mini_browser_nav_result {sessionId, ok, error?}``
- ``mini_browser_copy`` -> ``mini_browser_clipboard {text, requestId?}``
- ``mini_browser_activity_query`` -> ``mini_browser_activity {sessions, snapshot}``
- ``mini_browser_vault_list`` -> ``mini_browser_vault_list {entries, status, error?}``
- other vault requests -> ``mini_browser_vault_result {op, ok, error?}``
- subscribe, start, shutdown, the ad-block switch -> ``mini_browser_state``
- any other failure -> ``mini_browser_event {kind: "error", level, code, title,
  message, sessionId?}``

**Viewers.** A socket subscribes to the session whose browser panel it
shows; only that session's viewers receive its browser's state, frames,
agent cursor moves and events, and a browser streams its screen only while
it has a viewer. Opening the panel (subscribe) starts that session's
browser. Every client receives ``mini_browser_activity`` (which session
browsers run, and whether an agent is browsing in them, which opens that
chat's panel); viewers receive install progress. While the browser host has
never started, a session's state is synthesized here.

**UI sink.** The browser thread publishes through ``bridge.publish``, which
calls ``post`` here; ``post`` hops onto the UI loop in a clean context (no
request id of whatever request happens to be running). Frames are coalesced
into one latest-frame slot per session, and a socket that is still behind
gets no new frame, so a slow tab never queues a backlog of images in front
of its chat.

Passwords never travel to a browser tab: vault replies carry no password,
and any error text built from a request that carried one (a vault password,
text typed into the page) is scrubbed of it before it is logged or sent.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import json
import math
import threading
from collections import deque
from typing import (
    Any,
    Awaitable,
    Callable,
    Deque,
    Dict,
    FrozenSet,
    List,
    Optional,
    Protocol,
    Sequence,
    Set,
    Tuple,
)

from app.logger import logger
from app.mini_browser.errors import (
    ERROR_SPECS,
    MiniBrowserError,
    first_line,
    scrub,
    ui_error,
)

__all__ = ["MiniBrowserAdapter", "MiniBrowserWS"]

# Bridge message kind -> WebSocket message type.
_MESSAGE_TYPES: Dict[str, str] = {
    "state": "mini_browser_state",
    "frame": "mini_browser_frame",
    "pointer": "mini_browser_pointer",
    "event": "mini_browser_event",
    "activity": "mini_browser_activity",
    "install": "mini_browser_install_progress",
    "last_frame": "mini_browser_last_frame",
}
# Kinds about one session's browser (their payload names it: sessionId).
_SESSION_KINDS = frozenset({"state", "frame", "pointer", "event", "last_frame"})
# Queued-message backlog above which a socket is skipped for this kind: a
# frame is only worth sending to a socket that has caught up (the next frame
# replaces it anyway), a cursor move to one that is not badly behind.
_MAX_PENDING: Dict[str, int] = {"frame": 1, "pointer": 8}

_HISTORY_ACTIONS = frozenset({"back", "forward", "reload", "stop"})
_MOUSE_ACTIONS = frozenset({"down", "up", "move"})
_MOUSE_BUTTONS = frozenset({"left", "middle", "right"})
_MODIFIER_KEYS = ("shift", "ctrl", "alt", "meta")
# High-rate input whose failures are not worth a toast each (the next one
# follows within milliseconds); clicks, keys and pastes always report.
_CONTINUOUS_INPUT = frozenset({("mouse", "move"), ("wheel", None)})
# Live input waiting for the browser, per socket (see _InputQueue). The cap
# only matters for a page that stopped responding: continuous input is
# coalesced, so only clicks, keys and pastes can pile up.
_MAX_QUEUED_INPUT = 256
# How long copying a selection, or handing a tab back, waits for that tab's
# queued input to be applied first.
_INPUT_SETTLE_S = 2.0
_INPUT_SETTLE_POLL_S = 0.01

_VIEWPORT_WIDTH = (320, 3840)
_VIEWPORT_HEIGHT = (240, 2160)
_DEFAULT_VIEWPORT = {"width": 1280, "height": 800}
_MAX_WHEEL_DELTA = 5000.0
_MAX_KEY_CHARS = 32
_MAX_TEXT_CHARS = 2000
_MAX_URL_CHARS = 8192
_MAX_ID_CHARS = 128
_MAX_CLIPBOARD_CHARS = 200_000
_MAX_INSTALL_LINE_CHARS = 500

# Coarse caps only — the vault enforces its own exact limits; these keep
# megabyte strings away from it (and from any log line).
_MAX_VAULT_SITE_CHARS = 2048
_MAX_VAULT_USERNAME_CHARS = 1024
_MAX_VAULT_PASSWORD_CHARS = 4096
_MAX_VAULT_LABEL_CHARS = 1024
_VAULT_CODES = frozenset(
    {
        "MINI_BROWSER_VAULT_UNREADABLE",
        "MINI_BROWSER_VAULT_INVALID",
        "MINI_BROWSER_VAULT_IO",
    }
)
_VAULT_DEFAULT_DETAIL = {
    "MINI_BROWSER_VAULT_INVALID": "The login details are not valid.",
    "MINI_BROWSER_VAULT_IO": "the file could not be written.",
}
# The only entry fields that ever leave the server.
_ENTRY_FIELDS = (
    "id",
    "site",
    "username",
    "label",
    "createdAt",
    "updatedAt",
    "lastUsedAt",
)

_STATE_TIMEOUT_S = 5.0
_TASK_CANCEL_WAIT_S = 2.0
_SHUTDOWN_TIMEOUT_S = 10.0
_LIFECYCLE_SHUTDOWN_S = 8.0  # inside _SHUTDOWN_TIMEOUT_S, so it can finish cleanly

# Message type -> handler method name.
_HANDLERS: Dict[str, str] = {
    "mini_browser_subscribe": "_handle_subscribe",
    "mini_browser_unsubscribe": "_handle_unsubscribe",
    "mini_browser_activity_query": "_handle_activity_query",
    "mini_browser_start": "_handle_start",
    "mini_browser_shutdown": "_handle_shutdown",
    "mini_browser_install": "_handle_install",
    "mini_browser_navigate": "_handle_navigate",
    "mini_browser_history": "_handle_history",
    "mini_browser_input": "_handle_input",
    "mini_browser_resize": "_handle_resize",
    "mini_browser_tab": "_handle_tab",
    "mini_browser_view": "_handle_view",
    "mini_browser_control": "_handle_control",
    "mini_browser_adblock": "_handle_adblock",
    "mini_browser_copy": "_handle_copy",
    "mini_browser_vault_list": "_handle_vault_list",
    "mini_browser_vault_add": "_handle_vault_add",
    "mini_browser_vault_update": "_handle_vault_update",
    "mini_browser_vault_delete": "_handle_vault_delete",
    "mini_browser_vault_reset": "_handle_vault_reset",
}


class MiniBrowserAdapter(Protocol):
    """What ``MiniBrowserWS`` needs from the browser UI adapter."""

    @property
    def ui_hosts(self) -> FrozenSet[str]:
        """CraftBot's own UI origins (``host:port``): no browser opens them."""

    def client_channel(self, ws: Any) -> Any:
        """The open outbound channel of socket ``ws`` (``closed``, ``pending``,
        ``send_text``), or None when that socket is gone."""

    def client_channels(self) -> List[Any]:
        """The open outbound channel of every connected socket."""

    def send_only_to(self, ws: Any, message: Dict[str, Any]) -> bool:
        """Send ``message`` to socket ``ws`` only (never broadcast); whether
        it was queued."""


# ─────────────────────────────────────────────────────────────────────────────
# Collaborators, resolved lazily: importing this module never starts or even
# imports the browser engine. Module-level so tests can substitute them.
# ─────────────────────────────────────────────────────────────────────────────


def _get_host() -> Any:
    """The browser host, starting its thread (not Chromium) if needed."""
    from app.mini_browser.host import get_host

    return get_host()


def _host_if_started() -> Any:
    """The browser host if it has ever been started, else None."""
    try:
        from app.mini_browser.host import get_host_if_started
    except ImportError:
        return None
    return get_host_if_started()


def _get_vault() -> Any:
    from app.mini_browser.vault import get_vault

    return get_vault()


def _bridge() -> Any:
    from app.mini_browser import bridge

    return bridge


def _last_frame(key: str) -> Dict[str, Any]:
    """Session ``key``'s ``mini_browser_last_frame``: where its browser left
    off (``resume.py``). Blocking file I/O: run it in a worker thread."""
    from app.mini_browser import config, resume

    return resume.ui_payload(key, resume.resume_frame(config.profile_dir(key)))


def _lifecycle() -> Any:
    from app.mini_browser import lifecycle

    return lifecycle


def _load_settings() -> Dict[str, Any]:
    from app.config import get_mini_browser_settings

    return get_mini_browser_settings()


def _save_setting(key: str, value: Any) -> None:
    from app.config import set_mini_browser_setting

    set_mini_browser_setting(key, value)


def _notify_vault_changed() -> None:
    """Every tab showing saved logins refetches them (the data never broadcasts)."""
    try:
        from app.ui_layer.events.resource_changes import (
            Resource,
            notify_resource_changed,
        )

        notify_resource_changed(Resource.MINI_BROWSER_VAULT)
    except Exception as e:
        logger.debug(f"[MINI_BROWSER] Vault change notice failed: {e}")


def _run_install(log: Callable[[str], None]) -> Tuple[bool, str]:
    """Download Playwright's Chromium (blocking: runs on a worker thread)."""
    from app.provision import default_context
    from app.provision.deps import PlaywrightStage

    result = PlaywrightStage().apply(default_context(), log)
    return bool(result.ok), str(result.detail or "")


# ─────────────────────────────────────────────────────────────────────────────
# Host-loop helpers (run inside host.call / call_fleet on the browser thread)
# ─────────────────────────────────────────────────────────────────────────────


async def _existing_state(key: str, fleet: Any) -> Optional[Dict[str, Any]]:
    """Session ``key``'s browser state, or None when it was never used."""
    core = fleet.existing(key)
    return core.state() if core is not None else None


async def _on_existing(
    key: str, fn: Callable[[Any], Awaitable[Any]], fleet: Any
) -> Any:
    """``fn(core)`` on session ``key``'s browser if it was ever used (else None)."""
    core = fleet.existing(key)
    return await fn(core) if core is not None else None


async def _activity(fleet: Any) -> List[Dict[str, Any]]:
    return fleet.activity()


async def _clear_launch_errors(fleet: Any) -> None:
    """After an install, an earlier "browser missing" failure no longer applies."""
    for core in list(fleet.cores.values()):
        core.clear_launch_error()


async def _copy_selection(
    core: Any, tab_id: str, cut_request: Optional[str] = None
) -> str:
    """The tab's selected text, minus any password autofill typed into it.

    ``cut_request``: the copy is the first half of a cut (see
    BrowserCore.ui_copy_selection)."""
    if cut_request:
        text = await core.ui_copy_selection(tab_id, cut_request=cut_request)
    else:
        text = await core.ui_copy_selection(tab_id)
    if not isinstance(text, str):
        return ""
    tab = (getattr(core, "tabs", None) or {}).get(tab_id)
    secrets = list(getattr(tab, "filled_secrets", None) or ())
    cleaned = _clean_text(text[:_MAX_CLIPBOARD_CHARS], secrets)
    if cut_request and cleaned != text:
        # The clipboard does not get the selection as it is: never delete it.
        core.ui_drop_cut(tab_id, cut_request)
    return cleaned


def _cut_key(ws: Any, request_id: str) -> str:
    """A cut's request id, scoped to the viewer connection that sent it: every
    viewer counts its own ids, so two viewers' cuts never share a record."""
    return f"{id(ws):x}:{request_id}"


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────


def _invalid(detail: str) -> MiniBrowserError:
    return MiniBrowserError("MINI_BROWSER_INVALID_INPUT", detail=detail)


def _number(value: Any, name: str) -> float:
    """A finite number (bools, strings, NaN and infinities are refused)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{name} must be a number.")
    try:
        number = float(value)
    except OverflowError:
        raise _invalid(f"{name} is out of range.") from None
    if not math.isfinite(number):
        raise _invalid(f"{name} must be a finite number.")
    return number


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _int_in(value: Any, name: str, bounds: Tuple[int, int]) -> int:
    return int(_clamp(round(_number(value, name)), bounds[0], bounds[1]))


def _unit(value: Any, name: str) -> float:
    """A coordinate normalised to the frame the user saw, clamped to 0..1."""
    return _clamp(_number(value, name), 0.0, 1.0)


def _delta(value: Any, name: str) -> float:
    if value is None:
        return 0.0
    return _clamp(_number(value, name), -_MAX_WHEEL_DELTA, _MAX_WHEEL_DELTA)


def _short_id(value: Any, name: str, *, required: bool) -> Optional[str]:
    """A tab or entry id: a short printable string (None when optional and absent)."""
    if value is None or value == "":
        if required:
            raise _invalid(f"{name} is required.")
        return None
    if (
        not isinstance(value, str)
        or len(value) > _MAX_ID_CHARS
        or not value.isprintable()
    ):
        raise _invalid(f"{name} is not a valid id.")
    return value


def _required_id(value: Any, name: str) -> str:
    """A required tab / session id (see :func:`_short_id`)."""
    checked = _short_id(value, name, required=True)
    if checked is None:  # unreachable: _short_id raises for a missing id
        raise _invalid(f"{name} is required.")
    return checked


def _flag(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid(f"{name} must be true or false.")
    return value


def _url_text(value: Any, *, required: bool) -> Optional[str]:
    """What the user typed in the address bar (a URL or a search)."""
    if value is None:
        if required:
            raise _invalid("Type an address or a search.")
        return None
    if not isinstance(value, str):
        raise _invalid("The address must be text.")
    text = value.strip()
    if len(text) > _MAX_URL_CHARS:
        raise _invalid(
            f"The address is too long ({_MAX_URL_CHARS} characters at most)."
        )
    if not text:
        if required:
            raise _invalid("Type an address or a search.")
        return None
    return text


def _input_event(event: Any) -> Optional[Dict[str, Any]]:
    """A validated, clamped copy of a live-view input event.

    None for an unknown kind (ignored); a malformed known kind raises
    MINI_BROWSER_INVALID_INPUT.
    """
    if not isinstance(event, dict):
        raise _invalid("event must be an object.")
    kind = event.get("kind")
    if kind == "mouse":
        action = event.get("action")
        if action not in _MOUSE_ACTIONS:
            raise _invalid("Unknown mouse action.")
        button = event.get("button", "left")
        if button not in _MOUSE_BUTTONS:
            raise _invalid("Unknown mouse button.")
        clicks = event.get("clickCount")
        click_count = 1 if clicks is None else _int_in(clicks, "clickCount", (1, 3))
        return {
            "kind": "mouse",
            "action": action,
            "x": _unit(event.get("x"), "x"),
            "y": _unit(event.get("y"), "y"),
            "button": button,
            "clickCount": click_count,
        }
    if kind == "wheel":
        return {
            "kind": "wheel",
            "x": _unit(event.get("x"), "x"),
            "y": _unit(event.get("y"), "y"),
            "dx": _delta(event.get("dx"), "dx"),
            "dy": _delta(event.get("dy"), "dy"),
        }
    if kind == "key":
        key = event.get("key")
        if (
            not isinstance(key, str)
            or not key
            or len(key) > _MAX_KEY_CHARS
            or not key.isprintable()
        ):
            raise _invalid(
                f"key must be a key name ({_MAX_KEY_CHARS} characters at most)."
            )
        modifiers = event.get("modifiers")
        if not isinstance(modifiers, dict):
            modifiers = {}
        return {
            "kind": "key",
            "key": key,
            "modifiers": {name: modifiers.get(name) is True for name in _MODIFIER_KEYS},
        }
    if kind == "cut":
        # Delete what a cut copied (see BrowserCore._cut); queued like any
        # other input, so it runs after what the user did before it.
        return {
            "kind": "cut",
            "requestId": _short_id(event.get("requestId"), "requestId", required=True),
        }
    if kind == "text":
        text = event.get("text")
        if not isinstance(text, str) or not text:
            raise _invalid("text must be a non-empty string.")
        if len(text) > _MAX_TEXT_CHARS:
            raise _invalid(
                f"The pasted text is too long ({_MAX_TEXT_CHARS} characters at most)."
            )
        return {"kind": "text", "text": text}
    return None


def _vault_text(
    data: Dict[str, Any], key: str, limit: int, *, required: bool
) -> Optional[str]:
    """A vault form field. Never echoes the value in an error."""
    value = data.get(key)
    if value is None:
        return "" if required else None
    if not isinstance(value, str):
        raise _invalid(f"{key} must be text.")
    if len(value) > limit:
        raise _invalid(f"{key} is too long.")
    return value


# ─────────────────────────────────────────────────────────────────────────────
# Secrets and error replies
# ─────────────────────────────────────────────────────────────────────────────


def _request_secrets(data: Dict[str, Any]) -> Tuple[str, ...]:
    """Strings in a request that must never be echoed back or logged."""
    secrets = []
    password = data.get("password")
    if isinstance(password, str) and password:
        secrets.append(password)
    event = data.get("event")
    if isinstance(event, dict) and isinstance(event.get("text"), str) and event["text"]:
        secrets.append(event["text"])  # may be a password typed into a page
    return tuple(secrets)


def _clean_text(text: str, secrets: Sequence[str]) -> str:
    """``text`` without any of ``secrets`` (fully masked if one is too short to scrub)."""
    if not secrets:
        return text
    cleaned = scrub(text, secrets)
    if any(secret and secret in cleaned for secret in secrets):
        return "[redacted]"
    return cleaned


def _error_reply(
    code: str,
    fields: Optional[Dict[str, Any]] = None,
    secrets: Sequence[str] = (),
) -> Dict[str, str]:
    """``errors.ui_error`` with its text scrubbed of the request's secrets.

    Only the message carries caller-supplied text; the code and the title
    are constants from ERROR_SPECS.
    """
    clean_fields = {
        key: _clean_text(value, secrets) if isinstance(value, str) else value
        for key, value in (fields or {}).items()
        if key not in ("code", "secrets")
    }
    error = ui_error(code, secrets=secrets, **clean_fields)
    error["message"] = _clean_text(error["message"], secrets)
    return error


def _vault_detail(exc: Exception, code: str, secrets: Sequence[str]) -> str:
    """The user-facing reason of a vault failure, never containing a secret."""
    fields = getattr(exc, "fields", None)
    if isinstance(fields, dict):
        # A MiniBrowserError (the vault's VaultError is one): its str() is
        # "CODE: {fields}", so only the detail field is meant for the user.
        detail = fields.get("detail")
        detail = detail if isinstance(detail, str) else ""
    else:
        detail = getattr(exc, "detail", None)
        if not isinstance(detail, str) or not detail.strip():
            detail = first_line(exc)
        if detail.startswith(f"{code}:"):
            detail = detail[len(code) + 1 :]
    detail = detail.strip()
    if detail in ("", code, type(exc).__name__):
        detail = _VAULT_DEFAULT_DETAIL.get(code, "")
    return _clean_text(detail, secrets)


async def _vault_call(fn: Callable[[Any], Any], secrets: Sequence[str] = ()) -> Any:
    """``fn(vault)`` on a worker thread (the vault does blocking file I/O and
    crypto); a VaultError becomes the matching MiniBrowserError."""
    try:
        return await asyncio.to_thread(lambda: fn(_get_vault()))
    except Exception as e:
        code = getattr(e, "code", None)
        if code in _VAULT_CODES:
            raise MiniBrowserError(
                code, detail=_vault_detail(e, code, secrets)
            ) from None
        raise


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)


def _public_entries(entries: Any) -> List[Dict[str, Any]]:
    """Saved logins as the UI may see them: a fixed allowlist of fields."""
    if not isinstance(entries, (list, tuple)):
        return []
    return [
        {key: _json_safe(entry.get(key)) for key in _ENTRY_FIELDS}
        for entry in entries
        if isinstance(entry, dict)
    ]


def _public_status(status: Any) -> Dict[str, Any]:
    status = status if isinstance(status, dict) else {}
    protection = status.get("protection")
    return {
        "ok": bool(status.get("ok")),
        "unreadable": bool(status.get("unreadable")),
        "protection": protection if protection in ("dpapi", "file") else "file",
    }


def _level(code: str) -> str:
    severity = ERROR_SPECS.get(code, ERROR_SPECS["MINI_BROWSER_INTERNAL"])[1]
    return severity if severity in ("info", "warning") else "error"


def _log_future_failure(what: str, future: Any) -> None:
    try:
        if future.cancelled():
            return
        exc = future.exception()
    except Exception:
        return
    if exc is not None:
        logger.debug(f"[MINI_BROWSER] {what} failed: {first_line(exc)}")


async def _in_daemon_thread(fn: Callable[..., Any], *args: Any) -> Any:
    """Run blocking ``fn`` on a daemon thread and await its result.

    Unlike ``asyncio.to_thread``, a daemon thread never holds up interpreter
    exit: ``asyncio.run`` joins the default executor's threads on shutdown,
    which would keep the app alive until a minutes-long download finished.
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def settle(result: Any, error: Optional[BaseException]) -> None:
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)

    def worker() -> None:
        result: Any = None
        error: Optional[BaseException] = None
        try:
            result = fn(*args)
        except Exception as e:
            error = e
        except BaseException as e:  # SystemExit etc.: still settle the future
            error = RuntimeError(f"interrupted ({type(e).__name__})")
        try:
            loop.call_soon_threadsafe(settle, result, error)
        except RuntimeError:
            pass  # the UI loop is gone (shutdown)

    threading.Thread(target=worker, name="mini-browser-install", daemon=True).start()
    return await future


# ─────────────────────────────────────────────────────────────────────────────
# Live input queue
# ─────────────────────────────────────────────────────────────────────────────


class _InputQueue:
    """One socket's live input that has not reached its browser yet.

    Events are applied one at a time, in arrival order, by a single drain
    task. While the page lags behind, continuous input is coalesced at the
    tail (see :func:`_coalesce`), so a slow or hung page costs a few queued
    events instead of a backlog of hover moves that would hold up keystrokes.
    Each event names its session's browser and its tab.
    """

    __slots__ = ("items", "task", "current", "overflowed")

    def __init__(self) -> None:
        self.items: Deque[Tuple[str, str, Dict[str, Any]]] = deque()
        self.task: Optional[asyncio.Task] = None
        # (session, tab) of the event being applied.
        self.current: Optional[Tuple[str, str]] = None
        self.overflowed = False

    def pending_for(self, key: str, tab_id: str) -> bool:
        """Whether input for ``tab_id`` of session ``key`` is queued or being applied."""
        target = (key, tab_id)
        return self.current == target or any(
            (session, tab) == target for session, tab, _ in self.items
        )

    def drop_tab(self, key: str, tab_id: str) -> int:
        """Forget the queued (not yet applied) input of one tab."""
        return self._drop(lambda session, tab: session == key and tab == tab_id)

    def drop_session(self, key: str) -> int:
        """Forget the queued (not yet applied) input of a session's browser."""
        return self._drop(lambda session, _tab: session == key)

    def _drop(self, matches: Callable[[str, str], bool]) -> int:
        kept = [item for item in self.items if not matches(item[0], item[1])]
        dropped = len(self.items) - len(kept)
        if dropped:
            self.items = deque(kept)
        return dropped


def _coalesce(
    items: Deque[Tuple[str, str, Dict[str, Any]]],
    key: str,
    tab_id: str,
    event: Dict[str, Any],
) -> bool:
    """Merge ``event`` into the newest queued event if both are continuous
    input of the same kind on the same tab: a move replaces the queued move
    (only where the pointer ends up matters), a wheel step adds its deltas to
    the queued one (scroll distance is never lost). Never reaches past the
    newest event, so nothing is reordered around a click, key or paste.
    Returns whether it was merged.
    """
    if not items:
        return False
    last_key, last_tab, last = items[-1]
    if last_key != key or last_tab != tab_id or last["kind"] != event["kind"]:
        return False
    if event["kind"] == "mouse":
        if event["action"] != "move" or last["action"] != "move":
            return False
        items[-1] = (key, tab_id, event)
        return True
    if event["kind"] == "wheel":
        dx = last["dx"] + event["dx"]
        dy = last["dy"] + event["dy"]
        if abs(dx) > _MAX_WHEEL_DELTA or abs(dy) > _MAX_WHEEL_DELTA:
            return False
        items[-1] = (key, tab_id, {**event, "dx": dx, "dy": dy})
        return True
    return False


def _session_id(data: Dict[str, Any]) -> str:
    """The session whose browser a request is about."""
    return _required_id(data.get("sessionId"), "sessionId")


def _optional_session_id(data: Dict[str, Any]) -> Optional[str]:
    """The request's session id when it carries a valid one, else None."""
    try:
        return _short_id(data.get("sessionId"), "sessionId", required=False)
    except MiniBrowserError:
        return None


def _dump(msg_type: str, data: Dict[str, Any]) -> Optional[str]:
    try:
        return json.dumps({"type": msg_type, "data": data}, allow_nan=False)
    except (TypeError, ValueError) as e:
        logger.warning(f"[MINI_BROWSER] Dropped an unserializable {msg_type}: {e}")
        return None


async def _sync_core_stream(core: Any) -> None:
    await core.set_streaming(core.has_viewers())


async def _push_frame(core: Any) -> None:
    await core.push_frame_now()


async def _close_core(core: Any) -> None:
    await core.close()


# ─────────────────────────────────────────────────────────────────────────────
# The handler
# ─────────────────────────────────────────────────────────────────────────────


class MiniBrowserWS:
    """Browser-panel requests, viewers and UI sink for one browser adapter.

    Everything except ``has_viewers`` and ``post`` runs on the UI loop;
    those two are called from the browser thread.
    """

    def __init__(self, adapter: MiniBrowserAdapter) -> None:
        self._adapter = adapter
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Sockets watching each session's browser, and the sessions each
        # socket watches (UI loop only).
        self._viewers: Dict[str, Set[Any]] = {}
        self._watching: Dict[Any, Set[str]] = {}
        # Sessions with a viewer, read by the browser thread (replaced, never
        # mutated, so a read never needs a lock).
        self._watched: FrozenSet[str] = frozenset()
        # The latest frame of each session, filled by the browser thread and
        # drained on the UI loop.
        self._frame_lock = threading.Lock()
        self._frames: Dict[str, Dict[str, Any]] = {}
        self._frames_scheduled = False
        self._tasks: set = set()
        self._installing = False
        # Live input per socket, waiting for the browser (UI loop only).
        self._input_queues: Dict[Any, _InputQueue] = {}

    # ── lifecycle (called by the adapter) ────────────────────────────────────

    def on_start(self) -> None:
        """Adapter started: capture the UI loop and become the bridge's UI sink."""
        self._loop = asyncio.get_running_loop()
        try:
            bridge = _bridge()
            bridge.set_ui_origins(self._ui_hosts())
            bridge.register_ui_sink(self)
        except Exception as e:
            logger.warning(f"[MINI_BROWSER] Live view unavailable: {first_line(e)}")

    async def shutdown(self) -> None:
        """Adapter stopping: detach from the bridge, end background work and
        close every browser (each holds a lock on its profile). Never raises."""
        try:
            _bridge().unregister_ui_sink(self)
        except Exception as e:
            logger.debug(f"[MINI_BROWSER] Sink unregister failed: {first_line(e)}")
        self._loop = None
        with self._frame_lock:
            self._frames.clear()
            self._frames_scheduled = False
        self._viewers.clear()
        self._watching.clear()
        self._watched = frozenset()
        self._input_queues.clear()
        tasks = [task for task in self._tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=_TASK_CANCEL_WAIT_S)
        try:
            if _host_if_started() is None:
                return
            await asyncio.wait_for(
                _lifecycle().shutdown(timeout=_LIFECYCLE_SHUTDOWN_S),
                timeout=_SHUTDOWN_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning("[MINI_BROWSER] Browser shutdown timed out")
        except Exception as e:
            logger.warning(f"[MINI_BROWSER] Browser shutdown failed: {first_line(e)}")

    def forget(self, ws: Any) -> None:
        """A socket closed: it watches no browser any more, and its input that
        has not reached a browser yet is dropped. Never raises."""
        try:
            queue = self._input_queues.pop(ws, None)
            if queue is not None:
                queue.items.clear()
            self._forget_viewer(ws)
        except Exception as e:
            logger.debug(f"[MINI_BROWSER] forget failed: {first_line(e)}")

    # ── UI sink (thread-safe) ────────────────────────────────────────────────

    def has_viewers(self, key: str) -> bool:
        """Whether any socket watches session ``key``'s browser. Thread-safe."""
        return key in self._watched

    def post(self, kind: str, payload: Dict[str, Any]) -> None:
        """Deliver a bridge message. Thread-safe, never blocks.

        ``kind`` is one of state / frame / pointer / event (to the viewers of
        the session the payload names), activity (to every client) or
        install (to every viewer). Frames are coalesced: only the newest one
        of each session waiting for the UI loop is sent.
        """
        loop = self._loop
        if loop is None or kind not in _MESSAGE_TYPES or not isinstance(payload, dict):
            return
        data = dict(payload)  # the producer may reuse its dict
        key = data.get("sessionId")
        if kind in _SESSION_KINDS:
            if not isinstance(key, str) or key not in self._watched:
                return
        elif kind == "install" and not self._watched:
            return
        context = contextvars.Context()
        try:
            if kind == "frame":
                with self._frame_lock:
                    self._frames[key] = data
                    if self._frames_scheduled:
                        return
                    self._frames_scheduled = True
                try:
                    loop.call_soon_threadsafe(self._flush_frames, context=context)
                except RuntimeError:
                    with self._frame_lock:
                        self._frames_scheduled = False
                        self._frames.clear()
                    raise
            else:
                loop.call_soon_threadsafe(self._deliver, kind, data, context=context)
        except RuntimeError:
            pass  # the UI loop is closed (shutting down): nobody to deliver to

    def _flush_frames(self) -> None:
        with self._frame_lock:
            frames, self._frames = self._frames, {}
            self._frames_scheduled = False
        for data in frames.values():
            self._deliver("frame", data)

    def _deliver(self, kind: str, data: Dict[str, Any]) -> None:
        """UI loop: send one bridge message to whoever it is for."""
        try:
            msg_type = _MESSAGE_TYPES[kind]
            if kind == "activity":
                self._send_to_all(msg_type, {"sessions": [data], "snapshot": False})
            elif kind == "install":
                self._send_to_viewers(None, msg_type, data)
            else:
                if kind == "state":
                    data = self._overlay_state(data)
                self._send_to_viewers(
                    data["sessionId"], msg_type, data, _MAX_PENDING.get(kind)
                )
        except Exception as e:
            logger.warning(f"[MINI_BROWSER] {kind} delivery failed: {first_line(e)}")

    def _send_to_viewers(
        self,
        key: Optional[str],
        msg_type: str,
        data: Dict[str, Any],
        max_pending: Optional[int] = None,
    ) -> None:
        """Queue one message for each socket watching session ``key``'s browser
        (``key`` None: watching any browser). Never via a broadcast."""
        sockets = (
            list(self._viewers.get(key, ()))
            if key is not None
            else list(self._watching)
        )
        if not sockets:
            return
        text = _dump(msg_type, data)
        if text is None:
            return
        for ws in sockets:
            channel = self._adapter.client_channel(ws)
            if channel is None or channel.closed:
                self._forget_viewer(ws)
            elif max_pending is None or channel.pending <= max_pending:
                channel.send_text(text)

    def _send_to_all(self, msg_type: str, data: Dict[str, Any]) -> None:
        """Queue one message for every connected socket."""
        channels = self._adapter.client_channels()
        if not channels:
            return
        text = _dump(msg_type, data)
        if text is None:
            return
        for channel in channels:
            if not channel.closed:
                channel.send_text(text)

    # ── viewers and streaming ────────────────────────────────────────────────

    def _add_viewer(self, ws: Any, key: str) -> bool:
        """``ws`` watches session ``key``'s browser; True for its first viewer."""
        viewers = self._viewers.setdefault(key, set())
        first = not viewers
        viewers.add(ws)
        self._watching.setdefault(ws, set()).add(key)
        if first:
            self._watched = frozenset(self._viewers)
        return first

    def _drop_viewer(self, ws: Any, key: str) -> None:
        viewers = self._viewers.get(key)
        if not viewers or ws not in viewers:
            return
        viewers.discard(ws)
        keys = self._watching.get(ws)
        if keys is not None:
            keys.discard(key)
            if not keys:
                del self._watching[ws]
        if not viewers:
            del self._viewers[key]
            self._watched = frozenset(self._viewers)
            self._sync_streaming(key)

    def _forget_viewer(self, ws: Any) -> None:
        for key in list(self._watching.get(ws, ())):
            self._drop_viewer(ws, key)

    def _watches(self, ws: Any, key: str) -> bool:
        return ws in self._viewers.get(key, ())

    def _sync_streaming(self, key: str) -> None:
        """Tell session ``key``'s browser to stream iff someone watches it."""
        host = _host_if_started()
        if host is not None:
            self._submit(
                host,
                functools.partial(_on_existing, key, _sync_core_stream),
                "set_streaming",
            )

    @staticmethod
    def _submit(host: Any, fn: Callable[[Any], Awaitable[Any]], what: str) -> None:
        """Fire-and-forget call on the browser loop; failures are only logged."""
        try:
            future = host.submit(fn)
            future.add_done_callback(functools.partial(_log_future_failure, what))
        except Exception as e:
            logger.debug(f"[MINI_BROWSER] {what} not sent: {first_line(e)}")

    # ── state ────────────────────────────────────────────────────────────────

    def _ui_hosts(self) -> frozenset:
        try:
            return frozenset(self._adapter.ui_hosts)
        except Exception:
            return frozenset()

    def _overlay_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """What only this side knows: a Chromium install in progress."""
        if self._installing and state.get("status") in ("stopped", "error"):
            state = {**state, "status": "installing", "error": None}
        return state

    async def _synthesized_state(
        self, key: str, error: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """The state of a session browser that was never used (never starts it)."""
        settings = await asyncio.to_thread(_load_settings)
        return {
            "sessionId": key,
            "status": "error" if error else "stopped",
            "error": error,
            "adblock": bool(settings.get("adblock", True)),
            "viewedTabId": None,
            "follow": True,
            "viewport": dict(_DEFAULT_VIEWPORT),
            "tabs": [],
            "settings": {
                "humanlike": bool(settings.get("humanlike", True)),
                "showCursor": bool(settings.get("show_cursor", True)),
            },
        }

    async def _state_snapshot(
        self, key: str, error: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Session ``key``'s current ``mini_browser_state``. Never starts a
        browser. ``error`` is shown when the browser has no error of its own
        (a request about it failed before it existed)."""
        state: Any = None
        host = _host_if_started()
        if host is not None:
            try:
                state = await asyncio.wait_for(
                    host.call_fleet(functools.partial(_existing_state, key)),
                    _STATE_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                error = error or _error_reply(
                    "MINI_BROWSER_TIMEOUT",
                    {"what": "The browser", "seconds": int(_STATE_TIMEOUT_S)},
                )
            except Exception as e:
                error = error or _error_reply(
                    "MINI_BROWSER_INTERNAL", {"detail": first_line(e)}
                )
        if not isinstance(state, dict):
            state = await self._synthesized_state(key, error)
        elif error is not None and not state.get("error"):
            state = {**state, "status": "error", "error": error}
        return self._overlay_state(state)

    async def _publish_state(
        self, key: str, ws: Any = None, error: Optional[Dict[str, str]] = None
    ) -> None:
        """Send session ``key``'s state to its viewers (and to ``ws`` if it
        does not watch it)."""
        try:
            state = await self._state_snapshot(key, error)
            self._send_to_viewers(key, "mini_browser_state", state)
            if ws is not None and not self._watches(ws, key):
                self._send(ws, "mini_browser_state", state)
        except Exception as e:
            logger.debug(f"[MINI_BROWSER] State refresh failed: {first_line(e)}")

    async def _publish_watched_states(self) -> None:
        for key in list(self._viewers):
            await self._publish_state(key)

    # ── request plumbing ─────────────────────────────────────────────────────

    async def handle(self, ws: Any, msg_type: str, data: Dict[str, Any]) -> None:
        """Handle one ``mini_browser_*`` message. Never raises (except on
        cancellation); every failure is answered to ``ws`` only."""
        name = _HANDLERS.get(msg_type)
        if name is None:
            logger.debug(
                f"[MINI_BROWSER] Ignoring unknown message {str(msg_type)[:64]!r}"
            )
            return
        if not isinstance(data, dict):
            data = {}
        handler = getattr(self, name)
        await self._guarded(ws, msg_type, data, lambda: handler(ws, data))

    async def _guarded(
        self,
        ws: Any,
        msg_type: str,
        data: Dict[str, Any],
        operation: Callable[[], Awaitable[None]],
    ) -> None:
        secrets = _request_secrets(data)
        try:
            await operation()
        except asyncio.CancelledError:
            raise
        except MiniBrowserError as e:
            logger.debug(f"[MINI_BROWSER] {msg_type} refused: {e.code}")
            self._reply_error(
                ws, msg_type, data, _error_reply(e.code, e.fields, secrets)
            )
        except Exception as e:
            # Type and first line only: a traceback's locals could hold a
            # password typed into a page or sent to the vault.
            detail = _clean_text(first_line(e), secrets)
            logger.error(
                f"[MINI_BROWSER] {msg_type} failed: {type(e).__name__}: {detail}"
            )
            self._reply_error(
                ws,
                msg_type,
                data,
                _error_reply("MINI_BROWSER_INTERNAL", {"detail": detail}, secrets),
            )

    def _background(
        self,
        ws: Any,
        msg_type: str,
        data: Dict[str, Any],
        operation: Callable[[], Awaitable[None]],
    ) -> None:
        """Run a slow request off the socket's message lane, errors answered as usual.

        The task inherits the request's context, so its reply still carries
        the request id."""
        self._spawn(lambda: self._guarded(ws, msg_type, data, operation))

    def _spawn(
        self, make: Callable[[], Awaitable[Any]], *, clean: bool = False
    ) -> asyncio.Task:
        """Run ``make()`` as a tracked task (``clean``: in an empty context)."""
        loop = asyncio.get_running_loop()
        if clean:
            task = contextvars.Context().run(lambda: loop.create_task(make()))
        else:
            task = loop.create_task(make())
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning(
                f"[MINI_BROWSER] Background task failed: {first_line(task.exception())}"
            )

    def _send(self, ws: Any, msg_type: str, data: Dict[str, Any]) -> None:
        """Reply to ``ws`` only; dropped if it is gone (never broadcast)."""
        try:
            self._adapter.send_only_to(ws, {"type": msg_type, "data": data})
        except Exception as e:
            logger.warning(f"[MINI_BROWSER] Could not send {msg_type}: {first_line(e)}")

    def _reply_error(
        self,
        ws: Any,
        msg_type: str,
        data: Dict[str, Any],
        error: Dict[str, str],
    ) -> None:
        session = _optional_session_id(data)
        if msg_type == "mini_browser_navigate":
            self._send(
                ws,
                "mini_browser_nav_result",
                {"sessionId": session, "ok": False, "error": error},
            )
        elif msg_type == "mini_browser_vault_list":
            self._send(
                ws,
                "mini_browser_vault_list",
                {"entries": [], "status": _public_status(None), "error": error},
            )
        elif msg_type.startswith("mini_browser_vault_"):
            self._send(
                ws,
                "mini_browser_vault_result",
                {
                    "op": msg_type[len("mini_browser_vault_") :],
                    "ok": False,
                    "error": error,
                },
            )
        else:
            self._send(
                ws,
                "mini_browser_event",
                {
                    "kind": "error",
                    "sessionId": session,
                    "level": _level(error.get("code", "")),
                    "code": error.get("code"),
                    "title": error.get("title"),
                    "message": error.get("message"),
                },
            )

    def _running_host(self) -> Any:
        host = _host_if_started()
        if host is None:
            raise MiniBrowserError("MINI_BROWSER_NOT_RUNNING")
        return host

    async def _start_host(self) -> Any:
        """The browser host, started if needed (its thread, not Chromium).

        Starting waits for the host thread to come up, so it happens on a
        worker thread, never on the UI loop. A host started here after
        panels subscribed learns right away which browsers are watched.
        """
        host = _host_if_started()
        if host is not None:
            return host
        host = await asyncio.to_thread(_get_host)
        for key in list(self._viewers):
            self._sync_streaming(key)
        return host

    # ── handlers: viewers and lifecycle ──────────────────────────────────────

    async def _handle_subscribe(self, ws: Any, data: Dict[str, Any]) -> None:
        """The chat's browser panel opened: watch that session's browser, and
        turn the browser on."""
        key = _session_id(data)
        if self._adapter.client_channel(ws) is None:
            return  # the socket is already gone
        first_viewer = self._add_viewer(ws, key)
        state = await self._state_snapshot(key)
        if state.get("status") != "ready":
            # Until the live page is back, the panel shows where the browser
            # left off (or nothing: an earlier picture may be out of date).
            last_frame = await asyncio.to_thread(_last_frame, key)
            self._send(ws, "mini_browser_last_frame", last_frame)
        if state.get("status") == "stopped":
            # Opening the panel turns the browser on (below): say so at once.
            state = {**state, "status": "starting", "error": None}
        self._send(ws, "mini_browser_state", state)
        host = await self._start_host()
        if not self._watches(ws, key):
            return  # the panel closed meanwhile
        if first_viewer:
            self._sync_streaming(key)
        self._submit(
            host, functools.partial(_on_existing, key, _push_frame), "push_frame_now"
        )
        self._spawn(lambda: self._open_browser(ws, host, key))

    async def _open_browser(self, ws: Any, host: Any, key: str) -> None:
        """Start session ``key``'s browser for its panel. A failure is shown in
        the panel (the state names it), not as a separate error."""
        error: Optional[Dict[str, str]] = None
        try:
            await host.call(key, lambda core: core.ensure_started())
        except asyncio.CancelledError:
            raise
        except MiniBrowserError as e:
            logger.debug(f"[MINI_BROWSER] Browser of {key} not started: {e.code}")
            error = _error_reply(e.code, e.fields)
        except Exception as e:
            logger.warning(
                f"[MINI_BROWSER] Browser of {key} not started: {type(e).__name__}"
            )
            error = _error_reply("MINI_BROWSER_INTERNAL", {"detail": first_line(e)})
        await self._publish_state(key, ws, error)

    async def _handle_unsubscribe(self, ws: Any, data: Dict[str, Any]) -> None:
        self._drop_viewer(ws, _session_id(data))

    async def _handle_activity_query(self, ws: Any, data: Dict[str, Any]) -> None:
        """Which session browsers run and which have an agent browsing (a
        client that just connected; updates follow as they happen)."""
        host = _host_if_started()
        sessions: List[Dict[str, Any]] = []
        if host is not None:
            sessions = await asyncio.wait_for(
                host.call_fleet(_activity), _STATE_TIMEOUT_S
            )
        self._send(
            ws, "mini_browser_activity", {"sessions": sessions, "snapshot": True}
        )

    async def _handle_start(self, ws: Any, data: Dict[str, Any]) -> None:
        key = _session_id(data)
        host = await self._start_host()

        async def start() -> None:
            try:
                await host.call(key, lambda core: core.start())
            except Exception:
                await self._publish_state(key, ws)  # e.g. status "error" + the reason
                raise
            await self._publish_state(key, ws)

        self._background(ws, "mini_browser_start", data, start)

    async def _handle_shutdown(self, ws: Any, data: Dict[str, Any]) -> None:
        """Close one session's browser (its panel's Close button)."""
        key = _session_id(data)
        host = _host_if_started()
        # Input still on its way to the closing browser has nowhere to go.
        for queue in self._input_queues.values():
            queue.drop_session(key)
        try:
            if host is not None:
                await host.call_fleet(functools.partial(_on_existing, key, _close_core))
        finally:
            await self._publish_state(key, ws)

    async def _handle_install(self, ws: Any, data: Dict[str, Any]) -> None:
        if self._installing:
            logger.info("[MINI_BROWSER] Chromium install already running")
            return
        self._installing = True
        try:
            await self._publish_watched_states()  # status "installing"
            logger.info("[MINI_BROWSER] Installing Chromium")
            ok, detail = await _in_daemon_thread(_run_install, self._install_log)
        except Exception as e:
            ok, detail = False, first_line(e)
        finally:
            self._installing = False
        if ok:
            logger.info("[MINI_BROWSER] Chromium installed")
            host = _host_if_started()
            if host is not None:
                try:
                    await host.call_fleet(_clear_launch_errors)
                except Exception as e:
                    logger.debug(f"[MINI_BROWSER] Status reset failed: {first_line(e)}")
            done: Dict[str, Any] = {"done": True, "ok": True}
        else:
            logger.warning(f"[MINI_BROWSER] Chromium install failed: {detail}")
            done = {
                "done": True,
                "ok": False,
                "error": _error_reply(
                    "MINI_BROWSER_INSTALL_FAILED", {"detail": detail or "unknown error"}
                ),
            }
        self._send_to_viewers(None, "mini_browser_install_progress", done)
        if ws not in self._watching:
            self._send(ws, "mini_browser_install_progress", done)
        await self._publish_watched_states()

    def _install_log(self, line: str) -> None:
        """Install output (worker thread) -> viewers' progress panel."""
        text = str(line or "").strip()
        if text:
            self.post("install", {"line": text[:_MAX_INSTALL_LINE_CHARS]})

    # ── handlers: browsing ───────────────────────────────────────────────────

    async def _handle_navigate(self, ws: Any, data: Dict[str, Any]) -> None:
        key = _session_id(data)
        tab_id = _short_id(data.get("tabId"), "tabId", required=False)
        text = _url_text(data.get("url"), required=True)
        host = await self._start_host()

        async def navigate() -> None:
            await host.call(key, lambda core: core.ui_navigate(tab_id, text))
            self._send(ws, "mini_browser_nav_result", {"sessionId": key, "ok": True})

        self._background(ws, "mini_browser_navigate", data, navigate)

    async def _handle_history(self, ws: Any, data: Dict[str, Any]) -> None:
        key = _session_id(data)
        tab_id = _short_id(data.get("tabId"), "tabId", required=False)
        action = data.get("action")
        if action not in _HISTORY_ACTIONS:
            raise _invalid("action must be back, forward, reload or stop.")
        host = self._running_host()
        self._background(
            ws,
            "mini_browser_history",
            data,
            lambda: host.call(key, lambda core: core.ui_history(tab_id, action)),
        )

    async def _handle_tab(self, ws: Any, data: Dict[str, Any]) -> None:
        key = _session_id(data)
        action = data.get("action")
        if action == "new":
            url = _url_text(data.get("url"), required=False)
            host = await self._start_host()
            self._background(
                ws,
                "mini_browser_tab",
                data,
                lambda: host.call(key, lambda core: core.ui_new_tab(url)),
            )
        elif action == "switch":
            tab_id = _required_id(data.get("tabId"), "tabId")
            await self._running_host().call(
                key, lambda core: core.ui_switch_tab(tab_id)
            )
        elif action == "close":
            tab_id = _required_id(data.get("tabId"), "tabId")
            host = self._running_host()
            # Input queued for a tab that is closing would only fail.
            for queue in self._input_queues.values():
                queue.drop_tab(key, tab_id)
            await host.call(key, lambda core: core.ui_close_tab(tab_id))
        else:
            raise _invalid("action must be new, switch or close.")

    async def _handle_input(self, ws: Any, data: Dict[str, Any]) -> None:
        """Validate one live-view event and queue it for its browser.

        Returns as soon as it is queued: the socket's drain task applies the
        events in order (see _InputQueue), so a lagging page never holds up
        this lane, and its moves and wheel steps are coalesced meanwhile.
        """
        event = _input_event(data.get("event"))
        if event is None:
            return  # an unknown kind of input is ignored
        key = _session_id(data)
        tab_id = _required_id(data.get("tabId"), "tabId")
        if _host_if_started() is None:
            return  # no browser to type into
        if event["kind"] == "cut":
            event = {**event, "requestId": _cut_key(ws, event["requestId"])}
        self._queue_input(ws, key, tab_id, event)

    def _queue_input(
        self, ws: Any, key: str, tab_id: str, event: Dict[str, Any]
    ) -> None:
        queue = self._input_queues.get(ws)
        if queue is None:
            queue = self._input_queues[ws] = _InputQueue()
        if not _coalesce(queue.items, key, tab_id, event):
            if len(queue.items) >= _MAX_QUEUED_INPUT:
                # The page stopped taking input; tell the user once per backlog.
                if not queue.overflowed:
                    queue.overflowed = True
                    logger.warning(
                        "[MINI_BROWSER] Live input backlog is full; dropping input "
                        "until the page catches up"
                    )
                    self._reply_error(
                        ws,
                        "mini_browser_input",
                        {"sessionId": key},
                        _error_reply("MINI_BROWSER_PAGE_UNRESPONSIVE"),
                    )
                return
            queue.items.append((key, tab_id, event))
        if queue.task is None or queue.task.done():
            queue.task = self._spawn(lambda: self._drain_input(ws, queue), clean=True)

    async def _drain_input(self, ws: Any, queue: _InputQueue) -> None:
        """Apply a socket's queued input one event at a time, in order."""
        while queue.items and self._input_queues.get(ws) is queue:
            key, tab_id, event = queue.items.popleft()
            host = _host_if_started()
            if host is None:
                queue.items.clear()  # the browser host is gone
                return
            queue.current = (key, tab_id)
            try:
                await self._guarded(
                    ws,
                    "mini_browser_input",
                    # Its text is scrubbed from any error.
                    {"event": event, "sessionId": key},
                    lambda: self._apply_input(host, key, tab_id, event),
                )
            finally:
                queue.current = None
            if len(queue.items) <= _MAX_QUEUED_INPUT // 2:
                queue.overflowed = False

    @staticmethod
    async def _apply_input(
        host: Any, key: str, tab_id: str, event: Dict[str, Any]
    ) -> None:
        try:
            await host.call(key, lambda core: core.ui_input(tab_id, event))
        except MiniBrowserError as e:
            if (event["kind"], event.get("action")) not in _CONTINUOUS_INPUT:
                raise
            logger.debug(f"[MINI_BROWSER] {event['kind']} input dropped: {e.code}")

    async def _settle_input(
        self, ws: Any, key: str, tab_id: str, *, drop_late: bool
    ) -> None:
        """Wait (at most _INPUT_SETTLE_S) until the input ``ws`` queued for
        ``tab_id`` has been applied, so a request that must follow it (copy
        the selection it made, hand the tab back) does. ``drop_late``: input
        still queued after that is dropped, never applied afterwards."""
        queue = self._input_queues.get(ws)
        if queue is None:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _INPUT_SETTLE_S
        while queue.pending_for(key, tab_id) and self._input_queues.get(ws) is queue:
            if loop.time() >= deadline:
                if drop_late:
                    dropped = queue.drop_tab(key, tab_id)
                    if dropped:
                        logger.info(
                            f"[MINI_BROWSER] Dropped {dropped} input event(s) the "
                            "page did not take in time"
                        )
                return
            await asyncio.sleep(_INPUT_SETTLE_POLL_S)

    async def _handle_resize(self, ws: Any, data: Dict[str, Any]) -> None:
        key = _session_id(data)
        width = _int_in(data.get("width"), "width", _VIEWPORT_WIDTH)
        height = _int_in(data.get("height"), "height", _VIEWPORT_HEIGHT)
        # Starts the host (not Chromium) so the first launch already has the size.
        host = await self._start_host()
        await host.call(key, lambda core: core.set_viewport(width, height))

    async def _handle_view(self, ws: Any, data: Dict[str, Any]) -> None:
        key = _session_id(data)
        tab_id = _short_id(data.get("tabId"), "tabId", required=False)
        follow = data.get("follow")
        if follow is not None:
            follow = _flag(follow, "follow")
        host = _host_if_started()
        if host is not None:  # nothing to view before the browser exists
            await host.call_fleet(
                functools.partial(
                    _on_existing, key, lambda core: core.ui_view(tab_id, follow)
                )
            )

    async def _handle_control(self, ws: Any, data: Dict[str, Any]) -> None:
        key = _session_id(data)
        tab_id = _required_id(data.get("tabId"), "tabId")
        take = _flag(data.get("take"), "take")
        host = self._running_host()
        if not take:
            # Control runs in its own lane: let the user's last keystrokes and
            # clicks land before the agent gets the tab back (otherwise they
            # would arrive afterwards and take control again).
            await self._settle_input(ws, key, tab_id, drop_late=True)
        await host.call(key, lambda core: core.ui_control(tab_id, take))

    async def _handle_adblock(self, ws: Any, data: Dict[str, Any]) -> None:
        """Ad blocking on/off: one setting for every session's browser."""
        enabled = _flag(data.get("enabled"), "enabled")
        host = _host_if_started()
        if host is not None:
            await host.call_fleet(lambda fleet: fleet.set_adblock(enabled))
        else:
            await asyncio.to_thread(_save_setting, "adblock", enabled)
        await self._publish_watched_states()

    async def _handle_copy(self, ws: Any, data: Dict[str, Any]) -> None:
        key = _session_id(data)
        tab_id = _required_id(data.get("tabId"), "tabId")
        # Echoed back, so the page matches the reply to its request (a cut
        # deletes the selection only once ITS copy has arrived).
        request_id = _short_id(data.get("requestId"), "requestId", required=False)
        # The first half of a cut: the delete follows as a "cut" input event
        # with the same requestId, once the text is on the user's clipboard.
        cut_request = (
            _cut_key(ws, request_id)
            if request_id is not None and data.get("cut") is True
            else None
        )
        host = self._running_host()
        # The selection may come from input still on its way (a drag, Ctrl+A).
        await self._settle_input(ws, key, tab_id, drop_late=False)
        text = await host.call(
            key, lambda core: _copy_selection(core, tab_id, cut_request)
        )
        reply: Dict[str, Any] = {"text": text}
        if request_id is not None:
            reply["requestId"] = request_id
        self._send(ws, "mini_browser_clipboard", reply)

    # ── handlers: password vault (replies to the requester only) ────────────

    async def _handle_vault_list(self, ws: Any, data: Dict[str, Any]) -> None:
        status, entries = await _vault_call(
            lambda vault: (vault.status(), vault.list_entries())
        )
        self._send(
            ws,
            "mini_browser_vault_list",
            {"entries": _public_entries(entries), "status": _public_status(status)},
        )

    async def _handle_vault_add(self, ws: Any, data: Dict[str, Any]) -> None:
        site = _vault_text(data, "site", _MAX_VAULT_SITE_CHARS, required=True)
        username = _vault_text(
            data, "username", _MAX_VAULT_USERNAME_CHARS, required=True
        )
        password = _vault_text(
            data, "password", _MAX_VAULT_PASSWORD_CHARS, required=True
        )
        label = _vault_text(data, "label", _MAX_VAULT_LABEL_CHARS, required=False) or ""
        try:
            await _vault_call(
                lambda vault: vault.add_entry(site, username, password, label),
                secrets=(password,),
            )
        finally:
            _notify_vault_changed()
        self._send(ws, "mini_browser_vault_result", {"op": "add", "ok": True})

    async def _handle_vault_update(self, ws: Any, data: Dict[str, Any]) -> None:
        entry_id = _short_id(data.get("id"), "id", required=True)
        site = _vault_text(data, "site", _MAX_VAULT_SITE_CHARS, required=False)
        username = _vault_text(
            data, "username", _MAX_VAULT_USERNAME_CHARS, required=False
        )
        password = _vault_text(
            data, "password", _MAX_VAULT_PASSWORD_CHARS, required=False
        )
        label = _vault_text(data, "label", _MAX_VAULT_LABEL_CHARS, required=False)
        try:
            await _vault_call(
                lambda vault: vault.update_entry(
                    entry_id,
                    site=site,
                    username=username,
                    password=password or None,  # empty = keep the saved one
                    label=label,
                ),
                secrets=(password,) if password else (),
            )
        finally:
            _notify_vault_changed()
        self._send(ws, "mini_browser_vault_result", {"op": "update", "ok": True})

    async def _handle_vault_delete(self, ws: Any, data: Dict[str, Any]) -> None:
        entry_id = _short_id(data.get("id"), "id", required=True)
        try:
            # Deleting an entry that is already gone is not an error.
            await _vault_call(lambda vault: vault.delete_entry(entry_id))
        finally:
            _notify_vault_changed()
        self._send(ws, "mini_browser_vault_result", {"op": "delete", "ok": True})

    async def _handle_vault_reset(self, ws: Any, data: Dict[str, Any]) -> None:
        try:
            backup = await _vault_call(lambda vault: vault.reset_unreadable())
        finally:
            _notify_vault_changed()
        logger.warning("[MINI_BROWSER] Unreadable password vault reset by the user")
        self._send(
            ws,
            "mini_browser_vault_result",
            {"op": "reset", "ok": True, "backupPath": str(backup) if backup else None},
        )
