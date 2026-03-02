# -*- coding: utf-8 -*-
"""
app.external_comms.config

Configuration for external communication channels (WhatsApp, Telegram).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


@dataclass
class TelegramConfig:
    """Configuration for Telegram integration."""
    enabled: bool = False
    mode: str = "bot"  # "bot" for Bot API, "mtproto" for user account
    bot_token: str = ""
    bot_username: str = ""
    # MTProto settings (for user account mode)
    api_id: str = ""
    api_hash: str = ""
    phone_number: str = ""
    # Behavior settings
    auto_reply: bool = True  # Automatically route messages to agent


@dataclass
class WhatsAppConfig:
    """Configuration for WhatsApp integration."""
    enabled: bool = False
    mode: str = "web"  # "web" for WhatsApp Web, "business" for Business API
    # WhatsApp Web settings
    session_id: str = ""
    # Business API settings
    phone_number_id: str = ""
    access_token: str = ""
    # Behavior settings
    auto_reply: bool = True  # Automatically route messages to agent


@dataclass
class ExternalCommsConfig:
    """Configuration for all external communication channels."""
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExternalCommsConfig":
        """Create config from dictionary."""
        telegram_data = data.get("telegram", {})
        whatsapp_data = data.get("whatsapp", {})

        return cls(
            telegram=TelegramConfig(
                enabled=telegram_data.get("enabled", False),
                mode=telegram_data.get("mode", "bot"),
                bot_token=telegram_data.get("bot_token", ""),
                bot_username=telegram_data.get("bot_username", ""),
                api_id=telegram_data.get("api_id", ""),
                api_hash=telegram_data.get("api_hash", ""),
                phone_number=telegram_data.get("phone_number", ""),
                auto_reply=telegram_data.get("auto_reply", True),
            ),
            whatsapp=WhatsAppConfig(
                enabled=whatsapp_data.get("enabled", False),
                mode=whatsapp_data.get("mode", "web"),
                session_id=whatsapp_data.get("session_id", ""),
                phone_number_id=whatsapp_data.get("phone_number_id", ""),
                access_token=whatsapp_data.get("access_token", ""),
                auto_reply=whatsapp_data.get("auto_reply", True),
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "telegram": {
                "enabled": self.telegram.enabled,
                "mode": self.telegram.mode,
                "bot_token": self.telegram.bot_token,
                "bot_username": self.telegram.bot_username,
                "api_id": self.telegram.api_id,
                "api_hash": self.telegram.api_hash,
                "phone_number": self.telegram.phone_number,
                "auto_reply": self.telegram.auto_reply,
            },
            "whatsapp": {
                "enabled": self.whatsapp.enabled,
                "mode": self.whatsapp.mode,
                "session_id": self.whatsapp.session_id,
                "phone_number_id": self.whatsapp.phone_number_id,
                "access_token": self.whatsapp.access_token,
                "auto_reply": self.whatsapp.auto_reply,
            },
        }


def load_config(config_path: Optional[Path] = None) -> ExternalCommsConfig:
    """
    Load external communications configuration.

    Loads from config file and applies environment variable overrides.

    Args:
        config_path: Path to config JSON file. If None, uses default location.

    Returns:
        ExternalCommsConfig instance.
    """
    config_data = {}

    # Load from file if exists
    if config_path is None:
        from app.config import PROJECT_ROOT
        config_path = PROJECT_ROOT / "app" / "config" / "external_comms_config.json"

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            logger.info(f"[EXTERNAL_COMMS] Loaded config from {config_path}")
        except Exception as e:
            logger.warning(f"[EXTERNAL_COMMS] Failed to load config: {e}")

    # Create config from file data
    config = ExternalCommsConfig.from_dict(config_data)

    # Apply environment variable overrides
    _apply_env_overrides(config)

    return config


def _apply_env_overrides(config: ExternalCommsConfig) -> None:
    """Apply environment variable overrides to config."""
    # Master switch
    if os.getenv("ENABLE_EXTERNAL_COMMS", "").lower() == "true":
        # Individual channel toggles still apply
        pass

    # Telegram overrides
    if os.getenv("ENABLE_TELEGRAM", "").lower() == "true":
        config.telegram.enabled = True
    if os.getenv("TELEGRAM_SHARED_BOT_TOKEN"):
        config.telegram.bot_token = os.getenv("TELEGRAM_SHARED_BOT_TOKEN", "")
    if os.getenv("TELEGRAM_SHARED_BOT_USERNAME"):
        config.telegram.bot_username = os.getenv("TELEGRAM_SHARED_BOT_USERNAME", "")
    if os.getenv("TELEGRAM_API_ID"):
        config.telegram.api_id = os.getenv("TELEGRAM_API_ID", "")
    if os.getenv("TELEGRAM_API_HASH"):
        config.telegram.api_hash = os.getenv("TELEGRAM_API_HASH", "")

    # WhatsApp overrides
    if os.getenv("ENABLE_WHATSAPP", "").lower() == "true":
        config.whatsapp.enabled = True


def save_config(config: ExternalCommsConfig, config_path: Optional[Path] = None) -> None:
    """
    Save external communications configuration to file.

    Args:
        config: Configuration to save.
        config_path: Path to config JSON file. If None, uses default location.
    """
    if config_path is None:
        from app.config import PROJECT_ROOT
        config_path = PROJECT_ROOT / "app" / "config" / "external_comms_config.json"

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2)
        logger.info(f"[EXTERNAL_COMMS] Saved config to {config_path}")
    except Exception as e:
        logger.error(f"[EXTERNAL_COMMS] Failed to save config: {e}")


# Global config instance
_config: Optional[ExternalCommsConfig] = None


def get_config() -> ExternalCommsConfig:
    """Get the global external communications config."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> ExternalCommsConfig:
    """Reload configuration from file."""
    global _config
    _config = load_config()
    return _config
