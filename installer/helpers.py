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

`process_start_time()` reads when a pid's process started, stdlib only (the
frozen installer has no psutil). A pid alone is not an identity: after the
process exits the OS hands the number to something else, so anything that
kills a pid it saved earlier must also check the start time.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Optional, TypeVar

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


def process_start_time(pid: int) -> Optional[float]:
    """Epoch seconds at which `pid` started, or None if no such live process
    (or it can't be inspected). Precision: sub-second on Windows/Linux, one
    second on macOS — compare with a tolerance."""
    if not pid or pid <= 0:
        return None
    try:
        return dispatch_per_platform(
            win=_start_time_windows, mac=_start_time_macos, linux=_start_time_linux
        )(int(pid))
    except Exception:
        return None


def _start_time_windows(pid: int) -> Optional[float]:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        if code.value != STILL_ACTIVE:
            return None  # exited; the handle only keeps the pid reserved
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return ticks / 1e7 - 11644473600  # FILETIME epoch 1601 → 1970
    finally:
        k32.CloseHandle(handle)


def _start_time_linux(pid: int) -> Optional[float]:
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            stat = f.read()
        # comm (field 2) may contain spaces/parens; fields resume after ")".
        fields = stat[stat.rindex(")") + 2 :].split()
        if fields[0] == "Z":
            return None  # zombie: already exited
        start_ticks = int(fields[19])  # field 22 overall
        with open("/proc/stat", encoding="utf-8") as f:
            btime = next(int(line.split()[1]) for line in f if line.startswith("btime"))
        return btime + start_ticks / os.sysconf("SC_CLK_TCK")
    except Exception:
        return None


def _start_time_macos(pid: int) -> Optional[float]:
    out = subprocess.run(
        ["ps", "-o", "stat=,lstart=", "-p", str(pid)],
        capture_output=True,
        text=True,
        timeout=5,
        env={**os.environ, "LC_ALL": "C"},
    ).stdout.strip()
    if not out:
        return None
    state, lstart = out.split(None, 1)
    if state.startswith("Z"):
        return None
    return time.mktime(time.strptime(lstart.strip(), "%a %b %d %H:%M:%S %Y"))
