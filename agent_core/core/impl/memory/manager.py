# -*- coding: utf-8 -*-
"""
Memory Manager for the Agent File System.

This module provides a RAG-based memory system that:
- Chunks the agent file system (markdown files) into semantic sections
- Stores chunks in ChromaDB for fast retrieval (uses ChromaDB's built-in embeddings)
- Supports retrieval via semantic query (returns pointers, not full content)
- Supports incremental updates (only re-index changed files/sections)

The memory manager returns "memory pointers" - small pieces of information
that tell the agent WHERE to find the full content, rather than returning
the full content directly. This keeps retrieval lightweight.
"""

from __future__ import annotations

import hashlib
import re
import os as _os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb

from agent_core.utils.logger import logger
from agent_core.core.impl.memory.bm25_index import BM25Index
from agent_core.core.impl.memory.entity_extractor import extract_entities


# Files that are flat lists of "[timestamp] [category] content" items.
# These get per-item chunking so each fact has its own embedding, instead of
# the whole list collapsing into a single section chunk under "## Memory".
PER_ITEM_FILES = frozenset({"MEMORY.md", "EVENT_UNPROCESSED.md"})

# Matches a memory item line. Tolerates both "/" and "-" date separators and
# either "[YYYY-MM-DD HH:MM:SS]" (MEMORY.md) or "[YYYY/MM/DD HH:MM:SS]"
# (EVENT_UNPROCESSED.md). Captures: timestamp, category, content.
MEMORY_ITEM_LINE_RE = re.compile(
    r"^\s*\[(\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2})\]\s+\[([\w\-]+)\]\s*:?\s*(.+?)\s*$"
)

# Hybrid-retrieval weights. Vector is the primary signal, BM25 backstops
# proper nouns and dates.
HYBRID_WEIGHTS = {
    "vector": 0.65,
    "bm25": 0.35,
}

# Log-line preview limits. Keep multi-line queries and long summaries from
# bleeding across log entries.
_LOG_QUERY_MAX_CHARS = 300
_LOG_SUMMARY_MAX_CHARS = 120


def _log_preview(text: str, max_chars: int) -> str:
    """Collapse whitespace and truncate text for safe logging."""
    flat = " ".join((text or "").split())
    if len(flat) <= max_chars:
        return flat
    return flat[: max_chars - 3] + "..."


def _is_embedding_function_conflict(err: Exception) -> bool:
    """Detect ChromaDB's "embedding function mismatch" ValueError by message."""
    msg = str(err).lower()
    return "embedding function" in msg and (
        "conflict" in msg or "already exists" in msg
    )


# ───────────────────────── Embedding Model ─────────────────────────
# ChromaDB's default is sentence-transformers/all-MiniLM-L6-v2 (22M params,
# 2021). Verbatim self-similarity scores ~0.65; topical matches sit at
# ~0.50; noise floor is ~0.45. That ~0.05 dynamic range can't support
# accurate retrieval no matter how the downstream scoring is tuned.
#
# BGE-small-en-v1.5 (33M params, 384-dim, same dimensionality as MiniLM
# so we don't break anything else) typically scores ~0.92 on verbatim
# matches, ~0.75 on topical, and drops below 0.50 for unrelated content.
# That's the dynamic range hybrid scoring actually needs.
#
# Override via the MEMORY_EMBEDDING_MODEL env var if you want to try
# bge-base-en-v1.5 (better, slower), e5-small-v2, or any other
# sentence-transformers model. Set to "default" to use ChromaDB's
# bundled ONNX MiniLM.
MEMORY_EMBEDDING_MODEL = _os.environ.get(
    "MEMORY_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"
)


# ───────────────────────────── Data Classes ─────────────────────────────


@dataclass
class MemoryChunk:
    """
    Represents a chunk of memory from the agent file system.

    A chunk is a semantic unit (usually a section) from a markdown file.
    It stores both the content and metadata needed for retrieval and updates.
    """

    chunk_id: str  # Unique identifier for this chunk
    file_path: str  # Relative path from agent_file_system root
    section_path: (
        str  # Hierarchical path of headers (e.g., "## Overview > ### Details")
    )
    title: str  # Section title (last header in path)
    content: str  # Full content of this chunk
    summary: str  # Brief summary for the pointer (first ~150 chars)
    content_hash: str  # Hash of content for change detection
    file_modified_at: str  # File modification timestamp
    indexed_at: str  # When this chunk was indexed
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata

    def to_pointer(self) -> Dict[str, Any]:
        """
        Convert to a memory pointer - a lightweight reference to this chunk.

        The pointer contains enough information for the agent to know:
        1. Where to find the full content (file_path, section_path)
        2. What the content is about (title, summary)
        3. How relevant it might be (metadata)
        """
        return {
            "chunk_id": self.chunk_id,
            "file_path": self.file_path,
            "section_path": self.section_path,
            "title": self.title,
            "summary": self.summary,
            "metadata": self.metadata,
        }


@dataclass
class MemoryPointer:
    """
    A lightweight reference to a memory chunk.

    This is what the retrieve() method returns - not the full content,
    but a pointer showing the agent where to find relevant information.
    """

    chunk_id: str
    file_path: str
    section_path: str
    title: str
    summary: str
    relevance_score: float  # Similarity score from vector search
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.file_path}] {self.section_path} - {self.summary[:50]}..."


@dataclass
class FileIndex:
    """
    Tracks the indexed state of a file for incremental updates.
    """

    file_path: str
    content_hash: str  # Hash of entire file content
    modified_at: str  # File modification timestamp
    chunk_ids: List[str] = field(default_factory=list)  # IDs of chunks from this file
    indexed_at: str = ""  # When this file was last indexed


# ───────────────────────────── Memory Manager ─────────────────────────────


class MemoryManager:
    """
    Manages the agent's memory system backed by ChromaDB.

    The memory manager indexes the agent file system (markdown files) and
    provides semantic retrieval. It returns "pointers" rather than full
    content, acting as a table of contents that shows the agent where to
    find relevant information.

    Key features:
    - Semantic chunking: Splits markdown by sections/headers
    - Incremental updates: Only re-indexes changed files
    - Pointer-based retrieval: Returns lightweight references, not full content
    - Duplicate detection: Prevents duplicate chunks in the index

    Usage:
        manager = MemoryManager(
            agent_file_system_path="./agent_file_system",
            chroma_path="./chroma_db_memory"
        )

        # Initial indexing
        manager.index_all()

        # Retrieve relevant memory pointers
        pointers = manager.retrieve("user preferences for communication")

        # Update after file changes
        manager.update()
    """

    # v2 collections use cosine distance and per-item chunking. The "_v2"
    # suffix forces a clean rebuild on first run with the new code — old
    # "agent_memory" collections are left intact but unused (so a downgrade
    # is non-destructive). Drop the old collections manually if disk is
    # tight; the manager never reads them.
    COLLECTION_NAME = "agent_memory_v2"
    FILE_INDEX_COLLECTION = "agent_memory_file_index_v2"

    def __init__(
        self,
        agent_file_system_path: str = "./agent_file_system",
        chroma_path: str = "./chroma_db_memory",
        chunk_size_limit: int = 1500,  # Max chars per chunk
        chunk_overlap: int = 100,  # Overlap between chunks when splitting large sections
    ):
        """
        Initialize the Memory Manager.

        Args:
            agent_file_system_path: Path to the agent file system directory
            chroma_path: Path for ChromaDB persistence
            chunk_size_limit: Maximum characters per chunk before splitting
            chunk_overlap: Character overlap when splitting large chunks
        """
        self.agent_fs_path = Path(agent_file_system_path).resolve()
        self.chroma_path = chroma_path
        self.chunk_size_limit = chunk_size_limit
        self.chunk_overlap = chunk_overlap

        # Initialize ChromaDB.
        # hnsw:space=cosine — cosine similarity gives well-scaled scores in
        # [0,1] for the hybrid retriever and behaves better than L2 on the
        # short factual snippets that dominate MEMORY.md.
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)

        # Build the embedding function. Default ChromaDB uses MiniLM-L6-v2
        # (weak — ~0.65 verbatim self-similarity). MEMORY_EMBEDDING_MODEL
        # points to a stronger sentence-transformers model by default.
        # Silent fallback to ChromaDB's bundled MiniLM if sentence-transformers
        # isn't installed, so the system keeps working on minimal installs.
        embedding_fn = self._build_embedding_function()

        self.collection = self._open_collection(
            name=self.COLLECTION_NAME,
            embedding_fn=embedding_fn,
            metadata={
                "description": "Agent file system memory chunks (v2)",
                "hnsw:space": "cosine",
                "embedding_model": MEMORY_EMBEDDING_MODEL,
            },
        )

        # File index collection (tracks which files are indexed and their hashes)
        self.file_index_collection = self._open_collection(
            name=self.FILE_INDEX_COLLECTION,
            embedding_fn=embedding_fn,
            metadata={"description": "File index for incremental updates (v2)"},
        )

        # In-memory cache of file indices
        self._file_index_cache: Dict[str, FileIndex] = {}
        self._load_file_index_cache()

        # BM25 keyword index — mirrors ChromaDB's chunk set. Rebuilt lazily
        # on first query and after each index mutation.
        self._bm25 = BM25Index()
        self._bm25_dirty = True

        logger.info(
            f"MemoryManager initialized. Agent FS: {self.agent_fs_path}, "
            f"ChromaDB: {chroma_path}, embedding model: {MEMORY_EMBEDDING_MODEL}"
        )

    # ───────────────────────────── Embedding ─────────────────────────────

    def _open_collection(self, name: str, embedding_fn, metadata: Dict[str, Any]):
        """Open a Chroma collection, auto-rebuilding on embedding mismatch.

        ChromaDB persists the embedding-function name in the collection config
        and refuses get_or_create with a different one — happens when the
        collection was first created without sentence-transformers loadable
        and is reopened later with a real model. The index is a derived cache
        (source of truth is the markdown files), so dropping and rebuilding
        is safe; update() repopulates from disk on next call.
        """
        try:
            return self.chroma_client.get_or_create_collection(
                name=name,
                embedding_function=embedding_fn,
                metadata=metadata,
            )
        except ValueError as e:
            if not _is_embedding_function_conflict(e):
                raise

        logger.warning(
            f"[MEMORY] Embedding-function mismatch on '{name}' — dropping and "
            f"rebuilding; index will repopulate from agent_file_system on next update()."
        )
        self.chroma_client.delete_collection(name)
        return self.chroma_client.create_collection(
            name=name,
            embedding_function=embedding_fn,
            metadata=metadata,
        )

    @staticmethod
    def _build_embedding_function():
        """Construct ChromaDB's embedding function.

        Honours the MEMORY_EMBEDDING_MODEL constant. Falls back to
        ChromaDB's bundled default (ONNX all-MiniLM-L6-v2) silently when
        sentence-transformers is missing or the model can't load — so
        the agent never fails to start because of an embedding-model
        installation issue.
        """
        if MEMORY_EMBEDDING_MODEL == "default":
            return None  # ChromaDB applies its bundled default
        try:
            from chromadb.utils.embedding_functions import (
                SentenceTransformerEmbeddingFunction,
            )

            return SentenceTransformerEmbeddingFunction(
                model_name=MEMORY_EMBEDDING_MODEL
            )
        except ImportError:
            logger.warning(
                "[MEMORY] sentence-transformers not installed — falling back "
                "to ChromaDB's default MiniLM embeddings. Retrieval quality "
                "will be poor. Install with: conda install -c conda-forge "
                "sentence-transformers"
            )
            return None
        except Exception as e:
            logger.warning(
                f"[MEMORY] Failed to load embedding model "
                f"'{MEMORY_EMBEDDING_MODEL}' ({e}); falling back to ChromaDB "
                f"default."
            )
            return None

    # ───────────────────────────── Public API ─────────────────────────────

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        min_relevance: float = 0.55,
        file_filter: Optional[List[str]] = None,
    ) -> List[MemoryPointer]:
        """
        Retrieve memory pointers relevant to the query.

        Uses a hybrid score: vector cosine similarity + BM25 keyword match.
        Candidate pool is the union of top-K from each channel
        (Reciprocal-Rank-Fusion style); final ranking is the weighted sum
        defined by ``HYBRID_WEIGHTS``.

        Args:
            query: The search query
            top_k: Maximum number of results to return
            min_relevance: Minimum hybrid score (0-1) to include.
                Default 0.55 matches cosine-scaled scores; BM25 lifts
                keyword-strong matches above the cut.
            file_filter: Optional list of file paths to search within

        Returns:
            List of MemoryPointer objects, sorted by relevance (highest first).
            Result shape is unchanged from v1 — only the ranking improves.
        """
        if not query or not query.strip():
            logger.warning("Empty query provided to retrieve()")
            return []

        collection_count = self.collection.count()
        if collection_count == 0:
            logger.info(
                "Memory collection is empty. Consider running index_all() first."
            )
            return []

        # Cast a wider net than top_k so the hybrid re-rank has signal to work
        # with. ChromaDB and BM25 each return up to candidate_pool items.
        candidate_pool = max(top_k * 4, 20)

        where_filter = None
        if file_filter:
            where_filter = {"file_path": {"$in": file_filter}}

        # Render single-line so multi-line queries don't bleed into the next
        # log entry. Full query is still passed to the retriever.
        logger.info(f"[MEMORY QUERY] {_log_preview(query, _LOG_QUERY_MAX_CHARS)}")

        # ── Channel 1: vector similarity ──
        vector_hits: Dict[str, Dict[str, Any]] = {}
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=min(candidate_pool, collection_count),
                where=where_filter,
                include=["metadatas", "distances", "documents"],
            )
            ids = (results.get("ids") or [[]])[0]
            metadatas = (results.get("metadatas") or [[]])[0]
            distances = (results.get("distances") or [[]])[0]
            for i, chunk_id in enumerate(ids):
                meta = metadatas[i] if i < len(metadatas) else {}
                distance = distances[i] if i < len(distances) else 1.0
                vector_hits[chunk_id] = {
                    "score": _cosine_distance_to_similarity(distance),
                    "metadata": meta,
                    "rank": i,
                }
        except Exception as e:
            logger.error(f"Error querying ChromaDB: {e}")
            # Continue — BM25 alone may still return useful results.

        # ── Channel 2: BM25 keyword search ──
        self._ensure_bm25_built()
        bm25_hits: Dict[str, Dict[str, Any]] = {}
        bm25_raw = self._bm25.search(query, top_k=candidate_pool)
        if bm25_raw:
            max_bm25 = max(score for _, score in bm25_raw) or 1.0
            for rank, (chunk_id, score) in enumerate(bm25_raw):
                bm25_hits[chunk_id] = {
                    "score": score / max_bm25,  # min-max normalise to [0,1]
                    "rank": rank,
                }

        # Union the candidate ids from both channels (RRF-style fusion).
        candidate_ids = set(vector_hits) | set(bm25_hits)
        if not candidate_ids:
            return []

        # If file_filter was set, BM25 may have returned chunks outside the
        # filter — drop them by reading metadata for the missing ones.
        if file_filter:
            need_meta = [cid for cid in candidate_ids if cid not in vector_hits]
            if need_meta:
                missing_meta = self._fetch_metadata(need_meta)
                candidate_ids = {
                    cid
                    for cid in candidate_ids
                    if (
                        vector_hits.get(cid, {}).get("metadata", {}).get("file_path")
                        or missing_meta.get(cid, {}).get("file_path", "")
                    )
                    in set(file_filter)
                }

        # Pull metadata for any BM25-only hits so we can build pointers + age.
        missing_ids = [cid for cid in candidate_ids if cid not in vector_hits]
        extra_meta = self._fetch_metadata(missing_ids) if missing_ids else {}

        pointers: List[MemoryPointer] = []

        w = HYBRID_WEIGHTS
        for chunk_id in candidate_ids:
            meta = (
                vector_hits[chunk_id]["metadata"]
                if chunk_id in vector_hits
                else extra_meta.get(chunk_id, {})
            )
            if not meta:
                continue

            vector_score = vector_hits.get(chunk_id, {}).get("score", 0.0)
            bm25_score = bm25_hits.get(chunk_id, {}).get("score", 0.0)

            final = w["vector"] * vector_score + w["bm25"] * bm25_score

            if final < min_relevance:
                continue

            pointers.append(
                MemoryPointer(
                    chunk_id=chunk_id,
                    file_path=meta.get("file_path", ""),
                    section_path=meta.get("section_path", ""),
                    title=meta.get("title", ""),
                    summary=meta.get("summary", ""),
                    relevance_score=final,
                    metadata={
                        k: v
                        for k, v in meta.items()
                        if k not in ("file_path", "section_path", "title", "summary")
                    },
                )
            )

        pointers.sort(key=lambda p: p.relevance_score, reverse=True)
        pointers = pointers[:top_k]

        logger.info(
            f"[MEMORY RESULT] {len(pointers)} pointer(s) returned "
            f"(vector candidates={len(vector_hits)}, bm25 candidates={len(bm25_hits)}, "
            f"min_relevance={min_relevance})"
        )
        if not pointers:
            logger.info("[MEMORY RESULT]   (no pointers above min_relevance)")
        for i, p in enumerate(pointers, start=1):
            logger.info(
                f"[MEMORY RESULT]   #{i} score={p.relevance_score:.3f} "
                f"file={p.file_path} section={p.section_path} "
                f":: {_log_preview(p.summary, _LOG_SUMMARY_MAX_CHARS)}"
            )
        return pointers

    # ───────────────────────── Hybrid retrieval helpers ─────────────────────────

    def _ensure_bm25_built(self) -> None:
        """Rebuild the BM25 index if it's been invalidated since last build."""
        if not self._bm25_dirty:
            return
        try:
            corpus = self._load_bm25_corpus()
            self._bm25.rebuild(corpus)
            self._bm25_dirty = False
            logger.debug(f"[MEMORY] BM25 index rebuilt: {self._bm25.size} chunks")
        except Exception as e:
            logger.warning(f"[MEMORY] Failed to rebuild BM25 index: {e}")
            # Leave the flag dirty so we retry on the next query.

    def _load_bm25_corpus(self) -> Dict[str, str]:
        """Pull every chunk's searchable text from ChromaDB.

        We concatenate the document body, summary, and extracted_entities so
        BM25 has the strongest possible keyword signal — especially proper
        nouns that vector embeddings often miss.
        """
        try:
            result = self.collection.get(
                include=["documents", "metadatas"],
            )
        except Exception as e:
            logger.warning(f"[MEMORY] BM25 corpus load failed: {e}")
            return {}

        ids = result.get("ids") or []
        docs = result.get("documents") or []
        metas = result.get("metadatas") or []

        corpus: Dict[str, str] = {}
        for i, chunk_id in enumerate(ids):
            body = docs[i] if i < len(docs) else ""
            meta = metas[i] if i < len(metas) else {}
            summary = meta.get("summary", "")
            entities = meta.get("extracted_entities", "")
            corpus[chunk_id] = f"{body}\n{summary}\n{entities}"
        return corpus

    def _fetch_metadata(self, chunk_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch metadata for a specific set of chunk ids."""
        if not chunk_ids:
            return {}
        try:
            result = self.collection.get(ids=chunk_ids, include=["metadatas"])
            ids = result.get("ids") or []
            metas = result.get("metadatas") or []
            return {ids[i]: metas[i] for i in range(len(ids))}
        except Exception as e:
            logger.warning(f"[MEMORY] Metadata fetch failed: {e}")
            return {}

    def retrieve_full_content(self, chunk_id: str) -> Optional[str]:
        """
        Retrieve the full content of a specific chunk by its ID.

        This method is used when the agent wants to read the full content
        of a chunk after reviewing the pointers from retrieve().

        Args:
            chunk_id: The chunk ID to retrieve

        Returns:
            The full content string, or None if not found
        """
        try:
            result = self.collection.get(
                ids=[chunk_id],
                include=["documents"],
            )
            if result and result.get("documents") and result["documents"][0]:
                return result["documents"][0]
        except Exception as e:
            logger.error(f"Error retrieving chunk {chunk_id}: {e}")

        return None

    def update(self) -> Dict[str, Any]:
        """
        Incrementally update the memory index.

        This method checks for changes in the agent file system and only
        re-indexes files that have been modified, added, or deleted.

        Returns:
            Summary dict with counts of added, updated, and removed files
        """
        logger.info("Starting incremental memory update...")

        stats = {
            "files_added": 0,
            "files_updated": 0,
            "files_removed": 0,
            "chunks_added": 0,
            "chunks_removed": 0,
        }

        # Get current files in agent file system
        current_files = self._get_all_markdown_files()
        current_file_paths = {
            str(f.relative_to(self.agent_fs_path)) for f in current_files
        }
        indexed_file_paths = set(self._file_index_cache.keys())

        # Find new, modified, and removed files
        new_files = current_file_paths - indexed_file_paths
        removed_files = indexed_file_paths - current_file_paths
        existing_files = current_file_paths & indexed_file_paths

        # Remove deleted files from index
        for file_path in removed_files:
            self._remove_file_from_index(file_path)
            stats["files_removed"] += 1

        # Check existing files for modifications
        modified_files = []
        for file_path in existing_files:
            full_path = self.agent_fs_path / file_path
            current_hash = self._compute_file_hash(full_path)
            cached_index = self._file_index_cache.get(file_path)

            if cached_index and cached_index.content_hash != current_hash:
                modified_files.append(file_path)

        # Index new files
        for file_path in new_files:
            full_path = self.agent_fs_path / file_path
            chunks_added = self._index_file(full_path)
            stats["files_added"] += 1
            stats["chunks_added"] += chunks_added

        # Re-index modified files
        for file_path in modified_files:
            full_path = self.agent_fs_path / file_path
            # Remove old chunks first
            old_index = self._file_index_cache.get(file_path)
            if old_index:
                stats["chunks_removed"] += len(old_index.chunk_ids)
                self._remove_file_from_index(file_path)

            # Re-index
            chunks_added = self._index_file(full_path)
            stats["files_updated"] += 1
            stats["chunks_added"] += chunks_added

        logger.info(f"Memory update complete: {stats}")
        return stats

    def index_all(self, force: bool = False) -> Dict[str, Any]:
        """
        Index all markdown files in the agent file system.

        Args:
            force: If True, clear existing index and re-index everything

        Returns:
            Summary dict with indexing statistics
        """
        logger.info(f"Starting full memory indexing (force={force})...")

        if force:
            self._clear_index()

        stats = {
            "files_processed": 0,
            "chunks_created": 0,
            "files_skipped": 0,
        }

        markdown_files = self._get_all_markdown_files()

        for file_path in markdown_files:
            rel_path = str(file_path.relative_to(self.agent_fs_path))

            # Skip if already indexed (and not forcing)
            if not force and rel_path in self._file_index_cache:
                current_hash = self._compute_file_hash(file_path)
                if self._file_index_cache[rel_path].content_hash == current_hash:
                    stats["files_skipped"] += 1
                    continue

            chunks_created = self._index_file(file_path)
            stats["files_processed"] += 1
            stats["chunks_created"] += chunks_created

        logger.info(f"Full indexing complete: {stats}")
        return stats

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the memory index.

        Returns:
            Dict with collection stats
        """
        return {
            "total_chunks": self.collection.count(),
            "total_files_indexed": len(self._file_index_cache),
            "agent_fs_path": str(self.agent_fs_path),
            "chroma_path": self.chroma_path,
        }

    def clear(self) -> None:
        """
        Clear all indexed memory.
        """
        self._clear_index()
        logger.info("Memory index cleared")

    # ───────────────────────────── Chunking Logic ─────────────────────────────

    def _chunk_markdown(self, content: str, file_path: str) -> List[MemoryChunk]:
        """
        Split markdown content into semantic chunks.

        Dispatches based on file shape:
        - Flat per-item logs (MEMORY.md, EVENT_UNPROCESSED.md) → one chunk
          per "[ts] [cat] content" line via :meth:`_chunk_memory_log`.
        - Everything else → header-based section chunking (original
          behaviour, unchanged).

        Per-item chunking is the Phase 1 fix for retrieval accuracy: in the
        old section-based path, every memory item collapsed into a single
        chunk under "## Memory" and the embedding represented the whole blob.

        Args:
            content: The markdown content to chunk
            file_path: Relative file path for metadata

        Returns:
            List of MemoryChunk objects
        """
        filename = Path(file_path).name
        if filename in PER_ITEM_FILES:
            return self._chunk_memory_log(content, file_path)
        return self._chunk_by_sections(content, file_path)

    def _chunk_memory_log(self, content: str, file_path: str) -> List[MemoryChunk]:
        """One chunk per ``[ts] [cat] content`` line.

        Each line is short enough on its own (memory items are capped at
        ~150 words by the memory-processor skill) that no further splitting
        is needed. Lines that don't match the expected pattern — headers,
        blank lines, the file's preamble — are skipped here; the file as a
        whole is still in INDEX_TARGET_FILES so its preamble is captured
        by the section chunker on other indexed files where appropriate.

        Per-chunk metadata carries timestamp, category, extracted_entities
        (list of capitalised tokens / quoted strings) and an indexed_at
        stamp. Timestamp is stored for display / debugging only.
        """
        chunks: List[MemoryChunk] = []
        now = datetime.utcnow().isoformat()

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(">"):
                continue
            match = MEMORY_ITEM_LINE_RE.match(line)
            if not match:
                continue

            timestamp_str, category, item_text = match.groups()
            timestamp_iso = _normalize_timestamp(timestamp_str)
            category = category.lower()

            # Body = the item content. Summary = first ~150 chars cleaned.
            entities = extract_entities(item_text)
            summary = self._create_summary(item_text)

            chunks.append(
                MemoryChunk(
                    chunk_id=str(uuid.uuid4()),
                    file_path=file_path,
                    section_path=f"item:{category}",
                    title=category,
                    content=line,  # keep the full bracketed line for grep parity
                    summary=summary,
                    content_hash=self._compute_content_hash(line),
                    file_modified_at="",
                    indexed_at=now,
                    metadata={
                        "timestamp": timestamp_iso,
                        "category": category,
                        # ChromaDB metadata values must be primitives; serialise
                        # the entity list as a comma-joined string. The BM25
                        # corpus and retrieval consumers parse it back.
                        "extracted_entities": ", ".join(entities),
                        "item_kind": "memory_log",
                    },
                )
            )

        return chunks

    def _chunk_by_sections(self, content: str, file_path: str) -> List[MemoryChunk]:
        """Original header-based chunker. Preserves existing behaviour for
        non-list markdown (AGENT.md, USER.md, PROACTIVE.md, ...).
        """
        chunks: List[MemoryChunk] = []

        # Parse headers and their content
        sections = self._parse_markdown_sections(content)

        now = datetime.utcnow().isoformat()

        for section in sections:
            section_content = section["content"].strip()
            if not section_content:
                continue

            # Create summary (first ~150 chars, cleaned up)
            summary = self._create_summary(section_content)

            # Check if section needs to be split further
            if len(section_content) > self.chunk_size_limit:
                sub_chunks = self._split_large_section(
                    section_content,
                    section["path"],
                    section["title"],
                )
                for i, sub_content in enumerate(sub_chunks):
                    chunk = MemoryChunk(
                        chunk_id=str(uuid.uuid4()),
                        file_path=file_path,
                        section_path=f"{section['path']} (part {i + 1})",
                        title=section["title"],
                        content=sub_content,
                        summary=self._create_summary(sub_content),
                        content_hash=self._compute_content_hash(sub_content),
                        file_modified_at="",  # Will be set by caller
                        indexed_at=now,
                        metadata={
                            "header_level": section["level"],
                            "part": i + 1,
                            "total_parts": len(sub_chunks),
                        },
                    )
                    chunks.append(chunk)
            else:
                chunk = MemoryChunk(
                    chunk_id=str(uuid.uuid4()),
                    file_path=file_path,
                    section_path=section["path"],
                    title=section["title"],
                    content=section_content,
                    summary=summary,
                    content_hash=self._compute_content_hash(section_content),
                    file_modified_at="",
                    indexed_at=now,
                    metadata={
                        "header_level": section["level"],
                    },
                )
                chunks.append(chunk)

        return chunks

    def _parse_markdown_sections(self, content: str) -> List[Dict[str, Any]]:
        """
        Parse markdown into sections based on headers.

        Returns a list of dicts with:
        - title: The header text
        - level: Header level (1-6)
        - path: Full header path (e.g., "## Overview > ### Details")
        - content: Content under this header (until next same/higher level header)
        """
        sections: List[Dict[str, Any]] = []

        # Regex to match markdown headers
        header_pattern = re.compile(r"^(#{1,6})\s+(.+?)$", re.MULTILINE)

        # Find all headers with their positions
        headers = []
        for match in header_pattern.finditer(content):
            headers.append(
                {
                    "level": len(match.group(1)),
                    "title": match.group(2).strip(),
                    "start": match.start(),
                    "end": match.end(),
                }
            )

        # If no headers, treat entire content as one section
        if not headers:
            sections.append(
                {
                    "title": "Document",
                    "level": 0,
                    "path": "Document",
                    "content": content,
                }
            )
            return sections

        # Add content before first header as a section (if any)
        if headers[0]["start"] > 0:
            pre_content = content[: headers[0]["start"]].strip()
            if pre_content:
                sections.append(
                    {
                        "title": "Introduction",
                        "level": 0,
                        "path": "Introduction",
                        "content": pre_content,
                    }
                )

        # Build hierarchical path for each header
        header_stack: List[Dict[str, Any]] = []  # Stack to track parent headers

        for i, header in enumerate(headers):
            # Get content for this section (until next header or end)
            content_start = header["end"]
            content_end = (
                headers[i + 1]["start"] if i + 1 < len(headers) else len(content)
            )
            section_content = content[content_start:content_end].strip()

            # Update header stack for path building
            while header_stack and header_stack[-1]["level"] >= header["level"]:
                header_stack.pop()

            header_stack.append(header)

            # Build path from stack
            path = " > ".join(f"{'#' * h['level']} {h['title']}" for h in header_stack)

            sections.append(
                {
                    "title": header["title"],
                    "level": header["level"],
                    "path": path,
                    "content": section_content,
                }
            )

        return sections

    def _split_large_section(
        self, content: str, section_path: str, title: str
    ) -> List[str]:
        """
        Split a large section into smaller chunks with overlap.

        Uses paragraph boundaries when possible to maintain coherence.
        """
        chunks: List[str] = []

        # Try to split by paragraphs first
        paragraphs = re.split(r"\n\s*\n", content)

        current_chunk = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) + 2 <= self.chunk_size_limit:
                current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
            else:
                if current_chunk:
                    chunks.append(current_chunk)

                # If paragraph itself is too long, split by sentences
                if len(para) > self.chunk_size_limit:
                    sentence_chunks = self._split_by_sentences(para)
                    chunks.extend(sentence_chunks[:-1])
                    current_chunk = sentence_chunks[-1] if sentence_chunks else ""
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        # Add overlap between chunks
        if len(chunks) > 1 and self.chunk_overlap > 0:
            overlapped_chunks = []
            for i, chunk in enumerate(chunks):
                if i > 0:
                    # Add end of previous chunk as prefix
                    prev_suffix = chunks[i - 1][-self.chunk_overlap :]
                    chunk = f"...{prev_suffix}\n\n{chunk}"
                overlapped_chunks.append(chunk)
            chunks = overlapped_chunks

        return chunks if chunks else [content]

    def _split_by_sentences(self, text: str) -> List[str]:
        """Split text by sentences, respecting chunk size limit."""
        # Simple sentence splitting
        sentences = re.split(r"(?<=[.!?])\s+", text)

        chunks: List[str] = []
        current = ""

        for sentence in sentences:
            if len(current) + len(sentence) + 1 <= self.chunk_size_limit:
                current = f"{current} {sentence}" if current else sentence
            else:
                if current:
                    chunks.append(current)
                current = sentence

        if current:
            chunks.append(current)

        return chunks

    def _create_summary(self, content: str, max_length: int = 150) -> str:
        """
        Create a brief summary of content for the memory pointer.

        Takes the first meaningful text, cleans it up, and truncates.
        """
        # Remove markdown formatting
        clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", content)  # Links
        clean = re.sub(r"[*_`#]+", "", clean)  # Formatting
        clean = re.sub(r"\s+", " ", clean).strip()  # Whitespace

        # Take first max_length chars, break at word boundary
        if len(clean) <= max_length:
            return clean

        truncated = clean[:max_length]
        last_space = truncated.rfind(" ")
        if last_space > max_length * 0.7:
            truncated = truncated[:last_space]

        return truncated + "..."

    # ───────────────────────────── Indexing Helpers ─────────────────────────────

    def _index_file(self, file_path: Path) -> int:
        """
        Index a single file and add its chunks to ChromaDB.

        Returns the number of chunks created.
        """
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return 0

        rel_path = str(file_path.relative_to(self.agent_fs_path))
        file_hash = self._compute_file_hash(file_path)
        file_modified = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()

        # Chunk the file
        chunks = self._chunk_markdown(content, rel_path)

        if not chunks:
            return 0

        # Update file modification time in chunks
        for chunk in chunks:
            chunk.file_modified_at = file_modified

        # Add to ChromaDB
        chunk_ids = []
        documents = []
        metadatas = []

        for chunk in chunks:
            chunk_ids.append(chunk.chunk_id)
            documents.append(chunk.content)
            metadatas.append(
                {
                    "file_path": chunk.file_path,
                    "section_path": chunk.section_path,
                    "title": chunk.title,
                    "summary": chunk.summary,
                    "content_hash": chunk.content_hash,
                    "file_modified_at": chunk.file_modified_at,
                    "indexed_at": chunk.indexed_at,
                    **chunk.metadata,
                }
            )

        try:
            self.collection.add(
                ids=chunk_ids,
                documents=documents,
                metadatas=metadatas,
            )
        except Exception as e:
            logger.error(f"Error adding chunks to ChromaDB: {e}")
            return 0

        self._bm25_dirty = True

        # Update file index cache
        file_index = FileIndex(
            file_path=rel_path,
            content_hash=file_hash,
            modified_at=file_modified,
            chunk_ids=chunk_ids,
            indexed_at=datetime.utcnow().isoformat(),
        )
        self._file_index_cache[rel_path] = file_index
        self._save_file_index(file_index)

        logger.debug(f"Indexed {len(chunks)} chunks from {rel_path}")
        return len(chunks)

    def _remove_file_from_index(self, file_path: str) -> None:
        """Remove all chunks for a file from the index."""
        file_index = self._file_index_cache.get(file_path)
        if not file_index:
            return

        # Remove chunks from ChromaDB
        if file_index.chunk_ids:
            try:
                self.collection.delete(ids=file_index.chunk_ids)
            except Exception as e:
                logger.error(f"Error removing chunks from ChromaDB: {e}")

        # Remove from file index
        try:
            self.file_index_collection.delete(ids=[file_path])
        except Exception:
            pass

        # Remove from cache
        del self._file_index_cache[file_path]
        self._bm25_dirty = True

        logger.debug(f"Removed {len(file_index.chunk_ids)} chunks for {file_path}")

    def _clear_index(self) -> None:
        """Clear all data from the memory index."""
        # Delete and recreate collections
        try:
            self.chroma_client.delete_collection(self.COLLECTION_NAME)
        except Exception:
            pass

        try:
            self.chroma_client.delete_collection(self.FILE_INDEX_COLLECTION)
        except Exception:
            pass

        self.collection = self.chroma_client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={
                "description": "Agent file system memory chunks (v2)",
                "hnsw:space": "cosine",
            },
        )
        self.file_index_collection = self.chroma_client.get_or_create_collection(
            name=self.FILE_INDEX_COLLECTION,
            metadata={"description": "File index for incremental updates (v2)"},
        )

        self._file_index_cache.clear()
        self._bm25_dirty = True

    # ───────────────────────────── File Index Persistence ─────────────────────────────

    def _load_file_index_cache(self) -> None:
        """Load file index from ChromaDB into memory cache."""
        try:
            result = self.file_index_collection.get(include=["metadatas", "documents"])

            if not result or not result.get("ids"):
                return

            for i, file_path in enumerate(result["ids"]):
                meta = (
                    result.get("metadatas", [[]])[i] if result.get("metadatas") else {}
                )
                doc = (
                    result.get("documents", [[]])[i] if result.get("documents") else ""
                )

                # chunk_ids stored as comma-separated in document
                chunk_ids = doc.split(",") if doc else []

                self._file_index_cache[file_path] = FileIndex(
                    file_path=file_path,
                    content_hash=meta.get("content_hash", ""),
                    modified_at=meta.get("modified_at", ""),
                    chunk_ids=chunk_ids,
                    indexed_at=meta.get("indexed_at", ""),
                )
        except Exception as e:
            logger.warning(f"Error loading file index cache: {e}")

    def _save_file_index(self, file_index: FileIndex) -> None:
        """Save/update a file index entry in ChromaDB."""
        try:
            # Store chunk_ids as comma-separated document
            self.file_index_collection.upsert(
                ids=[file_index.file_path],
                documents=[",".join(file_index.chunk_ids)],
                metadatas=[
                    {
                        "content_hash": file_index.content_hash,
                        "modified_at": file_index.modified_at,
                        "indexed_at": file_index.indexed_at,
                    }
                ],
            )
        except Exception as e:
            logger.warning(f"Error saving file index: {e}")

    # ───────────────────────────── Utilities ─────────────────────────────

    # Files to index for memory retrieval
    INDEX_TARGET_FILES = [
        "AGENT.md",
        "PROACTIVE.md",
        "MEMORY.md",
        "USER.md",
        "EVENT_UNPROCESSED.md",
    ]

    def _get_all_markdown_files(self) -> List[Path]:
        """Get the target markdown files in the agent file system."""
        if not self.agent_fs_path.exists():
            logger.warning(
                f"Agent file system path does not exist: {self.agent_fs_path}"
            )
            return []

        files = []
        for filename in self.INDEX_TARGET_FILES:
            file_path = self.agent_fs_path / filename
            if file_path.exists():
                files.append(file_path)
        return files

    @staticmethod
    def _compute_file_hash(file_path: Path) -> str:
        """Compute MD5 hash of file content."""
        try:
            content = file_path.read_bytes()
            return hashlib.md5(content).hexdigest()
        except Exception:
            return ""

    @staticmethod
    def _compute_content_hash(content: str) -> str:
        """Compute MD5 hash of string content."""
        return hashlib.md5(content.encode("utf-8")).hexdigest()


# ───────────────────── Hybrid Retrieval Scoring Helpers ─────────────────────


def _cosine_distance_to_similarity(distance: float) -> float:
    """Map ChromaDB's cosine distance to a [0,1] similarity score.

    ChromaDB returns ``1 - cosine_similarity`` when the collection is
    configured with ``hnsw:space=cosine``. Clamp to handle floating-point
    drift and the L2 fallback case (where distances can exceed 1).
    """
    if distance is None:
        return 0.0
    sim = 1.0 - float(distance)
    if sim < 0.0:
        return 0.0
    if sim > 1.0:
        return 1.0
    return sim


def _normalize_timestamp(ts: str) -> str:
    """Coerce '/' or 'T'-separated timestamps to canonical 'YYYY-MM-DD HH:MM:SS'.

    Returns an empty string when parsing fails — stored as metadata only;
    not currently used in ranking.
    """
    if not ts:
        return ""
    cleaned = ts.replace("/", "-").replace("T", " ")
    try:
        dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""


# ───────────────────────────── Testing / Demo ─────────────────────────────


if __name__ == "__main__":
    # Demo usage

    print("Memory Manager Demo")
    print("=" * 50)

    # Initialize with default paths
    manager = MemoryManager(
        agent_file_system_path="./agent_file_system",
        chroma_path="./chroma_db_memory",
    )

    # Check current stats
    stats = manager.get_stats()
    print(f"\nCurrent stats: {stats}")

    # Full indexing
    print("\nRunning full index...")
    result = manager.index_all(force=True)
    print(f"Indexing result: {result}")

    # Incremental update
    # print("\nRunning incremental update...")
    # result = manager.update()
    # print(f"Update result: {result}")

    # Demo retrieval
    if manager.collection.count() > 0:
        print("\n" + "=" * 50)
        query = "input('Enter a query (or press Enter for default): ').strip()"
        if not query:
            query = "agent capabilities and configuration"

        print(f"\nSearching for: {query}")
        pointers = manager.retrieve(query, top_k=3)

        print(f"\nFound {len(pointers)} relevant memory pointers:")
        for i, ptr in enumerate(pointers, 1):
            print(f"\n{i}. [{ptr.file_path}]")
            print(f"   Section: {ptr.section_path}")
            print(f"   Summary: {ptr.summary}")
            print(f"   Relevance: {ptr.relevance_score:.3f}")
