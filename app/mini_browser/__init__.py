"""Mini Browser — a real Chromium that agents drive and the user watches live.

Every kind of agent (main chat, chat sessions, the dedicated Mini Browser
session, scheduled runs, Agent App trigger runs and sub-agents) can use it.
Each agent session gets its own tab, so concurrent agents never act on each
other's page, and the user can watch any tab and take control of it.

Layout
------
- ``host.py``        dedicated "mini-browser" thread + event loop that owns
                     Playwright; callers on any loop/thread marshal into it.
- ``core.py``        ``BrowserCore``: lifecycle, tabs, per-owner claims,
                     viewport, dialogs, downloads, crash recovery, UI ops.
- ``stream.py``      CDP screencast (fallback: screenshot polling) of the
                     viewed tab, only while a UI subscriber exists.
- ``ops.py``         agent primitives (navigate, read, click, type, ...).
- ``observe.py``     page snapshot JS + compact observations for the LLM.
- ``human.py``       human-like mouse paths, typing rhythm and scrolling.
- ``login.py``       password-vault autofill (origin-checked, never leaks).
- ``vault.py``       encrypted credential vault.
- ``actions_api.py`` validation + entry point used by the action stubs.
- ``ws.py``          WebSocket protocol handler living in the UI adapter.
- ``bridge.py``      thread-safe channel from the browser thread to the UI.
- ``lifecycle.py``   hooks called by AgentBase (run state, stop, shutdown).
- ``urls.py`` / ``adblock.py`` / ``config.py`` / ``errors.py`` / ``types.py``.

This package is import-light on purpose: nothing here imports Playwright at
module import time, so the actions and the UI adapter stay cheap to load in
every mode (browser UI, CLI, tests).
"""

# The dedicated chat session behind the Mini Browser page.
SESSION_ID = "mini_browser"
SESSION_TITLE = "Mini Browser"

# Action set holding every mini_browser_* action, and the companion skill.
ACTION_SET = "mini_browser"
SKILL_NAME = "mini-browser"

# Owner used when an action arrives without a session id (should be rare).
DEFAULT_OWNER = "main"
