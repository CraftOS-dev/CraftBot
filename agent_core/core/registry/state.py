# -*- coding: utf-8 -*-
"""
Registry for StateManager.

This module provides the StateManagerRegistry for accessing the state
manager instance without knowing the underlying implementation.

Note: This is separate from StateRegistry which provides access to
the current state provider (StateSession or STATE singleton).

Usage:
    # At application startup:
    from agent_core.core.registry.state import StateManagerRegistry

    StateManagerRegistry.register(lambda: state_manager)

    # In shared code:
    manager = StateManagerRegistry.get()
    await manager.start_session()
"""

from typing import TYPE_CHECKING

from agent_core.core.registry.base import ComponentRegistry

if TYPE_CHECKING:
    from agent_core.core.protocols.state import StateManagerProtocol


class StateManagerRegistry(ComponentRegistry["StateManagerProtocol"]):
    """
    Registry for accessing the StateManager instance.

    Each project (CraftBot, CraftBot) registers their state
    manager at startup. Shared code uses get() to access the manager.

    Note: This is different from StateRegistry which provides access
    to the current state provider (StateSession.get() or STATE).
    """
    pass


def get_state_manager() -> "StateManagerProtocol":
    """
    Get the registered state manager.

    Returns:
        The StateManager instance.

    Raises:
        RuntimeError: If StateManagerRegistry has not been initialized.
    """
    return StateManagerRegistry.get()


def get_state_manager_or_none() -> "StateManagerProtocol | None":
    """
    Get the state manager, or None if not available.

    Returns:
        The StateManager instance, or None if unavailable.
    """
    return StateManagerRegistry.get_or_none()
