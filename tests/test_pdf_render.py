# -*- coding: utf-8 -*-
"""
Tests for the shared PDF render engine and the markdown_to_pdf action.

Pure style-resolution tests always run; render/persistence tests require
fpdf2 + markdown2 + pypdf and skip if unavailable.

See app/utils/pdf_render.py and docs/design/multi-source-pdf-actions.md.
"""

import os
import tempfile

import pytest

from app.utils import pdf_render as R


# ── Pure style resolution (no heavy deps) ───────────────────────────────────


def test_defaults_complete():
    style = R.resolve_style(None)
    # FORMAT.md brand defaults + the extra knobs are all present.
    assert style["highlight"] == (255, 79, 24)
    assert style["page_size"] == "A4"
    assert style["orientation"] == "portrait"
    assert style["banner"] is True
    assert style["page_numbers"] is True


def test_overrides_layer():
    style = R.resolve_style(
        None,
        overrides={
            "accent_color": "#0066FF",
            "orientation": "landscape",
            "h1_pt": 30,
            "page_numbers": False,
            "watermark_text": "DRAFT",
        },
    )
    assert style["highlight"] == (0, 102, 255)
    assert style["orientation"] == "landscape"
    assert style["h1_pt"] == 30.0
    assert style["page_numbers"] is False
    assert style["watermark_text"] == "DRAFT"


def test_embedded_then_override_precedence():
    embedded = {"highlight": [10, 20, 30], "orientation": "landscape"}
    # No override -> embedded wins over FORMAT.md defaults.
    s1 = R.resolve_style(None, embedded=embedded)
    assert s1["highlight"] == (10, 20, 30)
    assert s1["orientation"] == "landscape"
    # Override beats embedded, but only for the key passed.
    s2 = R.resolve_style(None, embedded=embedded, overrides={"orientation": "portrait"})
    assert s2["orientation"] == "portrait"
    assert s2["highlight"] == (10, 20, 30)  # untouched


def test_unknown_override_keys_ignored():
    ignored = R._apply_overrides(dict(R._EXTRA_DEFAULTS), {"bogus": 1, "h1_pt": 20})
    assert "bogus" in ignored
    assert "h1_pt" not in ignored


def test_format_md_only_for_new_with_no_user_styles(tmp_path):
    # FORMAT.md sets a distinctive highlight; it must apply ONLY for a brand-new doc
    # with no user-requested styles. Editing or new+styles must NOT pull it in.
    fmt = tmp_path / "FORMAT.md"
    fmt.write_text("## global\n\n- Highlight: #00FF00\n", encoding="utf-8")
    p = str(fmt)
    brand = (255, 79, 24)  # CraftBot brand default highlight

    # 1) new + no styles -> FORMAT.md applies
    assert R.resolve_style(p)["highlight"] == (0, 255, 0)

    # 2) editing (embedded present) -> FORMAT.md NOT applied; existing style preserved
    edit = R.resolve_style(p, embedded={"orientation": "landscape"})
    assert edit["highlight"] == brand and edit["orientation"] == "landscape"

    # 3) new + user-requested styles -> FORMAT.md NOT applied
    styled = R.resolve_style(p, overrides={"margin_in": 2})
    assert styled["highlight"] == brand and styled["margin_in"] == 2.0


# ── Render + persistence (need fpdf2/markdown2/pypdf) ───────────────────────

_HAS_LIBS = True
try:  # pragma: no cover
    import markdown2  # noqa: F401
    import fpdf  # noqa: F401
    import pypdf  # noqa: F401
except Exception:  # pragma: no cover
    _HAS_LIBS = False

renders = pytest.mark.skipif(not _HAS_LIBS, reason="fpdf2/markdown2/pypdf not installed")

_MD = "# Title\n\n## Sec\n\nBody **bold** `code`.\n\n- a\n- b\n\n| X | Y |\n|---|---|\n| 1 | 2 |\n"


@renders
def test_render_and_persist_roundtrip():
    d = tempfile.mkdtemp()
    out = os.path.join(d, "r.pdf")
    res = R.convert_markdown(_MD, out)
    assert res["pages"] >= 1 and os.path.isfile(out)
    emb = R.read_embedded_style(out)
    assert emb is not None and emb["page_size"] == "A4"


@renders
def test_update_without_overrides_preserves_style():
    d = tempfile.mkdtemp()
    out = os.path.join(d, "r.pdf")
    R.convert_markdown(_MD, out, overrides={"accent_color": "#0066FF", "orientation": "landscape"})
    # Re-render with NO overrides — the customized style must survive.
    R.convert_markdown(_MD + "\n\nmore\n", out)
    emb = R.read_embedded_style(out)
    assert emb["highlight"] == [0, 102, 255]
    assert emb["orientation"] == "landscape"


@renders
def test_update_with_override_changes_only_that_key():
    d = tempfile.mkdtemp()
    out = os.path.join(d, "r.pdf")
    R.convert_markdown(_MD, out, overrides={"accent_color": "#0066FF", "orientation": "landscape"})
    R.convert_markdown(_MD, out, overrides={"orientation": "portrait"})
    emb = R.read_embedded_style(out)
    assert emb["orientation"] == "portrait"
    assert emb["highlight"] == [0, 102, 255]  # accent unchanged


# ── markdown_to_pdf action ──────────────────────────────────────────────────


def test_action_simulated():
    from app.data.action.markdown_to_pdf import markdown_to_pdf

    r = markdown_to_pdf({"output_path": "C:/x/y.pdf", "content": "# Hi", "simulated_mode": True})
    assert r["status"] == "success"


def test_action_requires_output_pdf_extension():
    from app.data.action.markdown_to_pdf import markdown_to_pdf

    r = markdown_to_pdf({"output_path": "C:/x/y.txt", "content": "# Hi"})
    assert r["status"] == "error" and ".pdf" in r["message"]


def test_action_requires_a_source():
    from app.data.action.markdown_to_pdf import markdown_to_pdf

    r = markdown_to_pdf({"output_path": "C:/x/y.pdf"})
    assert r["status"] == "error"


@renders
def test_action_real_render(tmp_path):
    from app.data.action.markdown_to_pdf import markdown_to_pdf

    out = str(tmp_path / "doc.pdf")
    r = markdown_to_pdf({"output_path": out, "content": _MD, "style": {"accent_color": "#123456"}})
    assert r["status"] == "success" and r["pages"] >= 1 and os.path.isfile(out)
