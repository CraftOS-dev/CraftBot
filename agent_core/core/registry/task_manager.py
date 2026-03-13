# -*- coding: utf-8 -*-
"""
Registry for TaskManager.

This module provides the TaskManagerRegistry for accessing the task
manager instance without knowing the underlying implementation.

Usage:
    # At application startup:
    from agent_core.core.registry.task_manager import TaskManagerRegistry

    TaskManagerRegistry.register(lambda: task_manager)

    # In shared code:
    manager = TaskManagerRegistry.get()
    task_id = manager.create_task("My Task", "Do something")
"""

from typing import TYPE_CHECKING

from agent_core.core.registry.base import ComponentRegistry

if TYPE_CHECKING:
    from agent_core.core.protocols.task_manager import TaskManagerProtocol


class TaskManagerRegistry(ComponentRegistry["TaskManagerProtocol"]):
    """
    Registry for accessing the TaskManager instance.

    Each project (CraftBot, CraftBot) registers their task
    manager at startup. Shared code uses get() to access the manager.
    """
    pass


def get_task_manager() -> "TaskManagerProtocol":
    """
    Get the registered task manager.

    Returns:
        The TaskManager instance.

    Raises:
        RuntimeError: If TaskManagerRegistry has not been initialized.
    """
    return TaskManagerRegistry.get()


def get_task_manager_or_none() -> "TaskManagerProtocol | None":
    """
    Get the task manager, or None if not available.

    Returns:
        The TaskManager instance, or None if unavailable.
    """
    return TaskManagerRegistry.get_or_none()
