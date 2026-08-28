# -*- coding: utf-8 -*-
"""Registry derivations over ProviderProfile (Phase 1, FR-1).

Every structure that used to be a hand-maintained literal is derived here
from PROVIDER_CONFIG, so a provider added to provider_config.py appears
everywhere (settings UI, CLI, connection tester, factory) with zero extra
code. Derived outputs are shape-identical to the old literals; the contract
tests in tests/settings/test_self_config_contract.py pin this.

Phase 3 extends ``get_registry`` with user-defined custom providers loaded
from settings.json (custom_providers block).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from agent_core.core.models.provider_config import (
    PROVIDER_CONFIG,
    ProviderProfile,
    get_profile,
)

__all__ = [
    "PROVIDER_CONFIG",
    "ProviderProfile",
    "get_profile",
    "get_registry",
    "provider_info",
    "provider_settings_keys",
    "cli_providers",
    "display_name",
    "error_display_map",
    "default_models_registry",
]


# Custom providers are restricted to the OpenAI-compatible wire for now:
# the factory's other wires bind provider-specific clients (Anthropic SDK
# without base_url override, boto3, Gemini) that a user endpoint can't use.
_ALLOWED_CUSTOM_WIRES = ("chat_completions",)


def _load_custom_specs() -> Dict[str, Any]:
    """settings.json custom_providers block, via the app layer when present.

    agent_core stays importable without the app package (same deferred-import
    pattern the factory uses for app.config); no app -> no custom providers.
    """
    try:
        from app.config import get_custom_providers

        specs = get_custom_providers()
        return specs if isinstance(specs, dict) else {}
    except Exception:
        return {}


def _build_custom_profile(name: str, spec: Any) -> Optional[ProviderProfile]:
    """Validate one custom_providers entry into a ProviderProfile.

    Invalid entries are skipped with a warning — a misconfigured custom
    provider must never brick startup (the agent edits this block itself).
    """
    import logging
    from urllib.parse import urlparse

    log = logging.getLogger(__name__)

    if not isinstance(spec, dict):
        log.warning(f"[REGISTRY] custom provider {name!r}: spec must be an object")
        return None
    if name in PROVIDER_CONFIG:
        log.warning(
            f"[REGISTRY] custom provider {name!r} collides with a built-in; ignored"
        )
        return None
    base_url = spec.get("base_url")
    parsed = urlparse(base_url) if isinstance(base_url, str) else None
    if parsed is None or parsed.scheme not in ("http", "https") or not parsed.netloc:
        log.warning(
            f"[REGISTRY] custom provider {name!r}: base_url must be an http(s) URL"
        )
        return None
    wire = spec.get("wire", "chat_completions")
    if wire not in _ALLOWED_CUSTOM_WIRES:
        log.warning(
            f"[REGISTRY] custom provider {name!r}: wire {wire!r} not supported "
            f"(allowed: {', '.join(_ALLOWED_CUSTOM_WIRES)})"
        )
        return None

    models = spec.get("models") or []
    default_model = spec.get("default_model") or (models[0] if models else None)

    from agent_core.core.models.types import InterfaceType

    return ProviderProfile(
        key=name,
        display_name=str(spec.get("display_name") or name),
        wire=wire,
        api_key_env=spec.get("api_key_env"),
        default_base_url=base_url,
        settings_key=name,
        requires_api_key=bool(spec.get("requires_api_key", True)),
        supports_prompt_cache_key=bool(
            spec.get("supports_prompt_cache_key", False)
        ),
        # New chat_completions providers get session accumulation — it is
        # the correct behavior; only legacy minimax/moonshot opt out.
        session_accumulation=True,
        default_headers=dict(spec.get("headers") or {}),
        connection_test_model=spec.get("connection_test_model") or default_model,
        default_models={
            InterfaceType.LLM: default_model,
            InterfaceType.VLM: spec.get("vlm_model"),
            InterfaceType.EMBEDDING: None,
            InterfaceType.IMAGE_GEN: None,
            InterfaceType.VIDEO_GEN: None,
        },
    )


def get_registry() -> Dict[str, ProviderProfile]:
    """Built-in profiles merged with settings.json custom providers.

    Called per lookup (factory create, connection test, session-list
    derivations) so a reload_settings() after editing custom_providers takes
    effect without restart. The import-time constants (PROVIDER_INFO,
    MODEL_REGISTRY, PROVIDER_TO_SETTINGS_KEY) cover built-ins only.
    """
    registry = dict(PROVIDER_CONFIG)
    for name, spec in _load_custom_specs().items():
        profile = _build_custom_profile(name, spec)
        if profile is not None:
            registry[name] = profile
    return registry


def provider_info() -> Dict[str, Dict[str, Any]]:
    """Derive the PROVIDER_INFO dict consumed by the settings frontend.

    Key-presence rules mirror the retired literal exactly (NFR-4):
    - api_key_env / settings_key only when set;
    - base_url_env only for providers WITHOUT an API key (remote, bedrock);
      byteplus/openrouter have overridable base URLs but never exposed them
      here (OpenRouter's is hidden intentionally — power users set
      endpoints.openrouter_base_url in settings.json by hand);
    - subscription fields only for OAuth-capable providers;
    - supports_catalog / is_bedrock only when true.
    """
    info: Dict[str, Dict[str, Any]] = {}
    for key, p in get_registry().items():
        entry: Dict[str, Any] = {"name": p.display_name}
        if p.api_key_env:
            entry["api_key_env"] = p.api_key_env
        if p.settings_key:
            entry["settings_key"] = p.settings_key
        entry["requires_api_key"] = p.requires_api_key
        if p.oauth_backend:
            entry["supports_subscription_oauth"] = True
            entry["subscription_label"] = p.subscription_label
            entry["subscription_models"] = list(p.subscription_models)
            if p.subscription_default_model:
                entry["subscription_default_model"] = p.subscription_default_model
        if p.supports_catalog_picker:
            entry["supports_catalog"] = True
        if p.aws_credential_block:
            entry["is_bedrock"] = True
        if p.base_url_env and not p.api_key_env:
            entry["base_url_env"] = p.base_url_env
        info[key] = entry
    return info


def provider_settings_keys() -> Dict[str, str]:
    """Derive PROVIDER_TO_SETTINGS_KEY (settings.json api_keys mapping).

    Includes the legacy "google" alias: callers historically passed either
    the provider key ("gemini") or the settings key ("google"); both resolve
    to api_keys.google. Bedrock is deliberately absent (no single API key —
    credentials live under aws_credentials), so ``.get("bedrock")`` returns
    None and the save path routes accordingly.
    """
    mapping = {
        key: p.settings_key
        for key, p in get_registry().items()
        if p.settings_key
    }
    mapping["google"] = "google"
    return mapping


def cli_providers() -> Dict[str, Tuple[Optional[str], str]]:
    """Derive the /provider command's provider table.

    Shape: {provider: (api_key_env or None, display_name)}. Unlike the
    retired literal this covers EVERY registry provider (the old dict was
    missing minimax/moonshot/bedrock — a hand-sync failure this derivation
    makes impossible).
    """
    return {
        key: (p.api_key_env, p.display_name)
        for key, p in get_registry().items()
    }


def display_name(provider: str) -> str:
    """Settings-UI display name, falling back to the raw key."""
    p = get_registry().get(provider)
    return p.display_name if p else provider


def error_display_map() -> Dict[str, str]:
    """Derive the factory's short error-message display map.

    Only providers with an explicit error_display_name appear; callers keep
    the historical ``.get(provider, provider)`` fallback so the output is
    byte-identical to the retired factory._PROVIDER_DISPLAY literal.
    """
    return {
        key: p.error_display_name
        for key, p in get_registry().items()
        if p.error_display_name
    }


def default_models_registry() -> Dict[str, Dict[Any, Optional[str]]]:
    """Derive MODEL_REGISTRY ({provider: {InterfaceType: default model}})."""
    return {key: dict(p.default_models) for key, p in get_registry().items()}


def session_cc_providers() -> frozenset:
    """chat_completions providers whose session path accumulates history
    (the _openai_compat_session_messages / openrouter-anthropic buffers).

    Replaces the hand-maintained tuple in interface.py's session dispatcher
    and create_session_cache. minimax/moonshot stay excluded
    (session_accumulation=False) to preserve their historical stateless
    session behavior.
    """
    return frozenset(
        key
        for key, p in get_registry().items()
        if p.wire == "chat_completions" and p.session_accumulation
    )


def supports_prompt_cache_key(provider: str) -> bool:
    """Whether the chat_completions transport may emit ``prompt_cache_key``
    for this provider. Opt-in per profile: some OpenAI-compatible endpoints
    reject unknown top-level fields rather than ignoring them."""
    p = get_registry().get(provider)
    return bool(p and p.supports_prompt_cache_key)
