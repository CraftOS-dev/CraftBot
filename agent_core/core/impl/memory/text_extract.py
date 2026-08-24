# -*- coding: utf-8 -*-
"""
Text extraction for indexable files.

One shared preprocessing point for everything that reads an indexed file's
content (the memory indexer, section listing, and the read_file action), so
every consumer sees the identical text for the identical file.

Supported types:
- .md / .txt — read as-is (UTF-8, undecodable bytes replaced)
- .pdf      — TEXT LAYER ONLY via pypdf. Images, drawings, and any other
              non-text content are ignored. Each page becomes a
              ``## Page N`` section so the markdown section chunker (and
              therefore the entity-indexer's section keys) get a stable,
              meaningful structure.
"""

from __future__ import annotations

from pathlib import Path

# The closed set of file types the memory system can index.
INDEXABLE_SUFFIXES = (".md", ".txt", ".pdf")


def is_indexable_file(path: str) -> bool:
    """Whether a path's type can be indexed into memory."""
    return path.lower().endswith(INDEXABLE_SUFFIXES)


def extract_text(file_path: Path) -> str:
    """Return the text content of an indexable file.

    Raises on unreadable files — callers treat extraction failure like a
    read failure (the file is skipped and logged, never half-indexed).
    """
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        pages = []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            pages.append(f"## Page {number}\n\n{text}")
        return "\n\n".join(pages)
    return file_path.read_text(encoding="utf-8", errors="replace")
