from agent_core import action


_STYLE_DESC = (
    "Optional style overrides applied on top of FORMAT.md (and on top of the existing PDF's saved "
    "style when updating an existing file). Pass ONLY the keys you want to change; omit entirely "
    "to use FORMAT.md / keep the existing look. Themed formats (markdown/text/csv/xlsx/images) honor "
    "all keys; html/url honor only page-level keys (HTML's own styling wins) and accept `css` to "
    "inject a raw stylesheet; office formats (docx/odt/rtf/pptx) ignore style entirely (native "
    "fidelity is preserved by LibreOffice).\n"
    "  Common: page_size('A4'|'Letter'|'A3'|'A5'|'Legal'), orientation('portrait'|'landscape'), "
    "margin_in(float), page_numbers(bool), header_text(str), footer_text(str), watermark_text(str), "
    "watermark_color(hex), watermark_opacity(0-1)\n"
    "  Colors (hex): base_color, accent_color, muted_color, border_color, surface_color, "
    "code_fg_color, code_bg_color\n"
    "  Typography (pt): h1_pt, h2_pt, h3_pt, body_pt, code_pt, small_pt\n"
    "  Banner: banner(bool, default true — the first # heading becomes the title banner)\n"
    "  Web only: css (raw stylesheet string injected last), print_background(bool, default true)"
)


@action(
    name="convert_to_pdf",
    description=(
        "Universal source-to-PDF converter. Reads from `source_path`, an inline `content` string, "
        "`url` (live web page), or `image_paths` (list of images, one per page) and writes a PDF "
        "to `output_path`. Format is auto-detected from the input (source extension / which input "
        "key you pass); pass `source_format` to override.\n\n"
        "Supported formats:\n"
        "  - markdown (.md or inline) — themed via FORMAT.md; first # becomes the banner title; "
        "    supports headings, lists, bold/italic, code, tables, blockquotes. Pass `subtitle` "
        "    for a line below the banner.\n"
        "  - text (.txt or inline) — themed; rendered literally (markdown NOT interpreted); pass "
        "    `title` for a banner heading.\n"
        "  - csv (.csv) — themed table; first row is the header unless `has_header=false`; "
        "    `delimiter` defaults to ','; pass `title` for a banner.\n"
        "  - xlsx (.xlsx) — themed; each sheet becomes a table under its name; pick one with "
        "    `sheet` (name or 1-based index) or render all; `has_header` controls the header row; "
        "    pass `title` for a banner. Sheet-native colors/merged cells/charts are NOT preserved.\n"
        "  - images (image_paths list of png/jpg/etc.) — one image per page, aspect-ratio "
        "    preserved; only page-level style keys apply.\n"
        "  - html (.html or inline) — rendered with Playwright/Chromium (WeasyPrint fallback); "
        "    HTML's own styling is preserved; pass `style.css` to inject extra CSS. If no "
        "    page_size/orientation/margin is set, the HTML's own @page is honored.\n"
        "  - url (live web page) — same Chromium engine; requires `playwright install chromium`.\n"
        "  - docx/.doc, .odt, .rtf, .pptx/.ppt — converted via LibreOffice headless (requires "
        "    `soffice` on PATH); native fidelity is preserved; `style` does NOT apply.\n\n"
        "Updating an existing PDF re-applies that PDF's saved style unless overrides are passed, "
        "so re-renders keep the look. Use absolute paths only. `output_path` must end with .pdf."
        "Warning: this action convert file to PDF in a FIXED format and theme. Agent must not"
        "use this action if they need to create PDF in custom format when requested."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=True,
    input_schema={
        "output_path": {
            "type": "string",
            "example": "C:/path/out.pdf",
            "description": "Absolute output path; must end with .pdf. Parent dirs are created.",
        },
        "source_path": {
            "type": "string",
            "example": "C:/path/in.md",
            "description": (
                "Absolute path to the input file. Extension drives format detection: .md→markdown, "
                ".txt→text, .csv→csv, .xlsx→xlsx, .html/.htm→html, .docx/.doc/.odt/.rtf/.pptx/.ppt→office. "
                "Provide one of: source_path, content, url, or image_paths."
            ),
        },
        "content": {
            "type": "string",
            "example": "# Title\n\nBody.",
            "description": (
                "Inline string for markdown/text/html input. Format defaults to markdown; pass "
                "`source_format` ('markdown'|'text'|'html') to disambiguate. Use source_path for "
                "long documents to avoid the per-step output budget."
            ),
        },
        "url": {
            "type": "string",
            "example": "https://example.com",
            "description": "Live web page URL (http/https) to render via Chromium. Sets format to 'url'.",
        },
        "image_paths": {
            "type": "array",
            "items": {"type": "string"},
            "example": ["C:/path/a.png", "C:/path/b.jpg"],
            "description": "Ordered list of absolute image paths; sets format to 'images'. Each becomes one page.",
        },
        "source_format": {
            "type": "string",
            "example": "markdown",
            "description": (
                "Optional explicit format override. One of: markdown, text, csv, xlsx, html, url, "
                "images, docx, odt, rtf, pptx. If omitted, inferred from inputs."
            ),
        },
        "title": {
            "type": "string",
            "example": "Sales Q3",
            "description": "Optional banner heading for text/csv/xlsx formats.",
        },
        "subtitle": {
            "type": "string",
            "example": "Confidential",
            "description": "Optional subtitle below the banner (markdown only).",
        },
        "has_header": {
            "type": "boolean",
            "example": True,
            "description": "csv/xlsx: treat the first row as the header. Defaults to true.",
        },
        "delimiter": {
            "type": "string",
            "example": ",",
            "description": "csv: field delimiter. Defaults to ','.",
        },
        "sheet": {
            "type": "string",
            "example": "Sheet1",
            "description": "xlsx: a sheet name or 1-based index. Omit to render all sheets.",
        },
        "style": {
            "type": "object",
            "description": _STYLE_DESC,
        },
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/out.pdf", "description": "Absolute path of the created PDF."},
        "pages": {"type": "integer", "example": 12, "description": "Page count. Only on success, where the engine reports it."},
        "size_bytes": {"type": "integer", "example": 48230, "description": "File size. Only on success."},
        "rows": {"type": "integer", "example": 120, "description": "csv/xlsx only: data rows rendered."},
        "format": {"type": "string", "example": "markdown", "description": "Detected/used source format."},
        "message": {"type": "string", "example": "...", "description": "Error detail. Only on error."},
    },
    requirement=["markdown2", "fpdf2", "pypdf", "openpyxl", "pillow", "playwright"],
    test_payload={
        "output_path": "C:/x/out.pdf",
        "content": "# Title\n\nBody.",
        "source_format": "markdown",
        "simulated_mode": True,
    },
)
def convert_to_pdf(input_data: dict) -> dict:
    # NOTE: all helpers + lookup tables are defined INSIDE this function.
    # The action loader strips module-level names from the function's
    # globals at runtime, so referencing module-scope symbols here would
    # raise NameError at execution time.
    import os

    simulated_mode = bool(input_data.get("simulated_mode", False))
    output_path = str(input_data.get("output_path", "")).strip()
    source_path = str(input_data.get("source_path", "")).strip()
    url = str(input_data.get("url", "")).strip()
    image_paths = input_data.get("image_paths") or []
    if isinstance(image_paths, str):
        image_paths = [image_paths]
    content = input_data.get("content")
    source_format = str(input_data.get("source_format", "")).strip().lower()
    title = str(input_data.get("title", "")).strip()
    subtitle = str(input_data.get("subtitle", "")).strip()
    has_header = bool(input_data.get("has_header", True))
    delimiter = str(input_data.get("delimiter", ",")) or ","
    sheet_sel = str(input_data.get("sheet", "")).strip()
    style = input_data.get("style") or {}
    if not isinstance(style, dict):
        style = {}

    if not output_path:
        return {"status": "error", "message": "'output_path' is required."}
    if not output_path.lower().endswith(".pdf"):
        return {"status": "error", "message": "'output_path' must end with .pdf."}

    ext_to_format = {
        ".md": "markdown",
        ".markdown": "markdown",
        ".txt": "text",
        ".csv": "csv",
        ".xlsx": "xlsx",
        ".html": "html",
        ".htm": "html",
        ".docx": "docx",
        ".doc": "docx",
        ".odt": "odt",
        ".rtf": "rtf",
        ".pptx": "pptx",
        ".ppt": "pptx",
    }
    office_exts = {
        "docx": (".docx", ".doc"),
        "odt": (".odt",),
        "rtf": (".rtf",),
        "pptx": (".pptx", ".ppt"),
    }
    known_formats = {
        "markdown", "text", "csv", "xlsx", "images", "html", "url",
        "docx", "odt", "rtf", "pptx",
    }

    # ── Resolve format ─────────────────────────────────────────────────────
    fmt = source_format
    if not fmt:
        if url:
            fmt = "url"
        elif isinstance(image_paths, list) and image_paths:
            fmt = "images"
        elif source_path:
            ext = os.path.splitext(source_path)[1].lower()
            fmt = ext_to_format.get(ext, "")
        elif isinstance(content, str) and content.strip():
            fmt = "markdown"  # default for inline content
    if not fmt:
        return {
            "status": "error",
            "message": (
                "Could not determine source format. Provide source_path, content (with "
                "source_format), url, or image_paths."
            ),
        }
    if fmt not in known_formats:
        return {"status": "error", "message": f"Unsupported source_format: '{fmt}'."}

    if simulated_mode:
        pages = len(image_paths) if fmt == "images" else 1
        return {"status": "success", "path": output_path, "pages": pages, "format": fmt}

    # ── Dispatch ──────────────────────────────────────────────────────────
    result: dict

    if fmt == "markdown":
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
            return {"status": "error", "message": "Provide source_path (.md) or non-empty content."}

        try:
            from app.utils.pdf_render import convert_markdown

            r = convert_markdown(markdown_text, output_path, overrides=style, subtitle=subtitle)
            result = {
                "status": "success",
                "path": r["path"],
                "pages": r.get("pages"),
                "size_bytes": r.get("size_bytes"),
            }
        except PermissionError as exc:
            return {"status": "error", "message": f"Permission denied writing to '{output_path}': {exc}"}
        except Exception as exc:
            return {"status": "error", "message": f"PDF generation failed: {type(exc).__name__}: {exc}"}

    elif fmt == "text":
        import re

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
            return {"status": "error", "message": "Provide source_path (.txt) or non-empty content."}

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

            r = convert_markdown(markdown_text, output_path, overrides=style)
            result = {
                "status": "success",
                "path": r["path"],
                "pages": r.get("pages"),
                "size_bytes": r.get("size_bytes"),
            }
        except PermissionError as exc:
            return {"status": "error", "message": f"Permission denied writing to '{output_path}': {exc}"}
        except Exception as exc:
            return {"status": "error", "message": f"PDF generation failed: {type(exc).__name__}: {exc}"}

    elif fmt == "csv":
        import csv

        if not source_path or not os.path.isfile(source_path):
            return {"status": "error", "message": f"source_path (.csv) not found: {source_path}"}

        try:
            with open(source_path, newline="", encoding="utf-8", errors="replace") as f:
                rows = list(csv.reader(f, delimiter=delimiter))
        except OSError as exc:
            return {"status": "error", "message": f"Could not read source_path: {exc}"}

        rows = [r for r in rows if any(str(c).strip() for c in r)]
        if not rows:
            return {"status": "error", "message": "CSV is empty."}

        def _cell(v):
            return str(v).replace("|", "\\|").replace("\n", " ").strip()

        ncols = max(len(r) for r in rows)
        if has_header:
            header = [_cell(c) for c in rows[0]] + [""] * (ncols - len(rows[0]))
            body = rows[1:]
        else:
            header = [f"Column {i + 1}" for i in range(ncols)]
            body = rows

        lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * ncols) + " |"]
        for r in body:
            cells = [_cell(c) for c in r] + [""] * (ncols - len(r))
            lines.append("| " + " | ".join(cells) + " |")
        markdown_text = "\n".join(lines)
        if title:
            markdown_text = f"# {title}\n\n" + markdown_text

        try:
            from app.utils.pdf_render import convert_markdown

            r = convert_markdown(markdown_text, output_path, overrides=style)
            result = {
                "status": "success",
                "path": r["path"],
                "pages": r.get("pages"),
                "size_bytes": r.get("size_bytes"),
                "rows": len(body),
            }
        except PermissionError as exc:
            return {"status": "error", "message": f"Permission denied writing to '{output_path}': {exc}"}
        except Exception as exc:
            return {"status": "error", "message": f"PDF generation failed: {type(exc).__name__}: {exc}"}

    elif fmt == "xlsx":
        if not source_path or not os.path.isfile(source_path):
            return {"status": "error", "message": f"source_path (.xlsx) not found: {source_path}"}

        try:
            import openpyxl

            wb = openpyxl.load_workbook(source_path, read_only=True, data_only=True)
        except Exception as exc:
            return {"status": "error", "message": f"Could not read xlsx: {type(exc).__name__}: {exc}"}

        sheets = list(wb.worksheets)
        if sheet_sel:
            if sheet_sel.isdigit():
                idx = int(sheet_sel) - 1
                sheets = [sheets[idx]] if 0 <= idx < len(sheets) else []
            else:
                sheets = [ws for ws in sheets if ws.title == sheet_sel]
            if not sheets:
                return {"status": "error", "message": f"Sheet '{sheet_sel}' not found."}

        def _cell(v):
            if v is None:
                return ""
            return str(v).replace("|", "\\|").replace("\n", " ").strip()

        multi = len(sheets) > 1
        blocks = []
        total_rows = 0
        for ws in sheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            rows = [r for r in rows if any(c is not None and str(c).strip() for c in r)]
            if not rows:
                continue
            ncols = max(len(r) for r in rows)
            if has_header:
                header = [_cell(c) for c in rows[0]] + [""] * (ncols - len(rows[0]))
                body = rows[1:]
            else:
                header = [f"Column {i + 1}" for i in range(ncols)]
                body = rows
            total_rows += len(body)
            lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * ncols) + " |"]
            for r in body:
                cells = [_cell(c) for c in r] + [""] * (ncols - len(r))
                lines.append("| " + " | ".join(cells) + " |")
            block = "\n".join(lines)
            if multi:
                block = f"## {ws.title}\n\n{block}"
            blocks.append(block)

        if not blocks:
            return {"status": "error", "message": "Workbook has no data."}
        markdown_text = "\n\n".join(blocks)
        if title:
            markdown_text = f"# {title}\n\n" + markdown_text

        try:
            from app.utils.pdf_render import convert_markdown

            r = convert_markdown(markdown_text, output_path, overrides=style)
            result = {
                "status": "success",
                "path": r["path"],
                "pages": r.get("pages"),
                "size_bytes": r.get("size_bytes"),
                "rows": total_rows,
            }
        except PermissionError as exc:
            return {"status": "error", "message": f"Permission denied writing to '{output_path}': {exc}"}
        except Exception as exc:
            return {"status": "error", "message": f"PDF generation failed: {type(exc).__name__}: {exc}"}

    elif fmt == "images":
        if not isinstance(image_paths, list) or not image_paths:
            return {"status": "error", "message": "'image_paths' must be a non-empty list of absolute paths."}
        missing = [p for p in image_paths if not os.path.isfile(p)]
        if missing:
            return {"status": "error", "message": f"Image(s) not found: {missing[:5]}"}

        try:
            from app.utils.pdf_render import convert_images

            r = convert_images(image_paths, output_path, overrides=style)
            result = {
                "status": "success",
                "path": r["path"],
                "pages": r.get("pages"),
                "size_bytes": r.get("size_bytes"),
            }
        except PermissionError as exc:
            return {"status": "error", "message": f"Permission denied writing to '{output_path}': {exc}"}
        except Exception as exc:
            return {"status": "error", "message": f"PDF generation failed: {type(exc).__name__}: {exc}"}

    elif fmt == "html":
        if source_path:
            if not os.path.isfile(source_path):
                return {"status": "error", "message": f"source_path not found: {source_path}"}
            html_text = None
        elif isinstance(content, str) and content.strip():
            html_text = content
        else:
            return {"status": "error", "message": "Provide source_path (.html) or non-empty content."}

        from app.utils.pdf_convert import convert_html

        result = convert_html(output_path, source_path=source_path or None, html_text=html_text, style=style)

    elif fmt == "url":
        if not (url.startswith("http://") or url.startswith("https://")):
            return {"status": "error", "message": "'url' must start with http:// or https://."}

        from app.utils.pdf_convert import convert_url

        result = convert_url(url, output_path, style=style)

    else:  # office formats: docx / odt / rtf / pptx
        from app.utils.pdf_convert import office_to_pdf_impl

        result = office_to_pdf_impl(
            {"output_path": output_path, "source_path": source_path},
            office_exts[fmt],
        )

    if isinstance(result, dict) and result.get("status") == "success":
        result.setdefault("format", fmt)
    return result
