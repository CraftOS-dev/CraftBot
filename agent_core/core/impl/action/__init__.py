# -*- coding: utf-8 -*-
"""
Action implementation module.

This module provides implementations for action execution, routing,
and management in the agent framework.
"""

from agent_core.core.impl.action.executor import (
    ActionExecutor,
    PROCESS_POOL,
    THREAD_POOL,
    DEFAULT_ACTION_TIMEOUT,
    set_gui_execute_hook,
)
from agent_core.core.impl.action.library import ActionLibrary
from agent_core.core.impl.action.router import ActionRouter, _is_visible_in_mode
from agent_core.core.impl.action.manager import (
    ActionManager,
    OnActionStartHook,
    OnActionEndHook,
    GetParentIdHook,
)

__all__ = [
    # Executor
    "ActionExecutor",
    "PROCESS_POOL",
    "THREAD_POOL",
    "DEFAULT_ACTION_TIMEOUT",
    "set_gui_execute_hook",
    # Library
    "ActionLibrary",
    # Router
    "ActionRouter",
    "_is_visible_in_mode",
    # Manager
    "ActionManager",
    "OnActionStartHook",
    "OnActionEndHook",
    "GetParentIdHook",
]
