# -*- coding: utf-8 -*-
"""Model factory for creating provider-specific model contexts.

API keys and base URLs should be passed directly - no environment variable reading.
"""

import logging
import urllib.request
import json as _json

from openai import OpenAI
from anthropic import Anthropic
from typing import Optional

try:
    import boto3  # type: ignore[import]
except ImportError:  # pragma: no cover — boto3 is an optional extra
    boto3 = None  # type: ignore[assignment]

from agent_core.core.models.types import InterfaceType
from agent_core.core.models.model_registry import MODEL_REGISTRY
from agent_core.core.models.provider_config import PROVIDER_CONFIG
from agent_core.core.llm.google_gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# Providers that should route through OpenRouter when OR is configured,
# because their direct APIs are geo-restricted for most international users.
_OPENROUTER_PROXIED = {"moonshot", "minimax"}

# OpenRouter namespace per provider (for auto-slugging unknown model IDs).
_OR_NAMESPACE = {
    "moonshot": "moonshotai",
    "minimax": "minimax",
}

# Explicit model-ID → OpenRouter slug overrides.
_OR_MODEL_MAP: dict = {
    "moonshot": {
        "kimi-k2.5": "moonshotai/kimi-k2.5",
        "moonshot-v1-8k": "moonshotai/moonshot-v1-8k",
        "moonshot-v1-32k": "moonshotai/moonshot-v1-32k",
        "moonshot-v1-128k": "moonshotai/moonshot-v1-128k",
        "moonshot-v1-8k-vision-preview": "moonshotai/moonshot-v1-8k-vision-preview",
    },
    "minimax": {
        "MiniMax-Text-01": "minimax/minimax-01",
        "MiniMax-VL-01": "minimax/minimax-01",
        "abab6.5s-chat": "minimax/abab6.5s-chat",
    },
}

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _to_openrouter_slug(provider: str, model: str) -> str:
    """Convert a provider-native model ID to its OpenRouter slug."""
    if "/" in model:
        return model
    explicit = _OR_MODEL_MAP.get(provider, {}).get(model)
    if explicit:
        return explicit
    namespace = _OR_NAMESPACE.get(provider, provider)
    return f"{namespace}/{model}"


def _get_openrouter_key() -> Optional[str]:
    """Return the stored OpenRouter API key, or None if not configured."""
    try:
        from app.config import get_api_key

        return get_api_key("openrouter") or None
    except Exception:
        return None


def _get_oauth_bearer(provider: str):
    """Return (access_token, base_url_override, extra_headers) if the user has
    a subscription connected for this provider; else None.

    Subscription-mode auth (ChatGPT Plus/Pro, SuperGrok) takes precedence
    over the stored API key when both are present. A RuntimeError here
    means the credential exists but the refresh failed — surface it so the
    user sees "reconnect" rather than a silent fallback to the API key.
    """
    try:
        from craftos_integrations.integrations.llm_oauth.tokens import get_bearer

        return get_bearer(provider)
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning(f"[FACTORY] OAuth bearer lookup for {provider} failed: {e}")
        return None


def _resolve_ollama_model(requested: str, base_url: str) -> str:
    """Return `requested` if Ollama has it, otherwise return the first available model."""
    try:
        tags_url = base_url.rstrip("/") + "/api/tags"
        with urllib.request.urlopen(tags_url, timeout=5) as resp:
            data = _json.loads(resp.read())
        available = [m["name"] for m in data.get("models", [])]
        if not available:
            return requested
        if requested in available:
            return requested
        logger.warning(
            "[OLLAMA] Model '%s' not found in Ollama. Available: %s. Using '%s'.",
            requested,
            available,
            available[0],
        )
        return available[0]
    except Exception:
        return requested


class ModelFactory:
    @staticmethod
    def create(
        *,
        provider: str,
        interface: InterfaceType,
        model_override: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        deferred: bool = False,
    ) -> dict:
        """Create model context for a given provider.

        Args:
            provider: The LLM provider name (openai, gemini, anthropic, byteplus, remote)
            interface: The interface type (LLM or VLM)
            model_override: Optional model name override
            api_key: API key for the provider (required for most providers)
            base_url: Base URL override (for byteplus/remote)
            deferred: If True, don't raise error if API key is missing (for lazy init)

        Returns:
            Dictionary with provider context including client instances
        """
        # OpenAI-compatible providers that use OpenAI client with a custom base_url
        _OPENAI_COMPAT = {"minimax", "deepseek", "moonshot", "grok", "openrouter", "glm", "fugu"}

        if provider not in PROVIDER_CONFIG:
            raise ValueError(f"Unsupported provider: {provider}")

        cfg = PROVIDER_CONFIG[provider]
        model = model_override or MODEL_REGISTRY[provider].get(interface)
        if model is None:
            if deferred:
                return {
                    "provider": provider,
                    "model": None,
                    "client": None,
                    "gemini_client": None,
                    "remote_url": None,
                    "byteplus": None,
                    "anthropic_client": None,
                    "bedrock_client": None,
                    "initialized": False,
                }
            supported = ", ".join(
                p for p, caps in MODEL_REGISTRY.items() if caps.get(interface)
            )
            raise ValueError(
                f"Provider '{provider}' does not support {interface.value}. "
                f"Supported providers: {supported}"
            )

        # Use provided base_url or fall back to default
        resolved_base_url = base_url or cfg.default_base_url

        # Default empty context (used when deferred and no API key)
        empty_context = {
            "provider": provider,
            "model": model,
            "client": None,
            "gemini_client": None,
            "remote_url": resolved_base_url if provider == "remote" else None,
            "byteplus": None,
            "anthropic_client": None,
            "bedrock_client": None,
            "initialized": False,
        }

        # Providers
        if provider == "openai":
            # Prefer ChatGPT subscription OAuth when connected — the JWT is
            # audience-locked to chatgpt.com/backend-api/codex, so this path
            # also rewrites the base_url + injects the required Codex
            # impersonation headers (Originator, Beta, chatgpt-account-id).
            # The bare OpenAI client would issue ``/chat/completions`` against
            # that base URL and 404, so we wrap it in a translator that
            # re-routes through the Responses API.
            oauth = _get_oauth_bearer("openai")
            if oauth is not None:
                from agent_core.core.models.chatgpt_subscription_client import (
                    ChatGPTSubscriptionClient,
                )

                access_token, sub_base_url, extra_headers = oauth

                # Codex's accepted-model list lives in the ChatGPT OAuth
                # backend module so provider-specific knowledge stays
                # colocated with the flow that authenticates against it.
                # See ``llm_oauth.chatgpt.CODEX_ACCEPTED_MODELS`` for the
                # source-of-truth list and the reasoning behind the fallback.
                from craftos_integrations.integrations.llm_oauth.chatgpt import (
                    CODEX_ACCEPTED_MODELS,
                    effective_model_for_subscription,
                )

                effective_model, was_substituted = effective_model_for_subscription(model)
                if was_substituted:
                    logger.warning(
                        f"[FACTORY] ChatGPT subscription mode rejects model "
                        f"{model!r}; substituting {effective_model!r}. "
                        f"Valid Codex-subscription models: "
                        f"{sorted(CODEX_ACCEPTED_MODELS)}. Set the model in "
                        f"Settings to silence this warning."
                    )

                sdk_client = OpenAI(
                    api_key=access_token,
                    base_url=sub_base_url,
                    default_headers=extra_headers,
                )
                return {
                    "provider": provider,
                    "model": effective_model,
                    "client": ChatGPTSubscriptionClient(sdk_client),
                    "gemini_client": None,
                    "remote_url": None,
                    "byteplus": None,
                    "anthropic_client": None,
                    "bedrock_client": None,
                    "initialized": True,
                    "auth_mode": "subscription",
                }

            if not api_key:
                if deferred:
                    return empty_context
                raise ValueError("API key required for OpenAI")

            return {
                "provider": provider,
                "model": model,
                "client": OpenAI(api_key=api_key),
                "gemini_client": None,
                "remote_url": None,
                "byteplus": None,
                "anthropic_client": None,
                "bedrock_client": None,
                "initialized": True,
            }

        if provider == "gemini":
            if not api_key:
                if deferred:
                    return empty_context
                raise ValueError("API key required for Gemini")

            return {
                "provider": provider,
                "model": model,
                "client": None,
                "gemini_client": GeminiClient(api_key),
                "remote_url": None,
                "byteplus": None,
                "anthropic_client": None,
                "bedrock_client": None,
                "initialized": True,
            }

        if provider == "anthropic":
            if not api_key:
                if deferred:
                    return empty_context
                raise ValueError("API key required for Anthropic")

            return {
                "provider": provider,
                "model": model,
                "client": None,
                "gemini_client": None,
                "remote_url": None,
                "byteplus": None,
                "anthropic_client": Anthropic(api_key=api_key),
                "bedrock_client": None,
                "initialized": True,
            }

        if provider == "byteplus":
            if not api_key:
                if deferred:
                    return empty_context
                raise ValueError("API key required for BytePlus")

            return {
                "provider": provider,
                "model": model,
                "client": None,
                "gemini_client": None,
                "remote_url": None,
                "byteplus": {
                    "api_key": api_key,
                    "base_url": resolved_base_url,
                },
                "anthropic_client": None,
                "bedrock_client": None,
                "initialized": True,
            }

        if provider == "remote":
            # Remote (Ollama) doesn't require API key.
            # Validate the model against Ollama's available models and auto-correct if needed.
            resolved_model = _resolve_ollama_model(model, resolved_base_url)
            return {
                "provider": provider,
                "model": resolved_model,
                "client": None,
                "gemini_client": None,
                "remote_url": resolved_base_url,
                "byteplus": None,
                "anthropic_client": None,
                "bedrock_client": None,
                "initialized": True,
            }

        if provider in _OPENAI_COMPAT:
            # Subscription OAuth takes precedence before any API-key/OpenRouter
            # fallback path. Grok subscription tokens hit the same
            # api.x.ai/v1 host as API-key mode, so the base_url override may
            # be None — the backend returns the URL it wants used.
            oauth = _get_oauth_bearer(provider)
            if oauth is not None:
                access_token, sub_base_url, extra_headers = oauth
                return {
                    "provider": provider,
                    "model": model,
                    "client": OpenAI(
                        api_key=access_token,
                        base_url=sub_base_url or resolved_base_url,
                        default_headers=extra_headers,
                    ),
                    "gemini_client": None,
                    "remote_url": None,
                    "byteplus": None,
                    "anthropic_client": None,
                    "bedrock_client": None,
                    "initialized": True,
                    "auth_mode": "subscription",
                }

            # Moonshot and MiniMax are geo-restricted for most international users.
            # Strategy:
            #   1. If a direct API key is provided → use the provider's own endpoint.
            #   2. If no direct key but OpenRouter is configured → proxy through OR.
            #   3. Otherwise → raise / defer as usual.
            if provider in _OPENROUTER_PROXIED and not api_key:
                or_key = _get_openrouter_key()
                if or_key:
                    or_model = _to_openrouter_slug(provider, model)
                    logger.info(
                        f"[FACTORY] No direct key for {provider} — routing through OpenRouter as {or_model}"
                    )
                    return {
                        "provider": "openrouter",
                        "model": or_model,
                        "client": OpenAI(api_key=or_key, base_url=_OPENROUTER_BASE_URL),
                        "gemini_client": None,
                        "remote_url": None,
                        "byteplus": None,
                        "anthropic_client": None,
                        "bedrock_client": None,
                        "initialized": True,
                    }

            if not api_key:
                if deferred:
                    return empty_context
                raise ValueError(f"API key required for {provider}")

            return {
                "provider": provider,
                "model": model,
                "client": OpenAI(api_key=api_key, base_url=resolved_base_url),
                "gemini_client": None,
                "remote_url": None,
                "byteplus": None,
                "anthropic_client": None,
                "bedrock_client": None,
                "initialized": True,
            }

        if provider == "bedrock":
            # Bedrock uses the boto3 credential chain. CraftBot stores AWS
            # credentials in settings.json (not env vars), so we pull them via
            # app.config — mirroring how the OpenRouter fallback path also
            # reaches into app.config to read its stored key.
            #
            # `base_url` carries the region through the factory plumbing
            # (api_key/base_url are the only fields the callers thread through).
            # If unset, fall back to settings → AWS_REGION env → default.
            region = resolved_base_url or "us-east-1"
            access_key = secret_key = session_token = None
            try:
                from app.config import get_aws_credentials  # type: ignore

                creds = get_aws_credentials()
                access_key = creds.get("access_key_id") or None
                secret_key = creds.get("secret_access_key") or None
                session_token = creds.get("session_token") or None
                region = creds.get("region") or region
            except Exception:
                # Falling back to boto3's default credential chain (env, IAM
                # role, SSO profile). Useful when running on an EC2/ECS host.
                pass

            if boto3 is None:
                if deferred:
                    return empty_context
                raise ImportError(
                    "boto3 is required for the Bedrock provider. "
                    "Install with `pip install boto3`."
                )

            try:
                client_kwargs = {"region_name": region}
                if access_key and secret_key:
                    client_kwargs["aws_access_key_id"] = access_key
                    client_kwargs["aws_secret_access_key"] = secret_key
                    if session_token:
                        client_kwargs["aws_session_token"] = session_token
                bedrock_client = boto3.client("bedrock-runtime", **client_kwargs)
            except Exception as exc:
                if deferred:
                    return empty_context
                raise EnvironmentError(
                    f"Failed to create Bedrock client: {exc}"
                ) from exc

            return {
                "provider": provider,
                "model": model,
                "client": None,
                "gemini_client": None,
                "remote_url": None,
                "byteplus": None,
                "anthropic_client": None,
                "bedrock_client": bedrock_client,
                "initialized": True,
            }

        raise RuntimeError("Unreachable")
