"""Model settings management for UI layer.

Provides functions for managing model configuration including:
- LLM/VLM provider selection
- API key management
- Model selection per provider
- Connection testing

All settings are stored in settings.json (not .env).
"""

import json
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import SETTINGS_CONFIG_PATH
from app.models import (
    MODEL_REGISTRY,
    InterfaceType,
    test_provider_connection,
)


# Provider display names and settings.json key mapping — DERIVED from the
# provider profiles (Phase 1, docs/PROVIDER_LAYER_CATCHUP.md). The JSON shape
# is a frozen frontend contract pinned by
# tests/settings/snapshots/provider_info.json; per-provider data (names, env
# vars, subscription OAuth, is_bedrock, base_url_env visibility rules) lives
# on ProviderProfile in agent_core/core/models/provider_config.py.
from agent_core.core.models.registry import provider_info as _derive_provider_info

PROVIDER_INFO = _derive_provider_info()


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
        from agent_core.core.models.registry import get_registry

        registry = get_registry()
        providers = []

        for provider_id, info in PROVIDER_INFO.items():
            # Get models for this provider
            provider_models = MODEL_REGISTRY.get(provider_id, {})
            profile = registry.get(provider_id)

            llm_model = provider_models.get(InterfaceType.LLM)
            vlm_model = provider_models.get(InterfaceType.VLM)
            image_gen_model = provider_models.get(InterfaceType.IMAGE_GEN)
            video_gen_model = provider_models.get(InterfaceType.VIDEO_GEN)

            providers.append(
                {
                    "id": provider_id,
                    "name": info["name"],
                    "requires_api_key": info.get("requires_api_key", True),
                    "api_key_env": info.get("api_key_env"),
                    "base_url_env": info.get("base_url_env"),
                    # Default endpoint, so the UI can show a helpful
                    # placeholder (e.g. http://localhost:1234/v1 for LM
                    # Studio) instead of a generic "Enter base URL...".
                    "default_base_url": (
                        profile.default_base_url if profile else None
                    ),
                    "llm_model": llm_model,
                    "vlm_model": vlm_model,
                    "has_vlm": vlm_model is not None,
                    "image_gen_model": image_gen_model,
                    "has_image_gen": image_gen_model is not None,
                    "video_gen_model": video_gen_model,
                    "has_video_gen": video_gen_model is not None,
                    "supports_catalog": info.get("supports_catalog", False),
                    "is_bedrock": info.get("is_bedrock", False),
                    "supports_subscription_oauth": info.get(
                        "supports_subscription_oauth", False
                    ),
                    "subscription_label": info.get("subscription_label"),
                    "subscription_models": info.get("subscription_models", []),
                    # ── UX generalization (docs/PROVIDER_SETTINGS_UX_FIX.md) ──
                    # Live GET /v1/models dropdown (all new cloud + local
                    # servers except Perplexity).
                    "has_model_discovery": bool(
                        profile.supports_model_discovery if profile else False
                    ),
                    # "lmstudio" unlocks the native list-all + load UI.
                    "local_kind": profile.local_kind if profile else None,
                    # Drives the OpenRouter geo-fallback hint by flag instead
                    # of a hardcoded ['moonshot','minimax'] list.
                    "openrouter_proxy": bool(
                        profile.openrouter_proxy if profile else False
                    ),
                }
            )

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
        # When no explicit image-gen provider is set, follow the VLM provider if
        # it can generate images (so installs onboarded before image gen was
        # wired to the chosen provider show the right value), else the default.
        image_gen_provider = model_settings.get("image_gen_provider")
        if not image_gen_provider:
            if MODEL_REGISTRY.get(vlm_provider, {}).get(InterfaceType.IMAGE_GEN):
                image_gen_provider = vlm_provider
            else:
                image_gen_provider = "openai"

        # Model overrides, falling back to the provider's registry default so
        # the UI shows the concrete model actually in use rather than a blank
        # field. Hard onboarding only persists the provider (model overrides
        # stay unset = "use the provider default"), which otherwise rendered as
        # an empty Model box in settings.
        llm_model = model_settings.get("llm_model") or MODEL_REGISTRY.get(
            llm_provider, {}
        ).get(InterfaceType.LLM)
        vlm_model = model_settings.get("vlm_model") or MODEL_REGISTRY.get(
            vlm_provider, {}
        ).get(InterfaceType.VLM)
        image_gen_model = model_settings.get("image_gen_model") or MODEL_REGISTRY.get(
            image_gen_provider, {}
        ).get(InterfaceType.IMAGE_GEN)

        video_gen_provider = model_settings.get("video_gen_provider")
        if not video_gen_provider:
            if MODEL_REGISTRY.get(vlm_provider, {}).get(InterfaceType.VIDEO_GEN):
                video_gen_provider = vlm_provider
            else:
                video_gen_provider = "gemini"
        video_gen_model = model_settings.get("video_gen_model") or MODEL_REGISTRY.get(
            video_gen_provider, {}
        ).get(InterfaceType.VIDEO_GEN)

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

        # Subscription OAuth status. Imported lazily so the module load order
        # doesn't pull craftos_integrations until the user actually opens the
        # settings page — keeps cold-start cheap.
        subscription_status: Dict[str, Any] = {}
        try:
            from craftos_integrations.integrations.llm_oauth.tokens import (
                status as _oauth_status,
            )

            for provider_id, info in PROVIDER_INFO.items():
                if not info.get("supports_subscription_oauth"):
                    continue
                subscription_status[provider_id] = _oauth_status(provider_id)
        except Exception:
            # OAuth module missing or broken — leave the map empty so the UI
            # falls back to API-key-only mode rather than 500ing the settings call.
            pass

        # Get base URLs for providers that support them (settings.json only)
        base_urls = {}
        if endpoints_settings.get("byteplus_base_url"):
            base_urls["byteplus"] = endpoints_settings["byteplus_base_url"]

        # Support both the legacy "remote_model_url" key and "remote" key
        remote_url = endpoints_settings.get(
            "remote_model_url"
        ) or endpoints_settings.get("remote")
        if remote_url:
            base_urls["remote"] = remote_url

        if endpoints_settings.get("openrouter_base_url"):
            base_urls["openrouter"] = endpoints_settings["openrouter_base_url"]

        # Bedrock: surface the region through the same base_urls map so the
        # frontend can use the existing field. AWS creds status is reported
        # in a separate `aws_credentials` block below.
        aws_region = endpoints_settings.get("aws_region", "us-east-1")
        base_urls["bedrock"] = aws_region

        aws_settings = settings.get("aws_credentials", {}) or {}
        has_access_key = bool(aws_settings.get("access_key_id"))
        has_secret_key = bool(aws_settings.get("secret_access_key"))
        aws_creds_status = {
            "has_access_key_id": has_access_key,
            "has_secret_access_key": has_secret_key,
            "has_session_token": bool(aws_settings.get("session_token")),
            "masked_access_key_id": _mask_api_key(
                aws_settings.get("access_key_id", "")
            ),
            "region": aws_region,
        }
        # Reflect AWS creds in the api_keys map too so the existing "Configured"
        # badge logic in the frontend lights up for bedrock without special
        # casing. has_key = both keys present (or boto3 chain available).
        api_keys["bedrock"] = {
            "has_key": has_access_key and has_secret_key,
            "masked_key": aws_creds_status["masked_access_key_id"] or "(boto3 chain)",
        }

        return {
            "success": True,
            "llm_provider": llm_provider,
            "vlm_provider": vlm_provider,
            "image_gen_provider": image_gen_provider,
            "video_gen_provider": video_gen_provider,
            "llm_model": llm_model,
            "vlm_model": vlm_model,
            "image_gen_model": image_gen_model,
            "video_gen_model": video_gen_model,
            "api_keys": api_keys,
            "base_urls": base_urls,
            "aws_credentials": aws_creds_status,
            "subscription_oauth": subscription_status,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get model settings: {str(e)}",
        }


def update_model_settings(
    llm_provider: Optional[str] = None,
    vlm_provider: Optional[str] = None,
    image_gen_provider: Optional[str] = None,
    video_gen_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    vlm_model: Optional[str] = None,
    image_gen_model: Optional[str] = None,
    video_gen_model: Optional[str] = None,
    api_key: Optional[str] = None,
    provider_for_key: Optional[str] = None,
    base_url: Optional[str] = None,
    provider_for_url: Optional[str] = None,
    aws_credentials: Optional[Dict[str, str]] = None,
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
        if "aws_credentials" not in settings:
            settings["aws_credentials"] = {}

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

        # Update image generation provider (validate before saving)
        if image_gen_provider:
            supported_img_providers = {
                p
                for p, caps in MODEL_REGISTRY.items()
                if caps.get(InterfaceType.IMAGE_GEN)
            }
            if image_gen_provider not in supported_img_providers:
                return {
                    "success": False,
                    "error": (
                        f"'{image_gen_provider}' does not support image generation. "
                        f"Supported providers: {', '.join(sorted(supported_img_providers))}"
                    ),
                }
            old_img_provider = settings["model"].get("image_gen_provider")
            settings["model"]["image_gen_provider"] = image_gen_provider
            if image_gen_provider != old_img_provider and image_gen_model is None:
                settings["model"]["image_gen_model"] = None

        # Update video generation provider (validate before saving)
        if video_gen_provider:
            supported_vid_providers = {
                p
                for p, caps in MODEL_REGISTRY.items()
                if caps.get(InterfaceType.VIDEO_GEN)
            }
            if video_gen_provider not in supported_vid_providers:
                return {
                    "success": False,
                    "error": (
                        f"'{video_gen_provider}' does not support video generation. "
                        f"Supported providers: {', '.join(sorted(supported_vid_providers))}"
                    ),
                }
            old_vid_provider = settings["model"].get("video_gen_provider")
            settings["model"]["video_gen_provider"] = video_gen_provider
            if video_gen_provider != old_vid_provider and video_gen_model is None:
                settings["model"]["video_gen_model"] = None

        # Update custom models (explicit values override the auto-clear above)
        if llm_model is not None:
            settings["model"]["llm_model"] = llm_model if llm_model else None
        if vlm_model is not None:
            settings["model"]["vlm_model"] = vlm_model if vlm_model else None
        if image_gen_model is not None:
            settings["model"]["image_gen_model"] = (
                image_gen_model if image_gen_model else None
            )
        if video_gen_model is not None:
            settings["model"]["video_gen_model"] = (
                video_gen_model if video_gen_model else None
            )

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
            elif provider_for_url == "openrouter":
                settings["endpoints"]["openrouter_base_url"] = base_url
            elif provider_for_url == "bedrock":
                # Bedrock's "base URL" slot carries the AWS region.
                settings["endpoints"]["aws_region"] = base_url

        # Update AWS credentials block (bedrock-only)
        if aws_credentials:
            for field in ("access_key_id", "secret_access_key", "session_token"):
                value = aws_credentials.get(field)
                if value is not None:
                    settings["aws_credentials"][field] = value
            region = aws_credentials.get("region")
            if region:
                settings["endpoints"]["aws_region"] = region

        # Clear remote URL when switching away from remote so stale values don't persist
        if (
            llm_provider
            and llm_provider != "remote"
            and old_llm_provider == "remote"
            and not provider_for_url
        ):
            settings["endpoints"]["remote_model_url"] = ""

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
    model: Optional[str] = None,
    aws_credentials: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Test connection to a provider.

    Args:
        provider: Provider to test
        api_key: Optional API key to test with (if not provided, uses stored key)
        base_url: Optional base URL for byteplus/remote providers
        model: Optional model id to verify. When provided the tester does a
            tiny chat completion against this exact model so a typo in the
            model id is caught at test time, not at first real call. When
            omitted, falls back to a known-good test model (auth check only).

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
        if base_url is None and provider in [
            "byteplus",
            "remote",
            "openrouter",
            "bedrock",
        ]:
            if provider == "byteplus":
                base_url = endpoints_settings.get("byteplus_base_url")
            elif provider == "remote":
                base_url = endpoints_settings.get("remote_model_url")
            elif provider == "openrouter":
                base_url = endpoints_settings.get("openrouter_base_url")
            elif provider == "bedrock":
                # `base_url` carries the AWS region through the existing
                # plumbing — the connection tester reads boto3 creds from
                # settings.json directly via app.config.get_aws_credentials.
                base_url = endpoints_settings.get("aws_region", "us-east-1")

        # Run connection test
        result = test_provider_connection(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            aws_credentials=aws_credentials,
        )

        return result

    except Exception as e:
        return {
            "success": False,
            "message": "Test failed",
            "provider": provider,
            "error": str(e),
        }


def _sort_models_by_recency(items: List[Tuple[str, Any]]) -> List[str]:
    """Order model ids newest-first, falling back to alphabetical.

    ``items`` is a list of ``(model_id, recency)`` pairs, where ``recency`` is
    a comparable value the provider reports for how new a model is — a unix
    timestamp for /v1/models' ``created``, an ISO-8601 string for Ollama's
    ``modified_at`` — or ``None`` when the provider doesn't report it (all
    recency values in one call are the same type).

    Ids that carry a recency sort newest-first; ids without one sort after
    them, case-insensitively A→Z. When no id reports a recency at all, the
    whole list is alphabetical.
    """
    if not any(r is not None for _, r in items):
        return sorted((mid for mid, _ in items), key=str.lower)
    dated = [(mid, r) for mid, r in items if r is not None]
    undated = sorted((mid for mid, r in items if r is None), key=str.lower)
    dated.sort(key=lambda t: t[0].lower())         # A→Z tiebreak (stable)
    dated.sort(key=lambda t: t[1], reverse=True)   # then newest first
    return [mid for mid, _ in dated] + undated


def get_ollama_models(base_url: Optional[str] = None) -> Dict[str, Any]:
    """Fetch available models from a running Ollama instance.

    Args:
        base_url: Optional Ollama base URL. Defaults to http://localhost:11434.

    Returns:
        Dict with success, models (list of name strings), and optional error.
    """
    url = base_url or "http://localhost:11434"
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{url.rstrip('/')}/api/tags")
        if response.status_code == 200:
            raw = response.json().get("models", [])
            models = _sort_models_by_recency(
                [
                    (m["name"], m.get("modified_at") or None)
                    for m in raw
                    if isinstance(m, dict) and m.get("name")
                ]
            )
            return {"success": True, "models": models}
        else:
            return {
                "success": False,
                "models": [],
                "error": f"Ollama returned status {response.status_code}",
            }
    except Exception as e:
        return {"success": False, "models": [], "error": str(e)}


def get_provider_models(
    provider: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """List a provider's models via the OpenAI-standard GET {base_url}/models.

    The wire-generic analogue of get_ollama_models (which uses Ollama's
    native /api/tags): powers the settings model dropdown for every provider
    with supports_model_discovery — the 9 new cloud providers and the local
    servers (LM Studio / vLLM / llama.cpp). See
    docs/PROVIDER_SETTINGS_UX_FIX.md A2.

    Returns {success, models: [id,...], error?}. Never raises.
    """
    from agent_core.core.models.registry import get_registry

    profile = get_registry().get(provider)
    if profile is None:
        return {"success": False, "models": [], "error": f"Unknown provider: {provider}"}

    url = base_url or profile.default_base_url
    if not url:
        return {"success": False, "models": [], "error": "No base URL configured."}

    # Resolve a bearer: explicit key, else the stored key, else a placeholder
    # for keyless local servers (which ignore auth).
    key = api_key
    if not key:
        try:
            from app.config import get_api_key

            key = get_api_key(provider) or None
        except Exception:
            key = None
    if not key and not profile.requires_api_key:
        key = "local"

    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.get(f"{url.rstrip('/')}/models", headers=headers)
        if response.status_code == 200:
            data = response.json().get("data", []) or []

            def _created(m: Dict[str, Any]) -> Optional[int]:
                c = m.get("created")
                # Several OpenAI-compatible providers stub `created` as 0/absent
                # — treat those as "no recency" so they fall back to alpha.
                return int(c) if isinstance(c, (int, float)) and c > 0 else None

            models = _sort_models_by_recency(
                [
                    (m["id"], _created(m))
                    for m in data
                    if isinstance(m, dict) and m.get("id")
                ]
            )
            return {"success": True, "models": models}
        return {
            "success": False,
            "models": [],
            "error": f"Provider returned status {response.status_code}",
        }
    except Exception as e:
        return {"success": False, "models": [], "error": str(e)}


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

        # A connected subscription OAuth fulfills the credential requirement —
        # the factory will use the OAuth bearer instead of an API key.
        # Imported lazily so a broken integrations package doesn't 500 the
        # whole settings page; just falls back to api-key-only validation.
        connected_subscriptions: set[str] = set()
        try:
            from craftos_integrations.integrations.llm_oauth.tokens import (
                has_credential,
            )

            for prov in providers_to_check:
                info = PROVIDER_INFO.get(prov, {})
                if info.get("supports_subscription_oauth") and has_credential(prov):
                    connected_subscriptions.add(prov)
        except Exception:
            pass

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

                if not has_key and provider not in connected_subscriptions:
                    errors.append(
                        f"API key or subscription connection required for {info['name']}"
                    )

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


# ─────────────────────────────────────────────────────────────────────
# Slow Mode Settings
# ─────────────────────────────────────────────────────────────────────


def get_slow_mode_settings() -> Dict[str, Any]:
    """Get slow mode settings."""
    settings = _load_settings()
    model = settings.get("model", {})
    return {
        "success": True,
        "enabled": model.get("slow_mode", False),
        "tpm_limit": model.get("slow_mode_tpm_limit", 30000),
    }


def set_slow_mode(enabled: bool, tpm_limit: Optional[int] = None) -> Dict[str, Any]:
    """Set slow mode on or off, optionally updating the TPM limit."""
    settings = _load_settings()
    if "model" not in settings:
        settings["model"] = {}
    settings["model"]["slow_mode"] = enabled
    if tpm_limit is not None:
        settings["model"]["slow_mode_tpm_limit"] = max(1000, tpm_limit)

    if _save_settings(settings):
        from app.config import reload_settings

        reload_settings()
        # Reset the rate limiter window on setting change
        from app.rate_limiter import get_rate_limiter

        get_rate_limiter().reset()
        return {
            "success": True,
            "enabled": enabled,
            "tpm_limit": settings["model"].get("slow_mode_tpm_limit", 30000),
        }
    return {"success": False, "error": "Failed to save settings"}
