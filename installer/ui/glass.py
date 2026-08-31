"""Turns the tokens in theme.py into pixels: the lit backdrop, and the
tints that controls sitting on it need in order to disappear into it.

Two things live here because they have to agree exactly:

  * `Backdrop.render()` paints the window's background.
  * `Backdrop.color_at()` reports the colour of any point in that background.

Every widget in the window asks `color_at()` for the colour behind it and
tints itself accordingly, so if the painter and the sampler ever disagreed
you would see a rectangle around every control. Keeping both on one class,
driven by one `color_at()`, makes disagreement impossible by construction:
the painter is just `color_at()` evaluated over a grid.

## Why the backdrop is an image and not shapes

Tk's canvas has no gradient primitive, so the obvious approach is stacked
shapes — horizontal lines for the ramp, concentric ovals for the glow. That
fails for a reason worth recording: a filled oval is opaque, so the outermost
ring of a glow repaints its entire area in one flat colour and erases the
ramp underneath it. The glow covers most of the window, so most of the
gradient disappears.

Painting into a `PhotoImage` instead composites properly because we do the
compositing in `color_at()` before any pixel is written. Measured on this
window: at 760x660 a full-resolution `put()` cost ~173 ms, while rendering at
`_SCALE`x reduction and `zoom()`-ing back up cost ~14 ms. The reduction is
invisible because the whole backdrop spans roughly 50 RGB units over its
height — well under one unit per block, which quantises away.
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Dict, List, Optional

from installer.ui.theme import (
    FONT_STACKS,
    PALETTE,
    Palette,
    Rgb,
    hex_to_rgb,
    over,
    rgb_to_hex,
)

__all__ = ["Backdrop", "pick_font"]

#: Render the backdrop at 1/_SCALE and zoom it back up. See module docstring
#: for why this is imperceptible and what it buys.
_SCALE = 3


class Backdrop:
    """The window's lit background, and the authority on what colour is
    behind any given point.

    Stateless apart from the cached PhotoImage, so it can be constructed and
    queried before a window exists (the layout code sizes itself from it).
    """

    def __init__(
        self, width: int, height: int, palette: Palette = PALETTE, scale: int = _SCALE
    ) -> None:
        self.width = width
        self.height = height
        self.palette = palette
        self.scale = max(1, scale)

        self._top = hex_to_rgb(palette.base_top)
        self._bottom = hex_to_rgb(palette.base_bottom)
        # Pre-resolve bloom geometry into pixels so color_at() stays cheap —
        # it is called once per pixel of the render.
        span = max(width, height)
        self._blooms = [
            (
                hex_to_rgb(b.color),
                b.x * width,
                b.y * height,
                max(1.0, b.radius * span),
                b.strength,
            )
            for b in palette.blooms
        ]
        # Tk discards a PhotoImage the moment its last Python reference goes
        # away, which shows up as a window that paints correctly and then
        # goes blank. Holding it on the instance is the fix.
        self._image: Optional[tk.PhotoImage] = None

    # ── The colour model ────────────────────────────────────────────────

    def color_at(self, x: float, y: float) -> Rgb:
        """The exact backdrop colour at a point: vertical ramp, then each
        bloom composited over it."""
        t = y / self.height if self.height else 0.0
        c = _lerp(self._top, self._bottom, t)
        for color, cx, cy, radius, strength in self._blooms:
            d = math.hypot(x - cx, y - cy) / radius
            if d < 1.0:
                falloff = 1.0 - d
                c = over(color, strength * falloff * falloff, c)
        return c

    def hex_at(self, x: float, y: float) -> str:
        return rgb_to_hex(self.color_at(x, y))

    def film(self, x: float, y: float, alpha: Optional[float] = None) -> str:
        """The opaque colour a translucent white panel would appear to be at
        this point. This is the glass."""
        if alpha is None:
            alpha = self.palette.glass_alpha
        return rgb_to_hex(over(self.palette.tint_rgb, alpha, self.color_at(x, y)))

    def hairline(self, x: float, y: float) -> str:
        """Border colour for a panel at this point — a slightly brighter film
        than the panel itself, which is what reads as an edge."""
        return self.film(x, y, self.palette.hairline_alpha)

    # ── Painting ────────────────────────────────────────────────────────

    def render(self) -> tk.PhotoImage:
        """Build (once) and return the backdrop image.

        Requires a Tk root to already exist, since PhotoImage needs an
        interpreter to allocate into.
        """
        if self._image is not None:
            return self._image

        s = self.scale
        w, h = max(1, self.width // s), max(1, self.height // s)
        # One string of "{#rrggbb #rrggbb ...} {...}" rows, handed to Tk in a
        # single put(). Per-pixel put() calls are orders of magnitude slower.
        rows: List[str] = []
        for row in range(h):
            y = row * s
            px = [rgb_to_hex(self.color_at(col * s, y)) for col in range(w)]
            rows.append("{" + " ".join(px) + "}")

        small = tk.PhotoImage(width=w, height=h)
        small.put(" ".join(rows))
        self._image = small.zoom(s) if s > 1 else small
        return self._image

    def attach(self, canvas: tk.Canvas) -> None:
        """Paint the backdrop as the bottom layer of `canvas`."""
        canvas.create_image(0, 0, image=self.render(), anchor="nw")


def _lerp(a: Rgb, b: Rgb, t: float) -> Rgb:
    t = max(0.0, min(1.0, t))
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


# ── Fonts ───────────────────────────────────────────────────────────────────

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
