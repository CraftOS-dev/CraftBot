from agent_core import action

@action(
    name="describe_image",
    description="Uses a Visual Language Model to analyse an image and return a detailed, markdown-ready description. IMPORTANT: Always provide a prompt describing what to look for or describe in the image.",
    mode="CLI",
    action_sets=["document_processing, image"],
    input_schema={
        "image_path": {
            "type": "string",
            "example": "C:\\\\Users\\\\user\\\\Pictures\\\\sample.jpg",
            "description": "Absolute path to the image file."
        },
        "prompt": {
            "type": "string",
            "example": "Describe the content of this image in detail, including objects, colours, and spatial relationships.",
            "description": "REQUIRED: The prompt telling the VLM what to describe or look for in the image. Without a prompt, the description will be empty."
        }
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if the description was generated, 'error' otherwise."
        },
        "description": {
            "type": "string",
            "example": "A photo of a golden retriever sitting on a red sofa...",
            "description": "Markdown-friendly textual description returned by the VLM."
        },
        "message": {
            "type": "string",
            "example": "File not found.",
            "description": "Error message if applicable."
        }
    },
    test_payload={
        "image_path": "C:\\\\Users\\\\user\\\\Pictures\\\\sample.jpg",
        "prompt": "Highlight objects, colours and spatial relationships.",
        "simulated_mode": True
    }
)
def view_image(input_data: dict) -> dict:
    import json, os

    image_path = str(input_data.get('image_path', '')).strip()
    simulated_mode = input_data.get('simulated_mode', False)
    prompt = str(input_data.get('prompt', '')).strip() or "Describe the content of this image in detail."

    if simulated_mode:
        # Return mock result for testing
        return {'status': 'success', 'description': 'A simulated image description showing various objects and colors.', 'message': ''}

    if not image_path:
        return {'status': 'error', 'description': '', 'message': 'image_path is required.'}

    if not os.path.isfile(image_path):
        return {'status': 'error', 'description': '', 'message': 'File not found.'}

    try:
        import app.internal_action_interface as iai
        description = iai.InternalActionInterface.describe_image(image_path, prompt)
        return {'status': 'success', 'description': description, 'message': ''}
    except Exception as e:
        return {'status': 'error', 'description': '', 'message': str(e)}