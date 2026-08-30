"""The ONE Node.js runtime every CraftBot component uses.

CraftBot spawns Node from several places — the browser frontend dev server,
the WhatsApp bridge, Agent App's lui CLI, npm installs, and Agent App app
pipeline steps. They must all agree on a single binary: deployments run
multiple Nodes side by side (a VPC pins its default to 20.x for other
services while local apps use 24.x), and the lui CLI needs >= 24 (it is
TypeScript executed through Node's native type stripping — older majors
throw ERR_UNKNOWN_FILE_EXTENSION).

Resolution order (cached per process):
  1. CRAFTBOT_NODE env var — explicit override (ignored with a warning when
     the path doesn't exist).
  2. PATH node when its major >= MIN_NODE_MAJOR.
  3. Newest >= MIN_NODE_MAJOR among nvm/nvm-windows installs and the sidecar
     install.py downloads into <repo>/runtime/node.
  4. An unprobeable PATH node, as the last resort — a broken probe must
     never block a good Node, but must not shadow a working install either.

The system default Node is NEVER upgraded, replaced, or shadowed outside
CraftBot's own subprocesses. When nothing >= MIN resolves, resolve() returns
None and callers fall back to plain PATH lookup — the frontend and bridge
run fine on Node 20; only Agent App hard-requires the resolved runtime
(runner.ensure_available raises the actionable message).

Stdlib-only on purpose: install.py and run.py import this before any
dependencies exist (app/__init__.py is empty).
"""

import functools
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MIN_NODE_MAJOR = 24  # keep the nodejs>=24 pin in environment.yml in sync

REPO_ROOT = Path(__file__).resolve().parents[1]
SIDECAR_DIR = REPO_ROOT / "runtime" / "node"

_NODE_VER_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


@dataclass
class NodeRuntime:
    node: str  # node binary path
    npm: Optional[str]  # version-matched npm from the same install, if present
    bin_dir: str  # directory to prepend to child PATHs
    version: Optional[str]  # "v24.11.1" when known
    source: str  # "override" | "path" | "discovered"


_cached: Optional[NodeRuntime] = None
_resolved = False


@functools.lru_cache(maxsize=8)
def probe_version(node: str) -> Optional[str]:
    """`node --version` output ("v24.1.0"), or None when the probe fails.
    Cached per path — a binary's version can't change mid-process, and the
    failure path (error messages, re-resolution) would otherwise re-spawn."""
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        out = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=15, **kwargs
        ).stdout.strip()
        return out or None
    except Exception as e:
        logger.warning(f"node version probe failed for {node}: {e}")
        return None


def major_of(version: Optional[str]) -> Optional[int]:
    try:
        return int((version or "").lstrip("v").split(".")[0])
    except ValueError:
        return None


def discover_node() -> Optional[str]:
    """Highest Node >= MIN_NODE_MAJOR from nvm/nvm-windows installs and the
    sidecar. Versions are parsed from directory names; nothing is spawned.
    (Other version managers aren't scanned — CRAFTBOT_NODE covers them.)"""
    home = Path.home()
    if sys.platform == "win32":
        nvm_home = os.environ.get("NVM_HOME") or os.path.join(
            os.environ.get("APPDATA") or str(home / "AppData" / "Roaming"), "nvm"
        )
        roots = [
            (Path(nvm_home), ("node.exe",)),
            (SIDECAR_DIR, ("node.exe",)),
        ]
    else:
        nvm_dir = os.environ.get("NVM_DIR") or str(home / ".nvm")
        roots = [
            (Path(nvm_dir) / "versions" / "node", ("bin", "node")),
            (SIDECAR_DIR, ("bin", "node")),
        ]
    best: Optional[tuple] = None
    best_path: Optional[Path] = None
    for root, rel in roots:
        try:
            entries = list(root.iterdir()) if root.is_dir() else []
        except OSError:
            continue
        for entry in entries:
            m = _NODE_VER_RE.search(entry.name)
            if not m:
                continue
            ver = tuple(int(x) for x in m.groups())
            if ver[0] < MIN_NODE_MAJOR:
                continue
            binary = entry.joinpath(*rel)
            if not binary.is_file():
                continue
            if best is None or ver > best:
                best, best_path = ver, binary
    return str(best_path) if best_path else None


def _sibling_npm(node: str) -> Optional[str]:
    """The npm shipped WITH this node install (same directory), so node and
    npm can never disagree on version. None when absent (bare binary)."""
    bin_dir = os.path.dirname(node)
    for name in ("npm.cmd", "npm") if sys.platform == "win32" else ("npm",):
        candidate = os.path.join(bin_dir, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def resolve(refresh: bool = False) -> Optional[NodeRuntime]:
    """The single Node runtime for this process (cached; refresh re-scans —
    install.py uses that right after downloading the sidecar)."""
    global _cached, _resolved
    if _resolved and not refresh:
        return _cached
    _resolved = True
    _cached = None

    override = os.environ.get("CRAFTBOT_NODE", "").strip()
    if override:
        if os.path.isfile(override):
            _cached = NodeRuntime(
                node=override,
                npm=_sibling_npm(override) or shutil.which("npm"),
                bin_dir=os.path.dirname(override),
                version=probe_version(override),
                source="override",
            )
            return _cached
        # A typo'd override must not become a raw FileNotFoundError at the
        # first spawn — warn and resolve normally instead.
        logger.warning(
            f"[NODE] CRAFTBOT_NODE points at a missing file ({override}) — ignoring it"
        )

    path_node = shutil.which("node")
    path_version = probe_version(path_node) if path_node else None
    path_major = major_of(path_version)
    if path_node and path_major is not None and path_major >= MIN_NODE_MAJOR:
        _cached = NodeRuntime(
            node=path_node,
            npm=_sibling_npm(path_node) or shutil.which("npm"),
            bin_dir=os.path.dirname(path_node),
            version=path_version,
            source="path",
        )
        return _cached

    discovered = discover_node()
    if discovered:
        _cached = NodeRuntime(
            node=discovered,
            npm=_sibling_npm(discovered),
            bin_dir=os.path.dirname(discovered),
            version=probe_version(discovered),
            source="discovered",
        )
        logger.info(
            f"[NODE] PATH node unsuitable — using {discovered} for all components"
        )
        return _cached

    # Fail open on a broken probe, but only as the LAST resort: an
    # unprobeable PATH node (hanging shim, corrupted binary) must never
    # block a launch — yet must not shadow a working discovered install.
    if path_node and path_major is None:
        _cached = NodeRuntime(
            node=path_node,
            npm=_sibling_npm(path_node) or shutil.which("npm"),
            bin_dir=os.path.dirname(path_node),
            version=path_version,
            source="path",
        )
        return _cached

    return None


def path_env() -> dict:
    """{"PATH": ...} with the resolved runtime's bin dir prepended, or {}
    when nothing resolved (children then see the unmodified system PATH).
    Merge into any subprocess env so bare `node`/`npm` in commands — and
    whatever npm itself spawns — hit the single runtime."""
    rt = resolve()
    if rt is None:
        return {}
    return {"PATH": rt.bin_dir + os.pathsep + os.environ.get("PATH", "")}


def child_env(extra: Optional[dict] = None) -> dict:
    """os.environ copy with the runtime's bin dir first on PATH."""
    env = {**os.environ, **path_env()}
    if extra:
        env.update(extra)
    return env


def node_cmd() -> Optional[str]:
    """Resolved node binary; falls back to plain PATH node (any version)
    for components that tolerate old majors (frontend, bridge)."""
    rt = resolve()
    return rt.node if rt else shutil.which("node")


def npm_cmd() -> Optional[str]:
    """Resolved npm; same fallback contract as node_cmd."""
    rt = resolve()
    if rt and rt.npm:
        return rt.npm
    return shutil.which("npm")
