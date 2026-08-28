"""CraftBot updater — version checking, update, and restart logic.

This module is the single source of truth for all update operations.
Both the /update command and browser adapter handlers call into this module.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Awaitable, Callable, NamedTuple, Optional, Tuple


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


class UpdateStatus(NamedTuple):
    """Result of an update check.

    ``branch`` is set only when the checkout sits off the update channel
    (a feature branch, or diverged from it). The UI uses it to explain why
    no update is offered instead of showing a misleading version comparison.
    """

    available: bool
    current: str
    latest: str
    branch: Optional[str] = None


# ---------------------------------------------------------------------------
# Remote version check
# ---------------------------------------------------------------------------

GITHUB_REPO = "CraftOS-dev/CraftBot"
GITHUB_TAGS_URL = f"https://api.github.com/repos/{GITHUB_REPO}/tags"
GITHUB_LATEST_RELEASE_URL = GITHUB_TAGS_URL
UPDATE_BRANCH = "main"
GIT_PROBE_TIMEOUT = 15

# Version file lookup on the remote branch, mirroring the order used by
# config.get_app_version so the reported version matches what the updated
# checkout will report once it restarts.
REMOTE_VERSION_SOURCES = ("VERSION", "app/config/settings.json")


async def check_for_update() -> UpdateStatus:
    """Check whether a newer version is available on the update channel.

    ``main`` is the only update channel. For a git checkout it is the sole
    source of truth: being level with ``origin/main`` means up to date, even
    if a stray tag elsewhere sorts higher. Release tags are only consulted
    when the git probe is inconclusive — frozen builds and tarball installs,
    which have no checkout to compare against.

    Returns:
        UpdateStatus(available, current_version, latest_version, branch)
    """
    from app.config import get_app_version

    current = get_app_version()
    project_root = Path(__file__).resolve().parent.parent

    source_update = await _check_source_update(project_root, current)
    if source_update is not None:
        return source_update

    return await _check_release_update(current)


async def _check_source_update(
    project_root: Path,
    current: str,
    branch: str = UPDATE_BRANCH,
) -> Optional[UpdateStatus]:
    """Check whether this git checkout is behind the update branch.

    Only a checkout sitting *on* the update branch is eligible for an update:
    updating runs ``git checkout main``, so offering it from a feature branch
    would switch the user off their work. Anything off-channel reports no
    update and names the branch instead.

    Returns ``None`` when the probe is inconclusive so callers can fall back to
    the release-tag check instead of blocking update checks on git-specific
    failures.
    """
    if getattr(sys, "frozen", False):
        return None

    try:
        inside, _ = await _run_git(
            ["git", "rev-parse", "--is-inside-work-tree"], str(project_root)
        )
        if _decode_git_stdout(inside) != "true":
            return None

        head_branch_stdout, _ = await _run_git(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], str(project_root)
        )
        head_branch = _decode_git_stdout(head_branch_stdout)
        if head_branch != branch:
            return UpdateStatus(False, current, current, head_branch or "HEAD")

        await _run_git(
            ["git", "fetch", "origin", f"{branch}:refs/remotes/origin/{branch}"],
            str(project_root),
        )
        local_stdout, _ = await _run_git(
            ["git", "rev-parse", "HEAD"], str(project_root)
        )
        remote_stdout, _ = await _run_git(
            ["git", "rev-parse", f"origin/{branch}"], str(project_root)
        )

        local_revision = _decode_git_stdout(local_stdout)
        remote_revision = _decode_git_stdout(remote_stdout)
        if not local_revision or not remote_revision:
            return None
        if local_revision == remote_revision:
            return UpdateStatus(False, current, current)

        count_stdout, _ = await _run_git(
            [
                "git",
                "rev-list",
                "--left-right",
                "--count",
                f"HEAD...origin/{branch}",
            ],
            str(project_root),
        )
        ahead_text, behind_text = _decode_git_stdout(count_stdout).split()
        ahead = int(ahead_text)
        behind = int(behind_text)

        # Local commits on top of main: a ff-only pull cannot land, and the
        # checkout would need a merge the updater must not perform silently.
        if ahead > 0:
            return UpdateStatus(False, current, current, head_branch)

        if behind > 0:
            latest = await _remote_version(project_root, branch) or current
            return UpdateStatus(True, current, latest)

        return UpdateStatus(False, current, current)
    except Exception:
        return None


async def _remote_version(project_root: Path, branch: str) -> Optional[str]:
    """Read the app version recorded on ``origin/<branch>`` without checking out.

    Returns ``None`` if no version can be read, so callers fall back to the
    local version rather than displaying a placeholder.
    """
    for source in REMOTE_VERSION_SOURCES:
        try:
            stdout, _ = await _run_git(
                ["git", "show", f"origin/{branch}:{source}"], str(project_root)
            )
        except Exception:
            continue

        raw = _decode_git_stdout(stdout)
        if not raw:
            continue

        if source.endswith(".json"):
            try:
                version = json.loads(raw).get("version", "")
            except (json.JSONDecodeError, AttributeError):
                continue
        else:
            version = raw

        version = version.strip().lstrip("vV") if isinstance(version, str) else ""
        if version:
            return version

    return None


async def _check_release_update(current: str) -> UpdateStatus:
    """Check GitHub release tags against the local app version.

    Fallback path for installs with no git checkout to compare against.
    """
    import aiohttp

    try:
        headers = {"Accept": "application/vnd.github.v3+json"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GITHUB_TAGS_URL,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                tags = await resp.json(content_type=None)
    except Exception:
        # Network error — treat as "no update available".
        return UpdateStatus(False, current, current)

    if not tags or not isinstance(tags, list):
        return UpdateStatus(False, current, current)

    # Find the highest semver tag. GitHub tags are not guaranteed sorted.
    latest = "0.0.0"
    for tag in tags:
        name = tag.get("name", "")
        try:
            if parse_version(name) > parse_version(latest):
                latest = name.strip().lstrip("vV")
        except (ValueError, AttributeError):
            continue

    if is_newer(latest, current):
        return UpdateStatus(True, current, latest)
    return UpdateStatus(False, current, current)


# ---------------------------------------------------------------------------
# Perform update
# ---------------------------------------------------------------------------

RESTART_EXIT_CODE = 42


async def perform_update(
    progress_callback: Optional[Callable[[str], Awaitable[None]]] = None,
) -> None:
    """Launch the external updater script, then shut down.

    The script waits for CraftBot to exit, pulls the update branch, installs
    dependencies, and relaunches CraftBot. Running that work outside this
    process avoids in-process git mutation and exit-code signalling. Failures
    are written to updater.log.
    """

    async def emit(msg: str) -> None:
        if progress_callback:
            await progress_callback(msg)

    project_root = Path(__file__).resolve().parent.parent

    target_branch = UPDATE_BRANCH
    updater_script = _updater_script_path(project_root)

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
            [str(updater_script), target_branch, sys.executable],
            cwd=str(project_root),
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
        )
    else:
        subprocess.Popen(
            ["sh", str(updater_script), target_branch, sys.executable],
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


def _decode_git_stdout(stdout: bytes) -> str:
    return stdout.decode("utf-8", errors="replace").strip()


def _updater_script_path(project_root: Path, platform: str = sys.platform) -> Path:
    if platform == "win32":
        return project_root / "scripts" / "updater.bat"
    return project_root / "scripts" / "updater.sh"


async def _run_git(
    cmd: list, cwd: str, timeout: int = GIT_PROBE_TIMEOUT
) -> Tuple[bytes, bytes]:
    """Run a git command asynchronously; raise on non-zero exit."""
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")

    kwargs = {}
    if sys.platform == "win32":
        # Without this, spawning git.exe from this windowless process makes
        # Windows flash a new console window per invocation (visible to the
        # user every time an update check runs, e.g. on Settings page load).
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **kwargs,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        stdout, stderr = await proc.communicate()
        raise RuntimeError(
            f"{' '.join(cmd)} timed out after {timeout} seconds"
        ) from exc

    if proc.returncode != 0:
        err = (
            stderr.decode("utf-8", errors="replace").strip()
            or stdout.decode("utf-8", errors="replace").strip()
        )
        raise RuntimeError(
            f"{' '.join(cmd)} failed (exit {proc.returncode}): {err[:500]}"
        )
    return stdout, stderr
