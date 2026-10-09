"""Page observations (app/mini_browser/observe.py) against a real Chromium page."""

import asyncio
import json
from types import SimpleNamespace

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


# ── review fixes: what the agent can see ────────────────────────────────────


def _line(obs, needle):
    found = [line for line in obs["elements"] if needle in line]
    assert found, (needle, obs["elements"])
    return found[0]


CLICKABLES = """
<style>
  .c { cursor: pointer; padding: 6px; margin: 4px; border: 1px solid #999; }
  .wall { cursor: pointer; position: absolute; inset: 0; z-index: -1; }
</style>
<div class="wall"></div>
<div class="c" id="sort">Sort by: Price</div>
<ul><li class="c">Price</li><li class="c">Duration</li></ul>
<div class="c" id="card">NH 123 <span>09:05</span> <b>Select</b></div>
<a class="c" id="more">Show 20 more flights</a>
<a id="plain">Not clickable text</a>
<div x-on:click="open = true">Alpine menu</div>
<div @click="open = true">Alpine short</div>
<div id="react">React row</div>
<label class="c"><input type="checkbox"> Remember me</label>
<span id="nothing">Just text</span>
<script>document.getElementById('react')['__reactProps$x1'] = {onClick() {}};</script>
"""


def test_clickable_elements_without_semantics_are_listed(browser):
    """OBS-1: framework click handlers and cursor:pointer areas are listed
    (the outermost one only), plain text is not."""
    obs, _state = _observe(browser, CLICKABLES)
    lines = obs["elements"]
    for label in (
        '"Sort by: Price"',
        '"Price"',
        '"Duration"',
        '"Alpine menu"',
        '"Alpine short"',
        '"React row"',
    ):
        assert any(label in line and "clickable" in line for line in lines), label
    assert any(line.endswith('link "Show 20 more flights"') for line in lines)
    # The card is one element, not one per inner span.
    assert sum("NH 123" in line or "09:05" in line for line in lines) == 1
    assert '"NH 123 09:05 Select"' in _line(obs, "NH 123")
    assert not any("Not clickable" in line or "Just text" in line for line in lines)
    # A label around a real checkbox adds nothing: the checkbox is listed.
    assert sum("Remember me" in line for line in lines) == 1
    assert _line(obs, "Remember me").split("] ")[1].startswith("checkbox")


SLOTTED = """
<my-button id=a>Place order</my-button>
<my-button id=b><span>Apply coupon</span></my-button>
<my-link href="/x">Track package</my-link>
<my-input>Promo code</my-input>
<script>
customElements.define('my-button', class extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}).innerHTML = '<button><slot></slot></button>'; }
});
customElements.define('my-link', class extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}).innerHTML =
    '<a href="' + this.getAttribute('href') + '"><slot></slot></a>'; }
});
customElements.define('my-input', class extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}).innerHTML = '<label><slot></slot><input></label>'; }
});
</script>
"""


def test_web_components_keep_their_slotted_labels_and_are_not_obscured(browser):
    """OBS-2: labels come through slots; slotted text is not a cover."""
    obs, _state = _observe(browser, SLOTTED)
    assert _line(obs, "Place order").endswith('button "Place order"')
    assert _line(obs, "Apply coupon").endswith('button "Apply coupon"')
    assert '"Track package"' in _line(obs, "Track package")
    assert _line(obs, "Promo code").endswith('input:text "Promo code"')
    assert not any("obscured" in line for line in obs["elements"])


def test_repeated_controls_carry_their_row_or_card(browser):
    """OBS-3: identical buttons are told apart by their row / card text."""
    rows = "".join(
        f"<tr><td>Order #{1000 + i}</td><td>Shoes size {38 + i}</td>"
        f"<td><button>Cancel order</button></td></tr>"
        for i in range(3)
    )
    cards = "".join(
        f"<div class=card><h3>T-shirt {c}</h3><span>${12 + i}</span>"
        f"<button>Add to cart</button></div>"
        for i, c in enumerate(("Blue", "Red"))
    )
    obs, _state = _observe(
        browser, f"<table>{rows}</table>{cards}<button>Checkout</button>"
    )
    lines = obs["elements"]
    assert '[0] button "Cancel order" (in "Order #1000 · Shoes size 38")' in lines
    assert '[2] button "Cancel order" (in "Order #1002 · Shoes size 40")' in lines
    assert '[3] button "Add to cart" (in "T-shirt Blue $12")' in lines
    assert '[4] button "Add to cart" (in "T-shirt Red $13")' in lines
    assert '[5] button "Checkout"' in lines  # unique: no context needed


def test_links_to_the_same_address_are_listed_once(browser):
    html = """<base href="https://shop.example/">
      <div><a href="/p/1"><img alt="Trail Runner 2" width=40 height=40></a>
      <h3><a href="/p/1">Trail Runner 2, size 38-46</a></h3>
      <a href="/p/1#reviews">4.5 stars</a> <a href="/p/1#reviews">12,345</a></div>
      <a href="/p/2">Other shoe</a>"""
    obs, _state = _observe(browser, html)
    links = [line for line in obs["elements"] if " link " in line]
    assert links == [
        '[0] link "Trail Runner 2, size 38-46" → shop.example/p/1',
        '[1] link "4.5 stars" → shop.example/p/1',
        '[2] link "Other shoe" → shop.example/p/2',
    ]


def _big_page():
    cards = "".join(
        f'<div style="display:inline-block;width:23%">'
        f'<a href="/Sony-WH-1000XM5-Wireless-Noise-Canceling-Headphones-{i}/dp/B0{i:08d}'
        f'/ref=sr_1_{i}?crid=2M096C61O4MLT&keywords=wireless+headphones&qid=1696000000">'
        f"<h2>Sony WH-1000XM5 Wireless Industry Leading Noise Canceling Headphones "
        f"with Auto Noise Canceling Optimizer, Black (Model {i})</h2></a>"
        f"<p>{'Great sound and comfort for long flights. ' * 6}</p>"
        f'<button aria-label="Add to cart">Add to cart</button>'
        f'<a href="/offers/B0{i:08d}?ref=sr_opts">See options</a></div>'
        for i in range(60)
    )
    nav = "".join(f'<a href="/nav/{k}">Department number {k}</a> ' for k in range(30))
    return (
        '<base href="https://shop.example/"><title>Results</title>'
        f"<header>{nav}</header>{cards}"
    )


def test_results_stay_under_the_event_stream_inline_limit(browser):
    """OBS-4: a busy results page fits (compact and read), with the most
    relevant elements kept and the text offsets still right."""
    html = _big_page()
    compact, _state = _observe(browser, html)
    assert len(json.dumps({"page": compact}, indent=2, ensure_ascii=False)) <= (
        obs_mod.COMPACT_BUDGET_CHARS
    )
    full, _state = _observe(browser, html, compact=False, max_elements=500)
    size = len(json.dumps(full, indent=2, ensure_ascii=False))
    assert size <= obs_mod.READ_BUDGET_CHARS
    assert full["elements_truncated"] and full["element_count"] > len(full["elements"])
    assert full["elements"][0].startswith("[0] link")  # numbering kept from 0
    more, _state = _observe(browser, html, compact=False, max_text_chars=8000)
    assert len(json.dumps(more, indent=2, ensure_ascii=False)) <= (
        obs_mod.READ_BUDGET_CHARS
    )
    assert more["next_text_offset"] == more["text_offset"] + len(more["text"])


def test_frames_are_listed_with_their_contents(browser):
    """OBS-5: a frame and its fields are visible (and secret rules apply)."""
    widget = (
        "<form><label>Name <input id=name></label>"
        "<label>Card <input autocomplete=cc-number value=4111111111111111></label>"
        "<button type=button>Find a table</button><p>Available: 19:00</p></form>"
    )
    html = (
        "<h1>Trattoria</h1>"
        f"<iframe title='Reservation widget' srcdoc='{widget}' "
        "style='width:600px;height:200px'></iframe><p>Call us</p>"
    )

    async def prepare(page):
        for _ in range(200):  # until the srcdoc frame has its document
            frames = page.main_frame.child_frames
            if frames and await frames[0].evaluate("document.readyState") == "complete":
                return
            await asyncio.sleep(0.05)

    obs, _state = _observe(browser, html, prepare=prepare)
    lines = obs["elements"]
    assert lines[0] == (
        '[0] frame "Reservation widget" → (inline) (its contents are [1]-[3])'
    )
    assert '[1] input:text "Name" (in frame 0)' in lines
    assert '[3] button "Find a table" (in frame 0)' in lines
    assert "4111" not in json.dumps(obs)
    assert "Available: 19:00" in obs["frame_text"]


def test_an_open_modal_s_text_comes_first(browser):
    """OBS-6: the question a modal asks leads the text."""
    rows = "".join(f"<p>Order #{1000 + i} Running shoes</p>" for i in range(80))
    html = (
        f"<h1>Your orders</h1>{rows}"
        "<div role=dialog aria-modal=true style='position:fixed;top:30%;left:30%;"
        "background:#fff;padding:20px'><p>Cancel order #1003? A 500 yen "
        "cancellation fee applies.</p><button>Keep order</button>"
        "<button>Yes, cancel</button></div>"
    )
    obs, _state = _observe(browser, html)
    assert obs["dialog_open"] is True
    assert obs["text"].startswith("Dialog: Cancel order #1003? A 500 yen")
    assert obs["elements"][0] == '[0] button "Keep order" (in dialog)'


def test_the_cores_tab_list_is_passed_through_untouched():
    """Agent-facing tab list (C4): no address or title is ever added for a
    tab the agent does not own."""
    payload = [
        {
            "index": 0,
            "id": "t1",
            "url": "https://a/",
            "title": "A",
            "mine": True,
            "active": True,
        },
        {"index": 1, "mine": False, "owner": "agent", "ownerLabel": "Research"},
        {
            "index": 2,
            "mine": False,
            "owner": "user",
            "host": "bank.example",
            "viewed": True,
        },
    ]
    core = FakeCore()
    core.tabs_payload = lambda owner=None: [dict(t) for t in payload]
    tab = Tab(id="t1", page=_ScriptedPage([_RAW]), owner="sess")
    result = asyncio.run(obs_mod.observe(core, tab, compact=True))
    assert result["tabs"] == payload


def test_a_hanging_frame_never_holds_up_the_observation(monkeypatch):
    """OBS-5: frames are best effort, within one small time budget."""
    monkeypatch.setattr(obs_mod, "FRAMES_BUDGET_S", 0.3)

    class Handle:
        async def get_attribute(self, name):
            return "1-0"

        async def dispose(self):
            return None

    class HangingFrame:
        url = "https://widget.example/"

        async def frame_element(self):
            return Handle()

        async def evaluate(self, script, arg=None):
            await asyncio.sleep(3600)

    raw = dict(
        _RAW,
        elements=[{"n": 0, "kind": "frame", "label": "Widget", "states": []}],
        frames=[{"n": 0, "inView": True, "dir": "", "src": "https://widget.example/"}],
    )
    page = _ScriptedPage([raw])
    page.main_frame = SimpleNamespace(child_frames=[HangingFrame()])
    tab = Tab(id="t1", page=page, owner="sess")
    loop_time = asyncio.new_event_loop()
    try:
        started = loop_time.time()
        result = loop_time.run_until_complete(
            obs_mod.observe(FakeCore(), tab, compact=True)
        )
        elapsed = loop_time.time() - started
    finally:
        loop_time.close()
    assert elapsed < 2.0
    assert result["elements"] == ['[0] frame "Widget" (its contents could not be read)']
