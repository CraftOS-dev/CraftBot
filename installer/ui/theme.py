"""Design tokens and colour maths for the installer window.

Deliberately imports nothing from tkinter: this is pure arithmetic, so it can
be unit-tested (and eyeballed) without a display.

## Why the surface colours are computed rather than written down

Tk has no alpha channel. A widget is either fully opaque or, via
`-transparentcolor`, fully invisible — there is no "8% white over whatever is
behind me", which is how every raised surface in this window is described.

So we composite ahead of time. The window is one flat colour, so the colour a
translucent film *would* be over it is a constant: `over()` blends the tint
onto `base` and returns the opaque hex that looks identical. `Palette.surface`
and friends are those constants.

That also fixes rounded corners for free. CustomTkinter fills the region
*outside* a corner's arc with the widget's `bg_color`; set it to `base` and
the shoulders match the window, so the corners read as genuinely round.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

Rgb = Tuple[int, int, int]

__all__ = [
    "Rgb",
    "hex_to_rgb",
    "rgb_to_hex",
    "mix",
    "over",
    "Palette",
    "PALETTE",
    "FONT_STACKS",
]


# ── Colour maths ────────────────────────────────────────────────────────────


def hex_to_rgb(value: str) -> Rgb:
    """'#FF4F18' -> (255, 79, 24)."""
    h = value.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(rgb: Rgb) -> str:
    """(255, 79, 24) -> '#ff4f18', clamped so callers can be sloppy."""
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def mix(a: Rgb, b: Rgb, t: float) -> Rgb:
    """Linear blend: t=0 gives `a`, t=1 gives `b`."""
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore


def over(top: Rgb, alpha: float, base: Rgb) -> Rgb:
    """Composite `top` at `alpha` onto opaque `base` (source-over).

    This is what makes the raised surfaces work at all — see the module
    docstring for why Tk forces us to do it by hand.
    """
    return mix(base, top, alpha)


# ── Tokens ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Palette:
    """Every colour in the window, in one place.

    One flat ground. An earlier version lit it with a gradient and two
    coloured blooms, which meant every widget had to sample the colour behind
    itself to disappear into it. Flat means the surfaces below are constants,
    and the only colour in the window that draws the eye is the accent — which
    is exactly the one the user is meant to press.
    """

    #: The window. Everything else is this, plus a little white.
    base: str = "#14141F"

    #: Films over `base`, as alphas. Resolved to hex by the properties below.
    surface_alpha: float = 0.055  # a control at rest
    surface_raised_alpha: float = 0.085  # hover
    hairline_alpha: float = 0.10  # 1px border
    tint: str = "#FFFFFF"

    # Ink.
    text: str = "#F2F2F6"
    text_dim: str = "#9C9CAB"
    text_faint: str = "#63636F"

    # Accent + semantic.
    accent: str = "#FF4F18"
    accent_hover: str = "#FF6A3B"
    accent_text: str = "#FFFFFF"
    green: str = "#4ADE80"
    amber: str = "#FBBF24"

    # ── Derived surfaces ────────────────────────────────────────────────
    # Computed, not written down, so changing `base` moves every surface with
    # it and they cannot drift apart.

    def film(self, alpha: float) -> str:
        """The opaque colour a white film at `alpha` would appear to be."""
        return rgb_to_hex(over(hex_to_rgb(self.tint), alpha, hex_to_rgb(self.base)))

    @property
    def surface(self) -> str:
        return self.film(self.surface_alpha)

    @property
    def surface_raised(self) -> str:
        return self.film(self.surface_raised_alpha)

    @property
    def hairline(self) -> str:
        return self.film(self.hairline_alpha)


PALETTE = Palette()


#: Font preferences per role, best first. Resolved against the fonts actually
#: installed (see glass.pick_font) because none of these ship everywhere:
#: Segoe UI Variable is Win11-only, SF Pro is macOS-only, and a minimal Linux
#: image may have neither. The final entry in each list is a family Tk always
#: resolves to *something* legible.
FONT_STACKS = {
    "display": [
        "SF Pro Display",  # macOS 11+
        "Segoe UI Variable Display",  # Windows 11
        "Segoe UI Semibold",  # Windows 10
        "Inter",
        "Ubuntu",
        "DejaVu Sans",
        "Helvetica",
    ],
    "ui": [
        "SF Pro Text",
        "Segoe UI Variable Text",
        "Segoe UI",
        "Inter",
        "Ubuntu",
        "DejaVu Sans",
        "Helvetica",
    ],
    "mono": [
        "SF Mono",
        "Menlo",
        "Cascadia Mono",
        "Consolas",
        "Ubuntu Mono",
        "DejaVu Sans Mono",
        "Courier",
    ],
}
