"""Install payload management — downloading and extracting what gets installed.

The installer (CraftBotInstaller.exe) is small and ships with no agent code.
At install time it downloads CraftBot-src.zip from GitHub Releases (pinned to
the bundled VERSION) and extracts it to a user-chosen directory;
app.provision then builds an interpreter and dependency set around it.

This module owns: asset naming, version pinning, download with progress,
local-staged-zip lookup (so devs can test the installer without publishing a
release), and extraction.

The CraftBot-agent-<platform>.zip helpers are the LEGACY frozen-agent path,
kept only so this code can still recognise a pre-1.5 release. See
docs/plans/unified-install-architecture.md.

All functions take the dependencies they need as arguments — there is no
module-level state pulled from craftbot.py, which keeps imports one-way.
"""

from __future__ import annotations

import os
import sys
import tempfile
from typing import Callable, Optional

# CHANGEME if the project moves repos. Asset naming convention:
#   v{version}/CraftBot-agent-{platform}.zip
GITHUB_OWNER = "CraftOS-dev"
GITHUB_REPO = "CraftBot"

_PLATFORM = sys.platform


def source_asset_name() -> str:
    """The source payload every platform shares.

    One asset, not one per platform: it is pure Python plus data files. What
    used to differ per platform was the bundled interpreter and the compiled
    wheels, and both are now provisioned on the machine by app.provision
    (a python-build-standalone sidecar plus the per-platform lock).
    """
    return "CraftBot-src.zip"


def read_bundled_version(base_dir: str) -> str:
    """Read the embedded VERSION file. Each installer build is pinned to a
    specific agent version: the workflow writes the git tag (without leading
    'v') into VERSION and bundles it. Missing → 'latest' (dev build)."""
    candidates = [
        os.path.join(getattr(sys, "_MEIPASS", base_dir), "VERSION"),
        os.path.join(base_dir, "VERSION"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                v = f.read().strip()
            if v:
                return v
        except OSError:
            continue
    return "latest"


def _asset_url(base_dir: str, asset: str) -> str:
    version = read_bundled_version(base_dir)
    if version == "latest":
        return f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest/download/{asset}"
    return f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/v{version}/{asset}"


def source_download_url(base_dir: str) -> str:
    return _asset_url(base_dir, source_asset_name())


def local_asset(asset: str, exe_path: Optional[str], env_var: str) -> Optional[str]:
    """A locally-staged copy of `asset`, if one exists.

    Lookup order (first match wins):
      1. $<env_var> (explicit override)
      2. <dir-of-running-EXE>/<asset>
      3. <cwd>/dist/<asset>   (matches local build output)

    This is the dev loop: build the payload, drop it beside the installer, and
    the wizard uses it instead of fetching a published release.
    """
    env_path = os.environ.get(env_var)
    if env_path and os.path.isfile(env_path):
        return env_path
    candidates: list[str] = []
    if exe_path:
        candidates.append(os.path.join(os.path.dirname(exe_path), asset))
    candidates.append(os.path.join(os.getcwd(), "dist", asset))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def local_source_zip(exe_path: Optional[str]) -> Optional[str]:
    return local_asset(source_asset_name(), exe_path, "CRAFTBOT_SRC_ZIP")


def download_asset(
    url: str,
    local: Optional[str],
    label: str,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
) -> str:
    """Get an asset — a locally-staged copy if given, else download it.

    Returns the path to the zip on disk. If a local copy was used, the caller
    MUST NOT unlink it; is_temp_zip() distinguishes the two.
    """
    if local:
        print(f"  Using local {label}: {local}")
        if progress_cb:
            try:
                size = os.path.getsize(local)
                progress_cb(size, size)
            except OSError:
                pass
        return local

    import urllib.request

    print(f"  Downloading {url}")

    fd, tmp_path = tempfile.mkstemp(prefix="CraftBot-", suffix=".zip")
    os.close(fd)
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            total = resp.getheader("Content-Length")
            total_bytes = int(total) if total and total.isdigit() else None
            read = 0
            chunk = 64 * 1024
            with open(tmp_path, "wb") as out:
                while True:
                    block = resp.read(chunk)
                    if not block:
                        break
                    out.write(block)
                    read += len(block)
                    if progress_cb:
                        try:
                            progress_cb(read, total_bytes)
                        except Exception:
                            pass
        return tmp_path
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def download_source_zip(
    base_dir: str,
    exe_path: Optional[str],
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
) -> str:
    """The source payload the installer provisions a runtime around."""
    return download_asset(
        source_download_url(base_dir),
        local_source_zip(exe_path),
        "source zip",
        progress_cb,
    )


def extract_source_zip(zip_path: str, target_dir: str) -> str:
    """Extract the source payload and return the directory holding run.py.

    Tolerates both shapes a zip can have: files at the root, or nested under a
    single wrapper directory (what `git archive` and GitHub's own zips
    produce). Getting this wrong yields an install that looks fine until
    nothing can find run.py.
    """
    import zipfile

    os.makedirs(target_dir, exist_ok=True)
    print(f"  Extracting source to {target_dir}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(target_dir)

    if os.path.isfile(os.path.join(target_dir, "run.py")):
        return target_dir

    entries = [
        os.path.join(target_dir, e)
        for e in os.listdir(target_dir)
        if os.path.isdir(os.path.join(target_dir, e))
    ]
    for candidate in entries:
        if os.path.isfile(os.path.join(candidate, "run.py")):
            return candidate

    raise RuntimeError(
        f"run.py not found after extracting to {target_dir}. "
        "The source payload is not shaped as expected."
    )


def is_temp_zip(zip_path: str) -> bool:
    """True if zip_path lives inside the OS temp dir — i.e. we downloaded it
    and the caller should unlink it after extraction. False for local-staged
    dev zips (which must survive)."""
    return os.path.dirname(os.path.abspath(zip_path)) == os.path.abspath(
        tempfile.gettempdir()
    )
