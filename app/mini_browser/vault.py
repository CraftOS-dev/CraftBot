"""Encrypted password vault for the Mini Browser.

The user saves website logins in the Mini Browser's Passwords panel and agents
sign in with them through ``login.autofill``. Passwords never travel back to
the UI or to the model: :meth:`CredentialVault.list_entries` and
:meth:`CredentialVault.status` carry no passwords. The only way out is
:meth:`CredentialVault.candidates_for_url`, which the autofill code uses to
type a password into the page whose URL it was matched against.

Storage
-------
Files live in ``PROJECT_ROOT/.credentials`` next to the integration
credentials and follow the same rules (directory 0700, files 0600):

- ``mini_browser_vault.enc``: a Fernet token (AES-128-CBC + HMAC-SHA256)
  of ``{"version": 1, "entries": [...]}``.
- ``mini_browser_vault.key``: the Fernet key, stored either as
  ``dpapi:<base64 blob>`` or as ``raw:<key>``. The DPAPI form is wrapped
  with Windows DPAPI, so only this Windows user account can unwrap it.
  The raw form is an owner-only file, used on other systems or when DPAPI
  fails.
- ``mini_browser_vault.enc.bak``: the previous version of the vault, kept
  on a best-effort basis and encrypted with the same key.

There is no master password. Like a browser's built-in password store, the
vault stops people reading the files from somewhere else (another OS user, a
copied or synced folder, a backup). It does not stop code that runs as this
user.

Never losing data
-----------------
- A key is generated only when neither a vault nor a key file exists. It is
  published atomically and never replaces an existing key.
- If the vault exists but cannot be decrypted or parsed (missing key, wrong
  key, damaged file), the vault is *unreadable*: reads return nothing and
  every write raises ``VaultError(MINI_BROWSER_VAULT_UNREADABLE)``, so nothing
  is silently overwritten. :meth:`CredentialVault.reset_unreadable` moves the
  files to timestamped ``*.bak`` copies and starts over. If the right key
  comes back first, the vault becomes readable again by itself.
- Saves write a temp file in the same directory, fsync it and
  ``os.replace`` it over the vault. A crash leaves either the old vault or
  the new one, never a torn file.
- Each vault directory has one lock, which serialises every
  load-modify-save in this process. Decrypted entries are cached until the
  files change on disk.

Secret hygiene
--------------
The app's loguru sinks use ``diagnose=True``. That prints the values of the
variables named on each line of a logged traceback, including any chained
exception. So in this module, no line that can raise (or that an exception
can pass through) names a raw password or key:

- passwords are wrapped in :class:`Secret` before anything can fail;
- entries are ``_Entry`` dicts whose repr is redacted;
- validators return problem strings instead of raising next to the value;
- exceptions are converted outside ``except`` blocks or ``from None``.

Callers should do the same: wrap a password in ``Secret`` as soon as it is
read, and never log a traceback from a frame that holds a raw one.

Every method is synchronous (file I/O + crypto): call it through
``asyncio.to_thread`` from async code.
"""

from __future__ import annotations

import base64
import binascii
import functools
import ipaddress
import json
import os
import re
import stat
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple
from urllib.parse import urlsplit

from app.logger import logger
from app.mini_browser.errors import MiniBrowserError

__all__ = [
    "CODE_INVALID",
    "CODE_IO",
    "CODE_UNREADABLE",
    "CredentialVault",
    "Secret",
    "VaultError",
    "get_vault",
    "normalize_site",
    "site_matches",
]

CODE_UNREADABLE = "MINI_BROWSER_VAULT_UNREADABLE"
CODE_INVALID = "MINI_BROWSER_VAULT_INVALID"
CODE_IO = "MINI_BROWSER_VAULT_IO"

VAULT_FILENAME = "mini_browser_vault.enc"
KEY_FILENAME = "mini_browser_vault.key"
PREVIOUS_FILENAME = VAULT_FILENAME + ".bak"

PROTECTION_DPAPI = "dpapi"
PROTECTION_FILE = "file"

MAX_USERNAME_CHARS = 256
MAX_PASSWORD_CHARS = 1024
MAX_LABEL_CHARS = 100
MAX_SITE_INPUT_CHARS = 2048
MAX_URL_CHARS = 2 * 1024 * 1024  # Chromium's own URL length limit
MAX_ENTRIES = 5000

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_FORMAT_VERSION = 1
_MAX_VAULT_BYTES = 32 * 1024 * 1024
_MAX_KEY_BYTES = 64 * 1024
_WEB_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORTS = frozenset({80, 443})
_REPLACE_ATTEMPTS = 8  # Windows: AV/sync tools briefly hold files open
_LOG = "[MINI_BROWSER_VAULT]"

_DPAPI_ENTROPY = b"CraftBot/mini-browser/vault-key/v1"
_DPAPI_DESCRIPTION = "CraftBot Mini Browser vault key"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1  # never show a Windows prompt

_BAD_CHARS_RE = re.compile("[\x00-\x1f\x7f-\x9f\ud800-\udfff]")
_SPACE_RE = re.compile(r"\s")
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):(.*)$", re.DOTALL)
_PORT_TAIL_RE = re.compile(r"^\d*(?:[/?#].*)?$", re.DOTALL)
_LABEL_RE = re.compile(r"^[a-z0-9_-]{1,63}$")
_NUMERIC_LABEL_RE = re.compile(r"^(?:\d+|0x[0-9a-f]*)$")
# Characters that IDNA 2003 maps differently from browsers (UTS #46
# non-transitional), e.g. "faß.de" -> "fass.de", which is another domain.
_IDNA_DEVIATIONS = frozenset(map(chr, (0xDF, 0x3C2, 0x200C, 0x200D)))  # ß ς ZWNJ ZWJ

# User-facing details (MINI_BROWSER_VAULT_INVALID renders "{detail}"). They
# never echo the input: a password pasted into the wrong field must not come
# back in an error message.
_MSG_SITE_EMPTY = "Enter the website address, for example example.com."
_MSG_SITE_LONG = "The website address is too long."
_MSG_SITE_SPACES = "A website address cannot contain spaces."
_MSG_SITE_SCHEME = "Only http:// and https:// website addresses can be saved."
_MSG_SITE_INVALID = (
    "That is not a valid website address. Use a domain such as example.com "
    "or a full https:// address."
)
_MSG_SITE_PORT = "The port number in the website address is not valid."
_MSG_SITE_DOTLESS = "Enter a full domain such as example.com, not a single word."
_MSG_SITE_IDN = (
    "That international domain name is not valid. Try its xn-- form from "
    "the browser's address bar."
)
_MSG_USERNAME_EMPTY = "Enter the username or email for this login."
_MSG_USERNAME_LONG = (
    f"The username is too long (at most {MAX_USERNAME_CHARS} characters)."
)
_MSG_USERNAME_CHARS = "The username cannot contain line breaks or control characters."
_MSG_PASSWORD_EMPTY = "Enter the password for this login."
_MSG_PASSWORD_LONG = (
    f"The password is too long (at most {MAX_PASSWORD_CHARS} characters)."
)
_MSG_PASSWORD_CHARS = (
    "The password cannot contain line breaks, tabs or other control characters."
)
_MSG_LABEL_TYPE = "The label must be text."
_MSG_LABEL_LONG = f"The label is too long (at most {MAX_LABEL_CHARS} characters)."
_MSG_LABEL_CHARS = "The label cannot contain line breaks or control characters."
_MSG_NOT_FOUND = "This saved login no longer exists. Refresh the list and try again."
_MSG_DUPLICATE = "Another saved login already uses this website and username."
_MSG_FULL = (
    f"The vault already holds {MAX_ENTRIES} logins. Delete some before adding more."
)
_MSG_NOTHING_TO_RESET = "The password vault is readable, so there is nothing to reset."
_MSG_NO_CRYPTO = "the 'cryptography' package is not installed"
_MSG_RACE = (
    "the vault was being created by another program at the same moment; try again"
)

# Log-only reasons for the unreadable state (the UI shows the generic
# MINI_BROWSER_VAULT_UNREADABLE message).
_PROBLEM_KEY_MISSING = "the key file is missing"
_PROBLEM_KEY_FORMAT = "the key file is not in a known format"
_PROBLEM_KEY_DAMAGED = "the key file is damaged"
_PROBLEM_KEY_INVALID = "the key file does not hold a valid vault key"
_PROBLEM_NO_DPAPI = "the key is protected by Windows DPAPI, which is not available here"
_PROBLEM_DPAPI_REFUSED = (
    "Windows could not unlock the key (it belongs to another Windows user or PC)"
)
_PROBLEM_WRONG_KEY = (
    "the vault cannot be decrypted with this key (wrong key or damaged file)"
)
_PROBLEM_DAMAGED = "the vault data is damaged"
_PROBLEM_TOO_LARGE = "the file is unexpectedly large"


class VaultError(MiniBrowserError):
    """A vault operation failed.

    ``code`` is one of ``CODE_UNREADABLE``, ``CODE_INVALID`` or ``CODE_IO``,
    and ``fields`` fill its ``ERROR_SPECS`` template. Because it is a
    :class:`MiniBrowserError`, ``errors.ui_error(e.code, **e.fields)`` and
    ``errors.from_exception(e)`` turn it into UI / action errors. The message
    never contains a password.
    """

    @property
    def detail(self) -> str:
        return str(self.fields.get("detail", ""))


class Secret:
    """A value (a password, a key) that never shows in a repr, str() or log.

    Wrap a password the moment it is read, e.g. from a WebSocket message, and
    pass the wrapper around. :meth:`reveal` returns the real value. The vault
    accepts either a ``Secret`` or a plain ``str`` wherever it takes a password.
    """

    __slots__ = ("_value",)

    def __init__(self, value: Any) -> None:
        self._value = value

    @classmethod
    def wrap(cls, value: Any) -> "Secret":
        return value if isinstance(value, Secret) else cls(value)

    def reveal(self) -> Any:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "Secret('[redacted]')"

    def __str__(self) -> str:
        return "[redacted]"

    def __reduce__(self):
        raise TypeError("Secret values cannot be pickled")


class _Entry(dict):
    """A vault entry. Its repr never shows the password (see "Secret hygiene")."""

    __slots__ = ()

    def __repr__(self) -> str:
        return f"<vault entry {self.get('id')!r} for {self.get('site')!r}>"

    __str__ = __repr__


class _Unreadable(Exception):
    """Internal: the vault files exist but cannot be used (log-safe reason)."""

    def __init__(self, problem: str) -> None:
        super().__init__(problem)
        self.problem = problem


class _HostError(ValueError):
    """Internal: a host name failed validation (``message`` is user-facing)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(repr=False)
class _State:
    """What is on disk right now, as of ``signature`` (file stats)."""

    signature: Optional[tuple]
    entries: List[_Entry] = field(default_factory=list)
    fernet: Any = None  # cryptography Fernet; None until a key exists
    protection: Optional[str] = None  # how the existing key file is protected
    unreadable: bool = False
    transient: bool = False  # a file was busy, or a dependency is missing
    problem: str = ""  # log-safe reason when not ok

    @property
    def ok(self) -> bool:
        return not self.unreadable and not self.transient

    def __repr__(self) -> str:
        return (
            f"<vault state ok={self.ok} unreadable={self.unreadable} "
            f"entries={len(self.entries)}>"
        )


class _FernetApi(NamedTuple):
    fernet: Any  # cryptography.fernet.Fernet
    invalid_token: Any  # cryptography.fernet.InvalidToken


class _DpapiBackend(NamedTuple):
    name: str
    protect: Callable[[bytes], bytes]
    unprotect: Callable[[bytes], bytes]


# ════════════════════════════════════════════════════════════════════════
# Site normalisation and matching
# ════════════════════════════════════════════════════════════════════════


def normalize_site(text: str) -> str:
    """Canonical ``host[:port]`` for a site the user types or pastes.

    Accepts a bare host or an http(s) URL, then:

    - strips the scheme, path, query, userinfo, one trailing dot and a
      leading ``www.``;
    - lowercases the host and converts Unicode names to IDNA (UTS #46
      non-transitional, the same as Chromium);
    - drops the default ports 80/443 and wraps IPv6 hosts in brackets.

    Raises :class:`VaultError` (``CODE_INVALID``) for empty input, spaces,
    other schemes, bad ports, and single-word hosts other than ``localhost``.
    """
    return _format_site(*_site_parts(text))


def site_matches(saved_site: str, url: str) -> bool:
    """True when a login saved for ``saved_site`` may be filled into ``url``.

    The page host must equal the saved host or be a subdomain of it on a dot
    boundary. A saved subdomain never matches its parent. When the saved site
    has a port, the page must use that port. The page must be https; only
    localhost, 127.0.0.1 and ::1 may also use plain http. Never raises.
    """
    if not isinstance(saved_site, str):
        return False
    saved = _saved_parts(saved_site)
    target = _parse_url(url)
    return saved is not None and target is not None and _matches(saved, target)


def _site_parts(text: Any) -> Tuple[str, Optional[int]]:
    """(host, port) of a saved site; raises VaultError(CODE_INVALID)."""
    if not isinstance(text, str):
        raise _invalid(_MSG_SITE_EMPTY)
    value = text.strip()
    if not value:
        raise _invalid(_MSG_SITE_EMPTY)
    if len(value) > MAX_SITE_INPUT_CHARS:
        raise _invalid(_MSG_SITE_LONG)
    if _SPACE_RE.search(value) or _BAD_CHARS_RE.search(value):
        raise _invalid(_MSG_SITE_SPACES)
    if "\\" in value:
        raise _invalid(_MSG_SITE_INVALID)
    url = _site_as_url(value)
    problem = ""
    try:
        parts = urlsplit(url)
        raw_host = parts.hostname
        port = parts.port
    except ValueError:
        problem = _MSG_SITE_INVALID
    if problem:
        raise _invalid(problem)
    try:
        host = _canonical_host(raw_host)
    except _HostError as exc:
        problem = exc.message
    if problem:
        raise _invalid(problem)
    if port == 0:
        raise _invalid(_MSG_SITE_PORT)
    if port in _DEFAULT_PORTS:
        port = None
    is_ip = _is_ip(host)
    if not is_ip and "." not in host and host != "localhost":
        raise _invalid(_MSG_SITE_DOTLESS)
    if not is_ip and host.startswith("www.") and "." in host[4:]:
        host = host[4:]
    return host, port


def _site_as_url(value: str) -> str:
    """Turn user input into something ``urlsplit`` parses as an authority."""
    # A bare IPv6 address ("::1") would otherwise look like host:port.
    if value.count(":") >= 2 and "[" not in value and "/" not in value:
        try:
            return f"//[{ipaddress.IPv6Address(value).compressed}]"
        except ValueError:
            pass
    match = _SCHEME_RE.match(value)
    if match:
        scheme, rest = match.group(1).lower(), match.group(2)
        if rest.startswith("//"):
            if scheme not in _WEB_SCHEMES:
                raise _invalid(_MSG_SITE_SCHEME)
            return value
        if not _PORT_TAIL_RE.match(rest):
            # "mailto:x", "javascript:x", "about:blank" (but not "host:8080").
            raise _invalid(
                _MSG_SITE_INVALID if scheme in _WEB_SCHEMES else _MSG_SITE_SCHEME
            )
    return value if value.startswith("//") else "//" + value


@functools.lru_cache(maxsize=4096)
def _saved_parts(site: str) -> Optional[Tuple[str, Optional[int]]]:
    """Parsed stored site, or None when it no longer validates."""
    try:
        return _site_parts(site)
    except VaultError:
        return None


def _parse_url(url: Any) -> Optional[Tuple[str, str, Optional[int]]]:
    """(scheme, host, port) of an http(s) page URL, or None."""
    if not isinstance(url, str) or len(url) > MAX_URL_CHARS:
        return None
    try:
        parts = urlsplit(url.strip())
        if parts.scheme not in _WEB_SCHEMES or "\\" in parts.netloc:
            # A backslash in the authority is parsed differently by browsers
            # ("https://evil.com\@bank.com" opens evil.com): never guess.
            return None
        host = _canonical_host(parts.hostname)
        port = parts.port
    except ValueError:
        return None
    if port == 0:
        return None
    return parts.scheme, host, None if port in _DEFAULT_PORTS else port


def _matches(
    saved: Tuple[str, Optional[int]], target: Tuple[str, str, Optional[int]]
) -> bool:
    saved_host, saved_port = saved
    scheme, host, port = target
    if scheme != "https" and host not in LOOPBACK_HOSTS:
        return False
    if saved_port is not None and port != saved_port:
        return False
    if host == saved_host:
        return True
    return not _is_ip(saved_host) and host.endswith("." + saved_host)


def _canonical_host(raw: Optional[str]) -> str:
    """Lowercase ASCII host (IPv6 without brackets); raises _HostError."""
    if not raw:
        raise _HostError(_MSG_SITE_EMPTY)
    if "%" in raw:  # percent-encoding or an IPv6 zone id: browsers differ
        raise _HostError(_MSG_SITE_INVALID)
    if ":" in raw:  # urlsplit strips the brackets of an IPv6 literal
        try:
            return ipaddress.IPv6Address(raw).compressed
        except ValueError:
            raise _HostError(_MSG_SITE_INVALID) from None
    host = raw if raw.isascii() else _idna_to_ascii(raw)
    host = host.lower()
    if host.endswith("."):
        host = host[:-1]
    if not host or len(host) > 253:
        raise _HostError(_MSG_SITE_INVALID)
    labels = host.split(".")
    if not all(_LABEL_RE.match(label) for label in labels):
        raise _HostError(_MSG_SITE_INVALID)
    if _NUMERIC_LABEL_RE.match(labels[-1]):
        # Browsers read a name ending in a number as IPv4 ("1.2.3" is
        # 1.2.0.3): accept only canonical dotted quads.
        try:
            return str(ipaddress.IPv4Address(host))
        except ValueError:
            raise _HostError(_MSG_SITE_INVALID) from None
    return host


def _idna_to_ascii(host: str) -> str:
    """Unicode host -> ASCII, the way Chromium does it (UTS #46)."""
    try:
        import idna
    except ImportError:
        idna = None
    if idna is not None:
        try:
            return idna.encode(host, uts46=True, transitional=False).decode("ascii")
        except ValueError:  # idna.IDNAError subclasses UnicodeError
            raise _HostError(_MSG_SITE_IDN) from None
    # Fallback: Python's IDNA 2003 codec. It maps the deviation characters to
    # a different domain than browsers do, so refuse those names.
    if any(ch in _IDNA_DEVIATIONS for ch in host):
        raise _HostError(_MSG_SITE_IDN)
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        raise _HostError(_MSG_SITE_IDN) from None


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _format_site(host: str, port: Optional[int]) -> str:
    shown = f"[{host}]" if ":" in host else host
    return shown if port is None else f"{shown}:{port}"


# ════════════════════════════════════════════════════════════════════════
# The vault
# ════════════════════════════════════════════════════════════════════════


class CredentialVault:
    """The Mini Browser's password vault (see the module docstring).

    ``base_dir`` defaults to ``PROJECT_ROOT/.credentials``; tests pass a
    temporary directory. Instances for the same directory share one lock.
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._dir = Path(base_dir) if base_dir is not None else _default_dir()
        self._lock = _lock_for(self._dir)
        self._cache: Optional[_State] = None
        self._reported = ""  # last problem logged, to avoid repeating it

    @property
    def directory(self) -> Path:
        return self._dir

    @property
    def vault_path(self) -> Path:
        return self._dir / VAULT_FILENAME

    @property
    def key_path(self) -> Path:
        return self._dir / KEY_FILENAME

    @property
    def previous_path(self) -> Path:
        return self._dir / PREVIOUS_FILENAME

    # ── reads (never raise for vault problems; no passwords) ───────────

    def status(self) -> Dict[str, Any]:
        """``{ok, unreadable, count, protection: 'dpapi'|'file'}``.

        ``ok`` is False when the vault is unreadable (needs a reset) or
        temporarily unavailable (a busy file, a missing dependency).
        ``protection`` describes the existing key, or the key a first save
        would create.
        """
        with self._lock:
            state = self._load_locked()
        return {
            "ok": state.ok,
            "unreadable": state.unreadable,
            "count": len(state.entries) if state.ok else 0,
            "protection": state.protection or _expected_protection(),
        }

    def list_entries(self) -> List[Dict[str, Any]]:
        """Saved logins for display, sorted by site: NO passwords."""
        with self._lock:
            state = self._load_locked()
            entries = [_public(entry) for entry in state.entries] if state.ok else []
        entries.sort(key=lambda e: (e["site"], e["username"].casefold(), e["id"]))
        return entries

    def candidates_for_url(self, url: str) -> List[Dict[str, Any]]:
        """INTERNAL (autofill only): logins allowed on ``url``, with passwords.

        Matching follows :func:`site_matches`. Results come exact-host first
        (ignoring a leading ``www.``), then most recently used. Each entry is a
        copy whose repr is redacted; never return it to the model or the UI.
        """
        target = _parse_url(url)
        if target is None:
            return []
        host = target[1]
        bare = host[4:] if host.startswith("www.") else host
        with self._lock:
            state = self._load_locked()
            if not state.ok:
                return []
            found = []
            for entry in state.entries:
                saved = _saved_parts(entry["site"])
                if saved is not None and _matches(saved, target):
                    found.append((saved[0] in (host, bare), _Entry(entry)))
        found.sort(key=lambda item: item[1].get("updatedAt") or "", reverse=True)
        found.sort(key=lambda item: item[1].get("lastUsedAt") or "", reverse=True)
        found.sort(key=lambda item: not item[0])
        return [entry for _exact, entry in found]

    # ── writes (raise VaultError) ──────────────────────────────────────

    def add_entry(
        self, site: str, username: str, password: Any, label: str = ""
    ) -> Dict[str, Any]:
        """Save a login; upserts on (normalised site, username ignoring case).

        On an upsert the password and the username's spelling are replaced
        and the label is replaced only when a non-empty one is given.
        ``password`` may be a ``str`` or a :class:`Secret`.
        """
        password = Secret.wrap(password)
        new = _new_fields(site, username, password, label)
        result = self._mutate(functools.partial(_upsert, new))
        logger.info(f"{_LOG} Saved a login for {result['site']} ({result['id']})")
        return result

    def update_entry(
        self,
        entry_id: str,
        *,
        site: Optional[str] = None,
        username: Optional[str] = None,
        password: Any = None,
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Change some fields of a login. ``None`` keeps a field; an empty
        password also keeps the current one. ``label=""`` clears the label."""
        password = None if password is None else Secret.wrap(password)
        changes = _changed_fields(site, username, password, label)
        target = _clean_id(entry_id)
        result, changed = self._mutate(
            functools.partial(_apply_update, target, changes)
        )
        if changed:
            logger.info(
                f"{_LOG} Updated the login for {result['site']} ({result['id']})"
            )
        return result

    def delete_entry(self, entry_id: str) -> bool:
        """Delete a login; False when no login has this id."""
        target = _clean_id(entry_id)
        removed = self._mutate(functools.partial(_remove, target))
        if removed:
            logger.info(f"{_LOG} Deleted saved login {target}")
        return removed

    def mark_used(self, entry_id: str) -> None:
        """Record that autofill used a login. Best effort: never raises."""
        target = _clean_id(entry_id)
        if target is None:
            return
        try:
            self._mutate(functools.partial(_touch, target))
        except VaultError as exc:
            logger.warning(
                f"{_LOG} Could not record that saved login {target} was used "
                f"({exc.code})"
            )

    def reset_unreadable(self) -> str:
        """Move an unreadable vault aside and start a new, empty one.

        The vault, its key and the previous version are renamed to
        ``mini_browser_vault.unreadable-<UTC time>.{enc,key,prev.enc}.bak``
        in the same directory. Returns the path of the vault backup, or of
        the key backup when only a key existed. Raises ``VaultError`` with
        ``CODE_INVALID`` when the vault is readable (nothing to reset).
        """
        with self._lock:
            state = self._load_locked()
            if not state.unreadable:
                raise _invalid(_MSG_NOTHING_TO_RESET)
            moved: List[Path] = []
            failure = ""
            try:
                stem = self._backup_stem()
                for source, suffix in (
                    (self.vault_path, ".enc.bak"),
                    (self.key_path, ".key.bak"),
                    (self.previous_path, ".prev.enc.bak"),
                ):
                    if source.exists():
                        target = self._dir / f"{stem}{suffix}"
                        _replace(source, target)
                        moved.append(target)
            except OSError as exc:
                failure = _os_reason(exc)
            self._cache = None
            if failure:
                logger.error(
                    f"{_LOG} Could not move the unreadable vault aside: {failure}"
                )
                raise VaultError(CODE_IO, detail=failure)
            names = ", ".join(path.name for path in moved) or "nothing"
            logger.warning(
                f"{_LOG} Reset the unreadable vault ({state.problem}); kept {names}"
            )
            return str(moved[0]) if moved else ""

    # ── internals ──────────────────────────────────────────────────────

    def _mutate(self, change: Callable[[List[_Entry]], Tuple[Any, bool]]) -> Any:
        """Load, apply ``change`` to a copy of the entries, save if changed."""
        with self._lock:
            state = self._load_locked()
            if state.unreadable:
                raise VaultError(CODE_UNREADABLE)
            if state.transient:
                raise VaultError(CODE_IO, detail=state.problem)
            entries = [_Entry(entry) for entry in state.entries]
            result, changed = change(entries)
            if changed:
                self._commit_locked(state, entries)
            return result

    def _commit_locked(self, state: _State, entries: List[_Entry]) -> None:
        fernet, protection = state.fernet, state.protection
        if fernet is None:
            fernet, protection = self._create_key_locked()
        token = _encrypt_entries(fernet, entries)
        failure = ""
        try:
            self._ensure_dir()
            self._keep_previous_locked()
            _atomic_write(self.vault_path, token)
            signature = self._signature()
        except OSError as exc:
            failure = _os_reason(exc)
        if failure:
            self._cache = None
            logger.error(f"{_LOG} Could not save the vault: {failure}")
            raise VaultError(CODE_IO, detail=failure)
        self._cache = _State(signature, entries, fernet=fernet, protection=protection)

    def _create_key_locked(self) -> Tuple[Any, str]:
        """Create the key of a brand-new vault; never replaces anything."""
        try:
            api = _fernet_api()
        except ImportError:
            raise VaultError(CODE_IO, detail=_MSG_NO_CRYPTO) from None
        key = Secret(api.fernet.generate_key())
        content, protection = _wrap_key(key)
        failure = ""
        try:
            # Never create a key while a vault (or another key) exists.
            if self.vault_path.exists() or self.key_path.exists():
                failure = _MSG_RACE
            else:
                self._ensure_dir()
                _publish_new_file(self.key_path, content.reveal())
        except FileExistsError:
            failure = _MSG_RACE
        except OSError as exc:
            failure = _os_reason(exc)
        if failure:
            self._cache = None
            raise VaultError(CODE_IO, detail=failure)
        logger.info(f"{_LOG} Created a new vault key (protection: {protection})")
        return api.fernet(key.reveal()), protection

    def _keep_previous_locked(self) -> None:
        """Best effort: copy the current vault to ``.enc.bak`` before a save."""
        try:
            data = _read_capped(self.vault_path, _MAX_VAULT_BYTES)
            _atomic_write(self.previous_path, data)
        except FileNotFoundError:
            return
        except (OSError, _Unreadable) as exc:
            reason = exc.problem if isinstance(exc, _Unreadable) else _os_reason(exc)
            logger.warning(
                f"{_LOG} Could not keep the previous vault version: {reason}"
            )

    def _load_locked(self) -> _State:
        try:
            signature = self._signature()
        except OSError as exc:
            return self._remember(_State(None, transient=True, problem=_os_reason(exc)))
        cached = self._cache
        if cached is not None and cached.signature == signature:
            return cached
        try:
            state = self._read_state(signature)
        except Exception as exc:
            # Never let an unexpected error carry decrypted data into a
            # traceback: report its type only.
            state = _State(
                None, transient=True, problem=f"unexpected {type(exc).__name__}"
            )
        return self._remember(state)

    def _remember(self, state: _State) -> _State:
        self._cache = None if state.transient else state
        if state.problem and state.problem != self._reported:
            if state.unreadable:
                logger.warning(
                    f"{_LOG} The vault is unreadable: {state.problem}. Saved logins "
                    f"are hidden and writes are refused until it is reset; nothing "
                    f"was changed."
                )
            else:
                logger.warning(f"{_LOG} The vault is unavailable: {state.problem}")
        self._reported = state.problem
        return state

    def _read_state(self, signature: tuple) -> _State:
        vault_sig, key_sig = signature
        try:
            api = _fernet_api()
        except ImportError:
            return _State(None, transient=True, problem=_MSG_NO_CRYPTO)
        if key_sig is None:
            if vault_sig is None:
                return _State(signature)  # fresh: the first save creates the key
            return _State(signature, unreadable=True, problem=_PROBLEM_KEY_MISSING)
        try:
            fernet, protection = self._load_key(api)
            entries = self._load_entries(api, fernet) if vault_sig is not None else []
        except _Unreadable as exc:
            return _State(signature, unreadable=True, problem=exc.problem)
        except OSError as exc:
            return _State(None, transient=True, problem=_os_reason(exc))
        return _State(signature, entries, fernet=fernet, protection=protection)

    def _load_key(self, api: _FernetApi) -> Tuple[Any, str]:
        content = Secret(_read_capped(self.key_path, _MAX_KEY_BYTES))
        key, protection = _unwrap_key(content)
        try:
            return api.fernet(key.reveal()), protection
        except (TypeError, ValueError):
            raise _Unreadable(_PROBLEM_KEY_INVALID) from None

    def _load_entries(self, api: _FernetApi, fernet: Any) -> List[_Entry]:
        token = _read_capped(self.vault_path, _MAX_VAULT_BYTES)
        try:
            plaintext = Secret(fernet.decrypt(token))
        except (api.invalid_token, TypeError, ValueError):
            raise _Unreadable(_PROBLEM_WRONG_KEY) from None
        return _parse_document(plaintext)

    def _signature(self) -> tuple:
        return (_stat_signature(self.vault_path), _stat_signature(self.key_path))

    def _ensure_dir(self) -> None:
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self._dir, stat.S_IRWXU)
        except OSError:
            pass

    def _backup_stem(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = f"mini_browser_vault.unreadable-{stamp}"
        stem, n = base, 1
        while any(
            (self._dir / f"{stem}{suffix}").exists()
            for suffix in (".enc.bak", ".key.bak", ".prev.enc.bak")
        ):
            n += 1
            stem = f"{base}-{n}"
        return stem


_default_vault: Optional[CredentialVault] = None
_default_vault_lock = threading.Lock()


def get_vault() -> CredentialVault:
    """The process-wide vault in ``PROJECT_ROOT/.credentials``."""
    global _default_vault
    vault = _default_vault
    if vault is None:
        with _default_vault_lock:
            if _default_vault is None:
                _default_vault = CredentialVault()
            vault = _default_vault
    return vault


# ════════════════════════════════════════════════════════════════════════
# Entry helpers (pure; operate on the copy that _mutate saves)
# ════════════════════════════════════════════════════════════════════════


def _new_fields(site: Any, username: Any, password: Secret, label: Any) -> _Entry:
    clean_site = normalize_site(site)
    clean_username = _clean_username(username)
    problem = _password_problem(password)
    if problem:
        raise _invalid(problem)
    clean_label = _clean_label(label)
    return _Entry(
        site=clean_site,
        username=clean_username,
        password=password.reveal(),
        label=clean_label,
    )


def _changed_fields(
    site: Any, username: Any, password: Optional[Secret], label: Any
) -> _Entry:
    changes = _Entry()
    if site is not None:
        changes["site"] = normalize_site(site)
    if username is not None:
        changes["username"] = _clean_username(username)
    if password:  # None or "" keeps the current password
        problem = _password_problem(password)
        if problem:
            raise _invalid(problem)
        changes["password"] = password.reveal()
    if label is not None:
        changes["label"] = _clean_label(label)
    return changes


def _upsert(new: _Entry, entries: List[_Entry]) -> Tuple[Dict[str, Any], bool]:
    now = _now()
    key = (new["site"], new["username"].casefold())
    for entry in entries:
        if (entry["site"], entry["username"].casefold()) == key:
            entry["username"] = new["username"]
            entry["password"] = new["password"]
            if new["label"]:
                entry["label"] = new["label"]
            entry["updatedAt"] = now
            return _public(entry), True
    if len(entries) >= MAX_ENTRIES:
        raise _invalid(_MSG_FULL)
    entry = _Entry(
        id=_new_id(existing["id"] for existing in entries),
        site=new["site"],
        username=new["username"],
        password=new["password"],
        label=new["label"],
        createdAt=now,
        updatedAt=now,
        lastUsedAt=None,
    )
    entries.append(entry)
    return _public(entry), True


def _apply_update(
    entry_id: Optional[str], changes: _Entry, entries: List[_Entry]
) -> Tuple[Tuple[Dict[str, Any], bool], bool]:
    """((public entry, changed), changed): saves only when something changed."""
    entry = next((e for e in entries if e["id"] == entry_id), None)
    if entry is None:
        raise _invalid(_MSG_NOT_FOUND)
    site = changes.get("site", entry["site"])
    username = changes.get("username", entry["username"])
    key = (site, username.casefold())
    for other in entries:
        if other is not entry and (other["site"], other["username"].casefold()) == key:
            raise _invalid(_MSG_DUPLICATE)
    changed = False
    for name, value in changes.items():
        if entry.get(name) != value:
            entry[name] = value
            changed = True
    if changed:
        entry["updatedAt"] = _now()
    return (_public(entry), changed), changed


def _remove(entry_id: Optional[str], entries: List[_Entry]) -> Tuple[bool, bool]:
    for index, entry in enumerate(entries):
        if entry["id"] == entry_id:
            del entries[index]
            return True, True
    return False, False


def _touch(entry_id: str, entries: List[_Entry]) -> Tuple[None, bool]:
    for entry in entries:
        if entry["id"] == entry_id:
            entry["lastUsedAt"] = _now()
            return None, True
    return None, False


def _public(entry: Dict[str, Any]) -> Dict[str, Any]:
    """The display form of an entry: never includes the password."""
    return {
        "id": entry["id"],
        "site": entry["site"],
        "username": entry["username"],
        "label": entry.get("label") or "",
        "createdAt": entry.get("createdAt") or None,
        "updatedAt": entry.get("updatedAt") or None,
        "lastUsedAt": entry.get("lastUsedAt") or None,
    }


def _clean_id(entry_id: Any) -> Optional[str]:
    if isinstance(entry_id, str) and 0 < len(entry_id) <= 64:
        return entry_id
    return None


def _clean_username(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(_MSG_USERNAME_EMPTY)
    text = value.strip()
    if len(text) > MAX_USERNAME_CHARS:
        raise _invalid(_MSG_USERNAME_LONG)
    if _BAD_CHARS_RE.search(text):
        raise _invalid(_MSG_USERNAME_CHARS)
    return text


def _password_problem(secret: Secret) -> str:
    """Why the password is unusable ("" when fine). Never raises."""
    value = secret.reveal()
    if not isinstance(value, str) or not value:
        return _MSG_PASSWORD_EMPTY
    if len(value) > MAX_PASSWORD_CHARS:
        return _MSG_PASSWORD_LONG
    if _BAD_CHARS_RE.search(value):
        return _MSG_PASSWORD_CHARS
    return ""


def _clean_label(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _invalid(_MSG_LABEL_TYPE)
    text = value.strip()
    if len(text) > MAX_LABEL_CHARS:
        raise _invalid(_MSG_LABEL_LONG)
    if _BAD_CHARS_RE.search(text):
        raise _invalid(_MSG_LABEL_CHARS)
    return text


def _invalid(detail: str) -> VaultError:
    return VaultError(CODE_INVALID, detail=detail)


def _new_id(taken: Iterable[str]) -> str:
    used = set(taken)
    while True:
        candidate = uuid.uuid4().hex[:12]
        if candidate not in used:
            return candidate


def _now() -> str:
    """ISO-8601 UTC timestamp, e.g. 2026-10-09T03:04:05.678+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ════════════════════════════════════════════════════════════════════════
# Serialisation and key handling
# ════════════════════════════════════════════════════════════════════════


def _fernet_api() -> _FernetApi:
    from cryptography.fernet import Fernet, InvalidToken

    return _FernetApi(Fernet, InvalidToken)


def _encrypt_entries(fernet: Any, entries: List[_Entry]) -> bytes:
    document = {"version": _FORMAT_VERSION, "entries": entries}
    return fernet.encrypt(
        json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    )


def _parse_document(plaintext: Secret) -> List[_Entry]:
    """Entries of a decrypted vault; raises _Unreadable when malformed.

    Unknown fields are kept so a save never drops data written by a newer
    version; duplicate ids get a fresh id instead of failing the whole vault.
    """
    try:
        document = json.loads(plaintext.reveal().decode("utf-8"))
    except ValueError:  # JSONDecodeError and UnicodeDecodeError
        raise _Unreadable(_PROBLEM_DAMAGED) from None
    if not isinstance(document, dict) or document.get("version") != _FORMAT_VERSION:
        raise _Unreadable(_PROBLEM_DAMAGED)
    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list):
        raise _Unreadable(_PROBLEM_DAMAGED)
    entries: List[_Entry] = []
    seen: set = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise _Unreadable(_PROBLEM_DAMAGED)
        entry = _Entry(raw)
        for name in ("id", "site", "username", "password"):
            if not isinstance(entry.get(name), str) or not entry[name]:
                raise _Unreadable(_PROBLEM_DAMAGED)
        if not isinstance(entry.get("label"), str):
            entry["label"] = ""
        for name in ("createdAt", "updatedAt", "lastUsedAt"):
            if not isinstance(entry.get(name), str):
                entry[name] = None
        if entry["id"] in seen:
            entry["id"] = _new_id(seen)
        seen.add(entry["id"])
        entries.append(entry)
    return entries


def _wrap_key(key: Secret) -> Tuple[Secret, str]:
    """Key file content for a new key: DPAPI-wrapped on Windows when possible.

    Never raises (DPAPI failures fall back to the owner-only raw form).
    """
    if os.name == "nt":
        blob = _dpapi_wrap(key)
        if blob is not None:
            return Secret(b"dpapi:" + base64.b64encode(blob)), PROTECTION_DPAPI
        logger.warning(
            f"{_LOG} Windows DPAPI is unavailable; the vault key is stored as an "
            f"owner-only file instead"
        )
    return Secret(b"raw:" + key.reveal()), PROTECTION_FILE


def _dpapi_wrap(key: Secret) -> Optional[bytes]:
    for backend in _dpapi_backends():
        try:
            blob = backend.protect(key.reveal())
            if backend.unprotect(blob) == key.reveal():
                return blob
            logger.warning(f"{_LOG} DPAPI ({backend.name}) round trip failed")
        except Exception as exc:
            logger.warning(
                f"{_LOG} DPAPI ({backend.name}) could not protect the vault key: "
                f"{type(exc).__name__}"
            )
    return None


def _unwrap_key(content: Secret) -> Tuple[Secret, str]:
    """(Fernet key, protection) from key file content; raises _Unreadable."""
    scheme, sep, body = content.reveal().strip().partition(b":")
    if not sep or not body:
        raise _Unreadable(_PROBLEM_KEY_FORMAT)
    if scheme == b"raw":
        return Secret(body), PROTECTION_FILE
    if scheme != b"dpapi":
        raise _Unreadable(_PROBLEM_KEY_FORMAT)
    try:
        blob = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        raise _Unreadable(_PROBLEM_KEY_DAMAGED) from None
    backends = _dpapi_backends()
    if not backends:
        raise _Unreadable(_PROBLEM_NO_DPAPI)
    for backend in backends:
        try:
            return Secret(backend.unprotect(blob)), PROTECTION_DPAPI
        except Exception:
            continue
    raise _Unreadable(_PROBLEM_DPAPI_REFUSED)


@functools.lru_cache(maxsize=None)
def _dpapi_backends() -> Tuple[_DpapiBackend, ...]:
    """Available DPAPI implementations, pywin32 first (empty off Windows)."""
    found = (_win32crypt_backend(), _ctypes_backend())
    return tuple(backend for backend in found if backend is not None)


def _expected_protection() -> str:
    return (
        PROTECTION_DPAPI if os.name == "nt" and _dpapi_backends() else PROTECTION_FILE
    )


def _win32crypt_backend() -> Optional[_DpapiBackend]:
    if os.name != "nt":
        return None
    try:
        import win32crypt
    except Exception:  # ImportError, or a pywin32 install whose DLLs fail to load
        return None

    def protect(data: bytes) -> bytes:
        return bytes(
            win32crypt.CryptProtectData(
                data,
                _DPAPI_DESCRIPTION,
                _DPAPI_ENTROPY,
                None,
                None,
                _CRYPTPROTECT_UI_FORBIDDEN,
            )
        )

    def unprotect(blob: bytes) -> bytes:
        _description, data = win32crypt.CryptUnprotectData(
            blob, _DPAPI_ENTROPY, None, None, _CRYPTPROTECT_UI_FORBIDDEN
        )
        return bytes(data)

    return _DpapiBackend("win32crypt", protect, unprotect)


def _ctypes_backend() -> Optional[_DpapiBackend]:
    """DPAPI through ctypes, for when pywin32 is missing or broken."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (ImportError, OSError, AttributeError):
        return None

    class _Blob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    blob_p = ctypes.POINTER(_Blob)
    protect_fn = crypt32.CryptProtectData
    protect_fn.argtypes = [
        blob_p,
        wintypes.LPCWSTR,
        blob_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        blob_p,
    ]
    protect_fn.restype = wintypes.BOOL
    unprotect_fn = crypt32.CryptUnprotectData
    unprotect_fn.argtypes = [
        blob_p,
        ctypes.c_void_p,  # LPWSTR* description: not wanted
        blob_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        blob_p,
    ]
    unprotect_fn.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    def run(fn: Any, data: bytes, description: Optional[str]) -> bytes:
        data_buf = ctypes.create_string_buffer(data, len(data))
        entropy_buf = ctypes.create_string_buffer(_DPAPI_ENTROPY, len(_DPAPI_ENTROPY))
        char_p = ctypes.POINTER(ctypes.c_char)
        data_blob = _Blob(len(data), ctypes.cast(data_buf, char_p))
        entropy_blob = _Blob(len(_DPAPI_ENTROPY), ctypes.cast(entropy_buf, char_p))
        out = _Blob()
        ok = fn(
            ctypes.byref(data_blob),
            description,
            ctypes.byref(entropy_blob),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out),
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            local_free(ctypes.cast(out.pbData, ctypes.c_void_p))

    return _DpapiBackend(
        "ctypes",
        lambda data: run(protect_fn, data, _DPAPI_DESCRIPTION),
        lambda blob: run(unprotect_fn, blob, None),
    )


# ════════════════════════════════════════════════════════════════════════
# Files
# ════════════════════════════════════════════════════════════════════════

_dir_locks: Dict[str, Any] = {}
_dir_locks_guard = threading.Lock()


def _lock_for(directory: Path) -> Any:
    """One re-entrant lock per vault directory (shared by every instance)."""
    key = os.path.normcase(os.path.abspath(str(directory)))
    with _dir_locks_guard:
        lock = _dir_locks.get(key)
        if lock is None:
            lock = _dir_locks[key] = threading.RLock()
        return lock


def _default_dir() -> Path:
    from app.config import PROJECT_ROOT

    return Path(PROJECT_ROOT) / ".credentials"


def _stat_signature(path: Path) -> Optional[tuple]:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _read_capped(path: Path, limit: int) -> bytes:
    with open(path, "rb") as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise _Unreadable(_PROBLEM_TOO_LARGE)
    return data


def _write_temp(path: Path, data: bytes) -> str:
    """Write ``data`` to a new owner-only temp file beside ``path`` (fsynced)."""
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fd = -1  # owned by fh now
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        _chmod_private(tmp)
    except BaseException:
        if fd != -1:
            os.close(fd)
        _unlink_quiet(tmp)
        raise
    return tmp


def _atomic_write(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data``; readers see the old or the new file."""
    tmp = _write_temp(path, data)
    try:
        _replace(tmp, path)
    except BaseException:
        _unlink_quiet(tmp)
        raise
    _fsync_dir(path.parent)


def _publish_new_file(path: Path, data: bytes) -> None:
    """Create ``path`` holding ``data`` atomically. Never replaces an existing
    file: raises FileExistsError instead, so a key can never be overwritten
    or left half-written."""
    tmp = _write_temp(path, data)
    try:
        if os.name == "nt":
            os.rename(tmp, path)  # MoveFileEx without REPLACE_EXISTING
        else:
            try:
                os.link(tmp, path)
            except FileExistsError:
                raise
            except OSError:  # no hard links on this filesystem
                _write_exclusive(path, data)
    finally:
        _unlink_quiet(tmp)
    _fsync_dir(path.parent)


def _write_exclusive(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def _replace(source: Any, target: Any) -> None:
    """``os.replace`` that retries while Windows reports the file busy."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if os.name != "nt" or attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def _chmod_private(path: Any) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _fsync_dir(directory: Path) -> None:
    """Persist a rename on POSIX (Windows cannot open directories for fsync)."""
    if os.name == "nt":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _unlink_quiet(path: Any) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _os_reason(exc: OSError) -> str:
    """A short, path-free reason for an OS error (e.g. 'Permission denied')."""
    return exc.strerror or type(exc).__name__
