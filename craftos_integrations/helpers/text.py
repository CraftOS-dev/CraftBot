"""Text shaping for listener message bodies.

Listeners that cap a body's length (to keep inbound token cost bounded)
use ``clip`` so every cap cuts the same way and reports that it cut —
the flag goes to ``PlatformMessage.truncated`` and the host marks the cut.
"""

from __future__ import annotations

from typing import Tuple

# How far back from the limit a word boundary may be before we give up
# and hard-cut (fraction of the limit).
_BOUNDARY_WINDOW = 0.2


def clip(text: str, limit: int) -> Tuple[str, bool]:
    """Cut ``text`` to at most ``limit`` chars, preferring a word boundary.

    Returns ``(clipped, was_clipped)``. No ellipsis is added — the host
    owns presentation of the cut.
    """
    if len(text) <= limit:
        return text, False
    head = text[:limit]
    cut = max(head.rfind(" "), head.rfind("\n"))
    if cut >= limit * (1 - _BOUNDARY_WINDOW):
        head = head[:cut]
    return head.rstrip(), True
