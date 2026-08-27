from agent_core import action
from agent_core.utils.logger import logger


@action(
    name="generate_image",
    description="""Generates an image from a text prompt using the configured image generation provider (OpenAI gpt-image-2 or Google Gemini).
- The provider is determined by 'image_gen_provider' in settings.json (default: openai). Supported: openai, gemini.
- Saves the result as a PNG file to output_path, or a timestamped temp file if omitted.
- TIP: When generating multiple related images, pass previously generated paths via 'reference_images' to maintain style consistency.
- NOTE: reference_images semantics differ by provider — Gemini uses them as style guidance; OpenAI's images.edit treats them as compositional/mask inputs.""",
    default=True,
    mode="CLI",
    action_sets=["content_creation", "image", "document_processing"],
    input_schema={
        "prompt": {
            "type": "string",
            "example": "A serene mountain landscape at sunset with a lake reflection",
            "description": "Text description of the image to generate.",
            "required": True,
        },
        "output_path": {
            "type": "string",
            "example": "C:/Users/user/Pictures/generated_image.png",
            "description": "Absolute path where the generated image will be saved. If omitted, saved to temp directory with a timestamped name.",
        },
        "resolution": {
            "type": "string",
            "example": "2K",
            "description": "Output resolution: '1K' (default), '2K', or '4K'. Higher resolution costs more. OpenAI tops out at ~1536px regardless of this setting.",
        },
        "aspect_ratio": {
            "type": "string",
            "example": "16:9",
            "description": "Aspect ratio: '1:1' (default), '3:4', '4:3', '9:16', '16:9'. OpenAI maps to the nearest available canvas size — true 16:9 and 9:16 are not supported natively.",
        },
        "number_of_images": {
            "type": "integer",
            "example": 1,
            "description": "Number of images to generate (1–4). Default: 1.",
        },
        "negative_prompt": {
            "type": "string",
            "example": "blurry, low quality, distorted",
            "description": "Elements to avoid. Native on Gemini; appended to prompt for OpenAI.",
        },
        "reference_images": {
            "type": "array",
            "example": ["C:/Users/user/Pictures/ref.png"],
            "description": "Optional reference image paths (up to 14). Gemini: style guidance. OpenAI: compositional/mask inputs (different behaviour — results may vary).",
        },
        "safety_filter_level": {
            "type": "string",
            "example": "block_medium_and_above",
            "description": "Gemini safety filter: 'block_none', 'block_only_high', 'block_medium_and_above' (default), 'block_low_and_above'. Ignored by OpenAI.",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "image_paths": {
            "type": "array",
            "description": "Absolute paths to the generated PNG files.",
        },
        "message": {
            "type": "string",
            "description": "Status message or error details.",
        },
    },
    requirement=["openai", "Pillow"],
    test_payload={
        "prompt": "A cute cartoon cat sitting on a rainbow",
        "resolution": "1K",
        "aspect_ratio": "1:1",
        "number_of_images": 1,
        "simulated_mode": True,
    },
)
def generate_image(input_data: dict) -> dict:
    simulated_mode = input_data.get("simulated_mode", False)
    if simulated_mode:
        return {
            "status": "success",
            "image_paths": ["/tmp/simulated_image_001.png"],
            "message": "Image generated successfully (simulated mode).",
        }

    import app.internal_action_interface as iai
    from agent_core.core.models.model_registry import MODEL_REGISTRY
    from agent_core.core.models.types import InterfaceType
    from app.config import get_api_key, get_image_gen_provider

    prompt = str(input_data.get("prompt", "")).strip()
    if not prompt:
        return {
            "status": "error",
            "image_paths": [],
            "message": "prompt is required.",
        }

    # Fallback priority when the configured provider can't generate images:
    # prefer Gemini, then OpenAI, then any other image-gen-capable provider.
    _IMAGE_GEN_PRIORITY = ["gemini", "openai"]

    def _supports(p):
        return bool(MODEL_REGISTRY.get(p, {}).get(InterfaceType.IMAGE_GEN))

    def _has_key(p):
        try:
            return bool(get_api_key(p))
        except Exception:
            return False

    def _resolve_image_gen_provider(configured):
        """Configured provider if it can image-gen AND has a key, else highest-
        priority capable provider with a key, else None."""
        if configured and _supports(configured) and _has_key(configured):
            return configured
        candidates = list(_IMAGE_GEN_PRIORITY)
        for p, caps in MODEL_REGISTRY.items():
            if caps.get(InterfaceType.IMAGE_GEN) and p not in candidates:
                candidates.append(p)
        for p in candidates:
            if _supports(p) and _has_key(p):
                return p
        return None

    configured_provider = get_image_gen_provider()
    effective_provider = _resolve_image_gen_provider(configured_provider)

    if effective_provider is None:
        return {
            "status": "error",
            "image_paths": [],
            "message": (
                "No image-generation provider is available. Image generation requires "
                "OpenAI or Google (Gemini) with a configured API key. Set "
                "'image_gen_provider' and add the matching key under 'api_keys' in settings.json."
            ),
        }

    # Use the live interface when it already serves the effective provider;
    # otherwise build a transient interface for the fallback provider (the
    # configured provider can't generate images, but another configured key can).
    image_gen = iai.InternalActionInterface.image_gen_interface
    if (
        image_gen is None
        or not getattr(image_gen, "is_initialized", False)
        or image_gen.provider != effective_provider
    ):
        from app.image_gen_interface import ImageGenInterface
        from app.config import get_image_gen_model

        if effective_provider != configured_provider:
            from agent_core.utils.logger import logger

            logger.info(
                f"[IMAGE_GEN] Configured provider '{configured_provider}' can't generate "
                f"images; falling back to '{effective_provider}' (has a configured key)."
            )
        try:
            image_gen = ImageGenInterface(
                provider=effective_provider,
                # Honor the configured model override only when it matches the
                # configured provider; a fallback provider uses its own default.
                model=(
                    get_image_gen_model()
                    if effective_provider == configured_provider
                    else None
                ),
                api_key=get_api_key(effective_provider),
                deferred=False,
            )
        except Exception as e:
            return {
                "status": "error",
                "image_paths": [],
                "message": f"Failed to initialize image generation ({effective_provider}): {e}",
            }
        if not image_gen.is_initialized:
            return {
                "status": "error",
                "image_paths": [],
                "message": (
                    f"Image generation provider '{effective_provider}' could not be "
                    "initialized — check its API key in settings.json."
                ),
            }

    try:
        paths = image_gen.generate_image(
            prompt=prompt,
            resolution=str(input_data.get("resolution", "1K")).upper(),
            aspect_ratio=str(input_data.get("aspect_ratio", "1:1")),
            number_of_images=min(max(int(input_data.get("number_of_images", 1)), 1), 4),
            output_path=str(input_data.get("output_path") or ""),
            negative_prompt=str(input_data.get("negative_prompt") or ""),
            reference_images=list(input_data.get("reference_images") or []),
            safety_filter_level=str(
                input_data.get("safety_filter_level") or "block_medium_and_above"
            ),
        )
        return {
            "status": "success",
            "image_paths": paths,
            "message": f"Generated {len(paths)} image(s) via {effective_provider}.",
        }
    except Exception as e:
        return {
            "status": "error",
            "image_paths": [],
            "message": str(e),
        }
