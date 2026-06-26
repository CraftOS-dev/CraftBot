from agent_core import action


@action(
    name="rtf_to_pdf",
    description=(
        "Converts a Rich Text Format file (.rtf) to PDF via LibreOffice headless, preserving "
        "formatting. Requires LibreOffice (`soffice` on PATH). Use absolute paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    input_schema={
        "output_path": {"type": "string", "example": "C:/path/doc.pdf", "description": "Absolute output path, must end with .pdf."},
        "source_path": {"type": "string", "example": "C:/path/doc.rtf", "description": "Absolute path to the .rtf file."},
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/doc.pdf", "description": "Absolute path of the created PDF."},
        "size_bytes": {"type": "integer", "example": 40000, "description": "File size. Only on success."},
        "message": {"type": "string", "example": "...", "description": "Error detail. Only on error."},
    },
    requirement=[],
    test_payload={"output_path": "C:/x/d.pdf", "source_path": "C:/x/d.rtf", "simulated_mode": True},
)
def rtf_to_pdf(input_data: dict) -> dict:
    from app.utils.pdf_convert import office_to_pdf_impl

    return office_to_pdf_impl(input_data, (".rtf",))
