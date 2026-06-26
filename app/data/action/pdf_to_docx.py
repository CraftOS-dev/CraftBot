from agent_core import action


@action(
    name="pdf_to_docx",
    description=(
        "Converts a PDF into an editable Word document (.docx), preserving text, tables, images "
        "and layout as closely as possible (via pdf2docx). Use when the user wants an editable "
        "Word version of a PDF, or to hand a document off for manual editing — then docx_to_pdf "
        "renders it back. Note: conversion of complex/scanned PDFs is approximate. Use absolute "
        "paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    input_schema={
        "source_path": {"type": "string", "example": "C:/path/doc.pdf", "description": "Absolute path to the source .pdf."},
        "output_path": {"type": "string", "example": "C:/path/doc.docx", "description": "Absolute path for the .docx output. Must end with .docx."},
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/doc.docx", "description": "Absolute path of the created .docx."},
        "size_bytes": {"type": "integer", "example": 40000, "description": "File size. Only on success."},
        "message": {"type": "string", "example": "...", "description": "Error detail. Only on error."},
    },
    requirement=["pdf2docx"],
    test_payload={"source_path": "C:/x/d.pdf", "output_path": "C:/x/d.docx", "simulated_mode": True},
)
def pdf_to_docx(input_data: dict) -> dict:
    import os

    simulated_mode = bool(input_data.get("simulated_mode", False))
    source_path = str(input_data.get("source_path", "")).strip()
    output_path = str(input_data.get("output_path", "")).strip()

    if not source_path:
        return {"status": "error", "message": "'source_path' is required."}
    if not source_path.lower().endswith(".pdf"):
        return {"status": "error", "message": "'source_path' must be a .pdf file."}
    if not output_path:
        return {"status": "error", "message": "'output_path' is required."}
    if not output_path.lower().endswith(".docx"):
        return {"status": "error", "message": "'output_path' must end with .docx."}
    if simulated_mode:
        return {"status": "success", "path": output_path}
    if not os.path.isfile(source_path):
        return {"status": "error", "message": f"source_path not found: {source_path}"}

    from app.utils.pdf_convert import convert_pdf_to_docx

    return convert_pdf_to_docx(source_path, output_path)
