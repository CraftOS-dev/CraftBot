from agent_core import action


_STYLE_DESC = (
    "Optional style overrides (same as csv_to_pdf — themed via FORMAT.md). Keys: page_size, "
    "orientation (use 'landscape' for wide tables), margin_in, page_numbers, header_text, "
    "footer_text, watermark_text; colors base_color/accent_color/muted_color; typography "
    "h1_pt/h2_pt/h3_pt/body_pt/small_pt. Updating an existing PDF keeps its style unless overridden."
)


@action(
    name="xlsx_to_pdf",
    description=(
        "Converts an Excel workbook (.xlsx) to a styled PDF. Each worksheet becomes a styled "
        "table under its sheet-name heading. The first row of each sheet is the header unless "
        "has_header=false. Pick one sheet with `sheet` (name or 1-based index) or omit for all. "
        "Rendered with our themed engine (spreadsheet-native colors/merged cells/charts are NOT "
        "preserved); pass `style` to customize. Use absolute paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    input_schema={
        "output_path": {"type": "string", "example": "C:/path/book.pdf", "description": "Absolute output path, must end with .pdf."},
        "source_path": {"type": "string", "example": "C:/path/book.xlsx", "description": "Absolute path to the .xlsx file."},
        "sheet": {"type": "string", "example": "Sheet1", "description": "Optional: a sheet name or 1-based index. Omit to render all sheets."},
        "title": {"type": "string", "example": "Q3 Workbook", "description": "Optional banner heading. Omit for none."},
        "has_header": {"type": "boolean", "example": True, "description": "Treat each sheet's first row as the header. Defaults to true."},
        "style": {"type": "object", "description": _STYLE_DESC},
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/book.pdf", "description": "Absolute path of the created PDF."},
        "pages": {"type": "integer", "example": 4, "description": "Page count. Only on success."},
        "size_bytes": {"type": "integer", "example": 30000, "description": "File size. Only on success."},
        "rows": {"type": "integer", "example": 200, "description": "Total data rows rendered. Only on success."},
        "message": {"type": "string", "example": "...", "description": "Error detail. Only on error."},
    },
    requirement=["openpyxl", "markdown2", "fpdf2", "pypdf"],
    test_payload={"output_path": "C:/x/b.pdf", "source_path": "C:/x/b.xlsx", "simulated_mode": True},
)
def xlsx_to_pdf(input_data: dict) -> dict:
    import os

    simulated_mode = bool(input_data.get("simulated_mode", False))
    output_path = str(input_data.get("output_path", "")).strip()
    source_path = str(input_data.get("source_path", "")).strip()
    sheet_sel = str(input_data.get("sheet", "")).strip()
    title = str(input_data.get("title", "")).strip()
    has_header = bool(input_data.get("has_header", True))
    style = input_data.get("style") or {}
    if not isinstance(style, dict):
        style = {}

    if not output_path:
        return {"status": "error", "message": "'output_path' is required."}
    if not output_path.lower().endswith(".pdf"):
        return {"status": "error", "message": "'output_path' must end with .pdf."}
    if simulated_mode:
        return {"status": "success", "path": output_path, "pages": 1, "rows": 0}
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

    def _cell(v) -> str:
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

        result = convert_markdown(markdown_text, output_path, overrides=style)
        return {
            "status": "success",
            "path": result["path"],
            "pages": result.get("pages"),
            "size_bytes": result.get("size_bytes"),
            "rows": total_rows,
        }
    except PermissionError as exc:
        return {"status": "error", "message": f"Permission denied writing to '{output_path}': {exc}"}
    except Exception as exc:
        return {"status": "error", "message": f"PDF generation failed: {type(exc).__name__}: {exc}"}
