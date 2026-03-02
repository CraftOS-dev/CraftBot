# -*- coding: utf-8 -*-
"""
app.external_comms

External communication channels for CraftBot.
Enables receiving messages from WhatsApp, Telegram, and other platforms.
"""

from app.external_comms.config import (
    TelegramConfig,
    WhatsAppConfig,
    ExternalCommsConfig,
    get_config,
    load_config,
    save_config,
    reload_config,
)

from app.external_comms.manager import (
    ExternalCommsManager,
    BaseChannel,
    TelegramChannel,
    WhatsAppChannel,
    get_external_comms_manager,
    initialize_manager,
)

__all__ = [
    # Config
    "TelegramConfig",
    "WhatsAppConfig",
    "ExternalCommsConfig",
    "get_config",
    "load_config",
    "save_config",
    "reload_config",
    # Manager
    "ExternalCommsManager",
    "BaseChannel",
    "TelegramChannel",
    "WhatsAppChannel",
    "get_external_comms_manager",
    "initialize_manager",
]
