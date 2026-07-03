# -*- coding: utf-8 -*-
"""
In-memory BM25 keyword index for memory chunks.

Sits alongside ChromaDB to backstop semantic search on terms vector embeddings
struggle with (proper nouns, dates, IDs, code identifiers). The index is fully
rebuilt from the current chunk set on every refresh — at ~200 memory items it
costs <50ms and avoids the complexity of incremental BM25 updates.
"""

from __future__ import annotations

import re
import threading
from typing import Dict, List, Optional, Tuple

try:
    from rank_bm25 import BM25Okapi
    _HAS_BM25 = True
except ImportError:
    BM25Okapi = None
    _HAS_BM25 = False

from agent_core.utils.logger import logger


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def tokenize(text: str) -> List[str]:
    """Lowercase word/number tokenizer. Keeps identifiers intact."""
    if not text:
        return []
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class BM25Index:
    """Thread-safe BM25 index keyed by chunk_id.

    On a fresh install or when ``rank_bm25`` is not installed, BM25 retrieval
    silently degrades to an empty result set. The MemoryManager then falls back
    to pure vector search, so retrieval keeps working — just without the
    keyword channel.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chunk_ids: List[str] = []
        self._tokenized: List[List[str]] = []
        self._bm25: Optional["BM25Okapi"] = None

    def rebuild(self, chunks: Dict[str, str]) -> None:
        """Rebuild the index from ``chunk_id -> raw text``.

        Args:
            chunks: Mapping of chunk_id to the searchable text body.
        """
        with self._lock:
            self._chunk_ids = list(chunks.keys())
            self._tokenized = [tokenize(chunks[cid]) for cid in self._chunk_ids]

            if not _HAS_BM25:
                self._bm25 = None
                return

            if not self._tokenized:
                self._bm25 = None
                return

            # rank_bm25 raises on empty docs; replace with a single sentinel token
            sanitized = [doc if doc else ["__empty__"] for doc in self._tokenized]
            try:
                self._bm25 = BM25Okapi(sanitized)
            except Exception as e:
                logger.warning(f"[BM25Index] Failed to build index: {e}")
                self._bm25 = None

    def search(self, query: str, top_k: int = 20) -> List[Tuple[str, float]]:
        """Return ``[(chunk_id, score)]`` sorted high-to-low. Empty when index unavailable."""
        if not query or not query.strip():
            return []

        with self._lock:
            if self._bm25 is None or not self._chunk_ids:
                return []

            tokens = tokenize(query)
            if not tokens:
                return []

            try:
                scores = self._bm25.get_scores(tokens)
            except Exception as e:
                logger.warning(f"[BM25Index] Query failed: {e}")
                return []

            indexed = [
                (self._chunk_ids[i], float(scores[i]))
                for i in range(len(self._chunk_ids))
                if scores[i] > 0
            ]
            indexed.sort(key=lambda x: x[1], reverse=True)
            return indexed[:top_k]

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._chunk_ids)

    @property
    def is_available(self) -> bool:
        """True when rank_bm25 is installed AND the index has documents."""
        return _HAS_BM25 and self.size > 0
