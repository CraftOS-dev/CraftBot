from agent_core import action


@action(
    name="edit_pdf",
    description=(
        "Edits an existing PDF by applying a list of operations and saves the result "
        "to a new file. Accepts two input types per operation: "
        "coord-based (x0/y0/x1/y1 in BOTTOMLEFT origin — direct from read_pdf layout mode) "
        "and pattern-based (text string searched internally — no read_pdf call needed). "
        "Operations: add_text, redact, highlight, underline, strikeout (coord or pattern), "
        "replace_text (find + font-matched reinsert), add_text_near (fill after a label), "
        "watermark, rotate_page, fill_field (AcroForm). "
        "For tasks that require text reflow (rephrasing paragraphs, inserting new sections, "
        "reformatting layout): use markdown_to_pdf to rebuild the document with changes applied — "
        "write to the SAME output_path and it reuses that PDF's saved style automatically, so the "
        "look is preserved. Use absolute paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    platforms=["windows", "linux", "darwin"],
    input_schema={
        "file_path": {
            "type": "string",
            "example": "C:/path/to/document.pdf",
            "description": "Absolute path to the source PDF to edit.",
        },
        "output_path": {
            "type": "string",
            "example": "C:/path/to/document_edited.pdf",
            "description": (
                "Absolute path for the output PDF. "
                "Parent directories are created automatically. "
                "Must end with .pdf."
            ),
        },
        "operations": {
            "type": "array",
            "description": (
                "Ordered list of edit operations to apply. Each operation is an object "
                "with a 'type' field plus type-specific fields. "
                "Coord fields (x0/y0/x1/y1) use BOTTOMLEFT origin (direct from read_pdf layout mode). "
                "Pattern fields search the PDF internally — no read_pdf call needed.\n"
                "Types:\n"
                "  add_text: insert text. Fields: page(int), text(str), x(float), y(float, BOTTOMLEFT), "
                "font_size(float,default 12), color(hex,default '#000000')\n"
                "  redact: true redaction — removes content from stream. Fields: page(int), "
                "x0/y0/x1/y1(float, BOTTOMLEFT) OR pattern(str) + page('all' or int)\n"
                "  highlight: highlight annotation. Fields: page(int), "
                "x0/y0/x1/y1(float, BOTTOMLEFT) OR pattern(str) + page, color(hex,default '#ffff00')\n"
                "  underline: underline annotation. Fields: page(int), x0/y0/x1/y1 OR pattern + page\n"
                "  strikeout: strikeout annotation. Fields: page(int), x0/y0/x1/y1 OR pattern + page\n"
                "  replace_text: find text and replace with font-matched new text. "
                "Fields: pattern(str), replacement(str), page('all' or int)\n"
                "  add_text_near: find a label and insert value after it (form fill). "
                "Fields: label(str), value(str), page(int), "
                "offset_x(float,default 5), font_size(float,default 11), color(hex,default '#000000')\n"
                "  watermark: add diagonal text watermark to all pages. "
                "Fields: text(str), font_size(float,default 52), color(hex,default '#bbbbbb'), opacity(0-1,default 0.25)\n"
                "  rotate_page: rotate a page. Fields: page(int), degrees(90/180/270)\n"
                "  fill_field: fill an AcroForm field. Fields: field_name(str), value(str)"
            ),
            "example": [
                {
                    "type": "highlight",
                    "pattern": "Invoice",
                    "page": "all",
                    "color": "#fef08a",
                },
                {
                    "type": "add_text",
                    "page": 1,
                    "text": "PAID",
                    "x": 200,
                    "y": 400,
                    "font_size": 36,
                    "color": "#16a34a",
                },
                {
                    "type": "redact",
                    "page": 1,
                    "x0": 31.2,
                    "y0": 791.3,
                    "x1": 86.3,
                    "y1": 807.3,
                },
                {
                    "type": "replace_text",
                    "pattern": "Q3",
                    "replacement": "Q4",
                    "page": "all",
                },
                {
                    "type": "watermark",
                    "text": "DRAFT",
                    "color": "#bbbbbb",
                    "opacity": 0.2,
                },
            ],
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "output_path": {
            "type": "string",
            "example": "C:/path/to/document_edited.pdf",
            "description": "Absolute path of the edited PDF.",
        },
        "operations_applied": {
            "type": "integer",
            "example": 3,
            "description": "Number of operations successfully applied.",
        },
        "warnings": {
            "type": "array",
            "example": ["replace_text 'Q3': 0 matches found on page 2"],
            "description": "Non-fatal issues (zero matches, font fallbacks, etc.).",
        },
        "message": {
            "type": "string",
            "example": "File does not exist.",
            "description": "Human-readable error detail. Only present on error.",
        },
    },
    requirement=["pymupdf", "pypdf"],
    test_payload={
        "file_path": "C:/path/to/document.pdf",
        "output_path": "C:/path/to/document_edited.pdf",
        "operations": [{"type": "watermark", "text": "DRAFT"}],
        "simulated_mode": True,
    },
)
def edit_pdf_file(input_data: dict) -> dict:
    import os
    import sys
    import subprocess
    import importlib

    # ── Helpers ───────────────────────────────────────────────────────────
    def _json(status, message="", output_path="", ops_applied=0, warnings=None):
        result = {
            "status": status,
            "output_path": output_path,
            "operations_applied": ops_applied,
            "warnings": warnings or [],
        }
        if message:
            result["message"] = message
        return result

    def _ensure(pkg, import_as=None):
        try:
            importlib.import_module(import_as or pkg)
        except ImportError:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

    def _hex_to_rgb(hex_color):
        """Convert '#rrggbb' or '#rgb' to (r,g,b) float tuple 0-1."""
        h = str(hex_color).lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6:
            return (0.0, 0.0, 0.0)
        return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

    def _color_int_to_rgb(color_int):
        """Convert PyMuPDF integer color to (r,g,b) float tuple."""
        r = ((color_int >> 16) & 0xFF) / 255.0
        g = ((color_int >> 8) & 0xFF) / 255.0
        b = (color_int & 0xFF) / 255.0
        return (r, g, b)

    # Base14 fonts always available in PyMuPDF — no embedding needed
    _BASE14 = {
        "Helvetica": "helv",
        "Helvetica-Bold": "hebo",
        "Helvetica-BoldOblique": "hebi",
        "Times-Roman": "tiro",
        "Times-Bold": "tibo",
        "Times-Italic": "tiit",
        "Times-BoldItalic": "tibi",
        "Courier": "cour",
        "Courier-Bold": "cobo",
        "Courier-Oblique": "coit",
        "Courier-BoldOblique": "cobi",
    }

    def _best_font(pdf_font_name):
        """
        Map any PDF font name to the nearest valid PyMuPDF Base14 shortcode.
        Returns (shortcode, was_fallback).
        """
        if pdf_font_name in _BASE14:
            return _BASE14[pdf_font_name], False
        n = pdf_font_name.lower()
        is_bold = any(x in n for x in ("bold", "demi", "black", "heavy"))
        is_italic = any(x in n for x in ("italic", "oblique", "slant"))
        if "times" in n or "roman" in n or "serif" in n:
            if is_bold and is_italic:
                return "tibi", True
            if is_bold:
                return "tibo", True
            if is_italic:
                return "tiit", True
            return "tiro", True
        if "courier" in n or "mono" in n or "typewriter" in n:
            if is_bold and is_italic:
                return "cobi", True
            if is_bold:
                return "cobo", True
            if is_italic:
                return "coit", True
            return "cour", True
        # Default: Helvetica family
        if is_bold and is_italic:
            return "hebi", True
        if is_bold:
            return "hebo", True
        return "helv", True

    def _bl_to_rect(x0, y0, x1, y1, ph):
        """
        Convert BOTTOMLEFT bbox (from read_pdf) to PyMuPDF TOPLEFT Rect.
        PyMuPDF: y=0 at top, y=ph at bottom.
        BOTTOMLEFT: y=0 at bottom, y=ph at top.
        Conversion: y_mupdf = ph - y_bottomleft
        """
        import fitz

        return fitz.Rect(x0, ph - y1, x1, ph - y0)

    def _resolve_pages(page_spec, total_pages):
        """
        Resolve page spec to list of 0-based indices.
        'all' → all pages. int → single page (1-based). 'all' default.
        """
        if page_spec == "all" or page_spec is None or page_spec == "":
            return list(range(total_pages))
        try:
            p = int(page_spec)
            if 1 <= p <= total_pages:
                return [p - 1]
            return []
        except (ValueError, TypeError):
            return list(range(total_pages))

    def _get_span_at_rect(page, target_rect):
        """
        Find the text span whose bbox best overlaps target_rect.
        Returns the span dict or None.
        """
        import fitz

        best_span = None
        best_area = 0.0
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    sr = fitz.Rect(span["bbox"])
                    overlap = sr & target_rect
                    if overlap.is_valid and overlap.get_area() > best_area:
                        best_area = overlap.get_area()
                        best_span = span
        return best_span

    # ── Input extraction ──────────────────────────────────────────────────
    simulated_mode = bool(input_data.get("simulated_mode", False))
    file_path = str(input_data.get("file_path", "")).strip()
    output_path = str(input_data.get("output_path", "")).strip()
    operations = input_data.get("operations", [])

    if not isinstance(operations, list):
        operations = []

    # ── Simulated mode ────────────────────────────────────────────────────
    if simulated_mode:
        return _json("success", output_path=output_path, ops_applied=len(operations))

    # ── Dependency bootstrap ──────────────────────────────────────────────
    _ensure("pymupdf", "fitz")
    _ensure("pypdf", "pypdf")

    import fitz
    import pypdf

    # ── Validation ────────────────────────────────────────────────────────
    if not file_path:
        return _json("error", "'file_path' is required.")
    if not output_path:
        return _json("error", "'output_path' is required.")
    if not file_path.lower().endswith(".pdf"):
        return _json("error", "Only .pdf files are supported.")
    if not output_path.lower().endswith(".pdf"):
        return _json("error", "'output_path' must end with .pdf.")
    if ".." in file_path.replace("\\", "/"):
        return _json("error", "Invalid file_path.")
    if ".." in output_path.replace("\\", "/"):
        return _json("error", "Invalid output_path.")
    if not os.path.isfile(file_path):
        return _json("error", "File does not exist.")
    if not os.access(file_path, os.R_OK):
        return _json("error", "File is not readable.")
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if size_mb > 100:
        return _json("error", f"File too large ({size_mb:.1f} MB). Max 100 MB.")
    if not operations:
        return _json("error", "'operations' list is required and must not be empty.")

    # Detect reflow operations — these require markdown_to_pdf rebuild routing
    _REFLOW_OPS = {
        "rephrase_text",
        "insert_section",
        "insert_table",
        "reformat",
        "reflow",
    }
    reflow_ops = [op.get("type") for op in operations if op.get("type") in _REFLOW_OPS]
    if reflow_ops:
        return _json(
            "error",
            f"Operation(s) {reflow_ops} require text reflow which PDF does not support. "
            "Use markdown_to_pdf to rebuild the document with the desired changes applied. "
            "Read the original with read_pdf (text mode), apply changes to the text content, "
            "then pass the updated content to markdown_to_pdf at the same output_path "
            "(it reuses the PDF's saved style, so the look is preserved).",
        )

    # ── Apply operations ──────────────────────────────────────────────────
    try:
        doc = fitz.open(file_path)
        total_pgs = len(doc)
        warnings = []
        ops_done = 0

        for i, op in enumerate(operations):
            op_type = str(op.get("type", "")).strip().lower()
            op_tag = f"op[{i}] '{op_type}'"

            try:
                # ── add_text ─────────────────────────────────────────────
                if op_type == "add_text":
                    page_idx = int(op.get("page", 1)) - 1
                    if not (0 <= page_idx < total_pgs):
                        warnings.append(
                            f"{op_tag}: page {op.get('page')} out of range."
                        )
                        continue
                    page = doc[page_idx]
                    ph = page.rect.height
                    # x,y are BOTTOMLEFT — convert y to TOPLEFT
                    x = float(op.get("x", 0))
                    y_bl = float(op.get("y", 0))
                    y_tl = ph - y_bl
                    text = str(op.get("text", ""))
                    font_size = float(op.get("font_size", 12))
                    color = _hex_to_rgb(op.get("color", "#000000"))
                    font_code, _ = _best_font(op.get("font", "Helvetica"))
                    page.insert_text(
                        fitz.Point(x, y_tl),
                        text,
                        fontname=font_code,
                        fontsize=font_size,
                        color=color,
                    )
                    ops_done += 1

                # ── redact (coord or pattern) ─────────────────────────────
                elif op_type == "redact":
                    fill_color = _hex_to_rgb(op.get("fill_color", "#000000"))
                    if "pattern" in op:
                        pattern = str(op["pattern"])
                        page_idxs = _resolve_pages(op.get("page", "all"), total_pgs)
                        hit_count = 0
                        for pi in page_idxs:
                            page = doc[pi]
                            hits = page.search_for(pattern)
                            for h in hits:
                                page.add_redact_annot(h, fill=fill_color)
                                hit_count += 1
                        for pi in page_idxs:
                            doc[pi].apply_redactions()
                        if hit_count == 0:
                            warnings.append(f"{op_tag}: pattern '{pattern}' not found.")
                        ops_done += 1
                    else:
                        page_idx = int(op.get("page", 1)) - 1
                        if not (0 <= page_idx < total_pgs):
                            warnings.append(f"{op_tag}: page out of range.")
                            continue
                        page = doc[page_idx]
                        ph = page.rect.height
                        r = _bl_to_rect(
                            float(op["x0"]),
                            float(op["y0"]),
                            float(op["x1"]),
                            float(op["y1"]),
                            ph,
                        )
                        page.add_redact_annot(r, fill=fill_color)
                        page.apply_redactions()
                        ops_done += 1

                # ── highlight / underline / strikeout ─────────────────────
                elif op_type in ("highlight", "underline", "strikeout"):
                    annot_fns = {
                        "highlight": "add_highlight_annot",
                        "underline": "add_underline_annot",
                        "strikeout": "add_strikeout_annot",
                    }
                    fn_name = annot_fns[op_type]
                    color = (
                        _hex_to_rgb(op.get("color", "#ffff00"))
                        if op_type == "highlight"
                        else None
                    )

                    if "pattern" in op:
                        pattern = str(op["pattern"])
                        page_idxs = _resolve_pages(op.get("page", "all"), total_pgs)
                        hit_count = 0
                        for pi in page_idxs:
                            page = doc[pi]
                            hits = page.search_for(pattern)
                            for h in hits:
                                annot = getattr(page, fn_name)(h)
                                if color:
                                    annot.set_colors(stroke=color)
                                annot.update()
                                hit_count += 1
                        if hit_count == 0:
                            warnings.append(f"{op_tag}: pattern '{pattern}' not found.")
                        ops_done += 1
                    else:
                        page_idx = int(op.get("page", 1)) - 1
                        if not (0 <= page_idx < total_pgs):
                            warnings.append(f"{op_tag}: page out of range.")
                            continue
                        page = doc[page_idx]
                        ph = page.rect.height
                        r = _bl_to_rect(
                            float(op["x0"]),
                            float(op["y0"]),
                            float(op["x1"]),
                            float(op["y1"]),
                            ph,
                        )
                        annot = getattr(page, fn_name)(r)
                        if color:
                            annot.set_colors(stroke=color)
                        annot.update()
                        ops_done += 1

                # ── replace_text (font-matched seamless replacement) ──────
                elif op_type == "replace_text":
                    pattern = str(op.get("pattern", ""))
                    replacement = str(op.get("replacement", ""))
                    page_idxs = _resolve_pages(op.get("page", "all"), total_pgs)
                    if not pattern:
                        warnings.append(f"{op_tag}: 'pattern' is required.")
                        continue
                    hit_count = 0
                    for pi in page_idxs:
                        page = doc[pi]
                        hits = page.search_for(pattern)
                        for h in hits:
                            span = _get_span_at_rect(page, h)
                            if span:
                                font_name = span["font"]
                                font_size = span["size"]
                                color_rgb = _color_int_to_rgb(span["color"])
                                font_code, was_fb = _best_font(font_name)
                                if was_fb:
                                    warnings.append(
                                        f"{op_tag}: font '{font_name}' not in Base14, "
                                        f"using '{font_code}' as fallback."
                                    )
                            else:
                                font_code = "helv"
                                font_size = 11.0
                                color_rgb = (0.0, 0.0, 0.0)
                            # Redact original text
                            page.add_redact_annot(h)
                            page.apply_redactions()
                            # Reinsert with same properties
                            insert_pt = fitz.Point(h.x0, h.y1 - 2)
                            page.insert_text(
                                insert_pt,
                                replacement,
                                fontname=font_code,
                                fontsize=font_size,
                                color=color_rgb,
                            )
                            hit_count += 1
                    if hit_count == 0:
                        warnings.append(f"{op_tag}: pattern '{pattern}' not found.")
                    ops_done += 1

                # ── add_text_near (form fill: insert value after label) ────
                elif op_type == "add_text_near":
                    label = str(op.get("label", ""))
                    value = str(op.get("value", ""))
                    page_idx = int(op.get("page", 1)) - 1
                    offset_x = float(op.get("offset_x", 5))
                    font_size = float(op.get("font_size", 11))
                    color = _hex_to_rgb(op.get("color", "#000000"))
                    font_code, _ = _best_font(op.get("font", "Helvetica"))
                    if not label:
                        warnings.append(f"{op_tag}: 'label' is required.")
                        continue
                    if not (0 <= page_idx < total_pgs):
                        warnings.append(f"{op_tag}: page out of range.")
                        continue
                    page = doc[page_idx]
                    hits = page.search_for(label)
                    if not hits:
                        warnings.append(
                            f"{op_tag}: label '{label}' not found on page {page_idx + 1}."
                        )
                        continue
                    label_rect = hits[0]
                    insert_pt = fitz.Point(
                        label_rect.x1 + offset_x,
                        label_rect.y1 - 2,  # baseline approx
                    )
                    page.insert_text(
                        insert_pt,
                        value,
                        fontname=font_code,
                        fontsize=font_size,
                        color=color,
                    )
                    ops_done += 1

                # ── watermark ─────────────────────────────────────────────
                elif op_type == "watermark":
                    text = str(op.get("text", "CONFIDENTIAL"))
                    font_size = float(op.get("font_size", 52))
                    color = _hex_to_rgb(op.get("color", "#bbbbbb"))
                    # opacity in insert_textbox: blend into color lightness
                    opacity = float(op.get("opacity", 0.25))
                    # Blend color toward white to simulate opacity
                    blended = tuple(c + (1.0 - c) * (1.0 - opacity) for c in color)
                    for page in doc:
                        pw, ph = page.rect.width, page.rect.height
                        rect = fitz.Rect(40, ph / 2 - 60, pw - 40, ph / 2 + 60)
                        page.insert_textbox(
                            rect,
                            text,
                            fontsize=font_size,
                            color=blended,
                            align=fitz.TEXT_ALIGN_CENTER,
                        )
                    ops_done += 1

                # ── rotate_page ───────────────────────────────────────────
                elif op_type == "rotate_page":
                    page_idx = int(op.get("page", 1)) - 1
                    degrees = int(op.get("degrees", 90))
                    if not (0 <= page_idx < total_pgs):
                        warnings.append(f"{op_tag}: page out of range.")
                        continue
                    if degrees not in (90, 180, 270, -90, -180, -270):
                        warnings.append(f"{op_tag}: degrees must be 90, 180, or 270.")
                        continue
                    # Normalize to 0-360
                    degrees = degrees % 360
                    current = doc[page_idx].rotation
                    doc[page_idx].set_rotation((current + degrees) % 360)
                    ops_done += 1

                # ── fill_field (AcroForm via pypdf) ───────────────────────
                elif op_type == "fill_field":
                    # Validate shape up-front so missing field_name is caught
                    # immediately, even if post-processing later fails wholesale.
                    if not str(op.get("field_name", "")).strip():
                        warnings.append(f"{op_tag}: 'field_name' is required.")
                    # Actual fill is deferred — see post-processing block below.

                else:
                    warnings.append(f"{op_tag}: unknown operation type '{op_type}'.")

            except KeyError as e:
                warnings.append(f"{op_tag}: missing required field {e}.")
            except Exception as e:
                warnings.append(f"{op_tag}: {type(e).__name__}: {e}.")

        # ── Write PyMuPDF output ──────────────────────────────────────────
        abs_output = os.path.abspath(output_path)
        parent = os.path.dirname(abs_output)
        if parent:
            os.makedirs(parent, exist_ok=True)

        doc.save(abs_output, garbage=4, deflate=True)
        doc.close()

        # ── Post-process: AcroForm fill_field via pypdf ───────────────────
        acroform_ops = [
            (j, op)
            for j, op in enumerate(operations)
            if str(op.get("type", "")).lower() == "fill_field"
        ]
        if acroform_ops:
            # Step 1: open the saved file — failure here means all fill_field
            # ops failed for the same upstream reason, warn per-op.
            try:
                reader = pypdf.PdfReader(abs_output)
                writer = pypdf.PdfWriter()
                writer.append(reader)
                existing_fields = reader.get_fields() or {}
            except Exception as e:
                for j, op in acroform_ops:
                    op_tag = f"op[{j}] 'fill_field'"
                    warnings.append(
                        f"{op_tag}: could not open PDF for AcroForm processing: "
                        f"{type(e).__name__}: {e}."
                    )
            else:
                # Step 2: apply each fill_field op individually so failures
                # are isolated — one bad field does not block the others.
                for j, op in acroform_ops:
                    op_tag = f"op[{j}] 'fill_field'"
                    field_name = str(op.get("field_name", "")).strip()
                    value = str(op.get("value", ""))
                    if not field_name:
                        continue  # already warned in main loop validation
                    if field_name not in existing_fields:
                        warnings.append(
                            f"{op_tag}: field '{field_name}' not found in AcroForm. "
                            f"Available: {list(existing_fields.keys())[:10]}."
                        )
                        continue
                    try:
                        for page_obj in writer.pages:
                            writer.update_page_form_field_values(
                                page_obj, {field_name: value}
                            )
                        ops_done += 1
                    except Exception as e:
                        warnings.append(f"{op_tag}: {type(e).__name__}: {e}.")

                # Step 3: write result — isolated so a disk failure does not
                # hide which fields were successfully processed.
                try:
                    with open(abs_output, "wb") as f:
                        writer.write(f)
                except Exception as e:
                    warnings.append(f"AcroForm write failed: {type(e).__name__}: {e}.")

        return _json(
            "success",
            output_path=abs_output,
            ops_applied=ops_done,
            warnings=warnings,
        )

    except PermissionError as exc:
        return _json("error", f"Permission denied: {exc}")
    except OSError as exc:
        return _json("error", f"File system error: {exc}")
    except Exception as exc:
        return _json("error", f"{type(exc).__name__}: {exc}")
