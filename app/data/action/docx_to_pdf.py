from agent_core import action


@action(
    name="docx_to_pdf",
    description=(
        "Converts a Word document (.docx) to PDF via LibreOffice headless, preserving the "
        "document's native formatting. Requires LibreOffice installed (`soffice` on PATH). "
        "The document's own styling is kept (FORMAT.md theme does not apply). Use absolute paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    input_schema={
        "output_path": {"type": "string", "example": "C:/path/doc.pdf", "description": "Absolute output path, must end with .pdf."},
        "source_path": {"type": "string", "example": "C:/path/doc.docx", "description": "Absolute path to the .docx (or .doc) file."},
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/doc.pdf", "description": "Absolute path of the created PDF."},
        "size_bytes": {"type": "integer", "example": 40000, "description": "File size. Only on success."},
        "message": {"type": "string", "example": "...", "description": "Error detail. Only on error."},
    },
    requirement=[],
    test_payload={"output_path": "C:/x/d.pdf", "source_path": "C:/x/d.docx", "simulated_mode": True},
)
def docx_to_pdf(input_data: dict) -> dict:
    from app.utils.pdf_convert import office_to_pdf_impl

    return office_to_pdf_impl(input_data, (".docx", ".doc"))
