"""Settings utilities for the TUI interface."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from app.logger import logger
from app.models.provider_config import PROVIDER_CONFIG
from app.config import SETTINGS_CONFIG_PATH


# Provider to settings.json api_keys key mapping
PROVIDER_TO_SETTINGS_KEY = {
    "openai": "openai",
    "gemini": "google",
    "google": "google",
    "byteplus": "byteplus",
    "anthropic": "anthropic",
}


def _load_settings() -> Dict[str, Any]:
    """Load settings from settings.json."""
    if not SETTINGS_CONFIG_PATH.exists():
        return {}
    try:
        with open(SETTINGS_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(settings: Dict[str, Any]) -> bool:
    """Save settings to settings.json."""
    try:
        SETTINGS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"[SETTINGS] Failed to save settings.json: {e}")
        return False


def save_settings_to_json(provider: str, api_key: str) -> bool:
    """Save provider and API key to settings.json.

    Args:
        provider: The LLM provider name
        api_key: The API key for the provider

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        settings = _load_settings()

        # Ensure model section exists
        if "model" not in settings:
            settings["model"] = {}

        # Update provider
        settings["model"]["llm_provider"] = provider
        settings["model"]["vlm_provider"] = provider

        # Update API key if provided
        if api_key:
            if "api_keys" not in settings:
                settings["api_keys"] = {}

            settings_key = PROVIDER_TO_SETTINGS_KEY.get(provider, provider)
            settings["api_keys"][settings_key] = api_key

        # Save to file
        if not _save_settings(settings):
            return False

        # Also sync to os.environ for current session
        _sync_to_environ(provider, api_key)

        logger.info(f"[SETTINGS] Saved provider={provider} to settings.json")
        return True

    except Exception as e:
        logger.error(f"[SETTINGS] Failed to save to settings.json: {e}")
        return False


def _sync_to_environ(provider: str, api_key: str) -> None:
    """Sync provider and API key to os.environ for current session."""
    os.environ["LLM_PROVIDER"] = provider
    os.environ["VLM_PROVIDER"] = provider

    if api_key:
        api_key_env = get_api_key_env_name(provider)
        if api_key_env:
            os.environ[api_key_env] = api_key


# Keep old function name as alias for backwards compatibility
save_settings_to_env = save_settings_to_json


def get_api_key_env_name(provider: str) -> Optional[str]:
    """Get the environment variable name for a provider's API key."""
    if provider not in PROVIDER_CONFIG:
        return None
    return PROVIDER_CONFIG[provider].api_key_env


def get_current_provider() -> str:
    """Get the current LLM provider from settings.json or os.environ."""
    settings = _load_settings()
    return settings.get("model", {}).get("llm_provider") or os.environ.get("LLM_PROVIDER", "openai")


def get_api_key_for_provider(provider: str) -> str:
    """Get the API key for a provider from settings.json or os.environ."""
    settings = _load_settings()
    settings_key = PROVIDER_TO_SETTINGS_KEY.get(provider, provider)

    # Try settings.json first
    api_key = settings.get("api_keys", {}).get(settings_key, "")
    if api_key:
        return api_key

    # Fall back to os.environ
    api_key_env = get_api_key_env_name(provider)
    if api_key_env:
        return os.environ.get(api_key_env, "")

    return ""
