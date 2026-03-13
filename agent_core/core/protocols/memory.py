# -*- coding: utf-8 -*-
"""
Protocol definition for MemoryManager.

This module defines the MemoryManagerProtocol that specifies the
interface for RAG-based memory operations.
"""

from typing import Any, Dict, List, Optional, Protocol


class MemoryPointerProtocol(Protocol):
    """Protocol for memory pointers returned by retrieve()."""

    chunk_id: str
    file_path: str
    section_path: str
    title: str
    summary: str
    relevance_score: float
    metadata: Dict[str, Any]


class MemoryManagerProtocol(Protocol):
    """
    Protocol for RAG-based memory operations.

    This defines the minimal interface that a memory manager must provide
    for indexing and retrieving semantic memory chunks.
    """

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        min_relevance: float = 0.0,
        file_filter: Optional[List[str]] = None,
    ) -> List[Any]:
        """
        Retrieve memory pointers relevant to the query.

        Args:
            query: The search query.
            top_k: Maximum number of results to return.
            min_relevance: Minimum relevance score (0-1) to include.
            file_filter: Optional list of file paths to search within.

        Returns:
            List of MemoryPointer objects, sorted by relevance.
        """
        ...

    def retrieve_full_content(self, chunk_id: str) -> Optional[str]:
        """
        Retrieve the full content of a specific chunk.

        Args:
            chunk_id: The chunk ID to retrieve.

        Returns:
            The full content string, or None if not found.
        """
        ...

    def update(self) -> Dict[str, Any]:
        """
        Incrementally update the memory index.

        Returns:
            Summary dict with counts of added, updated, and removed files.
        """
        ...

    def index_all(self, force: bool = False) -> Dict[str, Any]:
        """
        Index all markdown files in the agent file system.

        Args:
            force: If True, re-index all files even if unchanged.

        Returns:
            Summary dict with indexing statistics.
        """
        ...

    def clear(self) -> None:
        """Clear all indexed memory."""
        ...
