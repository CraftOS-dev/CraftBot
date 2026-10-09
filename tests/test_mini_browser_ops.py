"""Agent operations (app/mini_browser/ops.py, login.py) on a real Chromium page."""

import asyncio
import json
import os
import socket
import sys
from pathlib import Path
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

PASSWORD = "S3cret-Pa55word!"
USER = "alice@example.com"


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
    """Human-like code paths, minus most of the waiting."""
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


@pytest.fixture
def short_waits(monkeypatch):
    monkeypatch.setattr(ops, "ACTION_WAIT_MS", 1200)


def run(browser, html_or_url, scenario, *, core=None, viewport=(1280, 800)):
    """Open a tab (HTML or URL), observe it, run ``scenario(core, tab)``."""

    async def runner():
        if isinstance(html_or_url, str) and html_or_url.startswith("http"):
            tab = await browser.new_tab(url=html_or_url, viewport=viewport)
        else:
            tab = await browser.new_tab(html_or_url, viewport=viewport)
        try:
            the_core = core or FakeCore()
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


# ── navigate & read ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def site(server):
    server.add("/a", "<title>Page A</title><h1>Alpha</h1><a href='/b'>to b</a>")
    server.add("/b", "<title>Page B</title><h1>Bravo</h1><button>Hi</button>")
    server.add("/hop", "<title>Hop</title><script>location.replace('/b')</script>")
    server.add("/slow", "<title>Slow</title>", delay=3.0)
    return server


def test_navigate_returns_a_fresh_observation_and_follows_redirects(browser, site):
    async def scenario(core, tab):
        first = await ops.navigate(core, tab, url=site.url("/a"))
        second = await ops.navigate(core, tab, url=site.url("/hop"))
        return first, second

    first, second = run(browser, "<p>start</p>", scenario)
    assert first["status"] == "success"
    assert first["page"]["url"] == site.url("/a") and first["page"]["title"] == "Page A"
    assert '[0] link "to b" → /b' in first["page"]["elements"]
    assert "Opened " + site.url("/a") in first["message"]
    assert second["page"]["url"] == site.url("/b")
    assert "Bravo" in second["page"]["text"]


def test_navigate_history_steps(browser, site):
    async def scenario(core, tab):
        await ops.navigate(core, tab, url=site.url("/a"))
        await ops.navigate(core, tab, url=site.url("/b"))
        back = await ops.navigate(core, tab, url="back")
        forward = await ops.navigate(core, tab, url="forward")
        reload = await ops.navigate(core, tab, url="reload")
        return back, forward, reload

    back, forward, reload = run(browser, site.url("/a"), scenario)
    assert back["page"]["url"] == site.url("/a")
    assert forward["page"]["url"] == site.url("/b")
    assert reload["message"].startswith("Reloaded")

    async def at_start(core, tab):
        return await ops.navigate(core, tab, url="forward")

    result = run(browser, site.url("/a"), at_start)
    assert "no page to go forward" in result["message"]


def test_navigate_refuses_the_app_ui_and_unsafe_schemes(browser, site):
    async def scenario(core, tab):
        codes = []
        for url in (
            site.url("/a"),
            site.url("/a", host="localhost"),
            f"http://127.1:{site.port}/a",
            "file:///C:/Windows/win.ini",
            "javascript:alert(1)",
            "data:text/html,hi",
        ):
            exc = await expect_error(
                ops.navigate(core, tab, url=url), "MINI_BROWSER_BLOCKED_URL"
            )
            codes.append(exc.fields.get("reason"))
        return codes, tab.page.url

    core = FakeCore(ui_origins={f"127.0.0.1:{site.port}"})
    reasons, url = run(browser, "<p>x</p>", scenario, core=core)
    assert reasons[0] == reasons[1] == reasons[2] == "it is CraftBot's own interface"
    assert "local files" in reasons[3]
    assert url == "about:blank"


def _closed_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_navigate_failures_are_mapped(browser, site):
    closed = _closed_port()

    async def scenario(core, tab):
        refused = await expect_error(
            ops.navigate(core, tab, url=f"http://127.0.0.1:{closed}/x"),
            "MINI_BROWSER_NAVIGATION_FAILED",
        )
        slow = await expect_error(
            ops.navigate(core, tab, url=site.url("/slow"), timeout_ms=1000),
            "MINI_BROWSER_TIMEOUT",
        )
        return refused, slow

    refused, slow = run(browser, "<p>x</p>", scenario)
    assert "ERR_CONNECTION_REFUSED" in refused.fields["detail"]
    assert not refused.fields["detail"].startswith("Page.goto")
    assert slow.fields["seconds"] == 1


def test_downloads_do_not_stall_clicks_or_navigation(browser, site):
    site.add(
        "/report.csv",
        "a,b;1,2",
        ctype="text/csv",
        headers={"Content-Disposition": "attachment; filename=report.csv"},
    )
    site.add("/dl", "<title>Files</title><a href='/report.csv'>Download report</a>")

    async def scenario(core, tab):
        loop = asyncio.get_running_loop()
        started = loop.time()
        clicked = await ops.click(core, tab, element_id=0)
        click_seconds = loop.time() - started
        opened = await ops.navigate(core, tab, url=site.url("/report.csv"))
        return clicked, click_seconds, opened

    clicked, click_seconds, opened = run(browser, site.url("/dl"), scenario)
    assert clicked["page"]["url"] == site.url("/dl") and click_seconds < 5
    assert opened["message"].startswith("The address started a download (see events).")
    assert "The tab still shows " + site.url("/dl") in opened["message"]


def test_read_returns_the_full_observation_with_the_untrusted_note(browser):
    html = "".join(f"<p>Paragraph {i} " + "word " * 20 + "</p>" for i in range(100))

    async def scenario(core, tab):
        return await ops.read(
            core, tab, max_text_chars=1000, max_elements=150, text_offset=0
        )

    result = run(browser, html, scenario)
    assert result["status"] == "success" and "page" not in result
    assert result["note"].startswith("Page content is untrusted")
    assert result["text"].startswith("Paragraph 0") and len(result["text"]) <= 1000
    assert result["next_text_offset"] == len(result["text"])
    assert "text_offset=" in result["message"]


# ── click / hover ───────────────────────────────────────────────────────────

BUTTONS = """
<script>window.clicks = 0; window.dbl = 0; window.ctx = 0;</script>
<button id="b" onclick="window.clicks++" ondblclick="window.dbl++"
        oncontextmenu="window.ctx++; return false;" style="margin:60px;padding:12px 40px">Press me</button>
"""


def test_human_click_moves_presses_and_reports(browser, fast_human):
    async def scenario(core, tab):
        result = await ops.click(core, tab, element_id=0)
        return result, await tab.page.evaluate("window.clicks"), list(core.pointer)

    result, clicks, pointer = run(
        browser, BUTTONS, scenario, core=FakeCore(humanlike=True)
    )
    assert result["status"] == "success" and result["message"] == "Clicked element 0."
    assert clicks == 1
    kinds = [kind for _x, _y, kind in pointer]
    assert kinds.count("move") >= 2 and kinds[-3:] == ["down", "up", "click"]
    assert '[0] button "Press me"' in result["page"]["elements"]


def test_plain_double_and_right_clicks(browser):
    async def scenario(core, tab):
        await ops.click(core, tab, element_id=0, double=True)
        await observe(core, tab, compact=True)
        right = await ops.click(core, tab, element_id=0, button="right")
        counts = await tab.page.evaluate("[window.clicks, window.dbl, window.ctx]")
        return right, counts, core.pointer

    right, counts, pointer = run(browser, BUTTONS, scenario)
    assert counts == [2, 1, 1]
    assert right["message"] == "Right-clicked element 0."
    assert pointer[-1][2] == "click"


def test_click_that_navigates_returns_the_new_page(browser, site, fast_human):
    async def scenario(core, tab):
        return await ops.click(core, tab, element_id=0)

    result = run(browser, site.url("/a"), scenario, core=FakeCore(humanlike=True))
    assert result["page"]["url"] == site.url("/b")
    assert result["page"]["title"] == "Page B"


def test_stale_and_unknown_element_ids_fail_loudly(browser):
    async def scenario(core, tab):
        await tab.page.set_content("<button>Other</button><button>Second</button>")
        stale = await expect_error(
            ops.click(core, tab, element_id=0), "MINI_BROWSER_ELEMENT_NOT_FOUND"
        )
        await observe(core, tab, compact=True)
        unknown = await expect_error(
            ops.click(core, tab, element_id=99), "MINI_BROWSER_ELEMENT_NOT_FOUND"
        )
        clicked = await ops.click(core, tab, element_id=1)
        return stale, unknown, clicked

    stale, unknown, clicked = run(browser, BUTTONS, scenario)
    assert stale.fields["element_id"] == 0 and unknown.fields["element_id"] == 99
    assert clicked["status"] == "success"


def test_covered_or_disabled_elements_are_not_clicked(browser, short_waits, fast_human):
    html = """
    <script>window.clicks = 0</script>
    <button onclick="window.clicks++">Buy now</button>
    <button disabled onclick="window.clicks++">Disabled</button>
    <div id="cookie" style="position:fixed;left:0;top:0;width:100%;height:120px;background:#eee">
      We use cookies
    </div>
    """

    async def scenario(core, tab):
        covered = await expect_error(
            ops.click(core, tab, element_id=0), "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE"
        )
        disabled = await expect_error(
            ops.click(core, tab, element_id=1), "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE"
        )
        return covered, disabled, await tab.page.evaluate("window.clicks")

    core = FakeCore(humanlike=True)
    covered, disabled, clicks = run(browser, html, scenario, core=core)
    assert "covered by another element (<div#cookie>" in covered.fields["detail"]
    assert "disabled" in disabled.fields["detail"]
    assert clicks == 0


def test_a_cancelled_click_never_lands_late(browser):
    html = """
    <script>window.clicks = 0;
      setTimeout(() => document.getElementById('late').disabled = false, 1200);</script>
    <button id="late" disabled onclick="window.clicks++">Late</button>
    """

    async def scenario(core, tab):
        task = asyncio.ensure_future(ops.click(core, tab, element_id=0))
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(2.0)  # long after the button became clickable
        return await tab.page.evaluate("window.clicks")

    assert run(browser, html, scenario) == 0


def test_hover_reveals_a_menu(browser, fast_human):
    html = """
    <div tabindex="0" style="padding:20px;width:200px"
         onmouseenter="document.getElementById('sub').style.display='block'">Products</div>
    <a id="sub" href="#laptops" style="display:none">Laptops</a>
    """

    for humanlike in (True, False):
        result = run(
            browser,
            html,
            lambda core, tab: ops.hover(core, tab, element_id=0),
            core=FakeCore(humanlike=humanlike),
        )
        assert result["message"] == "Moved the pointer over element 0."
        assert any('"Laptops"' in e for e in result["page"]["elements"])


# ── typing & keys ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def form_page(server):
    server.add("/done", "<title>Done</title><p>Submitted</p>")
    return server.add(
        "/form",
        """<title>Form</title>
        <form action="/done" method="get">
          <input name="name" value="old value" aria-label="Name">
          <input type="email" name="email" value="a@b.c" aria-label="Email">
          <textarea name="bio" aria-label="Bio"></textarea>
          <div contenteditable="true" aria-label="Notes"></div>
          <select aria-label="Size"><option>S</option></select>
          <input type="checkbox" aria-label="Agree">
          <button type="submit">Send</button>
        </form>""",
    )


async def _values(tab):
    return await tab.page.evaluate(
        """() => ({name: document.querySelector('[name=name]').value,
                   email: document.querySelector('[name=email]').value,
                   bio: document.querySelector('[name=bio]').value,
                   notes: document.querySelector('[contenteditable]').innerText})"""
    )


def test_type_replaces_appends_and_inserts_ime_text(browser, form_page, fast_human):
    long_text = "The quick brown fox jumps over the lazy dog. " * 8

    async def scenario(core, tab):
        replaced = await ops.type_text(core, tab, element_id=0, text="Ada Lovelace")
        await ops.type_text(core, tab, element_id=0, text=" Jr.", clear=False)
        await ops.type_text(core, tab, element_id=1, text="x", clear=False)
        await ops.type_text(core, tab, element_id=2, text="東京タワー 😀 ok\nline two")
        await ops.type_text(core, tab, element_id=3, text=long_text)
        return replaced, await _values(tab), tab.page.url

    replaced, values, url = run(
        browser, form_page, scenario, core=FakeCore(humanlike=True)
    )
    assert replaced["message"] == "Typed 12 characters into element 0."
    assert '[0] input:text "Name" value="Ada Lovelace"' in replaced["page"]["elements"]
    assert values["name"] == "Ada Lovelace Jr."
    assert values["email"] == "a@b.cx"
    assert values["bio"] == "東京タワー 😀 ok\nline two"
    assert values["notes"].replace("\xa0", " ").strip() == long_text.strip()
    assert url.endswith("/form")  # the newline did not submit anything


def test_type_with_submit_presses_enter_and_follows_the_navigation(browser, form_page):
    async def scenario(core, tab):
        return await ops.type_text(core, tab, element_id=0, text="Grace", submit=True)

    result = run(browser, form_page, scenario)
    assert result["message"] == "Typed 5 characters into element 0 and pressed Enter."
    assert "/done?name=Grace" in result["page"]["url"]
    assert result["page"]["title"] == "Done"


def test_type_refuses_fields_that_need_another_action(browser, form_page):
    async def scenario(core, tab):
        select = await expect_error(
            ops.type_text(core, tab, element_id=4, text="M"),
            "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
        )
        box = await expect_error(
            ops.type_text(core, tab, element_id=5, text="x"),
            "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
        )
        cleared = await ops.type_text(core, tab, element_id=0, text="")
        return select, box, cleared, await _values(tab)

    select, box, cleared, values = run(browser, form_page, scenario)
    assert "mini_browser_select_option" in select.fields["detail"]
    assert "mini_browser_click" in box.fields["detail"]
    assert cleared["message"] == "Cleared element 0." and values["name"] == ""


KEYS = """
<input id="a" aria-label="A"><input id="b" aria-label="B"><input id="c" aria-label="C">
<script>window.keys = [];
document.addEventListener('keydown', (e) => window.keys.push(
  (e.ctrlKey ? 'C+' : '') + (e.metaKey ? 'M+' : '') + (e.shiftKey ? 'S+' : '') + e.key));</script>
"""


def test_press_key_combos_and_sequences(browser):
    async def scenario(core, tab):
        first = await ops.press_key(core, tab, keys="Tab Tab", element_id=0)
        focus1 = await tab.page.evaluate("document.activeElement.id")
        await ops.press_key(core, tab, keys="shift + tab")
        focus2 = await tab.page.evaluate("document.activeElement.id")
        await ops.press_key(core, tab, keys="ControlOrMeta+a")
        await ops.press_key(core, tab, keys="esc ArrowDown")
        unknown = await expect_error(
            ops.press_key(core, tab, keys="Hyperspace"), "MINI_BROWSER_INVALID_INPUT"
        )
        return first, focus1, focus2, await tab.page.evaluate("window.keys"), unknown

    first, focus1, focus2, keys, unknown = run(browser, KEYS, scenario)
    assert first["message"] == "Pressed Tab Tab in element 0."
    assert (focus1, focus2) == ("c", "b")
    assert keys[:3] == ["Tab", "Tab", "S+Shift"] or keys[:2] == ["Tab", "Tab"]
    assert "S+Tab" in keys
    assert "C+a" in keys or "M+a" in keys
    assert keys[-2:] == ["Escape", "ArrowDown"]
    assert "Hyperspace" in unknown.fields["detail"]


def test_parse_keys_normalises_aliases():
    assert ops.parse_keys("ctrl+shift+t") == ["Control+Shift+t"]
    assert ops.parse_keys("Cmd+K, Enter") == ["Meta+K", "Enter"]
    assert ops.parse_keys("pgdn f5 Control++") == ["PageDown", "F5", "Control++"]
    with pytest.raises(MiniBrowserError):
        ops.parse_keys("   ")
    with pytest.raises(MiniBrowserError):
        ops.parse_keys("++")
    assert ops.parse_keys("+") == ["+"]
    assert ops.parse_keys(",") == [","]


# ── select ──────────────────────────────────────────────────────────────────

SELECT = """
<script>window.changes = 0</script>
<label for="s">Size</label>
<select id="s" onchange="window.changes++">
  <option value="">Choose…</option><option value="s">Small</option>
  <option value="m">Medium</option><option value="l" disabled>Large</option>
</select>
<label class="pretty">Colour
  <select id="c" style="display:none"><option value="r">Red</option><option value="g">Green</option></select>
</label>
<button>Not a select</button>
"""


def test_select_option_by_label_or_value(browser, fast_human):
    async def scenario(core, tab):
        by_label = await ops.select_option(core, tab, element_id=0, value="medium")
        value1 = await tab.page.evaluate("document.getElementById('s').value")
        await observe(core, tab, compact=True)
        await ops.select_option(core, tab, element_id=0, value="s")
        value2 = await tab.page.evaluate("document.getElementById('s').value")
        await observe(core, tab, compact=True)
        hidden = await ops.select_option(core, tab, element_id=1, value="Green")
        colour = await tab.page.evaluate("document.getElementById('c').value")
        missing = await expect_error(
            ops.select_option(core, tab, element_id=0, value="XL"),
            "MINI_BROWSER_INVALID_INPUT",
        )
        disabled = await expect_error(
            ops.select_option(core, tab, element_id=0, value="Large"),
            "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
        )
        not_select = await expect_error(
            ops.select_option(core, tab, element_id=2, value="x"),
            "MINI_BROWSER_ELEMENT_NOT_INTERACTABLE",
        )
        changes = await tab.page.evaluate("window.changes")
        return (
            by_label,
            value1,
            value2,
            hidden,
            colour,
            missing,
            disabled,
            not_select,
            changes,
        )

    out = run(browser, SELECT, scenario, core=FakeCore(humanlike=True))
    by_label, value1, value2, hidden, colour, missing, disabled, not_select, changes = (
        out
    )
    assert by_label["message"] == 'Selected "Medium" in element 0.'
    assert '[0] select "Size" = "Medium"' in by_label["page"]["elements"][0]
    assert (value1, value2, colour, changes) == ("m", "s", "g", 2)
    assert "Options: Choose…, Small, Medium, Large" in missing.fields["detail"]
    assert "disabled" in disabled.fields["detail"]
    assert "not a dropdown list" in not_select.fields["detail"]
    assert hidden["status"] == "success"


# ── scroll ──────────────────────────────────────────────────────────────────

LONG = "<h1>Top</h1>" + "".join(
    f'<p style="height:120px">Row {i}</p>' for i in range(60)
)
INNER = """
<body style="margin:0;overflow:hidden">
  <div id="main" style="height:100vh;overflow:auto">
    <div style="height:4000px">tall content <a href="#">link</a></div>
  </div>
</body>
"""


def test_scroll_down_bottom_and_top(browser, fast_human):
    async def scenario(core, tab):
        down = await ops.scroll(core, tab, direction="down", amount=600)
        bottom = await ops.scroll(core, tab, direction="bottom")
        again = await ops.scroll(core, tab, direction="down")
        top = await ops.scroll(core, tab, direction="top")
        up = await ops.scroll(core, tab, direction="up")
        return down, bottom, again, top, up

    core = FakeCore(humanlike=True)
    down, bottom, again, top, up = run(
        browser, LONG, scenario, core=core, viewport=(1000, 700)
    )
    assert down["scrolled"] is True and down["page"]["scroll"]["y"] == 600
    assert down["message"] == "Scrolled down 600 px."
    assert bottom["at_bottom"] is True and bottom["page"]["scroll"]["at_bottom"] is True
    assert (
        again["scrolled"] is False
        and again["message"] == "Did not scroll: already at the bottom."
    )
    assert top["scrolled"] is True and top["page"]["scroll"]["y"] == 0
    assert up["message"] == "Did not scroll: already at the top."


def test_scroll_moves_an_inner_scroll_area(browser):
    async def scenario(core, tab):
        result = await ops.scroll(core, tab, direction="down", amount=500)
        return result, await tab.page.evaluate(
            "document.getElementById('main').scrollTop"
        )

    result, inner = run(browser, INNER, scenario)
    assert result["scrolled"] is True and inner == 500
    assert result["page"]["scroll"]["y"] == 500


# ── wait ────────────────────────────────────────────────────────────────────


def test_wait_for_text_seconds_and_settle(browser):
    html = "<div id='out'></div><script>setTimeout(() => out.textContent = 'Order confirmed', 400)</script>"

    async def scenario(core, tab):
        found = await ops.wait(core, tab, text="order CONFIRMED", timeout_ms=5000)
        missing = await expect_error(
            ops.wait(core, tab, text="never there", timeout_ms=1000),
            "MINI_BROWSER_TIMEOUT",
        )
        slept = await ops.wait(core, tab, seconds=0.2)
        settled = await ops.wait(core, tab)
        return found, missing, slept, settled

    found, missing, slept, settled = run(browser, html, scenario)
    assert found["message"] == 'The text "order CONFIRMED" is on the page.'
    assert "Order confirmed" in found["page"]["text"]
    assert missing.fields["seconds"] == 1
    assert slept["message"] == "Waited 0.2 s."
    assert settled["message"] == "Waited for the page to settle."


def test_wait_for_user_returns_when_control_is_handed_back(browser):
    async def scenario(core, tab):
        idle = await ops.wait(core, tab, for_user=True, timeout_ms=5000)
        tab.user_control = True

        async def hand_back():
            await asyncio.sleep(0.4)
            tab.user_control = False

        flip = asyncio.ensure_future(hand_back())
        handed = await ops.wait(core, tab, for_user=True, timeout_ms=5000)
        await flip
        tab.user_control = True
        timeout = await expect_error(
            ops.wait(core, tab, for_user=True, timeout_ms=1000), "MINI_BROWSER_TIMEOUT"
        )
        return idle, handed, timeout

    idle, handed, timeout = run(browser, "<p>x</p>", scenario)
    assert "not controlling" in idle["message"]
    assert handed["message"] == "The user handed control back."
    assert "hand back control" in timeout.fields["what"]


# ── files ───────────────────────────────────────────────────────────────────


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A temporary agent workspace (AGENT_WORKSPACE_ROOT + session dirs)."""
    import app.config as app_config

    root = tmp_path / "workspace"
    session = root / "sessions" / "sess"
    session.mkdir(parents=True)
    monkeypatch.setattr(app_config, "AGENT_WORKSPACE_ROOT", root)
    try:
        from app.mini_browser import config as mb_config
    except ImportError:  # WP1a's module not there yet: provide the two helpers
        mb_config = SimpleNamespace()
        monkeypatch.setitem(sys.modules, "app.mini_browser.config", mb_config)
    monkeypatch.setattr(
        mb_config,
        "workspace_dir",
        lambda owner: root / "sessions" / str(owner),
        raising=False,
    )
    monkeypatch.setattr(
        mb_config,
        "screenshots_dir",
        lambda owner: root / "sessions" / str(owner) / "shots",
        raising=False,
    )
    return SimpleNamespace(root=root, session=session, outside=tmp_path / "outside")


UPLOAD = """
<input type="file" id="one" aria-label="One file">
<input type="file" id="many" multiple aria-label="Many files">
<button onclick="document.getElementById('hidden').click()">Choose file</button>
<input type="file" id="hidden" style="display:none">
"""


async def _file_names(tab, element):
    return await tab.page.evaluate(
        f"Array.from(document.getElementById('{element}').files).map(f => f.name)"
    )


def test_upload_files_inside_the_workspace(browser, workspace, fast_human):
    (workspace.session / "cv.pdf").write_bytes(b"%PDF-1.4 cv")
    (workspace.root / "photo.png").write_bytes(b"png")

    async def scenario(core, tab):
        one = await ops.upload_file(core, tab, element_id=0, paths=["cv.pdf"])
        await observe(core, tab, compact=True)
        many = await ops.upload_file(
            core,
            tab,
            element_id=1,
            paths=[str(workspace.session / "cv.pdf"), "photo.png"],
        )
        await observe(core, tab, compact=True)
        chooser = await ops.upload_file(core, tab, element_id=2, paths=["photo.png"])
        names = [await _file_names(tab, e) for e in ("one", "many", "hidden")]
        return one, many, chooser, names

    one, many, chooser, names = run(
        browser, UPLOAD, scenario, core=FakeCore(humanlike=True)
    )
    assert (
        one["files"] == ["cv.pdf"] and one["message"] == "Attached cv.pdf to element 0."
    )
    assert many["files"] == ["cv.pdf", "photo.png"]
    assert chooser["status"] == "success"
    assert names == [["cv.pdf"], ["cv.pdf", "photo.png"], ["photo.png"]]


def test_upload_outside_the_workspace_is_denied(browser, workspace):
    workspace.outside.mkdir()
    secret = workspace.outside / "id_rsa"
    secret.write_text("PRIVATE KEY")
    (workspace.root / "a.txt").write_text("a")
    (workspace.root / "b.txt").write_text("b")
    cases = [
        str(secret),
        "../outside/id_rsa",
        "../../outside/id_rsa",
        "../../../outside/id_rsa",
    ]
    if os.name == "nt":
        cases.append("\\\\evil-host\\share\\x.txt")  # a UNC share is never touched
    link = workspace.root / "link_out"
    try:
        os.symlink(secret, link)
        cases.append(str(link))
    except (OSError, NotImplementedError):
        pass  # symlinks need extra rights on Windows

    async def scenario(core, tab):
        denied = []
        for path in cases:
            exc = await expect_error(
                ops.upload_file(core, tab, element_id=0, paths=[path]),
                "MINI_BROWSER_UPLOAD_DENIED",
            )
            denied.append(exc.fields["path"])
        missing = await expect_error(
            ops.upload_file(core, tab, element_id=0, paths=["nope.txt"]),
            "MINI_BROWSER_INVALID_INPUT",
        )
        single = await expect_error(
            ops.upload_file(core, tab, element_id=0, paths=["a.txt", "b.txt"]),
            "MINI_BROWSER_INVALID_INPUT",
        )
        return denied, missing, single, await _file_names(tab, "one")

    denied, missing, single, names = run(browser, UPLOAD, scenario)
    assert denied == cases
    assert "nope.txt" in missing.fields["detail"]
    assert "only one file" in single.fields["detail"]
    assert names == []


def test_screenshot_writes_a_png_into_the_owner_workspace(browser, workspace):
    async def scenario(core, tab):
        return (
            await ops.screenshot(core, tab),
            await ops.screenshot(core, tab, full_page=True),
        )

    first, second = run(browser, LONG, scenario)
    for result in (first, second):
        path = Path(result["file_path"])
        assert path.parent == workspace.session / "shots"
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert "page" in result and "image" not in json.dumps(result)
    assert first["file_path"] != second["file_path"]
    assert "full-page" in second["message"]


# ── login ───────────────────────────────────────────────────────────────────

LOGIN_SCRIPT = """
<script>
document.getElementById('login').addEventListener('submit', (e) => {
  e.preventDefault();
  const u = document.getElementById('user').value, p = document.getElementById('pw').value;
  const q = document.querySelector('[name=q]');
  sessionStorage.setItem('q', q ? q.value : '');
  if (u === 'USER' && p === 'PASSWORD') location.href = '/home';
  else document.getElementById('err').innerHTML = '<div role="alert">Incorrect email or password.</div>';
});
</script>
"""


@pytest.fixture(scope="module")
def login_site(server):
    script = LOGIN_SCRIPT.replace("USER", USER).replace("PASSWORD", PASSWORD)
    form = """<title>Sign in</title>
        <header><form action="/search"><input name="q" placeholder="Search the shop"></form></header>
        <form id="login">
          <label for="user">Email address</label><input id="user" name="email" type="text">
          <label for="pw">Password</label><input id="pw" name="password" type="password">
          <button type="submit">Sign in</button>
        </form>
        <div id="err"></div>"""
    server.add("/home", "<title>Home</title><h1>Welcome back</h1>")
    server.add("/login", form + script)
    # Outcome heuristics: a landing page with an unrelated alert banner, a
    # verification step, and a CAPTCHA challenge shown instead of signing in.
    server.add(
        "/home-banner",
        "<title>Home</title><div class='alert alert-info'>New: two-factor sign-in "
        "is available in your settings.</div><h1>Hello</h1>",
    )
    server.add("/login-banner", form + script.replace("'/home'", "'/home-banner'"))
    server.add(
        "/verify",
        "<title>Verify</title><p>Enter the verification code we sent you.</p>"
        "<input name='code' autocomplete='one-time-code' aria-label='Code'>",
    )
    server.add("/login-2fa", form + script.replace("'/home'", "'/verify'"))
    server.add(
        "/login-captcha",
        form
        + script.replace(
            "location.href = '/home'",
            "document.body.insertAdjacentHTML('beforeend', "
            '\'<iframe title="reCAPTCHA captcha challenge" width="304" height="78"></iframe>\')',
        ),
    )
    server.add(
        "/step1",
        """<title>Sign in</title>
        <form action="/step2" method="get">
          <label for="id">Email or phone</label>
          <input id="id" name="identifier" type="email" autocomplete="username">
          <button>Next</button>
        </form>""",
    )
    server.add(
        "/step2",
        """<title>Sign in</title>
        <form id="login"><input id="user" type="hidden">
          <label for="pw">Enter your password</label>
          <input id="pw" type="password" autocomplete="current-password">
          <button>Sign in</button>
        </form><div id="err"></div>"""
        + script.replace(f"u === '{USER}' && ", ""),
    )
    server.add(
        "/step1-elsewhere",
        f"""<title>Sign in</title>
        <form action="http://localhost:{server.port}/step2" method="get">
          <input name="identifier" type="email" autocomplete="username" aria-label="Email">
          <button>Next</button>
        </form>""",
    )
    server.add(
        "/signup",
        """<title>Create account</title><form>
        <input type="email" autocomplete="email" aria-label="Email">
        <input type="password" autocomplete="new-password" aria-label="New password">
        <input type="password" autocomplete="new-password" aria-label="Repeat password">
        </form>""",
    )
    server.add("/plain", "<title>Plain</title><p>No form here</p>")
    return server


def _vault(password=PASSWORD, **kwargs):
    entries = [
        {"id": "e1", "site": "127.0.0.1", "username": USER, "password": password},
        {
            "id": "e2",
            "site": "127.0.0.1",
            "username": "bob@example.com",
            "password": "Bob-pass-777",
        },
    ]
    return FakeVault(entries, hosts={"127.0.0.1"}, **kwargs)


def _no_secret(value, *secrets):
    dumped = json.dumps(value, ensure_ascii=False, default=str)
    return all(s not in dumped for s in secrets)


def test_login_happy_path_never_types_into_the_search_box(
    browser, login_site, fast_human
):
    vault = _vault()
    core = FakeCore(humanlike=True, vault=vault)

    async def scenario(core, tab):
        result = await ops.login(core, tab)
        query = await tab.page.evaluate("sessionStorage.getItem('q')")
        return result, query, list(tab.filled_secrets)

    result, query, secrets = run(browser, login_site.url("/login"), scenario, core=core)
    assert result["status"] == "success", result
    assert result["outcome"] == "signed_in"
    assert result["username"] == USER and result["site"] == "127.0.0.1"
    assert result["other_usernames"] == ["bob@example.com"]
    assert result["page"]["url"] == login_site.url("/home")
    assert query == ""  # the header search box stayed empty
    assert secrets == [PASSWORD]
    assert vault.used == ["e1"]
    assert vault.asked == [login_site.url("/login")]
    assert core.events and "Filled the saved login" in core.events[0]["message"]
    assert _no_secret(result, PASSWORD, "Bob-pass-777")
    assert _no_secret(core.events, PASSWORD)


def test_login_without_submit_fills_and_the_observation_masks_the_password(
    browser, login_site
):
    core = FakeCore(vault=_vault())

    async def scenario(core, tab):
        result = await ops.login(core, tab, submit=False)
        values = await tab.page.evaluate(
            "[document.getElementById('user').value, document.getElementById('pw').value]"
        )
        full = await ops.read(core, tab)
        return result, values, full

    result, values, full = run(browser, login_site.url("/login"), scenario, core=core)
    assert result["outcome"] == "filled" and "(not submitted)" in result["message"]
    assert values == [USER, PASSWORD]
    assert '[2] input:password "Password"' in full["elements"]
    assert _no_secret(result, PASSWORD) and _no_secret(full, PASSWORD)


def test_login_picks_a_username_and_reports_a_rejected_password(browser, login_site):
    core = FakeCore(vault=_vault())

    async def scenario(core, tab):
        rejected = await ops.login(core, tab, username="BOB@example.com")
        unknown = await expect_error(
            ops.login(core, tab, username="carol"), "MINI_BROWSER_NO_SAVED_LOGIN"
        )
        return rejected, unknown, list(tab.filled_secrets)

    rejected, unknown, secrets = run(
        browser, login_site.url("/login"), scenario, core=core
    )
    assert rejected["status"] == "error" and rejected["outcome"] == "error"
    assert rejected["error_code"] == "MINI_BROWSER_LOGIN_FAILED"
    assert "Incorrect email or password." in rejected["message"]
    assert rejected["username"] == "bob@example.com"
    assert "carol" in unknown.fields["site"]
    assert secrets == ["Bob-pass-777"]
    assert _no_secret(rejected, "Bob-pass-777", PASSWORD)


@pytest.mark.parametrize(
    "path, outcome",
    [
        ("/login-banner", "signed_in"),
        ("/login-2fa", "needs_verification"),
        ("/login-captcha", "captcha"),
    ],
)
def test_login_outcome_heuristics(browser, login_site, path, outcome):
    core = FakeCore(vault=_vault())

    async def scenario(core, tab):
        return await ops.login(core, tab)

    result = run(browser, login_site.url(path), scenario, core=core)
    assert result["status"] == "success", result
    assert result["outcome"] == outcome
    assert _no_secret(result, PASSWORD)


def test_two_step_login(browser, login_site):
    vault = _vault()
    core = FakeCore(vault=vault)

    async def scenario(core, tab):
        return await ops.login(core, tab)

    result = run(browser, login_site.url("/step1"), scenario, core=core)
    assert result["status"] == "success", result
    assert result["outcome"] == "signed_in"
    assert result["page"]["url"] == login_site.url("/home")
    assert vault.used == ["e1"]


def test_two_step_login_aborts_when_the_origin_changes(browser, login_site):
    core = FakeCore(vault=_vault())

    async def scenario(core, tab):
        exc = await expect_error(ops.login(core, tab), "MINI_BROWSER_LOGIN_FAILED")
        pw = await tab.page.evaluate("document.getElementById('pw').value")
        return exc, pw, tab.page.url, list(tab.filled_secrets)

    exc, pw, url, secrets = run(
        browser, login_site.url("/step1-elsewhere"), scenario, core=core
    )
    assert exc.fields["detail"] == login.MSG_ORIGIN_CHANGED
    assert url.startswith(f"http://localhost:{login_site.port}/step2")
    assert pw == "" and secrets == []


@pytest.mark.parametrize("breakage", ["disable", "detach"])
def test_a_failed_fill_never_leaks_the_password(
    browser, login_site, monkeypatch, breakage
):
    monkeypatch.setattr(login, "FILL_TIMEOUT_MS", 400)
    script = {
        "disable": "document.querySelectorAll('input[type=password]').forEach(e => e.disabled = true)",
        "detach": "document.querySelectorAll('input[type=password]').forEach(e => e.remove())",
    }[breakage]

    async def sabotage(core, tab, locator):
        await tab.page.evaluate(script)

    monkeypatch.setattr(login, "_point_at", sabotage)
    core = FakeCore(vault=_vault())

    async def scenario(core, tab):
        exc = await expect_error(ops.login(core, tab), "MINI_BROWSER_LOGIN_FAILED")
        return exc

    exc = run(browser, login_site.url("/login"), scenario, core=core)
    assert exc.fields["detail"] == login.MSG_FILL_FAILED
    assert PASSWORD not in str(exc) and PASSWORD not in repr(exc.fields)
    assert exc.__context__ is None and exc.__cause__ is None


def test_login_refusals(browser, login_site):
    async def scenario(core, tab):
        out = {}
        out["no_saved"] = await expect_error(
            ops.login(core, tab), "MINI_BROWSER_NO_SAVED_LOGIN"
        )
        core._vault = _vault(unreadable=True)
        out["unreadable"] = await expect_error(
            ops.login(core, tab), "MINI_BROWSER_VAULT_UNREADABLE"
        )
        core._vault = _vault()
        await tab.page.goto(login_site.url("/signup"))
        out["signup"] = await expect_error(
            ops.login(core, tab), "MINI_BROWSER_LOGIN_FAILED"
        )
        await tab.page.goto(login_site.url("/plain"))
        out["plain"] = await expect_error(
            ops.login(core, tab), "MINI_BROWSER_LOGIN_FAILED"
        )
        await tab.page.goto("about:blank")
        out["blank"] = await expect_error(
            ops.login(core, tab), "MINI_BROWSER_LOGIN_FAILED"
        )
        return out

    core = FakeCore(vault=FakeVault([], hosts={"127.0.0.1"}))
    out = run(browser, login_site.url("/login"), scenario, core=core)
    assert out["no_saved"].fields["site"] == "127.0.0.1"
    assert out["signup"].fields["detail"] == login.MSG_SIGNUP_FORM
    assert out["plain"].fields["detail"] == login.MSG_NO_FORM
    assert out["blank"].fields["detail"] == login.MSG_NOT_WEB


# ── misc ────────────────────────────────────────────────────────────────────


def test_ops_table_matches_the_spec():
    assert set(ops.OPS) == {
        "navigate",
        "read",
        "click",
        "hover",
        "type",
        "press_key",
        "select_option",
        "scroll",
        "wait",
        "upload_file",
        "login",
        "screenshot",
    }
    assert "tabs" not in ops.OPS


# ── navigation interrupted by a late error-page commit ──────────────────


def test_goto_retries_once_when_an_error_page_commit_interrupts_it():
    """A blocked earlier navigation commits Chromium's error page late; that
    commit can interrupt the next goto, which must then be retried once."""
    from app.mini_browser import ops

    class _Page:
        def __init__(self, failures):
            self.failures = list(failures)
            self.calls = 0

        async def goto(self, url, wait_until=None, timeout=None):
            self.calls += 1
            if self.failures:
                raise Exception(self.failures.pop(0))

    interrupted = (
        'Page.goto: Navigation to "http://example.test/" is interrupted by '
        'another navigation to "chrome-error://chromewebdata/"'
    )
    page = _Page([interrupted])
    assert asyncio.run(ops._goto(page, "http://example.test/", 5000, None)) == ""
    assert page.calls == 2

    # Only one retry: a second interruption is accepted as the page moving on.
    page = _Page([interrupted, interrupted])
    assert asyncio.run(ops._goto(page, "http://example.test/", 5000, None)) == ""
    assert page.calls == 2

    # Any other interruption (e.g. a client-side redirect) is not retried.
    page = _Page(['Page.goto: interrupted by another navigation to "http://x.test/"'])
    assert asyncio.run(ops._goto(page, "http://example.test/", 5000, None)) == ""
    assert page.calls == 1
