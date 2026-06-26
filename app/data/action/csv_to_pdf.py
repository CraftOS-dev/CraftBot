from agent_core import action


_STYLE_DESC = (
    "Optional style overrides on top of FORMAT.md (and an existing PDF's saved style when "
    "updating). Pass only keys to change. Keys: page_size, orientation, margin_in, page_numbers, "
    "header_text, footer_text, watermark_text; colors base_color/accent_color/muted_color; "
    "typography h1_pt/h2_pt/h3_pt/body_pt/small_pt. Tip: orientation='landscape' suits wide tables."
)


@action(
    name="csv_to_pdf",
    description=(
        "Converts a CSV file to a styled PDF table. Reads from a .csv file (source_path). The "
        "first row is treated as the header unless has_header=false. Optionally pass a title "
        "(banner heading). Styling comes from FORMAT.md; pass `style` to override (use "
        "orientation='landscape' for wide tables). Updating an existing PDF keeps its style "
        "unless overrides are passed. Use absolute paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    input_schema={
        "output_path": {"type": "string", "example": "C:/path/data.pdf", "description": "Absolute output path, must end with .pdf."},
        "source_path": {"type": "string", "example": "C:/path/data.csv", "description": "Absolute path to a .csv file."},
        "title": {"type": "string", "example": "Sales Q3", "description": "Optional banner heading. Omit for none."},
        "has_header": {"type": "boolean", "example": True, "description": "Treat the first row as the header. Defaults to true."},
        "delimiter": {"type": "string", "example": ",", "description": "Field delimiter. Defaults to ','."},
        "style": {"type": "object", "description": _STYLE_DESC},
    },
    output_schema={
        "status": {"type": "string", "example": "success", "description": "'success' or 'error'."},
        "path": {"type": "string", "example": "C:/path/data.pdf", "description": "Absolute path of the created PDF."},
        "pages": {"type": "integer", "example": 3, "description": "Page count. Only on success."},
        "size_bytes": {"type": "integer", "example": 20000, "description": "File size. Only on success."},
        "rows": {"type": "integer", "example": 120, "description": "Data rows rendered. Only on success."},
        "message": {"type": "string", "example": "...", "description": "Error detail. Only on error."},
    },
    requirement=["markdown2", "fpdf2", "pypdf"],
    test_payload={"output_path": "C:/x/data.pdf", "source_path": "C:/x/data.csv", "simulated_mode": True},
)
def csv_to_pdf(input_data: dict) -> dict:
    import os
    import csv

    simulated_mode = bool(input_data.get("simulated_mode", False))
    output_path = str(input_data.get("output_path", "")).strip()
    source_path = str(input_data.get("source_path", "")).strip()
    title = str(input_data.get("title", "")).strip()
    has_header = bool(input_data.get("has_header", True))
    delimiter = str(input_data.get("delimiter", ",")) or ","
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
        return {"status": "error", "message": f"source_path (.csv) not found: {source_path}"}

    try:
        with open(source_path, newline="", encoding="utf-8", errors="replace") as f:
            rows = list(csv.reader(f, delimiter=delimiter))
    except OSError as exc:
        return {"status": "error", "message": f"Could not read source_path: {exc}"}

    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return {"status": "error", "message": "CSV is empty."}

    def _cell(v: str) -> str:
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
    markdown_text = ("\n".join(lines))
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
            "rows": len(body),
        }
    except PermissionError as exc:
        return {"status": "error", "message": f"Permission denied writing to '{output_path}': {exc}"}
    except Exception as exc:
        return {"status": "error", "message": f"PDF generation failed: {type(exc).__name__}: {exc}"}
