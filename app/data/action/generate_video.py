from agent_core import action


@action(
    name="generate_video",
    description="""Generates a video from a text prompt using the configured video generation provider (Google Gemini Veo, OpenAI Sora, or BytePlus Seedance).
- The provider is determined by 'video_gen_provider' in settings.json (default: gemini). Supported: gemini, openai, byteplus.
- The action BLOCKS while the long-running generation completes (typically 60-300s; up to ~25 min hard cap).
- Saves the result as an MP4 file to output_path, or a timestamped temp file if omitted.
- TIP: For image-to-video, pass an absolute path to a single start frame via 'reference_image'.
- NOTE: Per-provider quirks — Veo supports last_frame + reference_images (style); Sora accepts a single reference_image (uploaded inline as the SDK file field); Seedance accepts camera_fixed and watermark flags. Audio: Veo and Sora 2 produce synchronized audio; Seedance honors with_audio on 2.0+ models (silent on older 1.0 builds).""",
    default=True,
    mode="CLI",
    action_sets=["content_creation", "video"],
    input_schema={
        "prompt": {
            "type": "string",
            "example": "A drone shot of a misty mountain valley at dawn, cinematic",
            "description": "Text description of the video to generate.",
            "required": True,
        },
        "output_path": {
            "type": "string",
            "example": "C:/Users/user/Videos/generated.mp4",
            "description": "Absolute path where the generated video will be saved. If omitted, saved to temp directory with a timestamped name.",
        },
        "duration_seconds": {
            "type": "integer",
            "example": 8,
            "description": "Target duration in seconds. Per-provider clamping: Sora 2 = 4/8/12; Veo = 4/6/8 (forced to 8 with 1080p+/refs); Seedance = 2-12.",
        },
        "aspect_ratio": {
            "type": "string",
            "example": "16:9",
            "description": "Aspect ratio: '16:9' (default), '9:16', '1:1', '4:3', '3:4', '21:9'. Sora and Veo only support 16:9 and 9:16.",
        },
        "resolution": {
            "type": "string",
            "example": "1080p",
            "description": "Output resolution: '480p', '720p' (default), '1080p', '4k'. Sora 2 standard tops at 720p; 4k is Veo only.",
        },
        "number_of_videos": {
            "type": "integer",
            "example": 1,
            "description": "Number of videos to generate (1-4). Default: 1. Multiple videos are submitted as independent jobs for Sora and Seedance.",
        },
        "negative_prompt": {
            "type": "string",
            "example": "blurry, low quality, distorted",
            "description": "Elements to avoid. Native on Veo and Seedance; appended to prompt for Sora.",
        },
        "reference_image": {
            "type": "string",
            "example": "C:/Users/user/Pictures/start_frame.png",
            "description": "Optional absolute path to a single start-frame image for image-to-video.",
        },
        "last_frame": {
            "type": "string",
            "example": "C:/Users/user/Pictures/end_frame.png",
            "description": "Optional absolute path to an end-frame image for frame interpolation. Veo 3.1+ only; silently dropped elsewhere.",
        },
        "reference_images": {
            "type": "array",
            "example": ["C:/Users/user/Pictures/style1.png"],
            "description": "Optional list of absolute paths to additional style-reference images. Veo 3.1+ accepts up to 3; silently dropped on Sora and Seedance.",
        },
        "seed": {
            "type": "integer",
            "example": 42,
            "description": "Optional deterministic seed.",
        },
        "with_audio": {
            "type": "boolean",
            "example": True,
            "description": "Whether to generate synchronized native audio. Veo 3.x and Sora 2 produce audio by default (no toggle — this flag is ignored on those providers). Honored on BytePlus Seedance 2.0+; silent on older Seedance 1.0 builds.",
        },
        "person_generation": {
            "type": "string",
            "example": "allow_adult",
            "description": "Veo only — 'allow_all', 'allow_adult' (default), or 'dont_allow'. 'allow_all' is geo-restricted (EU/UK/CH/MENA).",
        },
        "camera_fixed": {
            "type": "boolean",
            "example": False,
            "description": "BytePlus Seedance only — lock camera position throughout the clip.",
        },
        "watermark": {
            "type": "boolean",
            "example": False,
            "description": "BytePlus Seedance only — apply watermark to output.",
        },
        "callback_url": {
            "type": "string",
            "example": "",
            "description": "BytePlus Seedance only — webhook for task completion (optional).",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "video_paths": {
            "type": "array",
            "description": "Absolute paths to the generated MP4 files.",
        },
        "message": {
            "type": "string",
            "description": "Status message or error details.",
        },
    },
    requirement=["openai", "requests"],
    test_payload={
        "prompt": "A cute corgi running through autumn leaves, slow motion",
        "duration_seconds": 4,
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "number_of_videos": 1,
        "simulated_mode": True,
    },
)
def generate_video(input_data: dict) -> dict:
    simulated_mode = input_data.get("simulated_mode", False)
    if simulated_mode:
        return {
            "status": "success",
            "video_paths": ["/tmp/simulated_video_001.mp4"],
            "message": "Video generated successfully (simulated mode).",
        }

    import app.internal_action_interface as iai
    from agent_core.core.models.model_registry import MODEL_REGISTRY
    from agent_core.core.models.types import InterfaceType
    from app.config import get_api_key, get_video_gen_provider

    prompt = str(input_data.get("prompt", "")).strip()
    if not prompt:
        return {
            "status": "error",
            "video_paths": [],
            "message": "prompt is required.",
        }

    # Fallback priority when the configured provider can't generate videos:
    # prefer Gemini Veo, then OpenAI Sora, then BytePlus Seedance.
    _VIDEO_GEN_PRIORITY = ["gemini", "openai", "byteplus"]

    def _supports(p):
        return bool(MODEL_REGISTRY.get(p, {}).get(InterfaceType.VIDEO_GEN))

    def _has_key(p):
        try:
            return bool(get_api_key(p))
        except Exception:
            return False

    def _resolve_video_gen_provider(configured):
        """Configured provider if it can video-gen AND has a key, else highest-
        priority capable provider with a key, else None."""
        if configured and _supports(configured) and _has_key(configured):
            return configured
        candidates = list(_VIDEO_GEN_PRIORITY)
        for p, caps in MODEL_REGISTRY.items():
            if caps.get(InterfaceType.VIDEO_GEN) and p not in candidates:
                candidates.append(p)
        for p in candidates:
            if _supports(p) and _has_key(p):
                return p
        return None

    configured_provider = get_video_gen_provider()
    effective_provider = _resolve_video_gen_provider(configured_provider)

    if effective_provider is None:
        return {
            "status": "error",
            "video_paths": [],
            "message": (
                "No video-generation provider is available. Video generation requires "
                "Google (Gemini Veo), OpenAI (Sora), or BytePlus (Seedance) with a "
                "configured API key. Set 'video_gen_provider' and add the matching "
                "key under 'api_keys' in settings.json."
            ),
        }

    # Use the live interface when it already serves the effective provider;
    # otherwise build a transient interface for the fallback provider.
    video_gen = iai.InternalActionInterface.video_gen_interface
    if (
        video_gen is None
        or not getattr(video_gen, "is_initialized", False)
        or video_gen.provider != effective_provider
    ):
        from app.video_gen_interface import VideoGenInterface
        from app.config import get_video_gen_model

        if effective_provider != configured_provider:
            from agent_core.utils.logger import logger

            logger.info(
                f"[VIDEO_GEN] Configured provider '{configured_provider}' can't generate "
                f"videos; falling back to '{effective_provider}' (has a configured key)."
            )
        try:
            video_gen = VideoGenInterface(
                provider=effective_provider,
                # Honor the configured model override only when it matches the
                # configured provider; a fallback provider uses its own default.
                model=(
                    get_video_gen_model()
                    if effective_provider == configured_provider
                    else None
                ),
                api_key=get_api_key(effective_provider),
                deferred=False,
            )
        except Exception as e:
            return {
                "status": "error",
                "video_paths": [],
                "message": f"Failed to initialize video generation ({effective_provider}): {e}",
            }
        if not video_gen.is_initialized:
            return {
                "status": "error",
                "video_paths": [],
                "message": (
                    f"Video generation provider '{effective_provider}' could not be "
                    "initialized — check its API key in settings.json."
                ),
            }

    try:
        paths = video_gen.generate_video(
            prompt=prompt,
            duration_seconds=int(input_data.get("duration_seconds", 5)),
            aspect_ratio=str(input_data.get("aspect_ratio", "16:9")),
            resolution=str(input_data.get("resolution", "720p")),
            number_of_videos=min(max(int(input_data.get("number_of_videos", 1)), 1), 4),
            output_path=str(input_data.get("output_path") or ""),
            negative_prompt=str(input_data.get("negative_prompt") or ""),
            reference_image=(input_data.get("reference_image") or None),
            last_frame=(input_data.get("last_frame") or None),
            reference_images=list(input_data.get("reference_images") or []),
            seed=(
                int(input_data["seed"])
                if input_data.get("seed") not in (None, "")
                else None
            ),
            with_audio=bool(input_data.get("with_audio", True)),
            person_generation=str(input_data.get("person_generation") or "allow_adult"),
            camera_fixed=bool(input_data.get("camera_fixed", False)),
            watermark=bool(input_data.get("watermark", False)),
            callback_url=str(input_data.get("callback_url") or ""),
        )
        return {
            "status": "success",
            "video_paths": paths,
            "message": f"Generated {len(paths)} video(s) via {effective_provider}.",
        }
    except Exception as e:
        return {
            "status": "error",
            "video_paths": [],
            "message": str(e),
        }
