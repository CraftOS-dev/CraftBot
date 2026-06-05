"""FORMAT.md → PDF style resolver for create_pdf and edit_pdf."""

from __future__ import annotations

import re
from pathlib import Path

# Built-in CraftBot-brand defaults — used when FORMAT.md is absent or unparseable.
# Values mirror FORMAT.md's current ## global / ## pdf sections.
_DEFAULTS: dict = {
    "base": (20, 21, 23),  # #141517
    "highlight": (255, 79, 24),  # #FF4F18
    "muted": (107, 110, 118),  # #6B6E76
    "border": (46, 47, 51),  # #2E2F33
    "surface": (30, 31, 34),  # #1E1F22
    "light_grey": (244, 244, 245),  # #F4F4F5
    "white": (255, 255, 255),
    "h1_pt": 24.0,
    "h2_pt": 17.0,
    "h3_pt": 13.0,
    "body_pt": 11.0,
    "code_pt": 10.0,
    "small_pt": 9.0,
    "margin_in": 1.0,
    "header_height_in": 0.4,
}


def _hex_to_rgb(hex_val: str) -> tuple[int, int, int] | None:
    h = str(hex_val).lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def _section(text: str, name: str) -> str:
    """Return the body of a ## <name> section up to the next ## heading."""
    pat = rf"^##\s+{re.escape(name)}\b(.*?)(?=^##\s|\Z)"
    m = re.search(pat, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


def _parse_colors(block: str) -> dict[str, tuple[int, int, int]]:
    """Extract named hex colors from a text block.

    Finds lines that name a known color role and contain a #rrggbb value.
    """
    # Longer tokens must come before their substrings so they match first and
    # prevent a line like "Highlight hover: #E64615" from being stored as highlight.
    name_map = {
        "highlight hover": None,  # consume hover variant; None = skip
        "highlight_hover": None,
        "highlight": "highlight",
        "base": "base",
        "muted": "muted",
        "border": "border",
        "surface": "surface",
        "light grey": "light_grey",
        "light gray": "light_grey",
        "white": "white",
    }
    out: dict = {}
    for line in block.splitlines():
        hexes = re.findall(r"#[0-9a-fA-F]{6}\b", line)
        if not hexes:
            continue
        ll = line.lower()
        for token, key in name_map.items():
            if token in ll:
                if key is not None:
                    rgb = _hex_to_rgb(hexes[0])
                    if rgb:
                        out[key] = rgb
                break
    return out


def _parse_pt(text: str) -> float | None:
    """Parse '22-26pt', '22–26pt', or '22pt' → midpoint float."""
    m = re.search(r"(\d+)(?:[-–](\d+))?pt", text)
    if not m:
        return None
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    return (lo + hi) / 2.0


def _parse_inches(text: str) -> float | None:
    """Return the first N\" value in a string as a float."""
    m = re.search(r'(\d+(?:\.\d+)?)\s*"', text)
    return float(m.group(1)) if m else None


def load_style(format_md_path: Path | str | None = None) -> dict:
    """Parse FORMAT.md and return a resolved style dict.

    Always returns a complete dict with every key from _DEFAULTS populated.
    Any missing or unparseable value falls back to the built-in CraftBot defaults.
    """
    style = dict(_DEFAULTS)
    if format_md_path is None:
        return style
    path = Path(format_md_path)
    if not path.is_file():
        return style
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return style

    global_block = _section(text, "global")
    pdf_block = _section(text, "pdf")

    # Colors from ## global
    for key, val in _parse_colors(global_block).items():
        style[key] = val

    # Typography pt sizes from ## global — only table rows (lines containing |)
    role_map = {
        "h1": "h1_pt",
        "h2": "h2_pt",
        "h3": "h3_pt",
        "body": "body_pt",
        "code": "code_pt",
        "small": "small_pt",
        "caption": "small_pt",
    }
    for line in global_block.splitlines():
        if "|" not in line:
            continue
        ll = line.lower()
        for role, key in role_map.items():
            if role in ll:
                pt = _parse_pt(line)
                if pt:
                    style[key] = pt
                break

    # Margin from ## pdf — look for "N" all sides" first, then fall back to
    # the first inch value that follows the word "margins?" on the line.
    # This avoids capturing the paper size (e.g. "8.5"") that appears on the
    # same line as "Margins: 1" all sides."
    for line in pdf_block.splitlines():
        if "margin" in line.lower():
            m = re.search(r'(\d+(?:\.\d+)?)\s*"\s+all', line, re.IGNORECASE)
            if m:
                style["margin_in"] = float(m.group(1))
                break
            after = re.search(r"margins?\W+(.*)", line, re.IGNORECASE)
            if after:
                v = _parse_inches(after.group(1))
                if v:
                    style["margin_in"] = v
                    break

    # Header bar height from ## pdf
    for line in pdf_block.splitlines():
        if "header" in line.lower() and '"' in line:
            v = _parse_inches(line)
            if v:
                style["header_height_in"] = v
                break

    return style


def build_theme(s: dict) -> dict:
    """Map a FORMAT.md style dict to the theme dict consumed by create_pdf's render pipeline."""
    return {
        "hbg": [
            s["base"],
            s["base"],
        ],  # solid header bar (FORMAT.md specifies no gradient)
        "accent": s["highlight"],
        "h2": s["base"],
        "h3": s["muted"],
        "body": s["base"],
        "cbg": s["light_grey"],
        "cc": s["base"],
        "rule": s["highlight"],  # orange accent rule below header banner
        "htxt": s["white"],
        "subtitle": s["light_grey"],
    }
