"""Windows launch options for noninteractive commands and their descendants."""

import subprocess
import sys


def hidden_console_kwargs(*, new_process_group=False):
    """Start a hidden console that nested commands can inherit.

    CREATE_NO_WINDOW leaves a console program with no console to pass on.
    A descendant launched with default flags can then allocate a visible one.
    Hiding a private console at creation avoids that gap while preserving
    captured output, background PIDs and normal process-tree cancellation.
    Never combine these flags with DETACHED_PROCESS or CREATE_NO_WINDOW.
    Explicit interactive application launches should use their own options.
    """
    if sys.platform != "win32":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    flags = subprocess.CREATE_NEW_CONSOLE
    if new_process_group:
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    return {"startupinfo": startup, "creationflags": flags}
