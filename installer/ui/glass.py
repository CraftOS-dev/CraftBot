"""Small display helpers for the installer window.

This used to render a gradient backdrop and answer "what colour is behind
this point", because every widget had to sample the ground beneath it to
disappear into it. The window is one flat colour now, so those surfaces are
constants on the Palette (see theme.py) and none of that machinery is needed.

What is left is the two things that genuinely depend on the display: which
fonts actually exist, and how much text fits.
"""

from __future__ import annotations

from typing import Dict

from installer.ui.theme import FONT_STACKS

__all__ = ["pick_font", "elide"]

_font_cache: Dict[str, str] = {}


def pick_font(role: str) -> str:
    """First font in the role's stack that is actually installed.

    Tk silently substitutes a default for an unknown family rather than
    erroring, so asking for "SF Pro Display" on Windows yields whatever Tk
    feels like — usually Courier-ish and wrong. Checking the family list
    first is the only way to get a predictable result across the three
    platforms this installer ships to.
    """
    if role in _font_cache:
        return _font_cache[role]
    stack = FONT_STACKS[role]
    try:
        import tkinter.font as tkfont

        available = {name.lower() for name in tkfont.families()}
        chosen = next((f for f in stack if f.lower() in available), stack[-1])
    except Exception:
        chosen = stack[-1]
    _font_cache[role] = chosen
    return chosen


def elide(path: str, limit: int = 46) -> str:
    """Shorten a filesystem path from the middle, keeping both ends readable.

    The install location is the one piece of text in the window the user has
    to verify, and the interesting parts are the drive and the final folder —
    truncating the tail would hide exactly what they are checking.
    """
    if len(path) <= limit:
        return path
    keep = (limit - 3) // 2
    return f"{path[:keep]}...{path[-keep:]}"
