# -*- coding: utf-8 -*-
"""
Memory implementation module.

This module provides the MemoryManager for RAG-based memory operations
and MemoryFileWatcher for automatic index updates.
"""

from agent_core.core.impl.memory.manager import (
    MemoryManager,
    MemoryChunk,
    MemoryPointer,
    FileIndex,
    create_memory_processing_task,
)
from agent_core.core.impl.memory.memory_file_watcher import MemoryFileWatcher

__all__ = [
    "MemoryManager",
    "MemoryChunk",
    "MemoryPointer",
    "FileIndex",
    "MemoryFileWatcher",
    "create_memory_processing_task",
]
