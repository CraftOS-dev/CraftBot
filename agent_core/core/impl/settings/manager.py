# -*- coding: utf-8 -*-
"""
Settings Manager Module

Singleton manager for application settings with hot-reload support.
All settings are loaded from settings.json and can be reloaded at runtime.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from threading import Lock

from agent_core.utils.logger import logger

# Default settings path
DEFAULT_SETTINGS_PATH = Path("app/config/settings.json")

# Default settings structure
DEFAULT_SETTINGS = {
    "general": {
        "agent_name": "CraftBot"
    },
    "proactive": {
        "enabled": False
    },
    "memory": {
        "enabled": True
    },
    "model": {
        "llm_provider": "gemini",
        "vlm_provider": "gemini",
        "llm_model": None,
        "vlm_model": None
    },
    "api_keys": {
        "openai": "",
        "anthropic": "",
        "google": "",
        "byteplus": ""
    },
    "endpoints": {
        "remote_model_url": "",
        "byteplus_base_url": "https://ark.ap-southeast.bytepluses.com/api/v3",
        "google_api_base": "",
        "google_api_version": ""
    },
    "gui": {
        "enabled": True,
        "use_omniparser": False,
        "omniparser_url": "http://127.0.0.1:7861"
    },
    "cache": {
        "prefix_ttl": 3600,
        "session_ttl": 7200,
        "min_tokens": 500
    },
    "oauth": {
        "google": {"client_id": "", "client_secret": ""},
        "linkedin": {"client_id": "", "client_secret": ""},
        "slack": {"client_id": "", "client_secret": ""},
        "notion": {"client_id": "", "client_secret": ""},
        "outlook": {"client_id": ""}
    },
    "web_search": {
        "google_cse_id": ""
    },
    "browser": {
        "port": 7926,
        "startup_ui": False
    }
}


class SettingsManager:
    """
    Singleton manager for application settings.

    Provides:
    - Centralized access to all settings
    - Hot-reload capability when settings.json changes
    - Type-safe getters for common settings
    """

    _instance: Optional["SettingsManager"] = None
    _lock = Lock()

    def __new__(cls) -> "SettingsManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._settings: Dict[str, Any] = {}
        self._settings_path: Optional[Path] = None
        self._reload_callbacks: list = []
        self._initialized = True

    def initialize(self, settings_path: Optional[Path] = None) -> None:
        """
        Initialize the settings manager.

        Args:
            settings_path: Path to settings.json. If None, uses default path.
        """
        self._settings_path = Path(settings_path) if settings_path else DEFAULT_SETTINGS_PATH
        self._load_settings()
        logger.info(f"[SETTINGS] Initialized from {self._settings_path}")

    def _load_settings(self) -> None:
        """Load settings from file, merging with defaults. Creates file if missing."""
        self._settings = self._deep_copy(DEFAULT_SETTINGS)

        if self._settings_path:
            if self._settings_path.exists():
                try:
                    with open(self._settings_path, "r", encoding="utf-8") as f:
                        file_settings = json.load(f)
                    self._deep_merge(self._settings, file_settings)
                    logger.debug(f"[SETTINGS] Loaded settings from {self._settings_path}")
                except Exception as e:
                    logger.warning(f"[SETTINGS] Failed to load settings: {e}, using defaults")
            else:
                # Create settings file with defaults if it doesn't exist
                try:
                    self._settings_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(self._settings_path, "w", encoding="utf-8") as f:
                        json.dump(self._settings, f, indent=2)
                    logger.info(f"[SETTINGS] Created default settings file at {self._settings_path}")
                except Exception as e:
                    logger.warning(f"[SETTINGS] Failed to create default settings file: {e}")

    def _deep_copy(self, obj: Any) -> Any:
        """Deep copy a nested dict/list structure."""
        if isinstance(obj, dict):
            return {k: self._deep_copy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._deep_copy(v) for v in obj]
        return obj

    def _deep_merge(self, base: dict, override: dict) -> None:
        """Deep merge override into base dict."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def reload(self) -> Dict[str, Any]:
        """
        Hot-reload settings from file.

        Returns:
            Dictionary with reload results.
        """
        result = {
            "success": True,
            "message": "",
        }

        try:
            old_settings = self._deep_copy(self._settings)
            self._load_settings()

            # Notify callbacks
            for callback in self._reload_callbacks:
                try:
                    callback(self._settings, old_settings)
                except Exception as e:
                    logger.warning(f"[SETTINGS] Reload callback failed: {e}")

            result["message"] = "Settings reloaded successfully"
            logger.info("[SETTINGS] Hot-reload complete")
        except Exception as e:
            result["success"] = False
            result["message"] = f"Failed to reload settings: {e}"
            logger.error(f"[SETTINGS] Reload failed: {e}")

        return result

    def register_reload_callback(self, callback) -> None:
        """Register a callback to be called when settings are reloaded."""
        self._reload_callbacks.append(callback)

    def save(self) -> bool:
        """Save current settings to file."""
        if not self._settings_path:
            return False

        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._settings_path, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"[SETTINGS] Failed to save settings: {e}")
            return False

    # ─────────────────────── Getters ───────────────────────

    def get(self, *keys, default: Any = None) -> Any:
        """
        Get a nested setting value.

        Args:
            *keys: Path to the setting (e.g., "model", "llm_provider")
            default: Default value if not found

        Returns:
            The setting value or default
        """
        value = self._settings
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def get_all(self) -> Dict[str, Any]:
        """Get all settings."""
        return self._deep_copy(self._settings)

    # Convenience getters

    @property
    def agent_name(self) -> str:
        return self.get("general", "agent_name", default="CraftBot")

    @property
    def llm_provider(self) -> str:
        return self.get("model", "llm_provider", default="openai")

    @property
    def vlm_provider(self) -> str:
        return self.get("model", "vlm_provider", default="openai")

    @property
    def llm_model(self) -> str:
        return self.get("model", "llm_model", default="")

    @property
    def vlm_model(self) -> str:
        return self.get("model", "vlm_model", default="")

    @property
    def memory_enabled(self) -> bool:
        return self.get("memory", "enabled", default=True)

    @property
    def proactive_enabled(self) -> bool:
        return self.get("proactive", "enabled", default=True)

    @property
    def gui_enabled(self) -> bool:
        return self.get("gui", "enabled", default=True)

    def get_api_key(self, provider: str) -> str:
        """Get API key for a provider."""
        return self.get("api_keys", provider, default="")

    def get_oauth_credentials(self, provider: str) -> Dict[str, str]:
        """Get OAuth credentials for a provider."""
        return self.get("oauth", provider, default={})


# Global singleton instance
settings_manager = SettingsManager()
