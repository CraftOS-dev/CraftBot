# -*- coding: utf-8 -*-
"""Model factory for creating provider-specific model contexts.

API keys and base URLs should be passed directly - no environment variable reading.
"""

import logging
from typing import Optional
import urllib.request
import json as _json

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


_PROVIDER_DISPLAY = {
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "grok": "Grok",
    "moonshot": "Moonshot",
    "minimax": "MiniMax",
    "openrouter": "OpenRouter",
}


def _create_openai_client(
    *,
    provider: str,
    api_key: str,
    base_url: Optional[str] = None,
):
    """Create an OpenAI SDK client for OpenAI-compatible providers."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        display = _PROVIDER_DISPLAY.get(provider, provider)
        raise ImportError(
            f"The openai package is required for {display} because CraftBot "
            "uses the OpenAI-compatible SDK client for this provider. "
            "Install it with the Python that launches CraftBot: "
            "`python -m pip install 'openai>=2.0.0'`."
        ) from exc

    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def _create_anthropic_client(*, api_key: str):
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise ImportError(
            "The anthropic package is required for the Anthropic provider. "
            "Install it with the Python that launches CraftBot: "
            "`python -m pip install 'anthropic>=0.97.0'`."
        ) from exc
    return Anthropic(api_key=api_key)


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
        # OpenAI-compatible providers that use chat-completions with a custom base_url.
        _OPENAI_COMPAT = {"minimax", "deepseek", "moonshot", "grok", "openrouter"}

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
            if not api_key:
                if deferred:
                    return empty_context
                raise ValueError("API key required for OpenAI")

            return {
                "provider": provider,
                "model": model,
                "client": _create_openai_client(
                    provider=provider,
                    api_key=api_key,
                ),
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
                "anthropic_client": _create_anthropic_client(api_key=api_key),
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
                        "client": _create_openai_client(
                            provider="openrouter",
                            api_key=or_key,
                            base_url=_OPENROUTER_BASE_URL,
                        ),
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
                "client": _create_openai_client(
                    provider=provider,
                    api_key=api_key,
                    base_url=resolved_base_url,
                ),
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
