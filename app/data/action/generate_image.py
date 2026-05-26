from agent_core import action


@action(
    name="generate_image",
    description="""Generates an image using Google's Nano Banana Pro (Gemini 3 Pro Image) model.
- State-of-the-art image generation with 1K, 2K, or 4K resolution support
- Excellent text rendering for infographics, menus, diagrams
- Uses GOOGLE_API_KEY environment variable (same as Gemini LLM provider)
- If API key is not set, returns an error with setup instructions
- TIP: When generating multiple images for the same project or related work, use 'reference_images' parameter with previously generated images to maintain consistent style across all outputs""",
    default=True,
    mode="CLI",
    action_sets=["content_creation", "image", "document_processing"],
    input_schema={
        "prompt": {
            "type": "string",
            "example": "A serene mountain landscape at sunset with a lake reflection",
            "description": "The text prompt describing the image to generate.",
            "required": True,
        },
        "output_path": {
            "type": "string",
            "example": "C:/Users/user/Pictures/generated_image.png",
            "description": "Absolute path where the generated image will be saved (e.g., C:/Users/user/image.png or /home/user/image.png). If not provided, saves to temp directory.",
        },
        "resolution": {
            "type": "string",
            "example": "2K",
            "description": "Output resolution. Options: '1K' (1080p), '2K', '4K'. Default: '1K'. Higher resolution costs more.",
        },
        "aspect_ratio": {
            "type": "string",
            "example": "16:9",
            "description": "Aspect ratio of the generated image. Options: '1:1', '3:4', '4:3', '9:16', '16:9'. Default: '1:1'.",
        },
        "number_of_images": {
            "type": "integer",
            "example": 1,
            "description": "Number of images to generate (1-4). Default: 1.",
        },
        "negative_prompt": {
            "type": "string",
            "example": "blurry, low quality, distorted",
            "description": "Text describing what to avoid in the generated image.",
        },
        "reference_images": {
            "type": "array",
            "example": [
                "C:/Users/user/Pictures/reference1.png",
                "C:/Users/user/Pictures/reference2.png",
            ],
            "description": "Optional list of reference image absolute paths to guide generation (up to 14 images). Use full absolute paths.",
        },
        "safety_filter_level": {
            "type": "string",
            "example": "block_medium_and_above",
            "description": "Safety filter level. Options: 'block_none', 'block_only_high', 'block_medium_and_above', 'block_low_and_above'. Default: 'block_medium_and_above'.",
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
            "description": "List of paths to the generated image files.",
        },
        "prompt_used": {
            "type": "string",
            "description": "The prompt that was used for generation.",
        },
        "resolution": {
            "type": "string",
            "description": "The resolution of the generated image.",
        },
        "message": {
            "type": "string",
            "description": "Status message or error message.",
        },
    },
    requirement=["google-genai", "Pillow"],
    test_payload={
        "prompt": "A cute cartoon cat sitting on a rainbow",
        "resolution": "1K",
        "aspect_ratio": "1:1",
        "number_of_images": 1,
        "simulated_mode": True,
    },
)
def generate_image(input_data: dict) -> dict:
    """
    Generates an image using Google's Nano Banana Pro (Gemini 3 Pro Image) model.
    """
    import os
    import sys
    import subprocess
    import importlib
    import tempfile
    from datetime import datetime

    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        return {
            "status": "success",
            "image_paths": ["/tmp/simulated_image_001.png"],
            "prompt_used": input_data.get("prompt", "Simulated prompt"),
            "resolution": input_data.get("resolution", "1K"),
            "message": "Image generated successfully (simulated mode).",
        }

    # Pre-flight validation: check API key is configured
    from app.config import get_api_key

    api_key = get_api_key("gemini")
    if not api_key:
        return {
            "status": "error",
            "image_paths": [],
            "prompt_used": "",
            "resolution": "",
            "message": "Gemini API key is not configured. Tell the user the Google Gemini API key is required for image generation, and ask if they need help setting it up.",
        }

    # Validate required input
    prompt = input_data.get("prompt", "").strip()
    if not prompt:
        return {
            "status": "error",
            "image_paths": [],
            "prompt_used": "",
            "resolution": "",
            "message": "A prompt is required to generate an image.",
        }

    # Get optional parameters
    output_path = input_data.get("output_path", "")
    resolution = input_data.get("resolution", "1K").upper()
    aspect_ratio = input_data.get("aspect_ratio", "1:1")
    number_of_images = min(max(int(input_data.get("number_of_images", 1)), 1), 4)
    negative_prompt = input_data.get("negative_prompt", "")
    reference_images = input_data.get("reference_images", [])
    safety_filter_level = input_data.get(
        "safety_filter_level", "block_medium_and_above"
    )

    # Validate resolution with user feedback
    valid_resolutions = ["1K", "2K", "4K"]
    warnings = []
    if resolution not in valid_resolutions:
        warnings.append(
            f"Invalid resolution '{resolution}'. Defaulting to '1K'. Valid options: {', '.join(valid_resolutions)}."
        )
        resolution = "1K"

    # Validate aspect ratio with user feedback
    valid_ratios = ["1:1", "3:4", "4:3", "9:16", "16:9"]
    if aspect_ratio not in valid_ratios:
        warnings.append(
            f"Invalid aspect ratio '{aspect_ratio}'. Defaulting to '1:1'. Valid options: {', '.join(valid_ratios)}."
        )
        aspect_ratio = "1:1"

    # Validate safety filter level with user feedback
    valid_safety_levels = [
        "block_none",
        "block_only_high",
        "block_medium_and_above",
        "block_low_and_above",
    ]
    if safety_filter_level not in valid_safety_levels:
        warnings.append(
            f"Invalid safety filter level '{safety_filter_level}'. Defaulting to 'block_medium_and_above'. Valid options: {', '.join(valid_safety_levels)}."
        )
        safety_filter_level = "block_medium_and_above"

    # Validate number_of_images with user feedback
    raw_num = int(input_data.get("number_of_images", 1))
    if raw_num < 1 or raw_num > 4:
        warnings.append(
            f"number_of_images '{raw_num}' out of range. Clamped to {number_of_images}. Valid range: 1-4."
        )

    # Limit reference images to 14
    if len(reference_images) > 14:
        warnings.append(
            f"Too many reference images ({len(reference_images)}). Only the first 14 will be used."
        )
        reference_images = reference_images[:14]

    # Helper: extract images from Gemini response
    def _extract_images_from_response(response):
        images = []
        # Primary path: candidates[].content.parts[].inline_data
        if hasattr(response, "candidates") and response.candidates:
            for candidate in response.candidates:
                if not (
                    hasattr(candidate, "content")
                    and hasattr(candidate.content, "parts")
                ):
                    continue
                for part in candidate.content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        if hasattr(
                            part.inline_data, "mime_type"
                        ) and part.inline_data.mime_type.startswith("image/"):
                            images.append(part.inline_data.data)
        # Fallback: response.images (older SDK versions)
        if not images and hasattr(response, "images"):
            for img in response.images:
                if hasattr(img, "data"):
                    images.append(img.data)
                elif hasattr(img, "_pil_image"):
                    images.append(img)
        return images

    # Helper: check if response was blocked by safety filters
    def _get_block_reason(response):
        if hasattr(response, "prompt_feedback"):
            feedback = response.prompt_feedback
            if hasattr(feedback, "block_reason") and feedback.block_reason:
                return str(feedback.block_reason)
        if hasattr(response, "candidates") and response.candidates:
            for candidate in response.candidates:
                if hasattr(candidate, "finish_reason") and candidate.finish_reason:
                    reason = str(candidate.finish_reason)
                    if "SAFETY" in reason.upper():
                        return reason
        return None

    # Helper: build the save path for a generated image
    def _build_save_path(output_path, timestamp, index, number_of_images, total_found):
        if output_path:
            if number_of_images > 1 or total_found > 1:
                base, ext = os.path.splitext(output_path)
                if not ext:
                    ext = ".png"
                return f"{base}_{index + 1}{ext}"
            else:
                save_path = output_path
                if not os.path.splitext(save_path)[1]:
                    save_path += ".png"
                return save_path
        else:
            temp_dir = tempfile.gettempdir()
            return os.path.join(
                temp_dir, f"generated_image_{timestamp}_{index + 1}.png"
            )

    # Helper: convert image data to PIL Image
    def _to_pil_image(img_data, Image, io, base64):
        if isinstance(img_data, str):
            image_bytes = base64.b64decode(img_data)
            return Image.open(io.BytesIO(image_bytes))
        elif isinstance(img_data, bytes):
            return Image.open(io.BytesIO(img_data))
        elif hasattr(img_data, "_pil_image"):
            return img_data._pil_image
        else:
            return img_data

    # Ensure required packages are installed
    def _ensure_package(pkg_name):
        try:
            importlib.import_module(pkg_name.replace("-", "_").split("[")[0])
        except ImportError:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg_name, "--quiet"]
            )

    try:
        _ensure_package("google-genai")
        _ensure_package("Pillow")
    except Exception as e:
        return {
            "status": "error",
            "image_paths": [],
            "prompt_used": prompt,
            "resolution": resolution,
            "message": f"Failed to install required packages: {str(e)}",
        }

    try:
        from google import genai
        from google.genai import types
        from PIL import Image
        import io
        import base64

        client = genai.Client(api_key=api_key)

        # Prepare reference images if provided
        image_parts = []
        for ref_path in reference_images:
            if os.path.exists(ref_path):
                try:
                    with open(ref_path, "rb") as f:
                        image_data = f.read()
                    ext = os.path.splitext(ref_path)[1].lower()
                    mime_map = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".gif": "image/gif",
                        ".webp": "image/webp",
                    }
                    mime_type = mime_map.get(ext, "image/png")
                    image_parts.append(
                        types.Part.from_bytes(data=image_data, mime_type=mime_type)
                    )
                except Exception:
                    pass  # Skip invalid reference images

        # Build the prompt with generation instructions
        generation_prompt = f"""Generate an image based on the following description:

{prompt}

Image specifications:
- Resolution: {resolution}
- Aspect ratio: {aspect_ratio}
- Number of variations: {number_of_images}"""

        if negative_prompt:
            generation_prompt += f"\n- Avoid: {negative_prompt}"

        content_parts = list(image_parts)
        content_parts.append(generation_prompt)

        # Safety settings
        safety_settings = None
        if safety_filter_level != "block_none":
            harm_block_threshold = {
                "block_only_high": "BLOCK_ONLY_HIGH",
                "block_medium_and_above": "BLOCK_MEDIUM_AND_ABOVE",
                "block_low_and_above": "BLOCK_LOW_AND_ABOVE",
            }.get(safety_filter_level, "BLOCK_MEDIUM_AND_ABOVE")

            safety_settings = [
                types.SafetySetting(category=category, threshold=harm_block_threshold)
                for category in (
                    "HARM_CATEGORY_HARASSMENT",
                    "HARM_CATEGORY_HATE_SPEECH",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "HARM_CATEGORY_DANGEROUS_CONTENT",
                )
            ]

        generate_config = types.GenerateContentConfig(
            candidate_count=1,
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(image_size=resolution),
            safety_settings=safety_settings,
        )

        response = client.models.generate_content(
            model="gemini-3-pro-image-preview",
            contents=content_parts,
            config=generate_config,
        )

        # Extract images from response
        image_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Process response to find generated images
        images_found = _extract_images_from_response(response)

        if not images_found:
            # Check if response was blocked by safety filters
            block_reason = _get_block_reason(response)
            if block_reason:
                return {
                    "status": "error",
                    "image_paths": [],
                    "prompt_used": prompt,
                    "resolution": resolution,
                    "message": f"Image generation was blocked by safety filters: {block_reason}. Try modifying your prompt or adjusting safety_filter_level.",
                }
            return {
                "status": "error",
                "image_paths": [],
                "prompt_used": prompt,
                "resolution": resolution,
                "message": "No images were generated. The model did not produce image output for this prompt. Try rephrasing your prompt or check if your API key has access to image generation.",
            }

        # Save each generated image
        for i, img_data in enumerate(images_found[:number_of_images]):
            save_path = _build_save_path(
                output_path, timestamp, i, number_of_images, len(images_found)
            )

            # Ensure parent directory exists
            parent_dir = os.path.dirname(os.path.abspath(save_path))
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Save the image
            pil_image = _to_pil_image(img_data, Image, io, base64)
            pil_image.save(save_path, "PNG")
            image_paths.append(save_path)

        message = (
            f"Successfully generated {len(image_paths)} image(s) using Nano Banana Pro."
        )
        if warnings:
            message += " Warnings: " + " ".join(warnings)

        return {
            "status": "success",
            "image_paths": image_paths,
            "prompt_used": prompt,
            "resolution": resolution,
            "message": message,
        }

    except Exception as e:
        error_message = str(e)

        # Provide more helpful error messages
        if "quota" in error_message.lower() or "rate" in error_message.lower():
            error_message = f"API rate limit or quota exceeded: {error_message}"
        elif "invalid" in error_message.lower() and "key" in error_message.lower():
            error_message = f"Invalid API key: {error_message}. Please verify your GOOGLE_API_KEY is correct."
        elif "permission" in error_message.lower() or "access" in error_message.lower():
            error_message = f"API access denied: {error_message}. Ensure your API key has access to Nano Banana Pro model."
        elif "safety" in error_message.lower() or "blocked" in error_message.lower():
            error_message = f"Content blocked by safety filters: {error_message}. Try modifying your prompt."
        elif "not found" in error_message.lower() or "404" in error_message:
            error_message = f"Model not available: {error_message}. The gemini-3-pro-image-preview model may not be accessible with your API key. Try using Google AI Studio to verify access."

        return {
            "status": "error",
            "image_paths": [],
            "prompt_used": prompt,
            "resolution": resolution,
            "message": error_message,
        }
