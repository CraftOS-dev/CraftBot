"""Regression tests for the agent-operation review fixes (ops.py, login.py).

Browser tests run against a real headless Chromium (skipped cleanly when it
is not installed); the rest are plain unit tests.
"""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from app.mini_browser import human, login, ops
from app.mini_browser.errors import MiniBrowserError
from app.mini_browser.observe import observe
from tests.mini_browser_fixtures import (
    FakeCore,
    FakeVault,
    LocalServer,
    launch_browser_or_skip,
)

PASSWORD = "Zq9-Secr3t!pw#77 ~*"
USER = "alice@example.test"


@pytest.fixture(scope="module")
def browser():
    harness = launch_browser_or_skip()
    yield harness
    harness.close()


@pytest.fixture(scope="module")
def server():
    srv = LocalServer()
    yield srv
    srv.close()


@pytest.fixture
def fast_human(monkeypatch):
    for name in (
        "STEP_DELAY",
        "HOVER_PAUSE",
        "PRESS_PAUSE",
        "DOUBLE_CLICK_GAP",
        "WHEEL_GAP",
        "TYPE_DELAY",
        "SPACE_PAUSE",
        "PUNCT_PAUSE",
        "RARE_PAUSE",
    ):
        monkeypatch.setattr(human, name, (0.0, 0.002))


class TabsCore(FakeCore):
    """FakeCore that also keeps the open tabs (like BrowserCore.tabs)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tabs = {}
        self.status = "ready"


def run(browser, html_or_url, scenario, *, core=None):
    async def runner():
        if isinstance(html_or_url, str) and html_or_url.startswith("http"):
            tab = await browser.new_tab(url=html_or_url)
        else:
            tab = await browser.new_tab(html_or_url)
        the_core = core or FakeCore()
        if isinstance(getattr(the_core, "tabs", None), dict):
            the_core.tabs[tab.id] = tab
        try:
            await observe(the_core, tab, compact=True)
            return await scenario(the_core, tab)
        finally:
            await browser.close_tab(tab)

    return browser.run(runner())


async def expect_error(coro, code):
    try:
        await coro
    except MiniBrowserError as exc:
        assert exc.code == code, (exc.code, exc.fields)
        return exc
    raise AssertionError(f"expected {code}")


async def frames_ready(page, count, timeout_s=10.0):
    """Wait until ``count`` child frames have loaded their documents."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        frames = page.main_frame.child_frames
        if len(frames) >= count:
            states = []
            for frame in frames:
                try:
                    states.append(await frame.evaluate("document.readyState"))
                except Exception:
                    states.append("")
            if all(state == "complete" for state in states):
                return
        await asyncio.sleep(0.05)
    raise AssertionError(f"frames did not load: {page.frames}")


def element(result, *needles):
    page = result.get("page") if isinstance(result.get("page"), dict) else result
    for line in page.get("elements") or []:
        if all(needle in line for needle in needles):
            return int(line[1 : line.index("]")])
    raise AssertionError(f"no element with {needles}: {page.get('elements')}")


# ── TYPE-1: date / time / month / week / colour / slider inputs ─────────────

WHOLE_VALUES = """
<script>window.events = [];</script>
<label for=d>Check-in date</label><input id=d type=date>
<label for=t>Arrival time</label><input id=t type=time>
<label for=m>Card expiry month</label><input id=m type=month>
<label for=w>Week</label><input id=w type=week>
<label for=dt>Pick-up</label><input id=dt type=datetime-local>
<label for=c>Colour</label><input id=c type=color value="#000000">
<label for=r>Volume</label><input id=r type=range min=0 max=100 step=10 value=20>
<script>
for (const el of document.querySelectorAll('input')) {
  el.addEventListener('input', () => window.events.push('input:' + el.id));
  el.addEventListener('change', () => window.events.push('change:' + el.id));
}
</script>
"""


async def _values(tab, *ids):
    return await tab.page.evaluate(
        "(ids) => ids.map((id) => document.getElementById(id).value)", list(ids)
    )


@pytest.mark.parametrize("humanlike", [True, False])
def test_whole_value_inputs_are_set_in_their_html_format(
    browser, fast_human, humanlike
):
    cases = [
        ("Check-in date", "2026-10-01", "d", "2026-10-01"),
        ("Arrival time", "2:30 PM", "t", "14:30"),
        ("Card expiry month", "2027/3", "m", "2027-03"),
        ("Week", "2026-W5", "w", "2026-W05"),
        ("Pick-up", "2026-10-01 09:05", "dt", "2026-10-01T09:05"),
        ("Colour", "#ABC", "c", "#aabbcc"),
    ]

    async def scenario(core, tab):
        results = []
        for label, text, _id, _want in cases:
            obs = await observe(core, tab, compact=True)
            n = element(obs, f'"{label}"')
            results.append(await ops.type_text(core, tab, element_id=n, text=text))
        obs = await observe(core, tab, compact=True)
        slider = await ops.type_text(
            core, tab, element_id=element(obs, '"Volume"'), text="55"
        )
        values = await _values(tab, *[c[2] for c in cases], "r")
        return results, slider, values, await tab.page.evaluate("window.events")

    results, slider, values, events = run(
        browser, WHOLE_VALUES, scenario, core=FakeCore(humanlike=humanlike)
    )
    assert values[:-1] == [want for *_rest, want in cases]
    for result, (*_rest, want) in zip(results, cases):
        assert result["status"] == "success"
        assert result["message"].startswith("Set element") and want in result["message"]
    # The slider takes the nearest value its step allows, and says so.
    assert values[-1] == "60"
    assert "to 60" in slider["message"] and "nearest" in slider["message"]
    # Frameworks see a normal edit: input and change events.
    for field in ("d", "t", "m", "c", "r"):
        assert f"input:{field}" in events and f"change:{field}" in events


def test_whole_value_inputs_refuse_ambiguous_or_impossible_values(browser):
    html = WHOLE_VALUES + (
        "<label for=g>Guarded date</label><input id=g type=date>"
        "<script>g.addEventListener('input', () => { g.value = '2030-01-01'; });</script>"
    )

    async def scenario(core, tab):
        obs = await observe(core, tab, compact=True)
        date_id = element(obs, '"Check-in date"')
        ambiguous = await expect_error(
            ops.type_text(core, tab, element_id=date_id, text="10/01/2026"),
            "MINI_BROWSER_INVALID_INPUT",
        )
        impossible = await expect_error(
            ops.type_text(core, tab, element_id=date_id, text="2026-02-30"),
            "MINI_BROWSER_INVALID_INPUT",
        )
        colour = await expect_error(
            ops.type_text(
                core, tab, element_id=element(obs, '"Colour"'), text="blue-ish"
            ),
            "MINI_BROWSER_INVALID_INPUT",
        )
        guarded = await expect_error(
            ops.type_text(
                core, tab, element_id=element(obs, '"Guarded date"'), text="2026-10-01"
            ),
            "MINI_BROWSER_INVALID_INPUT",
        )
        return ambiguous, impossible, colour, guarded, await _values(tab, "d")

    ambiguous, impossible, colour, guarded, (date_value,) = run(browser, html, scenario)
    assert "YYYY-MM-DD" in ambiguous.fields["detail"]
    assert "10/01/2026" in ambiguous.fields["detail"]
    assert "YYYY-MM-DD" in impossible.fields["detail"]
    assert "#rrggbb" in colour.fields["detail"]
    assert "did not keep" in guarded.fields["detail"]
    assert "2030-01-01" in guarded.fields["detail"]
    assert date_value == ""  # nothing half-typed was left behind


@pytest.mark.parametrize(
    "kind, text, expected",
    [
        ("date", "2026-10-01", "2026-10-01"),
        ("date", "2026/1/5", "2026-01-05"),
        ("date", "2026.10.01", "2026-10-01"),
        ("date", "2026年10月1日", "2026-10-01"),
        ("date", "10/01/2026", None),
        ("date", "01.10.2026", None),
        ("date", "2026-13-01", None),
        ("date", "next friday", None),
        ("time", "14:30", "14:30"),
        ("time", "9:05", "09:05"),
        ("time", "12:00 am", "00:00"),
        ("time", "12:15 PM", "12:15"),
        ("time", "14:30:15", "14:30:15"),
        ("time", "14:30:00", "14:30"),
        ("time", "25:00", None),
        ("time", "13:00 pm", None),
        ("datetime-local", "2026-10-01T14:30", "2026-10-01T14:30"),
        ("datetime-local", "2026/10/01 2:30 pm", "2026-10-01T14:30"),
        ("datetime-local", "2026-10-01", None),
        ("month", "2026-10", "2026-10"),
        ("month", "2026年3月", "2026-03"),
        ("month", "2026-13", None),
        ("week", "2026-W40", "2026-W40"),
        ("week", "2026W7", "2026-W07"),
        ("week", "2026-W54", None),
        ("color", "#1A73E8", "#1a73e8"),
        ("color", "fff", "#ffffff"),
        ("color", "red", None),
        ("range", "55", "55"),
        ("range", "2.5", "2.5"),
        ("range", "-3", "-3"),
        ("range", "nan", None),
        ("range", "lots", None),
    ],
)
def test_normalise_input_value(kind, text, expected):
    assert ops.normalise_input_value(kind, text) == expected


def test_a_text_field_still_empty_after_typing_is_a_failure(browser):
    html = """
    <label for=n>Guests</label><input id=n type=number>
    <label for=pw>Password</label><input id=pw type=password>
    <label for=q>Name</label><input id=q>
    """

    async def scenario(core, tab):
        obs = await observe(core, tab, compact=True)
        letters = await expect_error(
            ops.type_text(core, tab, element_id=element(obs, '"Guests"'), text="abc"),
            "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
        )
        obs = await observe(core, tab, compact=True)
        number = await ops.type_text(
            core, tab, element_id=element(obs, '"Guests"'), text="4"
        )
        obs = await observe(core, tab, compact=True)
        secret = await ops.type_text(
            core, tab, element_id=element(obs, '"Password"'), text="hunter22"
        )
        obs = await observe(core, tab, compact=True)
        name = await ops.type_text(
            core, tab, element_id=element(obs, '"Name"'), text="Jo"
        )
        return letters, number, secret, name

    letters, number, secret, name = run(browser, html, scenario)
    assert "still empty after typing" in letters.fields["detail"]
    assert number["status"] == secret["status"] == name["status"] == "success"


# ── NAV-1: results that arrive by XHR / fetch after the click ──────────────

FETCHING = """<title>Flights</title>
<button id=go>Search flights</button><div id=res></div>
<script>
document.getElementById('go').addEventListener('click', () => {
  document.getElementById('res').textContent = '';
  fetch('/api/flights-PATH').then(r => r.text()).then(t => {
    document.getElementById('res').textContent = t;
  });
});
</script>"""


def test_a_click_waits_for_the_data_it_requested(browser, server):
    server.add("/api/flights-slow", "JL 101 - 08:00 - 12,300 yen", delay=1.2)
    url = server.add("/flights-slow", FETCHING.replace("PATH", "slow"))

    async def scenario(core, tab):
        started = time.monotonic()
        result = await ops.click(core, tab, element_id=0)
        return result, time.monotonic() - started

    result, seconds = run(browser, url, scenario)
    assert "JL 101" in result["page"]["text"]
    assert result["message"] == "Clicked element 0."
    assert seconds < ops.DATA_WAIT_S + 3


def test_a_click_whose_data_is_still_loading_says_so(browser, server, monkeypatch):
    monkeypatch.setattr(ops, "DATA_WAIT_S", 0.8)
    server.add("/api/flights-stuck", "late", delay=4.0)
    url = server.add("/flights-stuck", FETCHING.replace("PATH", "stuck"))

    async def scenario(core, tab):
        return await ops.click(core, tab, element_id=0)

    result = run(browser, url, scenario)
    assert "may still be updating" in result["message"]
    assert "mini_browser_wait" in result["message"]


def test_ad_and_analytics_requests_are_not_waited_for():
    watch = ops.NavWatch(SimpleNamespace(main_frame=object()))

    class Request:
        def __init__(self, url, kind):
            self.url, self.resource_type, self.frame = url, kind, None

        def is_navigation_request(self):
            return False

    def request(url, kind="fetch"):
        return Request(url, kind)

    watch._on_request(request("https://www.google-analytics.com/g/collect?v=2"))
    watch._on_request(request("https://stats.example.com/ping", kind="ping"))
    assert not watch.busy and watch.requests == 1
    data = request("https://api.example.com/search?q=x")
    watch._on_request(data)
    assert watch.busy
    watch._on_request_failed(data)  # blocked / failed counts as finished
    assert not watch.busy


# ── TABS-1 (ops side): a click that opens a new tab says so ────────────────


def test_a_click_that_opens_a_new_tab_says_so(browser, server):
    server.add("/help", "<title>Help</title><h1>Help center</h1>")
    url = server.add(
        "/opener",
        "<title>Home</title><a href='/help' target='_blank'>Open help center</a>",
    )

    async def scenario(core, tab):
        return await ops.click(core, tab, element_id=0)

    result = run(browser, url, scenario)
    assert result["message"] == "Clicked element 0. It opened a new tab."


def test_a_new_tab_the_core_registered_is_left_to_the_core_to_report():
    popup = SimpleNamespace(is_closed=lambda: False)
    core = SimpleNamespace(tabs={"t2": SimpleNamespace(page=popup)})
    assert asyncio.run(ops._await_adoption(core, [popup])) is True
    assert asyncio.run(ops._await_adoption(SimpleNamespace(), [popup])) is False


# ── C8 / CONC-4 / CTRL-1: take control stops an operation in flight ────────

TWO_FIELDS = """<title>Two fields</title>
<form id=f action="/submitted" method=get>
  <label for=a>Field A</label><input id=a name=a style="width:400px">
  <label for=b>Field B</label><input id=b name=b style="width:400px">
</form>
<script>window.clicks = 0;</script>
<button id=late disabled onclick="window.clicks++">Late</button>
<script>setTimeout(() => document.getElementById('late').disabled = false, 600);</script>
"""


@pytest.mark.parametrize("submit", [False, True])
def test_typing_stops_once_the_user_takes_control(browser, server, monkeypatch, submit):
    monkeypatch.setattr(human, "TYPE_DELAY", (0.03, 0.03))
    for name in (
        "SPACE_PAUSE",
        "PUNCT_PAUSE",
        "RARE_PAUSE",
        "STEP_DELAY",
        "HOVER_PAUSE",
    ):
        monkeypatch.setattr(human, name, (0.0, 0.0))
    url = server.add("/two-fields", TWO_FIELDS)
    text = "The quick brown fox jumps over the lazy dog"

    async def scenario(core, tab):
        typing = asyncio.ensure_future(
            ops.type_text(core, tab, element_id=0, text=text, submit=submit)
        )
        for _ in range(200):  # until the agent has typed a few characters
            await asyncio.sleep(0.02)
            typed = await tab.page.evaluate("document.getElementById('a').value")
            if len(typed) >= 3:
                break
        # The user clicks Field B in the live view: the core marks the tab
        # as theirs BEFORE their click reaches the page.
        tab.user_control = True
        await tab.page.focus("#b")
        error = await expect_error(typing, "MINI_BROWSER_USER_IN_CONTROL")
        await asyncio.sleep(0.3)
        values = await _values(tab, "a", "b")
        return error, values, tab.page.url, list(tab.events)

    error, (field_a, field_b), page_url, events = run(
        browser, url, scenario, core=FakeCore(humanlike=True)
    )
    assert field_b == ""  # nothing of the agent's text landed in the user's field
    assert 0 < len(field_a) < len(text)
    assert text.startswith(field_a)
    assert page_url.endswith("/two-fields")  # Enter was never pressed
    notes = [e["message"] for e in events if e["kind"] == "notice"]
    assert any(
        f"stopped after {len(field_a)} of {len(text)} characters" in n for n in notes
    ), notes
    assert ("Enter was not pressed" in notes[-1]) is submit


def test_a_click_is_not_sent_once_the_user_took_control(browser, server, fast_human):
    url = server.add("/late-click", TWO_FIELDS)

    async def scenario(core, tab):
        obs = await observe(core, tab, compact=True)
        clicking = asyncio.ensure_future(
            ops.click(core, tab, element_id=element(obs, '"Late"'))
        )
        await asyncio.sleep(0.2)  # still waiting for the button to be enabled
        tab.user_control = True
        await expect_error(clicking, "MINI_BROWSER_USER_IN_CONTROL")
        await asyncio.sleep(0.8)
        return await tab.page.evaluate("window.clicks")

    assert run(browser, url, scenario, core=FakeCore(humanlike=True)) == 0


def test_scroll_and_login_do_nothing_once_the_user_took_control(browser, server):
    url = server.add(
        "/control-login",
        "<title>Sign in</title><div style='height:3000px'>tall</div>"
        "<form><input id=u type=email autocomplete=username aria-label=Email>"
        "<input id=p type=password autocomplete=current-password aria-label=Password>"
        "<button>Sign in</button></form>",
    )
    vault = FakeVault(
        [{"id": "e1", "site": "127.0.0.1", "username": USER, "password": PASSWORD}]
    )

    async def scenario(core, tab):
        tab.user_control = True
        await expect_error(
            ops.scroll(core, tab, direction="down"), "MINI_BROWSER_USER_IN_CONTROL"
        )
        await expect_error(ops.login(core, tab), "MINI_BROWSER_USER_IN_CONTROL")
        scrolled = await tab.page.evaluate("window.scrollY")
        return scrolled, await _values(tab, "u", "p"), list(tab.filled_secrets)

    scrolled, values, secrets = run(
        browser, url, scenario, core=FakeCore(humanlike=True, vault=vault)
    )
    assert scrolled == 0 and values == ["", ""] and secrets == []


# ── C5 / CONC-5: mini_browser_wait(for_user=true) ───────────────────────────


@pytest.fixture
def quick_polls(monkeypatch):
    monkeypatch.setattr(ops, "FOR_USER_POLL_S", 0.05)
    monkeypatch.setattr(ops, "SLEEP_SLICE_S", 0.05)
    monkeypatch.setattr(ops, "TEXT_POLL_S", 0.05)


def test_wait_for_user_waits_for_the_user_to_take_and_hand_back(browser, quick_polls):
    async def scenario(core, tab):
        async def user():
            await asyncio.sleep(0.3)
            tab.user_control = True  # e.g. they clicked into the tab
            await asyncio.sleep(0.4)
            tab.user_control = False  # "Hand back"

        started = time.monotonic()
        acting = asyncio.ensure_future(user())
        result = await ops.wait(core, tab, for_user=True, timeout_ms=10000)
        await acting
        return result, time.monotonic() - started

    result, seconds = run(browser, "<p>CAPTCHA</p>", scenario)
    assert result["status"] == "success"
    assert result["message"].startswith("The user handed control back.")
    assert 0.6 <= seconds < 5


@pytest.mark.parametrize(
    "reason, code",
    [("tab", "MINI_BROWSER_TAB_CLOSED"), ("browser", "MINI_BROWSER_CLOSED")],
)
def test_waits_end_at_once_when_the_tab_or_browser_closes(
    browser, quick_polls, reason, code
):
    async def scenario(core, tab):
        outcomes = []
        for params in (
            {"for_user": True, "timeout_ms": 30000},
            {"text": "never there", "timeout_ms": 30000},
            {"seconds": 30.0},
        ):
            tab.closed, tab.closed_reason = False, None
            tab.user_control = bool(params.get("for_user"))

            async def close_soon():
                await asyncio.sleep(0.3)
                tab.mark_closed(reason)

            closer = asyncio.ensure_future(close_soon())
            started = time.monotonic()
            error = await expect_error(ops.OPS["wait"](core, tab, **params), code)
            await closer
            tab.closed_event.clear()
            outcomes.append((error, time.monotonic() - started))
        return outcomes

    core = TabsCore()
    core.status = "ready" if reason == "tab" else "stopped"
    for _error, seconds in run(browser, "<p>x</p>", scenario, core=core):
        assert seconds < 3


def test_wait_for_user_ends_when_the_core_drops_the_tab(browser, quick_polls):
    async def scenario(core, tab):
        tab.user_control = True

        async def close_soon():
            await asyncio.sleep(0.3)
            core.tabs.clear()  # e.g. the browser was torn down

        closer = asyncio.ensure_future(close_soon())
        started = time.monotonic()
        core.status = "stopped"
        error = await expect_error(
            ops.wait(core, tab, for_user=True, timeout_ms=30000), "MINI_BROWSER_CLOSED"
        )
        await closer
        return error, time.monotonic() - started

    _error, seconds = run(browser, "<p>x</p>", scenario, core=TabsCore())
    assert seconds < 3


# ── e2e NAV-1: a navigation cut short by the browser closing ────────────────


def test_a_navigation_interrupted_by_the_browser_closing_is_not_a_success(
    browser, server
):
    slow = server.add("/very-slow", "<title>Slow</title>slow", delay=3.0)

    async def scenario(core, tab):
        async def close_browser():
            await asyncio.sleep(0.5)
            core.status = "stopped"
            tab.mark_closed("browser")
            await tab.page.close()

        closer = asyncio.ensure_future(close_browser())
        error = await expect_error(
            ops.OPS["navigate"](core, tab, url=slow, timeout_ms=20000),
            "MINI_BROWSER_CLOSED",
        )
        await closer
        return error

    run(browser, "<p>start</p>", scenario, core=TabsCore())


def test_an_aborted_load_does_not_claim_the_page_opened(browser, server):
    start = server.add("/start-page", "<title>Start</title><p>start</p>")
    empty = server.add("/no-content", "", status=204)

    async def scenario(core, tab):
        return await ops.navigate(core, tab, url=empty)

    result = run(browser, start, scenario)
    assert not result["message"].startswith("Opened")
    assert result["message"].startswith(f"Did not open {empty}")
    assert "the tab still shows " + start in result["message"]


# ── frames (OBS-5): elements inside an iframe can be used by their id ──────


def test_elements_inside_a_frame_are_listed_and_usable(browser, server, fast_human):
    server.add(
        "/booking-widget",
        "<form><label>Name <input id=name></label>"
        "<button type=button onclick=\"document.getElementById('out').textContent="
        "'Booked for ' + document.getElementById('name').value\">Book</button>"
        "<p id=out></p></form>",
    )
    url = server.add(
        "/restaurant",
        "<title>Trattoria</title><h1>Trattoria</h1>"
        "<iframe title='Booking' src='/booking-widget' style='width:500px;height:200px'></iframe>",
    )

    async def scenario(core, tab):
        await frames_ready(tab.page, 1)
        obs = await observe(core, tab, compact=True)
        name = element(obs, '"Name"', "in frame")
        typed = await ops.type_text(core, tab, element_id=name, text="Ada")
        book = element(typed, '"Book"', "in frame")
        clicked = await ops.click(core, tab, element_id=book)
        frame = tab.page.frames[1]
        return (
            obs,
            clicked,
            await frame.evaluate("document.getElementById('out').textContent"),
        )

    obs, clicked, out = run(browser, url, scenario, core=FakeCore(humanlike=True))
    assert any(line.startswith('[0] frame "Booking"') for line in obs["elements"])
    assert out == "Booked for Ada"
    assert "Booked for Ada" in clicked["page"].get("frame_text", "")


def test_frames_of_other_sites_are_expanded_when_they_matter(browser, server):
    """A cross-origin frame with fields (a booking or payment widget) is
    expanded in every observation; one with only buttons (an embedded
    player) only in a full read, so it does not crowd every step."""
    server.add(
        "/player",
        "<button>Play</button><button>Mute</button><button>Full screen</button>",
    )
    server.add("/signup-widget", "<label>Email <input type=email></label>")
    url = server.add(
        "/embeds",
        "<title>Embeds</title><h1>Embeds</h1>"
        f"<iframe title='Video' src='{server.url('/player', host='localhost')}' "
        "style='width:400px;height:150px'></iframe>"
        f"<iframe title='Newsletter' src='{server.url('/signup-widget', host='localhost')}' "
        "style='width:400px;height:150px'></iframe>",
    )

    async def scenario(core, tab):
        await frames_ready(tab.page, 2)
        compact = await observe(core, tab, compact=True)
        full = await observe(core, tab, compact=False)
        return compact, full

    compact, full = run(browser, url, scenario)
    video = next(line for line in compact["elements"] if '"Video"' in line)
    assert "content of another site" in video
    assert not any('"Play"' in line for line in compact["elements"])
    assert any('"Email"' in line and "in frame" in line for line in compact["elements"])
    assert any('"Play"' in line and "in frame" in line for line in full["elements"])
    # A frame's elements follow the frame itself.
    index = {line.split("]")[0]: i for i, line in enumerate(full["elements"])}
    frame_line = next(i for i, line in enumerate(full["elements"]) if '"Video"' in line)
    play_line = next(i for i, line in enumerate(full["elements"]) if '"Play"' in line)
    assert play_line == frame_line + 1, index


# ── LOGIN-1 / LOGIN-2: honest outcomes and C5-consistent advice ────────────


def _state(**kwargs):
    base = {
        "pwVisible": False,
        "messages": [],
        "code": False,
        "captcha": False,
        "signOut": False,
        "title": "",
        "headings": [],
        "bodyHead": "",
    }
    base.update(kwargs)
    return base


LOGIN_PAGE = _state(
    pwVisible=True, title="Sign in", headings=["Sign in"], bodyHead="Email Password"
)


@pytest.mark.parametrize(
    "after, url_after, expected",
    [
        # Wrong password: a failure page without alert markup.
        (
            _state(
                title="Sign-in problem",
                headings=["Sign-in failed"],
                bodyHead="Sign-in failed\nYour account is locked.",
            ),
            "https://x.test/session",
            ("error", "Sign-in failed"),
        ),
        # The form came back with a plain paragraph error.
        (
            _state(
                pwVisible=True,
                title="Sign in",
                headings=["Sign in"],
                bodyHead="The password you entered is incorrect.\nEmail Password",
            ),
            "https://x.test/login?email=a",
            ("error", "The password you entered is incorrect."),
        ),
        # Push approval / "verify it's you".
        (
            _state(title="2-Step Verification", headings=["Check your phone"]),
            "https://x.test/approve",
            ("needs_verification", "approve"),
        ),
        (
            _state(title="Account", headings=["Welcome"]),
            "https://x.test/challenge/pwd",
            ("needs_verification", "approve"),
        ),
        # A code field.
        (
            _state(code=True, title="Verify", headings=["Enter the code"]),
            "https://x.test/login/verify",
            ("needs_verification", "code"),
        ),
        # Positive evidence: the sign-in address was left.
        (
            _state(title="Your account", headings=["Welcome back, Jo"]),
            "https://x.test/account",
            ("signed_in", ""),
        ),
        # Positive evidence: a sign-out control appeared (same address).
        (
            _state(title="Dashboard", signOut=True),
            "https://x.test/login",
            ("signed_in", ""),
        ),
        # Form gone, still on a sign-in address, no evidence: unknown.
        (
            _state(title="Please wait", headings=["Loading"]),
            "https://x.test/login",
            ("unknown", "gone"),
        ),
        # Same form, nothing said: unknown, never signed in.
        (LOGIN_PAGE, "https://x.test/login", ("unknown", "form")),
        (LOGIN_PAGE, "https://x.test/session", ("unknown", "form")),
    ],
)
def test_decide_outcome_needs_positive_evidence(after, url_after, expected):
    outcome, said, kind = login.decide_outcome(
        LOGIN_PAGE, after, "https://x.test/login", url_after
    )
    assert outcome == expected[0], (outcome, said, kind)
    if outcome == "error":
        assert said == expected[1]
    else:
        assert kind == expected[1]


def test_a_failure_hint_the_login_page_already_showed_does_not_count():
    before = _state(pwVisible=True, bodyHead="Too many attempts lock your account.")
    after = _state(pwVisible=True, bodyHead="Too many attempts lock your account.")
    assert login.decide_outcome(before, after, "https://x/login", "https://x/login")[
        0
    ] == ("unknown")


@pytest.fixture(scope="module")
def login_pages(server):
    form = (
        "<title>Sign in</title><form method=post action='ACTION'>"
        "<label>Email <input type=email name=email autocomplete=username></label>"
        "<label>Password <input type=password name=password "
        "autocomplete=current-password></label><button>Sign in</button></form>"
    )
    pages = {
        "/lp-locked": "<title>Sign-in problem</title><h1>Sign-in failed</h1>"
        "<p>Your account is locked. Try again later.</p>",
        "/lp-push": "<title>2-Step Verification</title><h1>Check your phone</h1>"
        "<p>Tap Yes on the notification to verify it's you.</p>",
        "/lp-ok": "<title>Your account</title><h1>Welcome back</h1>"
        "<a href='/logout'>Sign out</a>",
        "/lp-captcha": "<title>Verify</title><iframe title='reCAPTCHA challenge' "
        "src='about:blank' style='width:300px;height:150px'></iframe>",
    }
    for path, body in pages.items():
        server.add(path, body)
        server.add("/login" + path, form.replace("ACTION", path))
    return server


@pytest.mark.parametrize(
    "path, status, outcome, words",
    [
        ("/lp-locked", "error", "error", "Sign-in failed"),
        ("/lp-push", "success", "needs_verification", "confirm the sign-in"),
        ("/lp-ok", "success", "signed_in", "Signed in as"),
        ("/lp-captcha", "success", "captcha", "take control of this tab"),
    ],
)
def test_login_reports_failure_pages_and_verification_steps(
    browser, login_pages, path, status, outcome, words
):
    vault = FakeVault(
        [{"id": "e1", "site": "127.0.0.1", "username": USER, "password": PASSWORD}]
    )

    async def scenario(core, tab):
        return await ops.login(core, tab)

    result = run(
        browser, login_pages.url("/login" + path), scenario, core=FakeCore(vault=vault)
    )
    assert result["status"] == status and result["outcome"] == outcome, result
    assert words in result["message"]
    if outcome in ("captcha", "needs_verification"):
        assert "mini_browser_wait with for_user=true" in result["message"]
    assert PASSWORD not in json.dumps(result, ensure_ascii=False)


# ── e2e SEC-1: a password never comes back encoded (GET sign-in form) ──────


def test_a_password_in_the_address_never_reaches_results(browser, server):
    server.add(
        "/get-done", "<title>Done</title><h1>Welcome</h1><a href=/logout>Sign out</a>"
    )
    url = server.add(
        "/get-login",
        "<title>Sign in</title><form method=get action='/get-done'>"
        "<input name=user autocomplete=username aria-label=User>"
        "<input name=pass type=password autocomplete=current-password aria-label=Password>"
        "<button>Sign in</button></form>",
    )
    vault = FakeVault(
        [{"id": "e1", "site": "127.0.0.1", "username": USER, "password": PASSWORD}]
    )

    async def scenario(core, tab):
        result = await ops.login(core, tab)
        page_url = tab.page.url
        full = await ops.read(core, tab)
        return result, full, page_url

    result, full, page_url = run(browser, url, scenario, core=FakeCore(vault=vault))
    assert "pass=" in page_url  # the site put the password in its address...
    from urllib.parse import quote, quote_plus

    dumped = json.dumps([result, full], ensure_ascii=False)
    for spelling in (
        PASSWORD,
        quote_plus(PASSWORD, safe=""),
        quote(PASSWORD, safe=""),
        page_url.split("pass=", 1)[1],
    ):
        assert spelling not in dumped, spelling  # ...and none of it came back
