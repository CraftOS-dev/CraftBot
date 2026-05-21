"""Install metadata read/write — a small JSON file recording where the
agent was installed and which run mode the user picked.

Written during the wizard's install flow, read by Repair (to know what to
overwrite), the wizard's state probe (to display Installed/Not installed),
and `cmd_start` (to know which agent EXE to spawn). Cleared by Uninstall.

Pure functions taking the metadata file path as an argument — keeps the
module decoupled from craftbot.py's path constants.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional


def read(path: str) -> Optional[dict]:
    """Return the parsed metadata dict, or None if missing/corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write(path: str, installed_path: str, mode: str) -> None:
    """Persist where the EXE was installed and which run mode the user picked."""
    meta = {
        "installed_path": installed_path,
        "mode": mode,
        "installed_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def clear(path: str) -> None:
    """Remove the metadata file. Idempotent."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def installed_exe_path(path: str) -> Optional[str]:
    """Convenience: read metadata and return just the installed EXE path."""
    meta = read(path)
    return meta.get("installed_path") if meta else None
