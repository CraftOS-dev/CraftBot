"""Model settings management for UI layer.

Provides functions for managing model configuration including:
- LLM/VLM provider selection
- API key management
- Model selection per provider
- Connection testing

All settings are stored in settings.json (not .env).
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

from app.config import SETTINGS_CONFIG_PATH
from app.models import (
    PROVIDER_CONFIG,
    MODEL_REGISTRY,
    InterfaceType,
    test_provider_connection,
)


# Provider display names and settings.json key mapping
PROVIDER_INFO = {
    "openai": {
        "name": "OpenAI",
        "api_key_env": "OPENAI_API_KEY",
        "settings_key": "openai",
        "requires_api_key": True,
    },
    "anthropic": {
        "name": "Anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "settings_key": "anthropic",
        "requires_api_key": True,
    },
    "gemini": {
        "name": "Google Gemini",
        "api_key_env": "GOOGLE_API_KEY",
        "settings_key": "google",
        "requires_api_key": True,
    },
    "byteplus": {
        "name": "BytePlus",
        "api_key_env": "BYTEPLUS_API_KEY",
        "settings_key": "byteplus",
        "requires_api_key": True,
    },
    "remote": {
        "name": "Local (Ollama)",
        "base_url_env": "REMOTE_MODEL_URL",
        "requires_api_key": False,
    },
}


def _load_settings() -> Dict[str, Any]:
    """Load settings from settings.json."""
    if not SETTINGS_CONFIG_PATH.exists():
        return {
            "proactive": {"enabled": True},
            "memory": {"enabled": True},
            "general": {"agent_name": "CraftBot"},
            "model": {
                "llm_provider": "anthropic",
                "vlm_provider": "anthropic",
            },
            "api_keys": {},
            "endpoints": {},
        }

    try:
        with open(SETTINGS_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "proactive": {"enabled": True},
            "memory": {"enabled": True},
            "general": {"agent_name": "CraftBot"},
            "model": {
                "llm_provider": "anthropic",
                "vlm_provider": "anthropic",
            },
            "api_keys": {},
            "endpoints": {},
        }


def _save_settings(settings: Dict[str, Any]) -> bool:
    """Save settings to settings.json."""
    try:
        SETTINGS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception:
        return False


def _mask_api_key(api_key: str) -> str:
    """Mask API key for display, showing first 4 and last 4 characters."""
    if not api_key or len(api_key) < 12:
        return "***" if api_key else ""
    return f"{api_key[:4]}...{api_key[-4:]}"


# ─────────────────────────────────────────────────────────────────────
# Provider and Model Information
# ─────────────────────────────────────────────────────────────────────

def get_available_providers() -> Dict[str, Any]:
    """Get list of available providers with their information.

    Returns:
        Dict with provider info including name and models
    """
    try:
        providers = []

        for provider_id, info in PROVIDER_INFO.items():
            # Get models for this provider
            provider_models = MODEL_REGISTRY.get(provider_id, {})

            llm_model = provider_models.get(InterfaceType.LLM)
            vlm_model = provider_models.get(InterfaceType.VLM)

            providers.append({
                "id": provider_id,
                "name": info["name"],
                "requires_api_key": info.get("requires_api_key", True),
                "api_key_env": info.get("api_key_env"),
                "base_url_env": info.get("base_url_env"),
                "llm_model": llm_model,
                "vlm_model": vlm_model,
                "has_vlm": vlm_model is not None,
            })

        return {
            "success": True,
            "providers": providers,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get providers: {str(e)}",
        }


# ─────────────────────────────────────────────────────────────────────
# Model Settings
# ─────────────────────────────────────────────────────────────────────

def get_model_settings() -> Dict[str, Any]:
    """Get current model settings.

    Returns:
        Dict with current LLM/VLM provider, models, and API key status
    """
    try:
        settings = _load_settings()
        model_settings = settings.get("model", {})
        api_keys_settings = settings.get("api_keys", {})
        endpoints_settings = settings.get("endpoints", {})

        # Get configured providers (settings.json is the single source of truth)
        llm_provider = model_settings.get("llm_provider", "anthropic")
        vlm_provider = model_settings.get("vlm_provider", llm_provider)

        # Get custom models if set
        llm_model = model_settings.get("llm_model")
        vlm_model = model_settings.get("vlm_model")

        # Check API key status for each provider (settings.json only)
        api_keys = {}
        for provider_id, info in PROVIDER_INFO.items():
            settings_key = info.get("settings_key")

            if settings_key:
                # Only check settings.json - no env var fallback
                key = api_keys_settings.get(settings_key, "")

                api_keys[provider_id] = {
                    "has_key": bool(key),
                    "masked_key": _mask_api_key(key) if key else "",
                }
            else:
                # Provider doesn't need API key
                api_keys[provider_id] = {
                    "has_key": True,
                    "masked_key": "(not required)",
                }

        # Get base URLs for providers that support them (settings.json only)
        base_urls = {}
        if endpoints_settings.get("byteplus_base_url"):
            base_urls["byteplus"] = endpoints_settings["byteplus_base_url"]

        if endpoints_settings.get("remote_model_url"):
            base_urls["remote"] = endpoints_settings["remote_model_url"]

        return {
            "success": True,
            "llm_provider": llm_provider,
            "vlm_provider": vlm_provider,
            "llm_model": llm_model,
            "vlm_model": vlm_model,
            "api_keys": api_keys,
            "base_urls": base_urls,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get model settings: {str(e)}",
        }


def update_model_settings(
    llm_provider: Optional[str] = None,
    vlm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    vlm_model: Optional[str] = None,
    api_key: Optional[str] = None,
    provider_for_key: Optional[str] = None,
    base_url: Optional[str] = None,
    provider_for_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Update model settings.

    All settings are saved to settings.json (not .env).

    Args:
        llm_provider: New LLM provider
        vlm_provider: New VLM provider
        llm_model: Custom LLM model name
        vlm_model: Custom VLM model name
        api_key: API key to save (if provider_for_key is set)
        provider_for_key: Provider to save API key for
        base_url: Base URL to save (for byteplus/remote)
        provider_for_url: Provider to save base URL for

    Returns:
        Dict with success status and updated settings
    """
    try:
        settings = _load_settings()
        if "model" not in settings:
            settings["model"] = {}
        if "api_keys" not in settings:
            settings["api_keys"] = {}
        if "endpoints" not in settings:
            settings["endpoints"] = {}

        # Update providers
        # When provider changes, clear the model override so default model is used
        old_llm_provider = settings["model"].get("llm_provider")
        old_vlm_provider = settings["model"].get("vlm_provider")

        if llm_provider:
            settings["model"]["llm_provider"] = llm_provider
            # Clear LLM model if provider changed (unless new model explicitly provided)
            if llm_provider != old_llm_provider and llm_model is None:
                settings["model"]["llm_model"] = None

        if vlm_provider:
            settings["model"]["vlm_provider"] = vlm_provider
            # Clear VLM model if provider changed (unless new model explicitly provided)
            if vlm_provider != old_vlm_provider and vlm_model is None:
                settings["model"]["vlm_model"] = None
        elif llm_provider and llm_provider != old_llm_provider:
            # If only llm_provider changed and vlm_provider not specified,
            # also update vlm_provider to match and clear vlm_model
            settings["model"]["vlm_provider"] = llm_provider
            if vlm_model is None:
                settings["model"]["vlm_model"] = None

        # Update custom models (explicit values override the auto-clear above)
        if llm_model is not None:
            settings["model"]["llm_model"] = llm_model if llm_model else None
        if vlm_model is not None:
            settings["model"]["vlm_model"] = vlm_model if vlm_model else None

        # Update API key in settings.json
        if provider_for_key and api_key is not None:
            info = PROVIDER_INFO.get(provider_for_key, {})
            settings_key = info.get("settings_key")
            if settings_key:
                settings["api_keys"][settings_key] = api_key

        # Update base URL in settings.json
        if provider_for_url and base_url is not None:
            if provider_for_url == "byteplus":
                settings["endpoints"]["byteplus_base_url"] = base_url
            elif provider_for_url == "remote":
                settings["endpoints"]["remote_model_url"] = base_url

        # Save settings.json
        if not _save_settings(settings):
            return {
                "success": False,
                "error": "Failed to save settings.json",
            }

        # Reload settings cache so changes take effect
        from app.config import reload_settings
        reload_settings()

        # Return updated settings
        return get_model_settings()

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to update model settings: {str(e)}",
        }


def test_connection(
    provider: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Test connection to a provider.

    Args:
        provider: Provider to test
        api_key: Optional API key to test with (if not provided, uses stored key)
        base_url: Optional base URL for byteplus/remote providers

    Returns:
        Dict with test results
    """
    try:
        settings = _load_settings()
        api_keys_settings = settings.get("api_keys", {})
        endpoints_settings = settings.get("endpoints", {})

        # If no API key provided, try to get it from settings.json
        if api_key is None:
            info = PROVIDER_INFO.get(provider, {})
            settings_key = info.get("settings_key")

            if settings_key:
                api_key = api_keys_settings.get(settings_key)

        # If no base URL provided, try to get it from settings.json
        if base_url is None and provider in ["byteplus", "remote"]:
            if provider == "byteplus":
                base_url = endpoints_settings.get("byteplus_base_url")
            elif provider == "remote":
                base_url = endpoints_settings.get("remote_model_url")

        # Run connection test
        result = test_provider_connection(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
        )

        return result

    except Exception as e:
        return {
            "success": False,
            "message": "Test failed",
            "provider": provider,
            "error": str(e),
        }


def validate_can_save(
    llm_provider: str,
    vlm_provider: Optional[str] = None,
    api_key: Optional[str] = None,
    provider_for_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate if model settings can be saved.

    Checks that required API keys are present for the selected providers.

    Args:
        llm_provider: The LLM provider being configured
        vlm_provider: The VLM provider (optional, defaults to llm_provider)
        api_key: New API key being set
        provider_for_key: Provider the new key is for

    Returns:
        Dict with validation result and any warnings/errors
    """
    try:
        warnings = []
        errors = []

        vlm_provider = vlm_provider or llm_provider
        settings = _load_settings()
        api_keys_settings = settings.get("api_keys", {})

        # Check each provider needs API key
        providers_to_check = {llm_provider}
        if vlm_provider:
            providers_to_check.add(vlm_provider)

        for provider in providers_to_check:
            info = PROVIDER_INFO.get(provider, {})

            if info.get("requires_api_key", True):
                settings_key = info.get("settings_key")

                # Check if we have an API key (either new one or existing in settings.json)
                has_key = False
                if provider_for_key == provider and api_key:
                    has_key = True
                elif settings_key:
                    existing = api_keys_settings.get(settings_key)
                    has_key = bool(existing)

                if not has_key:
                    errors.append(f"API key required for {info['name']}")

        return {
            "success": len(errors) == 0,
            "can_save": len(errors) == 0,
            "warnings": warnings,
            "errors": errors,
        }

    except Exception as e:
        return {
            "success": False,
            "can_save": False,
            "errors": [str(e)],
        }
