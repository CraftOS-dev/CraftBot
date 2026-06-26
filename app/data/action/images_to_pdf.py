from agent_core import action


_STYLE_DESC = (
    "Optional layout overrides on top of FORMAT.md. Images are not themed; only page-level "
    "keys apply: page_size, orientation, margin_in, page_numbers, header_text, footer_text, "
    "watermark_text, watermark_color(hex), watermark_opacity."
)


@action(
    name="images_to_pdf",
    description=(
        "Combines one or more images (PNG/JPG/etc.) into a PDF, one image per page, each fitted "
        "within the page margins while preserving aspect ratio. Pass image_paths in the order "
        "you want the pages. Page size/orientation/margins and optional header/footer/watermark "
        "come from FORMAT.md or `style`. Use absolute paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    input_schema={
        "output_path": {"type": "string", "example": "C:/path/album.pdf", "description": "Absolute output path, must end with .pdf."},
        "image_paths": {
            "type": "array",
            "items": {"type": "string"},
            "example": ["C:/path/a.png", "C:/path/b.jpg"],
            "description": "Ordered list of absolute image paths. Each becomes one page.",
        },
        "style": {"type": "object", "description": _STYLE_DESC},
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/album.pdf", "description": "Absolute path of the created PDF."},
        "pages": {"type": "integer", "example": 2, "description": "Page count (= image count). Only on success."},
        "size_bytes": {"type": "integer", "example": 90000, "description": "File size. Only on success."},
        "message": {"type": "string", "example": "...", "description": "Error detail. Only on error."},
    },
    requirement=["fpdf2", "pillow", "pypdf"],
    test_payload={"output_path": "C:/x/album.pdf", "image_paths": ["C:/x/a.png"], "simulated_mode": True},
)
def images_to_pdf(input_data: dict) -> dict:
    import os

    simulated_mode = bool(input_data.get("simulated_mode", False))
    output_path = str(input_data.get("output_path", "")).strip()
    image_paths = input_data.get("image_paths", [])
    if isinstance(image_paths, str):
        image_paths = [image_paths]
    style = input_data.get("style") or {}
    if not isinstance(style, dict):
        style = {}

    if not output_path:
        return {"status": "error", "message": "'output_path' is required."}
    if not output_path.lower().endswith(".pdf"):
        return {"status": "error", "message": "'output_path' must end with .pdf."}
    if not isinstance(image_paths, list) or not image_paths:
        return {"status": "error", "message": "'image_paths' must be a non-empty list of absolute paths."}
    if simulated_mode:
        return {"status": "success", "path": output_path, "pages": len(image_paths)}

    missing = [p for p in image_paths if not os.path.isfile(p)]
    if missing:
        return {"status": "error", "message": f"Image(s) not found: {missing[:5]}"}

    try:
        from app.utils.pdf_render import convert_images

        result = convert_images(image_paths, output_path, overrides=style)
        return {"status": "success", "path": result["path"], "pages": result.get("pages"), "size_bytes": result.get("size_bytes")}
    except PermissionError as exc:
        return {"status": "error", "message": f"Permission denied writing to '{output_path}': {exc}"}
    except Exception as exc:
        return {"status": "error", "message": f"PDF generation failed: {type(exc).__name__}: {exc}"}
