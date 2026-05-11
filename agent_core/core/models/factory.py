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

from agent_core.core.models.types import InterfaceType
from agent_core.core.models.model_registry import MODEL_REGISTRY
from agent_core.core.models.provider_config import PROVIDER_CONFIG
from agent_core.core.llm.google_gemini_client import GeminiClient

logger = logging.getLogger(__name__)


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
            requested, available, available[0],
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
        _OPENAI_COMPAT = {"minimax", "deepseek", "moonshot", "grok"}

        if provider not in PROVIDER_CONFIG:
            raise ValueError(f"Unsupported provider: {provider}")

        cfg = PROVIDER_CONFIG[provider]
        model = model_override or MODEL_REGISTRY[provider][interface]

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
                "client": OpenAI(api_key=api_key),
                "gemini_client": None,
                "remote_url": None,
                "byteplus": None,
                "anthropic_client": None,
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
                "initialized": True,
            }

        if provider in _OPENAI_COMPAT:
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
                "initialized": True,
            }

        raise RuntimeError("Unreachable")
