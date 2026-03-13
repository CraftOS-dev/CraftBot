# -*- coding: utf-8 -*-
"""
Memory File Watcher for the Agent File System.

This module monitors the agent_file_system directory for changes and triggers
incremental indexing in the MemoryManager when files are created, modified,
or deleted.

Features:
- Watches only specific target files (AGENT.md, PROACTIVE.md, MEMORY.md, USER.md, EVENT_UNPROCESSED.md)
- Debounces rapid changes to avoid excessive indexing
- Thread-safe integration with MemoryManager
- Graceful start/stop lifecycle
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional, Set

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from agent_core.utils.logger import logger
from agent_core.core.impl.memory.manager import MemoryManager


class MemoryFileWatcher:
    """
    Watches the agent file system for changes and triggers memory indexing.

    Uses the watchdog library to monitor file system events. When markdown
    files are created, modified, or deleted, it triggers an incremental
    update of the MemoryManager index after a debounce period.

    Usage:
        watcher = MemoryFileWatcher(memory_manager, debounce_seconds=2.0)
        watcher.start()
        # ... later ...
        watcher.stop()
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        debounce_seconds: float = 30.0,
    ):
        """
        Initialize the file watcher.

        Args:
            memory_manager: The MemoryManager instance to update on changes
            debounce_seconds: Time to wait after last change before triggering update
        """
        self.memory_manager = memory_manager
        self.debounce_seconds = debounce_seconds
        self.watch_path = memory_manager.agent_fs_path

        self._observer: Optional[Observer] = None
        self._is_running = False

        # Debouncing state
        self._pending_update = False
        self._last_change_time: float = 0
        self._debounce_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

        # Track changed files for logging
        self._changed_files: Set[str] = set()

    def start(self) -> None:
        """Start watching the agent file system for changes."""
        if self._is_running:
            logger.warning("[MemoryFileWatcher] Already running")
            return

        if not self.watch_path.exists():
            logger.error(f"[MemoryFileWatcher] Watch path does not exist: {self.watch_path}")
            return

        self._observer = Observer()
        event_handler = _TargetFileEventHandler(
            self._on_file_change,
            self.watch_path,
            MemoryManager.INDEX_TARGET_FILES,
        )

        self._observer.schedule(
            event_handler,
            str(self.watch_path),
            recursive=False,  # Target files are in root directory
        )

        self._observer.start()
        self._is_running = True
        logger.info(f"[MemoryFileWatcher] Started watching: {self.watch_path}")

    def stop(self) -> None:
        """Stop watching the agent file system."""
        if not self._is_running:
            return

        # Cancel any pending debounce timer
        with self._lock:
            if self._debounce_timer:
                self._debounce_timer.cancel()
                self._debounce_timer = None

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None

        self._is_running = False
        logger.info("[MemoryFileWatcher] Stopped")

    def _on_file_change(self, file_path: str, event_type: str) -> None:
        """
        Handle a file change event.

        This method is called by the event handler when a markdown file
        is created, modified, or deleted. It uses debouncing to batch
        rapid changes into a single update.

        Args:
            file_path: Path to the changed file
            event_type: Type of change ('created', 'modified', 'deleted', 'moved')
        """
        with self._lock:
            self._changed_files.add(f"{event_type}: {file_path}")
            self._last_change_time = time.time()
            self._pending_update = True

            # Cancel existing timer if any
            if self._debounce_timer:
                self._debounce_timer.cancel()

            # Start new debounce timer
            self._debounce_timer = threading.Timer(
                self.debounce_seconds,
                self._trigger_update,
            )
            self._debounce_timer.start()

    def _trigger_update(self) -> None:
        """Trigger the memory index update after debounce period."""
        with self._lock:
            if not self._pending_update:
                return

            changed_files = self._changed_files.copy()
            self._changed_files.clear()
            self._pending_update = False
            self._debounce_timer = None

        # Log what changed
        logger.info(f"[MemoryFileWatcher] Detected {len(changed_files)} change(s), updating index...")
        for change in changed_files:
            logger.debug(f"  - {change}")

        # Perform incremental update
        try:
            stats = self.memory_manager.update()
            logger.info(
                f"[MemoryFileWatcher] Index updated: "
                f"added={stats['files_added']}, "
                f"updated={stats['files_updated']}, "
                f"removed={stats['files_removed']}, "
                f"chunks +{stats['chunks_added']}/-{stats['chunks_removed']}"
            )
        except Exception as e:
            logger.error(f"[MemoryFileWatcher] Failed to update index: {e}")

    @property
    def is_running(self) -> bool:
        """Check if the watcher is currently running."""
        return self._is_running


class _TargetFileEventHandler(FileSystemEventHandler):
    """
    Event handler that filters for specific target files and forwards events.
    """

    def __init__(self, callback, watch_path: Path, target_files: list):
        """
        Initialize the handler.

        Args:
            callback: Function to call with (file_path, event_type) on changes
            watch_path: The base directory being watched
            target_files: List of filenames to watch (e.g., ["AGENT.md", "MEMORY.md"])
        """
        super().__init__()
        self._callback = callback
        self._watch_path = watch_path
        self._target_files = set(target_files)

    def _is_target_file(self, path: str) -> bool:
        """Check if the path is one of the target files."""
        filename = Path(path).name
        return filename in self._target_files

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_target_file(event.src_path):
            self._callback(event.src_path, 'created')

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_target_file(event.src_path):
            self._callback(event.src_path, 'modified')

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_target_file(event.src_path):
            self._callback(event.src_path, 'deleted')

    def on_moved(self, event: FileSystemEvent) -> None:
        # Handle both source and destination for moves
        if not event.is_directory:
            if self._is_target_file(event.src_path):
                self._callback(event.src_path, 'deleted')
            if self._is_target_file(event.dest_path):
                self._callback(event.dest_path, 'created')
