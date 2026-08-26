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
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import chromadb

from agent_core.utils.logger import logger
from agent_core.core.impl.memory.bm25_index import BM25Index
from agent_core.core.impl.memory.graph import (
    CONNECTION_LINE_RE,
    ENTITY_REGISTRY_FILE,
    _CONNECTION_TEXT_SEPARATOR,
    MemoryGraph,
    compute_item_id,
    parse_entity_registry,
    split_item_fields,
)
from agent_core.core.impl.memory.text_extract import extract_text, is_indexable_file

# All numeric behavior constants live in tuning.py — the single typed home
# of the memory system's magic numbers.
from agent_core.core.impl.memory.tuning import (
    CANDIDATE_POOL_FLOOR,
    CANDIDATE_POOL_MULTIPLIER,
    CHUNK_OVERLAP,
    CHUNK_SIZE_LIMIT,
    ENTITY_JUDGE_TEXT_CAP,
    ENTITY_MATCH_MIN_SCORE,
    GRAPH_ELIGIBILITY_SCORE,
    HYBRID_WEIGHTS,
    LOG_QUERY_MAX_CHARS,
    LOG_SUMMARY_MAX_CHARS,
    MERGED_SEEDS_MAX,
    PREVIEW_LEAD,
    PREVIEW_MAX_CHARS,
    RECENCY_HALF_LIFE_DAYS,
    RECENCY_MAX_BONUS,
    RETRIEVE_MIN_RELEVANCE,
    RETRIEVE_TOP_K,
    SEMANTIC_SEEDS_MAX,
)


# Files that are flat lists of "[timestamp] [category] content" items.
# These get per-item chunking so each fact has its own embedding, instead of
# the whole list collapsing into a single section chunk under "## Memory".
PER_ITEM_FILES = frozenset({"MEMORY.md", "EVENT_UNPROCESSED.md"})

# Matches a memory item line: "[stamp] [category] content". The stamp slot
# accepts any bracketed token — stamp validity is METADATA, never a gate on
# whether the memory exists. A canonical "YYYY-MM-DD HH:MM:SS" stamp (the
# only recognized format, validated downstream by _normalize_timestamp)
# yields timestamp metadata for identity and recency; any other stamp
# content indexes the memory all the same with no timestamp metadata.
# The optional colon after the category bracket is the EVENT_UNPROCESSED.md
# event-line separator ("[kind]: message").
# Captures: stamp, category, content.
MEMORY_ITEM_LINE_RE = re.compile(
    r"^\s*\[([^\]]+)\]\s+\[([\w\-]+)\]\s*:?\s*(.+?)\s*$"
)

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

    # The chunk collection and its companion file-index. The index is a
    # derived cache of the markdown files, so it is always rebuildable from
    # disk; if the chunking shape changes, clear it and re-index.
    COLLECTION_NAME = "agent_memory"
    FILE_INDEX_COLLECTION = "agent_memory_file_index"
    # Entity-name embeddings for the graph channel's semantic entity match.
    # A separate collection so entity vectors never mix with chunk vectors;
    # a derived cache, reseeded from the graph on every rebuild.
    ENTITY_COLLECTION = "agent_memory_entities"

    def __init__(
        self,
        agent_file_system_path: str = "./agent_file_system",
        chroma_path: str = "./chroma_db_memory",
        chunk_size_limit: int = CHUNK_SIZE_LIMIT,
        chunk_overlap: int = CHUNK_OVERLAP,
        extra_files_provider: Optional[Callable[[], List[str]]] = None,
    ):
        """
        Initialize the Memory Manager.

        Args:
            agent_file_system_path: Path to the agent file system directory
            chroma_path: Path for ChromaDB persistence
            chunk_size_limit: Maximum characters per chunk before splitting
            chunk_overlap: Character overlap when splitting large chunks
            extra_files_provider: Callable returning user-selected extra
                files to index (relative paths under the agent file
                system, e.g. "workspace/notes.md"). Read on every index
                pass so panel changes apply without restart.
        """
        self.agent_fs_path = Path(agent_file_system_path).resolve()
        self.chroma_path = chroma_path
        self.chunk_size_limit = chunk_size_limit
        self.chunk_overlap = chunk_overlap
        self._extra_files_provider = extra_files_provider

        # Initialize ChromaDB.
        # hnsw:space=cosine — cosine similarity gives well-scaled scores in
        # [0,1] for the hybrid retriever and behaves better than L2 on the
        # short factual snippets that dominate MEMORY.md.
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)

        # Build the embedding function. Default ChromaDB uses MiniLM-L6-v2
        # (weak — ~0.65 verbatim self-similarity). MEMORY_EMBEDDING_MODEL
        # points to a stronger sentence-transformers model by default; if it
        # can't load, construction fails — retrieval thresholds are calibrated
        # for the configured model, so running with a substitute is worse than
        # not starting.
        # Stored so _clear_index can rebuild every collection with the SAME
        # embedding function — a force rebuild must not silently downgrade the
        # model (e.g. bge-small back to ChromaDB's default MiniLM).
        self._embedding_fn = embedding_fn = self._build_embedding_function()

        self.collection = self._open_collection(
            name=self.COLLECTION_NAME,
            embedding_fn=embedding_fn,
            metadata={
                "description": "Agent file system memory chunks",
                "hnsw:space": "cosine",
                "embedding_model": MEMORY_EMBEDDING_MODEL,
            },
        )

        # File index collection (tracks which files are indexed and their hashes)
        self.file_index_collection = self._open_collection(
            name=self.FILE_INDEX_COLLECTION,
            embedding_fn=embedding_fn,
            metadata={"description": "File index for incremental updates"},
        )

        # Entity-name embeddings for the graph channel's semantic entity match.
        # Same embedding function as the chunks; cosine space for [0,1] scores.
        self.entity_collection = self._open_collection(
            name=self.ENTITY_COLLECTION,
            embedding_fn=embedding_fn,
            metadata={
                "description": "Entity name embeddings for graph-channel matching",
                "hnsw:space": "cosine",
                "embedding_model": MEMORY_EMBEDDING_MODEL,
            },
        )

        # In-memory cache of file indices
        self._file_index_cache: Dict[str, FileIndex] = {}
        self._load_file_index_cache()

        # BM25 keyword index — mirrors ChromaDB's chunk set. Rebuilt lazily
        # on first query and after each index mutation.
        self._bm25 = BM25Index()
        self._bm25_dirty = True

        # Memory graph — the semantic layer (entities/items/files) derived
        # from the same chunk corpus. Same lazy-rebuild lifecycle as BM25.
        self._graph: Optional[MemoryGraph] = None
        self._graph_dirty = True

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

        Honours the MEMORY_EMBEDDING_MODEL constant. Every retrieval
        threshold is calibrated for the configured model, so a load
        failure raises instead of degrading to a different model.
        """
        if MEMORY_EMBEDDING_MODEL == "default":
            return None  # ChromaDB applies its bundled default
        try:
            from chromadb.utils.embedding_functions import (
                SentenceTransformerEmbeddingFunction,
            )
        except ImportError as e:
            raise RuntimeError(
                "[MEMORY] sentence-transformers is required for the configured "
                f"embedding model '{MEMORY_EMBEDDING_MODEL}'. Install with: "
                "conda install -c conda-forge sentence-transformers"
            ) from e

        try:
            return SentenceTransformerEmbeddingFunction(
                model_name=MEMORY_EMBEDDING_MODEL
            )
        except (OSError, ImportError) as e:
            # The constructor imports sentence-transformers → transformers →
            # torch; a native-DLL failure (Windows without the VC++
            # Redistributable: WinError 126 on torch_python.dll; Linux
            # without libgomp) lands here as a 40-line torch traceback.
            # Still fatal by design (thresholds are calibrated to this
            # model) — but say what to do.
            fix = (
                "install the Visual C++ Redistributable "
                "(https://aka.ms/vs/17/release/vc_redist.x64.exe)"
                if sys.platform == "win32"
                else "install libgomp1/libstdc++6 (apt-get install -y libgomp1 libstdc++6)"
            )
            raise RuntimeError(
                f"[MEMORY] The embedding stack for '{MEMORY_EMBEDDING_MODEL}' is "
                f"installed but cannot load: {e}. Usual fix: {fix}, or re-run "
                "`python install.py` (it checks this). Escape hatch: "
                "MEMORY_EMBEDDING_MODEL=default (lower retrieval quality)."
            ) from e

    # ───────────────────────────── Public API ─────────────────────────────

    def retrieve(
        self,
        query: str,
        top_k: int = RETRIEVE_TOP_K,
        min_relevance: float = RETRIEVE_MIN_RELEVANCE,
        file_filter: Optional[List[str]] = None,
        include_superseded: bool = False,
    ) -> List[MemoryPointer]:
        """
        Retrieve memory pointers relevant to the query.

        Uses a hybrid score across three channels: vector cosine
        similarity, BM25 keyword match, and graph proximity (items
        connected to entities the query mentions, up to 2 hops). Candidate
        pool is the union of top-K from each channel (Reciprocal-Rank-
        Fusion style); final ranking is the weighted sum defined by
        ``HYBRID_WEIGHTS`` plus a small recency bonus.

        Superseded memory items (facts invalidated by newer information)
        are excluded unless ``include_superseded`` is set — pass True for
        queries about the past.

        Args:
            query: The search query
            top_k: Maximum number of results to return
            min_relevance: Minimum hybrid score (0-1) to include.
                Strongly graph-connected items are eligible below this
                cut (see GRAPH_ELIGIBILITY_SCORE).
            file_filter: Optional list of file paths to search within
            include_superseded: Include invalidated memory items.

        Returns:
            List of MemoryPointer objects, sorted by relevance (highest first).
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
        candidate_pool = max(top_k * CANDIDATE_POOL_MULTIPLIER, CANDIDATE_POOL_FLOOR)

        where_filter = None
        if file_filter:
            where_filter = {"file_path": {"$in": file_filter}}

        # Render single-line so multi-line queries don't bleed into the next
        # log entry. Full query is still passed to the retriever.
        logger.info(f"[MEMORY QUERY] {_log_preview(query, LOG_QUERY_MAX_CHARS)}")

        # ── Channel 1: vector similarity ──
        vector_hits: Dict[str, Dict[str, Any]] = {}
        results = self.collection.query(
            query_texts=[query],
            n_results=min(candidate_pool, collection_count),
            where=where_filter,
            include=["metadatas", "distances", "documents"],
        )
        ids = (results.get("ids") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]
        documents = (results.get("documents") or [[]])[0]
        for i, chunk_id in enumerate(ids):
            meta = metadatas[i] if i < len(metadatas) else {}
            distance = distances[i] if i < len(distances) else 1.0
            vector_hits[chunk_id] = {
                "score": _cosine_distance_to_similarity(distance),
                "metadata": meta,
                # Kept for the query-aware preview snippet (built below).
                "document": documents[i] if i < len(documents) else "",
                "rank": i,
            }

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

        # ── Channel 3: graph proximity ──
        # Entities mentioned in the query seed a 2-hop walk over the memory
        # graph; connected items get a proximity score in [0,1].
        graph_hits: Dict[str, float] = {}
        try:
            self._ensure_graph_built()
            if self._graph is not None:
                # String seeds (exact / all-token) at full strength, unioned
                # with semantic seeds (entity-name embedding ≥ threshold) for
                # partial names. Union keeps the strongest strength per entity.
                seeds = self._merge_entity_seeds(
                    self._graph.match_entities(query),
                    self._match_entities_semantic(query),
                )
                if seeds:
                    graph_hits = self._graph.bfs_item_scores(
                        seeds, include_superseded=include_superseded
                    )
        except Exception as e:
            logger.warning(f"[MEMORY] Graph channel failed: {e}")

        # Union the candidate ids from all channels (RRF-style fusion).
        candidate_ids = set(vector_hits) | set(bm25_hits) | set(graph_hits)
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

        # Pull metadata + documents for any non-vector hits so we can build
        # pointers, age them, and window a query-aware preview.
        missing_ids = [cid for cid in candidate_ids if cid not in vector_hits]
        extra_meta, extra_docs = (
            self._fetch_meta_and_docs(missing_ids) if missing_ids else ({}, {})
        )

        pointers: List[MemoryPointer] = []

        for chunk_id in candidate_ids:
            meta = (
                vector_hits[chunk_id]["metadata"]
                if chunk_id in vector_hits
                else extra_meta.get(chunk_id, {})
            )
            if not meta:
                continue

            # Invalidated facts stay in the index (history is preserved)
            # but never surface in normal retrieval.
            if not include_superseded and meta.get("superseded"):
                continue

            vector_score = vector_hits.get(chunk_id, {}).get("score", 0.0)
            bm25_score = bm25_hits.get(chunk_id, {}).get("score", 0.0)
            graph_score = graph_hits.get(chunk_id, 0.0)

            final = (
                HYBRID_WEIGHTS.vector * vector_score
                + HYBRID_WEIGHTS.bm25 * bm25_score
                + HYBRID_WEIGHTS.graph * graph_score
                + _recency_bonus(meta.get("timestamp", ""))
            )

            # Eligibility: pass the relevance cut, or be strongly connected
            # in the graph to an entity the query names.
            if final < min_relevance and graph_score < GRAPH_ELIGIBILITY_SCORE:
                continue

            # Query-aware preview: window the snippet around the query match
            # rather than the chunk head. Prefer the item's clean content
            # (MEMORY.md items), else the raw document (file chunks), else the
            # stored summary as a last resort.
            full_text = (
                meta.get("item_content")
                or (
                    vector_hits[chunk_id].get("document")
                    if chunk_id in vector_hits
                    else extra_docs.get(chunk_id, "")
                )
                or meta.get("summary", "")
            )
            pointers.append(
                MemoryPointer(
                    chunk_id=chunk_id,
                    file_path=meta.get("file_path", ""),
                    section_path=meta.get("section_path", ""),
                    title=meta.get("title", ""),
                    summary=self._preview_snippet(query, full_text),
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
            f"graph candidates={len(graph_hits)}, min_relevance={min_relevance})"
        )
        if not pointers:
            logger.info("[MEMORY RESULT]   (no pointers above min_relevance)")
        for i, p in enumerate(pointers, start=1):
            logger.info(
                f"[MEMORY RESULT]   #{i} score={p.relevance_score:.3f} "
                f"file={p.file_path} section={p.section_path} "
                f":: {_log_preview(p.summary, LOG_SUMMARY_MAX_CHARS)}"
            )
        return pointers

    # ───────────────────────── Memory graph API ─────────────────────────

    def _ensure_graph_built(self) -> None:
        """Rebuild the memory graph if the index changed since last build."""
        if not self._graph_dirty and self._graph is not None:
            return
        try:
            # The registry supplies the entity list and each memory's
            # connection marks. Missing file means an empty registry.
            registry: Dict[str, Any] = {}
            registry_path = self.agent_fs_path / ENTITY_REGISTRY_FILE
            if registry_path.exists():
                registry = parse_entity_registry(
                    registry_path.read_text(encoding="utf-8")
                )
            self._graph = MemoryGraph.build(self._load_full_corpus(), registry)
            self._graph_dirty = False
            # Keep the entity embedding collection in lock-step with the graph
            # so the semantic entity match sees the current entity set.
            self._rebuild_entity_index()
            # Persist this build's established connections back into the
            # ## Connections section (write only on change).
            self._sync_connection_records(registry_path)
            logger.debug(
                f"[MEMORY] Graph rebuilt: {len(self._graph.entities)} entities, "
                f"{len(self._graph.items)} items, {len(self._graph.files)} files"
            )
        except Exception as e:
            logger.warning(f"[MEMORY] Failed to rebuild memory graph: {e}")
            # Leave dirty so the next call retries.

    def _sync_connection_records(self, registry_path: Path) -> None:
        """Re-sync the connection record lines in ENTITIES.md.

        Ownership is line-scoped, not section-scoped: the system may touch
        ONLY lines matching the connection-record grammar
        (CONNECTION_LINE_RE) — it removes them and regenerates them from
        this build. Every other line — headers, prose, and above all the
        ``## Entities`` names — is preserved verbatim, wherever it is and
        however mangled the file may be, so no sync can ever damage the
        entity list. The regenerated records are placed after the
        ``## Connections`` header line (matched as a whole line, never as a
        substring; appended at the end if the file lacks one). The file is
        written only when the result differs, so the watcher's reindex of
        this write converges instead of looping.
        """
        if self._graph is None:
            return
        current = (
            registry_path.read_text(encoding="utf-8")
            if registry_path.exists()
            else ""
        )
        header = "## Connections"

        kept: List[str] = []
        for line in current.splitlines():
            if CONNECTION_LINE_RE.match(line.strip()):
                continue  # system-owned record line; regenerated below
            kept.append(line)
        while kept and not kept[-1].strip():
            kept.pop()

        header_index = next(
            (i for i, line in enumerate(kept) if line.strip() == header), None
        )
        if header_index is None:
            if kept:
                kept.append("")
            kept.append(header)
            header_index = len(kept) - 1
        else:
            # Blank lines directly under the header are re-added below.
            while (
                header_index + 1 < len(kept) and not kept[header_index + 1].strip()
            ):
                kept.pop(header_index + 1)

        records = self._graph.connection_lines()
        rebuilt = (
            kept[: header_index + 1] + [""] + records + kept[header_index + 1 :]
        )
        rendered = "\n".join(rebuilt).rstrip("\n") + "\n"
        if rendered != current:
            registry_path.write_text(rendered, encoding="utf-8")
            logger.debug("[MEMORY] Connection records synced to ENTITIES.md")

    def _load_full_corpus(self) -> List[Dict[str, Any]]:
        """Pull every chunk (id, document, metadata) from ChromaDB."""
        result = self.collection.get(include=["documents", "metadatas"])
        ids = result.get("ids") or []
        docs = result.get("documents") or []
        metas = result.get("metadatas") or []
        return [
            {
                "chunk_id": ids[i],
                "document": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
            }
            for i in range(len(ids))
        ]

    def _rebuild_entity_index(self) -> None:
        """Sync the entity embedding collection with the current graph.

        One record per entity (id = entity key, document = display name),
        embedded with the same function as the chunks so the graph channel
        can resolve entities by name similarity. Incremental: only new
        entities are embedded and dropped ones removed. It is a derived cache
        rebuilt from the graph, never migrated.
        """
        if self._graph is None:
            return
        try:
            current = {
                key: (node.name or key)
                for key, node in self._graph.entities.items()
                if key
            }
            existing = set(self.entity_collection.get().get("ids") or [])
            current_ids = set(current.keys())

            to_remove = list(existing - current_ids)
            if to_remove:
                self.entity_collection.delete(ids=to_remove)

            to_add = [k for k in current_ids if k not in existing]
            if to_add:
                self.entity_collection.add(
                    ids=to_add,
                    documents=[current[k] for k in to_add],
                    metadatas=[{"name": current[k], "key": k} for k in to_add],
                )
        except Exception as e:
            logger.warning(f"[MEMORY] Failed to rebuild entity index: {e}")

    def _match_entities_semantic(
        self,
        query: str,
        max_seeds: int = SEMANTIC_SEEDS_MAX,
        min_score: float = ENTITY_MATCH_MIN_SCORE,
    ) -> List[Tuple[str, float]]:
        """Resolve query → entities by NAME embedding similarity.

        Returns (entity_key, similarity) pairs at or above ``min_score``.
        This is the fuzzy/partial channel — "Tobias" resolves to the
        "Tobias Garcia" node here where the string matcher cannot.
        """
        if not query or not query.strip():
            return []
        try:
            count = self.entity_collection.count()
            if count == 0:
                return []
            result = self.entity_collection.query(
                query_texts=[query],
                n_results=min(max_seeds, count),
                include=["distances"],
            )
            ids = (result.get("ids") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            seeds: List[Tuple[str, float]] = []
            for i, key in enumerate(ids):
                sim = _cosine_distance_to_similarity(
                    distances[i] if i < len(distances) else 1.0
                )
                if sim >= min_score:
                    seeds.append((key, sim))
            return seeds
        except Exception as e:
            logger.warning(f"[MEMORY] Semantic entity match failed: {e}")
            return []

    @staticmethod
    def _merge_entity_seeds(
        *seed_lists: List[Tuple[str, float]], max_seeds: int = MERGED_SEEDS_MAX
    ) -> List[Tuple[str, float]]:
        """Union entity seeds keeping the strongest strength per entity."""
        best: Dict[str, float] = {}
        for seeds in seed_lists:
            for key, strength in seeds:
                if strength > best.get(key, 0.0):
                    best[key] = strength
        return sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))[:max_seeds]

    def graph_snapshot(self) -> Dict[str, Any]:
        """Full graph serialisation for the Memory panel (nodes/edges/stats)."""
        self._ensure_graph_built()
        if self._graph is None:
            return {"nodes": [], "edges": [], "stats": {}}
        return self._graph.snapshot()

    def entity_overview(self, name: str) -> Optional[Dict[str, Any]]:
        """Everything the memory graph knows about one entity, or None."""
        self._ensure_graph_built()
        if self._graph is None:
            return None
        return self._graph.entity_overview(name)

    def related_path(self, name_a: str, name_b: str) -> List[Dict[str, Any]]:
        """Shortest connection between two entities through items/files."""
        self._ensure_graph_built()
        if self._graph is None:
            return []
        return self._graph.shortest_path(name_a, name_b)

    # ───────────────────────── Entity-judge pipeline API ─────────────────────────

    def pending_judgment_records(
        self, text_cap: int = ENTITY_JUDGE_TEXT_CAP
    ) -> List[Dict[str, Any]]:
        """Records awaiting the entity judge, with full chunk text as evidence.

        One entry per memory whose connection record renders ``[pending]``:
        its ``?``-marked candidate entity names plus the chunk's FULL text
        (capped) — far richer evidence than the 160-char record preview.
        A record with no candidates still needs one review of its text for
        new entities.
        """
        self._ensure_graph_built()
        if self._graph is None:
            return []
        records: List[Dict[str, Any]] = []
        for item_id in sorted(self._graph.items):
            item = self._graph.items[item_id]
            if item.superseded:
                continue
            if item.reviewed and not item.pending_entities:
                continue  # renders [judged] — nothing to do
            candidates = [
                self._graph.entities[key].name
                for key in sorted(item.pending_entities)
                if key in self._graph.entities
            ]
            text = " ".join((item.content or "").split())
            if len(text) > text_cap:
                text = text[: text_cap - 3] + "..."
            records.append({"id": item_id, "candidates": candidates, "text": text})
        return records

    def registry_entity_names(self) -> List[str]:
        """The canonical ## Entities list from ENTITIES.md, verbatim.

        Read from the registry file rather than the graph so hub-pruned
        entities (excluded from the derived graph) still appear — the judge
        must see them to avoid re-creating them.
        """
        registry_path = self.agent_fs_path / ENTITY_REGISTRY_FILE
        if not registry_path.exists():
            return []
        try:
            registry = parse_entity_registry(
                registry_path.read_text(encoding="utf-8")
            )
        except Exception as e:
            logger.warning(f"[MEMORY] Failed to parse {ENTITY_REGISTRY_FILE}: {e}")
            return []
        return registry.get("entities", [])

    def apply_entity_judgments(
        self,
        verdicts: Dict[str, Dict[str, str]],
        new_entities: List[str],
    ) -> Dict[str, int]:
        """Write entity-judge verdicts into ENTITIES.md deterministically.

        ``verdicts`` maps chunk id → {candidate name (casefolded) →
        "confirm"|"reject"} for every record the judge reviewed (empty dict
        for a no-candidate record: its review still flips the line to
        ``[judged]``). Marks are flipped in place on the record lines —
        ``?Name`` → ``Name`` (confirm) or ``!Name`` (reject); nothing else
        on the line is touched, so a verdict can only ever decide a
        connection the matcher established. ``new_entities`` are appended
        under ``## Entities`` (deduped against the registry by normalized
        name). The graph is marked dirty so the next build consumes the
        judged state from the file — the file stays the single source of
        truth.
        """
        registry_path = self.agent_fs_path / ENTITY_REGISTRY_FILE
        current = (
            registry_path.read_text(encoding="utf-8")
            if registry_path.exists()
            else ""
        )

        def _norm(name: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()

        # ── Flip marks on the judged record lines ──
        flipped = 0
        out: List[str] = []
        for line in current.splitlines():
            match = CONNECTION_LINE_RE.match(line.strip())
            if not match:
                out.append(line)
                continue
            chunk_id = match.group(1)
            record_verdicts = verdicts.get(chunk_id)
            if record_verdicts is None:
                out.append(line)
                continue
            names_part, sep, preview = match.group(3).partition(
                _CONNECTION_TEXT_SEPARATOR
            )
            parts: List[str] = []
            pending_left = False
            for raw in names_part.split(","):
                name = raw.strip()
                if not name:
                    continue
                if name.startswith("?"):
                    bare = name[1:].strip()
                    verdict = record_verdicts.get(bare.casefold())
                    if verdict == "confirm":
                        parts.append(bare)
                        flipped += 1
                    elif verdict == "reject":
                        parts.append(f"!{bare}")
                        flipped += 1
                    else:
                        parts.append(name)
                        pending_left = True
                else:
                    parts.append(name)
            status = "pending" if pending_left else "judged"
            names = f" {', '.join(parts)}" if parts else ""
            tail = f"{_CONNECTION_TEXT_SEPARATOR}{preview}" if sep else ""
            out.append(f"[{chunk_id}] [{status}]{names}{tail}")

        # ── Append genuinely new entities under ## Entities ──
        existing = {_norm(n) for n in parse_entity_registry(current)["entities"]}
        accepted: List[str] = []
        for raw in new_entities:
            name = " ".join(str(raw).split())
            key = _norm(name)
            if not name or not key or key in existing:
                continue
            existing.add(key)
            accepted.append(name)
        if accepted:
            header_idx = next(
                (i for i, l in enumerate(out) if l.strip() == "## Entities"), None
            )
            if header_idx is None:
                conn_idx = next(
                    (
                        i
                        for i, l in enumerate(out)
                        if l.strip() == "## Connections"
                    ),
                    len(out),
                )
                out[conn_idx:conn_idx] = ["## Entities", ""]
                header_idx = conn_idx
            # Insert after the section's last entity line (or the header).
            insert_at = header_idx + 1
            for i in range(header_idx + 1, len(out)):
                stripped = out[i].strip()
                if stripped.startswith("#"):
                    break
                if stripped:
                    insert_at = i + 1
            out[insert_at:insert_at] = accepted

        rendered = "\n".join(out).rstrip("\n") + "\n"
        if rendered != current:
            registry_path.write_text(rendered, encoding="utf-8")
            self._graph_dirty = True
            logger.info(
                f"[MEMORY] Entity judgments applied: {flipped} mark(s) flipped, "
                f"{len(accepted)} new entit{'y' if len(accepted) == 1 else 'ies'}"
            )
        return {"flipped": flipped, "entities_added": len(accepted)}

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

        We concatenate the document body and summary so BM25 has the full
        keyword signal of each chunk.
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
            corpus[chunk_id] = f"{body}\n{summary}"
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

    def _fetch_meta_and_docs(
        self, chunk_ids: List[str]
    ) -> tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
        """Fetch metadata AND documents for a set of chunk ids in one call.

        Used for non-vector candidates so the query-aware preview can window
        the full chunk text (the vector channel already carries its own docs).
        """
        if not chunk_ids:
            return {}, {}
        try:
            result = self.collection.get(
                ids=chunk_ids, include=["metadatas", "documents"]
            )
            ids = result.get("ids") or []
            metas = result.get("metadatas") or []
            docs = result.get("documents") or []
            meta_map = {ids[i]: metas[i] for i in range(len(ids))}
            doc_map = {ids[i]: (docs[i] if i < len(docs) else "") for i in range(len(ids))}
            return meta_map, doc_map
        except Exception as e:
            logger.warning(f"[MEMORY] Metadata/document fetch failed: {e}")
            return {}, {}

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
        current_file_paths = {self._rel_path(f) for f in current_files}
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

            if cached_index and (
                cached_index.content_hash != current_hash
                or self._expected_chunk_ids(full_path) != cached_index.chunk_ids
            ):
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
            rel_path = self._rel_path(file_path)

            # Skip if already indexed (and not forcing)
            if not force and rel_path in self._file_index_cache:
                cached = self._file_index_cache[rel_path]
                current_hash = self._compute_file_hash(file_path)
                if (
                    cached.content_hash == current_hash
                    and self._expected_chunk_ids(file_path) == cached.chunk_ids
                ):
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

        Per-chunk metadata carries timestamp, category, entities (wikilinks
        when present, heuristic extraction otherwise), the superseded flag,
        and an indexed_at stamp. MEMORY.md chunks get deterministic ids
        derived from (timestamp, content), so the graph node, the Chroma
        chunk, and the UI item share one identity across rebuilds.
        """
        chunks: List[MemoryChunk] = []
        now = datetime.utcnow().isoformat()
        seen_ids: Dict[str, int] = {}

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

            clean_text, _, superseded = split_item_fields(item_text)
            summary = self._create_summary(clean_text)

            # Deterministic id for every per-item chunk: same line → same id
            # across rebuilds (graph node, Chroma chunk, and UI item share
            # one identity, and cached index entries can be validated by
            # re-deriving). Identical duplicate lines get a stable ordinal
            # suffix.
            chunk_id = compute_item_id(timestamp_iso or timestamp_str, clean_text)
            dup = seen_ids.get(chunk_id, 0)
            seen_ids[chunk_id] = dup + 1
            if dup:
                chunk_id = f"{chunk_id}-{dup + 1}"

            chunks.append(
                MemoryChunk(
                    chunk_id=chunk_id,
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
                        "item_content": clean_text,
                        "superseded": superseded,
                        "item_kind": "memory_log",
                    },
                )
            )

        return chunks

    def _chunk_by_sections(self, content: str, file_path: str) -> List[MemoryChunk]:
        """Header-based chunker for non-list markdown (AGENT.md, USER.md,
        workspace docs, ...).

        Chunk ids are deterministic hashes of (file, section, content):
        file chunks ARE memories, so the graph node, the Chroma chunk, and
        the ENTITIES.md connection records must share one identity across
        rebuilds — same rule as MEMORY.md items.
        """
        chunks: List[MemoryChunk] = []
        seen_ids: Dict[str, int] = {}

        def chunk_id_for(section_path: str, chunk_content: str) -> str:
            digest = hashlib.md5(
                f"{file_path}|{section_path}|{chunk_content}".encode("utf-8")
            ).hexdigest()
            cid = f"c{digest[:12]}"
            dup = seen_ids.get(cid, 0)
            seen_ids[cid] = dup + 1
            return cid if not dup else f"{cid}-{dup + 1}"

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
                        chunk_id=chunk_id_for(
                            f"{section['path']} (part {i + 1})", sub_content
                        ),
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
                    chunk_id=chunk_id_for(section["path"], section_content),
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

    def _clean_for_preview(self, content: str) -> str:
        """Strip markdown SYNTAX positionally for a readable preview.

        Never removes characters inside words, or snake_case identifiers like
        list_available_integrations collapse into unreadable mush.
        """
        clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", content or "")  # Links
        clean = re.sub(r"^#{1,6}\s+", "", clean, flags=re.MULTILINE)  # Headings
        clean = clean.replace("`", "")  # Inline-code markers
        clean = re.sub(r"\*+", "", clean)  # Bold/italic markers
        clean = re.sub(r"\s+", " ", clean).strip()  # Whitespace
        return clean

    @staticmethod
    def _truncate_preview(clean: str, max_length: int) -> str:
        """Head-of-text truncation at a word boundary, with trailing '...'."""
        if len(clean) <= max_length:
            return clean
        truncated = clean[:max_length]
        last_space = truncated.rfind(" ")
        if last_space > max_length * 0.7:
            truncated = truncated[:last_space]
        return truncated + "..."

    def _create_summary(self, content: str, max_length: int = 150) -> str:
        """Brief from-the-head summary of content for the stored pointer."""
        return self._truncate_preview(self._clean_for_preview(content), max_length)

    def _preview_snippet(self, query: str, content: str) -> str:
        """A query-CENTRED preview of a chunk (keyword-in-context).

        Cleans markdown like the stored summary, then returns a window
        centred on the first query match that covers the most query terms,
        with leading/trailing ellipses marking omitted text. Degrades to the
        head-of-content summary when no query term appears, so non-matching
        previews look exactly as before. Built at retrieval time because the
        stored summary is query-independent.
        """
        clean = self._clean_for_preview(content)
        if len(clean) <= PREVIEW_MAX_CHARS:
            return clean

        terms = [
            t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) > 2
        ]
        low = clean.lower()
        # Anchor on the term occurrence whose window covers the most distinct
        # query terms, so multi-word matches stay together.
        anchor = -1
        best_hits = 0
        for term in terms:
            i = low.find(term)
            while i != -1:
                hits = sum(1 for u in terms if u in low[i : i + PREVIEW_MAX_CHARS])
                if hits > best_hits:
                    best_hits = hits
                    anchor = i
                i = low.find(term, i + len(term))

        if anchor < 0:
            # No query term in the chunk — fall back to the head snippet.
            return self._truncate_preview(clean, PREVIEW_MAX_CHARS)

        start = max(0, anchor - PREVIEW_LEAD)
        end = min(len(clean), start + PREVIEW_MAX_CHARS)
        start = max(0, end - PREVIEW_MAX_CHARS)  # re-widen left near the tail
        snippet = clean[start:end].strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(clean):
            snippet = snippet + "..."
        return snippet

    # ───────────────────────────── Indexing Helpers ─────────────────────────────

    def _index_file(self, file_path: Path) -> int:
        """
        Index a single file and add its chunks to ChromaDB.

        Returns the number of chunks created.
        """
        try:
            content = extract_text(file_path)
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return 0

        rel_path = self._rel_path(file_path)
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
        self._graph_dirty = True

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

    def _expected_chunk_ids(self, file_path: Path) -> List[str]:
        """Chunk ids the CURRENT chunker derives from the file's content.

        Pure text derivation, no embedding. Chunk ids are deterministic
        functions of content, so a cached index entry is valid only if its
        stored ids equal this derivation — an entry produced by different
        chunking code simply fails the comparison and the file reseeds.
        Nothing about past code is stored or detected.
        """
        try:
            content = extract_text(file_path)
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return []
        rel_path = self._rel_path(file_path)
        return [chunk.chunk_id for chunk in self._chunk_markdown(content, rel_path)]

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
        self._graph_dirty = True

        logger.debug(f"Removed {len(file_index.chunk_ids)} chunks for {file_path}")

    def _clear_index(self) -> None:
        """Drop and recreate every derived collection from scratch.

        Chunks, the file index, AND the entity embedding collection are all
        wiped and reopened with the SAME embedding function, so a force
        rebuild reseeds cleanly from the markdown without downgrading the
        model. The graph is dropped too; it rebuilds (and reseeds the entity
        vectors) on next access.
        """
        for name in (
            self.COLLECTION_NAME,
            self.FILE_INDEX_COLLECTION,
            self.ENTITY_COLLECTION,
        ):
            try:
                self.chroma_client.delete_collection(name)
            except Exception:
                pass

        self.collection = self._open_collection(
            name=self.COLLECTION_NAME,
            embedding_fn=self._embedding_fn,
            metadata={
                "description": "Agent file system memory chunks",
                "hnsw:space": "cosine",
                "embedding_model": MEMORY_EMBEDDING_MODEL,
            },
        )
        self.file_index_collection = self._open_collection(
            name=self.FILE_INDEX_COLLECTION,
            embedding_fn=self._embedding_fn,
            metadata={"description": "File index for incremental updates"},
        )
        self.entity_collection = self._open_collection(
            name=self.ENTITY_COLLECTION,
            embedding_fn=self._embedding_fn,
            metadata={
                "description": "Entity name embeddings for graph-channel matching",
                "hnsw:space": "cosine",
                "embedding_model": MEMORY_EMBEDDING_MODEL,
            },
        )

        self._file_index_cache.clear()
        self._bm25_dirty = True
        self._graph = None
        self._graph_dirty = True

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

    # Files always indexed for memory retrieval. User-selected extras come
    # from the extra_files_provider (settings-backed, managed in the Memory
    # panel) and are merged in by get_index_target_files().
    INDEX_TARGET_FILES = [
        "AGENT.md",
        "PROACTIVE.md",
        "MEMORY.md",
        "USER.md",
        "EVENT_UNPROCESSED.md",
        # Entity registry (entity-judge pipeline output). Indexed so the
        # file watcher picks up registry edits and dirties the graph.
        "ENTITIES.md",
    ]

    def get_index_target_files(self) -> List[str]:
        """Core files plus validated user-selected extras (relative paths)."""
        targets = list(self.INDEX_TARGET_FILES)
        if self._extra_files_provider is None:
            return targets

        try:
            extras = self._extra_files_provider() or []
        except Exception as e:
            logger.warning(f"[MEMORY] extra_files_provider failed: {e}")
            return targets

        seen = set(targets)
        for raw in extras:
            rel = str(raw).replace("\\", "/").strip().lstrip("/")
            if not rel or rel in seen or not is_indexable_file(rel):
                continue
            # Confine to the agent file system — reject traversal attempts.
            try:
                resolved = (self.agent_fs_path / rel).resolve()
                resolved.relative_to(self.agent_fs_path)
            except (ValueError, OSError):
                logger.warning(f"[MEMORY] Ignoring indexed file outside FS: {raw}")
                continue
            seen.add(rel)
            targets.append(rel)
        return targets

    def is_index_target(self, path: str) -> bool:
        """Whether an absolute or relative path is currently indexed."""
        try:
            p = Path(path)
            rel = (
                str(p.resolve().relative_to(self.agent_fs_path))
                if p.is_absolute()
                else str(p)
            ).replace("\\", "/")
        except (ValueError, OSError):
            return False
        return rel in set(self.get_index_target_files())

    def _get_all_markdown_files(self) -> List[Path]:
        """Get the target markdown files in the agent file system."""
        if not self.agent_fs_path.exists():
            logger.warning(
                f"Agent file system path does not exist: {self.agent_fs_path}"
            )
            return []

        files = []
        for filename in self.get_index_target_files():
            file_path = self.agent_fs_path / filename
            if file_path.exists():
                files.append(file_path)
        return files

    def _rel_path(self, file_path: Path) -> str:
        """Path relative to the FS root, always forward-slashed.

        One canonical separator keeps chunk metadata, the file-index cache,
        the settings list, and the panel display consistent across platforms.
        """
        return str(file_path.relative_to(self.agent_fs_path)).replace("\\", "/")

    def get_index_files_info(self) -> List[Dict[str, Any]]:
        """Per-file index status for the Memory panel."""
        core = set(self.INDEX_TARGET_FILES)
        info: List[Dict[str, Any]] = []
        for rel in self.get_index_target_files():
            file_path = self.agent_fs_path / rel
            index = self._file_index_cache.get(rel)
            info.append(
                {
                    "path": rel,
                    "core": rel in core,
                    "exists": file_path.exists(),
                    "chunk_count": len(index.chunk_ids) if index else 0,
                    "indexed_at": index.indexed_at if index else "",
                }
            )
        return info

    @staticmethod
    def _compute_file_hash(file_path: Path) -> str:
        """MD5 of file content — the incremental updater's change signal."""
        try:
            return hashlib.md5(file_path.read_bytes()).hexdigest()
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


def _recency_bonus(timestamp: str) -> float:
    """Small additive bonus for recent memory items.

    Decays exponentially with RECENCY_HALF_LIFE_DAYS; chunks without a
    parseable timestamp (section chunks, legacy items) get no bonus.
    """
    if not timestamp:
        return 0.0
    try:
        dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return 0.0
    age_days = max(0.0, (datetime.now() - dt).total_seconds() / 86400.0)
    return RECENCY_MAX_BONUS * (0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS))


def _normalize_timestamp(ts: str) -> str:
    """Validate against the canonical 'YYYY-MM-DD HH:MM:SS' stamp format.
    Delegates to the shared graph helper so item ids are derived from the
    identical canonical form everywhere. Returns '' when the stamp is
    invalid; the timestamp feeds the recency bonus in retrieval.
    """
    from agent_core.core.impl.memory.graph import normalize_timestamp

    return normalize_timestamp(ts)


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
