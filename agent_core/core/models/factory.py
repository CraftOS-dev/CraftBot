# -*- coding: utf-8 -*-
"""Model factory for creating provider-specific model contexts."""

import os
from openai import OpenAI
from anthropic import Anthropic

from agent_core.core.models.types import InterfaceType
from agent_core.core.models.model_registry import MODEL_REGISTRY
from agent_core.core.models.provider_config import PROVIDER_CONFIG
from agent_core.core.llm.google_gemini_client import GeminiClient


class ModelFactory:
    @staticmethod
    def create(
        *,
        provider: str,
        interface: InterfaceType,
        model_override: str | None = None,
        deferred: bool = False,
    ) -> dict:
        """Create model context for a given provider.

        Args:
            provider: The LLM provider name (openai, gemini, anthropic, byteplus, remote)
            interface: The interface type (LLM or VLM)
            model_override: Optional model name override
            deferred: If True, don't raise error if API key is missing (for lazy init)

        Returns:
            Dictionary with provider context including client instances
        """
        if provider not in PROVIDER_CONFIG:
            raise ValueError(f"Unsupported provider: {provider}")

        cfg = PROVIDER_CONFIG[provider]
        model = model_override or MODEL_REGISTRY[provider][interface]

        # Resolve base URL (if any)
        base_url = None
        if cfg.default_base_url:
            base_url = os.getenv(cfg.base_url_env, cfg.default_base_url)

        # Default empty context (used when deferred and no API key)
        empty_context = {
            "provider": provider,
            "model": model,
            "client": None,
            "gemini_client": None,
            "remote_url": base_url if provider == "remote" else None,
            "byteplus": None,
            "anthropic_client": None,
            "initialized": False,
        }

        # Providers
        if provider == "openai":
            api_key = os.getenv(cfg.api_key_env)
            if not api_key:
                if deferred:
                    return empty_context
                raise EnvironmentError("OPENAI_API_KEY not set")

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
            api_key = os.getenv(cfg.api_key_env)
            if not api_key:
                if deferred:
                    return empty_context
                raise EnvironmentError("GOOGLE_API_KEY not set")

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
            api_key = os.getenv(cfg.api_key_env)
            if not api_key:
                if deferred:
                    return empty_context
                raise EnvironmentError("ANTHROPIC_API_KEY not set")

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
            api_key = os.getenv(cfg.api_key_env)
            if not api_key:
                if deferred:
                    return empty_context
                raise EnvironmentError("BYTEPLUS_API_KEY not set")

            return {
                "provider": provider,
                "model": model,
                "client": None,
                "gemini_client": None,
                "remote_url": None,
                "byteplus": {
                    "api_key": api_key,
                    "base_url": base_url,
                },
                "anthropic_client": None,
                "initialized": True,
            }

        if provider == "remote":
            # Remote (Ollama) doesn't require API key
            return {
                "provider": provider,
                "model": model,
                "client": None,
                "gemini_client": None,
                "remote_url": base_url,
                "byteplus": None,
                "anthropic_client": None,
                "initialized": True,
            }

        raise RuntimeError("Unreachable")
