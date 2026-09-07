"""Install metadata read/write — a small JSON file recording what was
installed, where, and which interpreter runs it.

Written during the wizard's install flow, read by Repair (to know what to
overwrite), the wizard's state probe (to display Installed/Not installed),
and `cmd_start` (to know what to spawn). Cleared by Uninstall.

Pure functions taking the metadata file path as an argument — keeps the
module decoupled from craftbot.py's path constants.

## Schema history

**1** — `installed_path` pointed at CraftBotAgent.exe, a PyInstaller bundle of
the whole agent. There was nothing else to record: the EXE carried its own
interpreter and dependencies.

**2** — the agent is no longer frozen (see
docs/plans/unified-install-architecture.md). An install is now a source tree
plus a resolved interpreter, so both are recorded. `installed_path` is the
source ROOT, not an executable, and `python` is the interpreter to run it
with.

Schema 1 metadata is still readable: `schema_of()` reports 1 for it, and the
migration in craftbot.py uses that to find and remove the old bundle.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import List, Optional

SCHEMA = 2


def read(path: str) -> Optional[dict]:
    """Return the parsed metadata dict, or None if missing/corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def schema_of(meta: Optional[dict]) -> int:
    """Schema version of a metadata dict. Absent 'schema' means the original
    frozen-agent layout, which predates the field."""
    if not meta:
        return 0
    try:
        return int(meta.get("schema", 1))
    except (TypeError, ValueError):
        return 1


def write(
    path: str,
    installed_path: str,
    mode: str,
    python: Optional[str] = None,
    version: Optional[str] = None,
) -> None:
    """Persist the install root, run mode, and the interpreter that runs it."""
    meta = {
        "schema": SCHEMA,
        "installed_path": installed_path,
        "mode": mode,
        "installed_at": datetime.now().isoformat(timespec="seconds"),
    }
    if python:
        meta["python"] = python
    if version:
        meta["version"] = version
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def clear(path: str) -> None:
    """Remove the metadata file. Idempotent."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def installed_exe_path(path: str) -> Optional[str]:
    """The install root (schema 2) or the agent EXE (schema 1).

    Name kept for compatibility with existing callers; under schema 2 it is a
    directory, which is why every caller must go through launch_command()
    rather than assuming it can be executed.
    """
    meta = read(path)
    return meta.get("installed_path") if meta else None


def launch_command(path: str, run_script: str = "run.py") -> Optional[List[str]]:
    """The command that starts CraftBot for this install, or None.

    The single place that knows how an install is launched, so `cmd_start`,
    the wizard and repair cannot disagree:

      schema 2 → [<python>, <install_root>/run.py]
      schema 1 → [<agent exe>]      (legacy frozen bundle, still runnable)
    """
    meta = read(path)
    if not meta:
        return None
    installed = meta.get("installed_path")
    if not installed:
        return None

    if schema_of(meta) >= 2:
        python = meta.get("python")
        script = os.path.join(installed, run_script)
        if not python or not os.path.isfile(script):
            return None
        return [python, script]

    # Legacy: installed_path IS the executable.
    return [installed] if os.path.isfile(installed) else None
