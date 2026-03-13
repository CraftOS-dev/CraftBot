# -*- coding: utf-8 -*-
"""
Registry for LLMInterface.

This module provides the LLMInterfaceRegistry for accessing the LLM
interface instance without knowing the underlying implementation.

Usage:
    # At application startup:
    from agent_core.core.registry.llm import LLMInterfaceRegistry
    from app.llm import LLMInterface

    llm = LLMInterface(provider="openai", model="gpt-4")
    LLMInterfaceRegistry.register(lambda: llm)

    # In shared code:
    llm = LLMInterfaceRegistry.get()
    response = await llm.generate_response_async(prompt)
"""

from typing import TYPE_CHECKING

from agent_core.core.registry.base import ComponentRegistry

if TYPE_CHECKING:
    from agent_core.core.protocols.llm import LLMInterfaceProtocol


class LLMInterfaceRegistry(ComponentRegistry["LLMInterfaceProtocol"]):
    """
    Registry for accessing the LLMInterface instance.

    Each project (CraftBot, CraftBot) registers their LLM
    interface at startup. Shared code uses get() to access the interface.
    """
    pass


def get_llm_interface() -> "LLMInterfaceProtocol":
    """
    Get the registered LLM interface.

    Returns:
        The LLMInterface instance.

    Raises:
        RuntimeError: If LLMInterfaceRegistry has not been initialized.
    """
    return LLMInterfaceRegistry.get()


def get_llm_interface_or_none() -> "LLMInterfaceProtocol | None":
    """
    Get the LLM interface, or None if not available.

    Returns:
        The LLMInterface instance, or None if unavailable.
    """
    return LLMInterfaceRegistry.get_or_none()
