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

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from agent_core.core.errors import ClassifiedError

import requests

from agent_core.core.models.factory import ModelFactory
from agent_core.core.models.types import InterfaceType
from agent_core.utils.logger import logger

from agent_core.core.llm.google_gemini_client import GeminiClient


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
        self._bedrock_client = ctx.get("bedrock_client")

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
        elif self.provider == "bedrock":
            return self._get_bedrock_embedding(text)
        elif self.provider == "anthropic":
            raise NotImplementedError(
                "Anthropic does not provide native embedding models. "
                "Consider using OpenAI or another provider for embeddings."
            )
        else:  # pragma: no cover
            raise RuntimeError(f"Unknown provider {self.provider!r}")

    # ───────────────────── Provider-specific helpers ───────────────────
    def _log_classified(self, tag: str, e: Exception) -> None:
        """Log *e* through the shared classifier instead of raw str(e)."""
        from agent_core.core.impl.llm.errors import classify_llm_error

        info = classify_llm_error(e, provider=self.provider, model=self.model)
        logger.error(f"[EMBEDDING] {tag}: {info.message}")

    @staticmethod
    def _not_initialised(provider: str, client_name: str) -> "ClassifiedError":
        from agent_core.core.errors import ClassifiedError
        from agent_core.core.impl.llm.errors import classify_llm_error

        return ClassifiedError(
            classify_llm_error(
                RuntimeError(f"{client_name} client was not initialised."),
                provider=provider,
            )
        )

    def _get_openai_embedding(self, text: str) -> Optional[List[float]]:
        try:
            response = self.client.embeddings.create(model=self.model, input=text)
            # OpenAI returns: response.data[0].embedding
            return response.data[0].embedding  # type: ignore[attr-defined]
        except Exception as e:
            self._log_classified("OpenAI", e)
            return None

    def _get_gemini_embedding(self, text: str) -> Optional[List[float]]:
        if not self._gemini_client:
            raise self._not_initialised("gemini", "Gemini")

        try:
            return self._gemini_client.embed_text(self.model, text=text)
        except Exception as e:
            self._log_classified("Gemini", e)
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
            self._log_classified("BytePlus", e)
            return None

    def _get_bedrock_embedding(self, text: str) -> Optional[List[float]]:
        """Invoke an embedding model on AWS Bedrock.

        Titan Text Embeddings (v1 / v2) accept `{"inputText": "..."}` and
        return `{"embedding": [floats]}`. The invoke_model API is used here
        (Converse doesn't expose embeddings).
        """
        if not self._bedrock_client:
            raise self._not_initialised("bedrock", "Bedrock")

        try:
            import json as _json

            payload = {"inputText": text}
            response = self._bedrock_client.invoke_model(
                modelId=self.model,
                body=_json.dumps(payload),
                accept="application/json",
                contentType="application/json",
            )
            body = response.get("body")
            raw = body.read() if hasattr(body, "read") else body
            result = _json.loads(raw)
            return result.get("embedding")
        except Exception as e:
            self._log_classified("Bedrock", e)
            return None

    def _get_ollama_embedding(self, text: str) -> Optional[List[float]]:
        try:
            payload = {
                "model": self.model,
                "prompt": text,  # Ollama accepts "prompt" for /api/embeddings
            }
            url: str = f"{self.remote_url.rstrip('/')}/api/embeddings"
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json()
            # Ollama returns {"embedding": [floats]}
            return result.get("embedding", None)
        except Exception as e:
            self._log_classified("Ollama", e)
            return None
