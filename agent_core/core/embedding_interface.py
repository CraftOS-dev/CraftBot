# -*- coding: utf-8 -*-
"""
core.embedding_interface

Embedding interface supporting:
- OpenAI (via openai SDK)
- Google Gemini (via the public REST API)
- Remote (Ollama /api/embeddings)

Environment variables:
- OPENAI_API_KEY (for provider="openai")
- GOOGLE_API_KEY (for provider="gemini")
"""

import os
from typing import List, Optional

import requests

from agent_core.core.models.factory import ModelFactory
from agent_core.core.models.types import InterfaceType
from agent_core.utils.logger import logger

# Optional imports so the module works even if some SDKs aren't installed
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from agent_core.core.llm.google_gemini_client import GeminiAPIError, GeminiClient


class EmbeddingInterface:
    """
    A class to handle interactions with embedding models:
    - OpenAI
    - Google Gemini
    - Local/remote Ollama
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.provider = provider
        self._gemini_client: GeminiClient | None = None

        ctx = ModelFactory.create(
            provider=self.provider,
            interface=InterfaceType.EMBEDDING,
            model_override=model,
            api_key=api_key,
            base_url=base_url,
        )

        self.model = ctx["model"]
        self.client = ctx["client"]
        self._gemini_client = ctx["gemini_client"]
        self.remote_url = ctx["remote_url"]

        if ctx["byteplus"]:
            self.api_key = ctx["byteplus"]["api_key"]
            self.byteplus_base_url = ctx["byteplus"]["base_url"]

    # ─────────────────────────── Public API ───────────────────────────
    def get_embedding(self, text: str) -> Optional[List[float]]:
        """
        Get embedding vector for input text.

        :param text: Input text to embed
        :return: List[float] embedding vector, or None on failure
        """
        if not isinstance(text, str):
            raise TypeError("`text` must be a string.")

        if self.provider == "openai":
            return self._get_openai_embedding(text)
        elif self.provider == "gemini":
            return self._get_gemini_embedding(text)
        elif self.provider == "remote":
            return self._get_ollama_embedding(text)
        elif self.provider == "byteplus":
            return self._get_byteplus_embedding(text)
        elif self.provider == "anthropic":
            raise NotImplementedError(
                "Anthropic does not provide native embedding models. "
                "Consider using OpenAI or another provider for embeddings."
            )
        else:  # pragma: no cover
            raise RuntimeError(f"Unknown provider {self.provider!r}")

    # ───────────────────── Provider-specific helpers ───────────────────
    def _get_openai_embedding(self, text: str) -> Optional[List[float]]:
        try:
            response = self.client.embeddings.create(model=self.model, input=text)
            # OpenAI returns: response.data[0].embedding
            return response.data[0].embedding  # type: ignore[attr-defined]
        except Exception as e:
            logger.exception(f"Error calling OpenAI Embedding API: {e}")
            return None

    def _get_gemini_embedding(self, text: str) -> Optional[List[float]]:
        if not self._gemini_client:
            raise RuntimeError("Gemini client was not initialised.")

        try:
            return self._gemini_client.embed_text(self.model, text=text)
        except GeminiAPIError as e:
            logger.exception(f"Gemini rejected the embedding request: {e}")
            return None
        except Exception as e:
            logger.exception(f"Error calling Gemini Embedding API: {e}")
            return None

    def _get_byteplus_embedding(self, text: str) -> Optional[List[float]]:
        try:
            url = f"{self.byteplus_base_url.rstrip('/')}/embeddings/multimodal"
            payload = {
                "model": self.model,
                "input": [
                    {
                        "type": "text",
                        "text": text,
                    }
                ],
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            response = requests.post(url, json=payload, headers=headers, timeout=120)
            response.raise_for_status()
            result = response.json()
            data = result.get("data")
            if not data:
                return None
            return data.get("embedding")
        except Exception as e:
            logger.exception(f"Error calling BytePlus Embedding API: {e}")
            return None

    def _get_ollama_embedding(self, text: str) -> Optional[List[float]]:
        try:
            payload = {
                "model": self.model,
                "prompt": text,  # Ollama accepts "prompt" for /api/embeddings
            }
            url: str = f"{self.remote_url.rstrip('/')}/embeddings"
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()
            # Ollama returns {"embedding": [floats]}
            return result.get("embedding", None)
        except Exception as e:
            logger.exception(f"Error calling Ollama Embedding API: {e}")
            return None
