# -*- coding: utf-8 -*-
"""
Registry for ContextEngine.

This module provides the ContextEngineRegistry for accessing the context
engine instance without knowing the underlying implementation.

Usage:
    # At application startup:
    from agent_core.core.registry.context import ContextEngineRegistry

    ContextEngineRegistry.register(lambda: context_engine)

    # In shared code:
    engine = ContextEngineRegistry.get()
    system_prompt, user_prompt = engine.make_prompt(query="...")
"""

from typing import TYPE_CHECKING

from agent_core.core.registry.base import ComponentRegistry

if TYPE_CHECKING:
    from agent_core.core.protocols.context import ContextEngineProtocol


class ContextEngineRegistry(ComponentRegistry["ContextEngineProtocol"]):
    """
    Registry for accessing the ContextEngine instance.

    Each project (CraftBot, CraftBot) registers their context
    engine at startup. Shared code uses get() to access the engine.
    """
    pass


def get_context_engine() -> "ContextEngineProtocol":
    """
    Get the registered context engine.

    Returns:
        The ContextEngine instance.

    Raises:
        RuntimeError: If ContextEngineRegistry has not been initialized.
    """
    return ContextEngineRegistry.get()


def get_context_engine_or_none() -> "ContextEngineProtocol | None":
    """
    Get the context engine, or None if not available.

    Returns:
        The ContextEngine instance, or None if unavailable.
    """
    return ContextEngineRegistry.get_or_none()
