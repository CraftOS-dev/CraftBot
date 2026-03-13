# -*- coding: utf-8 -*-
"""
Registries for EventStream and EventStreamManager.

This module provides registries for accessing event stream components
without knowing the underlying implementation.

Usage:
    # At application startup:
    from agent_core.core.registry.event_stream import EventStreamManagerRegistry

    EventStreamManagerRegistry.register(lambda: event_stream_manager)

    # In shared code:
    manager = EventStreamManagerRegistry.get()
    manager.log("INFO", "Something happened")
"""

from typing import TYPE_CHECKING

from agent_core.core.registry.base import ComponentRegistry

if TYPE_CHECKING:
    from agent_core.core.protocols.event_stream import (
        EventStreamProtocol,
        EventStreamManagerProtocol,
    )


class EventStreamRegistry(ComponentRegistry["EventStreamProtocol"]):
    """
    Registry for accessing the current EventStream instance.

    Note: In most cases, use EventStreamManagerRegistry instead,
    as it handles per-task stream management automatically.
    """
    pass


class EventStreamManagerRegistry(ComponentRegistry["EventStreamManagerProtocol"]):
    """
    Registry for accessing the EventStreamManager instance.

    Each project (CraftBot, CraftBot) registers their manager
    at startup. Shared code uses get() to access the manager.
    """
    pass


def get_event_stream() -> "EventStreamProtocol":
    """
    Get the registered event stream.

    Returns:
        The EventStream instance.

    Raises:
        RuntimeError: If EventStreamRegistry has not been initialized.
    """
    return EventStreamRegistry.get()


def get_event_stream_or_none() -> "EventStreamProtocol | None":
    """
    Get the event stream, or None if not available.

    Returns:
        The EventStream instance, or None if unavailable.
    """
    return EventStreamRegistry.get_or_none()


def get_event_stream_manager() -> "EventStreamManagerProtocol":
    """
    Get the registered event stream manager.

    Returns:
        The EventStreamManager instance.

    Raises:
        RuntimeError: If EventStreamManagerRegistry has not been initialized.
    """
    return EventStreamManagerRegistry.get()


def get_event_stream_manager_or_none() -> "EventStreamManagerProtocol | None":
    """
    Get the event stream manager, or None if not available.

    Returns:
        The EventStreamManager instance, or None if unavailable.
    """
    return EventStreamManagerRegistry.get_or_none()
