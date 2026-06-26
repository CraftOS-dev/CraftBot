from agent_core import action


_STYLE_DESC = (
    "Optional layout/style. Common: page_size('A4'|'Letter'|...), orientation('portrait'|"
    "'landscape'), margin_in(float). For full visual control pass css (a raw stylesheet string) "
    "— it is injected last and can restyle anything. HTML keeps its own styling; FORMAT.md theme "
    "does NOT apply here."
)


@action(
    name="html_to_pdf",
    description=(
        "Converts HTML/CSS to PDF, rendering with Playwright/Chromium (cross-platform; WeasyPrint "
        "fallback). Reads from an .html file (source_path) or an inline string (content). This is "
        "also the render-back step when editing a document: pdf_to_html → stream_edit → html_to_pdf. "
        "For a LIVE web page (URL) use url_to_pdf instead. Pass `style.css` to restyle; if you pass "
        "no page_size/orientation/margin it preserves the HTML's own @page size. Use absolute paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    input_schema={
        "output_path": {"type": "string", "example": "C:/path/page.pdf", "description": "Absolute output path, must end with .pdf."},
        "source_path": {"type": "string", "example": "C:/path/page.html", "description": "Absolute path to an .html file. Provide source_path or content."},
        "content": {"type": "string", "example": "<h1>Hi</h1><p>Body</p>", "description": "Inline HTML. Provide source_path or content."},
        "style": {"type": "object", "description": _STYLE_DESC},
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/page.pdf", "description": "Absolute path of the created PDF."},
        "size_bytes": {"type": "integer", "example": 30000, "description": "File size. Only on success."},
        "message": {"type": "string", "example": "...", "description": "Error detail. Only on error."},
    },
    requirement=["playwright"],
    test_payload={"output_path": "C:/x/p.pdf", "content": "<h1>Hi</h1>", "simulated_mode": True},
)
def html_to_pdf(input_data: dict) -> dict:
    import os

    simulated_mode = bool(input_data.get("simulated_mode", False))
    output_path = str(input_data.get("output_path", "")).strip()
    source_path = str(input_data.get("source_path", "")).strip()
    content = input_data.get("content")
    style = input_data.get("style") or {}
    if not isinstance(style, dict):
        style = {}

    if not output_path:
        return {"status": "error", "message": "'output_path' is required."}
    if not output_path.lower().endswith(".pdf"):
        return {"status": "error", "message": "'output_path' must end with .pdf."}
    if simulated_mode:
        return {"status": "success", "path": output_path}

    if source_path:
        if not os.path.isfile(source_path):
            return {"status": "error", "message": f"source_path not found: {source_path}"}
        html_text = None
    elif isinstance(content, str) and content.strip():
        html_text = content
    else:
        return {"status": "error", "message": "Provide either 'source_path' (.html) or non-empty 'content'."}

    from app.utils.pdf_convert import convert_html

    return convert_html(output_path, source_path=source_path or None, html_text=html_text, style=style)
