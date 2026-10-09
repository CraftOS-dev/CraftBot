# -*- coding: utf-8 -*-
"""WebSocket side of the Mini Browser page, and the browser's UI sink.

``MiniBrowserWS`` lives in the browser UI adapter, on the UI event loop, and
has three jobs.

**Requests.** ``handle`` takes every ``mini_browser_*`` message from a
browser tab, validates and clamps it, and turns it into a call on the browser
host (``app.mini_browser.host``; the browser itself runs on its own thread)
or on the password vault. A handler never raises: an unhandled error would
be broadcast into every tab's main chat, so each failure is answered to the
requesting socket only, as ``{code, title, message}``. Page loads, history
moves, new tabs and explicit starts run as background tasks, so a slow site
never blocks the socket's message lane. Live-view input is queued per socket
and applied in order by one drain task; while the page lags, mouse moves
coalesce (latest wins) and wheel steps add up, so a hung page never builds a
backlog in front of the user's keystrokes, and closing the browser or taking
and handing back control (their own lanes) never wait behind it. Replies
(``{type, data}``):

- ``mini_browser_navigate`` -> ``mini_browser_nav_result {ok, error?}``
- ``mini_browser_copy`` -> ``mini_browser_clipboard {text}``
- ``mini_browser_vault_list`` -> ``mini_browser_vault_list {entries, status, error?}``
- other vault requests -> ``mini_browser_vault_result {op, ok, error?}``
- subscribe, the ad-block query -> ``mini_browser_state``
- any other failure -> ``mini_browser_event {kind: "error", level, code, title,
  message}``

**Viewers.** Only sockets that subscribed (the Mini Browser page is open)
receive browser state, frames, agent cursor moves, events and install
progress, and the browser streams its screen only while one exists. Passive
messages (subscribe, unsubscribe, the ad-block query, the vault) never start
Chromium; while the browser host has never started, its state is synthesized
here.

**UI sink.** The browser thread publishes through ``bridge.publish``, which
calls ``post`` here; ``post`` hops onto the UI loop in a clean context (no
request id of whatever request happens to be running). Frames are coalesced
into one latest-frame slot, and a socket that is still behind gets no new
frame, so a slow tab never queues a backlog of images in front of its chat.

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
    List,
    Optional,
    Sequence,
    Tuple,
)

from app.logger import logger
from app.mini_browser import ACTION_SET, SESSION_ID, SESSION_TITLE, SKILL_NAME
from app.mini_browser.errors import (
    ERROR_SPECS,
    MiniBrowserError,
    first_line,
    scrub,
    ui_error,
)

__all__ = ["MiniBrowserWS"]

# Bridge message kind -> WebSocket message type.
_MESSAGE_TYPES: Dict[str, str] = {
    "state": "mini_browser_state",
    "frame": "mini_browser_frame",
    "pointer": "mini_browser_pointer",
    "event": "mini_browser_event",
    "install": "mini_browser_install_progress",
}
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


def _lifecycle() -> Any:
    from app.mini_browser import lifecycle

    return lifecycle


def _load_settings() -> Dict[str, Any]:
    from app.config import get_mini_browser_settings

    return get_mini_browser_settings()


def _save_setting(key: str, value: Any) -> None:
    from app.config import set_mini_browser_setting

    set_mini_browser_setting(key, value)


def _preloaded_skills() -> List[str]:
    """[SKILL_NAME] when the Mini Browser skill is installed and enabled."""
    try:
        from app.skill import skill_manager

        skill = skill_manager.get_skill(SKILL_NAME)
    except Exception:
        return []
    if skill is not None and (skill.enabled or getattr(skill, "is_system", False)):
        return [SKILL_NAME]
    return []


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


def _notify_sessions_changed(session_id: str) -> None:
    try:
        from app.ui_layer.events.resource_changes import (
            Resource,
            notify_resource_changed,
        )

        notify_resource_changed(Resource.SESSIONS, [session_id])
    except Exception as e:
        logger.debug(f"[MINI_BROWSER] Session change notice failed: {e}")


def _run_install(log: Callable[[str], None]) -> Tuple[bool, str]:
    """Download Playwright's Chromium (blocking: runs on a worker thread)."""
    from app.provision import default_context
    from app.provision.deps import PlaywrightStage

    result = PlaywrightStage().apply(default_context(), log)
    return bool(result.ok), str(result.detail or "")


# ─────────────────────────────────────────────────────────────────────────────
# Host-loop helpers (run inside host.call on the browser thread)
# ─────────────────────────────────────────────────────────────────────────────


async def _core_state(core: Any) -> Dict[str, Any]:
    return core.state()


async def _copy_selection(core: Any, tab_id: str) -> str:
    """The tab's selected text, minus any password autofill typed into it."""
    text = await core.ui_copy_selection(tab_id)
    if not isinstance(text, str):
        return ""
    tab = (getattr(core, "tabs", None) or {}).get(tab_id)
    secrets = list(getattr(tab, "filled_secrets", None) or ())
    return _clean_text(text[:_MAX_CLIPBOARD_CHARS], secrets)


async def _clear_launch_error(core: Any) -> None:
    """After an install, an earlier "browser missing" failure no longer applies."""
    if getattr(core, "status", None) == "error":
        core.status = "stopped"
        core.last_error = None


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
    """One socket's live input that has not reached the browser yet.

    Events are applied one at a time, in arrival order, by a single drain
    task. While the page lags behind, continuous input is coalesced at the
    tail (see :func:`_coalesce`), so a slow or hung page costs a few queued
    events instead of a backlog of hover moves that would hold up keystrokes.
    """

    __slots__ = ("items", "task", "current", "overflowed")

    def __init__(self) -> None:
        self.items: Deque[Tuple[str, Dict[str, Any]]] = deque()
        self.task: Optional[asyncio.Task] = None
        self.current: Optional[str] = None  # tab of the event being applied
        self.overflowed = False

    def pending_for(self, tab_id: str) -> bool:
        """Whether input for ``tab_id`` is queued or being applied."""
        return self.current == tab_id or any(tab == tab_id for tab, _ in self.items)

    def drop_tab(self, tab_id: str) -> int:
        """Forget the queued (not yet applied) input of ``tab_id``."""
        kept = [(tab, event) for tab, event in self.items if tab != tab_id]
        dropped = len(self.items) - len(kept)
        if dropped:
            self.items = deque(kept)
        return dropped


def _coalesce(
    items: Deque[Tuple[str, Dict[str, Any]]], tab_id: str, event: Dict[str, Any]
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
    last_tab, last = items[-1]
    if last_tab != tab_id or last["kind"] != event["kind"]:
        return False
    if event["kind"] == "mouse":
        if event["action"] != "move" or last["action"] != "move":
            return False
        items[-1] = (tab_id, event)
        return True
    if event["kind"] == "wheel":
        dx = last["dx"] + event["dx"]
        dy = last["dy"] + event["dy"]
        if abs(dx) > _MAX_WHEEL_DELTA or abs(dy) > _MAX_WHEEL_DELTA:
            return False
        items[-1] = (tab_id, {**event, "dx": dx, "dy": dy})
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# The handler
# ─────────────────────────────────────────────────────────────────────────────


class MiniBrowserWS:
    """Mini Browser requests, viewers and UI sink for one browser adapter.

    Everything except ``has_viewers`` and ``post`` runs on the UI loop;
    those two are called from the browser thread.
    """

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Subscribed sockets (UI loop only) and a count other threads may read.
        self._viewers: set = set()
        self._viewer_count = 0
        # Latest-frame slot, filled by the browser thread, drained on the UI loop.
        self._frame_lock = threading.Lock()
        self._frame: Optional[Dict[str, Any]] = None
        self._frame_scheduled = False
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
        close Chromium (it holds a lock on its profile). Never raises."""
        try:
            _bridge().unregister_ui_sink(self)
        except Exception as e:
            logger.debug(f"[MINI_BROWSER] Sink unregister failed: {first_line(e)}")
        self._loop = None
        with self._frame_lock:
            self._frame = None
            self._frame_scheduled = False
        self._viewers.clear()
        self._viewer_count = 0
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
        """A socket closed: it is no longer a viewer, and its input that has
        not reached the browser yet is dropped. Never raises."""
        try:
            queue = self._input_queues.pop(ws, None)
            if queue is not None:
                queue.items.clear()
            self._drop_viewer(ws)
        except Exception as e:
            logger.debug(f"[MINI_BROWSER] forget failed: {first_line(e)}")

    # ── UI sink (thread-safe) ────────────────────────────────────────────────

    def has_viewers(self) -> bool:
        """Whether any socket is watching the Mini Browser. Thread-safe."""
        return self._viewer_count > 0

    def post(self, kind: str, payload: Dict[str, Any]) -> None:
        """Deliver a bridge message to the viewers. Thread-safe, never blocks.

        ``kind`` is one of state / frame / pointer / event / install. Frames
        are coalesced: only the newest one waiting for the UI loop is sent.
        """
        loop = self._loop
        if (
            loop is None
            or self._viewer_count == 0
            or kind not in _MESSAGE_TYPES
            or not isinstance(payload, dict)
        ):
            return
        data = dict(payload)  # the producer may reuse its dict
        context = contextvars.Context()
        try:
            if kind == "frame":
                with self._frame_lock:
                    self._frame = data
                    if self._frame_scheduled:
                        return
                    self._frame_scheduled = True
                try:
                    loop.call_soon_threadsafe(self._flush_frame, context=context)
                except RuntimeError:
                    with self._frame_lock:
                        self._frame_scheduled = False
                        self._frame = None
                    raise
            else:
                loop.call_soon_threadsafe(self._deliver, kind, data, context=context)
        except RuntimeError:
            pass  # the UI loop is closed (shutting down): nobody to deliver to

    def _flush_frame(self) -> None:
        with self._frame_lock:
            data, self._frame = self._frame, None
            self._frame_scheduled = False
        if data is not None:
            self._deliver("frame", data)

    def _deliver(self, kind: str, data: Dict[str, Any]) -> None:
        """UI loop: send one bridge message to every viewer."""
        try:
            if kind == "state":
                data = self._overlay_state(data)
            self._send_to_viewers(_MESSAGE_TYPES[kind], data, _MAX_PENDING.get(kind))
        except Exception as e:
            logger.warning(f"[MINI_BROWSER] {kind} delivery failed: {first_line(e)}")

    def _send_to_viewers(
        self, msg_type: str, data: Dict[str, Any], max_pending: Optional[int] = None
    ) -> None:
        """Queue one message for each subscribed socket (never via _broadcast)."""
        if not self._viewers:
            return
        try:
            text = json.dumps({"type": msg_type, "data": data}, allow_nan=False)
        except (TypeError, ValueError) as e:
            logger.warning(f"[MINI_BROWSER] Dropped an unserializable {msg_type}: {e}")
            return
        channels = getattr(self._adapter, "_channels", {})
        for ws in list(self._viewers):
            channel = channels.get(ws)
            if channel is None or channel.closed:
                self._drop_viewer(ws)
            elif max_pending is None or channel.pending <= max_pending:
                channel.send_text(text)

    # ── viewers and streaming ────────────────────────────────────────────────

    def _channel(self, ws: Any) -> Any:
        channel = (
            getattr(self._adapter, "_channels", {}).get(ws) if ws is not None else None
        )
        return None if channel is None or channel.closed else channel

    def _drop_viewer(self, ws: Any) -> None:
        if ws not in self._viewers:
            return
        self._viewers.discard(ws)
        self._viewer_count = len(self._viewers)
        if not self._viewers:
            self._sync_streaming()

    def _sync_streaming(self) -> None:
        """Tell the browser to stream iff someone is watching (read when it runs)."""
        host = _host_if_started()
        if host is not None:
            self._submit(
                host,
                lambda core: core.set_streaming(self.has_viewers()),
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

    # ── the dedicated chat session ───────────────────────────────────────────

    def _session_manager(self) -> Any:
        controller = getattr(self._adapter, "_controller", None)
        agent = getattr(controller, "agent", None)
        return getattr(agent, "session_manager", None)

    def _session_exists(self) -> bool:
        manager = self._session_manager()
        try:
            return manager is not None and manager.get(SESSION_ID) is not None
        except Exception:
            return False

    def ensure_session(self) -> Any:
        """The dedicated Mini Browser chat session, created if it is missing.

        Mirrors ``AgentAppManager.ensure_project_session``: a fixed id, the
        browser's action set (and its skill, when installed and enabled)
        preloaded, persisted by the SessionManager — so after a restart it is
        restored, not recreated. Clients learn about a new session from a
        ``session_created`` broadcast (the sessions store upserts it) and a
        ``sessions`` resource change. Idempotent; None without a session
        manager.
        """
        manager = self._session_manager()
        if manager is None:
            return None
        session = manager.get(SESSION_ID)
        if session is not None:
            return session

        from agent_core.core.session import SessionType

        session = manager.create_session(
            session_type=SessionType.MINI_BROWSER,
            title=SESSION_TITLE,
            session_id=SESSION_ID,
            action_sets=[ACTION_SET],
            selected_skills=_preloaded_skills(),
        )
        logger.info(f"[MINI_BROWSER] Created the dedicated session '{session.id}'")
        self._announce_session(session)
        return session

    def _announce_session(self, session: Any) -> None:
        try:
            info = self._adapter._session_info(session)
            message = {
                "type": "session_created",
                "data": {"session": info, "clientId": None},
            }
            # Clean context: the broadcast must not carry this request's id.
            self._spawn(lambda: self._adapter._broadcast(message), clean=True)
        except Exception as e:
            logger.warning(
                f"[MINI_BROWSER] Could not announce the session: {first_line(e)}"
            )
        _notify_sessions_changed(session.id)

    # ── state ────────────────────────────────────────────────────────────────

    def _ui_hosts(self) -> frozenset:
        try:
            return frozenset(self._adapter.ui_hosts)
        except Exception:
            return frozenset()

    def _overlay_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """What only this side knows: the session id (once the session exists)
        and an install in progress."""
        state = dict(state)
        state["sessionId"] = SESSION_ID if self._session_exists() else None
        if self._installing and state.get("status") in ("stopped", "error"):
            state["status"] = "installing"
            state["error"] = None
        return state

    async def _synthesized_state(
        self, error: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """The state of a browser host that is not running (never starts it)."""
        settings = await asyncio.to_thread(_load_settings)
        return {
            "status": "error" if error else "stopped",
            "error": error,
            "sessionId": None,
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

    async def _state_snapshot(self) -> Dict[str, Any]:
        """Current ``mini_browser_state`` payload. Never starts the browser."""
        state: Any = None
        error: Optional[Dict[str, str]] = None
        host = _host_if_started()
        if host is not None:
            try:
                state = await asyncio.wait_for(host.call(_core_state), _STATE_TIMEOUT_S)
            except asyncio.TimeoutError:
                error = _error_reply(
                    "MINI_BROWSER_TIMEOUT",
                    {"what": "The Mini Browser", "seconds": int(_STATE_TIMEOUT_S)},
                )
            except Exception as e:
                error = _error_reply("MINI_BROWSER_INTERNAL", {"detail": first_line(e)})
        if not isinstance(state, dict):
            state = await self._synthesized_state(error)
        return self._overlay_state(state)

    async def _publish_state(self, ws: Any = None) -> None:
        """Send the current state to every viewer (and to ``ws`` if it is not one)."""
        try:
            state = await self._state_snapshot()
            self._send_to_viewers("mini_browser_state", state)
            if ws is not None and ws not in self._viewers:
                self._send(ws, "mini_browser_state", state)
        except Exception as e:
            logger.debug(f"[MINI_BROWSER] State refresh failed: {first_line(e)}")

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
            self._reply_error(ws, msg_type, _error_reply(e.code, e.fields, secrets))
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
            self._adapter._send_only_to(ws, {"type": msg_type, "data": data})
        except Exception as e:
            logger.warning(f"[MINI_BROWSER] Could not send {msg_type}: {first_line(e)}")

    def _reply_error(self, ws: Any, msg_type: str, error: Dict[str, str]) -> None:
        if msg_type == "mini_browser_navigate":
            self._send(ws, "mini_browser_nav_result", {"ok": False, "error": error})
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
        worker thread, never on the UI loop. A host started here after the
        page subscribed learns right away that someone is watching.
        """
        host = _host_if_started()
        if host is not None:
            return host
        host = await asyncio.to_thread(_get_host)
        if self._viewers:
            self._sync_streaming()
        return host

    # ── handlers: viewers and lifecycle ──────────────────────────────────────

    async def _handle_subscribe(self, ws: Any, data: Dict[str, Any]) -> None:
        if self._channel(ws) is None:
            return  # the socket is already gone
        first_viewer = not self._viewers
        self._viewers.add(ws)
        self._viewer_count = len(self._viewers)
        try:
            self.ensure_session()
        except Exception as e:
            logger.warning(f"[MINI_BROWSER] Session not created: {first_line(e)}")
        self._send(ws, "mini_browser_state", await self._state_snapshot())
        host = _host_if_started()
        if host is not None and ws in self._viewers:
            if first_viewer:
                self._sync_streaming()
            self._submit(host, lambda core: core.push_frame_now(), "push_frame_now")

    async def _handle_unsubscribe(self, ws: Any, data: Dict[str, Any]) -> None:
        self._drop_viewer(ws)

    async def _handle_start(self, ws: Any, data: Dict[str, Any]) -> None:
        host = await self._start_host()

        async def start() -> None:
            try:
                await host.call(lambda core: core.start())
            except Exception:
                await self._publish_state(ws)  # e.g. status "error" + the reason
                raise
            await self._publish_state(ws)

        self._background(ws, "mini_browser_start", data, start)

    async def _handle_shutdown(self, ws: Any, data: Dict[str, Any]) -> None:
        host = _host_if_started()
        # Input still on its way to the closing browser has nowhere to go.
        for queue in self._input_queues.values():
            queue.items.clear()
        try:
            if host is not None:
                await host.call(lambda core: core.close())
        finally:
            await self._publish_state(ws)

    async def _handle_install(self, ws: Any, data: Dict[str, Any]) -> None:
        if self._installing:
            logger.info("[MINI_BROWSER] Chromium install already running")
            return
        self._installing = True
        try:
            await self._publish_state(ws)  # status "installing"
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
                    await host.call(_clear_launch_error)
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
        self._send_to_viewers("mini_browser_install_progress", done)
        if ws not in self._viewers:
            self._send(ws, "mini_browser_install_progress", done)
        await self._publish_state(ws)

    def _install_log(self, line: str) -> None:
        """Install output (worker thread) -> viewers' progress panel."""
        text = str(line or "").strip()
        if text:
            self.post("install", {"line": text[:_MAX_INSTALL_LINE_CHARS]})

    # ── handlers: browsing ───────────────────────────────────────────────────

    async def _handle_navigate(self, ws: Any, data: Dict[str, Any]) -> None:
        tab_id = _short_id(data.get("tabId"), "tabId", required=False)
        text = _url_text(data.get("url"), required=True)
        host = await self._start_host()

        async def navigate() -> None:
            await host.call(lambda core: core.ui_navigate(tab_id, text))
            self._send(ws, "mini_browser_nav_result", {"ok": True})

        self._background(ws, "mini_browser_navigate", data, navigate)

    async def _handle_history(self, ws: Any, data: Dict[str, Any]) -> None:
        tab_id = _short_id(data.get("tabId"), "tabId", required=False)
        action = data.get("action")
        if action not in _HISTORY_ACTIONS:
            raise _invalid("action must be back, forward, reload or stop.")
        host = self._running_host()
        self._background(
            ws,
            "mini_browser_history",
            data,
            lambda: host.call(lambda core: core.ui_history(tab_id, action)),
        )

    async def _handle_tab(self, ws: Any, data: Dict[str, Any]) -> None:
        action = data.get("action")
        if action == "new":
            url = _url_text(data.get("url"), required=False)
            host = await self._start_host()
            self._background(
                ws,
                "mini_browser_tab",
                data,
                lambda: host.call(lambda core: core.ui_new_tab(url)),
            )
        elif action == "switch":
            tab_id = _short_id(data.get("tabId"), "tabId", required=True)
            await self._running_host().call(lambda core: core.ui_switch_tab(tab_id))
        elif action == "close":
            tab_id = _short_id(data.get("tabId"), "tabId", required=True)
            host = self._running_host()
            # Input queued for a tab that is closing would only fail.
            for queue in self._input_queues.values():
                queue.drop_tab(tab_id)
            await host.call(lambda core: core.ui_close_tab(tab_id))
        else:
            raise _invalid("action must be new, switch or close.")

    async def _handle_input(self, ws: Any, data: Dict[str, Any]) -> None:
        """Validate one live-view event and queue it for the browser.

        Returns as soon as it is queued: the socket's drain task applies the
        events in order (see _InputQueue), so a lagging page never holds up
        this lane, and its moves and wheel steps are coalesced meanwhile.
        """
        event = _input_event(data.get("event"))
        if event is None:
            return  # an unknown kind of input is ignored
        tab_id = _short_id(data.get("tabId"), "tabId", required=True)
        if _host_if_started() is None:
            return  # no browser to type into
        self._queue_input(ws, tab_id, event)

    def _queue_input(self, ws: Any, tab_id: str, event: Dict[str, Any]) -> None:
        queue = self._input_queues.get(ws)
        if queue is None:
            queue = self._input_queues[ws] = _InputQueue()
        if not _coalesce(queue.items, tab_id, event):
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
                        _error_reply("MINI_BROWSER_PAGE_UNRESPONSIVE"),
                    )
                return
            queue.items.append((tab_id, event))
        if queue.task is None or queue.task.done():
            queue.task = self._spawn(lambda: self._drain_input(ws, queue), clean=True)

    async def _drain_input(self, ws: Any, queue: _InputQueue) -> None:
        """Apply a socket's queued input one event at a time, in order."""
        while queue.items and self._input_queues.get(ws) is queue:
            tab_id, event = queue.items.popleft()
            host = _host_if_started()
            if host is None:
                queue.items.clear()  # the browser host is gone
                return
            queue.current = tab_id
            try:
                await self._guarded(
                    ws,
                    "mini_browser_input",
                    {"event": event},  # its text is scrubbed from any error
                    lambda: self._apply_input(host, tab_id, event),
                )
            finally:
                queue.current = None
            if len(queue.items) <= _MAX_QUEUED_INPUT // 2:
                queue.overflowed = False

    @staticmethod
    async def _apply_input(host: Any, tab_id: str, event: Dict[str, Any]) -> None:
        try:
            await host.call(lambda core: core.ui_input(tab_id, event))
        except MiniBrowserError as e:
            if (event["kind"], event.get("action")) not in _CONTINUOUS_INPUT:
                raise
            logger.debug(f"[MINI_BROWSER] {event['kind']} input dropped: {e.code}")

    async def _settle_input(self, ws: Any, tab_id: str, *, drop_late: bool) -> None:
        """Wait (at most _INPUT_SETTLE_S) until the input ``ws`` queued for
        ``tab_id`` has been applied, so a request that must follow it (copy
        the selection it made, hand the tab back) does. ``drop_late``: input
        still queued after that is dropped, never applied afterwards."""
        queue = self._input_queues.get(ws)
        if queue is None:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _INPUT_SETTLE_S
        while queue.pending_for(tab_id) and self._input_queues.get(ws) is queue:
            if loop.time() >= deadline:
                if drop_late:
                    dropped = queue.drop_tab(tab_id)
                    if dropped:
                        logger.info(
                            f"[MINI_BROWSER] Dropped {dropped} input event(s) the "
                            "page did not take in time"
                        )
                return
            await asyncio.sleep(_INPUT_SETTLE_POLL_S)

    async def _handle_resize(self, ws: Any, data: Dict[str, Any]) -> None:
        width = _int_in(data.get("width"), "width", _VIEWPORT_WIDTH)
        height = _int_in(data.get("height"), "height", _VIEWPORT_HEIGHT)
        # Starts the host (not Chromium) so the first launch already has the size.
        host = await self._start_host()
        await host.call(lambda core: core.set_viewport(width, height))

    async def _handle_view(self, ws: Any, data: Dict[str, Any]) -> None:
        tab_id = _short_id(data.get("tabId"), "tabId", required=False)
        follow = data.get("follow")
        if follow is not None:
            follow = _flag(follow, "follow")
        host = _host_if_started()
        if host is not None:  # nothing to view before the browser exists
            await host.call(lambda core: core.ui_view(tab_id, follow))

    async def _handle_control(self, ws: Any, data: Dict[str, Any]) -> None:
        tab_id = _short_id(data.get("tabId"), "tabId", required=True)
        take = _flag(data.get("take"), "take")
        host = self._running_host()
        if not take:
            # Control runs in its own lane: let the user's last keystrokes and
            # clicks land before the agent gets the tab back (otherwise they
            # would arrive afterwards and take control again).
            await self._settle_input(ws, tab_id, drop_late=True)
        await host.call(lambda core: core.ui_control(tab_id, take))

    async def _handle_adblock(self, ws: Any, data: Dict[str, Any]) -> None:
        enabled = data.get("enabled")
        if enabled is None:  # a query: answer without starting anything
            self._send(ws, "mini_browser_state", await self._state_snapshot())
            return
        enabled = _flag(enabled, "enabled")
        host = _host_if_started()
        if host is not None:
            await host.call(lambda core: core.set_adblock(enabled))
        else:
            await asyncio.to_thread(_save_setting, "adblock", enabled)
        await self._publish_state(ws)

    async def _handle_copy(self, ws: Any, data: Dict[str, Any]) -> None:
        tab_id = _short_id(data.get("tabId"), "tabId", required=True)
        host = self._running_host()
        # The selection may come from input still on its way (a drag, Ctrl+A).
        await self._settle_input(ws, tab_id, drop_late=False)
        text = await host.call(lambda core: _copy_selection(core, tab_id))
        self._send(ws, "mini_browser_clipboard", {"text": text})

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
