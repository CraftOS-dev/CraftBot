from agent_core import action


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
    requirement=["google-genai", "openai", "Pillow"],
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
    from app.config import get_image_gen_provider

    image_gen = iai.InternalActionInterface.image_gen_interface
    current_provider = get_image_gen_provider()
    registry_entry = MODEL_REGISTRY.get(current_provider, {}).get(InterfaceType.IMAGE_GEN)

    if image_gen is None or not registry_entry:
        return {
            "status": "error",
            "image_paths": [],
            "message": (
                f"Provider '{current_provider}' does not support image generation. "
                "Set 'image_gen_provider' to 'openai' or 'gemini' in settings.json "
                "and ensure the corresponding API key is configured under 'api_keys'."
            ),
        }

    prompt = str(input_data.get("prompt", "")).strip()
    if not prompt:
        return {
            "status": "error",
            "image_paths": [],
            "message": "prompt is required.",
        }

    try:
        paths = iai.InternalActionInterface.generate_image(
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
            "message": f"Generated {len(paths)} image(s) via {current_provider}.",
        }
    except Exception as e:
        return {
            "status": "error",
            "image_paths": [],
            "message": str(e),
        }
