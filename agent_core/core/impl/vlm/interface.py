# -*- coding: utf-8 -*-
"""
Shared VLM (Vision Language Model) interface for agent_core.

This module provides the VLMInterface class that handles vision-language
model calls across different providers (OpenAI, Gemini, Anthropic, BytePlus).

Hooks allow runtime-specific behavior:
- Token counting via get_token_count/set_token_count hooks
- Usage reporting via report_usage hook (CraftBot only)
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import time
from typing import Any, Dict, Optional

import requests

from agent_core.core.impl.llm.cache import get_cache_config, get_cache_metrics
from agent_core.utils.token import billable_tokens
from agent_core.core.hooks import (
    GetTokenCountHook,
    SetTokenCountHook,
    ReportUsageHook,
    UsageEventData,
)

# Set up logger - use shared agent_core logger for consistency
from agent_core.utils.logger import logger


class VLMInterface:
    """Vision Language Model interface with multi-provider support.

    Supports OpenAI, Gemini, Anthropic, BytePlus, and remote Ollama.
    Uses hooks for state access and usage reporting to decouple from
    runtime-specific state management.

    Args:
        provider: LLM provider name ("openai", "gemini", "anthropic", "byteplus", "remote").
        model: Model name override.
        temperature: Sampling temperature.
        deferred: Whether to defer initialization.
        get_token_count: Hook to get current token count from state.
        set_token_count: Hook to set token count in state.
        report_usage: Optional hook to report usage for cost tracking.
    """

    _CODE_BLOCK_RE = re.compile(r"^```(?:\w+)?\s*|\s*```$", re.MULTILINE)

    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.5,
        deferred: bool = False,
        get_token_count: Optional[GetTokenCountHook] = None,
        set_token_count: Optional[SetTokenCountHook] = None,
        report_usage: Optional[ReportUsageHook] = None,
    ) -> None:
        self.provider = provider
        self.temperature = temperature
        self._gemini_client = None
        self._anthropic_client = None
        self._initialized = False
        self._deferred = deferred

        # Store for reinitialization
        self._init_api_key = api_key
        self._init_base_url = base_url

        # Hooks for runtime-specific behavior
        self._get_token_count = get_token_count or (lambda: 0)
        self._set_token_count = set_token_count or (lambda x: None)
        self._report_usage = report_usage

        # Defer import to avoid circular dependency
        from app.models.factory import ModelFactory
        from app.models.types import InterfaceType
        from agent_core.core.models.model_registry import MODEL_REGISTRY

        # Providers like DeepSeek have VLM=None in the registry. Initializing
        # them would raise inside ModelFactory and crash the backend at startup.
        # Set up an uninitialized state instead — VLM actions then surface a
        # clean "VLM not available" error to the event stream.
        registry_model = model or MODEL_REGISTRY.get(provider, {}).get(
            InterfaceType.VLM
        )
        if registry_model is None:
            self.model = None
            self.client = None
            self.remote_url = None
            self._anthropic_client = None
            self._bedrock_client = None
            self._initialized = False
            return

        ctx = ModelFactory.create(
            provider=provider,
            interface=InterfaceType.VLM,
            model_override=model,
            api_key=api_key,
            base_url=base_url,
            deferred=deferred,
        )

        self.model = ctx["model"]
        self.client = ctx["client"]
        self._gemini_client = ctx["gemini_client"]
        self.remote_url = ctx["remote_url"]
        self._anthropic_client = ctx.get("anthropic_client")
        self._bedrock_client = ctx.get("bedrock_client")
        self._initialized = ctx.get("initialized", False)

        if ctx["byteplus"]:
            self.api_key = ctx["byteplus"]["api_key"]
            self.byteplus_base_url = ctx["byteplus"]["base_url"]

    @property
    def is_initialized(self) -> bool:
        """Check if the VLM client is properly initialized."""
        return self._initialized

    def reinitialize(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> bool:
        """Reinitialize the VLM client with new settings.

        Args:
            provider: Optional provider override. If None, uses current provider.
            api_key: Optional API key. If None, reads from settings.json.
            base_url: Optional base URL. If None, reads from settings.json.

        Returns:
            True if initialization was successful, False otherwise.
        """
        from app.models.factory import ModelFactory
        from app.models.types import InterfaceType

        target_provider = provider or self.provider

        # Read API key and base URL from settings.json if not provided
        if api_key is None or base_url is None:
            from app.config import get_api_key, get_base_url

            target_api_key = (
                api_key if api_key is not None else get_api_key(target_provider)
            )
            target_base_url = (
                base_url if base_url is not None else get_base_url(target_provider)
            )
        else:
            target_api_key = api_key
            target_base_url = base_url

        try:
            from app.config import get_vlm_model as _get_vlm_model  # type: ignore[import]

            target_model = _get_vlm_model()
        except Exception:
            target_model = (
                None  # app context not available (e.g. agent_core standalone)
            )

        try:
            logger.info(
                f"[VLM] Reinitializing with provider: {target_provider}, model: {target_model or 'registry default'}"
            )
            ctx = ModelFactory.create(
                provider=target_provider,
                interface=InterfaceType.VLM,
                model_override=target_model,
                api_key=target_api_key,
                base_url=target_base_url,
                deferred=False,
            )

            self.provider = ctx["provider"]
            self.model = ctx["model"]
            self.client = ctx["client"]
            self._gemini_client = ctx["gemini_client"]
            self.remote_url = ctx["remote_url"]
            self._anthropic_client = ctx.get("anthropic_client")
            self._bedrock_client = ctx.get("bedrock_client")
            self._initialized = ctx.get("initialized", False)

            if ctx["byteplus"]:
                self.api_key = ctx["byteplus"]["api_key"]
                self.byteplus_base_url = ctx["byteplus"]["base_url"]

            logger.info(
                f"[VLM] Reinitialized successfully with provider: {self.provider}, model: {self.model}"
            )
            return self._initialized
        except EnvironmentError as e:
            logger.warning(f"[VLM] Failed to reinitialize - missing API key: {e}")
            return False
        except Exception as e:
            logger.error(
                f"[VLM] Failed to reinitialize - unexpected error: {e}", exc_info=True
            )
            return False

    # ───────────────────────── Public Methods ─────────────────────────

    def describe_image(
        self,
        image_path: str,
        system_prompt: str | None = None,
        user_prompt: str | None = "Describe this image in detail.",
        log_response: bool = True,
    ) -> str:
        """Read an image from disk and describe it using the VLM.

        Args:
            image_path: Path to the image file.
            system_prompt: Optional system prompt for the VLM.
            user_prompt: User prompt describing what to look for.
            log_response: Whether to log the response.

        Returns:
            Textual description of the image.
        """
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        return self.describe_image_bytes(
            image_bytes,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            log_response=log_response,
        )

    def describe_image_bytes(
        self,
        image_bytes: bytes,
        system_prompt: str | None = None,
        user_prompt: str | None = "Describe this image in detail.",
        log_response: bool = True,
        json_mode: bool = True,
    ) -> str:
        """Describe an image from raw bytes using the VLM.

        Args:
            image_bytes: Raw image bytes.
            system_prompt: Optional system prompt for the VLM.
            user_prompt: User prompt describing what to look for.
            log_response: Whether to log the response.

        Returns:
            Textual description of the image.
        """
        try:
            if log_response:
                logger.info(f"[LLM SEND] system={system_prompt} | user={user_prompt}")

            if self.provider == "deepseek":
                raise RuntimeError(
                    "DeepSeek does not support vision/VLM. Use a different provider for image description."
                )
            elif self.provider in ("openai", "minimax", "moonshot", "grok", "glm"):
                response = self._openai_describe_bytes(
                    image_bytes, system_prompt, user_prompt, json_mode=json_mode
                )
            elif self.provider == "remote":
                response = self._ollama_describe_bytes(
                    image_bytes, system_prompt, user_prompt
                )
            elif self.provider == "gemini":
                response = self._gemini_describe_bytes(
                    image_bytes, system_prompt, user_prompt
                )
            elif self.provider == "byteplus":
                response = self._byteplus_describe_bytes(
                    image_bytes, system_prompt, user_prompt
                )
            elif self.provider == "anthropic":
                response = self._anthropic_describe_bytes(
                    image_bytes, system_prompt, user_prompt
                )
            elif self.provider == "bedrock":
                response = self._bedrock_describe_bytes(
                    image_bytes, system_prompt, user_prompt
                )
            else:
                raise RuntimeError(f"Unknown provider {self.provider!r}")

            cleaned = re.sub(
                self._CODE_BLOCK_RE, "", response.get("content", "").strip()
            )

            # Update token count via hook
            tokens_used = response.get("tokens_used", 0)
            if tokens_used:
                current_count = self._get_token_count()
                self._set_token_count(current_count + billable_tokens(response))

            if log_response:
                logger.info(f"[LLM RECV] {cleaned}")
            return cleaned
        except Exception as e:
            from agent_core.core.errors import ClassifiedError
            from agent_core.core.impl.llm.errors import classify_llm_error

            info = classify_llm_error(e, provider=self.provider, model=self.model)
            logger.error(f"[VLM] {info.message}")
            raise ClassifiedError(info) from e

    async def generate_response_async(
        self,
        image_bytes,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        debug: bool = False,
        log_response: bool = True,
    ) -> str:
        """Async wrapper that defers the blocking call to a worker thread."""
        if debug:
            debug_dir = "debug_images"
            file_name = f"{debug_dir}/image_{time.time()}.png"
            os.makedirs(debug_dir, exist_ok=True)
            with open(file_name, "wb") as f:
                f.write(image_bytes)
            logger.info(f"[DEBUG] Image saved to {file_name}")

        return await asyncio.to_thread(
            self.describe_image_bytes,
            image_bytes,
            system_prompt,
            user_prompt,
            log_response,
        )

    def describe_image_ocr(
        self,
        image_path: str,
        user_prompt: str | None = None,
    ) -> str:
        """
        Run OCR on an image. Returns raw extracted text, not a description.
        Uses a structured extraction system prompt regardless of provider.
        """
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        system_prompt = (
            "You are a precise OCR engine. Extract ALL text from this image exactly as it appears. "
            "Preserve line breaks, indentation, and formatting. "
            "Do NOT add commentary, interpretation, or markdown. "
            "Output only the raw extracted text. If no text is present, output an empty string."
        )
        effective_user = user_prompt or "Extract all text from this image."

        logger.info(f"[LLM SEND] OCR request | path={image_path}")

        cleaned = self.describe_image_bytes(
            image_bytes,
            system_prompt=system_prompt,
            user_prompt=effective_user,
            log_response=False,  # Logged below
            json_mode=False,
        )

        logger.info(f"[LLM RECV OCR] {cleaned[:120]}...")
        return cleaned

    def describe_video_frames(
        self,
        video_path: str,
        query: str | None = None,
        max_frames: int = 8,
    ) -> str:
        """
        Analyse video by extracting evenly-spaced keyframes and sending to VLM.
        Falls back to graceful error if OpenCV is unavailable.
        """
        try:
            import cv2
        except ImportError:
            raise RuntimeError(
                "opencv-python-headless is required for video analysis. "
                "Install with: pip install opencv-python-headless"
            )

        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames == 0:
            cap.release()
            raise ValueError("Video has 0 frames or could not be read.")

        indices = [int(i * total_frames / max_frames) for i in range(max_frames)]
        frame_bytes_list: list[bytes] = []

        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret:
                success, buf = cv2.imencode(".jpg", frame)
                if success:
                    frame_bytes_list.append(buf.tobytes())
        cap.release()

        if not frame_bytes_list:
            raise ValueError("Could not extract any frames from the video.")

        system_prompt = (
            f"You are analysing a video represented by {len(frame_bytes_list)} evenly-spaced keyframes. "
            "Provide: 1) An overall narrative summary of what is happening, "
            "2) Any visible text or titles, "
            "3) Key objects, people, or scenes, "
            "4) Notable transitions between frames."
        )
        effective_user = query or "Summarise the content of this video."

        # For multi-frame, send frames sequentially (all providers support single-image per call)
        # Gemini 1.5 Pro supports native multi-image; others receive concatenated descriptions
        if self.provider == "gemini" and len(frame_bytes_list) > 1:
            return self._gemini_describe_video_frames(
                frame_bytes_list, system_prompt, effective_user
            )
        else:
            # Universal fallback: describe each frame, then synthesise
            return self._multi_frame_describe_fallback(
                frame_bytes_list, system_prompt, effective_user
            )

    # ───────────────────── Provider Helpers ─────────────────────

    @staticmethod
    def _detect_mime_type(image_bytes: bytes) -> str:
        """Detect image MIME type from the first few bytes of image data."""
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if image_bytes[:4] == b"GIF8":
            return "image/gif"
        if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return "image/jpeg"

    def _report_usage_async(
        self,
        service_type: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> None:
        """Report usage asynchronously if hook is set."""
        if not self._report_usage:
            return

        try:
            event = UsageEventData(
                service_type=service_type,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
            )
            # Schedule async reporting
            asyncio.get_event_loop().call_soon(
                lambda: asyncio.create_task(self._report_usage(event))
            )
        except Exception as e:
            logger.warning(f"[VLM] Failed to report usage: {e}")

    def _gemini_describe_video_frames(
        self, frame_bytes_list: list[bytes], sys: str | None, usr: str
    ) -> str:
        """Gemini-specific multi-image frame analysis in a single API call."""
        result = self._gemini_client.generate_multimodal(
            self.model,
            text=usr,
            image_bytes_list=frame_bytes_list,
            system_prompt=sys,
            temperature=self.temperature,
            json_mode=False,
        )
        tokens_used = result.get("tokens_used", 0)
        if tokens_used:
            self._set_token_count(self._get_token_count() + billable_tokens(result))
        return re.sub(self._CODE_BLOCK_RE, "", result.get("content", "").strip())

    def _multi_frame_describe_fallback(
        self, frame_bytes_list: list[bytes], system_prompt: str, user_prompt: str
    ) -> str:
        """Describe each frame individually, then synthesise into a narrative."""
        frame_descriptions = []
        for i, fb in enumerate(frame_bytes_list):
            desc = self.describe_image_bytes(
                fb,
                system_prompt=f"Frame {i + 1} of {len(frame_bytes_list)}: Describe what you see.",
                user_prompt=user_prompt,
                log_response=False,
            )
            frame_descriptions.append(f"[Frame {i + 1}]: {desc}")

        synthesis_prompt = (
            "You received descriptions of video keyframes. Write a coherent video summary:\n\n"
            + "\n".join(frame_descriptions)
        )
        synthesis = self.describe_image_bytes(
            frame_bytes_list[-1],  # anchor with last frame for context
            system_prompt=system_prompt,
            user_prompt=synthesis_prompt,
            log_response=True,
        )
        return synthesis

    def _openai_describe_bytes(
        self, image_bytes: bytes, sys: str | None, usr: str, json_mode: bool = True
    ) -> Dict[str, Any]:
        """OpenAI/Grok vision request with automatic prompt caching metrics."""
        img_b64 = base64.b64encode(image_bytes).decode()
        mime_type = self._detect_mime_type(image_bytes)
        messages: list[Dict[str, Any]] = []
        if sys:
            messages.append({"role": "system", "content": sys})
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": usr},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{img_b64}"},
                    },
                ],
            }
        )
        # Newer OpenAI models (o1, o3, o4, gpt-5, etc.) require
        # 'max_completion_tokens' instead of the legacy 'max_tokens' parameter.
        request_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if json_mode:
            request_kwargs["response_format"] = {"type": "json_object"}
        model_lower = (self.model or "").lower()
        uses_max_completion_tokens = (
            model_lower.startswith("o1")
            or model_lower.startswith("o3")
            or model_lower.startswith("o4")
            or model_lower.startswith("gpt-5")
        )
        if uses_max_completion_tokens:
            request_kwargs["max_completion_tokens"] = 2048
        else:
            request_kwargs["max_tokens"] = 2048

        response = self.client.chat.completions.create(**request_kwargs)
        if not response.choices:
            raise ValueError(f"VLM provider returned no choices (model={self.model!r})")
        content = (response.choices[0].message.content or "").strip()
        token_count_input = response.usage.prompt_tokens
        token_count_output = response.usage.completion_tokens
        total_tokens = token_count_input + token_count_output

        # Extract cached tokens
        cached_tokens = 0
        prompt_tokens_details = getattr(response.usage, "prompt_tokens_details", None)
        if prompt_tokens_details:
            cached_tokens = getattr(prompt_tokens_details, "cached_tokens", 0) or 0

        # Record cache metrics
        config = get_cache_config()
        metrics = get_cache_metrics()
        if cached_tokens > 0:
            logger.info(
                f"[CACHE] OpenAI VLM cache hit: {cached_tokens}/{token_count_input} tokens from cache"
            )
            metrics.record_hit(
                "openai",
                "automatic_vlm",
                cached_tokens=cached_tokens,
                total_tokens=token_count_input,
            )
        elif sys and len(sys) >= config.min_cache_tokens:
            metrics.record_miss(
                "openai", "automatic_vlm", total_tokens=token_count_input
            )

        # Report usage via hook (use actual provider name, e.g. "grok", "minimax")
        self._report_usage_async(
            f"vlm_{self.provider}",
            self.provider,
            self.model,
            token_count_input,
            token_count_output,
            cached_tokens,
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or "",
            "cached_tokens": cached_tokens,
        }

    def _ollama_describe_bytes(
        self, image_bytes: bytes, sys: str | None, usr: str
    ) -> Dict[str, Any]:
        """Remote Ollama vision request."""
        img_b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "model": self.model,
            "prompt": usr,
            "images": [img_b64],
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        if sys:
            payload["system"] = sys
        url: str = f"{self.remote_url.rstrip('/')}/api/generate"
        r = requests.post(url, json=payload, timeout=600)
        r.raise_for_status()
        result = r.json()
        content = result.get("response", "").strip()
        token_count_input = result.get("prompt_eval_count", 0)
        token_count_output = result.get("eval_count", 0)
        total_tokens = token_count_input + token_count_output

        return {"tokens_used": total_tokens or 0, "content": content or ""}

    def _gemini_describe_bytes(
        self, image_bytes: bytes, sys: str | None, usr: str
    ) -> Dict[str, Any]:
        """Gemini vision request with implicit caching metrics."""
        if not self._gemini_client:
            raise RuntimeError("Gemini client was not initialised.")

        result = self._gemini_client.generate_multimodal(
            self.model,
            text=usr,
            image_bytes_list=[image_bytes],
            system_prompt=sys,
            temperature=self.temperature,
            json_mode=False,
        )

        # Record cache metrics
        cached_tokens = result.get("cached_tokens", 0)
        token_count_input = result.get("prompt_tokens", 0)
        token_count_output = result.get("completion_tokens", 0)
        config = get_cache_config()
        metrics = get_cache_metrics()

        if cached_tokens > 0:
            logger.info(
                f"[CACHE] Gemini VLM implicit cache hit: {cached_tokens}/{token_count_input} tokens from cache"
            )
            metrics.record_hit(
                "gemini",
                "implicit_vlm",
                cached_tokens=cached_tokens,
                total_tokens=token_count_input,
            )
        elif sys and len(sys) >= config.min_cache_tokens:
            metrics.record_miss(
                "gemini", "implicit_vlm", total_tokens=token_count_input
            )

        # Report usage via hook
        self._report_usage_async(
            "vlm_gemini",
            "gemini",
            self.model,
            token_count_input,
            token_count_output,
            cached_tokens,
        )

        return result

    def _byteplus_describe_bytes(
        self, image_bytes: bytes, sys: str | None, usr: str
    ) -> Dict[str, Any]:
        """BytePlus vision request."""
        img_b64 = base64.b64encode(image_bytes).decode()
        mime_type = self._detect_mime_type(image_bytes)
        messages: list[Dict[str, Any]] = []
        if sys:
            messages.append({"role": "system", "content": sys})

        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": usr},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{img_b64}"},
                    },
                ],
            }
        )

        url = f"{self.byteplus_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": 2048,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        response = requests.post(url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        result = response.json()

        choices = result.get("choices", [])
        if choices:
            content = (
                choices[0].get("message", {}).get("content")
                or choices[0].get("delta", {}).get("content", "")
                or ""
            ).strip()
            total_tokens = result.get("usage", {}).get("total_tokens", 0)

            return {"tokens_used": total_tokens or 0, "content": content or ""}

        return {"tokens_used": 0, "content": ""}

    def _anthropic_describe_bytes(
        self, image_bytes: bytes, sys: str | None, usr: str
    ) -> Dict[str, Any]:
        """Anthropic vision request with ephemeral caching metrics."""
        if not self._anthropic_client:
            raise RuntimeError("Anthropic client was not initialised.")

        img_b64 = base64.b64encode(image_bytes).decode()
        config = get_cache_config()

        media_type = self._detect_mime_type(image_bytes)

        message_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": img_b64,
                },
            },
            {
                "type": "text",
                "text": usr,
            },
        ]

        message_kwargs = {
            "model": self.model,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": message_content}],
        }

        if sys:
            if len(sys) >= config.min_cache_tokens:
                message_kwargs["system"] = [
                    {
                        "type": "text",
                        "text": sys,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                message_kwargs["system"] = sys

        message_kwargs["temperature"] = self.temperature

        response = self._anthropic_client.messages.create(**message_kwargs)

        content = ""
        for block in response.content:
            if block.type == "text":
                content += block.text

        content = content.strip()

        # Anthropic reports input_tokens as non-cached input only.
        # Total input = input_tokens + cache_creation + cache_read
        base_input = response.usage.input_tokens
        token_count_output = response.usage.output_tokens
        cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
        token_count_input = base_input + cache_creation + cache_read
        total_tokens = token_count_input + token_count_output
        cached_tokens = cache_read

        # Record cache metrics
        metrics = get_cache_metrics()
        if cache_read > 0:
            logger.info(
                f"[CACHE] Anthropic VLM cache hit: {cache_read}/{token_count_input} tokens from cache"
            )
            metrics.record_hit(
                "anthropic",
                "ephemeral_vlm",
                cached_tokens=cache_read,
                total_tokens=token_count_input,
            )
        elif cache_creation > 0:
            logger.info(
                f"[CACHE] Anthropic VLM cache created: {cache_creation} tokens cached"
            )
            metrics.record_miss(
                "anthropic", "ephemeral_vlm", total_tokens=token_count_input
            )
        elif sys and len(sys) >= config.min_cache_tokens:
            metrics.record_miss(
                "anthropic", "ephemeral_vlm", total_tokens=token_count_input
            )

        # Report usage via hook
        self._report_usage_async(
            "vlm_anthropic",
            "anthropic",
            self.model,
            token_count_input,
            token_count_output,
            cached_tokens,
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or "",
            "cached_tokens": cached_tokens,
        }

    # ─────────── Bedrock model capability detection ───────────────────

    _BEDROCK_CACHE_PREFIXES = (
        "anthropic.",
        "us.anthropic.",
        "eu.anthropic.",
        "ap.anthropic.",
    )

    def _bedrock_model_supports_caching(self, model: str | None = None) -> bool:
        """Only Anthropic Claude models on Bedrock accept cachePoint markers."""
        model_id = model or self.model or ""
        return any(model_id.startswith(p) for p in self._BEDROCK_CACHE_PREFIXES)

    def _bedrock_describe_bytes(
        self, image_bytes: bytes, sys: str | None, usr: str
    ) -> Dict[str, Any]:
        """AWS Bedrock vision request via the Converse API.

        Converse supports vision for Claude (and Nova / Llama 3.2 vision)
        models on Bedrock with a unified format. cachePoint is only attached
        for Claude — other models would reject it.
        """
        if not self._bedrock_client:
            raise RuntimeError("Bedrock client was not initialised.")

        config = get_cache_config()

        image_format = "jpeg"
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            image_format = "png"
        elif image_bytes[:4] == b"GIF8":
            image_format = "gif"
        elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            image_format = "webp"

        message_content = [
            {"image": {"format": image_format, "source": {"bytes": image_bytes}}},
            {"text": usr},
        ]

        converse_kwargs: Dict[str, Any] = {
            "modelId": self.model,
            "messages": [{"role": "user", "content": message_content}],
            "inferenceConfig": {
                "maxTokens": 2048,
                "temperature": self.temperature,
            },
        }

        if sys:
            use_cache = (
                len(sys) >= config.min_cache_tokens
                and self._bedrock_model_supports_caching()
            )
            if use_cache:
                converse_kwargs["system"] = [
                    {"text": sys},
                    {"cachePoint": {"type": "default"}},
                ]
            else:
                converse_kwargs["system"] = [{"text": sys}]

        response = self._bedrock_client.converse(**converse_kwargs)

        output_message = response.get("output", {}).get("message", {})
        content_blocks = output_message.get("content", []) or []
        content = "".join(
            block.get("text", "") for block in content_blocks if "text" in block
        ).strip()

        usage = response.get("usage", {}) or {}
        token_count_input = int(usage.get("inputTokens", 0) or 0)
        token_count_output = int(usage.get("outputTokens", 0) or 0)
        total_tokens = token_count_input + token_count_output
        cached_tokens = 0

        if self._bedrock_model_supports_caching():
            # Official Converse response uses `cacheReadInputTokens` /
            # `cacheWriteInputTokens` (no "Count" suffix) per the API
            # reference. The "...TokenCount" variants are tolerated as a
            # defensive fallback for older SDK builds.
            cache_read = int(
                usage.get("cacheReadInputTokens")
                or usage.get("cacheReadInputTokenCount")
                or 0
            )
            cache_write = int(
                usage.get("cacheWriteInputTokens")
                or usage.get("cacheWriteInputTokenCount")
                or 0
            )
            cached_tokens = cache_read + cache_write

            metrics = get_cache_metrics()
            if cache_read > 0:
                logger.info(
                    f"[CACHE] Bedrock VLM cache hit: {cache_read}/{token_count_input} tokens from cache"
                )
                metrics.record_hit(
                    "bedrock",
                    "cachepoint_vlm",
                    cached_tokens=cache_read,
                    total_tokens=token_count_input,
                )
            elif cache_write > 0:
                logger.info(
                    f"[CACHE] Bedrock VLM cache created: {cache_write} tokens cached"
                )
                metrics.record_miss(
                    "bedrock", "cachepoint_vlm", total_tokens=token_count_input
                )
            elif sys and len(sys) >= config.min_cache_tokens:
                metrics.record_miss(
                    "bedrock", "cachepoint_vlm", total_tokens=token_count_input
                )

        self._report_usage_async(
            "vlm_bedrock",
            "bedrock",
            self.model,
            token_count_input,
            token_count_output,
            cached_tokens,
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or "",
            "cached_tokens": cached_tokens,
        }
