#!/usr/bin/env python3
"""Render the installer window's logo frames from craftbot_logo_1.png.

    python scripts/build_installer_marks.py

Writes installer/ui/assets/craftbot_mark_<size>[_blink<n>].png — the mark at
each DPI scale, plus the frames of its blink.

They live inside the installer package, not in the repo's assets/ directory.
assets/ is documentation and marketing imagery, and — more concretely — it is
NOT excluded from the agent payload, so these shipped inside CraftBot-src.zip
for a window the agent never renders. Under installer/ they are excluded by
the rule that already keeps the wizard out of the payload, and bundled by the
spec entry that already ships the installer package.

## Why these are generated ahead of time and committed

The installer window cannot do this at runtime:

  * Tk scales a PhotoImage only by integer subsample/zoom, so asking it to
    put the 3000px source at 96px gives a badly aliased mark.
  * Pillow could resample properly, but it is ~3 MB in a 17 MB installer
    that exists to be small, and the installer needs nothing else from it.

So the resampling happens here and the results are committed. They are 34 KB
in total, and committing them keeps the release build free of any image
processing step.

## What it does to the source

The icon draws the robot on a dark rounded-square tile. On the window's
gradient that tile reads as a box, so it is removed: a pixel survives if it
is bright OR saturated, which keeps the white head and the orange antenna and
eyes while dropping the near-black tile.

The blink frames redraw the eye bars shorter about their own centre — a lid
closing rather than the eye sliding. Eye geometry is MEASURED from the image
rather than hard-coded, so a redesigned logo still produces correct frames.

Deliberately Pillow-only, no numpy: Pillow is already a dependency, and every
mask below is built with channel operations that run in C rather than a
per-pixel Python loop over nine million pixels.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageChops, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "craftbot_logo_1.png"
OUT_DIR = REPO_ROOT / "installer" / "ui" / "assets"

#: One per DPI scale the window supports (100%, 150%, 200%).
SIZES = (96, 144, 192)

#: Openness of the eye bars per blink frame. Frame 0 is the open mark itself.
BLINK = (0.55, 0.22, 0.06)

#: Tile removal thresholds. The tile is near-black and grey; the head is
#: white and the details are vivid orange, so these separate cleanly.
MIN_LUMA = 70
MIN_SATURATION = 60


def _threshold(channel: Image.Image, cutoff: int) -> Image.Image:
    """0/255 mask of pixels above `cutoff`."""
    return channel.point(lambda v: 255 if v > cutoff else 0)


def _saturation(rgb: Image.Image) -> Image.Image:
    """max(r,g,b) - min(r,g,b), per pixel, without leaving C."""
    r, g, b = rgb.split()[:3]
    high = ImageChops.lighter(ImageChops.lighter(r, g), b)
    low = ImageChops.darker(ImageChops.darker(r, g), b)
    return ImageChops.subtract(high, low)


def strip_tile(img: Image.Image) -> Image.Image:
    """Drop the dark rounded-square tile, keeping the robot."""
    rgb = img.convert("RGB")
    keep = ImageChops.lighter(
        _threshold(rgb.convert("L"), MIN_LUMA),
        _threshold(_saturation(rgb), MIN_SATURATION),
    )
    out = img.copy()
    # multiply by a 0/255 mask == keep the original alpha, or zero it.
    out.putalpha(ImageChops.multiply(img.split()[3], keep))
    return out


def square(img: Image.Image) -> Image.Image:
    """Crop to content, then centre on a square canvas so the window can
    place the mark without per-size arithmetic."""
    img = img.crop(img.getbbox())
    w, h = img.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2))
    return canvas


def find_eyes(master: Image.Image) -> List[Tuple[int, int, int, int]]:
    """Bounding boxes of the two eye bars, measured from the image.

    Measured rather than hard-coded so this still works if the logo is
    redrawn. The antenna is the same orange as the eyes and sits above the
    head, so everything above the head's top edge (plus a margin) is excluded
    before the remaining orange is split into columns.
    """
    rgb = master.convert("RGB")
    r, g, b = rgb.split()
    orange = ImageChops.darker(
        ImageChops.darker(_threshold(r, 150), _threshold(g, 160).point(lambda v: 255 - v)),
        _threshold(b, 120).point(lambda v: 255 - v),
    )
    white = ImageChops.darker(
        ImageChops.darker(_threshold(r, 200), _threshold(g, 200)), _threshold(b, 200)
    )
    head = white.getbbox()
    if head is None:
        raise SystemExit("could not locate the head: is the source logo correct?")

    w, h = master.size
    body = orange.crop((0, head[1] + int(h * 0.05), w, h))
    # Column occupancy, then split on the gap between the two bars.
    occupied = [x for x in range(w) if body.crop((x, 0, x + 1, body.height)).getbbox()]
    if not occupied:
        raise SystemExit("could not locate the eyes in the source logo")
    groups: List[List[int]] = [[occupied[0]]]
    for x in occupied[1:]:
        if x - groups[-1][-1] <= 2:
            groups[-1].append(x)
        else:
            groups.append([x])

    boxes = []
    offset = head[1] + int(h * 0.05)
    for cols in groups:
        strip = body.crop((cols[0], 0, cols[-1] + 1, body.height))
        bb = strip.getbbox()
        boxes.append((cols[0], bb[1] + offset, cols[-1], bb[3] + offset - 1))
    return boxes


def main() -> int:
    if not SOURCE.is_file():
        print(f"source logo not found: {SOURCE}")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Everything is drawn at the source's own resolution and resampled ONCE
    # per output. Going via an intermediate master would downsample twice and
    # soften the open mark, which is the frame on screen almost all the time.
    master = square(strip_tile(Image.open(SOURCE).convert("RGBA")))

    boxes = find_eyes(master)
    if len(boxes) != 2:
        print(f"expected 2 eye bars, measured {len(boxes)}: {boxes}")
        return 1
    x0, y0, x1, y1 = boxes[0]
    eye_rgb = master.getpixel(((x0 + x1) // 2, (y0 + y1) // 2))[:3]
    print(f"eyes at {boxes}, colour {eye_rgb}")

    written = 0
    for size in SIZES:
        master.resize((size, size), Image.LANCZOS).save(
            OUT_DIR / f"craftbot_mark_{size}.png", optimize=True
        )
        written += 1

    for index, openness in enumerate(BLINK, start=1):
        frame = master.copy()
        draw = ImageDraw.Draw(frame)
        for ex0, ey0, ex1, ey1 in boxes:
            # Erase the bar, then redraw it shorter about its own centre.
            draw.rectangle([ex0 - 1, ey0 - 1, ex1 + 1, ey1 + 1], fill=(255, 255, 255, 255))
            half = max(1, int((ey1 - ey0) * openness / 2))
            centre = (ey0 + ey1) // 2
            radius = (ex1 - ex0) // 2
            draw.rounded_rectangle(
                [ex0, centre - half, ex1, centre + half],
                radius=min(radius, half),
                fill=eye_rgb + (255,),
            )
        for size in SIZES:
            frame.resize((size, size), Image.LANCZOS).save(
                OUT_DIR / f"craftbot_mark_{size}_blink{index}.png", optimize=True
            )
            written += 1

    print(f"wrote {written} files to {OUT_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
