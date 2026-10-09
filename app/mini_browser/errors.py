"""Mini Browser error codes, structured error builders and secret scrubbing.

``ERROR_SPECS`` is the single source of truth for every Mini Browser error.
``app/errors/codebook.py`` registers these specs into the app codebook, so
``make_error(code)`` works for them like for any other app error.

Action results use :func:`action_error`; UI replies use :func:`ui_error`.
Both always go through :func:`scrub` so a password can never leak through an
error message.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

# code -> (category, severity, title, message_template)
# category values come from agent_core.core.errors.ErrorCategory; severity from
# Severity. Templates may use {detail} (redacted by make_error) and other
# named fields passed by the caller.
ERROR_SPECS: Dict[str, Tuple[str, str, str, str]] = {
    "MINI_BROWSER_PLAYWRIGHT_MISSING": (
        "config",
        "error",
        "Browser engine not installed",
        "The Mini Browser needs the Playwright package, which is not installed.",
    ),
    "MINI_BROWSER_CHROMIUM_MISSING": (
        "config",
        "error",
        "Browser not installed",
        "The Mini Browser's Chromium is not installed yet. Install it from the "
        "Mini Browser page, or run `python -m playwright install chromium`.",
    ),
    "MINI_BROWSER_PROFILE_IN_USE": (
        "config",
        "error",
        "Browser profile in use",
        "The Mini Browser profile is already in use by another CraftBot window. "
        "Close the other window and try again.",
    ),
    "MINI_BROWSER_LAUNCH_FAILED": (
        "internal",
        "error",
        "Browser failed to start",
        "The Mini Browser could not start: {detail}",
    ),
    "MINI_BROWSER_NOT_RUNNING": (
        "not_found",
        "warning",
        "Browser not running",
        "The Mini Browser is not running.",
    ),
    "MINI_BROWSER_NAVIGATION_FAILED": (
        "connection",
        "error",
        "Page failed to load",
        "Could not open {url}: {detail}",
    ),
    "MINI_BROWSER_BLOCKED_URL": (
        "permission",
        "warning",
        "Address blocked",
        "The Mini Browser does not open this address: {reason}",
    ),
    "MINI_BROWSER_INVALID_INPUT": (
        "validation",
        "warning",
        "Invalid request",
        "{detail}",
    ),
    "MINI_BROWSER_ELEMENT_NOT_FOUND": (
        "not_found",
        "warning",
        "Element not found",
        "Element {element_id} is not on the page any more. Use the fresh element "
        "list in this result (ids change every time the page is observed).",
    ),
    "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE": (
        "validation",
        "warning",
        "Element not usable",
        "Element {element_id} could not be used: {detail}",
    ),
    "MINI_BROWSER_PAGE_UNRESPONSIVE": (
        "server",
        "warning",
        "Page not responding",
        "The page did not respond in time. Try again, reload, or open another tab.",
    ),
    "MINI_BROWSER_TAB_NOT_FOUND": (
        "not_found",
        "warning",
        "Tab not found",
        "There is no tab {tab}. Use mini_browser_tabs with action='list'.",
    ),
    "MINI_BROWSER_TAB_OWNED": (
        "permission",
        "warning",
        "Tab belongs to another agent",
        "Tab {tab} is being used by another agent ({owner}). Open your own tab "
        "with mini_browser_tabs action='new'.",
    ),
    "MINI_BROWSER_TOO_MANY_TABS": (
        "validation",
        "warning",
        "Too many tabs",
        "You already have {count} tabs open. Close one with mini_browser_tabs "
        "action='close' first.",
    ),
    "MINI_BROWSER_USER_IN_CONTROL": (
        "permission",
        "info",
        "User is in control",
        "The user has taken control of this tab. Wait for them to hand it back "
        "(mini_browser_wait with for_user=true) or ask them what to do.",
    ),
    "MINI_BROWSER_STOPPED": (
        "permission",
        "info",
        "Stopped",
        "The user stopped this run, so the Mini Browser refused the action.",
    ),
    "MINI_BROWSER_TIMEOUT": (
        "connection",
        "warning",
        "Timed out",
        "{what} did not finish within {seconds}s.",
    ),
    "MINI_BROWSER_NO_SAVED_LOGIN": (
        "not_found",
        "warning",
        "No saved login",
        "No saved login matches {site}. Ask the user to add one in the Mini "
        "Browser's Passwords panel, or to sign in themselves in the live view.",
    ),
    "MINI_BROWSER_LOGIN_FAILED": (
        "validation",
        "warning",
        "Sign-in form not filled",
        "{detail}",
    ),
    "MINI_BROWSER_UPLOAD_DENIED": (
        "permission",
        "warning",
        "Upload not allowed",
        "Only files inside the agent workspace can be uploaded ({path}).",
    ),
    "MINI_BROWSER_VAULT_UNREADABLE": (
        "permission",
        "error",
        "Password vault unreadable",
        "The saved-password vault exists but cannot be decrypted (missing or "
        "changed key). Nothing was overwritten. You can reset it from the "
        "Passwords panel — the unreadable file is kept as a backup.",
    ),
    "MINI_BROWSER_VAULT_INVALID": (
        "validation",
        "warning",
        "Invalid login details",
        "{detail}",
    ),
    "MINI_BROWSER_VAULT_IO": (
        "permission",
        "error",
        "Password vault error",
        "The password vault could not be saved: {detail}",
    ),
    "MINI_BROWSER_INSTALL_FAILED": (
        "internal",
        "error",
        "Browser install failed",
        "Installing Chromium failed: {detail}",
    ),
    "MINI_BROWSER_INTERNAL": (
        "internal",
        "error",
        "Mini Browser error",
        "Something went wrong in the Mini Browser: {detail}",
    ),
}


class MiniBrowserError(Exception):
    """An expected, user-presentable Mini Browser failure.

    ``code`` must be a key of ``ERROR_SPECS``; ``fields`` fill its template.
    """

    def __init__(self, code: str, **fields: Any) -> None:
        if code not in ERROR_SPECS:
            fields = {"detail": f"{code}: {fields}"}
            code = "MINI_BROWSER_INTERNAL"
        self.code = code
        self.fields = fields
        super().__init__(f"{code}: {fields}")


def first_line(exc: BaseException, limit: int = 300) -> str:
    """First line of an exception message, trimmed.

    Playwright errors carry multi-line call logs (and the call log of a
    ``fill`` contains the filled value!), so never return ``str(exc)`` raw.
    """
    text = str(exc) or type(exc).__name__
    line = text.strip().splitlines()[0] if text.strip() else type(exc).__name__
    return line[:limit]


def scrub(text: str, secrets: Iterable[str] = ()) -> str:
    """Replace every occurrence of any secret in ``text`` with a mask."""
    if not text:
        return text
    out = text
    # Longest first so a secret that contains another is masked whole. Very
    # short "secrets" (< 3 chars) are skipped: masking every "a" would make
    # the text unreadable while protecting nothing meaningful.
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        if len(secret) >= 3 and secret in out:
            out = out.replace(secret, "[redacted]")
    return out


def _format(code: str, fields: Dict[str, Any]) -> Tuple[str, str, str]:
    """(category, title, message) for ``code``, preferring the app codebook."""
    try:
        from app.errors.codebook import make_error

        info = make_error(code, **_template_fields(code, fields))
        return info.category.value, info.title, info.message
    except Exception:
        category, _severity, title, template = ERROR_SPECS.get(
            code, ERROR_SPECS["MINI_BROWSER_INTERNAL"]
        )
        try:
            message = template.format(**_template_fields(code, fields))
        except Exception:
            message = template
        return category, title, message


def _template_fields(code: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Fill every placeholder the template needs (missing ones become '')."""
    import string

    template = ERROR_SPECS.get(code, ERROR_SPECS["MINI_BROWSER_INTERNAL"])[3]
    needed = {name for _, name, _, _ in string.Formatter().parse(template) if name}
    out = {name: "" for name in needed}
    out.update({k: v for k, v in fields.items() if k in needed})
    return out


def ui_error(code: str, secrets: Iterable[str] = (), **fields: Any) -> Dict[str, str]:
    """``{code, title, message}`` for WebSocket replies to the UI."""
    _category, title, message = _format(code, fields)
    return {"code": code, "title": title, "message": scrub(message, secrets)}


def action_error(
    code: str,
    secrets: Iterable[str] = (),
    extra: Optional[Dict[str, Any]] = None,
    **fields: Any,
) -> Dict[str, Any]:
    """Standard action failure dict (status/message/error_code/error_category)."""
    category, _title, message = _format(code, fields)
    result: Dict[str, Any] = {
        "status": "error",
        "message": scrub(message, secrets),
        "error_code": code,
        "error_category": category,
    }
    if extra:
        result.update(extra)
    return result


def from_exception(
    exc: MiniBrowserError, secrets: Iterable[str] = ()
) -> Dict[str, Any]:
    """Action failure dict for a raised :class:`MiniBrowserError`."""
    return action_error(exc.code, secrets=secrets, **exc.fields)


def scrub_data(value: Any, secrets: Iterable[str] = ()) -> Any:
    """:func:`scrub` applied to every string inside dicts/lists/tuples.

    Returns a scrubbed copy (containers are rebuilt, other values are kept as
    they are), so a whole action result can be cleaned in one call.
    """
    secret_list = [s for s in secrets if s]
    if not secret_list:
        return value
    return _scrub_value(value, secret_list)


def _scrub_value(value: Any, secrets: list) -> Any:
    if isinstance(value, str):
        return scrub(value, secrets)
    if isinstance(value, dict):
        return {
            (scrub(k, secrets) if isinstance(k, str) else k): _scrub_value(v, secrets)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub_value(v, secrets) for v in value]
    if isinstance(value, tuple):
        return tuple(_scrub_value(v, secrets) for v in value)
    return value
