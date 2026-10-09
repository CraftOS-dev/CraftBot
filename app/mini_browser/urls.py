"""What the Mini Browser may open, and turning typed text into a URL.

:func:`resolve` turns URL-bar / agent input into a :class:`Target`: a URL to
open, a history step, or a web search. :func:`blocked_reason` is the policy
for pages that actually load (main-frame navigations and popups).

CraftBot's own UI must never load inside the Mini Browser: a page loaded from
the UI origin is same-origin with it and could drive CraftBot. The host
comparison therefore canonicalises hosts the way Chromium's URL parser does
(backslashes, percent-encoding, IDNA / full-width characters, IPv4 shorthand
such as ``127.1``), so a disguised spelling cannot slip past the check.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import FrozenSet, Iterable, Optional, Tuple
from urllib.parse import quote_plus, unquote, urlsplit

from app.mini_browser.errors import MiniBrowserError

DEFAULT_SEARCH_URL = "https://duckduckgo.com/?q={query}"
UI_ORIGIN_REASON = "CraftBot's own interface cannot be opened inside the Mini Browser"
FILE_REASON = "local files cannot be opened (file: addresses are turned off)"
MAX_INPUT_CHARS = 8192

KIND_URL = "url"
KIND_BACK = "back"
KIND_FORWARD = "forward"
KIND_RELOAD = "reload"
_HISTORY_KINDS = frozenset({KIND_BACK, KIND_FORWARD, KIND_RELOAD})

_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
_PORT_PREFIX_RE = re.compile(r"^[0-9]{1,5}(?:[/?#]|$)")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_ASCII_LABEL_RE = re.compile(r"^[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?$")
_HEX_RE = re.compile(r"^0[xX][0-9a-fA-F]*$")
_DECIMAL_RE = re.compile(r"^[0-9]+$")
_DOTTED_QUAD_RE = re.compile(r"^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$")
_UNICODE_DOTS = str.maketrans({"。": ".", "．": ".", "｡": "."})

_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443, "ftp": 21}
# Recognised as a scheme even without "//" (otherwise "word:rest" is text).
_KNOWN_SCHEMES = frozenset(
    {
        "about",
        "blob",
        "brave",
        "chrome",
        "chrome-error",
        "chrome-extension",
        "chrome-search",
        "chrome-untrusted",
        "data",
        "devtools",
        "edge",
        "file",
        "filesystem",
        "ftp",
        "http",
        "https",
        "intent",
        "javascript",
        "mailto",
        "opera",
        "sms",
        "tel",
        "view-source",
        "vivaldi",
        "ws",
        "wss",
    }
)
# Schemes a loaded page may legitimately show (error pages, generated content).
_CONTENT_SCHEMES = frozenset({"about", "data", "chrome-error"})
# Host suffixes that only exist on a local network: open them over http.
_LOCAL_SUFFIXES = (".local", ".localhost", ".lan", ".internal", ".home.arpa")
# File extensions that look like TLDs but are not ("node.js" is a search).
_NOT_TLDS = frozenset(
    {
        "bat",
        "bmp",
        "cfg",
        "cmd",
        "conf",
        "cpp",
        "css",
        "csv",
        "dll",
        "doc",
        "docx",
        "exe",
        "gif",
        "htm",
        "html",
        "ini",
        "java",
        "jpeg",
        "jpg",
        "js",
        "json",
        "jsx",
        "log",
        "mjs",
        "mp3",
        "mp4",
        "pdf",
        "php",
        "png",
        "ppt",
        "pptx",
        "ps1",
        "svg",
        "tmp",
        "ts",
        "tsx",
        "txt",
        "wav",
        "xls",
        "xlsx",
        "xml",
        "yaml",
        "yml",
    }
)


@dataclass(frozen=True)
class Target:
    """What to do with URL-bar text: open ``url``, or a history step."""

    kind: str  # url | back | forward | reload
    url: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def resolve(
    text: str,
    *,
    allow_history: bool,
    allow_search: bool,
    search_url: str,
    allow_file: bool,
    ui_origins: FrozenSet[str],
) -> Target:
    """Turn typed text into a :class:`Target`.

    - ``back`` / ``forward`` / ``reload`` are history steps when
      ``allow_history``;
    - http(s) URLs are kept; ``about:blank`` is allowed; ``file:`` only with
      ``allow_file``; every other scheme (javascript:, data:, chrome:, ...)
      is blocked;
    - without a scheme: local hosts (localhost, private IPs, ``*.local``) and
      any host with an explicit port open over http (port 443: https), a
      domain or public IP over https, anything else is a web search (when
      ``allow_search``);
    - CraftBot's own UI origins are always blocked.

    Raises MiniBrowserError MINI_BROWSER_INVALID_INPUT or
    MINI_BROWSER_BLOCKED_URL.
    """
    raw = text if isinstance(text, str) else ""
    value = raw.strip()
    if not value:
        raise _invalid("Enter a web address or something to search for.")
    if len(value) > MAX_INPUT_CHARS:
        raise _invalid("That address is too long.")
    if _CONTROL_RE.search(value):
        raise _invalid("The address contains control characters.")

    keyword = value.lower()
    if allow_history and keyword in _HISTORY_KINDS:
        return Target(kind=keyword)

    match = _SCHEME_RE.match(value)
    if match:
        scheme = match.group(1).lower()
        rest = value[match.end() :]
        if scheme in _KNOWN_SCHEMES or rest.startswith("//"):
            url = _explicit_url(value, scheme, allow_file)
            return _checked(url, allow_file, ui_origins)
        if not _PORT_PREFIX_RE.match(rest):
            # "word:something" is not an address we know: search for it.
            return _search_or_invalid(value, allow_search, search_url, ui_origins)

    url = _implicit_url(value)
    if url is not None:
        return _checked(url, allow_file, ui_origins)
    return _search_or_invalid(value, allow_search, search_url, ui_origins)


def blocked_reason(
    url: str, *, allow_file: bool, ui_origins: FrozenSet[str]
) -> Optional[str]:
    """Why a page at ``url`` must not stay loaded, or None if it is fine.

    Used for navigations that actually happen (links, redirects, scripts,
    popups). Content schemes a page can legitimately show (about:, data:,
    blob: of a non-UI origin, Chromium error pages) are fine.
    """
    value = (url or "").strip().replace("\\", "/")
    match = _SCHEME_RE.match(value)
    if not match:
        return None
    scheme = match.group(1).lower()
    if scheme == "blob":
        inner = value[match.end() :]
        return blocked_reason(inner, allow_file=allow_file, ui_origins=ui_origins)
    if scheme in ("http", "https"):
        return UI_ORIGIN_REASON if is_ui_origin(value, ui_origins) else None
    if scheme == "file":
        return None if allow_file else FILE_REASON
    if scheme in _CONTENT_SCHEMES:
        return None
    return _scheme_reason(scheme)


def is_ui_origin(url: str, ui_origins: Iterable[str]) -> bool:
    """True if ``url`` (http/https) points at one of CraftBot's UI origins.

    ``ui_origins`` holds normalised ``host:port`` entries (see
    :func:`normalize_origin`); a bare ``host`` entry matches every port.
    Hosts are compared exactly after canonicalisation: ``localhost`` does not
    stand in for ``127.0.0.1`` unless both are listed.
    """
    origins = frozenset(ui_origins or ())
    if not origins:
        return False
    parsed = host_and_port(url)
    if parsed is None:
        return False
    host, port = parsed
    return f"{host}:{port}" in origins or host in origins


def host_and_port(url: str) -> Optional[Tuple[str, int]]:
    """Canonical ``(host, port)`` of an http(s)/ws(s) URL (default port filled in)."""
    value = (url or "").strip().replace("\\", "/")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parts.netloc:
        return None
    host = canonical_host(_raw_host(parts.netloc))
    if not host:
        return None
    return host, port if port is not None else _DEFAULT_PORTS[scheme]


def normalize_origin(text: str) -> Optional[str]:
    """``"host:port"`` (lowercase, canonical host) for an origin, else None.

    Accepts ``http://localhost:7926``, ``localhost:7926``, ``[::1]:7926`` or a
    bare host (which then stands for every port).
    """
    value = (text or "").strip()
    if not value:
        return None
    if "://" in value:
        parsed = host_and_port(value)
        return f"{parsed[0]}:{parsed[1]}" if parsed else None
    host, port = _split_host_port(value)
    host = canonical_host(host)
    if not host or (port is not None and not 0 < port < 65536):
        return None
    return f"{host}:{port}" if port is not None else host


def split_origin(origin: str) -> Tuple[str, Optional[int]]:
    """``(host, port)`` of a normalised origin; port None for a bare host."""
    host, port = _split_host_port(origin or "")
    return host or "", port if port is not None and port > 0 else None


def canonical_host(host: str) -> str:
    """A host the way Chromium canonicalises it, for comparisons.

    Percent-decoded, IDNA-mapped (full-width / ideographic dots fold to
    ASCII), lowercased, trailing dot removed, IPv4 shorthand / hex / octal
    rewritten as dotted decimal, IPv6 compressed and bracketed.
    """
    value = unquote(host or "").strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].split("%", 1)[0]
        try:
            return f"[{_ipv6_text(ipaddress.IPv6Address(inner))}]"
        except ValueError:
            return value.lower()
    try:
        value = value.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        value = value.translate(_UNICODE_DOTS)
    value = value.lower().rstrip(".")
    ipv4 = _parse_ipv4(value)
    return ipv4 if ipv4 is not None else value


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _invalid(detail: str) -> MiniBrowserError:
    return MiniBrowserError("MINI_BROWSER_INVALID_INPUT", detail=detail)


def _blocked(reason: str) -> MiniBrowserError:
    return MiniBrowserError("MINI_BROWSER_BLOCKED_URL", reason=reason)


def _scheme_reason(scheme: str) -> str:
    return f"{scheme}: addresses are not allowed"


def _explicit_url(value: str, scheme: str, allow_file: bool) -> str:
    """Validate a URL typed with its scheme; return the URL to open."""
    if scheme in ("http", "https"):
        # WHATWG: for special schemes "\" is "/" and any number of slashes may
        # follow the scheme. Normalise so we check what Chromium will open.
        rest = value.split(":", 1)[1].replace("\\", "/").lstrip("/")
        url = f"{scheme}://{rest}"
        try:
            parts = urlsplit(url)
            parts.port  # noqa: B018 - raises ValueError for a bad port
        except ValueError:
            raise _invalid("That is not a valid web address.") from None
        if not parts.hostname:
            raise _invalid("That web address has no host name.")
        return url
    if scheme == "about":
        if value.lower() == "about:blank":
            return "about:blank"
        raise _blocked("only about:blank is allowed")
    if scheme == "file":
        if not allow_file:
            raise _blocked(FILE_REASON)
        return value.replace("\\", "/")
    raise _blocked(_scheme_reason(scheme))


def _implicit_url(value: str) -> Optional[str]:
    """The URL for scheme-less input that looks like an address, else None."""
    if any(ch.isspace() for ch in value) or "\\" in value:
        return None
    cut = min((i for i in (value.find(c) for c in "/?#") if i >= 0), default=len(value))
    hostport, rest = value[:cut], value[cut:]
    if not hostport or "@" in hostport:
        return None
    if hostport.count(":") > 1 and not hostport.startswith("["):
        # A bare IPv6 address ("::1"): bracket it.
        try:
            ipaddress.IPv6Address(hostport)
        except ValueError:
            return None
        hostport = f"[{hostport}]"
    host, port = _split_host_port(hostport)
    if port is not None and not 0 < port < 65536:
        return None
    if host is None or not host:
        return None
    canon = canonical_host(host)
    # Only a literal address is read as an IP: "1.5" is something to search
    # for, even though URL parsers would turn it into 1.0.0.5.
    literal = host.startswith("[") or bool(_DOTTED_QUAD_RE.match(host))
    ip = _ip(canon) if literal or port is not None else None
    if _is_local(canon, ip):
        scheme = "http"
    elif port is not None:
        scheme = "https" if port == 443 else "http"
    elif ip is not None:
        scheme = "https"
    elif _looks_like_domain(canon):
        scheme = "https"
    else:
        return None
    return f"{scheme}://{hostport}{rest}"


def _split_host_port(hostport: str) -> Tuple[Optional[str], Optional[int]]:
    """``(host, port)`` from ``host``, ``host:port``, ``[v6]`` or ``[v6]:port``.

    The port is None when absent and -1 when present but not a number.
    """
    if hostport.startswith("["):
        end = hostport.find("]")
        if end < 0:
            return None, None
        host, tail = hostport[: end + 1], hostport[end + 1 :]
        if not tail:
            return host, None
        if not tail.startswith(":"):
            return None, None
        return host, _port(tail[1:])
    if ":" in hostport:
        host, _, port_text = hostport.rpartition(":")
        return host, _port(port_text)
    return hostport, None


def _port(text: str) -> int:
    return int(text) if _DECIMAL_RE.match(text) and len(text) <= 5 else -1


def _raw_host(netloc: str) -> str:
    """The host part of a URL authority (userinfo and port removed)."""
    hostport = netloc.rpartition("@")[2]
    if hostport.startswith("["):
        end = hostport.find("]")
        return hostport[: end + 1] if end >= 0 else hostport
    return hostport.split(":", 1)[0]


def _ip(canon: str) -> Optional[ipaddress._BaseAddress]:
    text = canon[1:-1] if canon.startswith("[") and canon.endswith("]") else canon
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def _is_local(canon: str, ip: Optional[ipaddress._BaseAddress]) -> bool:
    if canon == "localhost" or canon.endswith(_LOCAL_SUFFIXES):
        return True
    if ip is None:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified


def _looks_like_domain(canon: str) -> bool:
    """``example.com``-shaped: 2+ valid labels and a plausible TLD."""
    if len(canon) > 253 or "." not in canon:
        return False
    labels = canon.split(".")
    if any(not _ASCII_LABEL_RE.match(label) for label in labels):
        return False
    tld = labels[-1]
    if tld.startswith("xn--"):
        return len(tld) > 4
    return tld.isalpha() and len(tld) >= 2 and tld not in _NOT_TLDS


def _search_or_invalid(
    value: str, allow_search: bool, search_url: str, ui_origins: FrozenSet[str]
) -> Target:
    if not allow_search:
        shown = value if len(value) <= 80 else value[:77] + "..."
        raise _invalid(f"'{shown}' is not a web address.")
    template = search_url if _usable_template(search_url) else DEFAULT_SEARCH_URL
    url = template.replace("{query}", quote_plus(value))
    if is_ui_origin(url, ui_origins):
        raise _blocked(UI_ORIGIN_REASON)
    return Target(kind=KIND_URL, url=url)


def _usable_template(search_url: str) -> bool:
    return (
        isinstance(search_url, str)
        and "{query}" in search_url
        and search_url.lower().startswith(("https://", "http://"))
    )


def _checked(url: str, allow_file: bool, ui_origins: FrozenSet[str]) -> Target:
    reason = blocked_reason(url, allow_file=allow_file, ui_origins=ui_origins)
    if reason:
        raise _blocked(reason)
    return Target(kind=KIND_URL, url=url)


def _ipv6_text(address: ipaddress.IPv6Address) -> str:
    """RFC 5952 text, as Chromium writes it (hex groups even for IPv4-mapped)."""
    packed = address.packed
    groups = [f"{(packed[i] << 8) | packed[i + 1]:x}" for i in range(0, 16, 2)]
    best_start, best_len, start = -1, 0, -1
    for index, group in enumerate([*groups, "end"]):
        if group == "0":
            start = index if start < 0 else start
        elif start >= 0:
            if index - start > best_len:
                best_start, best_len = start, index - start
            start = -1
    if best_len < 2:
        return ":".join(groups)
    head = ":".join(groups[:best_start])
    tail = ":".join(groups[best_start + best_len :])
    return f"{head}::{tail}"


def _parse_ipv4(host: str) -> Optional[str]:
    """WHATWG IPv4 parsing ("127.1", "0x7f.1", "2130706433"), else None."""
    if not host:
        return None
    parts = host.split(".")
    last = parts[-1]
    if not (_DECIMAL_RE.match(last) or _HEX_RE.match(last)):
        return None  # does not end in a number: a domain name
    if len(parts) > 4:
        return None
    numbers = []
    for part in parts:
        number = _ipv4_number(part)
        if number is None:
            return None
        numbers.append(number)
    if any(n > 255 for n in numbers[:-1]) or numbers[-1] >= 256 ** (5 - len(numbers)):
        return None
    value = numbers[-1]
    for index, number in enumerate(numbers[:-1]):
        value += number * 256 ** (3 - index)
    return str(ipaddress.IPv4Address(value))


def _ipv4_number(part: str) -> Optional[int]:
    if not part:
        return None
    if _HEX_RE.match(part):
        digits = part[2:]
        return int(digits, 16) if digits else 0
    if not _DECIMAL_RE.match(part):
        return None
    if len(part) > 1 and part.startswith("0"):
        try:
            return int(part[1:], 8)
        except ValueError:
            return None
    return int(part)
