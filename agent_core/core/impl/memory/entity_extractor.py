# -*- coding: utf-8 -*-
"""
Lightweight heuristic entity extractor for memory chunks.

This is intentionally simple — Phase 1 just needs to surface proper-noun-like
tokens so they end up in chunk metadata (and in the BM25 corpus). Higher-quality
LLM-based NER is a future phase.

The extractor pulls:
- Capitalised multi-word sequences (proper nouns)
- Tokens that look like identifiers (CamelCase, snake_case with caps)
- Quoted strings

Stopword filtering trims common English starters that get capitalised at
sentence boundaries.
"""

from __future__ import annotations

import re
from typing import List

_STOP = {
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "to", "for",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "should", "could",
    "may", "might", "must", "can", "i", "you", "he", "she", "it", "we", "they",
    "this", "that", "these", "those", "user", "agent", "task", "action", "event",
    "memory", "system", "note", "today", "yesterday", "tomorrow", "monday",
    "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}

# Capitalised words (incl. CamelCase), optionally chained: "Trading View",
# "OpenAI", "CraftBot", "John Doe"
_PROPER_NOUN_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9]*(?:[ \-_][A-Z][A-Za-z0-9]*)*\b"
)

# Quoted strings (single or double)
_QUOTED_RE = re.compile(r"\"([^\"]{2,40})\"|'([^']{2,40})'")


def extract_entities(text: str, max_entities: int = 12) -> List[str]:
    """Extract candidate entity strings from text.

    Returns a deduplicated, order-preserving list. The cap exists so chunk
    metadata stays compact (ChromaDB stores it for every chunk).
    """
    if not text:
        return []

    seen: set[str] = set()
    out: List[str] = []

    for match in _PROPER_NOUN_RE.finditer(text):
        candidate = match.group(0).strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in _STOP:
            continue
        # Drop single-letter or pure-numeric tokens
        if len(candidate) < 2:
            continue
        if candidate.isdigit():
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(candidate)
        if len(out) >= max_entities:
            return out

    for match in _QUOTED_RE.finditer(text):
        candidate = (match.group(1) or match.group(2) or "").strip()
        if not candidate or candidate.lower() in seen:
            continue
        seen.add(candidate.lower())
        out.append(candidate)
        if len(out) >= max_entities:
            break

    return out
