"""Text / string utilities — generic, dependency-light helpers."""

from __future__ import annotations

from typing import Any, Optional

_UNSET = object()


def csv_list(text: Optional[str], default: Any = _UNSET) -> Any:
    """Split a comma-separated string into a stripped, empty-filtered list.

    Examples:
        csv_list("a, b ,c")          -> ["a", "b", "c"]
        csv_list("")                 -> []
        csv_list("", default=None)   -> None
        csv_list(None, default=[])   -> []
    """
    if not text:
        return [] if default is _UNSET else default
    return [v.strip() for v in text.split(",") if v.strip()]
