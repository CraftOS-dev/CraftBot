"""Human-like input helpers of the Mini Browser (app/mini_browser/human.py)."""

import asyncio
import math
import random
from types import SimpleNamespace

import pytest

from app.mini_browser import human
from app.mini_browser.types import Tab


# ── pure helpers ────────────────────────────────────────────────────────────


def test_ease_in_out_is_monotonic_from_zero_to_one():
    samples = [human.ease_in_out(i / 200) for i in range(201)]
    assert samples[0] == 0.0 and samples[-1] == 1.0
    assert all(b >= a for a, b in zip(samples, samples[1:]))
    # Slow at both ends, fast in the middle.
    assert samples[10] - samples[0] < samples[105] - samples[95]
    assert human.ease_in_out(-1) == 0.0 and human.ease_in_out(2) == 1.0


def test_step_count_grows_with_distance_within_bounds():
    counts = [human.step_count(d) for d in (0, 1, 50, 300, 600, 1200, 5000)]
    assert all(human.MIN_STEPS <= c <= human.MAX_STEPS for c in counts)
    assert counts == sorted(counts)
    assert human.step_count(0) == human.MIN_STEPS
    assert human.step_count(10_000) == human.MAX_STEPS
    assert human.step_count(float("nan")) == human.MIN_STEPS


def test_bezier_path_ends_exactly_on_target_with_expected_steps():
    start, end = (10.0, 20.0), (900.0, 500.0)
    path = human.bezier_path(start, end, random.Random(1))
    assert len(path) == human.step_count(math.dist(start, end))
    assert path[-1] == end
    # Progress along the line never goes backwards (eased, no overshoot).
    along = [((x - 10) * 890 + (y - 20) * 480) for x, y in path]
    assert all(b >= a - 1e-6 for a, b in zip(along, along[1:]))


def test_bezier_path_is_deterministic_with_a_seeded_rng_and_varies_without():
    a = human.bezier_path((0, 0), (500, 300), random.Random(42))
    b = human.bezier_path((0, 0), (500, 300), random.Random(42))
    c = human.bezier_path((0, 0), (500, 300), random.Random(43))
    assert a == b
    assert a != c


def test_bezier_path_stays_inside_bounds():
    rng = random.Random(7)
    for _ in range(200):
        start = (rng.uniform(0, 1279), rng.uniform(0, 799))
        end = (rng.uniform(0, 1279), rng.uniform(0, 799))
        for x, y in human.bezier_path(start, end, rng, bounds=(1280, 800)):
            assert 0 <= x <= 1279 and 0 <= y <= 799


def test_bezier_path_short_moves_and_step_override():
    assert human.bezier_path((5, 5), (5.4, 5.2), random.Random(1)) == [(5.4, 5.2)]
    assert len(human.bezier_path((0, 0), (400, 0), random.Random(1), steps=5)) == 5


def test_target_point_lands_in_the_central_sixty_percent():
    box = {"x": 100.0, "y": 50.0, "width": 200.0, "height": 40.0}
    rng = random.Random(3)
    for _ in range(500):
        x, y = human.target_point(box, rng)
        assert 140.0 <= x <= 260.0
        assert 58.0 <= y <= 82.0
    assert human.target_point(box, random.Random(9)) == human.target_point(
        box, random.Random(9)
    )
    tiny = {"x": 10.0, "y": 10.0, "width": 1.0, "height": 1.0}
    assert human.target_point(tiny, rng) == (10.5, 10.5)


def test_typing_delays_have_a_human_rhythm():
    text = "Hello, world. How are you?" * 4
    delays = human.typing_delays(text, random.Random(5))
    assert len(delays) == len(text)
    low = human.TYPE_DELAY[0]
    high = human.TYPE_DELAY[1] + human.PUNCT_PAUSE[1]
    assert all(low <= d <= max(high, human.RARE_PAUSE[1]) for d in delays)
    punct = [d for ch, d in zip(text, delays) if ch in ",.?"]
    letters = [d for ch, d in zip(text, delays) if ch.isalpha()]
    assert sum(punct) / len(punct) > sum(letters) / len(letters)
    assert human.typing_delays(text, random.Random(5)) == delays


def test_scroll_steps_sum_exactly_and_keep_the_sign():
    rng = random.Random(11)
    for total in (1, 49, 50, 99, 100, 640, 1234, 5000):
        for sign in (1, -1):
            steps = human.scroll_steps(sign * total, rng)
            assert sum(steps) == sign * total
            assert all((s > 0) == (sign > 0) and s != 0 for s in steps)
            limit = human.WHEEL_STEP[1] + human.WHEEL_STEP[0] // 2
            assert all(abs(s) <= max(limit, total) for s in steps)
    assert human.scroll_steps(0) == []
    assert len(human.scroll_steps(5000, rng)) >= 5000 // (
        human.WHEEL_STEP[1] + human.WHEEL_STEP[0] // 2
    )


def test_split_runs_separates_keyed_from_inserted_text():
    assert human.split_runs("abc 日本語!\n") == [
        (True, "abc "),
        (False, "日本語"),
        (True, "!"),
        (False, "\n"),
    ]
    assert human.split_runs("") == []


# ── async movers (recording fake page, no browser) ──────────────────────────


class _Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        async def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return method


def _core(humanlike=True, show_cursor=True):
    published = []

    async def publish_pointer(tab, x, y, kind):
        published.append((x, y, kind))

    core = SimpleNamespace(
        settings=SimpleNamespace(humanlike=humanlike, show_cursor=show_cursor),
        viewport=(1280, 800),
        publish_pointer=publish_pointer,
    )
    return core, published


def _tab():
    page = SimpleNamespace(
        mouse=_Recorder(),
        keyboard=_Recorder(),
        viewport_size={"width": 1280, "height": 800},
    )
    return Tab(id="t1", page=page, owner="sess")


@pytest.fixture
def fast(monkeypatch):
    for name in (
        "STEP_DELAY",
        "HOVER_PAUSE",
        "PRESS_PAUSE",
        "DOUBLE_CLICK_GAP",
        "WHEEL_GAP",
    ):
        monkeypatch.setattr(human, name, (0.0, 0.0005))
    monkeypatch.setattr(human, "TYPE_DELAY", (0.0, 0.0005))
    monkeypatch.setattr(human, "SPACE_PAUSE", (0.0, 0.0005))
    monkeypatch.setattr(human, "PUNCT_PAUSE", (0.0, 0.0005))
    monkeypatch.setattr(human, "RARE_PAUSE", (0.0, 0.0005))


def test_move_mouse_follows_a_curve_and_publishes_the_pointer(fast):
    core, published = _core()
    tab = _tab()
    tab.mouse_x, tab.mouse_y = 100.0, 100.0
    asyncio.run(human.move_mouse(core, tab, 700, 400, rng=random.Random(2)))
    moves = [c for c in tab.page.mouse.calls if c[0] == "move"]
    assert len(moves) == human.step_count(math.dist((100, 100), (700, 400)))
    assert moves[-1][1] == (700.0, 400.0)
    assert (tab.mouse_x, tab.mouse_y) == (700.0, 400.0)
    assert published and published[-1] == (700.0, 400.0, "move")
    assert all(kind == "move" for _x, _y, kind in published)


def test_move_mouse_throttles_pointer_updates_to_thirty_per_second(fast, monkeypatch):
    clock = iter(i * 0.001 for i in range(10_000))  # 1 ms per step: far above 30/s
    monkeypatch.setattr(human, "_clock", lambda: next(clock))
    core, published = _core()
    tab = _tab()
    tab.mouse_x, tab.mouse_y = 0.0, 0.0
    asyncio.run(human.move_mouse(core, tab, 1200, 700, rng=random.Random(1)))
    moves = [c for c in tab.page.mouse.calls if c[0] == "move"]
    assert len(moves) == human.MAX_STEPS
    assert len(published) <= 3  # first, (maybe) one at 33 ms, and the final point
    assert published[-1][:2] == (1200.0, 700.0)


def test_move_mouse_without_humanlike_jumps_and_hides_cursor_when_disabled():
    core, published = _core(humanlike=False, show_cursor=False)
    tab = _tab()
    asyncio.run(human.move_mouse(core, tab, 5000, -20))  # clamped into the viewport
    assert tab.page.mouse.calls == [("move", (1279.0, 0.0), {})]
    assert published == []


def test_click_at_presses_and_releases_with_double_click_counts(fast):
    core, published = _core()
    tab = _tab()
    asyncio.run(human.click_at(core, tab, 50, 60, button="left", click_count=2))
    names = [
        (name, kwargs.get("click_count")) for name, _a, kwargs in tab.page.mouse.calls
    ]
    assert names == [("down", 1), ("up", 1), ("down", 2), ("up", 2)]
    assert [kind for _x, _y, kind in published] == ["down", "up", "down", "up", "click"]


def test_cancelled_click_releases_the_button_away_from_the_target(monkeypatch):
    core, _published = _core()
    tab = _tab()
    monkeypatch.setattr(human, "HOVER_PAUSE", (0.0, 0.0))
    monkeypatch.setattr(human, "PRESS_PAUSE", (5.0, 5.0))  # cancel while held

    async def scenario():
        task = asyncio.ensure_future(human.click_at(core, tab, 300, 300))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    calls = tab.page.mouse.calls
    assert [c[0] for c in calls] == ["down", "move", "up"]
    assert calls[1][1] == (0, 0)
    assert (tab.mouse_x, tab.mouse_y) == (0.0, 0.0)


def test_type_text_types_ascii_and_inserts_ime_text(fast):
    core, _ = _core()
    tab = _tab()
    asyncio.run(human.type_text(core, tab, "Hi 東京\nok"))
    calls = [(name, args[0]) for name, args, _k in tab.page.keyboard.calls]
    assert calls == [
        ("type", "H"),
        ("type", "i"),
        ("type", " "),
        ("insert_text", "東京\n"),
        ("type", "o"),
        ("type", "k"),
    ]


def test_type_text_long_text_types_a_prefix_then_inserts_the_rest(fast):
    core, _ = _core()
    tab = _tab()
    text = "x" * 3000
    asyncio.run(human.type_text(core, tab, text))
    calls = tab.page.keyboard.calls
    typed = [args[0] for name, args, _k in calls if name == "type"]
    inserted = "".join(args[0] for name, args, _k in calls if name == "insert_text")
    assert len(typed) == human.HUMAN_TYPED_PREFIX
    assert "".join(typed) + inserted == text
    assert all(
        len(args[0]) <= human.INSERT_CHUNK
        for n, args, _k in calls
        if n == "insert_text"
    )


def test_type_text_without_humanlike_types_runs_in_one_call():
    core, _ = _core(humanlike=False)
    tab = _tab()
    asyncio.run(human.type_text(core, tab, "hello 世界"))
    assert [(n, a[0]) for n, a, _k in tab.page.keyboard.calls] == [
        ("type", "hello "),
        ("insert_text", "世界"),
    ]


def test_wheel_scrolls_in_notches_summing_to_the_distance(fast):
    core, _ = _core()
    tab = _tab()
    asyncio.run(human.wheel(core, tab, -730, rng=random.Random(4)))
    deltas = [args[1] for name, args, _k in tab.page.mouse.calls if name == "wheel"]
    assert sum(deltas) == -730 and len(deltas) > 3

    core, _ = _core(humanlike=False)
    tab = _tab()
    asyncio.run(human.wheel(core, tab, 640))
    assert tab.page.mouse.calls == [("wheel", (0, 640.0), {})]


def test_publish_never_raises():
    async def broken(tab, x, y, kind):
        raise RuntimeError("bridge down")

    core = SimpleNamespace(
        settings=SimpleNamespace(humanlike=True, show_cursor=True),
        publish_pointer=broken,
    )
    asyncio.run(human.publish(core, _tab(), 1, 2, "move"))
