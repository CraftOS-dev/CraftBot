# -*- coding: utf-8 -*-
"""
Registry for MemoryManager.

This module provides the MemoryRegistry for accessing the memory manager
instance without knowing the underlying implementation.

Usage:
    # At application startup:
    from agent_core.core.registry.memory import MemoryRegistry
    from agent_core.core.impl.memory import MemoryManager

    memory = MemoryManager(
        agent_file_system_path="./agent_file_system",
        chroma_path="./chroma_db_memory"
    )
    MemoryRegistry.register(lambda: memory)

    # In shared code:
    memory = MemoryRegistry.get()
    pointers = memory.retrieve("user preferences")
"""

from typing import TYPE_CHECKING

from agent_core.core.registry.base import ComponentRegistry

if TYPE_CHECKING:
    from agent_core.core.protocols.memory import MemoryManagerProtocol


class MemoryRegistry(ComponentRegistry["MemoryManagerProtocol"]):
    """
    Registry for accessing the MemoryManager instance.

    Each project (CraftBot, CraftBot) registers their memory
    manager at startup. Shared code uses get() to access the manager.
    """
    pass


def get_memory_manager() -> "MemoryManagerProtocol":
    """
    Get the registered memory manager.

    Returns:
        The MemoryManager instance.

    Raises:
        RuntimeError: If MemoryRegistry has not been initialized.
    """
    return MemoryRegistry.get()


def get_memory_manager_or_none() -> "MemoryManagerProtocol | None":
    """
    Get the memory manager, or None if not available.

    Returns:
        The MemoryManager instance, or None if unavailable.
    """
    return MemoryRegistry.get_or_none()
