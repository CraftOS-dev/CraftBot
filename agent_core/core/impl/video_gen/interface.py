# -*- coding: utf-8 -*-
"""
Video generation interface for agent_core.

Supports OpenAI (Sora 2/Pro), Gemini (Veo 3.x), and BytePlus (Seedance).
All three providers expose async/long-running generation, so the public
``generate_video()`` blocks while internally submitting + polling + downloading.

Mirrors VLMInterface / ImageGenInterface structure — constructor, hooks,
dispatch. Like image gen, there is intentionally no in-place reinitialize();
provider switches build a fresh instance via agent_base.reinitialize_video_gen()
and swap it in only on success, so in-flight generate_video() calls keep their
old instance/client until done.

The interface caps internal polling with ``poll_timeout_seconds`` (default
1500s = 25min, covering realistic generation times) but the outer
DEFAULT_ACTION_TIMEOUT (6000s) is the real ceiling.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import time
import urllib.request as _urllib_request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from agent_core.core.hooks import (
    GetTokenCountHook,
    ReportUsageHook,
    SetTokenCountHook,
    UsageEventData,
)
from agent_core.utils.logger import logger

# Default polling cadence: start tight to catch fast Seedance jobs, back off to
# avoid hammering for slow Veo jobs.
_DEFAULT_POLL_TIMEOUT = 1500  # 25 min — well under DEFAULT_ACTION_TIMEOUT (100 min)
_DEFAULT_POLL_INITIAL = 5
_DEFAULT_POLL_MAX = 15

# OpenAI Sora 2 size mapping. Sora 2 accepts portrait/landscape 720p; Sora 2 Pro
# adds 1024p and 1080p. We pick the nearest-fit canvas for the requested
# aspect_ratio × resolution combination and warn when downgrading.
_SORA_SIZES: Dict[str, Dict[str, str]] = {
    "sora-2": {
        "16:9": "1280x720",
        "9:16": "720x1280",
    },
    "sora-2-pro": {
        "16:9": "1792x1024",
        "9:16": "1024x1792",
    },
}
_SORA_VALID_SECONDS = {
    "sora-2": {4, 8, 12},
    "sora-2-pro": {10, 15, 25},
}

# Gemini Veo accepts integer durations. 1080p/4k and reference-images require 8.
_VEO_DURATION_VALID = {4, 6, 8}
_VEO_RESOLUTION_VALID = {"720p", "1080p", "4k"}
_VEO_ASPECT_VALID = {"16:9", "9:16"}
_VEO_PERSON_GEN_VALID = {"allow_all", "allow_adult", "dont_allow"}

# BytePlus Seedance accepts duration as a string flag in the content text.
# Resolution / aspect_ratio / camera_fixed / watermark also go via the
# inline text flags per the public Seedance API.
_SEEDANCE_RESOLUTION_VALID = {"480p", "720p", "1080p"}
_SEEDANCE_ASPECT_VALID = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9"}

_AUDIO_CAPABLE_PROVIDERS = {"gemini", "openai", "byteplus"}  # all three honor it


def _classify_error(provider: str, exc: Exception, model: str) -> str:
    """Render *exc* as a human-readable error string via the shared catalog.

    Import deferred to call time — agent_core must stay importable without
    the host `app` package (all app.* imports in this package are
    function-local by convention).
    """
    from app.i18n import classify_provider_error

    return classify_provider_error(exc, provider=provider, model=model)


# ── File / image helpers ─────────────────────────────────────────────────────


def _build_save_path(
    output_path: str,
    timestamp: str,
    index: int,
    total: int,
    suffix: str = ".mp4",
) -> str:
    """Pick a save path for the i-th video out of `total`."""
    if output_path:
        if total > 1:
            base, ext = os.path.splitext(output_path)
            ext = ext or suffix
            return f"{base}_{index + 1}{ext}"
        save_path = output_path
        if not os.path.splitext(save_path)[1]:
            save_path += suffix
        return save_path
    return os.path.join(
        tempfile.gettempdir(), f"generated_video_{timestamp}_{index + 1}{suffix}"
    )


def _write_bytes(path: str, data: bytes) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _read_image_for_upload(image_path: str) -> Tuple[bytes, str]:
    """Read an image from disk and return (bytes, mime). Raises if missing."""
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Reference image not found: {image_path}")
    with open(image_path, "rb") as f:
        data = f.read()
    ext = os.path.splitext(image_path)[1].lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/png")
    return data, mime


# ── Main interface ───────────────────────────────────────────────────────────


class VideoGenInterface:
    """Video generation interface with multi-provider support.

    Supports OpenAI Sora 2/Pro, Gemini Veo 3.x, and BytePlus Seedance.
    Uses hooks for state access and usage reporting, mirroring VLMInterface
    and ImageGenInterface.

    All providers run as async/long-running operations; ``generate_video()``
    blocks while internally submitting + polling + downloading.

    Args:
        provider: Provider name ("openai", "gemini", "byteplus").
        model: Model name override (None = use registry default).
        api_key: API key (required for all supported providers).
        base_url: Base URL override (used for byteplus REST endpoint).
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

        # Defer import to avoid circular dependency (same pattern as VLM/ImageGen)
        from app.models.factory import ModelFactory
        from app.models.types import InterfaceType

        ctx = ModelFactory.create(
            provider=provider,
            interface=InterfaceType.VIDEO_GEN,
            model_override=model,
            api_key=api_key,
            base_url=base_url,
            deferred=deferred,
        )
        self.provider = ctx["provider"]
        self.model = ctx["model"]
        self.client = ctx["client"]  # OpenAI client (Sora) or None
        self._gemini_client = ctx["gemini_client"]  # GeminiClient (Veo) or None
        self._byteplus = ctx["byteplus"]  # {"api_key", "base_url"} or None
        self._initialized = ctx.get("initialized", False)
        try:
            self._main_loop: Optional[asyncio.AbstractEventLoop] = (
                asyncio.get_event_loop()
            )
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
        """Report video-generation usage if the hook is set (mirrors VLM / ImageGen)."""
        if not self._report_usage:
            return
        try:
            event = UsageEventData(
                service_type="video_gen",
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
            logger.warning(f"[VIDEO_GEN] Failed to report usage: {e}")

    # ─────────────────────────── Public API ──────────────────────────────────

    def generate_video(
        self,
        prompt: str,
        duration_seconds: int = 5,
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        number_of_videos: int = 1,
        output_path: str = "",
        negative_prompt: str = "",
        reference_image: Optional[str] = None,
        last_frame: Optional[str] = None,
        reference_images: Optional[List[str]] = None,
        seed: Optional[int] = None,
        with_audio: bool = True,
        # Gemini / Veo specific
        person_generation: str = "allow_adult",
        # BytePlus / Seedance specific
        camera_fixed: bool = False,
        watermark: bool = False,
        callback_url: str = "",
        # Polling
        poll_timeout_seconds: int = _DEFAULT_POLL_TIMEOUT,
    ) -> List[str]:
        """Generate video(s) from a text prompt (blocking).

        Submits the generation job, polls until completion, downloads the
        result(s) to disk, and returns local file paths.

        Args:
            prompt: Text description of the video to generate.
            duration_seconds: Target duration in seconds. Each provider clamps
                to its supported set (Sora 2: 4/8/12; Veo: 4/6/8; Seedance: 2–12).
            aspect_ratio: "16:9", "9:16", "1:1", "4:3", "3:4", "21:9". Sora
                and Veo only support 16:9 and 9:16.
            resolution: "480p" / "720p" / "1080p" / "4k". Sora 2 standard tops
                out at 720p; Veo Lite cannot do 4k.
            number_of_videos: Number of videos (1–N, provider-capped).
            output_path: Absolute path for the output file. Timestamped temp
                path used when empty. For multiple videos the index is
                appended before the extension.
            negative_prompt: Elements to avoid (native on Veo and Seedance;
                appended to prompt for Sora which has no dedicated param).
            reference_image: Optional absolute path to a single start-frame
                image for image-to-video. Mapped to ``input_reference`` (Sora),
                ``image`` (Veo), or ``image_urls`` (Seedance).
            last_frame: Optional absolute path to an end-frame image for
                frame interpolation. Veo 3.1+ only; silently dropped elsewhere.
            reference_images: Optional list of absolute paths to additional
                style-reference images. Veo 3.1+ accepts up to 3; silently
                dropped on Sora and Seedance.
            seed: Optional deterministic seed.
            with_audio: Whether to generate audio. Honored where the
                provider exposes a request-time toggle: Seedance's
                ``generate_audio`` (2.0+ models). Veo 3.x produces native
                synchronized audio by default and has no toggle — the flag
                is ignored there (Veo 2 is silent). Sora 2 produces audio
                by default and the flag is also a no-op.
            person_generation: Veo only — "allow_all", "allow_adult", or
                "dont_allow". ``allow_all`` is geo-restricted (EU/UK/CH/MENA).
            camera_fixed: BytePlus Seedance only — lock camera position.
            watermark: BytePlus Seedance only — apply watermark to output.
            callback_url: BytePlus Seedance only — webhook for completion.
            poll_timeout_seconds: Internal polling cap (default 1500s).
                Always remains below DEFAULT_ACTION_TIMEOUT (6000s).

        Returns:
            List of absolute file paths to the generated MP4 files.

        Raises:
            RuntimeError: If the provider is unsupported, the job is blocked,
                generation fails, or polling times out.
        """
        if not prompt:
            raise ValueError("prompt is required")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        refs = reference_images or []

        if self.provider == "openai":
            paths = self._openai_generate(
                prompt=prompt,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                number_of_videos=number_of_videos,
                output_path=output_path,
                negative_prompt=negative_prompt,
                reference_image=reference_image,
                seed=seed,
                with_audio=with_audio,
                timestamp=timestamp,
                poll_timeout_seconds=poll_timeout_seconds,
            )
        elif self.provider == "gemini":
            paths = self._gemini_generate(
                prompt=prompt,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                number_of_videos=number_of_videos,
                output_path=output_path,
                negative_prompt=negative_prompt,
                reference_image=reference_image,
                last_frame=last_frame,
                reference_images=refs,
                seed=seed,
                with_audio=with_audio,
                person_generation=person_generation,
                timestamp=timestamp,
                poll_timeout_seconds=poll_timeout_seconds,
            )
        elif self.provider == "byteplus":
            paths = self._byteplus_generate(
                prompt=prompt,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                number_of_videos=number_of_videos,
                output_path=output_path,
                negative_prompt=negative_prompt,
                reference_image=reference_image,
                seed=seed,
                with_audio=with_audio,
                camera_fixed=camera_fixed,
                watermark=watermark,
                callback_url=callback_url,
                timestamp=timestamp,
                poll_timeout_seconds=poll_timeout_seconds,
            )
        else:
            raise RuntimeError(
                f"Provider '{self.provider}' does not support video generation. "
                "Set video_gen_provider to 'gemini', 'openai', or 'byteplus' in settings.json."
            )

        logger.info(
            f"[VIDEO_GEN] Generated {len(paths)} video(s) via {self.provider} "
            f"(model={self.model})"
        )
        return paths

    async def generate_video_async(self, **kwargs) -> List[str]:
        """Async wrapper — runs generate_video in a thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.generate_video(**kwargs))

    # ──────────────────────── OpenAI / Sora 2 ────────────────────────────────

    def _openai_generate(
        self,
        *,
        prompt: str,
        duration_seconds: int,
        aspect_ratio: str,
        resolution: str,
        number_of_videos: int,
        output_path: str,
        negative_prompt: str,
        reference_image: Optional[str],
        seed: Optional[int],
        with_audio: bool,
        timestamp: str,
        poll_timeout_seconds: int,
    ) -> List[str]:
        # Sora 2 audio is on by default and not configurable per-request; the
        # `with_audio=False` flag is silently honored as a no-op signal.
        if not with_audio:
            logger.info(
                "[VIDEO_GEN] OpenAI Sora produces audio by default; "
                "with_audio=False is a no-op."
            )

        # Map aspect_ratio + resolution to the closest Sora canvas. If the
        # caller passes an unsupported aspect_ratio (Sora has only 16:9 / 9:16),
        # default to 16:9 and warn.
        size_map = _SORA_SIZES.get(self.model, _SORA_SIZES["sora-2"])
        if aspect_ratio not in size_map:
            logger.warning(
                f"[VIDEO_GEN] Sora does not support aspect_ratio={aspect_ratio}. "
                "Defaulting to 16:9."
            )
            aspect_ratio = "16:9"
        size = size_map[aspect_ratio]
        if resolution not in {"720p", "1024p", "1080p"}:
            logger.warning(
                f"[VIDEO_GEN] Sora ignores resolution={resolution}; using canvas {size} "
                "from aspect_ratio + model tier."
            )

        # Clamp seconds to the model's supported set, picking the closest larger value.
        valid_seconds = _SORA_VALID_SECONDS.get(self.model, {4, 8, 12})
        if duration_seconds not in valid_seconds:
            chosen = min(
                (s for s in valid_seconds if s >= duration_seconds), default=None
            )
            if chosen is None:
                chosen = max(valid_seconds)
            logger.warning(
                f"[VIDEO_GEN] Sora ({self.model}) does not support {duration_seconds}s; "
                f"using {chosen}s."
            )
            duration_seconds = chosen

        # Sora has no dedicated negative_prompt; append to the prompt body.
        full_prompt = prompt
        if negative_prompt:
            full_prompt += f"\n\nAvoid: {negative_prompt}"

        # Validate the reference image up-front; the SDK expects the file
        # to be passed inline (bytes / IOBase / PathLike), NOT a pre-uploaded
        # file id. A separate files.create() round-trip is not part of the
        # Sora image-to-video contract.
        if reference_image and not os.path.isfile(reference_image):
            raise RuntimeError(f"Sora reference_image not found: {reference_image}")

        # Sora 2's `n` parameter for multiple videos is not yet exposed in the
        # public API; we issue `number_of_videos` independent jobs and stitch
        # them into the returned list. Each job is independent so errors on
        # one don't kill the rest — we collect partial results and report.
        per_job_timeout = poll_timeout_seconds // max(1, number_of_videos)
        paths: List[str] = []
        first_error: Optional[Exception] = None
        for i in range(max(1, int(number_of_videos))):
            ref_handle = None
            try:
                create_kwargs: Dict[str, Any] = {
                    "model": self.model,
                    "prompt": full_prompt,
                    "size": size,
                    "seconds": duration_seconds,
                }
                if seed is not None:
                    create_kwargs["seed"] = seed
                if reference_image:
                    # Open a fresh handle per job — the SDK consumes the
                    # stream during multipart upload. Closed in finally.
                    ref_handle = open(reference_image, "rb")
                    create_kwargs["input_reference"] = ref_handle

                # The OpenAI SDK exposes Sora under client.videos (added in the
                # 2026 SDK release). Older SDKs may need a fallback to the raw
                # HTTP endpoint via client.post.
                video_obj = self.client.videos.create(**create_kwargs)
                video_id = video_obj.id

                # Poll for completion.
                final_obj = self._poll_openai_video(video_id, per_job_timeout)
                mp4_bytes = self._download_openai_video(video_id)

                save_path = _build_save_path(
                    output_path, timestamp, len(paths), number_of_videos
                )
                _write_bytes(save_path, mp4_bytes)
                paths.append(save_path)

                # Best-effort usage reporting.
                usage = getattr(final_obj, "usage", None)
                if usage is not None:
                    self._report_usage_async(
                        provider="openai",
                        model=self.model,
                        input_tokens=getattr(usage, "input_tokens", 0) or 0,
                        output_tokens=getattr(usage, "output_tokens", 0) or 0,
                    )
            except Exception as exc:
                if first_error is None:
                    first_error = exc
                logger.warning(
                    f"[VIDEO_GEN] Sora job {i + 1}/{number_of_videos} failed: {exc}"
                )
            finally:
                if ref_handle is not None:
                    try:
                        ref_handle.close()
                    except Exception:
                        pass

        if not paths:
            raise RuntimeError(
                _classify_error(
                    "openai", first_error or RuntimeError("no result"), self.model
                )
            )
        return paths

    def _poll_openai_video(self, video_id: str, poll_timeout_seconds: int) -> Any:
        """Poll a Sora video job to completion. Returns the final video object."""
        deadline = time.monotonic() + poll_timeout_seconds
        delay = _DEFAULT_POLL_INITIAL
        while True:
            try:
                obj = self.client.videos.retrieve(video_id)
            except Exception as exc:
                raise RuntimeError(_classify_error("openai", exc, self.model)) from exc

            status = getattr(obj, "status", None)
            if status == "completed":
                return obj
            if status in ("failed", "cancelled", "error"):
                error_msg = getattr(obj, "error", None) or status
                raise RuntimeError(
                    f"OpenAI Sora job ended with status={status}: {error_msg}"
                )
            if status not in (None, "pending", "queued", "processing", "running"):
                raise RuntimeError(
                    f"OpenAI Sora job {video_id} returned unexpected status: {status!r}"
                )

            logger.debug(
                f"[VIDEO_GEN] Sora job {video_id} status={status!r}; retrying in {delay:.1f}s"
            )
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"OpenAI Sora job {video_id} did not complete within "
                    f"{poll_timeout_seconds}s (last status: {status})."
                )

            time.sleep(delay)
            delay = min(delay * 1.5, _DEFAULT_POLL_MAX)

    def _download_openai_video(self, video_id: str) -> bytes:
        """Download the MP4 bytes for a completed Sora video."""
        try:
            content = self.client.videos.download_content(video_id)
        except Exception as exc:
            raise RuntimeError(_classify_error("openai", exc, self.model)) from exc

        # The SDK may return bytes directly or an HTTPResponse-like object.
        if isinstance(content, bytes):
            return content
        if hasattr(content, "read"):
            return content.read()
        if hasattr(content, "content"):
            return content.content
        raise RuntimeError("OpenAI Sora download returned an unexpected payload type.")

    # ──────────────────────── Gemini / Veo ───────────────────────────────────

    def _gemini_generate(
        self,
        *,
        prompt: str,
        duration_seconds: int,
        aspect_ratio: str,
        resolution: str,
        number_of_videos: int,
        output_path: str,
        negative_prompt: str,
        reference_image: Optional[str],
        last_frame: Optional[str],
        reference_images: List[str],
        seed: Optional[int],
        with_audio: bool,
        person_generation: str,
        timestamp: str,
        poll_timeout_seconds: int,
    ) -> List[str]:
        if not self._gemini_client:
            raise RuntimeError(
                "Gemini API key is not configured. "
                "Set 'video_gen_provider' to 'openai' or 'byteplus' or add "
                "a Google API key in settings."
            )

        # Normalize aspect_ratio to Veo's allowed set.
        if aspect_ratio not in _VEO_ASPECT_VALID:
            logger.warning(
                f"[VIDEO_GEN] Veo does not support aspect_ratio={aspect_ratio}. "
                "Defaulting to 16:9."
            )
            aspect_ratio = "16:9"

        if resolution not in _VEO_RESOLUTION_VALID:
            logger.warning(
                f"[VIDEO_GEN] Veo does not support resolution={resolution}. "
                "Defaulting to 720p."
            )
            resolution = "720p"

        # Veo durations are integers; 1080p/4k or any reference inputs force 8.
        # Snap to the closest legal value.
        forces_eight = (
            resolution in {"1080p", "4k"}
            or reference_image
            or last_frame
            or reference_images
        )
        if forces_eight:
            duration_int = 8
        else:
            duration_int = int(duration_seconds)
            if duration_int not in _VEO_DURATION_VALID:
                chosen = min(
                    (s for s in _VEO_DURATION_VALID if s >= duration_int), default=8
                )
                logger.warning(
                    f"[VIDEO_GEN] Veo does not support durationSeconds={duration_seconds}; "
                    f"using {chosen}s."
                )
                duration_int = chosen

        _is_image_to_video = bool(reference_image or last_frame or reference_images)
        _valid_person_gen = (
            {"allow_adult", "dont_allow"}
            if _is_image_to_video
            else {"allow_all", "dont_allow"}
        )
        if person_generation not in _valid_person_gen:
            logger.warning(
                f"[VIDEO_GEN] Veo "
                f"{'image-to-video' if _is_image_to_video else 'text-to-video'} "
                f"does not support person_generation={person_generation}; "
                "omitting it so the model uses its default."
            )
            person_generation = None

        # Audio on Veo 3.x is model-controlled, not a request-time toggle:
        # `veo-3.1-generate-preview` (and likely siblings) rejects the
        # `generateAudio` field outright with 400 INVALID_ARGUMENT, while
        # the model produces synchronized audio by default anyway. Veo 2
        # is silent and also has no toggle. So we never forward the flag
        # to the Gemini client — letting the model use its native default.
        # When the caller asked to disable audio, log so the dropped intent
        # is visible.
        if not with_audio:
            logger.info(
                "[VIDEO_GEN] Veo audio is model-controlled and cannot be "
                "disabled per-request; with_audio=False is ignored."
            )

        # Read the start frame / last frame / reference image bytes off disk.
        start_pair = None
        last_pair = None
        ref_pairs: List[Tuple[bytes, str]] = []
        if reference_image:
            try:
                start_pair = _read_image_for_upload(reference_image)
            except Exception as exc:
                logger.warning(
                    f"[VIDEO_GEN] Skipping unreadable start frame '{reference_image}': {exc}"
                )
        if last_frame:
            try:
                last_pair = _read_image_for_upload(last_frame)
            except Exception as exc:
                logger.warning(
                    f"[VIDEO_GEN] Skipping unreadable last frame '{last_frame}': {exc}"
                )
        for ref_path in reference_images[:3]:
            try:
                ref_pairs.append(_read_image_for_upload(ref_path))
            except Exception as exc:
                logger.warning(
                    f"[VIDEO_GEN] Skipping unreadable reference frame '{ref_path}': {exc}"
                )

        try:
            op = self._gemini_client.generate_video(
                self.model,
                prompt=prompt,
                negative_prompt=negative_prompt or None,
                image=start_pair,
                last_frame=last_pair,
                reference_images=ref_pairs or None,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_int,
                resolution=resolution,
                person_generation=person_generation,
                number_of_videos=number_of_videos,
                seed=seed,
                # generate_audio intentionally omitted — see comment above.
            )
        except Exception as exc:
            raise RuntimeError(_classify_error("gemini", exc, self.model)) from exc

        operation_name = op.get("name")
        if not operation_name:
            raise RuntimeError(
                "Gemini Veo did not return an operation name — cannot poll for result."
            )

        final = self._poll_gemini_operation(operation_name, poll_timeout_seconds)

        # Veo's response shape: response.generateVideoResponse.generatedSamples[].video.uri
        response_body = final.get("response") or {}
        gv = response_body.get("generateVideoResponse") or {}
        samples = gv.get("generatedSamples") or []

        if not samples:
            block_reason = (
                gv.get("raiFilteredReason")
                or response_body.get("blockReason")
                or final.get("error", {}).get("message")
            )
            if block_reason:
                raise RuntimeError(
                    f"Gemini Veo blocked or returned no samples ({block_reason}). "
                    "Try modifying your prompt or adjusting person_generation."
                )
            raise RuntimeError(
                "Gemini Veo returned no video samples — try rephrasing your prompt "
                "or check that your API key has access to a Veo model."
            )

        # Usage reporting (input/output token counts).
        usage_md = final.get("metadata", {}).get("usageMetadata") or {}
        if usage_md:
            self._report_usage_async(
                provider="gemini",
                model=self.model,
                input_tokens=usage_md.get("promptTokenCount", 0) or 0,
                output_tokens=usage_md.get("candidatesTokenCount", 0) or 0,
                cached_tokens=usage_md.get("cachedContentTokenCount", 0) or 0,
            )

        paths: List[str] = []
        for i, sample in enumerate(samples[:number_of_videos]):
            video = sample.get("video") or {}
            uri = video.get("uri")
            inline = video.get("bytesBase64Encoded")
            if uri:
                try:
                    data = self._gemini_client.download_video(uri, timeout=180)
                except Exception as exc:
                    raise RuntimeError(
                        _classify_error("gemini", exc, self.model)
                    ) from exc
            elif inline:
                data = base64.b64decode(inline)
            else:
                logger.warning(
                    f"[VIDEO_GEN] Veo sample {i} had no uri or inline bytes — skipping."
                )
                continue

            save_path = _build_save_path(output_path, timestamp, i, len(samples))
            _write_bytes(save_path, data)
            paths.append(save_path)

        if not paths:
            raise RuntimeError(
                "Gemini Veo completed but produced no downloadable samples."
            )
        return paths

    def _poll_gemini_operation(
        self, operation_name: str, poll_timeout_seconds: int
    ) -> Dict[str, Any]:
        """Poll a Veo long-running operation until done. Returns final op JSON."""
        deadline = time.monotonic() + poll_timeout_seconds
        delay = _DEFAULT_POLL_INITIAL
        while True:
            try:
                op = self._gemini_client.poll_video_operation(operation_name)
            except Exception as exc:
                raise RuntimeError(_classify_error("gemini", exc, self.model)) from exc

            if op.get("done"):
                err = op.get("error")
                if err:
                    raise RuntimeError(
                        f"Gemini Veo operation failed: {err.get('message') or err}"
                    )
                return op

            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Gemini Veo operation {operation_name} did not complete within "
                    f"{poll_timeout_seconds}s."
                )

            time.sleep(delay)
            delay = min(delay * 1.5, _DEFAULT_POLL_MAX)

    # ──────────────────────── BytePlus / Seedance ────────────────────────────

    def _byteplus_generate(
        self,
        *,
        prompt: str,
        duration_seconds: int,
        aspect_ratio: str,
        resolution: str,
        number_of_videos: int,
        output_path: str,
        negative_prompt: str,
        reference_image: Optional[str],
        seed: Optional[int],
        with_audio: bool,
        camera_fixed: bool,
        watermark: bool,
        callback_url: str,
        timestamp: str,
        poll_timeout_seconds: int,
    ) -> List[str]:
        if not self._byteplus:
            raise RuntimeError(
                "BytePlus API key is not configured. "
                "Add a BytePlus key in settings or pick a different video provider."
            )

        api_key = self._byteplus["api_key"]
        base_url = self._byteplus["base_url"].rstrip("/")

        # Validate Seedance enums; downshift if needed.
        if aspect_ratio not in _SEEDANCE_ASPECT_VALID:
            logger.warning(
                f"[VIDEO_GEN] Seedance does not support aspect_ratio={aspect_ratio}. "
                "Defaulting to 16:9."
            )
            aspect_ratio = "16:9"
        if resolution not in _SEEDANCE_RESOLUTION_VALID:
            logger.warning(
                f"[VIDEO_GEN] Seedance does not support resolution={resolution}. "
                "Defaulting to 720p."
            )
            resolution = "720p"
        # Seedance accepts 2–12 seconds; clamp.
        duration_int = max(2, min(12, int(duration_seconds)))
        if duration_int != duration_seconds:
            logger.warning(
                f"[VIDEO_GEN] Seedance clamped duration_seconds={duration_seconds} → {duration_int}."
            )

        # BytePlus ModelArk takes generation params as TOP-LEVEL fields next to
        # `content[]`, not as inline `--flag` directives in the prompt text.
        # (The `--flag` style is the legacy Volcengine 2024 form and is
        # rejected by the international `ark.ap-southeast.bytepluses.com`
        # endpoint.) Verified against the official Dreamina Seedance 2.0
        # tutorial sample.
        text_block = prompt
        if negative_prompt:
            text_block += f"\n\nAvoid: {negative_prompt}"

        content_parts: List[Dict[str, Any]] = [{"type": "text", "text": text_block}]
        if reference_image:
            try:
                if not os.path.isfile(reference_image):
                    raise FileNotFoundError(reference_image)
                with open(reference_image, "rb") as f:
                    img_bytes = f.read()
                ext = os.path.splitext(reference_image)[1].lower()
                mime = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                }.get(ext, "image/jpeg")
                data_url = (
                    f"data:{mime};base64,{base64.b64encode(img_bytes).decode('utf-8')}"
                )
                content_parts.append(
                    {"type": "image_url", "image_url": {"url": data_url}}
                )
            except Exception as exc:
                logger.warning(
                    f"[VIDEO_GEN] Skipping unreadable Seedance reference image "
                    f"'{reference_image}': {exc}"
                )

        body: Dict[str, Any] = {
            "model": self.model,
            "content": content_parts,
            "ratio": aspect_ratio,
            "resolution": resolution,
            "duration": duration_int,
            "generate_audio": bool(with_audio),
        }
        if seed is not None:
            body["seed"] = int(seed)
        if camera_fixed:
            body["camera_fixed"] = True
        if watermark:
            body["watermark"] = True
        if callback_url:
            body["callback_url"] = callback_url

        # Number of videos: Seedance generates 1 per task; loop for N>1 so the
        # user can request multiple variations from a single call.
        per_job_timeout = poll_timeout_seconds // max(1, number_of_videos)
        paths: List[str] = []
        first_error: Optional[Exception] = None
        for i in range(max(1, int(number_of_videos))):
            try:
                task_id = self._byteplus_submit(api_key, base_url, body)
                video_url = self._byteplus_poll(
                    api_key, base_url, task_id, per_job_timeout
                )
                mp4_bytes = _download_video_url(video_url)
                save_path = _build_save_path(
                    output_path, timestamp, len(paths), number_of_videos
                )
                _write_bytes(save_path, mp4_bytes)
                paths.append(save_path)
            except Exception as exc:
                if first_error is None:
                    first_error = exc
                logger.warning(
                    f"[VIDEO_GEN] Seedance job {i + 1}/{number_of_videos} failed: {exc}"
                )

        if not paths:
            raise RuntimeError(
                _classify_error(
                    "byteplus", first_error or RuntimeError("no result"), self.model
                )
            )
        return paths

    def _byteplus_submit(
        self, api_key: str, base_url: str, body: Dict[str, Any]
    ) -> str:
        """Submit a Seedance task and return its task id."""
        url = f"{base_url}/contents/generations/tasks"
        try:
            r = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=60,
            )
        except Exception as exc:
            raise RuntimeError(_classify_error("byteplus", exc, self.model)) from exc

        if not r.ok:
            try:
                err_body = r.json()
                logger.warning(
                    f"[VIDEO_GEN] BytePlus submit failed: status={r.status_code} body={err_body}"
                )
            except Exception:
                logger.warning(
                    f"[VIDEO_GEN] BytePlus submit failed: status={r.status_code} text={r.text[:1000]}"
                )
            r.raise_for_status()

        data = r.json()
        task_id = data.get("id") or data.get("task_id")
        if not task_id:
            raise RuntimeError(
                "BytePlus Seedance did not return a task id. "
                f"Response: {json.dumps(data)[:500]}"
            )
        return str(task_id)

    def _byteplus_poll(
        self,
        api_key: str,
        base_url: str,
        task_id: str,
        poll_timeout_seconds: int,
    ) -> str:
        """Poll a Seedance task until succeeded; return the video URL."""
        deadline = time.monotonic() + poll_timeout_seconds
        delay = _DEFAULT_POLL_INITIAL
        poll_url = f"{base_url}/contents/generations/tasks/{task_id}"
        last_status = "unknown"
        while True:
            try:
                r = requests.get(
                    poll_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=30,
                )
                r.raise_for_status()
            except Exception as exc:
                raise RuntimeError(
                    _classify_error("byteplus", exc, self.model)
                ) from exc

            data = r.json()
            status = (data.get("status") or "").lower()
            last_status = status or last_status

            if status == "succeeded":
                content = data.get("content") or {}
                # Seedance returns either content.video_url (current) or content.url (legacy).
                video_url = content.get("video_url") or content.get("url")
                if (
                    not video_url
                    and isinstance(data.get("videos"), list)
                    and data["videos"]
                ):
                    video_url = data["videos"][0].get("video_url") or data["videos"][
                        0
                    ].get("url")
                if not video_url:
                    raise RuntimeError(
                        "BytePlus Seedance reported succeeded but did not include a video_url."
                    )
                # Best-effort usage reporting.
                usage = data.get("usage") or {}
                if usage:
                    self._report_usage_async(
                        provider="byteplus",
                        model=self.model,
                        input_tokens=usage.get("prompt_tokens", 0) or 0,
                        output_tokens=usage.get("completion_tokens", 0)
                        or usage.get("output_tokens", 0)
                        or 0,
                    )
                return str(video_url)

            if status in ("failed", "cancelled"):
                reason = data.get("error") or data.get("failure_reason") or status
                raise RuntimeError(
                    f"BytePlus Seedance task {task_id} ended with status={status}: {reason}"
                )

            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"BytePlus Seedance task {task_id} did not complete within "
                    f"{poll_timeout_seconds}s (last status: {last_status})."
                )

            time.sleep(delay)
            delay = min(delay * 1.5, _DEFAULT_POLL_MAX)


# ── Shared HTTP download helper ──────────────────────────────────────────────


def _download_video_url(url: str, *, timeout: int = 180) -> bytes:
    """Fetch a video URL into memory with an explicit timeout."""
    with _urllib_request.urlopen(url, timeout=timeout) as r:
        return r.read()
