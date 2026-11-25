"""File guard for the agent's file tools (Settings > Security > Files).

Two checks, on resolved real paths (symlinks followed, ``..`` collapsed),
comparing locations, never file names:

- Protected files: CraftBot's own secret stores (settings with API keys,
  MCP server keys, credentials and the browser vault, security settings,
  the session token, the audit log) plus any paths the user adds. The file
  tools neither read nor write inside them.
- Confined writes (Strict): file tools write only inside the agent's file
  system, its workspace, and folders the user allows.
- System credentials (Hermes' agent/file_safety.py inventory): no writes to
  SSH, cloud and package-registry credentials or system account files, no
  writes to files that run commands at login or SSH connect, and no reads
  of project ``.env`` files or process files that leak a program's
  environment or memory.

Like Hermes' protected paths, this guards the file tools, not the shell: a
command the agent runs can still reach these files. Auto mode off (approval
for running commands) or a sandbox is what covers the shell.
"""

from __future__ import annotations

import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from app.security.policy import SecurityPolicy, get_policy


def _real(path) -> Path:
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def _inside(path: Path, root: Path) -> bool:
    # Both are resolved: compare as text (much faster than Path.parents),
    # case-insensitively where the file system is (normcase on Windows).
    p, r = os.path.normcase(str(path)), os.path.normcase(str(root))
    return p == r or p.startswith(r if r.endswith(os.sep) else r + os.sep)


# Hermes agent/file_safety.py: HOME_CREDENTIAL_FILES, HOME_CREDENTIAL_DIRS,
# build_write_denied_paths / _prefixes, SHELL_RC_FILES, the project env
# basenames and the /proc suffixes.
_HOME_CREDENTIAL_FILES = (".netrc", "_netrc", ".pgpass", ".npmrc", ".pypirc", ".git-credentials")
_HOME_CREDENTIAL_DIRS = (
    ".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure", ".config/gh", ".config/gcloud",
)
_SYSTEM_FILES = ("/etc/sudoers", "/etc/passwd", "/etc/shadow")
_SYSTEM_DIRS = ("/etc/sudoers.d", "/etc/systemd")
_SHELL_RC_FILES = (".bashrc", ".zshrc", ".profile", ".bash_profile", ".zprofile")
_ENV_FILE_NAMES = frozenset(
    {".env", ".env.local", ".env.development", ".env.production", ".env.test", ".env.staging", ".envrc"}
)
_DEVICE_FILES = frozenset(
    {
        "/dev/zero", "/dev/random", "/dev/urandom", "/dev/full", "/dev/stdin", "/dev/tty",
        "/dev/console", "/dev/stdout", "/dev/stderr", "/dev/fd/0", "/dev/fd/1", "/dev/fd/2",
    }
)
_PROC_SUFFIXES = (
    "/fd/0", "/fd/1", "/fd/2", "/environ", "/cmdline", "/maps", "/smaps", "/smaps_rollup",
    "/numa_maps", "/mem", "/auxv", "/pagemap",
)


@lru_cache(maxsize=4)
def _credential_locations(home: str):
    """(files, dirs, login files) for a home folder, as real paths."""
    files = {_real(os.path.join(home, name)) for name in _HOME_CREDENTIAL_FILES}
    files.update(_real(p) for p in _SYSTEM_FILES)
    dirs = [_real(os.path.join(home, *d.split("/"))) for d in _HOME_CREDENTIAL_DIRS]
    dirs.extend(_real(p) for p in _SYSTEM_DIRS)
    login = {_real(os.path.join(home, name)) for name in _SHELL_RC_FILES}
    login.add(_real(os.path.join(home, ".ssh", "config")))
    return frozenset(files), tuple(dirs), frozenset(login)


def _is_process_file(path: str) -> bool:
    normalized = os.path.normpath(path)
    return normalized in _DEVICE_FILES or (
        normalized.startswith("/proc/") and normalized.endswith(_PROC_SUFFIXES)
    )


def system_credential_refusal(path, real: Path, *, write: bool) -> Optional[str]:
    """Why the file tools may not use a system credential path, or None."""
    if write:
        files, dirs, login = _credential_locations(os.path.expanduser("~"))
        # ~/.ssh/config is in .ssh but holds no keys: it is a login file.
        if real in login:
            return (
                f"{path} runs commands at login or when SSH connects (Settings > "
                f"Security > Files). Ask the user to make this change."
            )
        if real in files or any(_inside(real, d) for d in dirs):
            return (
                f"{path} holds SSH, cloud or system credentials (Settings > "
                f"Security > Files). The agent cannot change it."
            )
        return None
    if _is_process_file(os.path.expanduser(str(path))) or _is_process_file(str(real)):
        return (
            f"{path} is a device or process file: reading it can hang or leak a "
            f"program's environment or memory."
        )
    if real.name.casefold() in _ENV_FILE_NAMES:
        return (
            f"{path} is an environment file that holds secrets (Settings > "
            f"Security > Files). Read .env.example to see its shape."
        )
    return None


# Resolving a root follows its symlinks (several system calls each), so a
# resolved list is reused for a few seconds; a changed setting or folder
# gets a new key at once.
_ROOTS_TTL_S = 5.0
_roots_cache: Dict[Tuple, Tuple[float, List[Path]]] = {}


def _resolved(roots: Tuple[str, ...]) -> List[Path]:
    now = time.monotonic()
    hit = _roots_cache.get(roots)
    if hit is not None and now - hit[0] < _ROOTS_TTL_S:
        return hit[1]
    resolved = [_real(r) for r in roots]
    if len(_roots_cache) > 32:
        _roots_cache.clear()
    _roots_cache[roots] = (now, resolved)
    return resolved


def protected_roots(policy: Optional[SecurityPolicy] = None) -> List[Path]:
    from app import paths
    from app.config import APP_CONFIG_PATH, PROJECT_ROOT

    policy = policy or get_policy()
    roots = (
        str(APP_CONFIG_PATH / "settings.json"),
        str(APP_CONFIG_PATH / "mcp_config.json"),
        str(APP_CONFIG_PATH / "security.json"),
        str(Path(PROJECT_ROOT) / ".credentials"),
        str(Path(PROJECT_ROOT) / ".security"),
        str(Path(paths.STATE_ROOT) / "run"),
    ) + tuple(policy.extra_protected_paths)
    return _resolved(roots)


def writable_roots(policy: Optional[SecurityPolicy] = None) -> List[Path]:
    from app.config import AGENT_FILE_SYSTEM_PATH, AGENT_WORKSPACE_ROOT

    policy = policy or get_policy()
    roots = (str(AGENT_FILE_SYSTEM_PATH), str(AGENT_WORKSPACE_ROOT)) + tuple(
        policy.workspace_paths
    )
    return _resolved(roots)


def check_file_access(path, *, write: bool) -> Optional[str]:
    """None when the file tools may use ``path``; otherwise why not."""
    policy = get_policy()
    if (
        not policy.protect_secret_files
        and not policy.protect_os_credentials
        and not (write and policy.confine_writes)
    ):
        return None
    if not path:
        return None
    real = _real(path)
    if policy.protect_os_credentials:
        refused = system_credential_refusal(path, real, write=write)
        if refused:
            return refused
    if policy.protect_secret_files:
        for root in protected_roots(policy):
            if _inside(real, root):
                return (
                    f"{path} is protected: it holds CraftBot's keys or security "
                    f"settings (Settings > Security > Files). To see settings, use "
                    f"read_settings (keys hidden); to change them, ask the user to "
                    f"use the Settings page."
                )
    if write and policy.confine_writes:
        if not any(_inside(real, root) for root in writable_roots(policy)):
            return (
                f"{path} is outside the folders the agent may write to "
                f"(Settings > Security > Files). Write inside the workspace, or "
                f"ask the user to allow this folder."
            )
    return None


def is_protected(path) -> bool:
    """Whether a path found by a search lies in a protected location."""
    policy = get_policy()
    if not policy.protect_secret_files and not policy.protect_os_credentials:
        return False
    real = _real(path)
    if policy.protect_os_credentials and system_credential_refusal(path, real, write=False):
        return True
    if not policy.protect_secret_files:
        return False
    return any(_inside(real, root) for root in protected_roots(policy))


def first_refusal(paths: Iterable[Tuple[object, bool]]) -> Optional[str]:
    """The first refusal among (path, write) pairs, or None."""
    for path, write in paths:
        refused = check_file_access(path, write=write)
        if refused:
            return refused
    return None
