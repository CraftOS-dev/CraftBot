"""CraftBot updater — version checking, update, and restart logic.

This module is the single source of truth for all update operations.
Both the /update command and browser adapter handlers call into this module.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Awaitable, Callable, Optional, Tuple


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


def parse_version(version_str: str) -> Tuple[int, ...]:
    """Parse 'X.Y.Z' into an (X, Y, Z) integer tuple."""
    parts = version_str.strip().lstrip("vV").split(".")
    return tuple(int(p) for p in parts)


def is_newer(remote: str, local: str) -> bool:
    """Return True if *remote* version is strictly newer than *local*."""
    try:
        return parse_version(remote) > parse_version(local)
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Remote version check
# ---------------------------------------------------------------------------

GITHUB_REPO = "CraftOS-dev/CraftBot"
GITHUB_LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/tags"


async def check_for_update() -> Tuple[bool, str, str]:
    """Check whether a newer version is available on the remote repo.

    Fetches the latest git tag from GitHub (e.g. ``v1.2.2``) and compares
    it against the local version stored in settings.json.

    Returns:
        (update_available, current_version, latest_version)
    """
    from app.config import get_app_version

    import aiohttp

    current = get_app_version()
    try:
        headers = {"Accept": "application/vnd.github.v3+json"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GITHUB_LATEST_RELEASE_URL,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                tags = await resp.json(content_type=None)

        if not tags or not isinstance(tags, list):
            return False, current, current

        # Find the highest semver tag (tags are not guaranteed sorted)
        latest = "0.0.0"
        for tag in tags:
            name = tag.get("name", "")
            try:
                if parse_version(name) > parse_version(latest):
                    latest = name.strip().lstrip("vV")
            except (ValueError, AttributeError):
                continue

    except Exception:
        # Network error — treat as "no update available"
        return False, current, current

    return is_newer(latest, current), current, latest


# ---------------------------------------------------------------------------
# Perform update
# ---------------------------------------------------------------------------

RESTART_EXIT_CODE = 42


async def perform_update(
    progress_callback: Optional[Callable[[str], Awaitable[None]]] = None,
) -> None:
    """Launch the external updater script in a new window, then shut down.

    The updater script (scripts/updater.bat on Windows) runs in its own
    visible terminal and handles: waiting for us to exit, git pull, install,
    and relaunch. This keeps the update logic out of the running Python
    process — no in-process git mutation, no exit-code signalling, no
    console-visibility hacks. If the updater fails, its window stays open
    showing the error.
    """

    async def emit(msg: str) -> None:
        if progress_callback:
            await progress_callback(msg)

    project_root = Path(__file__).resolve().parent.parent

    target_branch = "main"

    if sys.platform == "win32":
        updater_script = project_root / "scripts" / "updater.bat"
    else:
        updater_script = project_root / "scripts" / "updater.sh"

    if not updater_script.exists():
        raise RuntimeError(f"Updater script not found: {updater_script}")

    await emit(f"Launching updater in a new window (pulling {target_branch})...")
    await asyncio.sleep(0.5)  # let the UI show the message

    if sys.platform == "win32":
        # CREATE_NO_WINDOW hides the updater console. The current CraftBot
        # process will close, the updater runs git/install silently, then
        # relaunches CraftBot — which reopens the browser UI automatically.
        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(
            [str(updater_script), target_branch],
            cwd=str(project_root),
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
        )
    else:
        subprocess.Popen(
            ["sh", str(updater_script), target_branch],
            cwd=str(project_root),
            start_new_session=True,
        )

    await emit("Shutting down — the updater will relaunch CraftBot shortly.")
    await asyncio.sleep(1)

    # Exit cleanly. The updater handles everything from here.
    os._exit(0)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _run_git(cmd: list, cwd: str) -> Tuple[bytes, bytes]:
    """Run a git command asynchronously; raise on non-zero exit."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = (
            stderr.decode("utf-8", errors="replace").strip()
            or stdout.decode("utf-8", errors="replace").strip()
        )
        raise RuntimeError(
            f"{' '.join(cmd)} failed (exit {proc.returncode}): {err[:500]}"
        )
    return stdout, stderr
