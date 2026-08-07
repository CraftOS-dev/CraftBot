# -*- coding: utf-8 -*-
"""
Registry for SessionManager.

This module provides the SessionManagerRegistry for accessing the session
manager instance without knowing the underlying implementation.

Usage:
    # At application startup:
    from agent_core.core.registry.session_manager import SessionManagerRegistry

    SessionManagerRegistry.register(lambda: session_manager)

    # In shared code:
    manager = SessionManagerRegistry.get()
    session = manager.get(session_id)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_core.core.registry.base import ComponentRegistry

if TYPE_CHECKING:
    from agent_core.core.protocols.session_manager import SessionManagerProtocol


class SessionManagerRegistry(ComponentRegistry["SessionManagerProtocol"]):
    """
    Registry for accessing the SessionManager instance.

    The application registers its session manager at startup. Shared code
    uses get() to access the manager.
    """

    pass


def get_session_manager() -> "SessionManagerProtocol":
    """
    Get the registered session manager.

    Returns:
        The SessionManager instance.

    Raises:
        RuntimeError: If SessionManagerRegistry has not been initialized.
    """
    return SessionManagerRegistry.get()


def get_session_manager_or_none() -> "SessionManagerProtocol | None":
    """
    Get the session manager, or None if not available.

    Returns:
        The SessionManager instance, or None if unavailable.
    """
    return SessionManagerRegistry.get_or_none()
