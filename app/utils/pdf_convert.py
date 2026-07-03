"""Native-engine PDF converters for the Phase-2 <source>_to_pdf actions.

  * convert_html()   — static HTML/CSS via WeasyPrint (pure-Python, no browser).
  * convert_url()    — live URL via Playwright/Chromium, run in a SUBPROCESS so
                       it never collides with the host app's asyncio loop.
  * convert_office() — docx/odt/rtf/pptx/xlsx via LibreOffice headless.

Each returns {"status","path"/"message"} and fails gracefully with an actionable
message when its engine isn't installed (these engines can't all be pip-installed
— WeasyPrint needs system libs, Playwright needs a browser binary, LibreOffice is
a system package). Heavy imports stay inside functions (action-loader constraint).

Design: docs/design/multi-source-pdf-actions.md
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional


# ── Web: page CSS from the common style knobs ──────────────────────────────
def _landscape(style: Dict[str, Any]) -> bool:
    return str((style or {}).get("orientation", "portrait")).lower().startswith("l")


def _page_size(style: Dict[str, Any]) -> str:
    s = str((style or {}).get("page_size", "A4"))
    return s if s else "A4"


def _margin_in(style: Dict[str, Any]) -> float:
    try:
        return float((style or {}).get("margin_in", 1.0))
    except (TypeError, ValueError):
        return 1.0


def _page_css(style: Dict[str, Any]) -> str:
    size = _page_size(style)
    if _landscape(style):
        size = f"{size} landscape"
    return f"@page {{ size: {size}; margin: {_margin_in(style)}in; }}"


# ── Web/HTML render via Playwright in a subprocess ─────────────────────────
# The child uses the sync Playwright API in its own process, avoiding any
# conflict with the host application's (nest_asyncio-patched) event loop.
# Chromium works on Windows/Linux/macOS — unlike WeasyPrint, which needs GTK/
# Pango/Cairo native libs and fails to import on a bare Windows box.
_PLAYWRIGHT_CHILD = r"""
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(cfg["url"], wait_until=cfg.get("wait_until", "networkidle"), timeout=cfg["timeout_ms"])
    if cfg.get("css"):
        page.add_style_tag(content=cfg["css"])
    kwargs = {"path": cfg["output_path"], "print_background": cfg.get("print_background", True)}
    if cfg.get("prefer_css_page_size"):
        kwargs["prefer_css_page_size"] = True
    if cfg.get("page_size"):
        kwargs["format"] = cfg["page_size"]
        kwargs["landscape"] = cfg.get("landscape", False)
    if cfg.get("margin"):
        m = cfg["margin"]
        kwargs["margin"] = {"top": m, "right": m, "bottom": m, "left": m}
    page.pdf(**kwargs)
    browser.close()
"""


def _run_playwright(cfg: Dict[str, Any], timeout_ms: int) -> Dict[str, Any]:
    """Run the Playwright child to render cfg['url'] → cfg['output_path']."""
    cfg_dir = tempfile.mkdtemp()
    cfg_path = os.path.join(cfg_dir, "cfg.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PLAYWRIGHT_CHILD, cfg_path],
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000 + 60,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Render timed out."}
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)
    out = cfg["output_path"]
    if proc.returncode != 0 or not os.path.isfile(out):
        err = (proc.stderr or "").strip()
        hint = ""
        if "Executable doesn't exist" in err or "playwright install" in err:
            hint = " Run `playwright install chromium` to install the browser."
        elif "No module named 'playwright'" in err:
            hint = " Install the 'playwright' package."
        return {
            "status": "error",
            "message": f"Playwright render failed: {err[:400]}{hint}",
        }
    return {"status": "success", "path": out, "size_bytes": os.path.getsize(out)}


def convert_url(
    url: str,
    output_path: str,
    style: Optional[Dict[str, Any]] = None,
    timeout_ms: int = 60000,
) -> Dict[str, Any]:
    """Render a live URL to PDF via Playwright/Chromium."""
    style = style or {}
    abs_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    cfg = {
        "url": url,
        "output_path": abs_path,
        "page_size": _page_size(style),
        "landscape": _landscape(style),
        "print_background": bool(style.get("print_background", True)),
        "margin": f"{_margin_in(style)}in",
        "css": str(style["css"]) if style.get("css") else "",
        "timeout_ms": timeout_ms,
    }
    return _run_playwright(cfg, timeout_ms)


def _render_html_weasyprint(
    output_path: str,
    source_path: Optional[str],
    html_text: Optional[str],
    style: Dict[str, Any],
) -> Dict[str, Any]:
    """Fallback HTML→PDF via WeasyPrint. Its import can fail on Windows (no GTK/Pango/
    Cairo) — caught here so it degrades gracefully rather than crashing the action."""
    try:
        from weasyprint import HTML, CSS
    except Exception as exc:  # noqa: BLE001  (import-time OSError on bare Windows)
        return {
            "status": "error",
            "message": f"WeasyPrint unavailable ({type(exc).__name__}: {exc}).",
        }
    try:
        sheets = []
        if any(k in (style or {}) for k in ("page_size", "orientation", "margin_in")):
            sheets.append(CSS(string=_page_css(style)))
        if style.get("css"):
            sheets.append(CSS(string=str(style["css"])))
        doc = (
            HTML(filename=source_path)
            if source_path
            else HTML(string=html_text or "", base_url=os.getcwd())
        )
        doc.write_pdf(output_path, stylesheets=sheets or None)
        return {
            "status": "success",
            "path": output_path,
            "size_bytes": os.path.getsize(output_path),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "message": f"WeasyPrint render failed: {type(exc).__name__}: {exc}",
        }


def convert_html(
    output_path: str,
    source_path: Optional[str] = None,
    html_text: Optional[str] = None,
    style: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Render HTML to PDF — Playwright/Chromium primary (cross-platform, incl. Windows),
    WeasyPrint fallback. Only imposes page geometry when the user explicitly sets it;
    otherwise honors the HTML's own @page (preserves a reconstructed PDF's original size).
    `style.css` is injected last."""
    from pathlib import Path

    style = style or {}
    abs_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)

    # Resolve HTML to a local file for file:// rendering.
    tmp_dir = None
    if source_path:
        html_file = os.path.abspath(source_path)
    else:
        tmp_dir = tempfile.mkdtemp()
        html_file = os.path.join(tmp_dir, "in.html")
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_text or "")

    explicit_page = any(k in style for k in ("page_size", "orientation", "margin_in"))
    cfg = {
        "url": Path(html_file).as_uri(),
        "output_path": abs_path,
        "print_background": bool(style.get("print_background", True)),
        "css": str(style["css"]) if style.get("css") else "",
        "wait_until": "load",
        "timeout_ms": 60000,
    }
    if explicit_page:
        cfg["page_size"] = _page_size(style)
        cfg["landscape"] = _landscape(style)
        cfg["margin"] = f"{_margin_in(style)}in"
    else:
        cfg["prefer_css_page_size"] = True

    try:
        res = _run_playwright(cfg, 60000)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    if res["status"] == "success":
        return res

    # Playwright unavailable/failed → try WeasyPrint (gracefully).
    fb = _render_html_weasyprint(abs_path, source_path, html_text, style)
    if fb["status"] == "success":
        return fb
    return {
        "status": "error",
        "message": f"HTML render failed. Playwright: {res.get('message', '')} | {fb.get('message', '')}",
    }


# ── Office: LibreOffice headless ───────────────────────────────────────────
def _find_soffice() -> Optional[str]:
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    for cand in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if os.path.isfile(cand):
            return cand
    return None


def convert_office(
    source_path: str, output_path: str, timeout: int = 180
) -> Dict[str, Any]:
    """Convert an office document to PDF via LibreOffice headless (native fidelity)."""
    soffice = _find_soffice()
    if not soffice:
        return {
            "status": "error",
            "message": (
                "LibreOffice not found. Install LibreOffice and ensure `soffice` is on "
                "PATH to convert office documents."
            ),
        }
    abs_out = os.path.abspath(output_path)
    out_dir = os.path.dirname(abs_out) or "."
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp()
    try:
        proc = subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                work,
                os.path.abspath(source_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(work, ignore_errors=True)
        return {"status": "error", "message": "LibreOffice conversion timed out."}
    produced = os.path.join(
        work, os.path.splitext(os.path.basename(source_path))[0] + ".pdf"
    )
    if proc.returncode != 0 or not os.path.isfile(produced):
        shutil.rmtree(work, ignore_errors=True)
        return {
            "status": "error",
            "message": f"LibreOffice conversion failed: {(proc.stderr or proc.stdout or '').strip()[:300]}",
        }
    try:
        shutil.move(produced, abs_out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {
        "status": "success",
        "path": abs_out,
        "size_bytes": os.path.getsize(abs_out),
    }


def convert_pdf_to_html(
    source_path: str, output_path: str, mode: str = "xhtml"
) -> Dict[str, Any]:
    """Extract a layout-rich HTML reconstruction of a PDF via PyMuPDF.

    The output HTML carries the original's fonts, sizes, colors, positions and
    images, so the agent can edit its text with stream_edit and re-render with
    convert_to_pdf (html format) while preserving the look — no editable source needed.
    mode: 'xhtml' (flow-based, reflows on edits) or 'html' (absolute-positioned,
    near-identical but rigid).
    """
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "message": f"PyMuPDF not available ({type(exc).__name__}: {exc}). Install pymupdf.",
        }
    if mode not in ("html", "xhtml"):
        mode = "xhtml"
    try:
        doc = fitz.open(source_path)
        bodies = []
        page_w = page_h = None
        for page in doc:
            if page_w is None:
                page_w, page_h = page.rect.width, page.rect.height
            s = page.get_text(mode)
            m = re.search(r"<body[^>]*>(.*)</body>", s, re.DOTALL | re.IGNORECASE)
            bodies.append(m.group(1) if m else s)
        n = len(doc)
        doc.close()
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "message": f"PDF→HTML extraction failed: {type(exc).__name__}: {exc}",
        }

    # Carry the source's page size into the HTML so re-rendering preserves geometry
    # (convert_to_pdf html only overrides @page when the user explicitly passes page style).
    page_css = (
        f"<style>@page {{ size: {page_w:.0f}pt {page_h:.0f}pt; margin: 0; }}</style>"
        if page_w
        else ""
    )
    sep = '\n<div style="page-break-after: always;"></div>\n'
    html = (
        f'<!DOCTYPE html>\n<html><head><meta charset="utf-8">{page_css}</head><body>\n'
        + sep.join(bodies)
        + "\n</body></html>\n"
    )
    abs_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(html)
    return {
        "status": "success",
        "path": abs_path,
        "pages": n,
        "size_bytes": os.path.getsize(abs_path),
    }


def convert_pdf_to_docx(source_path: str, output_path: str) -> Dict[str, Any]:
    """Convert a PDF to an editable Word .docx via pdf2docx (preserves text, tables,
    images and layout as closely as possible). Graceful if pdf2docx isn't installed."""
    try:
        from pdf2docx import Converter
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "message": f"pdf2docx not available ({type(exc).__name__}: {exc}). Install pdf2docx.",
        }
    try:
        abs_out = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_out) or ".", exist_ok=True)
        cv = Converter(source_path)
        try:
            cv.convert(abs_out)
        finally:
            cv.close()
        return {
            "status": "success",
            "path": abs_out,
            "size_bytes": os.path.getsize(abs_out),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "message": f"PDF→DOCX conversion failed: {type(exc).__name__}: {exc}",
        }


def office_to_pdf_impl(input_data: Dict[str, Any], allowed_exts) -> Dict[str, Any]:
    """Shared body for the office <fmt>_to_pdf actions (native LibreOffice conversion)."""
    simulated = bool(input_data.get("simulated_mode", False))
    output_path = str(input_data.get("output_path", "")).strip()
    source_path = str(input_data.get("source_path", "")).strip()
    if not output_path:
        return {"status": "error", "message": "'output_path' is required."}
    if not output_path.lower().endswith(".pdf"):
        return {"status": "error", "message": "'output_path' must end with .pdf."}
    if simulated:
        return {"status": "success", "path": output_path}
    if not source_path or not os.path.isfile(source_path):
        return {"status": "error", "message": f"source_path not found: {source_path}"}
    if not source_path.lower().endswith(tuple(allowed_exts)):
        return {
            "status": "error",
            "message": f"source must be one of {tuple(allowed_exts)}",
        }
    return convert_office(source_path, output_path)


__all__ = [
    "convert_html",
    "convert_url",
    "convert_office",
    "convert_pdf_to_html",
    "convert_pdf_to_docx",
    "office_to_pdf_impl",
]
