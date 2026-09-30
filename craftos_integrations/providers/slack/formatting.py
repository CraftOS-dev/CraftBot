"""Slack message text → readable plain text.

Slack's ``text`` field is not what the user typed: ``& < >`` arrive
HTML-escaped and every reference is wrapped in angle-bracket markup.
Forwarded as-is, the agent and the chat details show ``<@U0123ABC>`` and
``&amp;`` (issue #444; docs/plans/inbound-message-fidelity-plan.md).

Pure module — the only outside knowledge (user id → display name) is
injected as ``resolve_user``, so it is testable without a client.
"""

from __future__ import annotations

import html
import re
from typing import Callable

# One `<…>` reference. Slack escapes literal `<` / `>` in user text, so a
# raw angle bracket is always markup.
_REFERENCE = re.compile(r"<([^<>]+)>")

# <!here> / <!channel> / <!everyone> — label-less special mentions.
_SPECIAL_MENTIONS = {"here", "channel", "everyone"}


def to_plain_text(text: str, resolve_user: Callable[[str], str]) -> str:
    """Convert Slack references + escapes to plain text. Never raises.

    ============================  =========================================
    ``<@U123>`` / ``<@U123|bob>`` ``@<display name>`` (via ``resolve_user``;
                                  falls back to the label, then ``@U123``)
    ``<#C123|general>``           ``#general``  (``<#C123>`` → ``#C123``)
    ``<https://x|label>``         ``label (https://x)``
    ``<https://x>``               ``https://x``  (``mailto:`` prefix dropped)
    ``<!here>`` etc.              ``@here`` / ``@channel`` / ``@everyone``
    ``<!subteam^S1|@team>``       ``@team``
    ``<!date^…|fallback>``        ``fallback``
    ============================  =========================================

    References are converted BEFORE unescaping: unescaping first would
    turn a user's literal ``&lt;@U1&gt;`` into a fake mention.
    """
    if not text:
        return ""
    return html.unescape(
        _REFERENCE.sub(lambda m: _render(m.group(1), resolve_user), text)
    )


def _render(ref: str, resolve_user: Callable[[str], str]) -> str:
    target, _, label = ref.partition("|")
    if target.startswith("@"):
        user_id = target[1:]
        try:
            name = resolve_user(user_id)
        except Exception:
            name = ""
        return f"@{name or label or user_id}"
    if target.startswith("#"):
        return f"#{label or target[1:]}"
    if target.startswith("!"):
        keyword = target[1:].split("^", 1)[0]
        if keyword in _SPECIAL_MENTIONS:
            return f"@{keyword}"
        return label or target[1:]
    if target.startswith("mailto:"):
        target = target[len("mailto:") :]
    if label and label != target:
        return f"{label} ({target})"
    return target
