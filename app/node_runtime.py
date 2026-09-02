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

# app.paths is the single answer to "where does state live" — in a dev
# checkout that is the repo (so this is unchanged), and in an install it is
# the per-user data dir. Before this, SIDECAR_DIR was derived from __file__
# and so pointed INSIDE the PyInstaller bundle: read-only, wiped between
# runs, and never populated. An installer-based user therefore had no
# reachable Node at all, and Living UI could not start.
# app.paths is stdlib-only, like this module, so the import is safe at the
# point install.py and run.py import us — before dependencies exist.
from app.paths import NODE_DIR as SIDECAR_DIR  # noqa: E402

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


def _platform_suffix():
    """(suffix, extension) of the Node archive for this machine.

    Windows gets the zip because tar would not preserve anything it needs;
    unix gets a tarball because zip does not preserve the executable bit.
    """
    import platform

    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if sys.platform == "win32":
        return f"win-{arch}", "zip"
    if sys.platform == "darwin":
        return f"darwin-{arch}", "tar.gz"
    return f"linux-{arch}", "tar.xz"


def latest_download_url(log=None) -> Optional[str]:
    """URL of the newest Node on the MIN_NODE_MAJOR line for this machine.

    Split out of download_sidecar so the archive can be pre-fetched into a
    cache without installing it (scripts/prefetch_runtimes.py).
    """
    import json
    import ssl
    import urllib.request

    say = log or (lambda _m: None)

    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()

    suffix, ext = _platform_suffix()

    try:
        req = urllib.request.Request(
            "https://nodejs.org/dist/index.json", headers={"User-Agent": "CraftBot"}
        )
        index = json.loads(urllib.request.urlopen(req, timeout=60, context=ctx).read())
    except Exception as e:
        say(f"   Could not reach the Node index: {str(e)[:160]}")
        return None

    ver = next(
        (
            e["version"]
            for e in index
            if e.get("version", "").startswith(f"v{MIN_NODE_MAJOR}.")
        ),
        None,
    )
    if not ver:
        say(f"   No v{MIN_NODE_MAJOR}.x release found in the Node index")
        return None
    return f"https://nodejs.org/dist/{ver}/node-{ver}-{suffix}.{ext}"


def _extract_node(archive_src, ver, suffix, ext, say, url=None):
    """Put a Node archive into SIDECAR_DIR and return its binary path.

    Shared by the cached and downloaded paths so extraction, layout and the
    binary probe cannot drift between them.
    """
    import tarfile
    import zipfile

    dest_root = str(SIDECAR_DIR)
    os.makedirs(dest_root, exist_ok=True)
    archive = os.path.join(dest_root, f"_download.{ext}")
    try:
        if archive_src:
            say(f"   Using cached {os.path.basename(archive_src)}")
            shutil.copyfile(archive_src, archive)
        else:
            # Streamed with progress: the archive is 30-55MB, and a single
            # silent blocking copy is indistinguishable from a hung install.
            from app import downloads

            downloads.download(url, archive, log=say, label=f"Node {ver}")
        say("   Extracting...")
        if ext == "zip":
            zipfile.ZipFile(archive).extractall(dest_root)
        else:
            # tar preserves the executable bit; zip does not, which is why
            # Windows gets the zip and unix the tarball.
            tarfile.open(archive, mode="r:*").extractall(dest_root)
    except Exception as e:
        say(f"   Node setup failed: {str(e)[:200]}")
        return None
    finally:
        try:
            os.remove(archive)
        except OSError:
            pass

    binary = os.path.join(
        dest_root,
        f"node-{ver}-{suffix}",
        "node.exe" if sys.platform == "win32" else os.path.join("bin", "node"),
    )
    return binary if os.path.isfile(binary) else None


def download_sidecar(log=None) -> Optional[str]:
    """Download an official Node build into SIDECAR_DIR; return the binary.

    No PATH edits, nothing else touched — plain discovery picks it up on the
    next resolve(refresh=True). Lives here rather than in install.py because
    the installer needs it too: installer users never run install.py, so that
    was the only route by which they could obtain Node, and they had none.

    Stdlib-only (certifi when importable, else the system trust store).
    """
    import json
    import ssl
    import urllib.request

    say = log or (lambda _m: None)

    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()

    suffix, ext = _platform_suffix()

    # Consult the cache BEFORE the network. Resolving the version means
    # fetching nodejs.org's release index, which on a slow or flaky link is
    # its own failure point — and failing there while the archive is already
    # on disk would be a pointless way to lose an install.
    cached_archive = None
    ver_from_cache = None
    try:
        from app import downloads

        cached_archive = downloads.find_cached(
            f"node-v{MIN_NODE_MAJOR}.*-{suffix}.{ext}"
        )
        if cached_archive:
            m = _NODE_VER_RE.search(os.path.basename(cached_archive))
            if m:
                ver_from_cache = "v" + ".".join(m.groups())
    except Exception:
        cached_archive = None

    if cached_archive and ver_from_cache:
        ver = ver_from_cache
        url = f"https://nodejs.org/dist/{ver}/node-{ver}-{suffix}.{ext}"
        return _extract_node(cached_archive, ver, suffix, ext, say, url)

    try:
        # Newest release on the MIN_NODE_MAJOR line (the index is newest-first).
        req = urllib.request.Request(
            "https://nodejs.org/dist/index.json", headers={"User-Agent": "CraftBot"}
        )
        index = json.loads(urllib.request.urlopen(req, timeout=60, context=ctx).read())
        ver = next(
            (
                e["version"]
                for e in index
                if e.get("version", "").startswith(f"v{MIN_NODE_MAJOR}.")
            ),
            None,
        )
        if not ver:
            say(f"   ⚠ No v{MIN_NODE_MAJOR}.x release found in the Node index")
            return None

        url = f"https://nodejs.org/dist/{ver}/node-{ver}-{suffix}.{ext}"
        return _extract_node(None, ver, suffix, ext, say, url)
    except Exception as e:
        say(f"   ⚠ Sidecar Node download failed: {str(e)[:200]}")
        return None


def ensure_sidecar(log=None) -> Optional[NodeRuntime]:
    """Return a usable Node >= MIN_NODE_MAJOR, downloading one if needed.
    Idempotent: a no-op when a suitable Node already resolves."""
    rt = resolve()
    if rt is not None:
        return rt
    if download_sidecar(log=log):
        return resolve(refresh=True)
    return None
