"""Shared data types for the Mini Browser.

Everything in here lives on the Mini Browser host loop (see ``host.py``);
nothing is safe to mutate from other threads.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

# Who owns a tab. ``None`` owner == a tab the user opened themselves.
OWNER_KIND_USER = "user"
OWNER_KIND_MAIN = "main"  # the main session (also scheduled/proactive runs)
OWNER_KIND_SESSION = "session"  # a chat / Agent App session
OWNER_KIND_MINI_BROWSER = "mini_browser"  # the dedicated Mini Browser chat
OWNER_KIND_SUBAGENT = "subagent"

# Agent-facing notice kinds collected on a tab and attached to the owner's
# next action result (``events``) and mirrored to the UI as toasts.
EVENT_DIALOG = "dialog"
EVENT_DOWNLOAD = "download"
EVENT_POPUP = "popup"
EVENT_BLOCKED = "blocked"
EVENT_CRASH = "crash"
EVENT_NOTICE = "notice"
EVENT_ERROR = "error"


@dataclass(eq=False)
class Tab:
    """One browser tab and the bookkeeping the Mini Browser keeps for it."""

    id: str
    page: Any
    owner: Optional[str] = None
    owner_label: str = ""
    owner_kind: str = OWNER_KIND_USER
    parent_owner: Optional[str] = None  # parent session of a sub-agent owner

    # Serialises multi-step AGENT operations on this tab. Raw user input does
    # not take it (it must stay responsive).
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    created_at: float = field(default_factory=time.monotonic)
    last_agent_use: float = 0.0
    last_user_input: float = 0.0

    # True while the user has taken control: agent ops on this tab are refused
    # with MINI_BROWSER_USER_IN_CONTROL until the user hands it back.
    user_control: bool = False

    loading: bool = False
    crashed: bool = False
    url: str = "about:blank"
    title: str = ""
    can_go_back: bool = False
    can_go_forward: bool = False

    # Element ids handed to the agent are "<snapshot_gen>-<n>" in the DOM
    # (data-mb-id) and plain ``n`` for the agent; bumping the generation on
    # every observation makes stale ids fail loudly instead of mis-clicking.
    snapshot_gen: int = 0

    # Last known pointer position in CSS px (for human-like mouse paths).
    mouse_x: float = -1.0
    mouse_y: float = -1.0

    # Pending agent-facing notices (dialogs, downloads, popups, blocks).
    events: List[Dict[str, Any]] = field(default_factory=list)

    # Per-page CDP session (network blocking, screencast, stop-loading).
    cdp: Any = None

    # In-flight agent operation tasks (so Stop can cancel them).
    ops: Set[asyncio.Task] = field(default_factory=set)

    # Secrets typed into this tab by vault autofill — used ONLY to scrub
    # outgoing text. Never serialise this field anywhere.
    filled_secrets: List[str] = field(default_factory=list, repr=False)

    # The tab whose page opened this one (popups), so closing a popup returns
    # its owner (and the view) to where it came from.
    opener_id: Optional[str] = None

    def touch_agent(self) -> None:
        self.last_agent_use = time.monotonic()

    def touch_user(self) -> None:
        self.last_user_input = time.monotonic()
