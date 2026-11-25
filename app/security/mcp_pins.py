"""Which MCP servers run a package without a fixed version.

A server started with ``npx -y some-package`` (or ``uvx some-package``)
downloads whatever version is newest at every start, so whoever controls
that package can change what runs on this computer at any time (Hermes
CVE-2026-82021 was a catalog pointing at a mutable ref). This reads the
package the launcher runs and reports it when no exact version is given.

Launchers understood: ``npx``, ``bunx``, ``pnpm dlx``, ``yarn dlx``,
``uvx`` and ``pipx run``. Local paths count as pinned.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, List, Optional, Sequence, Tuple

_EXACT_VERSION = re.compile(r"v?\d+(\.\d+)*([-+][0-9A-Za-z.-]+)?")
_NODE = {"npx", "bunx"}
_NODE_SUBCOMMAND = {"pnpm": "dlx", "yarn": "dlx"}
_PYTHON = {"uvx"}
_NODE_OPTIONS_WITH_VALUE = {"-p", "--package", "-c", "--call", "--registry", "--cache", "--userconfig"}
_UV_OPTIONS_WITH_VALUE = {"--from", "--with", "--python", "-p", "--index", "--index-url", "--extra-index-url"}


def _program(command: str) -> str:
    name = os.path.basename(command or "").lower()
    for suffix in (".cmd", ".exe", ".bat", ".ps1"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def _first_operand(args: Sequence[str], with_value: set) -> Tuple[Optional[str], Optional[str]]:
    """(the first non-option argument, the value of a package option)."""
    package_option = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            return (args[i + 1] if i + 1 < len(args) else None), package_option
        if arg.startswith("-"):
            name, equals, value = arg.partition("=")
            if name in ("-p", "--package", "--from", "--spec"):
                package_option = value if equals else (args[i + 1] if i + 1 < len(args) else None)
            if not equals and name in with_value:
                i += 1
            i += 1
            continue
        return arg, package_option
    return None, package_option


def _local(spec: str) -> bool:
    return spec.startswith((".", "/", "~", "file:")) or bool(re.match(r"^[A-Za-z]:[\\/]", spec))


def _npm_pinned(spec: str) -> bool:
    if _local(spec):
        return True
    name_end = spec.find("@", 1) if spec.startswith("@") else spec.find("@")
    if name_end <= 0:
        return False
    return bool(_EXACT_VERSION.fullmatch(spec[name_end + 1 :]))


def _python_pinned(spec: str) -> bool:
    if _local(spec):
        return True
    for separator in ("==", "@"):
        name, found, version = spec.partition(separator)
        if found and name and _EXACT_VERSION.fullmatch(version.strip()):
            return True
    return False


def unpinned_package(command: str, args: Sequence[str]) -> Optional[str]:
    """The package spec a launcher runs without an exact version, or None."""
    program = _program(command)
    args = list(args or [])
    if program in _NODE_SUBCOMMAND:
        if not args or args[0] != _NODE_SUBCOMMAND[program]:
            return None
        program, args = "npx", args[1:]
    if program in _NODE:
        operand, package = _first_operand(args, _NODE_OPTIONS_WITH_VALUE)
        spec = package or operand
        return spec if spec and not _npm_pinned(spec) else None
    if program == "pipx":
        if not args or args[0] != "run":
            return None
        program, args = "uvx", args[1:]
    if program in _PYTHON:
        operand, package = _first_operand(args, _UV_OPTIONS_WITH_VALUE)
        spec = package or operand
        return spec if spec and not _python_pinned(spec) else None
    return None


def unpinned_servers(servers: Iterable[dict]) -> List[Tuple[str, str]]:
    """(server name, package) for enabled servers running an unpinned package."""
    found = []
    for server in servers:
        if not server.get("enabled", True) or (server.get("transport") or "stdio") != "stdio":
            continue
        spec = unpinned_package(server.get("command") or "", server.get("args") or [])
        if spec:
            found.append((server.get("name", "?"), spec))
    return found
