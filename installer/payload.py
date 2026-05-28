"""Agent payload management — downloading and extracting the agent zip.

The frozen installer (CraftBotInstaller.exe) is small and ships with no
agent code. At install time it downloads CraftBot-agent-<platform>.zip from
GitHub Releases (pinned to the bundled VERSION) and extracts the contained
CraftBotAgent.exe to a user-chosen install directory.

This module owns: asset naming, version pinning, download with progress,
local-staged-zip lookup (so devs can test the installer without publishing
a release), and zip extraction with EXE discovery.

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


def agent_asset_name() -> str:
    """Filename of the per-platform zip we expect at the GitHub release."""
    plat = (
        "windows"
        if _PLATFORM == "win32"
        else "macos"
        if _PLATFORM == "darwin"
        else "linux"
    )
    return f"CraftBot-agent-{plat}.zip"


def agent_exe_filename() -> str:
    """Filename of the agent executable produced by CraftBotAgent.spec."""
    return "CraftBotAgent.exe" if _PLATFORM == "win32" else "CraftBotAgent"


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


def agent_download_url(base_dir: str) -> str:
    version = read_bundled_version(base_dir)
    asset = agent_asset_name()
    if version == "latest":
        return f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest/download/{asset}"
    return f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/v{version}/{asset}"


def find_agent_exe(install_dir: str) -> Optional[str]:
    """Locate the agent executable inside an extracted install directory.
    Tries flat layout first, then nested CraftBotAgent/ folder."""
    candidates = [
        os.path.join(install_dir, agent_exe_filename()),
        os.path.join(install_dir, "CraftBotAgent", agent_exe_filename()),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def local_agent_zip(exe_path: Optional[str]) -> Optional[str]:
    """Return path to a locally-staged agent zip, if one exists.

    Lookup order (first match wins):
      1. $CRAFTBOT_AGENT_ZIP env var (explicit override)
      2. <dir-of-running-EXE>/CraftBot-agent-<platform>.zip
      3. <cwd>/dist/CraftBot-agent-<platform>.zip  (matches local build output)
    """
    env_path = os.environ.get("CRAFTBOT_AGENT_ZIP")
    if env_path and os.path.isfile(env_path):
        return env_path
    asset = agent_asset_name()
    candidates: list[str] = []
    if exe_path:
        candidates.append(os.path.join(os.path.dirname(exe_path), asset))
    candidates.append(os.path.join(os.getcwd(), "dist", asset))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def download_agent_zip(
    base_dir: str,
    exe_path: Optional[str],
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
) -> str:
    """Get the agent zip — local copy if available, else download from GitHub.

    Returns the path to the zip on disk. If a local copy was found, the
    caller MUST NOT unlink it. If the result is in tempfile.gettempdir(),
    the caller is expected to clean it up.
    """
    local = local_agent_zip(exe_path)
    if local:
        print(f"  Using local agent zip: {local}")
        if progress_cb:
            try:
                size = os.path.getsize(local)
                progress_cb(size, size)
            except OSError:
                pass
        return local

    import urllib.request

    url = agent_download_url(base_dir)
    print(f"  Downloading {url}")

    fd, tmp_path = tempfile.mkstemp(prefix="CraftBot-agent-", suffix=".zip")
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


def extract_agent_zip(zip_path: str, target_dir: str) -> str:
    """Extract zip into target_dir, return absolute path to the agent EXE."""
    import zipfile

    os.makedirs(target_dir, exist_ok=True)
    print(f"  Extracting to {target_dir}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(target_dir)

    exe = find_agent_exe(target_dir)
    if not exe:
        raise RuntimeError(
            f"Agent EXE not found after extracting to {target_dir}. "
            f"Expected {agent_exe_filename()} at the top level or under CraftBotAgent/."
        )
    if _PLATFORM != "win32":
        os.chmod(exe, 0o755)
    return exe


def is_temp_zip(zip_path: str) -> bool:
    """True if zip_path lives inside the OS temp dir — i.e. we downloaded it
    and the caller should unlink it after extraction. False for local-staged
    dev zips (which must survive)."""
    return os.path.dirname(os.path.abspath(zip_path)) == os.path.abspath(
        tempfile.gettempdir()
    )
