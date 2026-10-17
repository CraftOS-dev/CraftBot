"""Mini Browser — a real Chromium that agents drive and the user watches live.

Every agent session (the main session, each chat, each Agent App session)
has a browser of its own, built into its chat: the user opens it in the
chat's browser panel, and it starts when they do or when the session's agent
first needs it. A session's browser keeps its own cookies and signed-in sites
(a persistent Chromium profile per session); only the password vault is
shared. Sub-agents work in their parent session's browser, scheduled runs in
the main session's. Each agent gets its own tab, so concurrent agents never
act on each other's page, and the user can take control of any tab.

Layout
------
- ``host.py``        dedicated "mini-browser" thread + event loop that owns
                     Playwright; callers on any loop/thread marshal into it.
- ``fleet.py``       ``BrowserFleet``: one browser per session, the limit on
                     browsers running at once, deleted sessions' profiles.
- ``core.py``        ``BrowserCore``: one session's browser: lifecycle, tabs,
                     per-owner claims, viewport, dialogs, downloads, crash
                     recovery, UI ops.
- ``stream.py``      CDP screencast (fallback: screenshot polling) of the
                     viewed tab, only while the session's panel is watched.
- ``ops.py``         agent primitives (navigate, read, click, type, ...).
- ``observe.py``     page snapshot JS + compact observations for the LLM.
- ``human.py``       human-like mouse paths, typing rhythm and scrolling.
- ``login.py``       password-vault autofill (origin-checked, never leaks).
- ``vault.py``       encrypted credential vault (shared by every session).
- ``actions_api.py`` validation + entry point used by the action stubs.
- ``ws.py``          WebSocket protocol handler living in the UI adapter.
- ``bridge.py``      thread-safe channel from the browser thread to the UI.
- ``lifecycle.py``   hooks called by AgentBase (run state, stop, deleted
                     sessions, shutdown).
- ``urls.py`` / ``adblock.py`` / ``config.py`` / ``errors.py`` / ``types.py``.

This package is import-light on purpose: nothing here imports Playwright at
module import time, so the actions and the UI adapter stay cheap to load in
every mode (browser UI, CLI, tests).
"""

# Action set holding every mini_browser_* action, and the companion skill.
ACTION_SET = "mini_browser"
SKILL_NAME = "mini-browser"

# The main session's id: its browser serves actions that arrive without a
# session id (should be rare) and scheduled runs (they run in the main session).
DEFAULT_OWNER = "main"
