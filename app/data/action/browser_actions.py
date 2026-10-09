"""
Web Agent actions — let the agent drive a real Chromium browser.

These actions wrap the persistent :class:`app.browser.web_agent.WebAgentSession`
so the agent can navigate, read, click, type, scroll, and screenshot a live web
page. The user watches it happen in the "Web Agent" panel (frames are streamed
to the UI after every action).

Recommended loop for the agent:
    1. browser_navigate  → open a page
    2. browser_read      → get the numbered list of interactive elements + text
    3. browser_click / browser_type  → act on an element by its id
    4. browser_read again → ids are reassigned after the page changes

IMPORTANT (execution model): the agent framework runs each action by extracting
*only the function body's source* and exec'ing it in an isolated namespace —
module-level imports are NOT in scope at runtime. So every function imports
``get_session`` inside its own body. All actions share one browser, so they are
not parallelizable.
"""

from __future__ import annotations

from agent_core import action

_SET = ["web_agent"]


@action(
    name="browser_navigate",
    description=(
        "Open a URL in the live web browser the agent controls (a real Chromium "
        "page the user can watch). Use this first, then browser_read to see the "
        "page. Special targets: 'back', 'forward', 'reload'. "
        "Distinct from web_fetch (which only downloads page text) — use this when "
        "you must interact with a site (log in, search, fill forms, buy)."
    ),
    mode="ALL",
    execution_mode="internal",
    action_sets=_SET,
    parallelizable=False,
    input_schema={
        "url": {
            "type": "string",
            "example": "https://www.amazon.com",
            "description": "URL to open, or 'back'/'forward'/'reload'. https:// is added if missing.",
            "required": True,
        },
        "timeout": {
            "type": "integer",
            "example": 30000,
            "description": "Navigation timeout in milliseconds. Defaults to 30000.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "url": {"type": "string", "description": "Final URL after redirects."},
        "title": {"type": "string", "description": "Page title."},
        "message": {"type": "string", "description": "Result or error message."},
    },
    test_payload={"url": "https://example.com", "simulated_mode": True},
)
async def browser_navigate(input_data: dict) -> dict:
    from app.browser.web_agent import get_session

    if input_data.get("simulated_mode"):
        return {"status": "success", "url": input_data.get("url", ""), "title": "Example", "message": "Simulated"}
    url = (input_data.get("url") or "").strip()
    if not url:
        return {"status": "error", "message": "url is required"}
    timeout = int(input_data.get("timeout", 30000))
    return await get_session().navigate(url, timeout_ms=timeout)


@action(
    name="browser_read",
    description=(
        "Read the current page: returns a NUMBERED list of interactive elements "
        "(links, buttons, inputs) each with an 'id', plus the visible page text. "
        "Use the returned ids with browser_click and browser_type. Always call "
        "this after navigating or after the page changes — element ids are "
        "reassigned every time."
    ),
    mode="ALL",
    execution_mode="internal",
    action_sets=_SET,
    parallelizable=False,
    input_schema={
        "max_text_chars": {
            "type": "integer",
            "example": 4000,
            "description": "Max characters of visible page text to return. Defaults to 4000.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "url": {"type": "string", "description": "Current URL."},
        "title": {"type": "string", "description": "Page title."},
        "elements": {
            "type": "array",
            "description": "Interactive elements: [{id, tag, type, text}]. Act on them by id.",
        },
        "element_count": {"type": "integer", "description": "Number of interactive elements found."},
        "page_text": {"type": "string", "description": "Visible page text (truncated)."},
    },
    test_payload={"simulated_mode": True},
)
async def browser_read(input_data: dict) -> dict:
    from app.browser.web_agent import get_session

    if input_data.get("simulated_mode"):
        return {"status": "success", "url": "", "title": "", "elements": [], "element_count": 0, "page_text": ""}
    return await get_session().snapshot(max_text_chars=int(input_data.get("max_text_chars", 2000)))


@action(
    name="browser_click",
    description=(
        "Click an element on the current page by its id (from browser_read). "
        "After clicking, call browser_read again to see the updated page."
    ),
    mode="ALL",
    execution_mode="internal",
    action_sets=_SET,
    parallelizable=False,
    input_schema={
        "element_id": {
            "type": "integer",
            "example": 3,
            "description": "The 'id' of the element from browser_read.",
            "required": True,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "url": {"type": "string", "description": "URL after the click."},
        "title": {"type": "string", "description": "Page title after the click."},
        "message": {"type": "string", "description": "Result or error message."},
    },
    test_payload={"element_id": 0, "simulated_mode": True},
)
async def browser_click(input_data: dict) -> dict:
    from app.browser.web_agent import get_session

    if input_data.get("simulated_mode"):
        return {"status": "success", "url": "", "title": "", "message": "Simulated"}
    if "element_id" not in input_data:
        return {"status": "error", "message": "element_id is required"}
    return await get_session().click(input_data["element_id"])


@action(
    name="browser_type",
    description=(
        "Type text into an input/textarea on the current page, addressed by its id "
        "(from browser_read). Set submit=true to press Enter afterwards (e.g. to "
        "run a search). The field is cleared first unless clear=false."
    ),
    mode="ALL",
    execution_mode="internal",
    action_sets=_SET,
    parallelizable=False,
    input_schema={
        "element_id": {
            "type": "integer",
            "example": 1,
            "description": "The 'id' of the input element from browser_read.",
            "required": True,
        },
        "text": {
            "type": "string",
            "example": "wireless headphones",
            "description": "The text to type.",
            "required": True,
        },
        "submit": {
            "type": "boolean",
            "example": True,
            "description": "Press Enter after typing (submit the field/form). Defaults to false.",
        },
        "clear": {
            "type": "boolean",
            "example": True,
            "description": "Clear the field before typing. Defaults to true.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "url": {"type": "string", "description": "URL after typing."},
        "title": {"type": "string", "description": "Page title."},
        "message": {"type": "string", "description": "Result or error message."},
    },
    test_payload={"element_id": 0, "text": "hello", "simulated_mode": True},
)
async def browser_type(input_data: dict) -> dict:
    from app.browser.web_agent import get_session

    if input_data.get("simulated_mode"):
        return {"status": "success", "url": "", "title": "", "message": "Simulated"}
    if "element_id" not in input_data:
        return {"status": "error", "message": "element_id is required"}
    return await get_session().type_text(
        input_data["element_id"],
        input_data.get("text", ""),
        submit=bool(input_data.get("submit", False)),
        clear=bool(input_data.get("clear", True)),
    )


@action(
    name="browser_scroll",
    description="Scroll the current page. direction: 'down' (default), 'up', 'top', or 'bottom'.",
    mode="ALL",
    execution_mode="internal",
    action_sets=_SET,
    parallelizable=False,
    input_schema={
        "direction": {
            "type": "string",
            "example": "down",
            "description": "'down', 'up', 'top', or 'bottom'. Defaults to 'down'.",
        },
        "amount": {
            "type": "integer",
            "example": 600,
            "description": "Pixels to scroll for up/down. Defaults to 600.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "url": {"type": "string", "description": "Current URL."},
        "message": {"type": "string", "description": "Result or error message."},
    },
    test_payload={"direction": "down", "simulated_mode": True},
)
async def browser_scroll(input_data: dict) -> dict:
    from app.browser.web_agent import get_session

    if input_data.get("simulated_mode"):
        return {"status": "success", "url": "", "message": "Simulated"}
    return await get_session().scroll(
        direction=(input_data.get("direction") or "down"),
        amount=int(input_data.get("amount", 600)),
    )


@action(
    name="browser_login",
    description=(
        "Log into the CURRENT website using a login the user saved in their "
        "password vault. First navigate to the site's sign-in page (so username "
        "and password fields are visible), then call this. The password is typed "
        "directly into the page — it is NEVER shown to you and never appears in "
        "logs. If no saved login matches, ask the user to add it in the Passwords "
        "panel. Optionally pass 'site' to choose which saved login to use."
    ),
    mode="ALL",
    execution_mode="internal",
    action_sets=_SET,
    parallelizable=False,
    input_schema={
        "site": {
            "type": "string",
            "example": "amazon.com",
            "description": "Optional domain to pick which saved login to use. Defaults to the current page's domain.",
        },
        "submit": {
            "type": "boolean",
            "example": True,
            "description": "Press Enter to submit after filling. Defaults to true.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "site": {"type": "string", "description": "Domain the login was used for."},
        "username": {"type": "string", "description": "Username filled (password is never returned)."},
        "message": {"type": "string", "description": "Result or error message."},
    },
    test_payload={"simulated_mode": True},
)
async def browser_login(input_data: dict) -> dict:
    from app.browser.web_agent import get_session

    if input_data.get("simulated_mode"):
        return {"status": "success", "site": "example.com", "username": "user@example.com", "message": "Simulated"}
    return await get_session().login(
        site=input_data.get("site"),
        submit=bool(input_data.get("submit", True)),
    )


@action(
    name="browser_new_tab",
    description=(
        "Open a new browser tab and make it active (subsequent browser_read/click/"
        "type act on it). Useful for working on several things at once — e.g. "
        "comparing products across sites. Optionally pass a 'url' to open in it."
    ),
    mode="ALL",
    execution_mode="internal",
    action_sets=_SET,
    parallelizable=False,
    input_schema={
        "url": {
            "type": "string",
            "example": "https://www.google.com",
            "description": "Optional URL to open in the new tab. https:// added if missing.",
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "url": {"type": "string", "description": "URL of the new tab."},
        "title": {"type": "string", "description": "Title of the new tab."},
    },
    test_payload={"simulated_mode": True},
)
async def browser_new_tab(input_data: dict) -> dict:
    from app.browser.web_agent import get_session

    if input_data.get("simulated_mode"):
        return {"status": "success", "url": "", "title": ""}
    return await get_session().new_tab(url=input_data.get("url"))


@action(
    name="browser_switch_tab",
    description=(
        "Switch to another open browser tab by its index (0-based, as shown in the "
        "tab bar). Following browser_read/click/type act on that tab."
    ),
    mode="ALL",
    execution_mode="internal",
    action_sets=_SET,
    parallelizable=False,
    input_schema={
        "index": {
            "type": "integer",
            "example": 0,
            "description": "0-based index of the tab to switch to.",
            "required": True,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "url": {"type": "string", "description": "URL of the now-active tab."},
    },
    test_payload={"index": 0, "simulated_mode": True},
)
async def browser_switch_tab(input_data: dict) -> dict:
    from app.browser.web_agent import get_session

    if input_data.get("simulated_mode"):
        return {"status": "success", "url": ""}
    return await get_session().switch_tab(int(input_data.get("index", 0)))


@action(
    name="browser_screenshot",
    description=(
        "Save a full-page screenshot of the current browser page to the workspace "
        "and return its file path (e.g. to attach it to the user or analyze it)."
    ),
    mode="ALL",
    execution_mode="internal",
    action_sets=_SET,
    parallelizable=False,
    input_schema={},
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "url": {"type": "string", "description": "Current URL."},
        "title": {"type": "string", "description": "Page title."},
        "file_path": {"type": "string", "description": "Absolute path to the saved PNG."},
        "message": {"type": "string", "description": "Result or error message."},
    },
    test_payload={"simulated_mode": True},
)
async def browser_screenshot(input_data: dict) -> dict:
    from app.browser.web_agent import get_session

    if input_data.get("simulated_mode"):
        return {"status": "success", "url": "", "title": "", "file_path": "", "message": "Simulated"}
    return await get_session().screenshot()
