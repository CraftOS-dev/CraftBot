# -*- coding: utf-8 -*-
"""
app.external_comms

External communication channels for CraftBot.
Enables receiving messages from WhatsApp, Telegram, and other platforms.
"""

from app.external_comms.config import (
    ExternalCommsConfig,
    get_config,
    load_config,
    save_config,
    reload_config,
)

from app.external_comms.manager import (
    ExternalCommsManager,
    get_external_comms_manager,
    initialize_manager,
)

from app.external_comms.base import BasePlatformClient, PlatformMessage
from app.external_comms.credentials import (
    has_credential,
    load_credential,
    save_credential,
    remove_credential,
)
from app.external_comms.registry import (
    register_client,
    get_client,
    get_all_clients,
    get_registered_platforms,
)

__all__ = [
    # Config
    "ExternalCommsConfig",
    "get_config",
    "load_config",
    "save_config",
    "reload_config",
    # Manager
    "ExternalCommsManager",
    "get_external_comms_manager",
    "initialize_manager",
    # Base
    "BasePlatformClient",
    "PlatformMessage",
    # Credentials
    "has_credential",
    "load_credential",
    "save_credential",
    "remove_credential",
    # Registry
    "register_client",
    "get_client",
    "get_all_clients",
    "get_registered_platforms",
]
