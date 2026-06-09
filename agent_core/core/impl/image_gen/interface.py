# -*- coding: utf-8 -*-
"""
Image generation interface for agent_core.

Supports OpenAI (gpt-image-2) and Gemini (gemini-*-image-preview) providers.
Provider logic lives here; the action (generate_image.py) just delegates.

Mirrors VLMInterface structure — constructor, hooks, dispatch. Unlike VLM there
is intentionally no in-place reinitialize(): provider switches build a fresh
instance via agent_base.reinitialize_image_gen() and swap it in only on success,
so an in-flight generate_image() keeps using its old instance/client until done.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import tempfile
import urllib.request as _urllib_request
from datetime import datetime
from typing import Any, Dict, List, Optional

from agent_core.core.hooks import (
    GetTokenCountHook,
    ReportUsageHook,
    SetTokenCountHook,
    UsageEventData,
)
from agent_core.utils.logger import logger

try:
    from PIL import Image as _PilImage  # type: ignore[import]
except ImportError:
    _PilImage = None  # type: ignore[assignment]

# OpenAI supports only three canvas sizes. Document the closest-fit mapping so
# callers understand the constraint at a glance.
#
# True 16:9 (1920×1080) and 9:16 are not available. The values below use the
# widest/tallest canvases OpenAI exposes; warn at runtime when the mismatch
# matters (resolution ≥ 2K or aspect ratio 16:9/9:16).
_OPENAI_ASPECT_MAP: Dict[str, str] = {
    "1:1": "1024x1024",
    "3:4": "1024x1536",
    "4:3": "1536x1024",
    "9:16": "1024x1536",  # nearest fit — true 9:16 not supported
    "16:9": "1536x1024",  # nearest fit — true 16:9 not supported
}
_OPENAI_INEXACT_RATIOS = {"16:9", "9:16"}

_OPENAI_QUALITY_MAP: Dict[str, str] = {
    "1K": "medium",
    "2K": "high",
    "4K": "high",  # API tops out at 1536px; warn caller
}

# ── Error message catalog (provider-keyed, English) ──────────────────────────
# Used to build human-readable RuntimeErrors that flow back through the
# action-selection loop, matching VLMInterface's raise-don't-return pattern.
_ERR: Dict[str, Dict[str, str]] = {
    "openai": {
        "quota": "OpenAI API rate limit or quota exceeded",
        "invalid_key": "Invalid OpenAI API key — verify your key in settings.",
        "content_policy": "Request blocked by OpenAI content policy — modify your prompt.",
        "model_not_found": (
            "OpenAI model not available — ensure your account has access to gpt-image-2."
        ),
        "generic": "OpenAI image generation failed",
    },
    "gemini": {
        "quota": "Gemini API rate limit or quota exceeded",
        "invalid_key": "Invalid Gemini API key — verify your Google API key in settings.",
        "content_policy": "Request blocked by Gemini safety filters — modify your prompt.",
        "model_not_found": (
            "Gemini model not available — ensure your account has access to the "
            "image generation preview model."
        ),
        "generic": "Gemini image generation failed",
    },
}


def _classify_error(provider: str, exc: Exception) -> str:
    """Map a raw exception message to a catalog entry for the given provider."""
    msg = str(exc).lower()
    catalog = _ERR.get(provider, _ERR["openai"])
    if (
        "quota" in msg
        or "rate" in msg
        or "billing" in msg
        or "insufficient_quota" in msg
    ):
        return catalog["quota"]
    if "invalid" in msg and "key" in msg:
        return catalog["invalid_key"]
    if "content_policy" in msg or "safety" in msg or "blocked" in msg:
        return catalog["content_policy"]
    if "not found" in msg or "404" in msg or "not available" in msg:
        return catalog["model_not_found"]
    # Do NOT include the raw exception — SDK error messages can contain API key fragments.
    return catalog["generic"]


# ── File-path helpers ─────────────────────────────────────────────────────────


def _build_save_path(
    output_path: str,
    timestamp: str,
    index: int,
    total: int,
) -> str:
    if output_path:
        if total > 1:
            base, ext = os.path.splitext(output_path)
            ext = ext or ".png"
            return f"{base}_{index + 1}{ext}"
        save_path = output_path
        if not os.path.splitext(save_path)[1]:
            save_path += ".png"
        return save_path
    return os.path.join(
        tempfile.gettempdir(), f"generated_image_{timestamp}_{index + 1}.png"
    )


def _save_pil_image(pil_image: Any, save_path: str) -> None:
    parent = os.path.dirname(os.path.abspath(save_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    pil_image.save(save_path, "PNG")


def _to_pil_image(img_data: Any) -> Any:
    """Convert raw image data (bytes or base64 str) to a PIL Image."""
    if isinstance(img_data, str):
        return _PilImage.open(io.BytesIO(base64.b64decode(img_data)))
    if isinstance(img_data, bytes):
        return _PilImage.open(io.BytesIO(img_data))
    return img_data


# ── Main interface ────────────────────────────────────────────────────────────


class ImageGenInterface:
    """Image generation interface with multi-provider support.

    Supports OpenAI (gpt-image-2) and Gemini image generation models.
    Uses hooks for state access and usage reporting, mirroring VLMInterface.

    Args:
        provider: Provider name ("openai", "gemini").
        model: Model name override (None = use registry default).
        api_key: API key (required for openai/gemini).
        base_url: Base URL override (unused by image providers currently).
        deferred: If True, allow deferred initialization without raising.
        get_token_count: Hook to read current token count from state.
        set_token_count: Hook to write token count to state.
        report_usage: Optional hook to report usage for cost tracking.
    """

    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        deferred: bool = False,
        get_token_count: Optional[GetTokenCountHook] = None,
        set_token_count: Optional[SetTokenCountHook] = None,
        report_usage: Optional[ReportUsageHook] = None,
    ) -> None:
        self.provider = provider
        self._initialized = False
        self._deferred = deferred
        self._init_api_key = api_key
        self._init_base_url = base_url

        self._get_token_count = get_token_count or (lambda: 0)
        self._set_token_count = set_token_count or (lambda x: None)
        self._report_usage = report_usage

        # Defer import to avoid circular dependency (same pattern as VLMInterface)
        from app.models.factory import ModelFactory
        from app.models.types import InterfaceType

        ctx = ModelFactory.create(
            provider=provider,
            interface=InterfaceType.IMAGE_GEN,
            model_override=model,
            api_key=api_key,
            base_url=base_url,
            deferred=deferred,
        )
        self.provider = ctx["provider"]
        self.model = ctx["model"]
        self.client = ctx["client"]  # OpenAI client or None
        self._gemini_client = ctx["gemini_client"]
        self._initialized = ctx.get("initialized", False)
        try:
            self._main_loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_event_loop()
        except RuntimeError:
            self._main_loop = None

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def _report_usage_async(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> None:
        """Report image-generation usage if the hook is set (mirrors VLM).

        Best-effort: scheduling onto the running loop can fail when invoked
        from a worker thread without one, in which case the usage is dropped
        with a warning rather than breaking generation.
        """
        if not self._report_usage:
            return
        try:
            event = UsageEventData(
                service_type="image_gen",
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
            )
            if self._main_loop is not None:
                self._main_loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._report_usage(event))
                )
        except Exception as e:
            logger.warning(f"[IMAGE_GEN] Failed to report usage: {e}")

    # ─────────────────────────── Public API ──────────────────────────────────

    def generate_image(
        self,
        prompt: str,
        resolution: str = "1K",
        aspect_ratio: str = "1:1",
        number_of_images: int = 1,
        output_path: str = "",
        negative_prompt: str = "",
        reference_images: Optional[List[str]] = None,
        safety_filter_level: str = "block_medium_and_above",
    ) -> List[str]:
        """Generate image(s) from a text prompt.

        Args:
            prompt: Text description of the image to generate.
            resolution: "1K", "2K", or "4K".
            aspect_ratio: "1:1", "3:4", "4:3", "9:16", or "16:9".
            number_of_images: Number of images to generate (1–4).
            output_path: Absolute path for the output file. Timestamped temp
                path used when empty. For multiple images the index is appended
                before the extension.
            negative_prompt: Elements to avoid (Gemini native; appended to
                prompt for OpenAI which has no dedicated parameter).
            reference_images: List of absolute paths to reference images.
                **Provider semantics differ**: Gemini treats these as style
                guidance; OpenAI's images.edit treats them as compositional /
                mask inputs. Warn users accordingly.
            safety_filter_level: Gemini safety threshold
                ("block_none", "block_only_high", "block_medium_and_above",
                "block_low_and_above"). Ignored by OpenAI.

        Returns:
            List of absolute file paths to the generated PNG files.

        Raises:
            RuntimeError: If the provider is unsupported or generation fails.
        """
        if _PilImage is None:
            raise RuntimeError(
                "Pillow is required for image generation. "
                "Install with: pip install Pillow"
            )

        if not prompt:
            raise ValueError("prompt is required")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ref = reference_images or []

        if self.provider == "openai":
            paths = self._openai_generate(
                prompt=prompt,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                number_of_images=number_of_images,
                output_path=output_path,
                negative_prompt=negative_prompt,
                reference_images=ref,
                timestamp=timestamp,
            )
        elif self.provider == "gemini":
            paths = self._gemini_generate(
                prompt=prompt,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                number_of_images=number_of_images,
                output_path=output_path,
                negative_prompt=negative_prompt,
                reference_images=ref,
                safety_filter_level=safety_filter_level,
                timestamp=timestamp,
            )
        else:
            raise RuntimeError(
                f"Provider '{self.provider}' does not support image generation. "
                "Set image_gen_provider to 'openai' or 'gemini' in settings.json."
            )

        logger.info(
            f"[IMAGE_GEN] Generated {len(paths)} image(s) via {self.provider} "
            f"(model={self.model})"
        )
        return paths

    async def generate_image_async(self, **kwargs) -> List[str]:
        """Async wrapper — runs generate_image in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.generate_image(**kwargs))

    # ──────────────────────── OpenAI provider ────────────────────────────────

    def _openai_generate(
        self,
        *,
        prompt: str,
        resolution: str,
        aspect_ratio: str,
        number_of_images: int,
        output_path: str,
        negative_prompt: str,
        reference_images: List[str],
        timestamp: str,
    ) -> List[str]:
        size = _OPENAI_ASPECT_MAP.get(aspect_ratio, "1024x1024")
        if aspect_ratio in _OPENAI_INEXACT_RATIOS:
            logger.warning(
                f"[IMAGE_GEN] OpenAI does not support true {aspect_ratio}. "
                f"Using closest available canvas {size} (~3:2 / ~2:3)."
            )

        quality = _OPENAI_QUALITY_MAP.get(resolution, "medium")
        if resolution == "4K":
            logger.warning(
                "[IMAGE_GEN] OpenAI image generation tops out at 1536px; "
                "'4K' is mapped to quality='high' (no true 4K output)."
            )

        full_prompt = prompt
        if negative_prompt:
            full_prompt += f"\n\nAvoid: {negative_prompt}"

        if reference_images:
            logger.warning(
                "[IMAGE_GEN] OpenAI reference_images uses images.edit(), which treats "
                "inputs as compositional/mask data — not style guidance as in Gemini. "
                "Output may differ significantly from the Gemini provider."
            )

        try:
            valid_refs = [p for p in reference_images if os.path.isfile(p)]
            if valid_refs:
                # Open progressively into a list so a mid-loop failure still
                # closes the handles we already opened.
                image_files: List[Any] = []
                try:
                    for p in valid_refs:
                        image_files.append(open(p, "rb"))
                    response = self.client.images.edit(
                        model=self.model,
                        image=image_files,
                        prompt=full_prompt,
                        n=number_of_images,
                        size=size,
                        quality=quality,
                    )
                finally:
                    for f in image_files:
                        f.close()
            else:
                response = self.client.images.generate(
                    model=self.model,
                    prompt=full_prompt,
                    n=number_of_images,
                    size=size,
                    quality=quality,
                )
        except Exception as exc:
            raise RuntimeError(_classify_error("openai", exc)) from exc

        usage = getattr(response, "usage", None)
        if usage is not None:
            self._report_usage_async(
                provider="openai",
                model=self.model,
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
            )

        images_bytes: List[bytes] = []
        for item in response.data:
            if item.b64_json:
                images_bytes.append(base64.b64decode(item.b64_json))
            elif item.url:
                with _urllib_request.urlopen(item.url, timeout=30) as r:
                    images_bytes.append(r.read())

        if not images_bytes:
            raise RuntimeError(
                "OpenAI returned no image data — try rephrasing your prompt."
            )

        paths: List[str] = []
        for i, raw in enumerate(images_bytes[:number_of_images]):
            save_path = _build_save_path(output_path, timestamp, i, len(images_bytes))
            pil_image = _PilImage.open(io.BytesIO(raw))
            _save_pil_image(pil_image, save_path)
            paths.append(save_path)

        return paths

    # ──────────────────────── Gemini provider ────────────────────────────────

    def _gemini_generate(
        self,
        *,
        prompt: str,
        resolution: str,
        aspect_ratio: str,
        number_of_images: int,
        output_path: str,
        negative_prompt: str,
        reference_images: List[str],
        safety_filter_level: str,
        timestamp: str,
    ) -> List[str]:
        if not self._gemini_client:
            raise RuntimeError(
                "Gemini API key is not configured. "
                "Set 'image_gen_provider' to 'openai' or add a Google API key in settings."
            )

        # Reference images as (bytes, mime) inline parts (style guidance)
        ref_parts: List[Any] = []
        for ref_path in reference_images:
            if not os.path.isfile(ref_path):
                continue
            try:
                with open(ref_path, "rb") as f:
                    data = f.read()
                ext = os.path.splitext(ref_path)[1].lower()
                mime = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".webp": "image/webp",
                }.get(ext, "image/png")
                ref_parts.append((data, mime))
            except Exception as exc:
                logger.warning(
                    f"[IMAGE_GEN] Skipping unreadable reference image '{ref_path}': {exc}"
                )

        gen_prompt = (
            f"Generate an image based on the following description:\n\n{prompt}"
        )
        gen_prompt += f"\n\nImage specifications:\n- Resolution: {resolution}\n- Aspect ratio: {aspect_ratio}\n- Number of variations: {number_of_images}"
        if negative_prompt:
            gen_prompt += f"\n- Avoid: {negative_prompt}"

        _threshold_map = {
            "block_only_high": "BLOCK_ONLY_HIGH",
            "block_medium_and_above": "BLOCK_MEDIUM_AND_ABOVE",
            "block_low_and_above": "BLOCK_LOW_AND_ABOVE",
        }
        safety_settings = None
        if safety_filter_level != "block_none":
            threshold = _threshold_map.get(
                safety_filter_level, "BLOCK_MEDIUM_AND_ABOVE"
            )
            safety_settings = [
                {"category": cat, "threshold": threshold}
                for cat in (
                    "HARM_CATEGORY_HARASSMENT",
                    "HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "HARM_CATEGORY_DANGEROUS_CONTENT",
                )
            ]

        try:
            # One client for the whole Gemini surface: the shared REST
            # GeminiClient handles image generation too (no google-genai SDK —
            # see GeminiClient's module docstring for why it avoids the SDK).
            result = self._gemini_client.generate_image(
                self.model,
                prompt=gen_prompt,
                reference_images=ref_parts,
                image_size=resolution,
                safety_settings=safety_settings,
            )
        except Exception as exc:
            raise RuntimeError(_classify_error("gemini", exc)) from exc

        usage_md = result.get("usage_metadata") or {}
        if usage_md:
            self._report_usage_async(
                provider="gemini",
                model=self.model,
                input_tokens=usage_md.get("promptTokenCount", 0) or 0,
                output_tokens=usage_md.get("candidatesTokenCount", 0) or 0,
                cached_tokens=usage_md.get("cachedContentTokenCount", 0) or 0,
            )

        images_data = result.get("images") or []

        if not images_data:
            block_reason = result.get("block_reason")
            if block_reason:
                raise RuntimeError(
                    f"Gemini blocked the request (safety filter: {block_reason}). "
                    "Try modifying your prompt or adjusting safety_filter_level."
                )
            raise RuntimeError(
                "Gemini returned no image data — try rephrasing your prompt or "
                "check that your API key has access to image generation."
            )

        paths: List[str] = []
        for i, img_data in enumerate(images_data[:number_of_images]):
            save_path = _build_save_path(output_path, timestamp, i, len(images_data))
            pil_image = _to_pil_image(img_data)
            _save_pil_image(pil_image, save_path)
            paths.append(save_path)

        return paths
