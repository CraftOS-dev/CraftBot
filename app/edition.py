# -*- coding: utf-8 -*-
"""
Which front end this CraftBot process serves.

CraftBot ships two editions over one backend: the browser edition (the React
UI in a web browser) and the terminal edition (the Ink client in
``app/ui_layer/terminal``). Both talk to the same WebSocket server; what
differs is what the agent is told about the user's screen and which actions
make sense there. The launcher (``run.py`` / ``craftbot.py``) chooses the
edition once per process through ``CRAFTBOT_FRONTEND``; it never changes
while the process runs, so every prompt built from it stays cache-stable.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import FrozenSet

ENV_VAR = "CRAFTBOT_FRONTEND"

BROWSER = "browser"
TERMINAL = "terminal"
EDITIONS = (BROWSER, TERMINAL)

# Actions that cannot work without a web page in front of the user. The
# terminal edition leaves them out of every compiled action list, so the agent
# is never offered them (render_ui produces sandboxed HTML for the browser's
# output panel; no terminal can run it).
_TERMINAL_EXCLUDED_ACTIONS: FrozenSet[str] = frozenset({"render_ui"})


def current() -> str:
    """The edition this process serves.

    Unset means the browser edition, the default ``python run.py`` starts.
    Any other value is a launcher bug and fails loudly instead of guessing.
    """
    value = os.environ.get(ENV_VAR, "").strip().lower()
    if not value:
        return BROWSER
    if value not in EDITIONS:
        raise ValueError(
            f"{ENV_VAR}={value!r} is not a CraftBot edition; "
            f"expected one of {', '.join(EDITIONS)}"
        )
    return value


def is_terminal() -> bool:
    return current() == TERMINAL


def excluded_actions() -> FrozenSet[str]:
    """Action names this edition never offers the agent."""
    return _TERMINAL_EXCLUDED_ACTIONS if is_terminal() else frozenset()


def terminal_client_dir() -> Path:
    """Source package of the terminal client (Node, React + Ink)."""
    from app.paths import CODE_ROOT

    return CODE_ROOT / "app" / "ui_layer" / "terminal"


def terminal_client_bundle() -> Path:
    """The built terminal client: one ES module run by Node 24+."""
    return terminal_client_dir() / "dist" / "craftbot-tui.mjs"
