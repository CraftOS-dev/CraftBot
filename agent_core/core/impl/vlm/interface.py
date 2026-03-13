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
from typing import Any, Awaitable, Callable, Dict, Optional

import requests

from agent_core.core.impl.llm.cache import get_cache_config, get_cache_metrics
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

        # Hooks for runtime-specific behavior
        self._get_token_count = get_token_count or (lambda: 0)
        self._set_token_count = set_token_count or (lambda x: None)
        self._report_usage = report_usage

        # Defer import to avoid circular dependency
        from app.models.factory import ModelFactory
        from app.models.types import InterfaceType

        ctx = ModelFactory.create(
            provider=provider,
            interface=InterfaceType.VLM,
            model_override=model,
            deferred=deferred,
        )

        self.model = ctx["model"]
        self.client = ctx["client"]
        self._gemini_client = ctx["gemini_client"]
        self.remote_url = ctx["remote_url"]
        self._anthropic_client = ctx.get("anthropic_client")
        self._initialized = ctx.get("initialized", False)

        if ctx["byteplus"]:
            self.api_key = ctx["byteplus"]["api_key"]
            self.byteplus_base_url = ctx["byteplus"]["base_url"]

    @property
    def is_initialized(self) -> bool:
        """Check if the VLM client is properly initialized."""
        return self._initialized

    def reinitialize(self, provider: Optional[str] = None) -> bool:
        """Reinitialize the VLM client with current environment variables.

        Args:
            provider: Optional provider override. If None, uses current provider.

        Returns:
            True if initialization was successful, False otherwise.
        """
        from app.models.factory import ModelFactory
        from app.models.types import InterfaceType

        target_provider = provider or self.provider
        try:
            logger.info(f"[VLM] Reinitializing with provider: {target_provider}")
            ctx = ModelFactory.create(
                provider=target_provider,
                interface=InterfaceType.VLM,
                model_override=None,
                deferred=False,
            )

            self.provider = ctx["provider"]
            self.model = ctx["model"]
            self.client = ctx["client"]
            self._gemini_client = ctx["gemini_client"]
            self.remote_url = ctx["remote_url"]
            self._anthropic_client = ctx.get("anthropic_client")
            self._initialized = ctx.get("initialized", False)

            if ctx["byteplus"]:
                self.api_key = ctx["byteplus"]["api_key"]
                self.byteplus_base_url = ctx["byteplus"]["base_url"]

            logger.info(f"[VLM] Reinitialized successfully with provider: {self.provider}, model: {self.model}")
            return self._initialized
        except EnvironmentError as e:
            logger.warning(f"[VLM] Failed to reinitialize - missing API key: {e}")
            return False
        except Exception as e:
            logger.error(f"[VLM] Failed to reinitialize - unexpected error: {e}", exc_info=True)
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

            if self.provider == "openai":
                response = self._openai_describe_bytes(image_bytes, system_prompt, user_prompt)
            elif self.provider == "remote":
                response = self._ollama_describe_bytes(image_bytes, system_prompt, user_prompt)
            elif self.provider == "gemini":
                response = self._gemini_describe_bytes(image_bytes, system_prompt, user_prompt)
            elif self.provider == "byteplus":
                response = self._byteplus_describe_bytes(image_bytes, system_prompt, user_prompt)
            elif self.provider == "anthropic":
                response = self._anthropic_describe_bytes(image_bytes, system_prompt, user_prompt)
            else:
                raise RuntimeError(f"Unknown provider {self.provider!r}")

            cleaned = re.sub(self._CODE_BLOCK_RE, "", response.get("content", "").strip())

            # Update token count via hook
            tokens_used = response.get("tokens_used", 0)
            if tokens_used:
                current_count = self._get_token_count()
                self._set_token_count(current_count + tokens_used)

            if log_response:
                logger.info(f"[LLM RECV] {cleaned}")
            return cleaned
        except Exception as e:
            logger.error(f"[ERROR] {e}")
            return ""

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

    # ───────────────────── Provider Helpers ─────────────────────

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

    def _openai_describe_bytes(self, image_bytes: bytes, sys: str | None, usr: str) -> Dict[str, Any]:
        """OpenAI vision request with automatic prompt caching metrics."""
        img_b64 = base64.b64encode(image_bytes).decode()
        messages: list[Dict[str, Any]] = []
        if sys:
            messages.append({"role": "system", "content": sys})
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": usr},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            }
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=2048,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content.strip()
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
            logger.info(f"[CACHE] OpenAI VLM cache hit: {cached_tokens}/{token_count_input} tokens from cache")
            metrics.record_hit("openai", "automatic_vlm", cached_tokens=cached_tokens, total_tokens=token_count_input)
        elif sys and len(sys) >= config.min_cache_tokens:
            metrics.record_miss("openai", "automatic_vlm", total_tokens=token_count_input)

        # Report usage via hook
        self._report_usage_async(
            "vlm_openai", "openai", self.model,
            token_count_input, token_count_output, cached_tokens
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or "",
            "cached_tokens": cached_tokens,
        }

    def _ollama_describe_bytes(self, image_bytes: bytes, sys: str | None, usr: str) -> Dict[str, Any]:
        """Remote Ollama vision request."""
        img_b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "model": self.model,
            "prompt": usr,
            "system": sys,
            "images": [img_b64],
            "stream": False,
            "temperature": self.temperature,
        }
        url: str = f"{self.remote_url.rstrip('/')}/vision"
        r = requests.post(url, json=payload, timeout=600)
        r.raise_for_status()
        content = r.json().get("response", "").strip()
        total_tokens = r.json().get("usage", {}).get("total_tokens", 0)

        return {
            "tokens_used": total_tokens or 0,
            "content": content or ""
        }

    def _gemini_describe_bytes(self, image_bytes: bytes, sys: str | None, usr: str) -> Dict[str, Any]:
        """Gemini vision request with implicit caching metrics."""
        if not self._gemini_client:
            raise RuntimeError("Gemini client was not initialised.")

        result = self._gemini_client.generate_multimodal(
            self.model,
            text=usr,
            image_bytes=image_bytes,
            system_prompt=sys,
            temperature=self.temperature,
            json_mode=True,
        )

        # Record cache metrics
        cached_tokens = result.get("cached_tokens", 0)
        token_count_input = result.get("prompt_tokens", 0)
        token_count_output = result.get("completion_tokens", 0)
        config = get_cache_config()
        metrics = get_cache_metrics()

        if cached_tokens > 0:
            logger.info(f"[CACHE] Gemini VLM implicit cache hit: {cached_tokens}/{token_count_input} tokens from cache")
            metrics.record_hit("gemini", "implicit_vlm", cached_tokens=cached_tokens, total_tokens=token_count_input)
        elif sys and len(sys) >= config.min_cache_tokens:
            metrics.record_miss("gemini", "implicit_vlm", total_tokens=token_count_input)

        # Report usage via hook
        self._report_usage_async(
            "vlm_gemini", "gemini", self.model,
            token_count_input, token_count_output, cached_tokens
        )

        return result

    def _byteplus_describe_bytes(self, image_bytes: bytes, sys: str | None, usr: str) -> Dict[str, Any]:
        """BytePlus vision request."""
        img_b64 = base64.b64encode(image_bytes).decode()
        messages: list[Dict[str, Any]] = []
        if sys:
            messages.append({"role": "system", "content": sys})

        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": usr},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            }
        )

        url = f"{self.byteplus_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": 2048,
            "response_format": {"type": "json_object"},
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

            return {
                "tokens_used": total_tokens or 0,
                "content": content or ""
            }

        return {"tokens_used": 0, "content": ""}

    def _anthropic_describe_bytes(self, image_bytes: bytes, sys: str | None, usr: str) -> Dict[str, Any]:
        """Anthropic vision request with ephemeral caching metrics."""
        if not self._anthropic_client:
            raise RuntimeError("Anthropic client was not initialised.")

        img_b64 = base64.b64encode(image_bytes).decode()
        config = get_cache_config()

        # Detect media type from image bytes
        media_type = "image/jpeg"
        if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            media_type = "image/png"
        elif image_bytes[:4] == b'GIF8':
            media_type = "image/gif"
        elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
            media_type = "image/webp"

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

        token_count_input = response.usage.input_tokens
        token_count_output = response.usage.output_tokens
        total_tokens = token_count_input + token_count_output

        cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
        cached_tokens = cache_creation + cache_read

        # Record cache metrics
        metrics = get_cache_metrics()
        if cache_read > 0:
            logger.info(f"[CACHE] Anthropic VLM cache hit: {cache_read}/{token_count_input} tokens from cache")
            metrics.record_hit("anthropic", "ephemeral_vlm", cached_tokens=cache_read, total_tokens=token_count_input)
        elif cache_creation > 0:
            logger.info(f"[CACHE] Anthropic VLM cache created: {cache_creation} tokens cached")
            metrics.record_miss("anthropic", "ephemeral_vlm", total_tokens=token_count_input)
        elif sys and len(sys) >= config.min_cache_tokens:
            metrics.record_miss("anthropic", "ephemeral_vlm", total_tokens=token_count_input)

        # Report usage via hook
        self._report_usage_async(
            "vlm_anthropic", "anthropic", self.model,
            token_count_input, token_count_output, cached_tokens
        )

        return {
            "tokens_used": total_tokens or 0,
            "content": content or "",
            "cached_tokens": cached_tokens,
        }
