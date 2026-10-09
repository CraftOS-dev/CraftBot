"""Mini Browser error codes, structured error builders and secret scrubbing.

``ERROR_SPECS`` is the single source of truth for every Mini Browser error.
``app/errors/codebook.py`` registers these specs into the app codebook, so
``make_error(code)`` works for them like for any other app error.

Action results use :func:`action_error`; UI replies use :func:`ui_error`.
Both format the ``ERROR_SPECS`` template directly (never through the
codebook's generic ``redact()``, which mangles the URLs and e-mail addresses
these messages are about) and always go through :func:`scrub`, so a password
can never leak through an error message.

:func:`scrub` masks a secret however it was spelled on the way out: as typed,
form-urlencoded the way Chromium submits a GET form, percent-encoded by a
script, HTML-escaped or JSON-escaped, and percent-encoded in a legacy page
charset (windows-1252, Shift_JIS, ...).
"""

from __future__ import annotations

import functools
import html
import json
import re
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple
from urllib.parse import quote, unquote_plus

# code -> (category, severity, title, message_template)
# category values come from agent_core.core.errors.ErrorCategory; severity from
# Severity. Templates may use {detail} and other named fields passed by the
# caller; they are filled in as they are (then scrubbed of secrets).
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
    "MINI_BROWSER_CLOSED": (
        "not_found",
        "warning",
        "Browser closed",
        "The Mini Browser was closed (by the user, an idle shutdown or a crash), "
        "so this action did not finish and your previous tabs are gone. Navigate "
        "again if the task still needs the browser.",
    ),
    "MINI_BROWSER_TAB_CLOSED": (
        "not_found",
        "warning",
        "Tab closed",
        "This tab was closed while the action was running (by the user or by the "
        "page), so the action did not finish. Your next action uses another of "
        "your tabs or a new one; look at the page with mini_browser_read before "
        "acting.",
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
    "MINI_BROWSER_USER_TAB": (
        "permission",
        "warning",
        "The user's tab",
        "Tab {tab} is the user's own tab. You can switch to it only while the "
        "user is viewing it in the Mini Browser and not using it (or when it is "
        "blank). Open your own tab with mini_browser_tabs action='new', or ask "
        "the user to show you the page.",
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


MASK = "[redacted]"
# Very short "secrets" (< 3 chars) are never masked: masking every "a" would
# make the text unreadable while protecting nothing meaningful.
MIN_SECRET_CHARS = 3

# Characters application/x-www-form-urlencoded (WHATWG, what Chromium submits
# for a GET form) leaves alone; space becomes "+", everything else %XX.
_FORM_SAFE = frozenset(
    b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789*-._"
)
# Extra characters left unescaped by Python's quote (it always keeps
# A-Za-z0-9_.-~): none, encodeURIComponent's, encodeURI's.
_PERCENT_SAFE_SETS = ("", "!*'()", "!*'();/?:@&=+$,#")
# Legacy charsets a page may submit a form in (a page without a charset is
# windows-1252); a non-ASCII password then arrives percent-encoded in them.
_LEGACY_CHARSETS = ("utf-8", "cp1252", "shift_jis", "euc_jp", "gb18030", "big5")
_PERCENT_HEX_RE = re.compile(r"%[0-9A-F]{2}")
# A run of text between URL / markup delimiters: a query value, a path
# segment, a fragment, a quoted string...
_TOKEN_RE = re.compile(r"[^\s/?#&;=\"'<>()\[\]{},|]+")


def scrub(text: str, secrets: Iterable[str] = ()) -> str:
    """Mask every occurrence of any secret in ``text`` with ``[redacted]``.

    Also masks the secret's encoded spellings: form-urlencoded (as Chromium
    submits a GET form: ``*-._`` kept, ``~`` as %7E, space as ``+``),
    percent-encoded with upper- or lower-case hex (``quote`` /
    encodeURIComponent / encodeURI), HTML-escaped and JSON-escaped. Finally
    any URL-ish token that percent-decodes (UTF-8 or a legacy charset) to
    text containing a secret is masked whole.
    """
    if not text or not isinstance(text, str):
        return text
    rules = _rules(_secret_key(secrets))
    if rules is None:
        return text
    return _scrub_with(text, rules)


def _secret_key(secrets: Iterable[str]) -> FrozenSet[str]:
    return frozenset(
        s for s in secrets or () if isinstance(s, str) and len(s) >= MIN_SECRET_CHARS
    )


@functools.lru_cache(maxsize=32)
def _rules(key: FrozenSet[str]) -> Optional[Tuple[Tuple[str, ...], Tuple[str, ...]]]:
    """``(needles longest first, secrets)`` for a set of secrets, or None."""
    if not key:
        return None
    needles = set()
    for secret in key:
        needles.update(_spellings(secret))
    ordered = tuple(
        sorted(
            (n for n in needles if len(n) >= MIN_SECRET_CHARS), key=len, reverse=True
        )
    )
    return ordered, tuple(sorted(key, key=len, reverse=True))


def _spellings(secret: str) -> List[str]:
    """The secret as typed plus the encodings a page or URL may show it in."""
    out = [secret]
    raw = secret.encode("utf-8", "surrogatepass")
    form = "".join(
        chr(b) if b in _FORM_SAFE else "+" if b == 0x20 else f"%{b:02X}" for b in raw
    )
    out.extend((form, _lower_hex(form)))
    for safe in _PERCENT_SAFE_SETS:
        encoded = quote(secret, safe=safe)
        out.extend((encoded, _lower_hex(encoded)))
        plus = quote(secret, safe=safe + " ").replace(" ", "+")
        out.extend((plus, _lower_hex(plus)))
    escaped = html.escape(secret)
    out.extend(
        (
            escaped,
            escaped.replace("&#x27;", "&#39;"),
            html.escape(secret, quote=False),
            json.dumps(secret)[1:-1],
            json.dumps(secret, ensure_ascii=False)[1:-1],
        )
    )
    return out


def _lower_hex(text: str) -> str:
    return _PERCENT_HEX_RE.sub(lambda m: m.group(0).lower(), text)


def _scrub_with(text: str, rules: Tuple[Tuple[str, ...], Tuple[str, ...]]) -> str:
    needles, secrets = rules
    out = text
    for needle in needles:
        if needle in out:
            out = out.replace(needle, MASK)
    if "%" not in out and "+" not in out:
        return out

    def mask_token(match: "re.Match[str]") -> str:
        token = match.group(0)
        if "%" not in token and "+" not in token:
            return token
        return MASK if _decodes_to_secret(token, secrets) else token

    return _TOKEN_RE.sub(mask_token, out)


def _decodes_to_secret(token: str, secrets: Tuple[str, ...]) -> bool:
    seen = set()
    for charset in _LEGACY_CHARSETS:
        try:
            decoded = unquote_plus(token, encoding=charset, errors="replace")
        except LookupError:  # a Python build without that codec
            continue
        if decoded in seen:
            continue
        seen.add(decoded)
        if any(secret in decoded for secret in secrets):
            return True
    return False


def _format(code: str, fields: Dict[str, Any]) -> Tuple[str, str, str]:
    """(category, title, message) for ``code`` from its ERROR_SPECS template.

    The fields are filled in as they are: the app codebook's generic
    ``redact()`` would turn the URLs, e-mail addresses and page texts these
    messages are about into ``[REDACTED]``. Secrets are masked by the
    callers through :func:`scrub`.
    """
    if code not in ERROR_SPECS:
        code = "MINI_BROWSER_INTERNAL"
    category, _severity, title, template = ERROR_SPECS[code]
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
    rules = _rules(_secret_key(secrets))
    if rules is None:
        return value
    return _scrub_value(value, rules)


def _scrub_value(value: Any, rules: Tuple[Tuple[str, ...], Tuple[str, ...]]) -> Any:
    if isinstance(value, str):
        return _scrub_with(value, rules) if value else value
    if isinstance(value, dict):
        return {
            (_scrub_with(k, rules) if isinstance(k, str) and k else k): _scrub_value(
                v, rules
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub_value(v, rules) for v in value]
    if isinstance(value, tuple):
        return tuple(_scrub_value(v, rules) for v in value)
    return value
