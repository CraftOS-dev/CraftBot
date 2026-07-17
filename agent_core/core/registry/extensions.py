# -*- coding: utf-8 -*-
"""Generic extension-hook registry — the plug-and-play seam.

Domain components (e.g. app/living_ui) self-register callbacks at import
time; the core calls hook POINTS without knowing who is listening. A
component that isn't installed simply never registers, and every point
degrades to a no-op — removing a component can never break the core.

Every hook is fail-open: one listener crashing is logged and skipped.

Points in use:
- ``boot_restore``        (agent) — before restored-task triggers are
                           scheduled; listeners may cancel stale tasks.
- ``user_message_routed`` (agent, session_id, message) — a user message
                           was routed to an existing task session.
- ``task_end_gate``       (session_id) → Optional[str] — consulted by the
                           task_end action before accepting
                           status="complete"; the FIRST non-None return is
                           the refusal message.
- ``action_start`` / ``action_end`` — ActionManager observation hooks
                           (run_id, action, ... — same signatures the
                           manager passes its callbacks).
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional

try:
    from loguru import logger
except ImportError:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

_HOOKS: Dict[str, List[Callable]] = {}


def register_hook(point: str, fn: Callable) -> None:
    """Register ``fn`` on a hook point (idempotent per function object)."""
    listeners = _HOOKS.setdefault(point, [])
    if fn not in listeners:
        listeners.append(fn)


def hook_listeners(point: str) -> List[Callable]:
    return list(_HOOKS.get(point, ()))


def run_hooks(point: str, *args: Any, **kwargs: Any) -> List[Any]:
    """Run all listeners synchronously (skip+log failures). Returns the
    non-None results in registration order."""
    results: List[Any] = []
    for fn in hook_listeners(point):
        try:
            out = fn(*args, **kwargs)
            if out is not None:
                results.append(out)
        except Exception as e:
            logger.warning(f"[EXTENSIONS] hook {point}/{fn!r} failed: {e}")
    return results


async def run_hooks_async(point: str, *args: Any, **kwargs: Any) -> List[Any]:
    """Run all listeners, awaiting coroutines (skip+log failures)."""
    results: List[Any] = []
    for fn in hook_listeners(point):
        try:
            out = fn(*args, **kwargs)
            if inspect.isawaitable(out):
                out = await out
            if out is not None:
                results.append(out)
        except Exception as e:
            logger.warning(f"[EXTENSIONS] hook {point}/{fn!r} failed: {e}")
    return results


def first_hook_result(point: str, *args: Any, **kwargs: Any) -> Optional[Any]:
    """Run listeners until one returns non-None (fail-open)."""
    for fn in hook_listeners(point):
        try:
            out = fn(*args, **kwargs)
            if out is not None:
                return out
        except Exception as e:
            logger.warning(f"[EXTENSIONS] hook {point}/{fn!r} failed: {e}")
    return None
