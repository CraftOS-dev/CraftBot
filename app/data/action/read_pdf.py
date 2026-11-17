from agent_core import action


@action(
    name="read_pdf",
    description=(
        "Reads a PDF and returns its content. "
        "mode='text' (default): returns plain text and tables — use for summarising, "
        "Q&A, and content extraction. Fast, minimal tokens. By default the output is "
        "SIMPLIFIED (just text + tables); set include_metadata=true to also get "
        "document_metadata (engine, page_count) and per-page dimensions — do this when "
        "you need the page count or extraction-engine details. "
        "mode='layout': returns per-word bounding boxes (BOTTOMLEFT origin) — use when "
        "edit_pdf or form-filling needs spatial coordinates (always includes metadata). "
        "page_range limits which pages are read (e.g. '1', '1-3', '2,4'). "
        "Digital PDFs use pdfplumber. Scanned/image PDFs fall back to OCR automatically. "
        "NOTE: this returns text/coordinates only, NOT the visual layout — to EDIT a PDF while "
        "preserving its look, use convert_from_pdf (html target) instead of rebuilding from this text."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    platforms=["windows", "linux", "darwin"],
    input_schema={
        "file_path": {
            "type": "string",
            "required": True,
            "example": "C:/path/to/document.pdf",
            "description": "Absolute path to the PDF file to read.",
        },
        "mode": {
            "type": "string",
            "required": False,
            "example": "text",
            "description": (
                "Output mode. 'text' (default): plain text + tables, minimal tokens. "
                "'layout': per-word bbox coordinates for spatial tasks like edit_pdf or form-filling."
            ),
        },
        "page_range": {
            "type": "string",
            "required": False,
            "example": "1-3",
            "description": (
                "Pages to read. Omit to read all pages. "
                "Formats: '1' (single), '1-3' (range), '1,3,5' (list)."
            ),
        },
        "include_metadata": {
            "type": "boolean",
            "required": False,
            "example": False,
            "description": (
                "False (default): text mode returns only {text, tables} — lean, for reading. "
                "True: also include document_metadata (file name, page_count, engine) and "
                "per-page width/height. Ignored in layout mode, which always includes them."
            ),
        },
    },
    output_schema={
        "status": {
            "type": "string",
            "example": "success",
            "description": "'success' or 'error'.",
        },
        "content": {
            "type": "object",
            "description": (
                "Extraction result. text mode: 'text' (string) and 'tables' (list, if any); "
                "document_metadata and pages are included only when include_metadata=true. "
                "layout mode: always contains document_metadata, pages, and 'elements' "
                "(list of words with bbox_abs, bbox_norm, is_form_field_candidate — same "
                "shape as v1 for backward compatibility)."
            ),
            "example": {
                "text": "Invoice #1042\nBill To: John Smith",
                "tables": [[["Description", "Amount"], ["Web Dev", "$1,500.00"]]],
            },
        },
        "message": {
            "type": "string",
            "example": "File does not exist.",
            "description": "Human-readable error detail. Only present on error.",
        },
    },
    requirement=["pdfplumber", "pypdfium2", "rapidocr", "pdfminer.six"],
    test_payload={
        "file_path": "C:/path/to/form.pdf",
        "simulated_mode": True,
    },
)
def read_pdf_file(input_data: dict) -> dict:
    import os
    import re

    # ── Helpers ───────────────────────────────────────────────────────────
    def _json(status, message="", content=None):
        return {"status": status, "message": message, "content": content or ""}

    _FIELD_RE = re.compile(r"(?:_{4,}|\.{4,}|—{3,}|–{3,})")

    def _is_form_blank(text):
        return bool(text and _FIELD_RE.search(text.strip()))

    def _parse_page_range(pr, total):
        """
        Parse '1', '1-3', '2,4,6' into a sorted list of 1-based page numbers.
        Returns None on invalid input so the caller can surface a clear error.
        """
        if not pr:
            return list(range(1, total + 1))
        pages = set()
        try:
            for part in str(pr).split(","):
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    s, e = part.split("-", 1)
                    start = max(1, int(s.strip()))
                    end = min(total, int(e.strip()))
                    if start > end:
                        # e.g. '5-2' — reversed range, treat as invalid
                        return None
                    pages.update(range(start, end + 1))
                else:
                    p = int(part.strip())
                    if 1 <= p <= total:
                        pages.add(p)
        except (ValueError, AttributeError):
            return None
        return sorted(pages)

    def _words_to_elements(words, page_num, pw, ph):
        """
        Convert pdfplumber word list to v1-compatible element format.
        pdfplumber uses TOPLEFT origin (top = distance from page top).
        We convert to BOTTOMLEFT so edit_pdf coordinates stay consistent
        with what v1 always produced.
        """
        out = []
        for w in words:
            x0, x1 = float(w["x0"]), float(w["x1"])
            # TOPLEFT → BOTTOMLEFT: flip y axis
            y0_bl = round(ph - float(w["bottom"]), 2)
            y1_bl = round(ph - float(w["top"]), 2)
            abs_bbox = {
                "x0": round(x0, 2),
                "y0": y0_bl,
                "x1": round(x1, 2),
                "y1": y1_bl,
                "coord_origin": "BOTTOMLEFT",
            }
            norm_bbox = {
                "x0": round(max(0.0, min(1.0, x0 / pw)), 4),
                "y0": round(max(0.0, min(1.0, y0_bl / ph)), 4),
                "x1": round(max(0.0, min(1.0, x1 / pw)), 4),
                "y1": round(max(0.0, min(1.0, y1_bl / ph)), 4),
            }
            out.append(
                {
                    "page_number": page_num,
                    "element_type": "text",
                    "text": w["text"],
                    "bbox_abs": abs_bbox,
                    "bbox_norm": norm_bbox,
                    "is_form_field_candidate": _is_form_blank(w["text"]),
                }
            )
        return out

    def _ocr_page(engine, pdf, idx, scale=2.0):
        """OCR one rendered page. Returns (lines, elements, width, height).

        Boxes come back in rendered pixels, top-left origin; they are mapped
        to PDF points with a BOTTOMLEFT origin so layout-mode coordinates
        match the pdfplumber path and edit_pdf.
        """
        page = pdf[idx]
        pw, ph = (float(v) for v in page.get_size())
        image = page.render(scale=scale).to_numpy()
        result = engine(image)
        boxes = getattr(result, "boxes", None)
        txts = getattr(result, "txts", None)
        if boxes is None or txts is None:
            return [], [], pw, ph

        items = []
        for box, text in zip(boxes, txts):
            if not text or not str(text).strip():
                continue
            xs = [float(pt[0]) / scale for pt in box]
            ys = [float(pt[1]) / scale for pt in box]
            items.append((min(xs), min(ys), max(xs), max(ys), str(text)))
        # Reading order: rows by vertical centre, then left to right.
        items.sort(key=lambda it: (round((it[1] + it[3]) / 2 / 8), it[0]))

        lines, row, row_key = [], [], None
        for x0, y0, x1, y1, text in items:
            key = round((y0 + y1) / 2 / 8)
            if row_key is not None and key != row_key:
                lines.append(" ".join(row))
                row = []
            row.append(text)
            row_key = key
        if row:
            lines.append(" ".join(row))

        elements = []
        for x0, y0, x1, y1, text in items:
            abs_bbox = {
                "x0": round(x0, 2),
                "y0": round(ph - y1, 2),
                "x1": round(x1, 2),
                "y1": round(ph - y0, 2),
                "coord_origin": "BOTTOMLEFT",
            }
            elements.append(
                {
                    "page_number": idx + 1,
                    "element_type": "text",
                    "text": text,
                    "bbox_abs": abs_bbox,
                    "bbox_norm": {
                        "x0": round(max(0.0, min(1.0, abs_bbox["x0"] / pw)), 4),
                        "y0": round(max(0.0, min(1.0, abs_bbox["y0"] / ph)), 4),
                        "x1": round(max(0.0, min(1.0, abs_bbox["x1"] / pw)), 4),
                        "y1": round(max(0.0, min(1.0, abs_bbox["y1"] / ph)), 4),
                    },
                    "is_form_field_candidate": _is_form_blank(text),
                }
            )
        return lines, elements, pw, ph

    # ── Input extraction ──────────────────────────────────────────────────
    simulated_mode = bool(input_data.get("simulated_mode", False))
    file_path = str(input_data.get("file_path", "")).strip()
    mode = str(input_data.get("mode", "text")).strip().lower()
    page_range = str(input_data.get("page_range", "")).strip()
    include_metadata = bool(input_data.get("include_metadata", False))

    if mode not in ("text", "layout"):
        mode = "text"
    if mode == "layout":
        # bboxes are the whole point of layout mode — metadata always included
        include_metadata = True

    # ── Simulated mode ────────────────────────────────────────────────────
    if simulated_mode:
        base_content = {
            "document_metadata": {
                "file_name": os.path.basename(file_path) if file_path else "test.pdf",
                "mimetype": "application/pdf",
                "page_count": 1,
                "engine": "simulated",
            },
            "pages": [{"page_number": 1, "width": 595.28, "height": 841.89}],
        }
        if mode == "layout":
            base_content["elements"] = [
                {
                    "page_number": 1,
                    "element_type": "text",
                    "text": "Test PDF content",
                    "bbox_abs": {
                        "x0": 10.0,
                        "y0": 20.0,
                        "x1": 100.0,
                        "y1": 40.0,
                        "coord_origin": "BOTTOMLEFT",
                    },
                    "bbox_norm": {"x0": 0.05, "y0": 0.02, "x1": 0.2, "y1": 0.05},
                    "is_form_field_candidate": False,
                }
            ]
        else:
            base_content["text"] = "Test PDF content"
            if not include_metadata:
                base_content = {"text": base_content["text"]}
        return _json("success", "", base_content)

    import pdfplumber
    import pypdfium2

    # ── Validation ────────────────────────────────────────────────────────
    if not file_path:
        return _json("error", "'file_path' is required.")
    if ".." in file_path.replace("\\", "/"):
        return _json("error", "Invalid file path.")
    if not os.path.isfile(file_path):
        return _json("error", "File does not exist.")
    if not os.access(file_path, os.R_OK):
        return _json("error", "File is not readable.")
    if not file_path.lower().endswith(".pdf"):
        return _json("error", "Only .pdf files are supported.")
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if size_mb > 100:
        return _json(
            "error",
            f"File too large ({size_mb:.1f} MB). Max 100 MB. "
            "If the PDF is a scanned document, consider splitting it into smaller "
            "sections first using a tool like qpdf, then read each part separately "
            "using the page_range parameter.",
        )

    # ── Primary extraction: pdfplumber ────────────────────────────────────
    try:
        pages_out = []
        text_parts = []
        all_elements = []
        all_tables = []
        scanned_page_nums = []  # pages where pdfplumber found no text

        with pdfplumber.open(file_path) as doc:
            total_pages = len(doc.pages)
            target_pages = _parse_page_range(page_range, total_pages)

            if target_pages is None:
                return _json(
                    "error",
                    f"Invalid page_range format: '{page_range}'. Use '1', '1-3', or '2,4,6'.",
                )

            for i, page in enumerate(doc.pages):
                pn = i + 1
                if pn not in target_pages:
                    continue

                pw = page.width
                ph = page.height
                pages_out.append(
                    {
                        "page_number": pn,
                        "width": round(pw, 2),
                        "height": round(ph, 2),
                    }
                )

                page_text = page.extract_text() or ""

                if page_text.strip():
                    # Digital page — pdfplumber can handle it
                    if mode == "text":
                        text_parts.append(page_text)
                        tables = page.extract_tables()
                        if tables:
                            all_tables.extend(tables)
                    else:
                        # layout mode: word-level bbox
                        words = page.extract_words()
                        all_elements.extend(_words_to_elements(words, pn, pw, ph))
                else:
                    # No extractable text on this page — could be blank or scanned.
                    # We record it but only trigger the OCR fallback if EVERY
                    # target page is empty. A single blank page in a digital PDF
                    # should not cause a full OCR run.
                    scanned_page_nums.append(pn)

        engine = "pdfplumber"
        engine_warning = ""

        # ── Fallback: OCR for scanned pages ───────────────────────────────
        # Only triggered when ALL target pages have no extractable text,
        # which reliably signals a scanned or image-only PDF.
        # A digital PDF with occasional blank pages will have text_parts
        # populated and will NOT reach this block. RapidOCR runs on ONNX
        # Runtime with its models bundled in the wheel: no torch, no
        # download at first use.
        all_text_empty = not text_parts and not all_elements
        if scanned_page_nums and all_text_empty:
            try:
                from rapidocr import RapidOCR

                engine_ocr = RapidOCR()
                pdf2 = pypdfium2.PdfDocument(file_path)
                pages_out = []
                ocr_text = []
                for pn in target_pages:
                    lines, elements, w, h = _ocr_page(engine_ocr, pdf2, pn - 1)
                    pages_out.append(
                        {"page_number": pn, "width": round(w, 2), "height": round(h, 2)}
                    )
                    if lines:
                        ocr_text.append("\n".join(lines))
                    all_elements.extend(elements)

                if ocr_text or all_elements:
                    engine = "rapidocr"
                    if mode == "text":
                        text_parts.append("\n\n".join(ocr_text))
                    else:
                        text_parts = []
                else:
                    engine_warning = (
                        "Scanned pages detected but OCR extraction returned no content."
                    )

            except Exception as exc:
                # OCR unavailable or failed: surface what pdfplumber got
                # (empty for scanned PDFs) and warn via metadata.
                engine_warning = f"Scanned pages detected but OCR fallback failed: {type(exc).__name__}."

        # ── Build output ──────────────────────────────────────────────────
        meta = {
            "file_name": os.path.basename(file_path),
            "mimetype": "application/pdf",
            "page_count": total_pages,
            "engine": engine,
        }
        if engine_warning:
            meta["engine_warning"] = engine_warning

        if mode == "text":
            content = {"text": "\n\n".join(text_parts)}
            if all_tables:
                content["tables"] = all_tables
            if include_metadata:
                content["document_metadata"] = meta
                content["pages"] = pages_out
                return _json("success", "", content)
            # Lean output drops document_metadata, so surface an OCR/engine
            # warning through the message field instead of losing it.
            return _json("success", engine_warning, content)
        else:
            content = {
                "document_metadata": meta,
                "pages": pages_out,
                "elements": all_elements,
            }

        return _json("success", "", content)

    except Exception as exc:
        return _json("error", f"{type(exc).__name__}: {exc}")
