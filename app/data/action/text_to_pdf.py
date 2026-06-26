from agent_core import action


_STYLE_DESC = (
    "Optional style overrides on top of FORMAT.md (and an existing PDF's saved style when "
    "updating). Pass only keys to change; omit to keep the look. Keys: page_size, orientation, "
    "margin_in, page_numbers, header_text, footer_text, watermark_text, watermark_color(hex), "
    "watermark_opacity; colors base_color/accent_color/muted_color/code_fg_color/code_bg_color; "
    "typography h1_pt/h2_pt/h3_pt/body_pt/code_pt/small_pt."
)


@action(
    name="text_to_pdf",
    description=(
        "Converts plain text to a styled PDF, preserving line breaks. Reads from a .txt file "
        "(source_path) or an inline string (content). Markdown is NOT interpreted — the text is "
        "rendered literally in the document body font. Optionally pass a title (rendered as a "
        "banner heading). Styling comes from FORMAT.md; pass `style` to override. Updating an "
        "existing PDF keeps its style unless overrides are passed. Use absolute paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    input_schema={
        "output_path": {"type": "string", "example": "C:/path/notes.pdf", "description": "Absolute output path, must end with .pdf."},
        "source_path": {"type": "string", "example": "C:/path/notes.txt", "description": "Absolute path to a .txt file. Provide source_path or content."},
        "content": {"type": "string", "example": "Line one\nLine two", "description": "Inline plain text. Provide source_path or content."},
        "title": {"type": "string", "example": "Meeting Notes", "description": "Optional title rendered as a banner heading. Omit for no banner."},
        "style": {"type": "object", "description": _STYLE_DESC},
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/notes.pdf", "description": "Absolute path of the created PDF."},
        "pages": {"type": "integer", "example": 2, "description": "Page count. Only on success."},
        "size_bytes": {"type": "integer", "example": 12000, "description": "File size. Only on success."},
        "message": {"type": "string", "example": "...", "description": "Error detail. Only on error."},
    },
    requirement=["markdown2", "fpdf2", "pypdf"],
    test_payload={"output_path": "C:/x/notes.pdf", "content": "Hello\nWorld", "simulated_mode": True},
)
def text_to_pdf(input_data: dict) -> dict:
    import os
    import re

    simulated_mode = bool(input_data.get("simulated_mode", False))
    output_path = str(input_data.get("output_path", "")).strip()
    source_path = str(input_data.get("source_path", "")).strip()
    content = input_data.get("content")
    title = str(input_data.get("title", "")).strip()
    style = input_data.get("style") or {}
    if not isinstance(style, dict):
        style = {}

    if not output_path:
        return {"status": "error", "message": "'output_path' is required."}
    if not output_path.lower().endswith(".pdf"):
        return {"status": "error", "message": "'output_path' must end with .pdf."}
    if simulated_mode:
        return {"status": "success", "path": output_path, "pages": 1}

    if source_path:
        if not os.path.isfile(source_path):
            return {"status": "error", "message": f"source_path not found: {source_path}"}
        try:
            with open(source_path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as exc:
            return {"status": "error", "message": f"Could not read source_path: {exc}"}
    elif isinstance(content, str) and content.strip():
        text = content
    else:
        return {"status": "error", "message": "Provide either 'source_path' (.txt) or non-empty 'content'."}

    # Escape markdown-significant characters so text renders literally, and keep
    # line breaks (two trailing spaces = markdown hard break). Blank lines stay
    # paragraph separators.
    def _esc(line: str) -> str:
        line = re.sub(r"([\\`*_|])", r"\\\1", line)
        line = re.sub(r"^(\s*)([#>+\-])", r"\1\\\2", line)
        line = re.sub(r"^(\s*\d+)\.", r"\1\\.", line)
        return line

    md_lines = [(_esc(ln) + "  ") if ln.strip() else "" for ln in text.split("\n")]
    markdown_text = "\n".join(md_lines)
    if title:
        markdown_text = f"# {title}\n\n" + markdown_text

    try:
        from app.utils.pdf_render import convert_markdown

        result = convert_markdown(markdown_text, output_path, overrides=style)
        return {"status": "success", "path": result["path"], "pages": result.get("pages"), "size_bytes": result.get("size_bytes")}
    except PermissionError as exc:
        return {"status": "error", "message": f"Permission denied writing to '{output_path}': {exc}"}
    except Exception as exc:
        return {"status": "error", "message": f"PDF generation failed: {type(exc).__name__}: {exc}"}
