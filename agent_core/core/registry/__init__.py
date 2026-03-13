# -*- coding: utf-8 -*-
"""
Component registries for dependency injection.

This module provides registry classes for accessing shared components
without knowing the underlying implementation details.

Each registry follows the same pattern:
    1. Define a registry class that extends ComponentRegistry
    2. At application startup, register a factory function
    3. In shared code, use get() to access the component

Example:
    # At startup (CraftBot or CraftBot):
    from agent_core.core.registry import TaskManagerRegistry
    TaskManagerRegistry.register(lambda: task_manager)

    # In shared code:
    from agent_core.core.registry import TaskManagerRegistry
    task_manager = TaskManagerRegistry.get()
"""

from agent_core.core.registry.base import ComponentRegistry

# Re-export StateRegistry from existing location for convenience
from agent_core.core.state.base import StateRegistry, get_state, get_state_or_none

# Database registry
from agent_core.core.registry.database import (
    DatabaseRegistry,
    get_database,
    get_database_or_none,
)

# Action registries
from agent_core.core.registry.action import (
    ActionExecutorRegistry,
    ActionManagerRegistry,
    get_action_executor,
    get_action_executor_or_none,
    get_action_manager,
    get_action_manager_or_none,
)

# Memory registry
from agent_core.core.registry.memory import (
    MemoryRegistry,
    get_memory_manager,
    get_memory_manager_or_none,
)

# LLM registry
from agent_core.core.registry.llm import (
    LLMInterfaceRegistry,
    get_llm_interface,
    get_llm_interface_or_none,
)

# Event stream registries
from agent_core.core.registry.event_stream import (
    EventStreamRegistry,
    EventStreamManagerRegistry,
    get_event_stream,
    get_event_stream_or_none,
    get_event_stream_manager,
    get_event_stream_manager_or_none,
)

# Task manager registry
from agent_core.core.registry.task_manager import (
    TaskManagerRegistry,
    get_task_manager,
    get_task_manager_or_none,
)

# State manager registry
from agent_core.core.registry.state import (
    StateManagerRegistry,
    get_state_manager,
    get_state_manager_or_none,
)

# Context engine registry
from agent_core.core.registry.context import (
    ContextEngineRegistry,
    get_context_engine,
    get_context_engine_or_none,
)

# Trigger queue registry
from agent_core.core.registry.trigger import (
    TriggerQueueRegistry,
    get_trigger_queue,
    get_trigger_queue_or_none,
)

__all__ = [
    "ComponentRegistry",
    "StateRegistry",
    "get_state",
    "get_state_or_none",
    "DatabaseRegistry",
    "get_database",
    "get_database_or_none",
    "ActionExecutorRegistry",
    "ActionManagerRegistry",
    "get_action_executor",
    "get_action_executor_or_none",
    "get_action_manager",
    "get_action_manager_or_none",
    "MemoryRegistry",
    "get_memory_manager",
    "get_memory_manager_or_none",
    "LLMInterfaceRegistry",
    "get_llm_interface",
    "get_llm_interface_or_none",
    "EventStreamRegistry",
    "EventStreamManagerRegistry",
    "get_event_stream",
    "get_event_stream_or_none",
    "get_event_stream_manager",
    "get_event_stream_manager_or_none",
    "TaskManagerRegistry",
    "get_task_manager",
    "get_task_manager_or_none",
    "StateManagerRegistry",
    "get_state_manager",
    "get_state_manager_or_none",
    "ContextEngineRegistry",
    "get_context_engine",
    "get_context_engine_or_none",
    "TriggerQueueRegistry",
    "get_trigger_queue",
    "get_trigger_queue_or_none",
]
