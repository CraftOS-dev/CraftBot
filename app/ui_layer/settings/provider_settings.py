"""Provider/API-key/remote-endpoint settings utilities."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional, Tuple

from app.logger import logger
from app.models.provider_config import PROVIDER_CONFIG
from app.config import SETTINGS_CONFIG_PATH


# Provider to settings.json api_keys key mapping — DERIVED from the provider
# profiles (Phase 1, docs/PROVIDER_LAYER_CATCHUP.md). Bedrock has no single
# API key (credentials live under "aws_credentials"), so it is absent and
# ``.get("bedrock")`` returns None, which the save path detects and routes
# accordingly. The legacy "google" alias entry is preserved.
from agent_core.core.models.registry import (
    provider_settings_keys as _derive_settings_keys,
)

PROVIDER_TO_SETTINGS_KEY = _derive_settings_keys()


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

        # Check if provider changed - if so, clear model overrides
        old_provider = settings["model"].get("llm_provider")
        if provider != old_provider:
            # Clear model overrides so default model for new provider is used
            settings["model"]["llm_model"] = None
            settings["model"]["vlm_model"] = None

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

        # Reload settings cache so changes take effect
        from app.config import reload_settings

        reload_settings()

        logger.info(f"[SETTINGS] Saved provider={provider} to settings.json")
        return True

    except Exception as e:
        logger.error(f"[SETTINGS] Failed to save to settings.json: {e}")
        return False


# Keep old function name as alias for backwards compatibility
save_settings_to_env = save_settings_to_json


def save_remote_endpoint(url: str) -> bool:
    """Save the Ollama (remote) base URL to settings.json.

    Args:
        url: The base URL for the Ollama server (e.g. http://localhost:11434)

    Returns:
        True if saved successfully, False otherwise
    """
    try:
        settings = _load_settings()

        if "model" not in settings:
            settings["model"] = {}
        settings["model"]["llm_provider"] = "remote"
        settings["model"]["vlm_provider"] = "remote"

        if "endpoints" not in settings:
            settings["endpoints"] = {}
        settings["endpoints"]["remote_model_url"] = url

        if not _save_settings(settings):
            return False

        from app.config import reload_settings

        reload_settings()

        logger.info(f"[SETTINGS] Saved remote endpoint={url} to settings.json")
        return True

    except Exception as e:
        logger.error(f"[SETTINGS] Failed to save remote endpoint: {e}")
        return False


def save_custom_provider(name: str, spec: Dict[str, Any]) -> Tuple[bool, str]:
    """Create or update a user-defined provider (Phase 3, FR-5).

    ``spec`` follows docs/PROVIDER_LAYER_CATCHUP.md section 7.2:
    base_url (required), wire, api_key or api_key_env, display_name,
    models, default_model, headers, supports_prompt_cache_key,
    requires_api_key. An inline "api_key" is routed into the regular
    api_keys block under ``name`` (never stored in custom_providers), so
    the whole existing key plumbing works unchanged.

    The entry is validated through the registry builder before saving —
    the agent can call this and get an actionable error instead of
    persisting a broken provider.
    """
    from agent_core.core.models.provider_config import PROVIDER_CONFIG
    from agent_core.core.models.registry import _build_custom_profile

    name = (name or "").strip().lower()
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        return False, "Provider name must be a slug (letters/digits/-/_)."
    if name in PROVIDER_CONFIG:
        return False, f"'{name}' collides with a built-in provider."
    if not isinstance(spec, dict):
        return False, "Provider spec must be an object."

    spec = dict(spec)
    inline_key = spec.pop("api_key", None)

    if _build_custom_profile(name, spec) is None:
        return False, (
            "Invalid provider spec: base_url must be an http(s) URL and "
            "wire (if set) must be 'chat_completions'."
        )

    try:
        settings = _load_settings()
        settings.setdefault("custom_providers", {})[name] = spec
        if inline_key:
            settings.setdefault("api_keys", {})[name] = inline_key
        if not _save_settings(settings):
            return False, "Failed to write settings.json."
        from app.config import reload_settings

        reload_settings()
        logger.info(f"[SETTINGS] Saved custom provider {name!r}")
        return True, f"Custom provider '{name}' saved."
    except Exception as e:
        logger.error(f"[SETTINGS] Failed to save custom provider {name!r}: {e}")
        return False, f"Failed to save custom provider: {e}"


def delete_custom_provider(name: str) -> Tuple[bool, str]:
    """Remove a custom provider and its stored API key."""
    try:
        settings = _load_settings()
        removed = settings.get("custom_providers", {}).pop(name, None)
        settings.get("api_keys", {}).pop(name, None)
        if removed is None:
            return False, f"No custom provider named '{name}'."
        if not _save_settings(settings):
            return False, "Failed to write settings.json."
        from app.config import reload_settings

        reload_settings()
        logger.info(f"[SETTINGS] Deleted custom provider {name!r}")
        return True, f"Custom provider '{name}' deleted."
    except Exception as e:
        logger.error(f"[SETTINGS] Failed to delete custom provider {name!r}: {e}")
        return False, f"Failed to delete custom provider: {e}"


def get_api_key_env_name(provider: str) -> Optional[str]:
    """Get the environment variable name for a provider's API key."""
    if provider not in PROVIDER_CONFIG:
        return None
    return PROVIDER_CONFIG[provider].api_key_env


def get_current_provider() -> str:
    """Get the current LLM provider from settings.json."""
    settings = _load_settings()
    return settings.get("model", {}).get("llm_provider", "anthropic")


def get_api_key_for_provider(provider: str) -> str:
    """Get the API key for a provider from settings.json."""
    settings = _load_settings()
    settings_key = PROVIDER_TO_SETTINGS_KEY.get(provider, provider)
    return settings.get("api_keys", {}).get(settings_key, "")


# ─────────────────────────────────────────────────────────────────────
# Subscription OAuth (ChatGPT Plus/Pro/Team, SuperGrok). UI sits in the
# model-settings panel next to the API-key field. Anthropic is intentionally
# excluded — Pro/Max OAuth in third-party tools was forbidden by Anthropic
# in Feb 2026, so we keep that path API-key-only.
# ─────────────────────────────────────────────────────────────────────


def _persist_auth_mode(provider: str, mode: str) -> None:
    """Write the UI-hint ``auth_mode`` for ``provider`` to settings.json.

    The factory checks OAuth credential presence directly, so this value
    is informational only — used by the settings UI to pick which toggle
    to highlight. A save failure does not break inference.
    """
    try:
        settings = _load_settings()
        settings.setdefault("auth_mode", {})[provider] = mode
        _save_settings(settings)
        from app.config import reload_settings

        reload_settings()
    except Exception as e:
        logger.warning(f"[SETTINGS] failed to persist auth_mode for {provider}: {e}")


async def connect_subscription_async(provider: str) -> Tuple[bool, str]:
    """Launch the subscription OAuth flow for ``provider`` (openai / grok).

    Opens the browser, waits for the loopback callback, persists the
    credential under ``.credentials/<provider>_oauth.json``. Async because
    the OAuth flow awaits a loopback HTTP callback — wrapping it in a fresh
    event loop from inside the browser adapter's running loop would
    deadlock; the sync wrapper below is only for CLI / script callers.

    This function is scoped to just the OAuth handshake + credential
    persistence. The caller (browser adapter) is responsible for flipping
    the active LLM provider and reinitializing the live LLM interface via
    ``update_model_settings`` + ``agent.reinitialize_llm`` — same path
    that the manual Save flow uses.
    """
    try:
        from craftos_integrations.integrations.llm_oauth import tokens as _oauth_tokens
    except Exception as e:
        return False, f"Subscription OAuth backend unavailable: {e}"
    try:
        success, message = await _oauth_tokens.connect(provider)
    except Exception as e:
        logger.error(f"[SETTINGS] subscription connect for {provider} crashed: {e}")
        return False, f"Connect failed: {e}"
    if success:
        _persist_auth_mode(provider, "subscription")
    return success, message


def disconnect_subscription(provider: str) -> Tuple[bool, str]:
    """Remove the subscription credential and flip auth_mode back to api_key.

    Synchronous — disconnect is just a file delete, no OAuth dance required.
    """
    try:
        from craftos_integrations.integrations.llm_oauth import tokens as _oauth_tokens
    except Exception as e:
        return False, f"Subscription OAuth backend unavailable: {e}"
    success, message = _oauth_tokens.disconnect(provider)
    _persist_auth_mode(provider, "api_key")
    return success, message


def connect_subscription(provider: str) -> Tuple[bool, str]:
    """Sync wrapper around ``connect_subscription_async`` — for CLI/script
    callers that aren't running inside an event loop. **Do not call from an
    async context.** Async callers should await ``connect_subscription_async``
    directly to avoid the "loop already running" RuntimeError.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(connect_subscription_async(provider))
    finally:
        loop.close()


def get_subscription_status(provider: str) -> Dict[str, Any]:
    """UI-facing status: connected? which account? plan? expiry?"""
    try:
        from craftos_integrations.integrations.llm_oauth.tokens import status
    except Exception:
        return {"supported": False, "connected": False}
    return status(provider)


async def prepare_subscription_async(provider: str) -> Tuple[bool, Dict[str, Any]]:
    """Paste-back flow: open browser, return auth URL + attempt_id.

    Used when the provider shows a "copy this code" page instead of
    redirecting to our loopback callback (happens with xAI's
    hermes-agent client family in some browser contexts).
    """
    try:
        from craftos_integrations.integrations.llm_oauth import tokens as _oauth_tokens
    except Exception as e:
        return False, {"error": f"Subscription OAuth backend unavailable: {e}"}
    return await _oauth_tokens.prepare_connect(provider)


def complete_subscription(
    provider: str, code: str, attempt_id: Optional[str] = None
) -> Tuple[bool, str]:
    """Finalize a paste-back attempt by exchanging the pasted code for tokens."""
    try:
        from craftos_integrations.integrations.llm_oauth import tokens as _oauth_tokens
    except Exception as e:
        return False, f"Subscription OAuth backend unavailable: {e}"
    success, message = _oauth_tokens.complete_connect(provider, code, attempt_id)
    if success:
        _persist_auth_mode(provider, "subscription")
    return success, message
