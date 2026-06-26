from agent_core import action


_STYLE_DESC = (
    "Optional layout/style. Common: page_size, orientation, margin_in. print_background(bool, "
    "default true). For full control pass css (a raw stylesheet injected into the page). The "
    "page's own styling is preserved; FORMAT.md theme does NOT apply."
)


@action(
    name="url_to_pdf",
    description=(
        "Renders a live web page (URL) to PDF using a headless Chromium browser (Playwright), so "
        "JavaScript-rendered pages capture correctly. For static local HTML files use html_to_pdf "
        "instead. Requires the Playwright browser to be installed (`playwright install chromium`). "
        "Use an absolute output path ending in .pdf."
    ),
    mode="CLI",
    action_sets=["document_processing", "web_research"],
    parallelizable=False,
    input_schema={
        "output_path": {"type": "string", "example": "C:/path/page.pdf", "description": "Absolute output path, must end with .pdf."},
        "url": {"type": "string", "example": "https://example.com", "description": "The URL to render. Must start with http:// or https://."},
        "style": {"type": "object", "description": _STYLE_DESC},
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/page.pdf", "description": "Absolute path of the created PDF."},
        "size_bytes": {"type": "integer", "example": 120000, "description": "File size. Only on success."},
        "message": {"type": "string", "example": "...", "description": "Error detail. Only on error."},
    },
    requirement=["playwright"],
    test_payload={"output_path": "C:/x/p.pdf", "url": "https://example.com", "simulated_mode": True},
)
def url_to_pdf(input_data: dict) -> dict:
    simulated_mode = bool(input_data.get("simulated_mode", False))
    output_path = str(input_data.get("output_path", "")).strip()
    url = str(input_data.get("url", "")).strip()
    style = input_data.get("style") or {}
    if not isinstance(style, dict):
        style = {}

    if not output_path:
        return {"status": "error", "message": "'output_path' is required."}
    if not output_path.lower().endswith(".pdf"):
        return {"status": "error", "message": "'output_path' must end with .pdf."}
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"status": "error", "message": "'url' must start with http:// or https://."}
    if simulated_mode:
        return {"status": "success", "path": output_path}

    from app.utils.pdf_convert import convert_url

    return convert_url(url, output_path, style=style)
