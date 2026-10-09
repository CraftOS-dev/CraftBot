"""Human-like pointer, keyboard and wheel input for agent operations.

Two layers:

- Pure helpers (``ease_in_out``, ``step_count``, ``bezier_path``,
  ``target_point``, ``typing_delays``, ``scroll_steps``) that only compute
  paths and timings. They take an optional ``rng`` (anything with the
  ``random.Random`` interface) so tests can make them deterministic.
- Async movers (``move_mouse``, ``click_at``, ``type_text``, ``wheel``) that
  drive ``tab.page.mouse`` / ``tab.page.keyboard`` on the Mini Browser host
  loop and mirror the agent's pointer to the live view through
  ``core.publish_pointer``.

When ``core.settings.humanlike`` is off the movers still do the same thing,
just without curves and pauses. Every await is a cancellation point, so a
cancelled operation stops typing or moving immediately.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Any, List, Optional, Sequence, Tuple

from app.logger import logger

Point = Tuple[float, float]

# Mouse paths: 12-35 steps depending on distance, ~8-16 ms per step.
MIN_STEPS = 12
MAX_STEPS = 35
FULL_STEPS_DISTANCE = 1200.0  # px from which a move uses MAX_STEPS
STEP_DELAY = (0.008, 0.016)
CURVE_SPREAD = 0.25  # max control-point offset as a fraction of the distance
CURVE_SPREAD_MAX = 180.0  # ... capped in px

# Clicks.
HOVER_PAUSE = (0.06, 0.16)
PRESS_PAUSE = (0.04, 0.12)
DOUBLE_CLICK_GAP = (0.07, 0.14)

# Typing rhythm (seconds after each character).
TYPE_DELAY = (0.035, 0.110)
SPACE_PAUSE = (0.02, 0.09)
PUNCT_PAUSE = (0.08, 0.22)
RARE_PAUSE = (0.15, 0.30)
RARE_PAUSE_CHANCE = 0.04
PUNCTUATION = frozenset(".,;:!?")
# Texts longer than this are typed humanly for HUMAN_TYPED_PREFIX characters
# and the rest is inserted at once (nobody wants to watch 2,000 keystrokes).
HUMAN_TYPED_LIMIT = 120
HUMAN_TYPED_PREFIX = 40
INSERT_CHUNK = 1000

# Wheel scrolling: notches of 70-130 px, 25-70 ms apart.
WHEEL_STEP = (70, 130)
WHEEL_GAP = (0.025, 0.07)

# The live view does not need more than ~30 pointer updates per second.
POINTER_MIN_INTERVAL = 1.0 / 30.0

DEFAULT_VIEWPORT = (1280, 800)

_SYSTEM_RNG = random.Random()
_clock = time.monotonic  # replaceable in tests (the event loop keeps the real one)


def _rng(rng: Any) -> Any:
    return rng if rng is not None else _SYSTEM_RNG


# ── pure helpers ────────────────────────────────────────────────────────────


def ease_in_out(t: float) -> float:
    """Smoothstep easing: 0 → 0, 1 → 1, monotonic, slow at both ends."""
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def step_count(distance: float) -> int:
    """Number of mouse-move steps for a path of ``distance`` CSS px."""
    if not math.isfinite(distance) or distance <= 0:
        return MIN_STEPS
    share = min(1.0, distance / FULL_STEPS_DISTANCE)
    return int(round(MIN_STEPS + (MAX_STEPS - MIN_STEPS) * share))


def _clamp_point(x: float, y: float, bounds: Optional[Tuple[float, float]]) -> Point:
    if bounds is None:
        return (x, y)
    width, height = bounds
    return (
        min(max(0.0, x), max(0.0, width - 1.0)),
        min(max(0.0, y), max(0.0, height - 1.0)),
    )


def bezier_path(
    start: Point,
    end: Point,
    rng: Any = None,
    *,
    steps: Optional[int] = None,
    bounds: Optional[Tuple[float, float]] = None,
) -> List[Point]:
    """Points of a cubic Bézier from ``start`` to ``end`` (start excluded).

    The two control points sit at random positions along the line, pushed
    sideways by a random offset, so every move bends a little differently.
    Points are sampled with ease-in-out timing (dense near both ends, like a
    hand accelerating and braking). The last point is exactly ``end``.
    ``bounds`` = (width, height) clamps every point into the viewport.
    """
    r = _rng(rng)
    x0, y0 = float(start[0]), float(start[1])
    x3, y3 = float(end[0]), float(end[1])
    dx, dy = x3 - x0, y3 - y0
    distance = math.hypot(dx, dy)
    if distance < 1.0:
        return [_clamp_point(x3, y3, bounds)]
    count = max(1, int(steps) if steps else step_count(distance))

    # Unit normal of the straight line; offsets bend the path sideways.
    nx, ny = -dy / distance, dx / distance
    spread = min(distance * CURVE_SPREAD, CURVE_SPREAD_MAX)
    offset1 = r.uniform(-spread, spread)
    # Same-side second offset most of the time: a gentle arc, not an "S".
    offset2 = offset1 * r.uniform(0.2, 1.0)
    along1 = r.uniform(0.15, 0.40)
    along2 = r.uniform(0.60, 0.85)
    c1x, c1y = x0 + dx * along1 + nx * offset1, y0 + dy * along1 + ny * offset1
    c2x, c2y = x0 + dx * along2 + nx * offset2, y0 + dy * along2 + ny * offset2

    points: List[Point] = []
    for index in range(1, count + 1):
        t = ease_in_out(index / count)
        u = 1.0 - t
        x = u * u * u * x0 + 3 * u * u * t * c1x + 3 * u * t * t * c2x + t * t * t * x3
        y = u * u * u * y0 + 3 * u * u * t * c1y + 3 * u * t * t * c2y + t * t * t * y3
        points.append(_clamp_point(x, y, bounds))
    points[-1] = _clamp_point(x3, y3, bounds)
    return points


def target_point(box: Any, rng: Any = None, *, fraction: float = 0.6) -> Point:
    """A random point inside the central ``fraction`` of an element box.

    ``box`` is a Playwright bounding box (``{x, y, width, height}``). The
    point leans towards the centre (triangular distribution), like a person
    aiming at a button rather than at its edge.
    """
    r = _rng(rng)
    x, y = float(box["x"]), float(box["y"])
    width, height = max(0.0, float(box["width"])), max(0.0, float(box["height"]))
    margin = (1.0 - min(1.0, max(0.0, fraction))) / 2.0
    cx, cy = x + width / 2.0, y + height / 2.0
    lo_x, hi_x = x + width * margin, x + width * (1.0 - margin)
    lo_y, hi_y = y + height * margin, y + height * (1.0 - margin)
    px = r.triangular(lo_x, hi_x, cx) if hi_x - lo_x >= 1.0 else cx
    py = r.triangular(lo_y, hi_y, cy) if hi_y - lo_y >= 1.0 else cy
    return (px, py)


def typing_delays(text: str, rng: Any = None) -> List[float]:
    """Seconds to wait after typing each character of ``text``.

    ~35-110 ms per key, a little longer after spaces, longer after
    punctuation, and now and then a 150-300 ms hesitation.
    """
    r = _rng(rng)
    delays: List[float] = []
    for char in text:
        delay = r.uniform(*TYPE_DELAY)
        if char == " ":
            delay += r.uniform(*SPACE_PAUSE)
        elif char in PUNCTUATION:
            delay += r.uniform(*PUNCT_PAUSE)
        if r.random() < RARE_PAUSE_CHANCE:
            delay = max(delay, r.uniform(*RARE_PAUSE))
        delays.append(delay)
    return delays


def scroll_steps(total: float, rng: Any = None) -> List[int]:
    """Split a scroll of ``total`` px into wheel notches (same sign, exact sum)."""
    r = _rng(rng)
    remaining = int(round(total))
    if remaining == 0:
        return []
    sign = 1 if remaining > 0 else -1
    remaining = abs(remaining)
    steps: List[int] = []
    while remaining > 0:
        notch = int(r.uniform(*WHEEL_STEP))
        if remaining - notch < WHEEL_STEP[0] // 2:
            notch = remaining  # fold a tiny tail into the last notch
        notch = min(notch, remaining)
        steps.append(sign * notch)
        remaining -= notch
    return steps


def is_typeable(char: str) -> bool:
    """True for characters typed as key presses (printable ASCII)."""
    return " " <= char <= "~"


def split_runs(text: str) -> List[Tuple[bool, str]]:
    """Split text into (typeable, run) pieces.

    Printable ASCII is typed key by key; everything else (CJK and other
    IME text, emoji, accented letters, newlines, tabs) is inserted as text,
    which is what an IME does and never presses Enter or Tab by accident.
    """
    runs: List[Tuple[bool, str]] = []
    for char in text:
        kind = is_typeable(char)
        if runs and runs[-1][0] == kind:
            runs[-1] = (kind, runs[-1][1] + char)
        else:
            runs.append((kind, char))
    return runs


# ── async movers ────────────────────────────────────────────────────────────


def _setting(core: Any, name: str, default: bool) -> bool:
    try:
        return bool(getattr(core.settings, name))
    except Exception:
        return default


def viewport_of(core: Any, tab: Any) -> Tuple[float, float]:
    """CSS px size of the tab's viewport (falls back to the core's default)."""
    size = None
    try:
        size = tab.page.viewport_size
    except Exception:
        size = None
    if size and size.get("width") and size.get("height"):
        return (float(size["width"]), float(size["height"]))
    try:
        width, height = core.viewport
        return (float(width), float(height))
    except Exception:
        return (float(DEFAULT_VIEWPORT[0]), float(DEFAULT_VIEWPORT[1]))


async def publish(core: Any, tab: Any, x: float, y: float, kind: str) -> None:
    """Mirror the agent pointer to the live view (best effort, never raises)."""
    if not _setting(core, "show_cursor", True):
        return
    try:
        await core.publish_pointer(tab, float(x), float(y), kind)
    except Exception as exc:
        logger.debug(f"[MiniBrowser] pointer publish failed: {type(exc).__name__}")


async def move_mouse(
    core: Any, tab: Any, x: float, y: float, *, rng: Any = None
) -> None:
    """Move the tab's mouse to (x, y) CSS px, along a curve when human-like."""
    page = tab.page
    bounds = viewport_of(core, tab)
    x, y = _clamp_point(float(x), float(y), bounds)
    if not _setting(core, "humanlike", True):
        await page.mouse.move(x, y)
        tab.mouse_x, tab.mouse_y = x, y
        await publish(core, tab, x, y, "move")
        return

    r = _rng(rng)
    if tab.mouse_x >= 0 and tab.mouse_y >= 0:
        start = (tab.mouse_x, tab.mouse_y)
    else:
        # Unknown position (fresh tab): enter from a plausible resting spot.
        start = (
            bounds[0] * r.uniform(0.35, 0.65),
            bounds[1] * r.uniform(0.55, 0.85),
        )
    path = bezier_path(start, (x, y), r, bounds=bounds)
    last_publish = float("-inf")
    for index, (px, py) in enumerate(path):
        await page.mouse.move(px, py)
        tab.mouse_x, tab.mouse_y = px, py
        now = _clock()
        if index == len(path) - 1 or now - last_publish >= POINTER_MIN_INTERVAL:
            last_publish = now
            await publish(core, tab, px, py, "move")
        if index < len(path) - 1:
            await asyncio.sleep(r.uniform(*STEP_DELAY))


async def _release_elsewhere(tab: Any, button: str, click_count: int) -> None:
    """Release a (possibly) pressed button away from the target.

    mousedown and mouseup then hit different elements, so no click event
    reaches the target.
    """
    try:
        await tab.page.mouse.move(0, 0)
        tab.mouse_x, tab.mouse_y = 0.0, 0.0
        await tab.page.mouse.up(button=button, click_count=click_count)
    except Exception:
        pass


async def click_at(
    core: Any,
    tab: Any,
    x: float,
    y: float,
    *,
    button: str = "left",
    click_count: int = 1,
    rng: Any = None,
) -> None:
    """Press and release at (x, y); the pointer must already be there.

    Hover pause, then down → short hold → up (twice for a double click).
    If the operation is cancelled while the button is held, the button is
    released away from the target, so a cancelled click never lands late.
    """
    page = tab.page
    r = _rng(rng)
    humanlike = _setting(core, "humanlike", True)
    total = max(1, int(click_count))
    if humanlike:
        await asyncio.sleep(r.uniform(*HOVER_PAUSE))
    for count in range(1, total + 1):
        held = True  # from the moment "down" is sent until "up" returns
        try:
            await page.mouse.down(button=button, click_count=count)
            await publish(core, tab, x, y, "down")
            if humanlike:
                await asyncio.sleep(r.uniform(*PRESS_PAUSE))
            await page.mouse.up(button=button, click_count=count)
            held = False
        except asyncio.CancelledError:
            if held:
                await asyncio.shield(_release_elsewhere(tab, button, count))
            raise
        await publish(core, tab, x, y, "up")
        if count < total and humanlike:
            await asyncio.sleep(r.uniform(*DOUBLE_CLICK_GAP))
    await publish(core, tab, x, y, "click")


async def _insert(page: Any, text: str) -> None:
    for start in range(0, len(text), INSERT_CHUNK):
        await page.keyboard.insert_text(text[start : start + INSERT_CHUNK])


async def type_text(core: Any, tab: Any, text: str, *, rng: Any = None) -> None:
    """Type ``text`` into the focused element.

    Human-like: key by key with a natural rhythm. Texts longer than
    HUMAN_TYPED_LIMIT get their first HUMAN_TYPED_PREFIX characters typed
    and the rest inserted. Non-ASCII text (Japanese, emoji, ...), newlines
    and tabs are always inserted, like an IME commit.
    """
    if not text:
        return
    page = tab.page
    r = _rng(rng)
    humanlike = _setting(core, "humanlike", True)
    if len(text) > HUMAN_TYPED_LIMIT:
        typed, rest = text[:HUMAN_TYPED_PREFIX], text[HUMAN_TYPED_PREFIX:]
    else:
        typed, rest = text, ""

    for keyed, run in split_runs(typed):
        if not keyed:
            await _insert(page, run)
            if humanlike:
                await asyncio.sleep(r.uniform(*TYPE_DELAY))
            continue
        if not humanlike:
            await page.keyboard.type(run)
            continue
        for char, delay in zip(run, typing_delays(run, r)):
            await page.keyboard.type(char)
            await asyncio.sleep(delay)
    if rest:
        await _insert(page, rest)


async def wheel(core: Any, tab: Any, delta_y: float, *, rng: Any = None) -> None:
    """Scroll with the mouse wheel at the current pointer position."""
    page = tab.page
    if not _setting(core, "humanlike", True):
        await page.mouse.wheel(0, float(delta_y))
        return
    r = _rng(rng)
    steps: Sequence[int] = scroll_steps(delta_y, r)
    for index, step in enumerate(steps):
        await page.mouse.wheel(0, step)
        if index < len(steps) - 1:
            await asyncio.sleep(r.uniform(*WHEEL_GAP))


def jitter(scale: float, rng: Any = None) -> float:
    """A random offset in [-scale, scale]."""
    return _rng(rng).uniform(-scale, scale)


async def pause(low: float, high: float, *, core: Any = None, rng: Any = None) -> None:
    """Sleep a random human pause (skipped when human-like input is off)."""
    if core is not None and not _setting(core, "humanlike", True):
        return
    await asyncio.sleep(_rng(rng).uniform(low, high))
