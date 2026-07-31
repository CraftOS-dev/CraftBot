# -*- coding: utf-8 -*-
"""
Guards against `ErrorCategory` (agent_core/core/errors.py) drifting from its
hand-duplicated mirror in the frontend's errorCategories.ts. There's no
codegen keeping the two in sync — this test is the only thing that will
catch a renamed/added/removed category on one side and not the other.
"""

import re
from pathlib import Path

from agent_core.core.errors import ErrorCategory

_TS_FILE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "ui_layer"
    / "browser"
    / "frontend"
    / "src"
    / "constants"
    / "errorCategories.ts"
)


def _ts_category_keys() -> set[str]:
    text = _TS_FILE.read_text(encoding="utf-8")
    start = text.index("ERROR_CATEGORY_STYLE: Record<string, ErrorCategoryStyle> = {")
    end = text.index("\n}", start)
    block = text[start:end]
    # Top-level entries are indented 2 spaces and followed by `{` (the style
    # object); the nested `icon:`/`colorVar:`/`label:` fields are indented 4
    # spaces, so this only matches category keys.
    return set(re.findall(r"^  ([a-z_]+): \{", block, re.MULTILINE))


def test_error_category_sync_with_frontend():
    python_categories = {c.value for c in ErrorCategory}
    ts_categories = _ts_category_keys()

    assert ts_categories, "Failed to parse any category keys out of errorCategories.ts"
    missing_in_ts = python_categories - ts_categories
    missing_in_python = ts_categories - python_categories
    assert not missing_in_ts and not missing_in_python, (
        f"ErrorCategory (agent_core/core/errors.py) and "
        f"ERROR_CATEGORY_STYLE (errorCategories.ts) are out of sync. "
        f"In Python but not TS: {sorted(missing_in_ts)}. "
        f"In TS but not Python: {sorted(missing_in_python)}."
    )
