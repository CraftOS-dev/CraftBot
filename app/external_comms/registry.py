# -*- coding: utf-8 -*-
"""
app.external_comms.registry

Simple registry of platform clients.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Type

from app.external_comms.base import BasePlatformClient

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# Maps PLATFORM_ID -> client class
_client_classes: Dict[str, Type[BasePlatformClient]] = {}

# Maps PLATFORM_ID -> instantiated client (singletons)
_client_instances: Dict[str, BasePlatformClient] = {}


def register_client(client_cls: Type[BasePlatformClient]) -> Type[BasePlatformClient]:
    """
    Register a platform client class. Can be used as a decorator.

    Usage:
        @register_client
        class SlackClient(BasePlatformClient):
            PLATFORM_ID = "slack"
    """
    platform_id = client_cls.PLATFORM_ID
    if not platform_id:
        raise ValueError(f"{client_cls.__name__} has no PLATFORM_ID set")
    _client_classes[platform_id] = client_cls
    return client_cls


def get_client(platform_id: str) -> Optional[BasePlatformClient]:
    """
    Get (or create) a singleton client instance by platform ID.

    Returns None if the platform is not registered.
    """
    if platform_id in _client_instances:
        return _client_instances[platform_id]

    cls = _client_classes.get(platform_id)
    if cls is None:
        return None

    instance = cls()
    _client_instances[platform_id] = instance
    return instance


def get_all_clients() -> Dict[str, BasePlatformClient]:
    """Get all registered client instances (instantiating as needed)."""
    for platform_id in _client_classes:
        if platform_id not in _client_instances:
            _client_instances[platform_id] = _client_classes[platform_id]()
    return dict(_client_instances)


def get_registered_platforms() -> list[str]:
    """Get list of all registered platform IDs."""
    return list(_client_classes.keys())


def reset() -> None:
    """Clear all instances (useful for testing)."""
    _client_instances.clear()
