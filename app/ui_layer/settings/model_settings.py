"""Model settings management for UI layer.

Provides functions for managing model configuration including:
- LLM/VLM provider selection
- API key management
- Model selection per provider
- Connection testing
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


# Provider display names
PROVIDER_INFO = {
    "openai": {
        "name": "OpenAI",
        "api_key_env": "OPENAI_API_KEY",
        "requires_api_key": True,
    },
    "anthropic": {
        "name": "Anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "requires_api_key": True,
    },
    "gemini": {
        "name": "Google Gemini",
        "api_key_env": "GOOGLE_API_KEY",
        "requires_api_key": True,
    },
    "byteplus": {
        "name": "BytePlus",
        "api_key_env": "BYTEPLUS_API_KEY",
        "base_url_env": "BYTEPLUS_BASE_URL",
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
            }
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
            }
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


def _get_env_path() -> Path:
    """Get the path to .env file."""
    return Path(".env")


def _read_env_file() -> Dict[str, str]:
    """Read environment variables from .env file."""
    env_path = _get_env_path()
    env_vars = {}

    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        env_vars[key.strip()] = value.strip()
        except Exception:
            pass

    return env_vars


def _write_env_file(env_vars: Dict[str, str]) -> bool:
    """Write environment variables to .env file."""
    env_path = _get_env_path()

    try:
        # Read existing content to preserve comments and order
        existing_lines = []
        updated_keys = set()

        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        key = stripped.split("=", 1)[0].strip()
                        if key in env_vars:
                            # Update this line with new value
                            if env_vars[key]:  # Only write non-empty values
                                existing_lines.append(f"{key}={env_vars[key]}\n")
                            updated_keys.add(key)
                        else:
                            existing_lines.append(line if line.endswith("\n") else line + "\n")
                    else:
                        existing_lines.append(line if line.endswith("\n") else line + "\n")

        # Add new keys that weren't in the file
        for key, value in env_vars.items():
            if key not in updated_keys and value:
                existing_lines.append(f"{key}={value}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(existing_lines)

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
        env_vars = _read_env_file()

        # Get configured providers
        llm_provider = model_settings.get("llm_provider") or env_vars.get("LLM_PROVIDER", "anthropic")
        vlm_provider = model_settings.get("vlm_provider") or env_vars.get("VLM_PROVIDER", llm_provider)

        # Get custom models if set
        llm_model = model_settings.get("llm_model")
        vlm_model = model_settings.get("vlm_model")

        # Check API key status for each provider
        api_keys = {}
        for provider_id, info in PROVIDER_INFO.items():
            api_key_env = info.get("api_key_env")
            if api_key_env:
                # Check env file first, then os.environ
                key = env_vars.get(api_key_env) or os.getenv(api_key_env, "")
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

        # Get base URLs for providers that support them
        base_urls = {}
        if "BYTEPLUS_BASE_URL" in env_vars:
            base_urls["byteplus"] = env_vars["BYTEPLUS_BASE_URL"]
        if "REMOTE_MODEL_URL" in env_vars:
            base_urls["remote"] = env_vars["REMOTE_MODEL_URL"]

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

        env_updates = {}

        # Update providers
        if llm_provider:
            settings["model"]["llm_provider"] = llm_provider
            env_updates["LLM_PROVIDER"] = llm_provider

        if vlm_provider:
            settings["model"]["vlm_provider"] = vlm_provider
            env_updates["VLM_PROVIDER"] = vlm_provider

        # Update custom models
        if llm_model is not None:
            settings["model"]["llm_model"] = llm_model if llm_model else None
        if vlm_model is not None:
            settings["model"]["vlm_model"] = vlm_model if vlm_model else None

        # Update API key
        if provider_for_key and api_key is not None:
            info = PROVIDER_INFO.get(provider_for_key, {})
            api_key_env = info.get("api_key_env")
            if api_key_env:
                env_updates[api_key_env] = api_key

        # Update base URL
        if provider_for_url and base_url is not None:
            info = PROVIDER_INFO.get(provider_for_url, {})
            base_url_env = info.get("base_url_env")
            if base_url_env:
                env_updates[base_url_env] = base_url

        # Save settings.json
        if not _save_settings(settings):
            return {
                "success": False,
                "error": "Failed to save settings.json",
            }

        # Save .env updates
        if env_updates:
            if not _write_env_file(env_updates):
                return {
                    "success": False,
                    "error": "Failed to save .env file",
                }

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
        # If no API key provided, try to get it from environment
        if api_key is None:
            info = PROVIDER_INFO.get(provider, {})
            api_key_env = info.get("api_key_env")
            if api_key_env:
                env_vars = _read_env_file()
                api_key = env_vars.get(api_key_env) or os.getenv(api_key_env)

        # If no base URL provided, try to get it from environment
        if base_url is None and provider in ["byteplus", "remote"]:
            info = PROVIDER_INFO.get(provider, {})
            base_url_env = info.get("base_url_env")
            if base_url_env:
                env_vars = _read_env_file()
                base_url = env_vars.get(base_url_env) or os.getenv(base_url_env)

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
        env_vars = _read_env_file()

        # Check each provider needs API key
        providers_to_check = {llm_provider}
        if vlm_provider:
            providers_to_check.add(vlm_provider)

        for provider in providers_to_check:
            info = PROVIDER_INFO.get(provider, {})

            if info.get("requires_api_key", True):
                api_key_env = info.get("api_key_env")

                # Check if we have an API key (either new one or existing)
                has_key = False
                if provider_for_key == provider and api_key:
                    has_key = True
                elif api_key_env:
                    existing = env_vars.get(api_key_env) or os.getenv(api_key_env)
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
