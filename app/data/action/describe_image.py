from agent_core import action


@action(
    name="describe_image",
    description="Uses a Visual Language Model to analyse an image and return a detailed, markdown-ready description. IMPORTANT: Always provide a prompt describing what to look for or describe in the image.",
    mode="CLI",
    action_sets=["core", "document_processing", "image"],
    input_schema={
        "image_path": {
            "type": "string",
            "example": "C:\\\\Users\\\\user\\\\Pictures\\\\sample.jpg",
            "description": "Absolute path to the image file.",
        },
        "prompt": {
            "type": "string",
            "example": "Describe the content of this image in detail, including objects, colours, and spatial relationships.",
            "description": "REQUIRED: The prompt telling the VLM what to describe or look for in the image. Without a prompt, the description will be empty.",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if the description was generated, 'error' otherwise.",
        },
        "description": {
            "type": "string",
            "example": "A photo of a golden retriever sitting on a red sofa...",
            "description": "Markdown-friendly textual description returned by the VLM.",
        },
        "message": {
            "type": "string",
            "example": "File not found.",
            "description": "Error message if applicable.",
        },
    },
    test_payload={
        "image_path": "C:\\\\Users\\\\user\\\\Pictures\\\\sample.jpg",
        "prompt": "Highlight objects, colours and spatial relationships.",
        "simulated_mode": True,
    },
)
def view_image(input_data: dict) -> dict:
    import os

    image_path = str(input_data.get("image_path", "")).strip()
    simulated_mode = input_data.get("simulated_mode", False)
    prompt = (
        str(input_data.get("prompt", "")).strip()
        or "Describe the content of this image in detail."
    )

    if simulated_mode:
        return {
            "status": "success",
            "description": "A simulated image description showing various objects and colors.",
            "message": "",
        }

    # ── VLM availability guard ──────────────────────────────────────────
    import app.internal_action_interface as iai
    from agent_core.core.models.model_registry import MODEL_REGISTRY
    from agent_core.core.models.types import InterfaceType
    from app.config import get_vlm_provider

    vlm = iai.InternalActionInterface.vlm_interface
    current_provider = get_vlm_provider()
    registry_vlm = MODEL_REGISTRY.get(current_provider, {}).get(InterfaceType.VLM)

    if vlm is None or not registry_vlm:
        return {
            "status": "error",
            "description": "",
            "message": (
                f"The current VLM provider '{current_provider}' does not support vision/image analysis. "
                "Please inform the user and suggest switching to a provider that supports VLM.\n\n"
                "Providers with VLM support: openai, anthropic, gemini, byteplus.\n\n"
                "To switch provider, edit 'app/config/settings.json' and update:\n"
                '  "vlm_provider": "<provider>"  (e.g. "anthropic")\n'
                '  "vlm_model": "<model>"  (e.g. "claude-sonnet-4-6" for anthropic)\n\n'
                "Make sure the corresponding API key is configured under 'api_keys' in the same file. "
                "If no API key is set, ask the user to provide one. "
                "The system will automatically detect the config change and reload."
            ),
        }
    # ───────────────────────────────────────────────────────────────────

    if not image_path:
        return {
            "status": "error",
            "description": "",
            "message": "image_path is required.",
        }

    if not os.path.isfile(image_path):
        return {"status": "error", "description": "", "message": "File not found."}

    try:
        description = iai.InternalActionInterface.describe_image(image_path, prompt)
        if not description:
            return {
                "status": "error",
                "description": "",
                "message": "VLM returned an empty description.",
            }
        return {"status": "success", "description": description, "message": ""}
    except Exception as e:
        return {"status": "error", "description": "", "message": str(e)}
