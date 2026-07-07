"""LIVING_UI.md requirement ledger — parser, keyed mutations, and gates.

LIVING_UI.md is THE requirement document and progress tracker for a Living
UI build: five mandatory sections (Features / Data / Design / CLI / Quality
of Life) of ID'd checkboxes between REQ:BEGIN / REQ:END markers. Checked
state changes ONLY through tick_requirements (keyed by requirement ID —
the agent names the item, the platform flips the box); making the model
reproduce ledger lines verbatim for stream_edit caused a steady stream of
old_string mismatches and retry loops. stream_edit remains valid for
REWORDING requirement text, which is genuinely a text edit. The platform
parses the ledger and refuses validation while it is missing or unfinished.

Gates are filesystem-only and fail-open, like the other Living UI guards.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REQ_BEGIN = "<!-- REQ:BEGIN -->"
REQ_END = "<!-- REQ:END -->"

# Canonical section key -> heading matcher (tolerates suffixes like
# "### Features (core capabilities)").
_SECTION_KEYS: List[Tuple[str, str]] = [
    ("features", r"features"),
    ("data", r"data"),
    ("design", r"design"),
    ("cli", r"cli"),
    ("quality", r"quality"),
]

_SECTION_LABELS = {
    "features": "Features",
    "data": "Data",
    "design": "Design",
    "cli": "CLI",
    "quality": "Quality of Life",
}

# NO numeric quotas: the depth of each section follows from the app's
# scope, judged by the workflow's prose demands and the design review —
# the platform only enforces STRUCTURE (all five sections present and
# genuinely filled) and COMPLETION (every box ticked).
REQUIRED_SECTIONS = ["features", "data", "design", "cli", "quality"]

_HEADING_RE = re.compile(r"^\s*#{2,4}\s+(.+?)\s*$")
_ITEM_RE = re.compile(r"^\s*-\s*\[( |x|X)\]\s*([A-Za-z]{1,3}\d{1,3})\s*[:.]?\s*(.*)$")


def _section_key_for(heading: str) -> Optional[str]:
    h = heading.strip().lower()
    for key, pattern in _SECTION_KEYS:
        if re.match(pattern, h):
            return key
    return None


def parse_requirements(text: str) -> Optional[Dict]:
    """Parse the REQ block. Returns
    {"sections": {key: [(id, text, done)]}, "done": n, "total": n}
    or None when no block exists."""
    try:
        start = text.index(REQ_BEGIN)
        end = text.index(REQ_END, start)
    except ValueError:
        return None
    block = text[start + len(REQ_BEGIN):end]

    sections: Dict[str, List[Tuple[str, str, bool]]] = {}
    current: Optional[str] = None
    for line in block.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            current = _section_key_for(heading.group(1))
            if current and current not in sections:
                sections[current] = []
            continue
        item = _ITEM_RE.match(line)
        if item and current:
            done = item.group(1).lower() == "x"
            sections[current].append((item.group(2), item.group(3).strip(), done))

    total = sum(len(v) for v in sections.values())
    done = sum(1 for v in sections.values() for _, _, d in v if d)
    return {"sections": sections, "done": done, "total": total}


def requirements_status(project_path) -> Optional[Dict]:
    """Parse the project's LIVING_UI.md ledger. None when file/block absent."""
    try:
        md = Path(project_path) / "LIVING_UI.md"
        if not md.exists():
            return None
        return parse_requirements(md.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def tick_requirements(project_path, ids) -> Dict:
    """Flip `- [ ] <ID>:` boxes to `- [x]` by requirement ID.

    Keyed mutation: the caller names the items, this function performs the
    edit — no verbatim string matching, so it cannot fail on text drift.
    IDs are matched case-insensitively. Everything outside the checkbox
    character is preserved byte-for-byte.

    Returns {"ticked": [...], "already": [...], "unknown": [...],
             "done": n, "total": n}. Raises ValueError when the file or
    REQ block is missing (callers surface that as an actionable error —
    this is a mutation, not a fail-open gate).
    """
    md = Path(project_path) / "LIVING_UI.md"
    if not md.exists():
        raise ValueError("LIVING_UI.md not found in the project")
    text = md.read_text(encoding="utf-8", errors="replace")
    try:
        start = text.index(REQ_BEGIN)
        end = text.index(REQ_END, start)
    except ValueError:
        raise ValueError(
            "LIVING_UI.md has no <!-- REQ:BEGIN --> ... <!-- REQ:END --> block"
        ) from None

    wanted = {str(i).strip().upper() for i in ids if str(i).strip()}
    ticked: List[str] = []
    already: List[str] = []

    block = text[start:end]
    lines = block.splitlines(keepends=True)
    for n, line in enumerate(lines):
        item = _ITEM_RE.match(line)
        if not item:
            continue
        item_id = item.group(2).upper()
        if item_id not in wanted:
            continue
        wanted.discard(item_id)
        if item.group(1).lower() == "x":
            already.append(item_id)
            continue
        # Flip exactly the checkbox character; the line is otherwise intact.
        lines[n] = line.replace("- [ ]", "- [x]", 1)
        ticked.append(item_id)

    if ticked:
        text = text[:start] + "".join(lines) + text[end:]
        md.write_text(text, encoding="utf-8")

    status = parse_requirements(text) or {"done": 0, "total": 0}
    return {
        "ticked": ticked,
        "already": already,
        "unknown": sorted(wanted),
        "done": status["done"],
        "total": status["total"],
    }


def requirements_errors(project_path) -> List[str]:
    """Validation-time gate. Empty list when the ledger is present,
    comprehensive (floors met), and fully checked. Fail-open on exceptions."""
    try:
        status = requirements_status(project_path)
        if status is None or status["total"] == 0:
            return [
                "The requirement ledger is missing or empty: LIVING_UI.md "
                "must contain the <!-- REQ:BEGIN --> ... <!-- REQ:END --> "
                "block with five sections (Features / Data / Design / CLI / "
                "Quality of Life) of ID'd checkboxes (- [ ] F1: ...). This "
                "is Phase 0 work — write the FULL, super-detailed "
                "requirements before building, then fulfill and tick every "
                "box."
            ]
        errors: List[str] = []
        sections = status["sections"]
        missing_sections = [
            _SECTION_LABELS[key]
            for key in REQUIRED_SECTIONS
            if len(sections.get(key, [])) == 0
        ]
        if missing_sections:
            errors.append(
                "The requirement ledger has missing or EMPTY sections: "
                + ", ".join(missing_sections)
                + ". All five aspects (Features / Data / Design / CLI / "
                "Quality of Life) must be genuinely covered — the depth of "
                "each section follows from this app's scope (cover it "
                "exhaustively with concrete, checkable items), not from any "
                "quota. Fill the empty sections, then continue building."
            )
        unchecked = [
            item_id
            for items in sections.values()
            for item_id, _, done in items
            if not done
        ]
        if unchecked:
            shown = ", ".join(unchecked[:20])
            more = f" (+{len(unchecked) - 20} more)" if len(unchecked) > 20 else ""
            errors.append(
                f"{len(unchecked)} requirement(s) are NOT fulfilled: {shown}"
                f"{more}. The ONLY way forward is to implement each one and "
                f"tick it via living_ui_tick_requirements(project_id, "
                f'ids=["F3", ...]), then validate again. You wrote this '
                f"ledger from the user's request — it is a commitment, not a "
                f"wishlist. Do NOT ask the user for permission to skip, "
                f"defer, or descope any item; proposing to shrink your own "
                f"committed scope is a violation and will be rejected. Do "
                f"NOT mark items out-of-scope. Resume building now."
            )
        return errors
    except Exception:
        return []


REQUIREMENTS_NOTE = (
    "NOTE — LIVING_UI.md has no requirement ledger yet. Phase 0 comes first: "
    "write the FULL requirements into the <!-- REQ:BEGIN --> block (five "
    "sections — Features / Data / Design / CLI / Quality of Life — of ID'd "
    "checkboxes, super detailed, covering the app's whole scope) BEFORE "
    "writing code. Validation refuses missing, thin, or unfinished ledgers."
)


def requirements_note(project_path) -> Optional[str]:
    """Write-time note when code is written before the ledger exists."""
    try:
        status = requirements_status(project_path)
        if status is None or status["total"] == 0:
            return REQUIREMENTS_NOTE
        return None
    except Exception:
        return None
