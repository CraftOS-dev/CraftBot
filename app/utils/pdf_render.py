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
    "—": "--", "–": "-", "‒": "-", "‘": "'", "’": "'",
    "‚": ",", "“": '"', "”": '"', "„": '"', "…": "...",
    " ": " ", "•": "*", "‐": "-", "‑": "-", "―": "--",
    "™": "TM", "®": "(R)", "©": "(C)", "€": "EUR",
    "£": "GBP", "¥": "JPY", "→": "->", "←": "<-",
    "↑": "^", "↓": "v", "✓": "[x]", "✔": "[x]",
    "✗": "[ ]", "☐": "[ ]", "☑": "[x]", "°": "deg",
    "≥": ">=", "≤": "<=", "×": "x", "÷": "/",
    "±": "+/-", "≈": "~=", "≠": "!=", "²": "^2", "³": "^3",
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
    orient = "L" if str(style.get("orientation", "portrait")).lower().startswith("l") else "P"
    return orient, fmt


def render_markdown(markdown_text: str, output_path: str, style: Dict[str, Any]) -> Dict[str, Any]:
    """Render markdown to a styled PDF at output_path using the resolved style."""
    import markdown2
    from fpdf import FPDF
    from fpdf.fonts import TextStyle, FontFace
    from fpdf.pattern import LinearGradient

    t = build_theme(style)
    margin_mm = float(style["margin_in"]) * 25.4
    orient, fmt = _fpdf_size(style)
    banner_on = bool(style.get("banner", True))

    html = markdown2.markdown(
        markdown_text, extras=["fenced-code-blocks", "tables", "strike", "footnotes"]
    )
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
    subtitle = _sanitize(str(style.get("subtitle", "")).strip()) if style.get("subtitle") else ""

    if doc_title:
        y0 = 8
        base_h = max(round(float(style["header_height_in"]) * 25.4 * 2.5), 30)
        hh = base_h + (10 if subtitle else 0)
        grad = LinearGradient(lm, y0, lm + pw, y0, colors=t["hbg"])
        with pdf.use_pattern(grad):
            pdf.rect(lm, y0, pw, hh, style="F")
        pdf.set_font("Helvetica", "B", style["h1_pt"])
        pdf.set_text_color(*t["htxt"])
        pdf.set_xy(lm + 8, y0 + (hh - 12) / 2 - (5 if subtitle else 0))
        pdf.cell(pw - 16, 12, doc_title[:72], align="L")
        if subtitle:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(*t["subtitle"])
            pdf.set_xy(lm + 8, y0 + hh - 14)
            pdf.cell(pw - 16, 8, subtitle[:100], align="L")
        pdf.set_draw_color(*t["rule"])
        pdf.set_line_width(0.8)
        pdf.line(lm, y0 + hh + 1, lm + pw, y0 + hh + 1)
        pdf.set_y(y0 + hh + 7)

    tag_styles = {
        "h1": TextStyle(font_family="Helvetica", font_style="B", font_size_pt=style["h1_pt"], color=t["h2"], t_margin=10, b_margin=3),
        "h2": TextStyle(font_family="Helvetica", font_style="B", font_size_pt=style["h2_pt"], color=t["h2"], t_margin=8, b_margin=2),
        "h3": TextStyle(font_family="Helvetica", font_style="B", font_size_pt=style["h3_pt"], color=t["h3"], t_margin=6, b_margin=2),
        "h4": TextStyle(font_family="Helvetica", font_style="BI", font_size_pt=style["body_pt"], color=t["h3"], t_margin=4, b_margin=1),
        "h5": TextStyle(font_family="Helvetica", font_style="I", font_size_pt=style["small_pt"], color=t["h3"], t_margin=3, b_margin=1),
        "code": TextStyle(font_family="Courier", font_size_pt=style["code_pt"], color=t["cc"], fill_color=t["cbg"]),
        "pre": TextStyle(font_family="Courier", font_size_pt=style["code_pt"], color=t["cc"], fill_color=t["cbg"]),
        "a": FontFace(color=t["accent"]),
    }
    pdf.set_text_color(*t["body"])
    pdf.set_font("Helvetica", size=style["body_pt"])
    pdf.write_html(html_body, font_family="Helvetica", tag_styles=tag_styles, table_line_separators=True, ul_bullet_char="*")

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


def render_images(image_paths: List[str], output_path: str, style: Dict[str, Any]) -> Dict[str, Any]:
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
        pdf.image(img, x=margin_mm, y=margin_mm, w=usable_w, h=usable_h, keep_aspect_ratio=True)
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
