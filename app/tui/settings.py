"""Settings utilities for the TUI interface."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.logger import logger
from app.models.provider_config import PROVIDER_CONFIG


def save_settings_to_env(provider: str, api_key: str) -> bool:
    """Save provider and API key to .env file.

    Args:
        provider: The LLM provider name
        api_key: The API key for the provider

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        env_path = Path(".env")
        env_lines: list[str] = []

        # Read existing .env file if it exists
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                env_lines = f.readlines()

        # Get the API key environment variable name for this provider
        key_lookup = {
            "openai": "OPENAI_API_KEY",
            "gemini": "GOOGLE_API_KEY",
            "byteplus": "BYTEPLUS_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        api_key_env = key_lookup.get(provider)

        # Update or add the LLM_PROVIDER and API key
        updated_provider = False
        updated_api_key = False

        new_lines = []
        for line in env_lines:
            stripped = line.strip()
            if stripped.startswith("LLM_PROVIDER="):
                new_lines.append(f"LLM_PROVIDER={provider}\n")
                updated_provider = True
            elif api_key_env and stripped.startswith(f"{api_key_env}="):
                if api_key:
                    new_lines.append(f"{api_key_env}={api_key}\n")
                    updated_api_key = True
                # Skip empty API key lines (don't write them)
            else:
                new_lines.append(line if line.endswith("\n") else line + "\n")

        # Add new entries if not updated
        if not updated_provider:
            new_lines.append(f"LLM_PROVIDER={provider}\n")

        if api_key_env and api_key and not updated_api_key:
            new_lines.append(f"{api_key_env}={api_key}\n")

        # Write back to .env file
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        logger.info(f"[SETTINGS] Saved provider={provider} to .env file")
        return True

    except Exception as e:
        logger.error(f"[SETTINGS] Failed to save to .env file: {e}")
        return False


def get_api_key_env_name(provider: str) -> Optional[str]:
    """Get the environment variable name for a provider's API key."""
    if provider not in PROVIDER_CONFIG:
        return None
    return PROVIDER_CONFIG[provider].api_key_env
