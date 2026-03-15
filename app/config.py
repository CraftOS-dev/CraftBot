# -*- coding: utf-8 -*-
"""
Root config for base agent, should be overwrite by specialise agent

All configuration is read from settings.json - no .env file is used.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def get_project_root() -> Path:
    """Get the project root directory"""
    if getattr(sys, 'frozen', False):
        # Frozen exe: use CWD so logs/workspace persist (not the temp _MEIPASS dir)
        return Path.cwd()
    return Path(__file__).resolve().parent.parent

PROJECT_ROOT = get_project_root()
AGENT_WORKSPACE_ROOT = PROJECT_ROOT / "agent_file_system/workspace"
AGENT_FILE_SYSTEM_PATH = PROJECT_ROOT / "agent_file_system"
APP_DATA_PATH = PROJECT_ROOT / "app" / "data"
APP_CONFIG_PATH = PROJECT_ROOT / "app" / "config"
AGENT_FILE_SYSTEM_TEMPLATE_PATH = APP_DATA_PATH / "agent_file_system_template"
AGENT_MEMORY_CHROMA_PATH = PROJECT_ROOT / "chroma_db_memory"
SETTINGS_CONFIG_PATH = APP_CONFIG_PATH / "settings.json"

# ─────────────────────────────────────────────────────────────────────────────
# Settings Reader - Single source of truth for all configuration
# ─────────────────────────────────────────────────────────────────────────────

_settings_cache: Optional[Dict[str, Any]] = None


def _get_default_settings() -> Dict[str, Any]:
    """Return default settings structure."""
    return {
        "general": {"agent_name": "CraftBot"},
        "proactive": {"enabled": True},
        "memory": {"enabled": True},
        "model": {
            "llm_provider": "anthropic",
            "vlm_provider": "anthropic",
            "llm_model": None,
            "vlm_model": None,
        },
        "api_keys": {
            "openai": "",
            "anthropic": "",
            "google": "",
            "byteplus": "",
        },
        "endpoints": {
            "remote_model_url": "",
            "byteplus_base_url": "https://ark.ap-southeast.bytepluses.com/api/v3",
            "google_api_base": "",
            "google_api_version": "",
        },
        "web_search": {
            "google_cse_id": "",
        },
        "gui": {
            "enabled": True,
            "use_omniparser": False,
            "omniparser_url": "http://127.0.0.1:7861",
        },
    }


def get_settings(reload: bool = False) -> Dict[str, Any]:
    """Load and return settings from settings.json.

    Args:
        reload: If True, reload from disk even if cached.

    Returns:
        Dictionary with all settings.
    """
    global _settings_cache

    if _settings_cache is not None and not reload:
        return _settings_cache

    if not SETTINGS_CONFIG_PATH.exists():
        _settings_cache = _get_default_settings()
        return _settings_cache

    try:
        with open(SETTINGS_CONFIG_PATH, "r", encoding="utf-8") as f:
            _settings_cache = json.load(f)
        return _settings_cache
    except (json.JSONDecodeError, IOError):
        _settings_cache = _get_default_settings()
        return _settings_cache


def get_llm_provider() -> str:
    """Get configured LLM provider."""
    settings = get_settings()
    return settings.get("model", {}).get("llm_provider", "anthropic")


def get_vlm_provider() -> str:
    """Get configured VLM provider."""
    settings = get_settings()
    model = settings.get("model", {})
    return model.get("vlm_provider") or model.get("llm_provider", "anthropic")


def get_llm_model() -> Optional[str]:
    """Get configured LLM model override (or None for default)."""
    settings = get_settings()
    return settings.get("model", {}).get("llm_model")


def get_vlm_model() -> Optional[str]:
    """Get configured VLM model override (or None for default)."""
    settings = get_settings()
    return settings.get("model", {}).get("vlm_model")


def get_api_key(provider: str) -> str:
    """Get API key for a provider.

    Args:
        provider: Provider name (openai, anthropic, google, byteplus)

    Returns:
        API key string (empty string if not configured)
    """
    settings = get_settings()
    api_keys = settings.get("api_keys", {})

    # Map provider names to settings keys
    key_map = {
        "openai": "openai",
        "anthropic": "anthropic",
        "gemini": "google",
        "google": "google",
        "byteplus": "byteplus",
    }

    settings_key = key_map.get(provider, provider)
    return api_keys.get(settings_key, "")


def get_base_url(provider: str) -> Optional[str]:
    """Get base URL for a provider.

    Args:
        provider: Provider name (byteplus, remote)

    Returns:
        Base URL string or None if not configured
    """
    settings = get_settings()
    endpoints = settings.get("endpoints", {})

    if provider == "byteplus":
        url = endpoints.get("byteplus_base_url", "")
        return url if url else "https://ark.ap-southeast.bytepluses.com/api/v3"
    elif provider == "remote":
        url = endpoints.get("remote_model_url", "")
        return url if url else "http://localhost:11434"
    elif provider == "gemini" or provider == "google":
        return endpoints.get("google_api_base") or None

    return None


def get_google_api_version() -> Optional[str]:
    """Get Google API version override."""
    settings = get_settings()
    return settings.get("endpoints", {}).get("google_api_version") or None


def get_web_search_cse_id() -> str:
    """Get Google Custom Search Engine ID."""
    settings = get_settings()
    return settings.get("web_search", {}).get("google_cse_id", "")


def reload_settings() -> Dict[str, Any]:
    """Force reload settings from disk."""
    return get_settings(reload=True)


MAX_ACTIONS_PER_TASK: int = 500
MAX_TOKEN_PER_TASK: int = 12000000 # of tokens

# Memory processing configuration
PROCESS_MEMORY_AT_STARTUP: bool = False  # Process EVENT_UNPROCESSED.md into MEMORY.md at startup
MEMORY_PROCESSING_SCHEDULE_HOUR: int = 3  # Hour (0-23) to run daily memory processing

# Credential storage mode (local-only in CraftBot)
USE_REMOTE_CREDENTIALS: bool = False

# OAuth client credentials
# Uses embedded credentials with environment variable override
# See core/credentials/embedded_credentials.py for credential management
import os
from agent_core import get_credential

# Google (PKCE - only client_id required, secret kept for backwards compatibility)
GOOGLE_CLIENT_ID: str = get_credential("google", "client_id", "GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# LinkedIn (requires both client_id and client_secret)
LINKEDIN_CLIENT_ID: str = get_credential("linkedin", "client_id", "LINKEDIN_CLIENT_ID")
LINKEDIN_CLIENT_SECRET: str = get_credential("linkedin", "client_secret", "LINKEDIN_CLIENT_SECRET")

# Outlook / Microsoft (PKCE - only client_id required)
OUTLOOK_CLIENT_ID: str = get_credential("outlook", "client_id", "OUTLOOK_CLIENT_ID")

# Slack (requires both client_id and client_secret - no PKCE support)
SLACK_SHARED_CLIENT_ID: str = get_credential("slack", "client_id", "SLACK_SHARED_CLIENT_ID")
SLACK_SHARED_CLIENT_SECRET: str = get_credential("slack", "client_secret", "SLACK_SHARED_CLIENT_SECRET")

# Telegram (token-based, not OAuth)
TELEGRAM_SHARED_BOT_TOKEN: str = os.environ.get("TELEGRAM_SHARED_BOT_TOKEN", "")
TELEGRAM_SHARED_BOT_USERNAME: str = os.environ.get("TELEGRAM_SHARED_BOT_USERNAME", "")

# Telegram API credentials for MTProto user login (from https://my.telegram.org)
TELEGRAM_API_ID: str = os.environ.get("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH: str = os.environ.get("TELEGRAM_API_HASH", "")

# Notion (requires both client_id and client_secret - no PKCE support)
NOTION_SHARED_CLIENT_ID: str = get_credential("notion", "client_id", "NOTION_SHARED_CLIENT_ID")
NOTION_SHARED_CLIENT_SECRET: str = get_credential("notion", "client_secret", "NOTION_SHARED_CLIENT_SECRET")