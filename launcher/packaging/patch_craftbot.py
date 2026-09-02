#!/usr/bin/env python3
"""Two small edits to craftbot.py so it behaves when the launcher drives it.

Run once from the repository root:

    python launcher/packaging/patch_craftbot.py

Idempotent: applying it twice is a no-op. Each edit is an exact-string
replacement and the script refuses to guess — if the surrounding code has
changed, it stops and says which edit to make by hand.

1. `_close_console_window()` kills the PARENT process on Windows ("close the
   cmd.exe we were launched from"). Under the launcher the parent is the
   launcher's window, so the guard skips the kill when stdout is not a
   console — a script, a pipe, or the launcher. Double-clicking a .bat still
   closes its window as before.

2. Source-mode `uninstall` pip-uninstalls every requirement from the
   interpreter. For a managed install the interpreter is a sidecar the
   launcher deletes wholesale right afterwards, so that step is minutes of
   work for nothing. Skipped when the managed marker is present.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET = os.path.join(ROOT, "craftbot.py")

EDITS = [
    (
        "console-kill guard",
        '''def _close_console_window() -> None:
    """Close the current console/terminal window on Windows then exit."""
    if _PLATFORM != "win32":
        sys.exit(0)
''',
        '''def _close_console_window() -> None:
    """Close the current console/terminal window on Windows then exit.

    Only when this process owns a console. Launched from a script, a pipe or
    the CraftBot launcher, the "parent" is not a cmd.exe window at all — it
    is whatever started us, and killing it would take the launcher's window
    down with it.
    """
    if _PLATFORM != "win32" or not sys.stdout.isatty():
        sys.exit(0)
''',
    ),
    (
        "managed-install uninstall shortcut",
        '''    # Source mode: uninstall pip packages
    req_file = os.path.join(BASE_DIR, "requirements.txt")
''',
        '''    # Source mode: uninstall pip packages.
    #
    # Not for a managed install: there the interpreter is a sidecar under the
    # user data directory that the launcher removes wholesale right after
    # this returns, so uninstalling packages from it one by one would only
    # add minutes to the uninstall.
    if paths.is_managed_install():
        print("\\n(managed install — the launcher removes the runtime)")
        print("\\nUninstall complete.")
        return

    req_file = os.path.join(BASE_DIR, "requirements.txt")
''',
    ),
]


def main() -> int:
    with open(TARGET, encoding="utf-8") as fh:
        text = fh.read()

    changed = False
    for name, old, new in EDITS:
        if new in text:
            print(f"  already applied: {name}")
            continue
        if text.count(old) != 1:
            print(f"  cannot apply {name}: expected exactly one match in craftbot.py, "
                  f"found {text.count(old)}. Make this edit by hand (see this script).")
            return 1
        text = text.replace(old, new)
        changed = True
        print(f"  applied: {name}")

    if changed:
        with open(TARGET, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
