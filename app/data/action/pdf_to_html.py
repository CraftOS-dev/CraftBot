from agent_core import action


@action(
    name="pdf_to_html",
    description=(
        "Extracts a LAYOUT-PRESERVING HTML reconstruction of a PDF (keeps fonts, sizes, colors, "
        "positions and images) so you can EDIT an existing document while keeping its look. "
        "Workflow to change an existing PDF: pdf_to_html → stream_edit the HTML text you need to "
        "change → html_to_pdf to re-render. This preserves the original design — do NOT rebuild "
        "from read_pdf text (that loses the layout). Use mode='xhtml' for content rewrites that "
        "change text length (reflows), 'html' for small in-place edits (near-identical, rigid). "
        "Reconstruction is close but not pixel-perfect; verify the result with the user. "
        "Use absolute paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    input_schema={
        "source_path": {"type": "string", "example": "C:/path/cv.pdf", "description": "Absolute path to the source .pdf to reconstruct."},
        "output_path": {"type": "string", "example": "C:/path/cv.html", "description": "Absolute path for the extracted HTML. Must end with .html (or .htm)."},
        "mode": {"type": "string", "example": "xhtml", "description": "'xhtml' (flow, reflows on edits — default) or 'html' (absolute-positioned, near-identical but rigid)."},
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/cv.html", "description": "Absolute path of the extracted HTML."},
        "pages": {"type": "integer", "example": 2, "description": "Source page count. Only on success."},
        "size_bytes": {"type": "integer", "example": 18000, "description": "HTML file size. Only on success."},
        "message": {"type": "string", "example": "...", "description": "Error detail. Only on error."},
    },
    requirement=["pymupdf"],
    test_payload={"source_path": "C:/x/cv.pdf", "output_path": "C:/x/cv.html", "simulated_mode": True},
)
def pdf_to_html(input_data: dict) -> dict:
    import os

    simulated_mode = bool(input_data.get("simulated_mode", False))
    source_path = str(input_data.get("source_path", "")).strip()
    output_path = str(input_data.get("output_path", "")).strip()
    mode = str(input_data.get("mode", "xhtml")).strip().lower() or "xhtml"

    if not source_path:
        return {"status": "error", "message": "'source_path' is required."}
    if not source_path.lower().endswith(".pdf"):
        return {"status": "error", "message": "'source_path' must be a .pdf file."}
    if not output_path:
        return {"status": "error", "message": "'output_path' is required."}
    if not output_path.lower().endswith((".html", ".htm")):
        return {"status": "error", "message": "'output_path' must end with .html."}
    if simulated_mode:
        return {"status": "success", "path": output_path, "pages": 1}
    if not os.path.isfile(source_path):
        return {"status": "error", "message": f"source_path not found: {source_path}"}

    from app.utils.pdf_convert import convert_pdf_to_html

    return convert_pdf_to_html(source_path, output_path, mode=mode)
