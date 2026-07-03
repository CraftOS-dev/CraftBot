from agent_core import action


@action(
    name="convert_from_pdf",
    description=(
        "Universal PDF-to-source converter. Reads `source_path` (.pdf) and writes to "
        "`output_path` in a format inferred from the output extension; pass `target_format` to "
        "override.\n\n"
        "Supported targets:\n"
        "  - .docx (target_format='docx') — editable Word document via pdf2docx. Preserves text, "
        "    tables, images and layout as closely as possible. Complex/scanned PDFs are approximate.\n"
        "  - .html / .htm (target_format='html') — layout-preserving HTML reconstruction via "
        "    PyMuPDF (keeps fonts, sizes, colors, positions, images). This is the EDIT path for "
        "    existing PDFs: convert_from_pdf → stream_edit the HTML → convert_to_pdf (html). Pass "
        "    `mode='xhtml'` (default, reflows on edits) for content rewrites or `mode='html'` "
        "    (absolute-positioned, rigid, near-identical) for small in-place edits.\n\n"
        "Use absolute paths only. `source_path` must end with .pdf."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=True,
    input_schema={
        "source_path": {
            "type": "string",
            "example": "C:/path/in.pdf",
            "description": "Absolute path to the source .pdf.",
        },
        "output_path": {
            "type": "string",
            "example": "C:/path/out.docx",
            "description": (
                "Absolute output path. Extension drives target detection: .docx→docx, "
                ".html/.htm→html."
            ),
        },
        "target_format": {
            "type": "string",
            "example": "docx",
            "description": "Optional explicit target override. One of: docx, html.",
        },
        "mode": {
            "type": "string",
            "example": "xhtml",
            "description": "html target only: 'xhtml' (flow, reflows on edits — default) or 'html' (absolute-positioned, rigid).",
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "path": {
            "type": "string",
            "example": "C:/path/out.docx",
            "description": "Absolute path of the created file.",
        },
        "pages": {
            "type": "integer",
            "example": 2,
            "description": "Source PDF page count (html target only).",
        },
        "size_bytes": {
            "type": "integer",
            "example": 18000,
            "description": "File size. Only on success.",
        },
        "format": {
            "type": "string",
            "example": "docx",
            "description": "Detected/used target format.",
        },
        "message": {
            "type": "string",
            "example": "...",
            "description": "Error detail. Only on error.",
        },
    },
    requirement=["pdf2docx", "pymupdf"],
    test_payload={
        "source_path": "C:/x/in.pdf",
        "output_path": "C:/x/out.docx",
        "simulated_mode": True,
    },
)
def convert_from_pdf(input_data: dict) -> dict:
    import os

    simulated_mode = bool(input_data.get("simulated_mode", False))
    source_path = str(input_data.get("source_path", "")).strip()
    output_path = str(input_data.get("output_path", "")).strip()
    target_format = str(input_data.get("target_format", "")).strip().lower()
    mode = str(input_data.get("mode", "xhtml")).strip().lower() or "xhtml"

    if not source_path:
        return {"status": "error", "message": "'source_path' is required."}
    if not source_path.lower().endswith(".pdf"):
        return {"status": "error", "message": "'source_path' must be a .pdf file."}
    if not output_path:
        return {"status": "error", "message": "'output_path' is required."}

    fmt = target_format
    if not fmt:
        ext = os.path.splitext(output_path)[1].lower()
        fmt = {".docx": "docx", ".html": "html", ".htm": "html"}.get(ext, "")
    if not fmt:
        return {
            "status": "error",
            "message": "Could not determine target format. Pass target_format or use a .docx/.html output_path.",
        }

    if fmt == "docx":
        if not output_path.lower().endswith(".docx"):
            return {
                "status": "error",
                "message": "'output_path' must end with .docx for target_format='docx'.",
            }
    elif fmt == "html":
        if not output_path.lower().endswith((".html", ".htm")):
            return {
                "status": "error",
                "message": "'output_path' must end with .html for target_format='html'.",
            }
    else:
        return {"status": "error", "message": f"Unsupported target_format: '{fmt}'."}

    if simulated_mode:
        return {"status": "success", "path": output_path, "format": fmt, "pages": 1}
    if not os.path.isfile(source_path):
        return {"status": "error", "message": f"source_path not found: {source_path}"}

    if fmt == "docx":
        from app.utils.pdf_convert import convert_pdf_to_docx

        result = convert_pdf_to_docx(source_path, output_path)
    else:
        from app.utils.pdf_convert import convert_pdf_to_html

        result = convert_pdf_to_html(source_path, output_path, mode=mode)
    if isinstance(result, dict) and result.get("status") == "success":
        result.setdefault("format", fmt)
    return result
