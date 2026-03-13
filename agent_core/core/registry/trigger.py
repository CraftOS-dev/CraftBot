# -*- coding: utf-8 -*-
"""
Registry for TriggerQueue.
"""
from typing import Optional

from agent_core.core.registry.base import ComponentRegistry
from agent_core.core.protocols.trigger import TriggerQueueProtocol


class TriggerQueueRegistry(ComponentRegistry[TriggerQueueProtocol]):
    """Registry for accessing the TriggerQueue instance."""
    pass


def get_trigger_queue() -> TriggerQueueProtocol:
    """Get the registered TriggerQueue instance.

    Returns:
        The TriggerQueue instance.

    Raises:
        RuntimeError: If no TriggerQueue has been registered.
    """
    return TriggerQueueRegistry.get()


def get_trigger_queue_or_none() -> Optional[TriggerQueueProtocol]:
    """Get the registered TriggerQueue instance or None.

    Returns:
        The TriggerQueue instance, or None if not registered.
    """
    return TriggerQueueRegistry.get_or_none()
