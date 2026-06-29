# -*- coding: utf-8 -*-
"""
Tests for text_to_pdf, csv_to_pdf, images_to_pdf.

Simulated-mode + validation tests always run; real renders skip if the PDF
libraries aren't installed. See docs/design/multi-source-pdf-actions.md.
"""

import os

import pytest

_HAS_LIBS = True
try:
    import markdown2  # noqa: F401
    import fpdf  # noqa: F401
    import pypdf  # noqa: F401
except Exception:
    _HAS_LIBS = False

renders = pytest.mark.skipif(not _HAS_LIBS, reason="fpdf2/markdown2/pypdf not installed")


# ── text_to_pdf ─────────────────────────────────────────────────────────────


def test_text_simulated():
    from app.data.action.text_to_pdf import text_to_pdf

    assert text_to_pdf({"output_path": "C:/x/n.pdf", "content": "hi", "simulated_mode": True})["status"] == "success"


def test_text_requires_source():
    from app.data.action.text_to_pdf import text_to_pdf

    assert text_to_pdf({"output_path": "C:/x/n.pdf"})["status"] == "error"


@renders
def test_text_real_render(tmp_path):
    from app.data.action.text_to_pdf import text_to_pdf

    out = str(tmp_path / "n.pdf")
    # Includes markdown-significant chars that must render literally, not as formatting.
    txt = "Line *one* with _under_ and # hash\n- not a bullet\nplain line"
    r = text_to_pdf({"output_path": out, "content": txt, "title": "Notes"})
    assert r["status"] == "success" and r["pages"] >= 1 and os.path.isfile(out)


# ── csv_to_pdf ──────────────────────────────────────────────────────────────


def test_csv_simulated():
    from app.data.action.csv_to_pdf import csv_to_pdf

    assert csv_to_pdf({"output_path": "C:/x/d.pdf", "source_path": "C:/x/d.csv", "simulated_mode": True})["status"] == "success"


def test_csv_missing_source():
    from app.data.action.csv_to_pdf import csv_to_pdf

    assert csv_to_pdf({"output_path": "C:/x/d.pdf", "source_path": "C:/nope/none.csv"})["status"] == "error"


@renders
def test_csv_real_render(tmp_path):
    from app.data.action.csv_to_pdf import csv_to_pdf

    csv_path = tmp_path / "d.csv"
    csv_path.write_text("Name,Score\nAlice,10\nBob,7\nPipe|Cell,3\n", encoding="utf-8")
    out = str(tmp_path / "d.pdf")
    r = csv_to_pdf({"output_path": out, "source_path": str(csv_path), "title": "Scores", "style": {"orientation": "landscape"}})
    assert r["status"] == "success" and r["rows"] == 3 and os.path.isfile(out)


# ── images_to_pdf ───────────────────────────────────────────────────────────


def test_images_simulated():
    from app.data.action.images_to_pdf import images_to_pdf

    r = images_to_pdf({"output_path": "C:/x/a.pdf", "image_paths": ["C:/x/a.png"], "simulated_mode": True})
    assert r["status"] == "success" and r["pages"] == 1


def test_images_requires_list():
    from app.data.action.images_to_pdf import images_to_pdf

    assert images_to_pdf({"output_path": "C:/x/a.pdf", "image_paths": []})["status"] == "error"


@renders
def test_images_real_render(tmp_path):
    PIL = pytest.importorskip("PIL")
    from PIL import Image
    from app.data.action.images_to_pdf import images_to_pdf

    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.png"
    Image.new("RGB", (200, 120), (200, 80, 20)).save(p1)
    Image.new("RGB", (120, 200), (20, 80, 200)).save(p2)
    out = str(tmp_path / "album.pdf")
    r = images_to_pdf({"output_path": out, "image_paths": [str(p1), str(p2)]})
    assert r["status"] == "success" and r["pages"] == 2 and os.path.isfile(out)
