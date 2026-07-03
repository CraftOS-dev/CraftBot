"""Shared PDF render engine for the <source>_to_pdf action family.

Provides:
  * resolve_style()  — 3-layer style merge: FORMAT.md defaults -> embedded style
                       (on update) -> explicit agent overrides.
  * render_markdown()/render_images() — the fpdf2 pipelines.
  * convert_markdown()/convert_images() — orchestrators used by the actions
    (read embedded style from an existing output, render, re-embed).
  * read_embedded_style()/embed_style() — style persistence in PDF metadata
    (sidecar JSON fallback) so an update keeps a doc's look unless overridden.

Heavy deps (fpdf2, markdown2, pypdf, pillow) are imported INSIDE functions:
action bodies are exec'd in a minimal namespace and these packages are pip-
installed at action-exec time via the action's requirement=[...]. Top-level
imports stay stdlib-only (this module is imported in-body, mirroring how
create_pdf imports app.utils.pdf_format).

Design: docs/design/multi-source-pdf-actions.md
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

# Style keys whose values are RGB tuples (need list<->tuple normalization for JSON).
_COLOR_KEYS = (
    "base",
    "highlight",
    "muted",
    "border",
    "surface",
    "light_grey",
    "white",
    "watermark_color",
    "code_fg",
    "code_bg",
)

# Agent-facing override key -> internal style key (colors).
_COLOR_OVERRIDES = {
    "base_color": "base",
    "accent_color": "highlight",
    "muted_color": "muted",
    "border_color": "border",
    "surface_color": "surface",
    "light_grey_color": "light_grey",
    "white_color": "white",
    "code_fg_color": "code_fg",
    "code_bg_color": "code_bg",
    "watermark_color": "watermark_color",
}
_FLOAT_OVERRIDES = (
    "h1_pt",
    "h2_pt",
    "h3_pt",
    "body_pt",
    "code_pt",
    "small_pt",
    "margin_in",
    "watermark_opacity",
)
_STR_OVERRIDES = (
    "page_size",
    "orientation",
    "header_text",
    "footer_text",
    "watermark_text",
)
_BOOL_OVERRIDES = ("banner", "page_numbers")

# Defaults for the new (non-FORMAT.md) knobs layered on top of pdf_format's dict.
_EXTRA_DEFAULTS = {
    "page_size": "A4",
    "orientation": "portrait",
    "banner": True,
    "page_numbers": True,
    "header_text": "",
    "footer_text": "",
    "watermark_text": "",
    "watermark_color": (187, 187, 187),
    "watermark_opacity": 0.25,
    "code_fg": None,  # None -> derive from palette in build_theme
    "code_bg": None,
}


def _hex_to_rgb(hex_val: Any):
    h = str(hex_val).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def _normalize_colors(style: Dict[str, Any]) -> None:
    """Coerce color values (which may arrive as lists from JSON) to tuples."""
    for k in _COLOR_KEYS:
        v = style.get(k)
        if isinstance(v, list) and len(v) == 3:
            style[k] = tuple(v)


def _apply_overrides(style: Dict[str, Any], ov: Dict[str, Any]) -> List[str]:
    """Overlay agent-supplied overrides onto the style dict. Returns ignored keys."""
    ignored: List[str] = []
    for k, v in (ov or {}).items():
        if k in _COLOR_OVERRIDES:
            rgb = _hex_to_rgb(v)
            if rgb:
                style[_COLOR_OVERRIDES[k]] = rgb
        elif k in _FLOAT_OVERRIDES:
            try:
                style[k] = float(v)
            except (TypeError, ValueError):
                pass
        elif k in _STR_OVERRIDES:
            style[k] = str(v)
        elif k in _BOOL_OVERRIDES:
            style[k] = bool(v)
        else:
            ignored.append(k)
    return ignored


def resolve_style(
    format_md_path: Optional[str] = None,
    embedded: Optional[Dict[str, Any]] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve the style. FORMAT.md is applied in EXACTLY ONE case — a brand-new
    document with no user-requested styles. Otherwise:
      * editing an existing styled doc (embedded present) -> keep its style; FORMAT.md
        is never consulted, so an edit can't silently restyle the document;
      * new doc + user-requested overrides -> brand-default floor + the user's styles
        (FORMAT.md not consulted — honor exactly what the user asked for).
    """
    from app.utils.pdf_format import load_style

    # Brand-default floor (load_style(None) reads no file) — guarantees completeness
    # without pulling FORMAT.md.
    style = load_style(None)
    for k, v in _EXTRA_DEFAULTS.items():
        style.setdefault(k, v)

    if embedded:
        # EDITING: the existing document's style is the base. Do NOT apply FORMAT.md.
        style.update(embedded)
    elif not overrides:
        # NEW from scratch + no requested styles -> FORMAT.md house style.
        style.update(load_style(format_md_path))
    # else: NEW + user-requested styles -> brand floor only; overrides applied below.
    _normalize_colors(style)

    if overrides:
        _apply_overrides(style, overrides)
    _normalize_colors(style)
    return style


def build_theme(style: Dict[str, Any]) -> Dict[str, Any]:
    """Map the resolved style to create_pdf's render-theme dict, honoring code overrides."""
    from app.utils.pdf_format import build_theme as _base_build

    t = _base_build(style)
    if style.get("code_fg"):
        t["cc"] = style["code_fg"]
    if style.get("code_bg"):
        t["cbg"] = style["code_bg"]
    return t


# ── Unicode sanitizer (fpdf2 built-in fonts are latin-1 only) ──────────────
_CHAR_MAP = {
    "—": "--",
    "–": "-",
    "‒": "-",
    "‘": "'",
    "’": "'",
    "‚": ",",
    "“": '"',
    "”": '"',
    "„": '"',
    "…": "...",
    " ": " ",
    "•": "*",
    "‐": "-",
    "‑": "-",
    "―": "--",
    "™": "TM",
    "®": "(R)",
    "©": "(C)",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "→": "->",
    "←": "<-",
    "↑": "^",
    "↓": "v",
    "✓": "[x]",
    "✔": "[x]",
    "✗": "[ ]",
    "☐": "[ ]",
    "☑": "[x]",
    "°": "deg",
    "≥": ">=",
    "≤": "<=",
    "×": "x",
    "÷": "/",
    "±": "+/-",
    "≈": "~=",
    "≠": "!=",
    "²": "^2",
    "³": "^3",
}


def _sanitize(text: str) -> str:
    from html import unescape

    out = []
    for ch in unescape(text):
        rep = _CHAR_MAP.get(ch)
        if rep is not None:
            out.append(rep)
        elif ord(ch) > 255:
            out.append("?")
        else:
            out.append(ch)
    return "".join(out)


def _fpdf_size(style: Dict[str, Any]):
    fmt = str(style.get("page_size", "A4")).lower()
    if fmt not in ("a3", "a4", "a5", "letter", "legal"):
        fmt = "a4"
    orient = (
        "L"
        if str(style.get("orientation", "portrait")).lower().startswith("l")
        else "P"
    )
    return orient, fmt


def _ensure_list_separators(markdown_text: str) -> str:
    """Insert a blank line before any list item that directly follows a
    non-blank, non-list line. markdown2 needs the separator to recognize the
    list; without it `- foo\\n- bar` glued to the preceding paragraph renders
    as one inline paragraph with literal hyphens. Skips inside fenced code
    blocks so list-like content there is untouched."""
    lines = markdown_text.split("\n")
    list_re = re.compile(r"^(\s{0,3})([-*+]|\d+\.)\s+\S")
    fence_re = re.compile(r"^\s*```")
    in_fence = False
    out: List[str] = []
    for line in lines:
        if fence_re.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and list_re.match(line) and out:
            prev = out[-1]
            if prev.strip() and not list_re.match(prev):
                out.append("")
        out.append(line)
    return "\n".join(out)


def _expand_ordered_lists(html: str) -> str:
    """Workaround fpdf2's <ol> marker-stacking bug: when an ordered list has
    multiple items (or wrapped items), every marker renders at the first
    item's y position. We replace each <ol>...<li>X</li>...</ol> with a
    single <p> block whose items are separated by <br/>, so item-to-item
    spacing is one line-height (tight) rather than full paragraph spacing."""

    def expand(m):
        body = m.group(1)
        items = re.findall(
            r"<li[^>]*>(.*?)</li>", body, flags=re.IGNORECASE | re.DOTALL
        )
        if not items:
            return ""
        lines = [
            f"&nbsp;&nbsp;{idx}. {item.strip()}" for idx, item in enumerate(items, 1)
        ]
        return "<p>" + "<br/>".join(lines) + "</p>"

    return re.sub(r"<ol[^>]*>(.*?)</ol>", expand, html, flags=re.IGNORECASE | re.DOTALL)


def _layout_images(html: str, max_width_mm: float, k: float) -> str:
    """Constrain and center each <img>:
      - if the image's natural size fits within max_width_mm: keep natural size
      - if it exceeds max_width_mm: cap width to max_width_mm (preserve aspect)
      - always wrap in <center>...</center> so the image is horizontally centered
    fpdf2's <img width="X"> attribute is in POINTS (it does width / pdf.k → mm
    internally), so the cap is converted via the supplied k (pt-per-mm).
    Skips <img> tags that already declare a width — agent overrides win."""
    max_w_pt = int(round(max_width_mm * k))
    natural_max_px = int(
        round(max_width_mm * 72 / 25.4)
    )  # fpdf2's natural-size assumption: 72dpi

    def inject(m):
        attrs = m.group(1) or ""
        if re.search(r"\bwidth\s*=", attrs, re.IGNORECASE):
            # Agent set explicit width — center, don't override.
            return f"<center>{m.group(0)}</center>"
        # Try to peek at the image's natural width to decide whether to cap.
        src_m = re.search(r'\bsrc\s*=\s*["\'](.*?)["\']', attrs, re.IGNORECASE)
        natural_fits = False
        if src_m:
            try:
                from PIL import Image

                with Image.open(src_m.group(1)) as img:
                    if img.size[0] <= natural_max_px:
                        natural_fits = True
            except Exception:
                pass  # missing/unreadable/remote → fall through to cap
        if natural_fits:
            return f"<center>{m.group(0)}</center>"
        return f'<center><img{attrs} width="{max_w_pt}"></center>'

    return re.sub(r"<img([^>]*)>", inject, html, flags=re.IGNORECASE)


def _set_line_height_attr(html: str, tags: List[str], ratio: float) -> str:
    """Inject `line-height="X"` onto every tag in `tags`. fpdf2's write_html
    honors this attribute on <p>, <ul>, and <ol> (the only paths that read it
    are the start-tag handlers for those three). Glyph size is untouched."""
    for tag in tags:
        pattern = rf"<{tag}([^>]*)>"

        def inject(m, _tag=tag):
            attrs = m.group(1) or ""
            if re.search(r"\bline-height\s*=", attrs, re.IGNORECASE):
                return m.group(0)
            return f'<{_tag}{attrs} line-height="{ratio}">'

        html = re.sub(pattern, inject, html, flags=re.IGNORECASE)
    return html


def _set_table_cellpadding(html: str, padding: float) -> str:
    """Inject `cellpadding="X"` onto every <table>. fpdf2's write_html honors
    the legacy HTML4 cellpadding attribute (in user units, mm) and adds
    horizontal+vertical padding inside each cell. Tables otherwise render with
    text flush against the cell borders."""

    def inject(m):
        attrs = m.group(1) or ""
        if re.search(r"\bcellpadding\s*=", attrs, re.IGNORECASE):
            return m.group(0)
        return f'<table{attrs} cellpadding="{padding}">'

    return re.sub(r"<table([^>]*)>", inject, html, flags=re.IGNORECASE)


def _left_align_table_cells(html: str) -> str:
    """fpdf2's write_html defaults <td> alignment to justify, which produces
    awkward inter-word gaps inside narrow cells (e.g. 'Imperium    of    Man').
    Force left-align on body cells; <th> headers keep their centered default."""

    def add_align(m):
        attrs = m.group(1) or ""
        if re.search(r"\balign\s*=", attrs, re.IGNORECASE):
            return m.group(0)
        return f'<td{attrs} align="left">'

    return re.sub(r"<td([^>]*)>", add_align, html, flags=re.IGNORECASE)


def _auto_width_tables(html: str) -> str:
    """Set proportional column widths on tables based on max cell content
    length. fpdf2's write_html otherwise distributes width equally regardless
    of content, so a 4-char column ('1987') gets the same room as a 40-char
    column. Each column is guaranteed a 12% floor so very short columns are
    still readable; the rest is split proportionally to max content length.
    fpdf2 reads column widths from the first row's <th>/<td> cells."""

    def process(table: str) -> str:
        rows = re.findall(
            r"<tr[^>]*>(.*?)</tr>", table, flags=re.IGNORECASE | re.DOTALL
        )
        if not rows:
            return table
        max_lens: List[int] = []
        for row in rows:
            cells = re.findall(
                r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.IGNORECASE | re.DOTALL
            )
            for i, cell in enumerate(cells):
                text = re.sub(r"<[^>]+>", "", cell).strip()
                w = len(text) or 1
                if i >= len(max_lens):
                    max_lens.append(w)
                else:
                    max_lens[i] = max(max_lens[i], w)
        if len(max_lens) < 2:
            return table
        n = len(max_lens)
        floor_pct = 12
        remainder = max(0, 100 - floor_pct * n)
        total = sum(max_lens) or 1
        raw = [floor_pct + (remainder * w / total) for w in max_lens]
        pcts = [int(round(r)) for r in raw]
        pcts[-1] += 100 - sum(pcts)  # fix rounding so widths sum to 100%

        first_row_match = re.search(
            r"<tr[^>]*>(.*?)</tr>", table, flags=re.IGNORECASE | re.DOTALL
        )
        if not first_row_match:
            return table
        first_row = first_row_match.group(0)
        col_idx = [0]

        def inject(cm):
            tag = cm.group(1)
            attrs = cm.group(2) or ""
            content = cm.group(3)
            i = col_idx[0]
            col_idx[0] += 1
            if i < len(pcts) and "width=" not in attrs.lower():
                attrs = f' width="{pcts[i]}%"' + attrs
            return f"<{tag}{attrs}>{content}</{tag}>"

        new_first_row = re.sub(
            r"<(t[dh])([^>]*)>(.*?)</\1>",
            inject,
            first_row,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return table.replace(first_row, new_first_row, 1)

    return re.sub(
        r"<table[^>]*>.*?</table>",
        lambda m: process(m.group(0)),
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def render_markdown(
    markdown_text: str, output_path: str, style: Dict[str, Any]
) -> Dict[str, Any]:
    """Render markdown to a styled PDF at output_path using the resolved style."""
    import markdown2
    from fpdf import FPDF
    from fpdf.fonts import TextStyle, FontFace
    from fpdf.pattern import LinearGradient

    t = build_theme(style)
    margin_mm = float(style["margin_in"]) * 25.4
    orient, fmt = _fpdf_size(style)
    banner_on = bool(style.get("banner", True))

    markdown_text = _ensure_list_separators(markdown_text)
    html = markdown2.markdown(
        markdown_text, extras=["fenced-code-blocks", "tables", "strike", "footnotes"]
    )
    # Strip in-page anchor links (e.g. TOC `[Section](#section)`). fpdf2's
    # write_html registers them as named-destination references, then errors at
    # output() because we never call set_link(name=...) on the heading. External
    # links (href="https://...") are unaffected.
    html = re.sub(
        r'<a\b[^>]*\bhref=["\']#[^"\']*["\'][^>]*>(.*?)</a>',
        r"\1",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Strip <hr> — markdown headings already provide section breaks, and an
    # <hr> rendered just above the next heading reads as visual noise. (Also
    # avoids draw-color bleed if anything upstream forgets to reset it.)
    html = re.sub(r"<hr\s*/?>", "", html, flags=re.IGNORECASE)
    # Work around fpdf2's <ol> marker-stacking bug: markers all render at the
    # first item's y position when items wrap or there are multiple items.
    # Replace each <ol> with explicitly-numbered paragraphs.
    html = _expand_ordered_lists(html)
    # Distribute table column widths proportionally to max cell content (fpdf2
    # otherwise gives every column the same width regardless of content).
    html = _auto_width_tables(html)
    # Force <td> body cells to left-align (fpdf2 defaults to justify which
    # gives ugly inter-word gaps in narrow columns).
    html = _left_align_table_cells(html)
    # Small inner cell padding so table text isn't flush against the borders.
    TABLE_CELL_PADDING = 1.5
    html = _set_table_cellpadding(html, TABLE_CELL_PADDING)
    # Inject line-height attribute on <p>/<ul>/<ol>. fpdf2's write_html honors
    # this attribute on those three tags (start-tag handlers in html.py). Glyph
    # size is unaffected — only the vertical advance per line scales. Tables
    # use a separate knob (see HTML2FPDF.TABLE_LINE_HEIGHT override around the
    # write_html call below). Edit LINE_HEIGHT_BODY to change line spacing for
    # paragraphs and lists; edit TABLE_LINE_HEIGHT for table rows.
    LINE_HEIGHT_BODY = 1.5
    html = _set_line_height_attr(html, ["p", "ul", "ol"], LINE_HEIGHT_BODY)
    # Lay out <img> tags: cap width to content area when oversized, center
    # via <center> wrapper, keep natural size when it already fits. Page
    # width depends on page_size + orientation; content area = page − 2·margin.
    _page_w_mm = {"a3": 297, "a4": 210, "a5": 148, "letter": 215.9, "legal": 215.9}.get(
        fmt, 210
    )
    _page_h_mm = {"a3": 420, "a4": 297, "a5": 210, "letter": 279.4, "legal": 355.6}.get(
        fmt, 297
    )
    _outer = _page_w_mm if orient == "P" else _page_h_mm
    _content_w_mm = _outer - 2 * margin_mm
    _k_pt_per_mm = 72 / 25.4  # fpdf2's default unit factor (mm-based FPDF)
    html = _layout_images(html, _content_w_mm, _k_pt_per_mm)
    html = _sanitize(html)

    doc_title = ""
    html_body = html
    if banner_on:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        if m:
            doc_title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            html_body = html.replace(m.group(0), "", 1)

    pdf = FPDF(orientation=orient, format=fmt)
    pdf.set_auto_page_break(auto=True, margin=margin_mm)
    pdf.set_margins(left=margin_mm, top=margin_mm, right=margin_mm)
    if doc_title:
        pdf.set_title(doc_title)
    pdf.set_creator("CraftBot")
    pdf.add_page()

    pw = pdf.w - pdf.l_margin - pdf.r_margin
    lm = pdf.l_margin
    subtitle = (
        _sanitize(str(style.get("subtitle", "")).strip())
        if style.get("subtitle")
        else ""
    )

    if doc_title:
        y0 = 8
        base_h = max(round(float(style["header_height_in"]) * 25.4 * 2.5), 30)
        # Auto-shrink the title font so long titles fit within the banner
        # rather than getting clipped at the right edge.
        title_pt = float(style["h1_pt"])
        min_pt = 14.0
        max_w = pw - 16
        pdf.set_font("Helvetica", "B", title_pt)
        while pdf.get_string_width(doc_title) > max_w and title_pt > min_pt:
            title_pt -= 1
            pdf.set_font("Helvetica", "B", title_pt)
        title_wraps = pdf.get_string_width(doc_title) > max_w
        # If still too wide at min_pt, grow the banner so multi_cell can wrap.
        hh = base_h + (10 if subtitle else 0) + (14 if title_wraps else 0)
        grad = LinearGradient(lm, y0, lm + pw, y0, colors=t["hbg"])
        with pdf.use_pattern(grad):
            pdf.rect(lm, y0, pw, hh, style="F")
        pdf.set_text_color(*t["htxt"])
        if title_wraps:
            pdf.set_xy(lm + 8, y0 + 6)
            pdf.multi_cell(pw - 16, title_pt * 0.46, doc_title, align="L")
        else:
            pdf.set_xy(lm + 8, y0 + (hh - 12) / 2 - (5 if subtitle else 0))
            pdf.cell(pw - 16, 12, doc_title, align="L")
        if subtitle:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(*t["subtitle"])
            pdf.set_xy(lm + 8, y0 + hh - 14)
            pdf.cell(pw - 16, 8, subtitle[:100], align="L")
        pdf.set_draw_color(*t["rule"])
        pdf.set_line_width(0.8)
        pdf.line(lm, y0 + hh + 1, lm + pw, y0 + hh + 1)
        pdf.set_y(y0 + hh + 7)
        # Reset draw color + line width so subsequent <hr>, list markers, and
        # table borders don't inherit the banner-rule color/thickness.
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)

    # Heading b_margin tuned smaller than fpdf2's natural ln(font_size) gap so
    # headings sit closer to the body that follows.
    #
    # DO NOT add a TextStyle for <p> or <li>: setting font_size_pt for those
    # tags in tag_styles makes fpdf2 inflate every body line's rendered size,
    # producing visibly larger glyphs than the bare set_font call below.
    # Paragraph and list rendering inherits the body font set just below.
    tag_styles = {
        "h1": TextStyle(
            font_family="Helvetica",
            font_style="B",
            font_size_pt=style["h1_pt"],
            color=t["h2"],
            t_margin=10,
            b_margin=1,
        ),
        "h2": TextStyle(
            font_family="Helvetica",
            font_style="B",
            font_size_pt=style["h2_pt"],
            color=t["h2"],
            t_margin=8,
            b_margin=1,
        ),
        "h3": TextStyle(
            font_family="Helvetica",
            font_style="B",
            font_size_pt=style["h3_pt"],
            color=t["h3"],
            t_margin=6,
            b_margin=1,
        ),
        "h4": TextStyle(
            font_family="Helvetica",
            font_style="BI",
            font_size_pt=style["body_pt"],
            color=t["h3"],
            t_margin=4,
            b_margin=0,
        ),
        "h5": TextStyle(
            font_family="Helvetica",
            font_style="I",
            font_size_pt=style["small_pt"],
            color=t["h3"],
            t_margin=3,
            b_margin=0,
        ),
        "code": TextStyle(
            font_family="Courier",
            font_size_pt=style["code_pt"],
            color=t["cc"],
            fill_color=t["cbg"],
        ),
        "pre": TextStyle(
            font_family="Courier",
            font_size_pt=style["code_pt"],
            color=t["cc"],
            fill_color=t["cbg"],
        ),
        "a": FontFace(color=t["accent"]),
    }
    pdf.set_text_color(*t["body"])
    pdf.set_font("Helvetica", size=style["body_pt"])

    # Table row line height: tables don't honor a per-tag line-height attribute,
    # but HTMLParser2FPDF reads the class constant TABLE_LINE_HEIGHT (default
    # 1.3) when laying out each row. Override it for the render and restore so
    # this doesn't leak into any other write_html caller. Bigger = taller rows.
    TABLE_LINE_HEIGHT = 1.2
    from fpdf.html import HTML2FPDF
    from fpdf.enums import YPos

    _orig_table_lh = HTML2FPDF.TABLE_LINE_HEIGHT
    HTML2FPDF.TABLE_LINE_HEIGHT = TABLE_LINE_HEIGHT

    # Bullet vertical alignment. fpdf2 draws every glyph at the cell's
    # baseline = self.y + 0.5*h + 0.3*font_size (see fpdf.py _render_styled_text_line).
    # Bullets use h = bullet_font (small), body lines use h = body_font *
    # line_height (large). The bullet's baseline ends up higher than the body
    # text's baseline, which makes the dot LOOK like it's hovering above the
    # text's x-height when line-height is increased. Shift y down before the
    # bullet render so the bullet baseline lines up with the body baseline,
    # then restore y so the body text still renders at its natural position.
    # Detected by new_y=YPos.TOP — only the bullet path uses that.
    _orig_render = pdf._render_styled_text_line
    BULLET_Y_SHIFT_RATIO = 0.18  # smaller = bullet lower, larger = bullet higher

    def _aligned_bullet_render(text_line, h=None, new_y=YPos.TOP, **kwargs):
        if new_y == YPos.TOP and h is not None:
            original_y = pdf.y
            pdf.y = original_y - h * BULLET_Y_SHIFT_RATIO
            try:
                return _orig_render(text_line, h=h, new_y=new_y, **kwargs)
            finally:
                pdf.y = original_y
        return _orig_render(text_line, h=h, new_y=new_y, **kwargs)

    pdf._render_styled_text_line = _aligned_bullet_render
    try:
        # ul_bullet_char="disc" → fpdf2's native filled-circle bullet glyph.
        # li_prefix_color colors only the bullet; <li> text stays body color.
        pdf.write_html(
            html_body,
            font_family="Helvetica",
            tag_styles=tag_styles,
            table_line_separators=True,
            ul_bullet_char="disc",
            li_prefix_color=tuple(t["accent"]),
        )
    finally:
        HTML2FPDF.TABLE_LINE_HEIGHT = _orig_table_lh
        pdf._render_styled_text_line = _orig_render

    _apply_page_furniture(pdf, style, t)

    abs_path = os.path.abspath(output_path)
    parent = os.path.dirname(abs_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    pdf.output(abs_path)
    return {"path": abs_path, "pages": len(pdf.pages)}


def _apply_page_furniture(pdf, style: Dict[str, Any], t: Dict[str, Any]) -> None:
    """Add header/footer text, page numbers, and watermark to every page."""
    header_text = _sanitize(str(style.get("header_text", "")).strip())
    footer_text = _sanitize(str(style.get("footer_text", "")).strip())
    page_numbers = bool(style.get("page_numbers", True))
    wm_text = _sanitize(str(style.get("watermark_text", "")).strip())
    n = len(pdf.pages)
    muted = style.get("muted", (107, 110, 118))

    # Watermark color blended toward white to fake opacity.
    wm_rgb = style.get("watermark_color", (187, 187, 187))
    op = float(style.get("watermark_opacity", 0.25))
    wm_blend = tuple(int(c + (255 - c) * (1.0 - op)) for c in wm_rgb)

    # Furniture is fixed-position near the page edges; disable auto page break
    # so writing a footer on a full page doesn't spill onto a new one.
    _prev_auto = pdf.auto_page_break
    _prev_bmargin = pdf.b_margin
    pdf.set_auto_page_break(False)

    for pg in range(1, n + 1):
        pdf.page = pg
        if header_text:
            pdf.set_y(6)
            pdf.set_font("Helvetica", "I", style["small_pt"])
            pdf.set_text_color(*muted)
            pdf.cell(0, 5, header_text[:120], align="C")
        if wm_text:
            pdf.set_font("Helvetica", "B", 52)
            pdf.set_text_color(*wm_blend)
            with pdf.rotation(45, pdf.w / 2, pdf.h / 2):
                pdf.set_xy(0, pdf.h / 2 - 10)
                pdf.cell(pdf.w, 20, wm_text[:40], align="C")
        if footer_text or page_numbers:
            pdf.set_y(-12)
            pdf.set_font("Helvetica", "I", style["small_pt"])
            pdf.set_text_color(*muted)
            label = footer_text[:80] if footer_text else ""
            if page_numbers:
                label = f"{label}  Page {pg} of {n}".strip()
            pdf.cell(0, 5, label, align="C")

    pdf.set_auto_page_break(_prev_auto, _prev_bmargin)


def render_images(
    image_paths: List[str], output_path: str, style: Dict[str, Any]
) -> Dict[str, Any]:
    """Render one or more images, one per page, fitted within the margins."""
    from fpdf import FPDF

    margin_mm = float(style["margin_in"]) * 25.4
    orient, fmt = _fpdf_size(style)
    pdf = FPDF(orientation=orient, format=fmt)
    pdf.set_creator("CraftBot")
    for img in image_paths:
        pdf.add_page()
        usable_w = pdf.w - 2 * margin_mm
        usable_h = pdf.h - 2 * margin_mm
        # fpdf2 keeps aspect ratio when only w or h is given; pass both as the
        # bounding box and let keep_aspect_ratio fit it.
        pdf.image(
            img,
            x=margin_mm,
            y=margin_mm,
            w=usable_w,
            h=usable_h,
            keep_aspect_ratio=True,
        )
    _apply_page_furniture(pdf, style, build_theme(style))
    abs_path = os.path.abspath(output_path)
    parent = os.path.dirname(abs_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    pdf.output(abs_path)
    return {"path": abs_path, "pages": len(pdf.pages)}


# ── Style persistence ──────────────────────────────────────────────────────
_STYLE_META_KEY = "/CraftBotStyle"


def _style_jsonable(style: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in style.items():
        out[k] = list(v) if isinstance(v, tuple) else v
    return out


def embed_style(path: str, style: Dict[str, Any]) -> None:
    """Persist the resolved style in the PDF's metadata (sidecar JSON fallback)."""
    payload = json.dumps(_style_jsonable(style))
    try:
        import pypdf

        reader = pypdf.PdfReader(path)
        writer = pypdf.PdfWriter()
        writer.append(reader)
        meta = {k: v for k, v in (reader.metadata or {}).items()}
        meta[_STYLE_META_KEY] = payload
        writer.add_metadata(meta)
        with open(path, "wb") as f:
            writer.write(f)
        return
    except Exception:
        pass
    try:
        with open(path + ".style.json", "w", encoding="utf-8") as f:
            f.write(payload)
    except Exception:
        pass


def read_embedded_style(path: str) -> Optional[Dict[str, Any]]:
    """Read a previously embedded style from a PDF (or its sidecar). None if absent."""
    if not path or not os.path.isfile(path):
        sidecar = (path or "") + ".style.json"
        if os.path.isfile(sidecar):
            try:
                with open(sidecar, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None
    try:
        import pypdf

        reader = pypdf.PdfReader(path)
        raw = (reader.metadata or {}).get(_STYLE_META_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    sidecar = path + ".style.json"
    if os.path.isfile(sidecar):
        try:
            with open(sidecar, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _format_md_path() -> Optional[str]:
    try:
        from app.config import AGENT_FILE_SYSTEM_PATH

        return str(AGENT_FILE_SYSTEM_PATH / "FORMAT.md")
    except Exception:
        return None


def convert_markdown(
    markdown_text: str,
    output_path: str,
    overrides: Optional[Dict[str, Any]] = None,
    subtitle: str = "",
) -> Dict[str, Any]:
    """Full markdown->PDF flow: reload embedded style (update), resolve, render, re-embed."""
    embedded = read_embedded_style(output_path)
    style = resolve_style(_format_md_path(), embedded, overrides)
    if subtitle:
        style["subtitle"] = subtitle
    result = render_markdown(markdown_text, output_path, style)
    embed_style(result["path"], style)
    result["size_bytes"] = os.path.getsize(result["path"])
    return result


def convert_images(
    image_paths: List[str],
    output_path: str,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full images->PDF flow with the same style resolution + persistence."""
    embedded = read_embedded_style(output_path)
    style = resolve_style(_format_md_path(), embedded, overrides)
    result = render_images(image_paths, output_path, style)
    embed_style(result["path"], style)
    result["size_bytes"] = os.path.getsize(result["path"])
    return result


__all__ = [
    "resolve_style",
    "build_theme",
    "render_markdown",
    "render_images",
    "convert_markdown",
    "convert_images",
    "read_embedded_style",
    "embed_style",
]
