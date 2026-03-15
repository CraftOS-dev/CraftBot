# -*- coding: utf-8 -*-
"""Utility client for interacting with the Google Generative Language REST API.

This small helper wraps the HTTP endpoints used by Gemini so that we can
interact with the service without pulling in the ``google-generativeai``
package.  Using the REST interface keeps stderr free from the gRPC warnings the
SDK emits during import/initialisation (e.g. the ``ALTS creds ignored`` message
that was polluting the CLI output).
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Iterable, List, Optional

import requests

# Logging setup - try to use agent_core logger, fall back to standard logging
try:
    from agent_core.utils.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DEFAULT_API_BASE = "https://generativelanguage.googleapis.com"
DEFAULT_API_VERSION = "v1beta"


class GeminiAPIError(RuntimeError):
    """Raised when the Gemini service reports an error or blocks a prompt."""


def _normalise_model_name(model: str) -> str:
    """Ensure model identifiers include the ``models/`` prefix."""
    model = model.strip()
    return model if model.startswith("models/") else f"models/{model}"


class GeminiClient:
    """Lightweight REST client for Gemini models.

    This client provides methods to interact with Google's Gemini API for:
    - Text generation (with optional system prompts)
    - Multimodal generation (text + images)
    - Text embeddings
    - Explicit caching for cost optimization

    Attributes:
        _api_key: The API key for authentication
        _api_base: Base URL for the API
        _api_version: API version string
        _timeout: Request timeout in seconds
    """

    def __init__(
        self,
        api_key: str,
        *,
        api_base: Optional[str] = None,
        api_version: Optional[str] = None,
        timeout: int = 120,
    ) -> None:
        """Initialize the Gemini client.

        Args:
            api_key: Google API key for authentication
            api_base: Base URL override (default: generativelanguage.googleapis.com)
            api_version: API version override (default: v1beta)
            timeout: Request timeout in seconds (default: 120)

        Raises:
            ValueError: If api_key is empty
        """
        if not api_key:
            raise ValueError("`api_key` must be a non-empty string.")

        self._api_key = api_key
        self._api_base = (api_base or DEFAULT_API_BASE).rstrip("/")
        self._api_version = api_version or DEFAULT_API_VERSION
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def generate_text(
        self,
        model: str,
        *,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """Generate text for a purely textual prompt.

        Returns a dict containing:
            - tokens_used: Total tokens consumed
            - content: Generated text content
            - prompt_tokens: Input/prompt token count
            - completion_tokens: Output/completion token count
            - cached_tokens: Tokens served from implicit cache (if any)

        Gemini's implicit caching (enabled by default since May 2025):
            - Automatically caches repeated content
            - 90% discount on cached tokens for Gemini 2.5 models
            - Returns cachedContentTokenCount in usageMetadata when cache is used

        Args:
            model: Model identifier (e.g., "gemini-2.5-flash")
            prompt: The user prompt
            system_prompt: Optional system instruction
            temperature: Sampling temperature
            max_output_tokens: Maximum output tokens
            json_mode: If True, enforce JSON output format

        Returns:
            Dict with generation results and token counts
        """
        contents = [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ]

        generation_config: Dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if max_output_tokens is not None:
            generation_config["maxOutputTokens"] = max_output_tokens
        if json_mode:
            generation_config["responseMimeType"] = "application/json"

        payload: Dict[str, Any] = {"contents": contents}
        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}],
            }
        if generation_config:
            payload["generationConfig"] = generation_config

        response = self._post_json(
            f"{_normalise_model_name(model)}:generateContent", payload
        )

        # Extract token usage from usageMetadata
        usage_metadata = response.get("usageMetadata", {})
        total_tokens = usage_metadata.get("totalTokenCount", 0)
        prompt_tokens = usage_metadata.get("promptTokenCount", 0)
        completion_tokens = usage_metadata.get("candidatesTokenCount", 0)
        # Implicit caching returns cachedContentTokenCount when cache is used
        cached_tokens = usage_metadata.get("cachedContentTokenCount", 0)

        content = self._extract_text(response)

        return {
            "tokens_used": total_tokens,
            "content": content,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached_tokens": cached_tokens,
        }

    def generate_multimodal(
        self,
        model: str,
        *,
        text: str,
        image_bytes: bytes,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """Generate text from a prompt that also contains an inline image.

        Returns a dict containing:
            - tokens_used: Total tokens consumed
            - content: Generated text content
            - prompt_tokens: Input/prompt token count
            - completion_tokens: Output/completion token count
            - cached_tokens: Tokens served from implicit cache (if any)

        Args:
            model: Model identifier
            text: The text prompt
            image_bytes: PNG image data
            system_prompt: Optional system instruction
            temperature: Sampling temperature
            json_mode: If True, enforce JSON output format

        Returns:
            Dict with generation results and token counts
        """
        inline_data = {
            "mimeType": "image/png",
            "data": base64.b64encode(image_bytes).decode("utf-8"),
        }

        parts: List[Dict[str, Any]] = [{"text": text}, {"inlineData": inline_data}]
        contents = [{"role": "user", "parts": parts}]

        payload: Dict[str, Any] = {"contents": contents}
        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}],
            }

        generation_config: Dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        if generation_config:
            payload["generationConfig"] = generation_config

        response = self._post_json(
            f"{_normalise_model_name(model)}:generateContent", payload
        )

        # Extract token usage from usageMetadata
        usage_metadata = response.get("usageMetadata", {})
        total_tokens = usage_metadata.get("totalTokenCount", 0)
        prompt_tokens = usage_metadata.get("promptTokenCount", 0)
        completion_tokens = usage_metadata.get("candidatesTokenCount", 0)
        cached_tokens = usage_metadata.get("cachedContentTokenCount", 0)

        content = self._extract_text(response)

        return {
            "tokens_used": total_tokens,
            "content": content,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached_tokens": cached_tokens,
        }

    def embed_text(self, model: str, *, text: str) -> List[float]:
        """Fetch an embedding vector for the supplied text.

        Args:
            model: Embedding model identifier
            text: Text to embed

        Returns:
            List of float values representing the embedding

        Raises:
            GeminiAPIError: If response doesn't contain embeddings
        """
        payload = {
            "content": {
                "parts": [{"text": text}],
            }
        }
        response = self._post_json(
            f"{_normalise_model_name(model)}:embedContent", payload
        )

        embedding = response.get("embedding")
        if isinstance(embedding, dict) and "values" in embedding:
            return list(map(float, embedding.get("values", [])))
        if isinstance(embedding, list):
            return [float(x) for x in embedding]

        raise GeminiAPIError("Gemini embedContent response did not contain embeddings.")

    # ------------------------------------------------------------------
    # Explicit Caching Methods
    # ------------------------------------------------------------------
    def create_cache(
        self,
        model: str,
        *,
        system_prompt: str,
        display_name: Optional[str] = None,
        ttl_seconds: int = 3600,
    ) -> Dict[str, Any]:
        """Create an explicit cache for the given system prompt.

        Explicit caching allows you to cache specific content (like system prompts)
        and reference it in subsequent requests. This is different from implicit
        caching which is automatic but unpredictable.

        Args:
            model: The model to use (e.g., "gemini-2.5-flash")
            system_prompt: The system instruction to cache
            display_name: Optional human-readable name for the cache
            ttl_seconds: Time-to-live in seconds (default 1 hour)

        Returns:
            Dict with cache info including 'name' (the cache ID to use in requests)

        Note:
            Minimum token requirements for caching:
            - Gemini 2.5 Flash: 1024 tokens
            - Gemini 2.5 Pro: 4096 tokens
        """
        payload: Dict[str, Any] = {
            "model": _normalise_model_name(model),
            "systemInstruction": {
                "parts": [{"text": system_prompt}],
            },
            "ttl": f"{ttl_seconds}s",
        }
        if display_name:
            payload["displayName"] = display_name

        response = self._post_json("cachedContents", payload)
        return response

    def delete_cache(self, cache_name: str) -> None:
        """Delete an explicit cache by its name.

        Args:
            cache_name: The cache name/ID returned from create_cache()
        """
        # Extract just the cache ID if full path provided
        if cache_name.startswith("cachedContents/"):
            cache_id = cache_name
        else:
            cache_id = f"cachedContents/{cache_name}"

        url = self._endpoint(cache_id)
        response = requests.delete(
            url,
            params={"key": self._api_key},
            timeout=self._timeout,
        )
        response.raise_for_status()

    def generate_text_with_cache(
        self,
        model: str,
        *,
        cache_name: str,
        prompt: str,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """Generate text using an explicit cache.

        The cache should contain the system prompt. Only the user prompt
        is sent with each request, dramatically reducing input tokens.

        Args:
            model: The model to use (must match the cached model)
            cache_name: The cache name/ID from create_cache()
            prompt: The user prompt for this request
            temperature: Sampling temperature
            max_output_tokens: Maximum output tokens
            json_mode: If True, enforce JSON output format

        Returns:
            Dict with tokens_used, content, prompt_tokens, completion_tokens, cached_tokens
        """
        contents = [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ]

        generation_config: Dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if max_output_tokens is not None:
            generation_config["maxOutputTokens"] = max_output_tokens
        if json_mode:
            generation_config["responseMimeType"] = "application/json"

        payload: Dict[str, Any] = {
            "contents": contents,
            "cachedContent": cache_name,
        }
        if generation_config:
            payload["generationConfig"] = generation_config

        response = self._post_json(
            f"{_normalise_model_name(model)}:generateContent", payload
        )

        # Extract token usage from usageMetadata
        usage_metadata = response.get("usageMetadata", {})
        total_tokens = usage_metadata.get("totalTokenCount", 0)
        prompt_tokens = usage_metadata.get("promptTokenCount", 0)
        completion_tokens = usage_metadata.get("candidatesTokenCount", 0)
        cached_tokens = usage_metadata.get("cachedContentTokenCount", 0)

        content = self._extract_text(response)

        return {
            "tokens_used": total_tokens,
            "content": content,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached_tokens": cached_tokens,
        }

    def generate_multimodal_with_cache(
        self,
        model: str,
        *,
        cache_name: str,
        text: str,
        image_bytes: bytes,
        temperature: Optional[float] = None,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """Generate multimodal response using an explicit cache.

        Args:
            model: The model to use (must match the cached model)
            cache_name: The cache name/ID from create_cache()
            text: The text prompt
            image_bytes: The image data
            temperature: Sampling temperature
            json_mode: If True, enforce JSON output format

        Returns:
            Dict with tokens_used, content, prompt_tokens, completion_tokens, cached_tokens
        """
        inline_data = {
            "mimeType": "image/png",
            "data": base64.b64encode(image_bytes).decode("utf-8"),
        }

        parts: List[Dict[str, Any]] = [{"text": text}, {"inlineData": inline_data}]
        contents = [{"role": "user", "parts": parts}]

        payload: Dict[str, Any] = {
            "contents": contents,
            "cachedContent": cache_name,
        }

        generation_config: Dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        if generation_config:
            payload["generationConfig"] = generation_config

        response = self._post_json(
            f"{_normalise_model_name(model)}:generateContent", payload
        )

        # Extract token usage from usageMetadata
        usage_metadata = response.get("usageMetadata", {})
        total_tokens = usage_metadata.get("totalTokenCount", 0)
        prompt_tokens = usage_metadata.get("promptTokenCount", 0)
        completion_tokens = usage_metadata.get("candidatesTokenCount", 0)
        cached_tokens = usage_metadata.get("cachedContentTokenCount", 0)

        content = self._extract_text(response)

        return {
            "tokens_used": total_tokens,
            "content": content,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached_tokens": cached_tokens,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _endpoint(self, path: str) -> str:
        """Build full API endpoint URL."""
        return f"{self._api_base}/{self._api_version}/{path.lstrip('/')}"

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send POST request and return JSON response."""
        response = requests.post(
            self._endpoint(path),
            params={"key": self._api_key},
            json=payload,
            timeout=self._timeout,
        )

        # Log response details before raising for status (helps debug API errors)
        if not response.ok:
            try:
                error_json = response.json()
                logger.warning(
                    f"[GEMINI ERROR] Status: {response.status_code}, Body: {error_json}"
                )
            except Exception:
                logger.warning(
                    f"[GEMINI ERROR] Status: {response.status_code}, "
                    f"Raw text: {response.text[:1000]}"
                )

        response.raise_for_status()
        return response.json()

    @staticmethod
    def _extract_text(response: Dict[str, Any]) -> str:
        """Extract text content from Gemini response."""
        feedback = response.get("promptFeedback")
        if isinstance(feedback, dict):
            reason = feedback.get("blockReason")
            if reason:
                raise GeminiAPIError(f"Prompt blocked by Gemini: {reason}")

        candidates: Iterable[Dict[str, Any]] = response.get("candidates", []) or []
        candidates_list = list(candidates)

        for candidate in candidates_list:
            finish_reason = candidate.get("finishReason")
            if finish_reason == "SAFETY":
                # Skip candidates halted for safety reasons.
                logger.warning(
                    f"[GEMINI] Candidate blocked for safety: "
                    f"{candidate.get('safetyRatings', [])}"
                )
                continue
            content = candidate.get("content") or {}
            parts: Iterable[Dict[str, Any]] = content.get("parts", []) or []
            texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
            text = "".join(texts).strip()
            if text:
                return text
            else:
                # Log when candidate exists but has no text
                logger.warning(
                    f"[GEMINI] Candidate has no text content. "
                    f"finishReason={finish_reason}, parts_count={len(list(parts))}, "
                    f"candidate_keys={list(candidate.keys())}"
                )

        # Log when no usable candidates found
        if candidates_list:
            finish_reasons = [c.get("finishReason") for c in candidates_list]
            logger.warning(
                f"[GEMINI] No usable content from {len(candidates_list)} candidates. "
                f"finishReasons={finish_reasons}"
            )
        else:
            logger.warning(
                f"[GEMINI] Response has no candidates. "
                f"Response keys: {list(response.keys())}"
            )

        return ""
