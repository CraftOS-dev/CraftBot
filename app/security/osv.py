"""Look up an MCP server's package in the OSV malware database before it starts.

Ported from Hermes Agent's ``tools/osv_check.py`` (MIT, Nous Research),
itself inspired by Block/goose's extension malware check. Before an MCP
server launched through ``npx``, ``uvx`` or ``pipx`` starts, the package it
runs is looked up in Google's public OSV database. Only confirmed malware
(``MAL-*`` advisories) stops the start; ordinary CVEs do not.

Like Hermes, a lookup that fails (no network, OSV down, a slow handshake)
lets the server start: the check is fail-open and a failure is never
cached, while clean and blocked verdicts are reused for an hour so a server
that keeps reconnecting does not become a stream of OSV queries.

Runs only with "Check MCP packages" on (Settings > Security > Tools).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from agent_core.utils.logger import logger
from app.security.policy import get_policy

_OSV_ENDPOINT = os.getenv("OSV_ENDPOINT", "https://api.osv.dev/v1/query")
_TIMEOUT = 10  # seconds, per request
# Just above _TIMEOUT, so it only bites when a stalled TLS handshake
# defeats the socket timeout (Hermes' _OSV_MALWARE_CHECK_TIMEOUT_S).
_PREFLIGHT_TIMEOUT_S = 12.0

_CACHE_TTL_S = 3600.0
_CACHE_MAX_ENTRIES = 256
_cache: Dict[Tuple[str, str, Optional[str]], Tuple[float, Optional[str]]] = {}
_cache_lock = threading.Lock()

# Only the shims each runner installs; lookalikes are not launchers.
_ECOSYSTEM_BY_COMMAND = {
    "npx": "npm",
    "npx.cmd": "npm",
    "uvx": "PyPI",
    "uvx.cmd": "PyPI",
    "uvx.exe": "PyPI",
    "pipx": "PyPI",
    "pipx.exe": "PyPI",
}


def _infer_ecosystem(command: str) -> Optional[str]:
    # Split on both separators: a config written on Windows keeps
    # ``C:\\...\\uvx.exe`` intact under os.path.basename on POSIX.
    return _ECOSYSTEM_BY_COMMAND.get(re.split(r"[\\/]", command or "")[-1].lower())


def _parse_npm_package(token: str) -> Tuple[Optional[str], Optional[str]]:
    """``@scope/name@version`` or ``name@version``."""
    if token.startswith("@"):
        match = re.match(r"^(@[^/]+/[^@]+)(?:@(.+))?$", token)
        return (match.group(1), match.group(2)) if match else (token, None)
    if "@" in token:
        name, version = token.rsplit("@", 1)
        return name, version if version != "latest" else None
    return token, None


def _parse_pypi_package(token: str) -> Tuple[Optional[str], Optional[str]]:
    """``name==version`` or ``name[extras]==version``."""
    match = re.match(r"^([a-zA-Z0-9._-]+)(?:\[[^\]]*\])?(?:==(.+))?$", token)
    return (match.group(1), match.group(2)) if match else (token, None)


_PACKAGE_PARSERS = {"npm": _parse_npm_package, "PyPI": _parse_pypi_package}


def _parse_package_from_args(
    command: str, args: List[Any], ecosystem: str
) -> Tuple[Optional[str], Optional[str]]:
    """(package, version) the launcher runs, or (None, None)."""
    args = [a for a in (args or ()) if isinstance(a, str)]
    # ``pipx run PKG``: the subcommand is not the package.
    if re.split(r"[\\/]", command or "")[-1].lower().startswith("pipx"):
        if not args or args[0] != "run":
            return None, None
        args = args[1:]
    # npx's explicit install target (--package=NAME / --package NAME /
    # -p NAME) names a package distinct from the binary it runs.
    package_token = None
    take_next = False
    for arg in args:
        if take_next:
            package_token = arg
            break
        if arg in ("--package", "-p"):
            take_next = True
            continue
        if arg.startswith("--package="):
            package_token = arg[len("--package=") :]
            break
        if arg.startswith("-"):
            continue
        package_token = arg
        break
    if not package_token:
        return None, None
    parser = _PACKAGE_PARSERS.get(ecosystem)
    return parser(package_token) if parser else (package_token, None)


def _query_osv(package: str, ecosystem: str, version: Optional[str] = None) -> list:
    """The package's MAL-* advisories in OSV (regular CVEs ignored)."""
    payload: Dict[str, Any] = {"package": {"name": package, "ecosystem": ecosystem}}
    if version:
        payload["version"] = version
    request = urllib.request.Request(
        _OSV_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "CraftBot"},
        method="POST",
    )
    try:
        from app.downloads import ssl_context

        context = ssl_context()
    except Exception:
        context = None
    with urllib.request.urlopen(request, timeout=_TIMEOUT, context=context) as response:
        result = json.loads(response.read())
    return [v for v in result.get("vulns", []) if str(v.get("id", "")).startswith("MAL-")]


def _cache_get(key) -> Tuple[bool, Optional[str]]:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is not None and time.time() < entry[0]:
            return True, entry[1]
        _cache.pop(key, None)
        return False, None


def _cache_put(key, result: Optional[str]) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            now = time.time()
            for stale in [k for k, (expiry, _) in _cache.items() if expiry <= now]:
                del _cache[stale]
            if len(_cache) >= _CACHE_MAX_ENTRIES:
                _cache.clear()
        _cache[key] = (time.time() + _CACHE_TTL_S, result)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def check_package_for_malware(command: str, args: List[Any]) -> Optional[str]:
    """Why the package this command runs must not start, or None.

    None also when the command is not a known launcher or the lookup fails
    (fail-open, as in Hermes)."""
    ecosystem = _infer_ecosystem(command)
    if not ecosystem:
        return None
    package, version = _parse_package_from_args(command, args, ecosystem)
    if not package:
        return None
    key = (ecosystem, package, version)
    hit, cached = _cache_get(key)
    if hit:
        return cached
    try:
        malware = _query_osv(package, ecosystem, version)
    except Exception as exc:
        # Not cached: a later lookup may well succeed and find an advisory.
        logger.info(
            f"[SECURITY] OSV lookup for {ecosystem} package {package} failed; "
            f"starting without it: {type(exc).__name__}: {exc}"
        )
        return None
    result = None
    if malware:
        ids = ", ".join(str(m["id"]) for m in malware[:3])
        summaries = "; ".join(
            str(m.get("summary") or m["id"])[:100] for m in malware[:3]
        )
        result = (
            f"its package {package} ({ecosystem}) has known malware advisories: "
            f"{ids}. Details: {summaries}"
        )
    _cache_put(key, result)
    return result


def _field(server: Any, name: str):
    return server.get(name) if isinstance(server, dict) else getattr(server, name, None)


async def malware_refusal(server: Any) -> Optional[str]:
    """None when this MCP server may start; otherwise why it was held back.

    One attribute read when "Check MCP packages" is off."""
    if not get_policy().check_mcp_packages:
        return None
    if (_field(server, "transport") or "stdio") != "stdio":
        return None
    name = _field(server, "name") or "?"
    command = _field(server, "command") or ""
    args = list(_field(server, "args") or [])
    if not _infer_ecosystem(command):
        return None
    try:
        found = await asyncio.wait_for(
            asyncio.to_thread(check_package_for_malware, command, args),
            timeout=_PREFLIGHT_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(
            f"[SECURITY] OSV lookup for MCP server '{name}' timed out after "
            f"{_PREFLIGHT_TIMEOUT_S:.0f}s; starting without it."
        )
        return None
    if not found:
        return None
    ecosystem = _infer_ecosystem(command)
    package, version = _parse_package_from_args(command, args, ecosystem or "")
    try:
        from app.security import audit

        audit.record(
            "mcp_blocked",
            server=name,
            reason="malware_advisory",
            ecosystem=ecosystem,
            package=package,
            version=version,
        )
    except Exception as exc:
        logger.warning(f"[SECURITY] Audit write failed: {exc}")
    return f"MCP server '{name}' was not started: {found}."
