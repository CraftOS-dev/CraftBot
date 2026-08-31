"""Design tokens and colour maths for the installer window.

Deliberately imports nothing from tkinter: this is pure arithmetic, so it can
be unit-tested (and eyeballed) without a display. installer/ui/glass.py turns
these numbers into pixels.

## Why the colours are computed rather than hard-coded

Tk has no alpha channel. A widget is either fully opaque or, via
`-transparentcolor`, fully invisible — there is no "70% white over whatever is
behind me", which is the single effect the whole frosted-glass look rests on.

So we do the compositing ourselves. The backdrop is a gradient whose colour at
any height is a known function (see glass.Backdrop), which means the colour a
translucent panel *would* have at that height is also known: `over()` blends
the panel's tint onto the sampled backdrop and returns the opaque hex that
looks identical. Every panel in the window gets its fill this way, so the
"glass" tracks the gradient instead of sitting on it as a flat slab.

The same trick fixes rounded corners. CustomTkinter draws a frame's rounded
corners by filling the region *outside* the arc with the widget's `bg_color`,
which normally means the parent's colour. Over a gradient the parent has no
single colour, so a default `bg_color` leaves visible square shoulders on every
card. Passing the sampled backdrop as `bg_color` makes those shoulders match
what is behind them and the corners read as genuinely round.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence, Tuple

Rgb = Tuple[int, int, int]

__all__ = [
    "Rgb",
    "hex_to_rgb",
    "rgb_to_hex",
    "mix",
    "over",
    "Bloom",
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

    This is the function that makes the glass look work at all — see the
    module docstring for why Tk forces us to do it by hand.
    """
    return mix(base, top, alpha)


# ── Tokens ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Bloom:
    """A soft radial glow painted over the base gradient.

    Coordinates and radius are fractions of the window, so the same numbers
    describe the design at any window size.
    """

    color: str
    x: float  # centre, 0..1 across the width
    y: float  # centre, 0..1 down the height
    radius: float  # as a fraction of the window's larger edge
    strength: float  # peak alpha at the centre, fading to 0 at the edge


@dataclass(frozen=True)
class Palette:
    """Every colour in the window, in one place.

    The look is "liquid glass": a near-black ground lit unevenly by two
    coloured blooms, with panels that are barely-there white films over it.
    The only saturated colour in the entire window is the accent, which is
    why the single primary action reads instantly.
    """

    # Ground. A vertical ramp, darkest at the bottom, so the window has a
    # sense of light coming from above.
    base_top: str = "#14141F"
    base_bottom: str = "#08080D"

    # The coloured light. Orange is the brand; the indigo counterweight stops
    # the window reading as a monochrome-orange gradient and is what gives
    # the glass its faintly iridescent, Apple-ish cast.
    blooms: Sequence[Bloom] = field(
        default_factory=lambda: (
            Bloom("#FF4F18", x=0.86, y=-0.26, radius=1.15, strength=0.22),
            Bloom("#5B6BFF", x=0.04, y=1.16, radius=1.05, strength=0.24),
        )
    )

    # Glass films. Alphas, not colours — they get composited onto whatever
    # the backdrop happens to be at that height.
    glass_alpha: float = 0.055  # a standard panel
    glass_alpha_raised: float = 0.085  # hover / the status pill
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

    @property
    def tint_rgb(self) -> Rgb:
        return hex_to_rgb(self.tint)


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
