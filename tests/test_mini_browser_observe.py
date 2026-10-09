"""Page observations (app/mini_browser/observe.py) against a real Chromium page."""

import asyncio
import json

import pytest

from app.mini_browser import observe as obs_mod
from app.mini_browser.errors import MiniBrowserError
from app.mini_browser.types import Tab
from tests.mini_browser_fixtures import FakeCore, launch_browser_or_skip

SECRET = "hunter2-Sup3r-secret"


@pytest.fixture(scope="module")
def browser():
    harness = launch_browser_or_skip()
    yield harness
    harness.close()


def _observe(
    browser, html, *, compact=True, prepare=None, viewport=(1280, 800), **kwargs
):
    """Load ``html``, run ``prepare(page)``, observe; returns (obs, tab_state)."""

    async def scenario():
        tab = await browser.new_tab(html, viewport=viewport)
        try:
            if prepare is not None:
                await prepare(tab.page)
            result = await obs_mod.observe(FakeCore(), tab, compact=compact, **kwargs)
            ids = await tab.page.evaluate(
                "() => Array.from(document.querySelectorAll('[data-mb-id]'))"
                ".map(e => e.getAttribute('data-mb-id'))"
            )
            return result, {"gen": tab.snapshot_gen, "ids": ids}
        finally:
            await browser.close_tab(tab)

    return browser.run(scenario())


# ── secrets ─────────────────────────────────────────────────────────────────

LOGIN_FORM = """
<form>
  <label for="u">Email</label><input id="u" type="email">
  <label for="p">Password</label><input id="p" type="password">
  <label for="o">Code</label><input id="o" autocomplete="one-time-code">
  <label for="c">Card</label><input id="c" autocomplete="cc-number">
  <label for="n">PIN</label><input id="n" name="pin">
  <label for="t">Note</label><input id="t" name="note">
  <button>Sign in</button>
</form>
"""


def test_password_with_only_a_label_and_a_typed_value_never_shows(browser):
    async def fill(page):
        await page.fill("#u", "jo@x.com")
        await page.fill("#p", SECRET)
        await page.fill("#o", SECRET + "-otp")
        await page.fill("#c", SECRET + "-card")
        await page.fill("#n", SECRET + "-pin")
        await page.fill("#t", "hello note")

    for compact in (True, False):
        result, _ = _observe(browser, LOGIN_FORM, compact=compact, prepare=fill)
        dumped = json.dumps(result, ensure_ascii=False)
        assert SECRET not in dumped
        elements = result["elements"]
        assert '[0] input:email "Email" value="jo@x.com"' in elements
        assert '[1] input:password "Password"' in elements
        assert '[2] input:text "Code"' in elements
        assert '[3] input:text "Card"' in elements
        assert '[4] input:text "PIN" (has value)' in elements
        assert '[5] input:text "Note" value="hello note"' in elements


def test_password_switched_to_text_by_a_show_toggle_is_still_hidden(browser):
    async def fill(page):
        await page.fill("#p", SECRET)
        await page.evaluate("document.querySelector('#p').type = 'text'")
        await page.evaluate("document.querySelector('#p').name = 'password'")

    result, _ = _observe(browser, LOGIN_FORM, prepare=fill)
    assert SECRET not in json.dumps(result)
    assert '[1] input:text "Password" (has value)' in result["elements"]


def test_a_password_field_seen_once_stays_secret_after_a_show_toggle(browser):
    html = '<label for="f3">Secret word</label><input id="f3" type="password">'

    async def scenario():
        tab = await browser.new_tab(html)
        try:
            await tab.page.fill("#f3", SECRET)
            first = await obs_mod.observe(FakeCore(), tab, compact=True)
            await tab.page.evaluate("document.querySelector('#f3').type = 'text'")
            second = await obs_mod.observe(FakeCore(), tab, compact=False)
            return first, second
        finally:
            await browser.close_tab(tab)

    first, second = browser.run(scenario())
    assert first["elements"] == ['[0] input:password "Secret word"']
    assert second["elements"] == ['[0] input:text "Secret word"']
    assert SECRET not in json.dumps([first, second])


def test_filled_secrets_are_scrubbed_from_text_title_and_elements(browser):
    html = f"<title>t {SECRET}</title><p>Your password is {SECRET}</p><a href='#'>{SECRET}</a>"

    async def scenario():
        tab = await browser.new_tab(html)
        tab.filled_secrets.append(SECRET)
        try:
            return await obs_mod.observe(FakeCore(), tab, compact=True)
        finally:
            await browser.close_tab(tab)

    result = browser.run(scenario())
    dumped = json.dumps(result)
    assert SECRET not in dumped
    assert "[redacted]" in result["text"] and "[redacted]" in result["title"]


# ── ids & generations ───────────────────────────────────────────────────────


def test_every_observation_bumps_the_generation_and_removes_old_ids(browser):
    html = "<button>A</button><button>B</button>" + "<a href='#x'>link</a>" * 3

    async def scenario():
        tab = await browser.new_tab(html)
        try:
            first = await obs_mod.observe(FakeCore(), tab, compact=True)
            gen1 = tab.snapshot_gen
            # A node the page cloned with an old id keeps it only until the next pass.
            await tab.page.evaluate(
                "document.body.appendChild(document.querySelector('button').cloneNode(true))"
            )
            second = await obs_mod.observe(FakeCore(), tab, compact=True)
            ids = await tab.page.evaluate(
                "() => Array.from(document.querySelectorAll('[data-mb-id]'))"
                ".map(e => e.getAttribute('data-mb-id'))"
            )
            return first, second, gen1, tab.snapshot_gen, ids
        finally:
            await browser.close_tab(tab)

    first, second, gen1, gen2, ids = browser.run(scenario())
    assert gen2 == gen1 + 1
    assert all(i.startswith(f"{gen2}-") for i in ids)
    assert len(ids) == len(set(ids)) == second["element_count"] == 6
    assert first["elements"][0] == '[0] button "A"'


def test_open_shadow_roots_are_walked(browser):
    html = """
    <shop-card></shop-card>
    <script>
      customElements.define('shop-card', class extends HTMLElement {
        constructor() {
          super();
          this.attachShadow({mode: 'open'}).innerHTML =
            '<p>Shadow price 9.99</p><button>Add to Cart</button>';
        }
      });
    </script>
    """
    result, _ = _observe(browser, html)
    assert '[0] button "Add to Cart"' in result["elements"]
    assert "Shadow price 9.99" in result["text"]


# ── element descriptions ────────────────────────────────────────────────────

FORM = """
<a href="/deals">Deals</a>
<a href="https://shop.example.com/cart?x=1">Cart</a>
<label for="size">Size</label>
<select id="size"><option>S</option><option selected>M</option><option>L</option></select>
<label><input type="checkbox" checked> Remember me</label>
<label class="sw"><input type="checkbox" style="opacity:0;position:absolute"> Dark mode</label>
<button disabled>Pay</button>
<button aria-expanded="false">Menu</button>
<a href="/x"><span onclick="1">Nested</span></a>
<div onclick="1"><button>Inner</button></div>
<div contenteditable="true" aria-label="Notes">draft text</div>
<input type="submit" value="Go">
"""


def test_compact_element_strings(browser):
    result, _ = _observe(browser, FORM)
    texts = [e.split("] ", 1)[1] for e in result["elements"]]
    assert 'link "Deals"' in texts  # no usable href on about:blank
    assert 'select "Size" = "M" (options: S, M, L)' in texts
    assert 'checkbox "Remember me" (checked)' in texts
    assert 'checkbox "Dark mode"' in texts  # hidden input listed through its label
    assert 'button "Pay" (disabled)' in texts
    assert 'button "Menu" (collapsed)' in texts
    assert 'link "Nested"' in texts  # the nested onclick span is not listed
    assert 'button "Inner"' in texts
    assert not any(t.startswith("clickable") for t in texts)
    assert 'editable "Notes" value="draft text"' in texts
    assert 'button "Go"' in texts


def test_links_show_short_hrefs_on_a_real_origin(browser):
    async def prepare(page):
        await page.route(
            "http://shop.test/**",
            lambda route: route.fulfill(
                status=200, content_type="text/html", body=FORM
            ),
        )
        await page.goto("http://shop.test/home")

    result, _ = _observe(browser, "", prepare=prepare)
    texts = [e.split("] ", 1)[1] for e in result["elements"]]
    assert 'link "Deals" → /deals' in texts
    assert 'link "Cart" → shop.example.com/cart?x=1' in texts


def test_obscured_elements_are_flagged(browser):
    html = """
    <button id="b">Buy now</button>
    <div style="position:fixed;inset:0;background:rgba(0,0,0,.4)">
      <p>We use cookies</p><button>Accept</button>
    </div>
    """
    result, _ = _observe(browser, html)
    assert '[1] button "Accept"' in result["elements"]
    assert '[0] button "Buy now" (obscured)' in result["elements"]


def test_open_modal_dialog_elements_come_first(browser):
    html = """
    <button>Outside</button>
    <div role="dialog" aria-modal="true" aria-label="Sign up">
      <button>Close</button><a href="#t">Terms</a>
    </div>
    """
    result, _ = _observe(browser, html)
    assert result["dialog_open"] is True
    assert result["elements"][0] == '[0] button "Close" (in dialog)'
    assert result["elements"][1].startswith('[1] link "Terms"')
    assert result["elements"][2] == '[2] button "Outside"'


def test_viewport_first_then_nearest_off_screen(browser):
    links = "".join(
        f'<p style="height:300px"><a href="#a{i}">Item {i}</a></p>' for i in range(30)
    )

    async def scroll(page):
        await page.evaluate("window.scrollTo(0, 3000)")

    result, _ = _observe(browser, links, prepare=scroll, viewport=(800, 600))
    elements = result["elements"]
    in_view = [e for e in elements if "off-screen" not in e]
    assert in_view and all(any(f'"Item {i}"' in e for i in (10, 11)) for e in in_view)
    off = [e for e in elements if "off-screen" in e]
    # The nearest off-screen items come next, both directions.
    assert '"Item 12"' in off[0] or '"Item 9"' in off[0]
    assert any("off-screen above" in e for e in off) and any(
        "off-screen below" in e for e in off
    )
    assert result["scroll"]["y"] == 3000 and result["scroll"]["at_bottom"] is False


def test_element_limit_and_truncation_flag(browser):
    html = "".join(f"<button>B{i}</button>" for i in range(80))
    compact, _ = _observe(browser, html, compact=True)
    assert len(compact["elements"]) == obs_mod.COMPACT_MAX_ELEMENTS
    assert compact["element_count"] == 80 and compact["elements_truncated"] is True
    full, state = _observe(browser, html, compact=False, max_elements=100)
    assert len(full["elements"]) == 80 and full["elements_truncated"] is False
    assert len(state["ids"]) == 80


# ── text ────────────────────────────────────────────────────────────────────


def test_compact_text_is_around_the_viewport(browser):
    html = "<h1>Top heading</h1>" + "".join(
        f'<p style="height:200px">Paragraph {i} ' + "lorem " * 10 + "</p>"
        for i in range(60)
    )

    async def scroll(page):
        await page.evaluate("window.scrollTo(0, 6000)")

    result, _ = _observe(browser, html, prepare=scroll)
    assert "Top heading" not in result["text"]
    assert "Paragraph 30" in result["text"]
    assert len(result["text"]) <= obs_mod.COMPACT_MAX_TEXT_CHARS
    assert 0 < result["text_offset"] < result["text_total"]


def test_read_text_pages_with_offsets(browser):
    html = "".join(f"<p>Line {i:03d} with some words</p>" for i in range(200))
    first, _ = _observe(browser, html, compact=False, max_text_chars=1000)
    assert first["text"].startswith("Line 000")
    assert first["next_text_offset"] == len(first["text"])
    collected = first["text"]
    offset = first["next_text_offset"]
    while offset is not None:
        page, _ = _observe(
            browser, html, compact=False, max_text_chars=1000, text_offset=offset
        )
        assert page["text_offset"] == offset
        collected += page["text"]
        offset = page.get("next_text_offset")
    assert collected.count("Line ") == 200
    assert len(collected) == first["text_total"]


def test_tables_and_blocks_keep_their_layout(browser):
    html = "<table><tr><td>A1</td><td>B1</td></tr><tr><td>A2</td><td>B2</td></tr></table><p>x<br>y</p>"
    result, _ = _observe(browser, html)
    assert "A1 | B1\nA2 | B2" in result["text"]
    assert "x\ny" in result["text"]


def test_emoji_offsets_never_split_surrogate_pairs(browser):
    html = "<p>" + "😀" * 3000 + "</p>"
    for offset in (0, 1, 2, 3, 1001):
        page, _ = _observe(
            browser, html, compact=False, max_text_chars=999, text_offset=offset
        )
        page["text"].encode("utf-8")  # a lone surrogate would raise here
        json.dumps(page, ensure_ascii=False).encode("utf-8")


# ── robustness (no browser needed) ──────────────────────────────────────────


class _ScriptedPage:
    def __init__(self, behaviours):
        self.behaviours = list(behaviours)
        self.calls = 0
        self.url = "https://example.com/"

    async def evaluate(self, script, arg=None):
        self.calls += 1
        behaviour = self.behaviours.pop(0)
        if isinstance(behaviour, Exception):
            raise behaviour
        if behaviour == "hang":
            await asyncio.sleep(3600)
        return behaviour

    async def wait_for_load_state(self, state, timeout=None):
        return None


_RAW = {
    "title": "Example",
    "elements": [{"n": 0, "kind": "button", "label": "OK", "states": []}],
    "total": 1,
    "text": "hello",
    "textOffset": 0,
    "textEnd": 5,
    "textTotal": 5,
    "scroll": {"y": 0, "height": 800, "at_bottom": True},
    "dialogOpen": False,
}


def test_retries_once_when_a_navigation_destroys_the_context():
    page = _ScriptedPage(
        [
            Exception(
                "Execution context was destroyed, most likely because of a navigation"
            ),
            _RAW,
        ]
    )
    tab = Tab(id="t1", page=page, owner="sess")
    result = asyncio.run(obs_mod.observe(FakeCore(), tab, compact=True))
    assert result["elements"] == ['[0] button "OK"'] and page.calls == 2
    assert tab.snapshot_gen == 2

    page = _ScriptedPage([Exception("Execution context was destroyed")] * 2)
    tab = Tab(id="t1", page=page, owner="sess")
    with pytest.raises(Exception, match="destroyed"):
        asyncio.run(obs_mod.observe(FakeCore(), tab, compact=True))


def test_an_unresponsive_page_raises_page_unresponsive(monkeypatch):
    monkeypatch.setattr(obs_mod, "EVALUATE_TIMEOUT_S", 0.05)
    tab = Tab(id="t1", page=_ScriptedPage(["hang"]), owner="sess")
    with pytest.raises(MiniBrowserError) as info:
        asyncio.run(obs_mod.observe(FakeCore(), tab, compact=True))
    assert info.value.code == "MINI_BROWSER_PAGE_UNRESPONSIVE"


def test_junk_from_a_hostile_page_does_not_crash_the_formatter():
    raw = dict(
        _RAW,
        elements=[{"n": "x"}, "junk", {"n": 1, "kind": "link", "label": 5}],
        total=-3,
    )
    tab = Tab(id="t1", page=_ScriptedPage([raw]), owner="sess")
    result = asyncio.run(obs_mod.observe(FakeCore(), tab, compact=True))
    assert result["elements"] == ['[1] link "5"'] and result["element_count"] == 1


def test_tabs_payload_failure_is_tolerated():
    core = FakeCore()
    core.tabs_payload = lambda owner=None: (_ for _ in ()).throw(RuntimeError("boom"))
    tab = Tab(id="t1", page=_ScriptedPage([_RAW]), owner="sess")
    assert asyncio.run(obs_mod.observe(core, tab, compact=True))["tabs"] == []


def test_format_element_examples():
    fmt = obs_mod.format_element
    assert (
        fmt({"n": 3, "kind": "button", "label": "Add to Cart"})
        == '[3] button "Add to Cart"'
    )
    assert (
        fmt({"n": 7, "kind": "input:email", "label": "Email", "value": "jo@x.com"})
        == '[7] input:email "Email" value="jo@x.com"'
    )
    assert (
        fmt({"n": 9, "kind": "link", "label": "Deals", "href": "/deals"})
        == '[9] link "Deals" → /deals'
    )
    assert (
        fmt(
            {
                "n": 12,
                "kind": "select",
                "label": "Size",
                "selected": "M",
                "options": ["S", "M", "L"],
            }
        )
        == '[12] select "Size" = "M" (options: S, M, L)'
    )
    assert (
        fmt(
            {"n": 15, "kind": "checkbox", "label": "Remember me", "states": ["checked"]}
        )
        == '[15] checkbox "Remember me" (checked)'
    )
    assert (
        fmt({"n": 1, "kind": "button", "label": 'say "hi"'})
        == "[1] button \"say 'hi'\""
    )
