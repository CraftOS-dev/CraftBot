"""Where everything lives, resolved once, for every install path.

The answer used to be spread across app/config.py, craftbot.py, install.py
and app/node_runtime.py, each with its own `sys.frozen` branch. They agreed
by convention, and when they stopped agreeing you got bugs like SIDECAR_DIR
pointing inside the PyInstaller bundle, leaving installer users with no
reachable Node.

This module is the single answer. Two roots, deliberately separate:

    CODE_ROOT   where CraftBot's code and bundled assets live.
                Treat as read-only. May sit inside an install dir or a
                PyInstaller bundle.

    STATE_ROOT  where the user's data lives — agent_file_system, dbs, logs,
                chroma, and the downloaded runtimes. Always writable, always
                survives an upgrade.

In a dev checkout both are the repo, which is why the split has been easy to
miss: it only shows up once the code is somewhere the user cannot write to.

Stdlib-only and imports nothing from app/: install.py and run.py import this
before dependencies exist.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "MANAGED_MARKER",
    "CODE_ROOT",
    "STATE_ROOT",
    "RUNTIME_DIR",
    "NODE_DIR",
    "is_frozen",
    "is_dev_checkout",
    "is_managed_install",
    "mark_managed_install",
    "describe",
]

_ENV_HOME = "CRAFTBOT_HOME"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _repo_root() -> Path:
    """The checkout containing this file (app/paths.py -> repo/)."""
    return Path(__file__).resolve().parents[1]


def _user_data_root() -> Path:
    """Per-user writable dir, matching craftbot.py's _user_data_dir()."""
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        return Path(root) / "CraftBot"
    if sys.platform == "darwin":
        return Path(os.path.expanduser("~/Library/Application Support/CraftBot"))
    root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(root) / "craftbot"


#: Written into the install root by the installer. Its presence is the ONLY
#: reliable way to tell a managed install from a developer's checkout: the
#: install payload is the source tree, so it contains install.py,
#: requirements.txt and everything else a checkout has. Sniffing for those
#: files would classify every installed copy as a checkout and put the user's
#: agent_file_system, databases and logs inside the install directory — which
#: an upgrade replaces wholesale, and which on Windows may not be writable.
MANAGED_MARKER = ".craftbot-managed"


def is_managed_install() -> bool:
    return (_repo_root() / MANAGED_MARKER).is_file()


def is_dev_checkout() -> bool:
    """True when running from a source checkout rather than an install."""
    if is_frozen() or is_managed_install():
        return False
    root = _repo_root()
    return (root / "install.py").is_file() and (root / "requirements.txt").is_file()


def _resolve_state_root() -> Path:
    # An explicit CRAFTBOT_HOME wins everywhere: it is how CI runs several
    # installs side by side without them colliding in the user profile, and
    # how a user relocates their data.
    override = os.environ.get(_ENV_HOME, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if is_dev_checkout():
        # Dev keeps state in the checkout — existing behaviour, and it keeps
        # a developer's experiments out of their real profile.
        return _repo_root()
    return _user_data_root()


def _resolve_code_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return _repo_root()


CODE_ROOT: Path = _resolve_code_root()
STATE_ROOT: Path = _resolve_state_root()

# Downloaded runtimes. Under STATE_ROOT because they are written after
# install and must outlive an upgrade that replaces CODE_ROOT wholesale.
RUNTIME_DIR: Path = STATE_ROOT / "runtime"
NODE_DIR: Path = RUNTIME_DIR / "node"

#: Written by AgentBase.boot() once initialisation has genuinely finished,
#: and deleted by run.py just before it launches the agent.
#:
#: run.py cannot tell when the agent is ready by watching its output — the
#: agent inherits run.py's stdout, so run.py has nothing to read — and "the
#: HTTP port answers" is not the same thing: the port binds early while the
#: model download, MCP connections, skills and scheduler are still going.
#: Using the port as the signal is what opened the browser at step 2 of 8,
#: onto a backend that could not serve a request yet.
AGENT_READY_FILE: Path = STATE_ROOT / ".agent-ready"


_MARKER_TEXT = """This file marks a managed CraftBot install.

It tells app/paths.py to keep user data (agent_file_system, databases, logs,
the vector store) in the per-user data directory rather than in this folder,
which an upgrade replaces wholesale.

Delete it only if you are converting this directory into a dev checkout.
"""


def mark_managed_install(root) -> None:
    """Stamp an install root as managed.

    Called by the installer right after it extracts the source payload, and
    before anything imports app.paths — the marker has to exist by the time
    STATE_ROOT is resolved, since that happens at import time.
    """
    (Path(root) / MANAGED_MARKER).write_text(_MARKER_TEXT, encoding="utf-8")


def describe() -> dict:
    """Everything a bug report needs to explain 'it can't find X'."""
    return {
        "frozen": is_frozen(),
        "dev_checkout": is_dev_checkout(),
        "managed_install": is_managed_install(),
        "code_root": str(CODE_ROOT),
        "state_root": str(STATE_ROOT),
        "runtime_dir": str(RUNTIME_DIR),
        "home_override": os.environ.get(_ENV_HOME) or None,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(describe(), indent=2))
