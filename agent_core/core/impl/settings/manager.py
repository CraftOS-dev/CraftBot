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
        "enabled": True
    },
    "memory": {
        "enabled": True
    },
    "model": {
        "llm_provider": "openai",
        "vlm_provider": "openai",
        "llm_model": "",
        "vlm_model": ""
    },
    "api_keys": {
        "openai": "",
        "anthropic": "",
        "google": "",
        "byteplus": ""
    },
    "endpoints": {
        "remote_model_url": "",
        "byteplus_base_url": "",
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
    - Backwards compatibility with os.environ for API keys
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
        self._sync_to_environ()
        logger.info(f"[SETTINGS] Initialized from {self._settings_path}")

    def _load_settings(self) -> None:
        """Load settings from file, merging with defaults."""
        self._settings = self._deep_copy(DEFAULT_SETTINGS)

        if self._settings_path and self._settings_path.exists():
            try:
                with open(self._settings_path, "r", encoding="utf-8") as f:
                    file_settings = json.load(f)
                self._deep_merge(self._settings, file_settings)
                logger.debug(f"[SETTINGS] Loaded settings from {self._settings_path}")
            except Exception as e:
                logger.warning(f"[SETTINGS] Failed to load settings: {e}, using defaults")

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

    def _sync_to_environ(self) -> None:
        """
        Sync API keys and critical settings to os.environ for backwards compatibility.
        This allows existing code that reads from os.environ to continue working.
        """
        # API Keys
        api_keys = self._settings.get("api_keys", {})
        env_mapping = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "byteplus": "BYTEPLUS_API_KEY"
        }
        for key, env_var in env_mapping.items():
            value = api_keys.get(key, "")
            if value:
                os.environ[env_var] = value

        # Model provider
        model = self._settings.get("model", {})
        if model.get("llm_provider"):
            os.environ["LLM_PROVIDER"] = model["llm_provider"]
        if model.get("vlm_provider"):
            os.environ["VLM_PROVIDER"] = model["vlm_provider"]

        # Endpoints
        endpoints = self._settings.get("endpoints", {})
        if endpoints.get("remote_model_url"):
            os.environ["REMOTE_MODEL_URL"] = endpoints["remote_model_url"]
        if endpoints.get("byteplus_base_url"):
            os.environ["BYTEPLUS_BASE_URL"] = endpoints["byteplus_base_url"]
        if endpoints.get("google_api_base"):
            os.environ["GOOGLE_API_BASE"] = endpoints["google_api_base"]
        if endpoints.get("google_api_version"):
            os.environ["GOOGLE_API_VERSION"] = endpoints["google_api_version"]

        # GUI
        gui = self._settings.get("gui", {})
        os.environ["GUI_MODE_ENABLED"] = str(gui.get("enabled", True))
        os.environ["USE_OMNIPARSER"] = str(gui.get("use_omniparser", False))
        if gui.get("omniparser_url"):
            os.environ["OMNIPARSER_BASE_URL"] = gui["omniparser_url"]

        # Cache
        cache = self._settings.get("cache", {})
        os.environ["CACHE_PREFIX_TTL"] = str(cache.get("prefix_ttl", 3600))
        os.environ["CACHE_SESSION_TTL"] = str(cache.get("session_ttl", 7200))
        os.environ["CACHE_MIN_TOKENS"] = str(cache.get("min_tokens", 500))

        # OAuth
        oauth = self._settings.get("oauth", {})
        if oauth.get("google", {}).get("client_id"):
            os.environ["GOOGLE_CLIENT_ID"] = oauth["google"]["client_id"]
        if oauth.get("google", {}).get("client_secret"):
            os.environ["GOOGLE_CLIENT_SECRET"] = oauth["google"]["client_secret"]
        if oauth.get("linkedin", {}).get("client_id"):
            os.environ["LINKEDIN_CLIENT_ID"] = oauth["linkedin"]["client_id"]
        if oauth.get("linkedin", {}).get("client_secret"):
            os.environ["LINKEDIN_CLIENT_SECRET"] = oauth["linkedin"]["client_secret"]
        if oauth.get("slack", {}).get("client_id"):
            os.environ["SLACK_SHARED_CLIENT_ID"] = oauth["slack"]["client_id"]
        if oauth.get("slack", {}).get("client_secret"):
            os.environ["SLACK_SHARED_CLIENT_SECRET"] = oauth["slack"]["client_secret"]
        if oauth.get("notion", {}).get("client_id"):
            os.environ["NOTION_SHARED_CLIENT_ID"] = oauth["notion"]["client_id"]
        if oauth.get("notion", {}).get("client_secret"):
            os.environ["NOTION_SHARED_CLIENT_SECRET"] = oauth["notion"]["client_secret"]
        if oauth.get("outlook", {}).get("client_id"):
            os.environ["OUTLOOK_CLIENT_ID"] = oauth["outlook"]["client_id"]

        # Web search
        web_search = self._settings.get("web_search", {})
        if web_search.get("google_cse_id"):
            os.environ["GOOGLE_CSE_ID"] = web_search["google_cse_id"]

        # Browser - only set if not already set by run.py (run.py takes precedence)
        browser = self._settings.get("browser", {})
        if "BROWSER_PORT" not in os.environ:
            os.environ["BROWSER_PORT"] = str(browser.get("port", 7926))
        if "BROWSER_STARTUP_UI" not in os.environ:
            os.environ["BROWSER_STARTUP_UI"] = "1" if browser.get("startup_ui") else "0"

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
            self._sync_to_environ()

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
