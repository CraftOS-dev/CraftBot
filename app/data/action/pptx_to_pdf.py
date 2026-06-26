from agent_core import action


@action(
    name="pptx_to_pdf",
    description=(
        "Converts a PowerPoint presentation (.pptx) to PDF (one slide per page) via LibreOffice "
        "headless, preserving the deck's native styling. Requires LibreOffice (`soffice` on PATH). "
        "Use absolute paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    input_schema={
        "output_path": {"type": "string", "example": "C:/path/deck.pdf", "description": "Absolute output path, must end with .pdf."},
        "source_path": {"type": "string", "example": "C:/path/deck.pptx", "description": "Absolute path to the .pptx (or .ppt) file."},
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/deck.pdf", "description": "Absolute path of the created PDF."},
        "size_bytes": {"type": "integer", "example": 200000, "description": "File size. Only on success."},
        "message": {"type": "string", "example": "...", "description": "Error detail. Only on error."},
    },
    requirement=[],
    test_payload={"output_path": "C:/x/d.pdf", "source_path": "C:/x/d.pptx", "simulated_mode": True},
)
def pptx_to_pdf(input_data: dict) -> dict:
    from app.utils.pdf_convert import office_to_pdf_impl

    return office_to_pdf_impl(input_data, (".pptx", ".ppt"))
