"""The ONE Node.js runtime every CraftBot component uses.

CraftBot spawns Node from several places — the browser frontend dev server,
the WhatsApp bridge, Agent App's agent-app CLI, npm installs, and Agent App app
pipeline steps. They must all agree on a single binary: deployments run
multiple Nodes side by side (a VPC pins its default to 20.x for other
services while local apps use 24.x), and the agent-app CLI needs >= 24 (it is
TypeScript executed through Node's native type stripping — older majors
throw ERR_UNKNOWN_FILE_EXTENSION).

Resolution is cached per process. An explicit valid CRAFTBOT_NODE override
wins. Managed installs then use the release-pinned private Node/npm pair.
Source/Conda installs may use a compatible complete runtime from PATH or nvm.
Only CraftBot subprocess PATHs change; system installations are never modified.
A present Node without a functioning npm is not a complete runtime.

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

# app.paths is the single answer to "where does state live" — in a dev
# checkout that is the repo (so this is unchanged), and in an install it is
# the per-user data dir. Before this, SIDECAR_DIR was derived from __file__
# and so pointed INSIDE the PyInstaller bundle: read-only, wiped between
# runs, and never populated. An installer-based user therefore had no
# reachable Node at all, and Living UI could not start.
# app.paths is stdlib-only, like this module, so the import is safe at the
# point install.py and run.py import us — before dependencies exist.
from app.paths import is_managed_install
from app import runtime_manifest
from app.paths import NODE_DIR as SIDECAR_DIR

logger = logging.getLogger(__name__)

MIN_NODE_MAJOR = 24  # keep the nodejs>=24 pin in environment.yml in sync

REPO_ROOT = Path(__file__).resolve().parents[1]

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
            if usable(_cached):
                return _cached
            _cached = None
        # A typo'd override must not become a raw FileNotFoundError at the
        # first spawn — warn and resolve normally instead.
        logger.warning(
            f"[NODE] CRAFTBOT_NODE is missing or lacks a usable Node/npm pair ({override}) — ignoring it"
        )

    if is_managed_install():
        candidate = _pinned_exe()
        if candidate.is_file():
            rt = _runtime(candidate)
            if usable(rt):
                _cached = rt
        return _cached

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
        if usable(_cached):
            return _cached
        _cached = None

    # A broken higher-version nvm installation must not shadow our repaired copy.
    for discovered in (discover_node(), str(_pinned_exe())):
        if not discovered or not os.path.isfile(discovered):
            continue
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
        if usable(_cached):
            return _cached
        _cached = None

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
    if sys.platform != "win32" and not shutil.which("sh", path=env.get("PATH", "")):
        # npm runs package scripts through an OS shell. A private Node PATH
        # must still work without exposing system Git/tar or requiring setup.
        env.setdefault("npm_config_script_shell", "/bin/sh")
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


def _platform_suffix():
    target = runtime_manifest.target("node")
    return target, (
        "zip"
        if target.startswith("win-")
        else ("tar.gz" if target.startswith("darwin-") else "tar.xz")
    )


def latest_download_url(log=None) -> Optional[str]:
    """Compatibility entry point for prefetch: the approved release, not latest."""
    try:
        return runtime_manifest.asset("node")["url"]
    except ValueError as exc:
        (log or (lambda _: None))(str(exc))
        return None


def _pinned_exe():
    target = runtime_manifest.target("node")
    root = SIDECAR_DIR / f"node-v{runtime_manifest.version('node')}-{target}"
    return root / ("node.exe" if sys.platform == "win32" else "bin/node")


def npm_command(rt=None):
    """Run npm's JS entry point with its own Node, without cmd.exe or shell quoting."""
    rt = rt or resolve()
    if rt is None:
        return None
    binary = Path(rt.node).resolve()
    candidates = [
        binary.parent / "node_modules/npm/bin/npm-cli.js",
        binary.parent.parent / "lib/node_modules/npm/bin/npm-cli.js",
    ]
    if rt.npm:
        candidates.append(Path(rt.npm).resolve().parent / "npm-cli.js")
    for entry in candidates:
        if entry.is_file():
            return [str(binary), str(entry)]
    return None


def usable(rt):
    if rt is None or (major_of(rt.version) or 0) < MIN_NODE_MAJOR:
        return False
    cmd = npm_command(rt)
    if not cmd:
        return False
    try:
        kwargs = (
            {"creationflags": subprocess.CREATE_NO_WINDOW}
            if sys.platform == "win32"
            else {}
        )
        result = subprocess.run(
            cmd + ["--version"], capture_output=True, text=True, timeout=20, **kwargs
        )
        return result.returncode == 0 and bool(
            re.match(r"^\d+\.", result.stdout.strip())
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def _runtime(node, source="sidecar"):
    return NodeRuntime(
        str(node),
        _sibling_npm(str(node)),
        str(Path(node).parent),
        probe_version(str(node)),
        source,
    )


def download_sidecar(log=None, offline=False) -> Optional[str]:
    import tarfile
    import tempfile
    import zipfile
    from app import downloads

    say = log or (lambda _: None)
    try:
        asset = runtime_manifest.asset("node")
        target, ext = _platform_suffix()
        version = "v" + runtime_manifest.version("node")
        SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
        installed = SIDECAR_DIR / f"node-{version}-{target}"
        with tempfile.TemporaryDirectory(prefix=".node-", dir=SIDECAR_DIR) as staging:
            stage = Path(staging)
            archive = stage / ("download." + ext)
            downloads.download(
                asset["url"],
                str(archive),
                log=say,
                label=f"Node {version}",
                expected_sha256=asset["sha256"],
                offline=offline,
            )
            if ext == "zip":
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(stage)
            else:
                with tarfile.open(archive) as tf:
                    tf.extractall(stage, filter="data")
            candidate = stage / installed.name
            exe = candidate / ("node.exe" if sys.platform == "win32" else "bin/node")
            if not usable(_runtime(exe)):
                raise RuntimeError("Downloaded Node/npm failed its execution check")
            backup = SIDECAR_DIR / (installed.name + ".previous")
            if backup.exists():
                shutil.rmtree(backup)
            if installed.exists():
                installed.rename(backup)
            try:
                candidate.rename(installed)
            except Exception:
                if backup.exists():
                    backup.rename(installed)
                raise
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
        probe_version.cache_clear()
        return str(_pinned_exe())
    except Exception as exc:
        say(f"Node setup failed: {exc}")
        return None


def ensure_sidecar(log=None, offline=False) -> Optional[NodeRuntime]:
    """Ensure a runnable Node/npm pair, repairing incomplete installations."""
    global _cached, _resolved
    rt = resolve(refresh=True)
    if usable(rt):
        return rt
    node = download_sidecar(log=log, offline=offline)
    if node:
        _cached, _resolved = _runtime(node), True
        return _cached
    return None
