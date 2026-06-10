# -*- coding: utf-8 -*-
"""Utility client for interacting with the Google Generative Language REST API.

This small helper wraps the HTTP endpoints used by Gemini so that we can
interact with the service without pulling in the ``google-genai`` package.
Using the REST interface keeps stderr free from the gRPC warnings the SDK
emits during import/initialisation (e.g. the ``ALTS creds ignored`` message
that was polluting the CLI output).
"""

from __future__ import annotations


import base64
import logging
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

    def generate_text_multiturn(
        self,
        model: str,
        *,
        contents: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """Generate text from a pre-built multi-turn `contents` array.

        This is the cache-friendly companion to ``generate_text``: by sending
        the growing user/model history as ``contents`` each call, Gemini's
        implicit caching matches the longest stable prefix automatically and
        serves the matched portion from cache (90% discount on Gemini 2.5).

        Args:
            model: Model identifier (e.g. ``gemini-2.5-pro``).
            contents: List of ``{"role": "user"|"model", "parts": [...]}``
                dicts representing the full conversation history plus the new
                user turn at the end.
            system_prompt: Optional system instruction (sent in
                ``systemInstruction`` field, not part of contents).
            temperature: Sampling temperature.
            max_output_tokens: Output token cap.
            json_mode: Force JSON response.

        Returns:
            Same shape as ``generate_text``.
        """
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

    def generate_multimodal(
        self,
        model: str,
        *,
        text: str,
        image_bytes_list: List[bytes],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        json_mode: bool = False,
    ) -> Dict[str, Any]:
        """Generate text from a prompt that contains one or more inline images.

        Normalises both single-image and multi-image inputs into a consistent
        request format for the Gemini API.

        Returns a dict containing:
            - tokens_used: Total tokens consumed
            - content: Generated text content
            - prompt_tokens: Input/prompt token count
            - completion_tokens: Output/completion token count
            - cached_tokens: Tokens served from implicit cache (if any)

        Args:
            model: Model identifier
            text: The text prompt

            image_bytes_list: List of image data (PNG/JPEG)
            system_prompt: Optional system instruction
            temperature: Sampling temperature
            json_mode: If True, enforce JSON output format

        Returns:
            Dict with generation results and token counts
        """
        parts: List[Dict[str, Any]] = [{"text": text}]
        for img in image_bytes_list:
            mime = "image/jpeg"
            parts.append(
                {
                    "inlineData": {
                        "mimeType": mime,
                        "data": base64.b64encode(img).decode("utf-8"),
                    }
                }
            )

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
            headers={"x-goog-api-key": self._api_key},
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

    def generate_image(
        self,
        model: str,
        *,
        prompt: str,
        reference_images: Optional[List[tuple]] = None,
        image_size: Optional[str] = None,
        safety_settings: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Generate image(s) via generateContent with the IMAGE response modality.

        Uses the same REST endpoint as the text/multimodal helpers (no
        ``google-genai`` SDK), keeping the whole Gemini surface on one client.

        Args:
            model: Image-capable model identifier (e.g. ``gemini-3-pro-image``).
            prompt: Text description of the image to generate.
            reference_images: Optional list of ``(bytes, mime_type)`` tuples sent
                as inline reference parts (style guidance).
            image_size: Optional size hint (e.g. ``"1K"``/``"2K"``/``"4K"``) passed
                through ``generationConfig.imageConfig.imageSize``.
            safety_settings: Optional list of ``{"category", "threshold"}`` dicts.

        Returns:
            Dict with:
                - images: List[bytes] of decoded image data (may be empty)
                - usage_metadata: Dict from the response's ``usageMetadata``
                - block_reason: Optional[str] when blocked by a safety/finish reason
        """
        parts: List[Dict[str, Any]] = []
        for data, mime in reference_images or []:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": mime or "image/png",
                        "data": base64.b64encode(data).decode("utf-8"),
                    }
                }
            )
        parts.append({"text": prompt})

        generation_config: Dict[str, Any] = {
            "responseModalities": ["TEXT", "IMAGE"],
            "candidateCount": 1,
        }
        if image_size:
            generation_config["imageConfig"] = {"imageSize": image_size}

        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
        }
        if safety_settings:
            payload["safetySettings"] = safety_settings

        response = self._post_json(
            f"{_normalise_model_name(model)}:generateContent", payload
        )

        images: List[bytes] = []
        for candidate in response.get("candidates", []) or []:
            content = candidate.get("content") or {}
            for part in content.get("parts", []) or []:
                inline = part.get("inlineData") if isinstance(part, dict) else None
                if inline and str(inline.get("mimeType", "")).startswith("image/"):
                    try:
                        images.append(base64.b64decode(inline["data"]))
                    except Exception:
                        pass

        block_reason: Optional[str] = None
        if not images:
            feedback = response.get("promptFeedback")
            if isinstance(feedback, dict) and feedback.get("blockReason"):
                block_reason = str(feedback["blockReason"])
            else:
                for candidate in response.get("candidates", []) or []:
                    fr = candidate.get("finishReason")
                    if fr and "SAFETY" in str(fr).upper():
                        block_reason = str(fr)
                        break

        return {
            "images": images,
            "usage_metadata": response.get("usageMetadata", {}) or {},
            "block_reason": block_reason,
        }

    # ------------------------------------------------------------------
    # Veo video generation (long-running operation)
    # ------------------------------------------------------------------
    def generate_video(
        self,
        model: str,
        *,
        prompt: str,
        negative_prompt: Optional[str] = None,
        image: Optional[tuple] = None,
        last_frame: Optional[tuple] = None,
        reference_images: Optional[List[tuple]] = None,
        aspect_ratio: Optional[str] = None,
        duration_seconds: Optional[str] = None,
        resolution: Optional[str] = None,
        person_generation: Optional[str] = None,
        number_of_videos: Optional[int] = None,
        seed: Optional[int] = None,
        generate_audio: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Kick off a Veo video generation as a long-running operation.

        Args:
            model: Veo model identifier (e.g. ``veo-3.1-generate-preview``).
            prompt: Text description of the video to generate.
            negative_prompt: Optional text describing what to avoid.
            image: Optional ``(bytes, mime_type)`` start-frame for image-to-video.
            last_frame: Optional ``(bytes, mime_type)`` end-frame for frame
                interpolation (Veo 3.1+).
            reference_images: Optional list of ``(bytes, mime_type)`` reference
                frames for style guidance (up to 3, Veo 3.1+).
            aspect_ratio: ``"16:9"`` or ``"9:16"``.
            duration_seconds: Duration as an INTEGER. Veo 3 accepts ``4`` /
                ``6`` / ``8``; 1080p+/refs require ``8``. (Earlier docs showed
                a string, but the live ``veo-3.1-generate-preview`` model
                rejects strings with 400 INVALID_ARGUMENT.)
            resolution: ``"720p"`` / ``"1080p"`` / ``"4k"`` (4k unavailable on Lite).
            person_generation: ``"allow_all"`` / ``"allow_adult"`` / ``"dont_allow"``.
                ``allow_all`` is geo-restricted (EU/UK/CH/MENA).
            number_of_videos: Number of videos to generate (typically 1–4).
            seed: Optional deterministic seed.
            generate_audio: Whether to generate synchronized native audio.
                Default behavior is provider-decided; set explicitly to control.

        Returns:
            Dict with the long-running operation ``{"name": "operations/..."}``.
            Pass the returned name to :meth:`poll_video_operation` to wait for
            completion.
        """
        instance: Dict[str, Any] = {"prompt": prompt}
        if image is not None:
            data, mime = image
            instance["image"] = {
                "bytesBase64Encoded": base64.b64encode(data).decode("utf-8"),
                "mimeType": mime or "image/png",
            }
        if last_frame is not None:
            data, mime = last_frame
            instance["lastFrame"] = {
                "bytesBase64Encoded": base64.b64encode(data).decode("utf-8"),
                "mimeType": mime or "image/png",
            }
        if reference_images:
            instance["referenceImages"] = [
                {
                    "image": {
                        "bytesBase64Encoded": base64.b64encode(data).decode("utf-8"),
                        "mimeType": mime or "image/png",
                    }
                }
                for data, mime in reference_images
            ]

        parameters: Dict[str, Any] = {}
        if aspect_ratio is not None:
            parameters["aspectRatio"] = aspect_ratio
        if duration_seconds is not None:
            # Veo expects an integer; passing a string yields
            # 400 INVALID_ARGUMENT ("durationSeconds needs to be a number").
            parameters["durationSeconds"] = int(duration_seconds)
        if resolution is not None:
            parameters["resolution"] = resolution
        if person_generation is not None:
            parameters["personGeneration"] = person_generation
        # numberOfVideos is rejected outright by some Veo variants (e.g.
        # veo-3.1-generate-preview). Only include it when the caller asked
        # for more than one — single-video requests omit the field.
        if number_of_videos is not None and number_of_videos > 1:
            parameters["numberOfVideos"] = number_of_videos
        if seed is not None:
            parameters["seed"] = seed
        if negative_prompt:
            parameters["negativePrompt"] = negative_prompt
        if generate_audio is not None:
            parameters["generateAudio"] = generate_audio

        payload: Dict[str, Any] = {"instances": [instance]}
        if parameters:
            payload["parameters"] = parameters

        return self._post_json(
            f"{_normalise_model_name(model)}:predictLongRunning", payload
        )

    def poll_video_operation(self, operation_name: str) -> Dict[str, Any]:
        """Poll a Veo long-running operation. Returns the raw operation JSON.

        The caller should check ``response["done"]`` and, when true, extract
        ``response["response"]["generateVideoResponse"]["generatedSamples"]``
        for the resulting video URIs.
        """
        path = operation_name.lstrip("/")
        if path.startswith(f"{self._api_version}/"):
            path = path[len(f"{self._api_version}/") :]
        url = self._endpoint(path)
        response = requests.get(
            url,
            headers={"x-goog-api-key": self._api_key},
            timeout=self._timeout,
        )
        if not response.ok:
            try:
                logger.warning(
                    f"[GEMINI ERROR] Veo poll status={response.status_code} body={response.json()}"
                )
            except Exception:
                logger.warning(
                    f"[GEMINI ERROR] Veo poll status={response.status_code} text={response.text[:1000]}"
                )
        response.raise_for_status()
        return response.json()

    def download_video(self, video_uri: str, *, timeout: int = 120) -> bytes:
        """Download a Veo signed video URI as raw MP4 bytes.

        Veo returns a URI on the ``generativelanguage.googleapis.com`` host
        that requires the API key. Sent via the ``x-goog-api-key`` header so
        the key never appears in the URL — otherwise it would leak through
        ``HTTPError`` messages (which include the request URL) and any
        request/response logging.
        """
        response = requests.get(
            video_uri,
            headers={"x-goog-api-key": self._api_key},
            timeout=timeout,
            stream=False,
        )
        response.raise_for_status()
        return response.content

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
            headers={"x-goog-api-key": self._api_key},
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
