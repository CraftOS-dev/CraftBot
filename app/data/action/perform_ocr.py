from agent_core import action


@action(
    name="perform_ocr",
    description="Extracts all text from an image using OCR via a Vision Language Model. Use this when the user wants to read text from a screenshot, scanned document, photo of a receipt, whiteboard, sign, or any image containing text. Returns extracted text saved to a file in workspace.",
    mode="CLI",
    action_sets=["document_processing", "image", "video"],
    input_schema={
        "image_path": {
            "type": "string",
            "example": "C:\\Users\\user\\Pictures\\receipt.jpg",
            "description": "Absolute path to the image file containing text to extract.",
        },
        "user_prompt": {
            "type": "string",
            "example": "Extract all text including prices and product names.",
            "description": "Optional: extra instruction to guide the OCR (e.g. focus on specific regions or text types).",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' if OCR completed, 'error' otherwise.",
        },
        "summary": {
            "type": "string",
            "example": "OCR complete: 42 lines, 1250 characters extracted.",
            "description": "Brief summary of extraction results.",
        },
        "file_path": {
            "type": "string",
            "example": "/workspace/ocr_result_20260414_153000.txt",
            "description": "Absolute path to the .txt file containing full extracted text.",
        },
        "file_saved": {
            "type": "boolean",
            "example": True,
            "description": "True if the extracted text was saved to disk.",
        },
        "message": {
            "type": "string",
            "example": "File not found.",
            "description": "Error message if applicable.",
        },
    },
    test_payload={
        "image_path": "C:\\Users\\user\\Pictures\\sample.jpg",
        "user_prompt": "Extract all visible text.",
        "simulated_mode": True,
    },
)
def perform_ocr(input_data: dict) -> dict:
    import os

    image_path = str(input_data.get("image_path", "")).strip()
    user_prompt = str(input_data.get("user_prompt", "")).strip() or None
    simulated_mode = input_data.get("simulated_mode", False)

    if simulated_mode:
        return {
            "status": "success",
            "summary": "OCR complete: 5 lines, 120 characters extracted.",
            "file_path": "/workspace/ocr_result_simulated.txt",
            "file_saved": True,
            "message": "",
        }

    if not image_path:
        return {
            "status": "error",
            "summary": "",
            "file_path": "",
            "file_saved": False,
            "message": "image_path is required.",
        }

    if not os.path.isfile(image_path):
        return {
            "status": "error",
            "summary": "",
            "file_path": "",
            "file_saved": False,
            "message": "File not found.",
        }

    try:
        import app.internal_action_interface as iai

        result = iai.InternalActionInterface.perform_ocr(
            image_path, user_prompt=user_prompt
        )
        return {**result, "message": ""}
    except Exception as e:
        return {
            "status": "error",
            "summary": "",
            "file_path": "",
            "file_saved": False,
            "message": str(e),
        }
