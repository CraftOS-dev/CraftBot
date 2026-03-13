# -*- coding: utf-8 -*-
"""
Registries for action execution components.

This module provides registries for ActionExecutor and ActionManager,
allowing shared code to access these components without knowing the
underlying implementation.

Usage:
    # At application startup:
    from agent_core.core.registry.action import ActionExecutorRegistry
    from agent_core.core.impl.action import ActionExecutor

    executor = ActionExecutor()
    ActionExecutorRegistry.register(lambda: executor)

    # In shared code:
    executor = ActionExecutorRegistry.get()
    result = await executor.execute_action(action, input_data)
"""

from typing import TYPE_CHECKING

from agent_core.core.registry.base import ComponentRegistry

if TYPE_CHECKING:
    from agent_core.core.protocols.action import ActionExecutorProtocol, ActionManagerProtocol


class ActionExecutorRegistry(ComponentRegistry["ActionExecutorProtocol"]):
    """
    Registry for accessing the ActionExecutor instance.

    Each project (CraftBot, CraftBot) registers their executor
    at startup. Shared code uses get() to access the executor.
    """
    pass


class ActionManagerRegistry(ComponentRegistry["ActionManagerProtocol"]):
    """
    Registry for accessing the ActionManager instance.

    Each project (CraftBot, CraftBot) registers their manager
    at startup. Shared code uses get() to access the manager.
    """
    pass


def get_action_executor() -> "ActionExecutorProtocol":
    """
    Get the registered action executor.

    Returns:
        The ActionExecutor instance.

    Raises:
        RuntimeError: If ActionExecutorRegistry has not been initialized.
    """
    return ActionExecutorRegistry.get()


def get_action_executor_or_none() -> "ActionExecutorProtocol | None":
    """
    Get the action executor, or None if not available.

    Returns:
        The ActionExecutor instance, or None if unavailable.
    """
    return ActionExecutorRegistry.get_or_none()


def get_action_manager() -> "ActionManagerProtocol":
    """
    Get the registered action manager.

    Returns:
        The ActionManager instance.

    Raises:
        RuntimeError: If ActionManagerRegistry has not been initialized.
    """
    return ActionManagerRegistry.get()


def get_action_manager_or_none() -> "ActionManagerProtocol | None":
    """
    Get the action manager, or None if not available.

    Returns:
        The ActionManager instance, or None if unavailable.
    """
    return ActionManagerRegistry.get_or_none()
