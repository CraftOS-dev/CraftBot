# -*- coding: utf-8 -*-
"""Error helpers for `@action` handler bodies.

Internal action handlers are not called directly: the registry stores
`inspect.getsource(handler)` with the `@action` decorator stripped
(agent_core/core/action_framework/registry.py:247-249), and the executor runs
`exec(action.code, local_ns, local_ns)` with `local_ns = {input_data, json,
asyncio}` (agent_core/core/impl/action/executor.py:522 sync, :569 async).

Consequences for every ported action body:
  - imports must be FUNCTION-LOCAL — `from app.errors.actions import ...` as
    the first statement, exactly like the existing precedent at
    app/data/action/web_fetch.py:102 ("must be inside for sandboxed
    execution").
  - no second decorator on the handler, and no comment/blank line between
    `@action` and `def` — `_strip_decorator` slices source, not AST.
  - no new module-level helper visible to the exec'd body.

This module exists so that discipline is ONE import line per action instead
of importing `app.errors.codebook` piecemeal, and so `grep -r
"app.errors.actions" app/data/action` is an exact adoption audit. Keep it
free of heavy/optional imports (notably aiohttp, which lives in
app/errors/web.py, never here) since it resolves on every action invocation.
"""

from __future__ import annotations

from typing import Any, Dict

from agent_core.core.errors import ErrorInfoLike
from app.errors.codebook import (  # noqa: F401 - re-exported for action bodies
    error_from_exception,
    make_error,
    verbatim,
)
from app.errors.envelope import error_fields

__all__ = ["action_error", "make_error", "verbatim", "error_from_exception"]


def action_error(info: ErrorInfoLike, **passthrough: Any) -> Dict[str, Any]:
    """Build an action's error return dict.

    `passthrough` re-states the action's success-shape keys with empty
    values (`content=""`, `return_code=-1`, ...) — the existing convention
    every hand-rolled error dict already follows, so an action's output
    schema stays stable across success and failure. It's spread BEFORE the
    error tags so a caller can never accidentally shadow `error_category`/
    `error_code`/`error_severity`.

    Emits `message` — the documented, dominant action contract, and the
    exact text the LLM reads from the <event_stream> block on the next turn
    (agent_core/core/impl/action/manager.py -> event_stream.py ->
    context/engine.py). Deliberately omits `error_actions`: nothing on the
    action path renders buttons, and every extra key here is pretty-printed
    into the prompt on every turn.
    """
    return {
        "status": "error",
        "message": info.message,
        **passthrough,
        **error_fields(info),
    }
