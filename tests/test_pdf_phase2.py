# -*- coding: utf-8 -*-
"""
Tests for the Phase-2 (native-engine) <source>_to_pdf actions.

xlsx is fully exercised (openpyxl + the themed engine). html/url/office only
have simulated-mode + validation + graceful-degradation tests here, because
WeasyPrint / a Playwright browser / LibreOffice aren't installed in CI — they
need verification on a machine with those engines.

See docs/design/multi-source-pdf-actions.md.
"""

import os

import pytest

from app.utils import pdf_convert as C


# ── pdf_convert helpers ─────────────────────────────────────────────────────


def test_page_css():
    css = C._page_css({"page_size": "Letter", "orientation": "landscape", "margin_in": 0.5})
    assert "Letter landscape" in css and "0.5in" in css


# ── xlsx_to_pdf (fully testable) ────────────────────────────────────────────

_HAS_RENDER = True
try:
    import openpyxl  # noqa: F401
    import markdown2  # noqa: F401
    import fpdf  # noqa: F401
    import pypdf  # noqa: F401
except Exception:
    _HAS_RENDER = False

renders = pytest.mark.skipif(not _HAS_RENDER, reason="openpyxl/fpdf2/markdown2/pypdf not installed")


def test_xlsx_simulated():
    from app.data.action.xlsx_to_pdf import xlsx_to_pdf

    assert xlsx_to_pdf({"output_path": "C:/x/b.pdf", "source_path": "C:/x/b.xlsx", "simulated_mode": True})["status"] == "success"


def test_xlsx_missing_source():
    from app.data.action.xlsx_to_pdf import xlsx_to_pdf

    assert xlsx_to_pdf({"output_path": "C:/x/b.pdf", "source_path": "C:/nope/x.xlsx"})["status"] == "error"


@renders
def test_xlsx_real_render(tmp_path):
    import openpyxl
    from app.data.action.xlsx_to_pdf import xlsx_to_pdf

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Scores"
    ws.append(["Name", "Score"])
    ws.append(["Alice", 10])
    ws.append(["Bob", 7])
    ws2 = wb.create_sheet("More")
    ws2.append(["K", "V"])
    ws2.append(["x", 1])
    src = tmp_path / "b.xlsx"
    wb.save(src)

    out = str(tmp_path / "b.pdf")
    r = xlsx_to_pdf({"output_path": out, "source_path": str(src), "title": "Book", "style": {"orientation": "landscape"}})
    assert r["status"] == "success" and r["rows"] == 3 and os.path.isfile(out)


# ── html_to_pdf ─────────────────────────────────────────────────────────────


def test_html_simulated():
    from app.data.action.html_to_pdf import html_to_pdf

    assert html_to_pdf({"output_path": "C:/x/p.pdf", "content": "<h1>Hi</h1>", "simulated_mode": True})["status"] == "success"


def test_html_requires_source():
    from app.data.action.html_to_pdf import html_to_pdf

    assert html_to_pdf({"output_path": "C:/x/p.pdf"})["status"] == "error"


def test_weasyprint_fallback_degrades_gracefully(tmp_path):
    # The WeasyPrint fallback must never crash on import (it throws on bare Windows).
    try:
        import weasyprint  # noqa: F401
        pytest.skip("WeasyPrint importable here; graceful-import path not exercised")
    except Exception:
        pass
    r = C._render_html_weasyprint(str(tmp_path / "p.pdf"), None, "<h1>Hi</h1>", {})
    assert r["status"] == "error" and "WeasyPrint" in r["message"]


def test_html_renders_or_degrades(tmp_path):
    # End to end via the action: Playwright primary, WeasyPrint fallback. Either it
    # renders (engine available) or returns a graceful error — never raises.
    from app.data.action.html_to_pdf import html_to_pdf

    out = str(tmp_path / "p.pdf")
    r = html_to_pdf({"output_path": out, "content": "<h1>Hi</h1><p>x</p>"})
    assert r["status"] in ("success", "error")
    if r["status"] == "success":
        assert os.path.isfile(out)
    else:
        assert r.get("message")


# ── url_to_pdf ──────────────────────────────────────────────────────────────


def test_url_simulated():
    from app.data.action.url_to_pdf import url_to_pdf

    assert url_to_pdf({"output_path": "C:/x/p.pdf", "url": "https://example.com", "simulated_mode": True})["status"] == "success"


def test_url_validates_scheme():
    from app.data.action.url_to_pdf import url_to_pdf

    assert url_to_pdf({"output_path": "C:/x/p.pdf", "url": "example.com"})["status"] == "error"


# ── office group ────────────────────────────────────────────────────────────


def test_docx_simulated():
    from app.data.action.docx_to_pdf import docx_to_pdf

    assert docx_to_pdf({"output_path": "C:/x/d.pdf", "source_path": "C:/x/d.docx", "simulated_mode": True})["status"] == "success"


def test_docx_wrong_ext(tmp_path):
    from app.data.action.docx_to_pdf import docx_to_pdf

    bad = tmp_path / "d.txt"
    bad.write_text("x")
    r = docx_to_pdf({"output_path": str(tmp_path / "d.pdf"), "source_path": str(bad)})
    assert r["status"] == "error"


def test_office_graceful_without_libreoffice(tmp_path):
    if C._find_soffice():
        pytest.skip("LibreOffice present; graceful-degradation path not exercised")
    from app.data.action.docx_to_pdf import docx_to_pdf

    src = tmp_path / "d.docx"
    src.write_bytes(b"PK\x03\x04 fake docx")  # passes existence + extension checks
    r = docx_to_pdf({"output_path": str(tmp_path / "d.pdf"), "source_path": str(src)})
    assert r["status"] == "error" and "LibreOffice" in r["message"]


# ── pdf_to_html (reconstruct-for-editing) ───────────────────────────────────


def test_pdf_to_html_simulated():
    from app.data.action.pdf_to_html import pdf_to_html

    r = pdf_to_html({"source_path": "C:/x/cv.pdf", "output_path": "C:/x/cv.html", "simulated_mode": True})
    assert r["status"] == "success"


def test_pdf_to_html_validates_extensions():
    from app.data.action.pdf_to_html import pdf_to_html

    assert pdf_to_html({"source_path": "C:/x/cv.txt", "output_path": "C:/x/cv.html"})["status"] == "error"
    assert pdf_to_html({"source_path": "C:/x/cv.pdf", "output_path": "C:/x/cv.pdf"})["status"] == "error"


def test_pdf_to_html_graceful_without_pymupdf(tmp_path):
    try:
        import fitz  # noqa: F401
        pytest.skip("PyMuPDF present; graceful-degradation path not exercised")
    except Exception:
        pass
    from app.data.action.pdf_to_html import pdf_to_html

    src = tmp_path / "cv.pdf"
    src.write_bytes(b"%PDF-1.4 fake")  # passes existence + extension checks
    r = pdf_to_html({"source_path": str(src), "output_path": str(tmp_path / "cv.html")})
    assert r["status"] == "error" and "PyMuPDF" in r["message"]


# ── pdf_to_docx ─────────────────────────────────────────────────────────────


def test_pdf_to_docx_simulated():
    from app.data.action.pdf_to_docx import pdf_to_docx

    r = pdf_to_docx({"source_path": "C:/x/d.pdf", "output_path": "C:/x/d.docx", "simulated_mode": True})
    assert r["status"] == "success"


def test_pdf_to_docx_validates_extensions():
    from app.data.action.pdf_to_docx import pdf_to_docx

    assert pdf_to_docx({"source_path": "C:/x/d.txt", "output_path": "C:/x/d.docx"})["status"] == "error"
    assert pdf_to_docx({"source_path": "C:/x/d.pdf", "output_path": "C:/x/d.pdf"})["status"] == "error"


def test_pdf_to_docx_graceful_without_pdf2docx(tmp_path):
    try:
        import pdf2docx  # noqa: F401
        pytest.skip("pdf2docx present; graceful-degradation path not exercised")
    except Exception:
        pass
    from app.data.action.pdf_to_docx import pdf_to_docx

    src = tmp_path / "d.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    r = pdf_to_docx({"source_path": str(src), "output_path": str(tmp_path / "d.docx")})
    assert r["status"] == "error" and "pdf2docx" in r["message"]
