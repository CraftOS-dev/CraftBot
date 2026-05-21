# -*- coding: utf-8 -*-
"""File utility helpers for agent-core."""

from pathlib import Path

# Maximum size (bytes) for append-only MD logs before trimming (default: 10 MB)
MAX_MD_FILE_BYTES = 10 * 1024 * 1024


def rotate_md_file_if_needed(
    file_path: Path, max_bytes: int = MAX_MD_FILE_BYTES
) -> None:
    """Drop the oldest 1/3 of lines from *file_path* when it exceeds *max_bytes*.

    The file is trimmed in-place: the most recent 2/3 of lines are kept so the
    agent never loses recent context and no extra archive files are created.
    """
    try:
        if not file_path.exists() or file_path.stat().st_size < max_bytes:
            return
        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        keep_from = len(lines) // 3  # drop oldest 1/3, keep newest 2/3
        file_path.write_text("".join(lines[keep_from:]), encoding="utf-8")
    except Exception:
        pass  # Never block a write due to trim failure
