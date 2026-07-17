"""Living UI module for managing dynamic agent-aware user interfaces.

Public surface (import from `app.living_ui`):

- LivingUIManager, LivingUIProject          — data + lifecycle (see manager.py)
- get_living_ui_manager, set_living_ui_manager — module singleton accessor
- register_broadcast_callbacks              — wire up browser adapter callbacks
- broadcast_living_ui_ready                 — async broadcast (agent actions)
- broadcast_living_ui_progress              — async broadcast (agent actions)
- make_todo_broadcast_hook                  — factory for TaskManager hook
- restart_living_ui                         — async restart operation

Internal (do not import from here): todo dispatch machinery lives in
`broadcast.py` behind `make_todo_broadcast_hook`.
"""

from .manager import LivingUIManager, LivingUIProject
from ._state import get_living_ui_manager, set_living_ui_manager
from .broadcast import (
    register_broadcast_callbacks,
    broadcast_living_ui_ready,
    broadcast_living_ui_created,
    broadcast_living_ui_progress,
    broadcast_living_ui_question,
    make_todo_broadcast_hook,
)
from .actions import restart_living_ui

# Component self-registration: importing the package plugs the domain's
# extension hooks (ghost guard, budget reset, task_end gate, construction
# action taps) into the core's generic registry. Fail-open — a broken
# registration degrades to "no listeners", never breaks the import.
try:
    from . import registrations  # noqa: F401
except Exception:  # pragma: no cover
    pass

__all__ = [
    "LivingUIManager",
    "LivingUIProject",
    "get_living_ui_manager",
    "set_living_ui_manager",
    "register_broadcast_callbacks",
    "broadcast_living_ui_ready",
    "broadcast_living_ui_created",
    "broadcast_living_ui_progress",
    "broadcast_living_ui_question",
    "make_todo_broadcast_hook",
    "restart_living_ui",
]
