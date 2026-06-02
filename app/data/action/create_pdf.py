from agent_core import action


@action(
    name="create_pdf",
    description=(
        "Creates a visually polished PDF from Markdown content. "
        "Supports headings (# to #####), paragraphs, bullet and numbered lists, "
        "bold, italic, inline code, fenced code blocks, tables, strikethrough, "
        "blockquotes, and horizontal rules. "
        "The first # heading is rendered as a banner header. "
        "Colours, typography, and margins are read from FORMAT.md at render time. "
        "Use absolute paths only."
    ),
    mode="CLI",
    action_sets=["document_processing"],
    parallelizable=False,
    input_schema={
        "file_path": {
            "type": "string",
            "example": "C:/Users/user/Documents/my_file.pdf",
            "description": (
                "Absolute path where the PDF will be saved. "
                "Parent directories are created automatically if they do not exist. "
                "Must end with .pdf."
            ),
        },
        "content": {
            "type": "string",
            "example": (
                "# My Report\n\n## Summary\n\nThis is **bold** and *italic*.\n\n"
                "- Item 1\n- Item 2\n\n```python\nprint('hello')\n```"
            ),
            "description": (
                "Markdown-formatted content to convert into a PDF. "
                "The first # heading becomes the banner title. "
                "Supports tables (pipe syntax), fenced code blocks (```lang), "
                "and ~~strikethrough~~."
            ),
        },
        "subtitle": {
            "type": "string",
            "example": "Confidential - Internal Use Only",
            "description": (
                "Optional subtitle line shown below the title in the banner. "
                "Leave empty or omit to hide."
            ),
        },
        "page_numbers": {
            "type": "boolean",
            "example": True,
            "description": "Show 'Page N of M' in the footer. Defaults to true.",
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
            "example": "C:/Users/user/Documents/my_file.pdf",
            "description": "Absolute path of the created PDF.",
        },
        "pages": {
            "type": "integer",
            "example": 3,
            "description": "Number of pages in the generated PDF. Only present on success.",
        },
        "size_bytes": {
            "type": "integer",
            "example": 48230,
            "description": "File size in bytes. Only present on success.",
        },
        "theme_used": {
            "type": "string",
            "example": "format_md",
            "description": (
                "Always 'format_md'. Styling is derived from FORMAT.md "
                "(accent=#FF4F18, base=#141517, muted=#6B6E76). "
                "Useful for downstream actions (e.g. edit_pdf) that need to match colours."
            ),
        },
        "message": {
            "type": "string",
            "example": "Permission denied.",
            "description": "Human-readable error detail. Only present on error.",
        },
    },
    requirement=["markdown2", "fpdf2"],
    test_payload={
        "file_path": "C:/Users/user/Documents/my_file.pdf",
        "content": (
            "# My Title\n\nThis is a paragraph with **bold** text and a bullet list:\n"
            "- Item 1\n- Item 2"
        ),
        "simulated_mode": True,
    },
)
def create_pdf_file(input_data: dict) -> dict:
    # ── Input extraction ──────────────────────────────────────────────────
    simulated_mode = bool(input_data.get("simulated_mode", False))
    file_path = str(input_data.get("file_path", "")).strip()
    content = str(input_data.get("content", "")).strip()
    subtitle = str(input_data.get("subtitle", "")).strip()
    page_numbers = bool(input_data.get("page_numbers", True))

    # ── Validation ────────────────────────────────────────────────────────
    if not file_path:
        return {
            "status": "error",
            "path": "",
            "message": "The 'file_path' field is required.",
        }
    if not content:
        return {
            "status": "error",
            "path": "",
            "message": "The 'content' field is required.",
        }
    if not file_path.lower().endswith(".pdf"):
        return {
            "status": "error",
            "path": "",
            "message": "'file_path' must end with .pdf.",
        }

    if simulated_mode:
        return {"status": "success", "path": file_path, "theme_used": "format_md"}

    # ── Imports (executor pre-installs via requirement=, this is a fallback) ──
    import os
    import re
    import sys
    import subprocess
    import importlib
    from html import unescape

    def _ensure(pkg, import_as=None):
        try:
            importlib.import_module(import_as or pkg)
        except ImportError:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    _ensure("markdown2")
    _ensure("fpdf2", "fpdf")

    import markdown2
    from fpdf import FPDF
    from fpdf.fonts import TextStyle, FontFace
    from fpdf.pattern import LinearGradient
    from app.config import AGENT_FILE_SYSTEM_PATH
    from app.utils.pdf_format import load_style, build_theme as _build_theme

    # ── Style resolved from FORMAT.md (falls back to CraftBot brand defaults) ──
    _fmt = load_style(AGENT_FILE_SYSTEM_PATH / "FORMAT.md")
    t = _build_theme(_fmt)
    _MARGIN_MM = _fmt["margin_in"] * 25.4

    # ── Unicode sanitizer ─────────────────────────────────────────────────
    # fpdf2's built-in fonts (Helvetica, Courier, Times) only cover latin-1
    # (characters 0-255). Any unicode character above that range causes a
    # crash at render time. This map converts the most common offenders to
    # safe ASCII equivalents before the HTML reaches fpdf2's parser.
    # Characters with no mapping are replaced with '?'.
    _CHAR_MAP = {
        "\u2014": "--",
        "\u2013": "-",
        "\u2012": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": ",",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2026": "...",
        "\u00a0": " ",
        "\u2022": "*",
        "\u2010": "-",
        "\u2011": "-",
        "\u2015": "--",
        "\u2122": "TM",
        "\u00ae": "(R)",
        "\u00a9": "(C)",
        "\u20ac": "EUR",
        "\u00a3": "GBP",
        "\u00a5": "JPY",
        "\u2192": "->",
        "\u2190": "<-",
        "\u2191": "^",
        "\u2193": "v",
        "\u2713": "[x]",
        "\u2714": "[x]",
        "\u2717": "[ ]",
        "\u2610": "[ ]",
        "\u2611": "[x]",
        "\u00b0": "deg",
        "\u2265": ">=",
        "\u2264": "<=",
        "\u00d7": "x",
        "\u00f7": "/",
        "\u00b1": "+/-",
        "\u2248": "~=",
        "\u2260": "!=",
        "\u00b2": "^2",
        "\u00b3": "^3",
    }

    def _sanitize(text):
        decoded = unescape(text)
        out = []
        for ch in decoded:
            rep = _CHAR_MAP.get(ch)
            if rep is not None:
                out.append(rep)
            elif ord(ch) > 255:
                out.append("?")
            else:
                out.append(ch)
        return "".join(out)

    # ── Build PDF ─────────────────────────────────────────────────────────
    try:
        # Convert markdown to HTML.
        # smarty-pants is intentionally excluded: it converts -- and "quotes"
        # to unicode HTML entities that get unescaped inside fpdf2's parser
        # AFTER our sanitizer has already run, causing a crash.
        html = markdown2.markdown(
            content,
            extras=["fenced-code-blocks", "tables", "strike", "footnotes"],
        )
        html = _sanitize(html)

        # Extract the first H1 to use as the banner title, then remove it
        # from the body so it is not rendered twice.
        title_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        doc_title = (
            re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
        )
        html_body = html.replace(title_match.group(0), "", 1) if title_match else html

        # FPDF setup
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=_MARGIN_MM)
        pdf.set_margins(left=_MARGIN_MM, top=_MARGIN_MM, right=_MARGIN_MM)
        if doc_title:
            pdf.set_title(doc_title)
        pdf.set_creator("CraftBot")
        pdf.add_page()

        pw = pdf.w - pdf.l_margin - pdf.r_margin  # usable page width
        lm = pdf.l_margin
        y0 = 8  # banner top y-position
        # Banner height: scale with FORMAT.md header_height_in but floor at 30mm
        # so the title text always fits. FORMAT.md's 0.4" is a nav-bar spec; the
        # PDF banner is a title block that needs proportionally more space.
        _BASE_H = max(round(_fmt["header_height_in"] * 25.4 * 2.5), 30)
        HH = _BASE_H + (10 if subtitle else 0)

        # ── Gradient banner ───────────────────────────────────────────────
        grad = LinearGradient(lm, y0, lm + pw, y0, colors=t["hbg"])
        with pdf.use_pattern(grad):
            pdf.rect(lm, y0, pw, HH, style="F")

        if doc_title:
            pdf.set_font("Helvetica", "B", _fmt["h1_pt"])
            pdf.set_text_color(*t["htxt"])
            title_y = y0 + (HH - 20) / 2 - (5 if subtitle else 0)
            pdf.set_xy(lm + 8, title_y)
            pdf.cell(pw - 16, 12, doc_title[:72], align="L")

        if subtitle:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(200, 210, 240)
            pdf.set_xy(lm + 8, y0 + HH - 14)
            pdf.cell(pw - 16, 8, _sanitize(subtitle)[:100], align="L")

        # Thin accent rule below banner
        pdf.set_draw_color(*t["rule"])
        pdf.set_line_width(0.8)
        pdf.line(lm, y0 + HH + 1, lm + pw, y0 + HH + 1)
        pdf.set_y(y0 + HH + 7)

        # ── Heading and code styles ───────────────────────────────────────
        tag_styles = {
            "h1": TextStyle(
                font_family="Helvetica",
                font_style="B",
                font_size_pt=_fmt["h1_pt"],
                color=t["h2"],
                t_margin=10,
                b_margin=3,
            ),
            "h2": TextStyle(
                font_family="Helvetica",
                font_style="B",
                font_size_pt=_fmt["h2_pt"],
                color=t["h2"],
                t_margin=8,
                b_margin=2,
            ),
            "h3": TextStyle(
                font_family="Helvetica",
                font_style="B",
                font_size_pt=_fmt["h3_pt"],
                color=t["h3"],
                t_margin=6,
                b_margin=2,
            ),
            "h4": TextStyle(
                font_family="Helvetica",
                font_style="BI",
                font_size_pt=_fmt["body_pt"],
                color=t["h3"],
                t_margin=4,
                b_margin=1,
            ),
            "h5": TextStyle(
                font_family="Helvetica",
                font_style="I",
                font_size_pt=_fmt["small_pt"],
                color=t["h3"],
                t_margin=3,
                b_margin=1,
            ),
            "code": TextStyle(
                font_family="Courier",
                font_size_pt=_fmt["code_pt"],
                color=t["cc"],
                fill_color=t["cbg"],
            ),
            "pre": TextStyle(
                font_family="Courier",
                font_size_pt=_fmt["code_pt"],
                color=t["cc"],
                fill_color=t["cbg"],
            ),
            "a": FontFace(color=t["accent"]),
        }

        pdf.set_text_color(*t["body"])
        pdf.set_font("Helvetica", size=_fmt["body_pt"])
        pdf.write_html(
            html_body,
            font_family="Helvetica",
            tag_styles=tag_styles,
            table_line_separators=True,
            ul_bullet_char="*",
        )

        # ── Page number footer ────────────────────────────────────────────
        n_pages = len(pdf.pages)
        if page_numbers:
            for pg in range(1, n_pages + 1):
                pdf.page = pg
                pdf.set_y(-12)
                pdf.set_font("Helvetica", "I", _fmt["small_pt"])
                pdf.set_text_color(*_fmt["muted"])
                pdf.cell(0, 5, f"Page {pg} of {n_pages}", align="C")

        # ── Write to disk ─────────────────────────────────────────────────
        abs_path = os.path.abspath(file_path)
        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        pdf.output(abs_path)
        return {
            "status": "success",
            "path": abs_path,
            "pages": n_pages,
            "size_bytes": os.path.getsize(abs_path),
            "theme_used": "format_md",
        }

    except PermissionError as exc:
        return {
            "status": "error",
            "path": "",
            "message": f"Permission denied writing to '{file_path}': {exc}",
        }
    except OSError as exc:
        return {
            "status": "error",
            "path": "",
            "message": f"File system error: {exc}",
        }
    except Exception as exc:
        return {
            "status": "error",
            "path": "",
            "message": f"PDF generation failed: {type(exc).__name__}: {exc}",
        }
