# -*- coding: utf-8 -*-
"""
Protocol definitions for shared components.

This module provides Python Protocol classes that define the interfaces
for shared components. Using protocols enables structural typing (duck typing)
without requiring explicit inheritance.

Each protocol defines the minimal interface that a component must implement
to be usable by shared code. Agent-specific implementations can add additional
methods as needed.

Example:
    from agent_core.core.protocols import TaskManagerProtocol

    def shared_function(task_manager: TaskManagerProtocol) -> None:
        task = task_manager.create_task("My Task", "Do something")
        # ...
"""

# Re-export StateProvider from existing location
from agent_core.core.state.protocols import StateProvider
from agent_core.core.protocols.database import DatabaseInterfaceProtocol
from agent_core.core.protocols.action import (
    ActionExecutorProtocol,
    ActionManagerProtocol,
    ActionLibraryProtocol,
    ActionRouterProtocol,
)
from agent_core.core.protocols.memory import MemoryManagerProtocol
from agent_core.core.protocols.llm import LLMInterfaceProtocol
from agent_core.core.protocols.event_stream import EventStreamProtocol, EventStreamManagerProtocol
from agent_core.core.protocols.task_manager import TaskManagerProtocol
from agent_core.core.protocols.state import StateManagerProtocol
from agent_core.core.protocols.context import ContextEngineProtocol
from agent_core.core.protocols.trigger import TriggerQueueProtocol

__all__ = [
    "StateProvider",
    "DatabaseInterfaceProtocol",
    "ActionExecutorProtocol",
    "ActionManagerProtocol",
    "ActionLibraryProtocol",
    "ActionRouterProtocol",
    "MemoryManagerProtocol",
    "LLMInterfaceProtocol",
    "EventStreamProtocol",
    "EventStreamManagerProtocol",
    "TaskManagerProtocol",
    "StateManagerProtocol",
    "ContextEngineProtocol",
    "TriggerQueueProtocol",
]
