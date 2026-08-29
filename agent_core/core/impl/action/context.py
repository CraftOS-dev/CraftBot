"""Execution-scoped context for in-process actions.

``current_input_data`` holds the full ``input_data`` dict of the action
currently executing in this context. It exists so cross-cutting helpers
deep inside an action's call tree (e.g. multi-account routing reading the
``account`` hint) can see routing keys without threading them through
every action function signature.

Scope rules:
  - Set only by the internal executors (``_atomic_action_internal*``),
    reset in a ``finally`` — never leaks across actions.
  - Sync actions run in a thread pool where the caller's context does NOT
    propagate, so the executor wraps the call and sets the var inside the
    worker thread (see ``run_with_input_context``).
  - Sandboxed (subprocess) actions cannot see it at all — helpers must
    treat a ``None`` value as "no context available".
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Callable, Dict, Optional

current_input_data: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "current_input_data", default=None
)


def run_with_input_context(
    function_to_call: Callable[[dict], dict], input_data: dict
) -> dict:
    """Call a sync action with ``current_input_data`` set for its duration.

    Used as the thread-pool target: the worker thread has its own context,
    so the var must be set (and reset) inside the thread, not the caller.
    """
    token = current_input_data.set(input_data)
    try:
        return function_to_call(input_data)
    finally:
        current_input_data.reset(token)
