"""File guard for the agent's file tools (Settings > Security > Files).

Two checks, on resolved real paths (symlinks followed, ``..`` collapsed),
comparing locations, never file names:

- Protected files: CraftBot's own secret stores (settings with API keys,
  MCP server keys, credentials and the browser vault, security settings,
  the session token, the audit log) plus any paths the user adds. The file
  tools neither read nor write inside them.
- Confined writes (Strict): file tools write only inside the agent's file
  system, its workspace, and folders the user allows.

Like Hermes' protected paths, this guards the file tools, not the shell: a
command the agent runs can still reach these files. Auto mode off (approval
for running commands) or a sandbox is what covers the shell.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from app.security.policy import SecurityPolicy, get_policy


def _real(path) -> Path:
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def protected_roots(policy: Optional[SecurityPolicy] = None) -> List[Path]:
    from app import paths
    from app.config import APP_CONFIG_PATH, PROJECT_ROOT

    policy = policy or get_policy()
    roots = [
        APP_CONFIG_PATH / "settings.json",
        APP_CONFIG_PATH / "mcp_config.json",
        APP_CONFIG_PATH / "security.json",
        Path(PROJECT_ROOT) / ".credentials",
        Path(PROJECT_ROOT) / ".security",
        Path(paths.STATE_ROOT) / "run",
    ]
    roots.extend(Path(p) for p in policy.extra_protected_paths)
    return [_real(r) for r in roots]


def writable_roots(policy: Optional[SecurityPolicy] = None) -> List[Path]:
    from app.config import AGENT_FILE_SYSTEM_PATH, AGENT_WORKSPACE_ROOT

    policy = policy or get_policy()
    roots = [AGENT_FILE_SYSTEM_PATH, AGENT_WORKSPACE_ROOT]
    roots.extend(Path(p) for p in policy.workspace_paths)
    return [_real(r) for r in roots]


def check_file_access(path, *, write: bool) -> Optional[str]:
    """None when the file tools may use ``path``; otherwise why not."""
    policy = get_policy()
    if not policy.protect_secret_files and not (write and policy.confine_writes):
        return None
    if not path:
        return None
    real = _real(path)
    if policy.protect_secret_files:
        for root in protected_roots(policy):
            if _inside(real, root):
                return (
                    f"{path} is protected: it holds CraftBot's keys or security "
                    f"settings (Settings > Security > Files). Ask the user instead "
                    f"of reading or changing it."
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
    if not policy.protect_secret_files:
        return False
    real = _real(path)
    return any(_inside(real, root) for root in protected_roots(policy))


def first_refusal(paths: Iterable[Tuple[object, bool]]) -> Optional[str]:
    """The first refusal among (path, write) pairs, or None."""
    for path, write in paths:
        refused = check_file_access(path, write=write)
        if refused:
            return refused
    return None
