"""Small platform-aware helpers used by craftbot.py.

`detached_popen_flags()` builds the per-platform OS-level flags for spawning
a fully detached subprocess (no console flash on Windows, new session on
Unix). Stdio is the caller's responsibility — this helper only handles the
"detach + suppress console" bits, so it composes with both DEVNULL stdio
and log-file stdio.

`dispatch_per_platform()` picks one of three values/callables based on
sys.platform — replaces the if win/elif darwin/else trinity that appears
in `_full_install_frozen`, `cmd_uninstall`, `cmd_install`, `cmd_repair`,
`_remove_desktop_shortcut`, and `_is_installed`.
"""

from __future__ import annotations

import sys
from typing import TypeVar

_PLATFORM = sys.platform
T = TypeVar("T")


def detached_popen_flags(*, new_process_group: bool = False) -> dict:
    """Return platform-specific Popen kwargs for a fully detached spawn.

    Caller still sets stdin/stdout/stderr explicitly — this helper only
    handles the OS-level detach flags so a single source of truth exists
    for the "no console flash, no terminal attachment" recipe.

    Args:
        new_process_group: Windows-only. Adds CREATE_NEW_PROCESS_GROUP so
            the spawned process gets its own console process group, which
            is what `cmd_start` uses to keep the agent alive after the
            installer's own process exits.
    """
    if _PLATFORM == "win32":
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        flags = DETACHED_PROCESS | CREATE_NO_WINDOW
        if new_process_group:
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            flags |= CREATE_NEW_PROCESS_GROUP
        return {"creationflags": flags, "close_fds": True}
    return {"start_new_session": True}


def dispatch_per_platform(*, win: T, mac: T, linux: T) -> T:
    """Return whichever of the three matches the current platform.
    Works for callables (caller invokes the result) or plain values."""
    if _PLATFORM == "win32":
        return win
    if _PLATFORM == "darwin":
        return mac
    return linux
