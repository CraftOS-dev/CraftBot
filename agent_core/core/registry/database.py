# -*- coding: utf-8 -*-
"""
Registry for DatabaseInterface.

This module provides the DatabaseRegistry for accessing the database
interface instance without knowing the underlying implementation.

Usage:
    # At application startup:
    from agent_core.core.registry.database import DatabaseRegistry
    from agent_core import DatabaseInterface

    db = DatabaseInterface(data_dir="./data", chroma_path="./chroma")
    DatabaseRegistry.register(lambda: db)

    # In shared code:
    db = DatabaseRegistry.get()
    db.log_task(task)
"""

from typing import TYPE_CHECKING

from agent_core.core.registry.base import ComponentRegistry

if TYPE_CHECKING:
    from agent_core.core.protocols.database import DatabaseInterfaceProtocol


class DatabaseRegistry(ComponentRegistry["DatabaseInterfaceProtocol"]):
    """
    Registry for accessing the DatabaseInterface instance.

    Each project (CraftBot, CraftBot) registers their database
    instance at startup. Shared code uses get() to access the database.
    """
    pass


def get_database() -> "DatabaseInterfaceProtocol":
    """
    Get the registered database interface.

    Returns:
        The DatabaseInterface instance.

    Raises:
        RuntimeError: If DatabaseRegistry has not been initialized.
    """
    return DatabaseRegistry.get()


def get_database_or_none() -> "DatabaseInterfaceProtocol | None":
    """
    Get the database interface, or None if not available.

    Returns:
        The DatabaseInterface instance, or None if unavailable.
    """
    return DatabaseRegistry.get_or_none()
