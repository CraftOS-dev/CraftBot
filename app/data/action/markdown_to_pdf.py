from agent_core import action


_STYLE_DESC = (
    "Optional style overrides applied on top of FORMAT.md (and, when updating an "
    "existing PDF, on top of that PDF's saved style). Pass ONLY the keys you want to "
    "change; omit it entirely to use FORMAT.md / keep the existing look. Keys:\n"
    "  Common: page_size('A4'|'Letter'|'A3'|'A5'|'Legal'), orientation('portrait'|'landscape'), "
    "margin_in(float), page_numbers(bool), header_text(str), footer_text(str), "
    "watermark_text(str), watermark_color(hex), watermark_opacity(0-1)\n"
    "  Colors (hex): base_color, accent_color, muted_color, border_color, surface_color, "
    "code_fg_color, code_bg_color\n"
    "  Typography (pt): h1_pt, h2_pt, h3_pt, body_pt, code_pt, small_pt\n"
    "  Banner: banner(bool, default true — the first # heading becomes the title banner)"
)


@action(
    name="markdown_to_pdf",
    description=(
        "Converts Markdown to a styled PDF. Reads the Markdown from a file (source_path) "
        "or from an inline string (content) — prefer source_path for long documents so you "
        "are not limited by the per-step output budget. Supports headings, lists, bold/italic, "
        "inline + fenced code, tables, strikethrough, blockquotes, rules. The first # heading "
        "becomes the banner title. Styling comes from FORMAT.md by default; pass `style` to "
        "override anything. Writing to an EXISTING PDF reuses that PDF's saved style unless you "
        "pass overrides, so updates keep their look. Use absolute paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    input_schema={
        "output_path": {
            "type": "string",
            "example": "C:/path/to/report.pdf",
            "description": "Absolute path where the PDF will be saved. Must end with .pdf. Parent dirs are created.",
        },
        "source_path": {
            "type": "string",
            "example": "C:/path/to/report.md",
            "description": "Absolute path to a Markdown (.md) file to convert. Use this for long documents. Provide either source_path or content.",
        },
        "content": {
            "type": "string",
            "example": "# My Report\n\nThis is **bold**.\n\n- Item 1\n- Item 2",
            "description": "Inline Markdown to convert. Use for short documents. Provide either source_path or content.",
        },
        "subtitle": {
            "type": "string",
            "example": "Confidential - Internal Use Only",
            "description": "Optional subtitle shown below the banner title. Omit to hide.",
        },
        "style": {
            "type": "object",
            "description": _STYLE_DESC,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/to/report.pdf", "description": "Absolute path of the created PDF."},
        "pages": {"type": "integer", "example": 12, "description": "Page count. Only on success."},
        "size_bytes": {"type": "integer", "example": 48230, "description": "File size. Only on success."},
        "message": {"type": "string", "example": "Permission denied.", "description": "Error detail. Only on error."},
    },
    requirement=["markdown2", "fpdf2", "pypdf"],
    test_payload={
        "output_path": "C:/Users/user/Documents/my_file.pdf",
        "content": "# My Title\n\nA paragraph with **bold** text.\n\n- Item 1\n- Item 2",
        "simulated_mode": True,
    },
)
def markdown_to_pdf(input_data: dict) -> dict:
    import os

    simulated_mode = bool(input_data.get("simulated_mode", False))
    output_path = str(input_data.get("output_path", "")).strip()
    source_path = str(input_data.get("source_path", "")).strip()
    content = input_data.get("content")
    subtitle = str(input_data.get("subtitle", "")).strip()
    style = input_data.get("style") or {}
    if not isinstance(style, dict):
        style = {}

    if not output_path:
        return {"status": "error", "message": "'output_path' is required."}
    if not output_path.lower().endswith(".pdf"):
        return {"status": "error", "message": "'output_path' must end with .pdf."}

    if simulated_mode:
        return {"status": "success", "path": output_path, "pages": 1}

    # Resolve the markdown text from file or inline content.
    if source_path:
        if not os.path.isfile(source_path):
            return {"status": "error", "message": f"source_path not found: {source_path}"}
        try:
            with open(source_path, encoding="utf-8", errors="replace") as f:
                markdown_text = f.read()
        except OSError as exc:
            return {"status": "error", "message": f"Could not read source_path: {exc}"}
    elif isinstance(content, str) and content.strip():
        markdown_text = content
    else:
        return {"status": "error", "message": "Provide either 'source_path' (a .md file) or non-empty 'content'."}

    try:
        from app.utils.pdf_render import convert_markdown

        result = convert_markdown(markdown_text, output_path, overrides=style, subtitle=subtitle)
        return {
            "status": "success",
            "path": result["path"],
            "pages": result.get("pages"),
            "size_bytes": result.get("size_bytes"),
        }
    except PermissionError as exc:
        return {"status": "error", "message": f"Permission denied writing to '{output_path}': {exc}"}
    except Exception as exc:
        return {"status": "error", "message": f"PDF generation failed: {type(exc).__name__}: {exc}"}
