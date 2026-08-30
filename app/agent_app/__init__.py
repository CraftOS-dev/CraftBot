"""Agent App module for managing dynamic agent-aware user interfaces.

Public surface (import from `app.agent_app`):

- AgentAppManager, AgentAppProject          — data + lifecycle (see manager.py)
- get_agent_app_manager, set_agent_app_manager — module singleton accessor
- register_broadcast_callbacks              — wire up browser adapter callbacks
- broadcast_agent_app_ready                 — async broadcast (agent actions)
- broadcast_agent_app_progress              — async broadcast (agent actions)
- make_todo_broadcast_hook                  — factory for SessionManager todo hook
- restart_agent_app                         — async restart operation

Internal (do not import from here): todo dispatch machinery lives in
`broadcast.py` behind `make_todo_broadcast_hook`.
"""

from .manager import AgentAppManager, AgentAppProject
from ._state import get_agent_app_manager, set_agent_app_manager
from .broadcast import (
    register_broadcast_callbacks,
    broadcast_agent_app_ready,
    broadcast_agent_app_created,
    broadcast_agent_app_progress,
    broadcast_agent_app_wizard_open,
    dispatch_agent_app_data_changed,
    make_todo_broadcast_hook,
)
from .actions import restart_agent_app

__all__ = [
    "AgentAppManager",
    "AgentAppProject",
    "get_agent_app_manager",
    "set_agent_app_manager",
    "register_broadcast_callbacks",
    "broadcast_agent_app_ready",
    "broadcast_agent_app_created",
    "broadcast_agent_app_progress",
    "broadcast_agent_app_wizard_open",
    "dispatch_agent_app_data_changed",
    "make_todo_broadcast_hook",
    "restart_agent_app",
]
