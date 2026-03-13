# -*- coding: utf-8 -*-
"""
core.impl.event_stream.manager

Event stream manager that manages, stores, return concurrent event streams
running under several active tasks.

Also handles file-based event logging to:
- EVENT.md: Complete event history
- EVENT_UNPROCESSED.md: Events pending memory processing

"""


from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import threading

from agent_core.core.impl.event_stream.event_stream import EventStream
from agent_core.core.event_stream.event import Event
from agent_core.core.protocols.llm import LLMInterfaceProtocol
from agent_core.utils.logger import logger
from agent_core.core.state.base import get_state_or_none

# Import memory mode check (deferred to avoid circular imports)
def _is_memory_enabled() -> bool:
    """Check if memory mode is enabled. Returns True if unknown."""
    try:
        from app.ui_layer.settings.memory_settings import is_memory_enabled
        return is_memory_enabled()
    except ImportError:
        return True  # Default to enabled if settings module not available

# Task names that should not log to EVENT_UNPROCESSED.md (to prevent infinite loops)
SKIP_UNPROCESSED_TASK_NAMES = {"Process Memory Events"}

# Event types that should not be logged to EVENT_UNPROCESSED.md
# These are routine events that the memory processor always discards anyway
# Filtering them at write time saves processing and keeps the file smaller
SKIP_UNPROCESSED_EVENT_TYPES = {
    # Action lifecycle events
    "action_start",
    "action_end",
    # GUI action events
    "gui_action",
    "GUI action start",
    "GUI action end",
    # Reasoning and observation
    "agent reasoning",
    "screen_description",
    # Task lifecycle events
    # "task_start",
    # "task_end",
    "todos",
    "error",
    # System events
    "waiting_for_user",
}


class EventStreamManager:
    def __init__(
        self,
        llm: LLMInterfaceProtocol,
        agent_file_system_path: Optional[Path] = None
    ) -> None:
        # Main stream for conversation mode (not task-specific)
        self._main_stream: EventStream = EventStream(llm=llm, temp_dir=None)
        # Per-task event streams, keyed by task_id
        self._task_streams: Dict[str, EventStream] = {}
        self.llm = llm

        # File-based event logging
        self._agent_file_system_path = agent_file_system_path
        self._skip_unprocessed_logging = False
        self._file_lock = threading.Lock()

        # Conversation history for context injection into tasks
        # Stores recent user AND agent messages without affecting TUI display
        self._conversation_history: List[Event] = []
        self._conversation_history_limit = 50  # Keep last 50 messages

    # ───────────────────────────── lifecycle ─────────────────────────────

    @property
    def event_stream(self) -> EventStream:
        """Current stream based on context. Backward-compatible property.

        Returns the task stream if a task is active, otherwise the main stream.
        Uses get_state_or_none() from StateRegistry for state access.
        """
        state = get_state_or_none()
        if state:
            task_id = state.get_agent_property("current_task_id", "")
            if task_id and task_id in self._task_streams:
                return self._task_streams[task_id]
        return self._main_stream

    def get_stream(self) -> EventStream:
        """Return the event stream for this session."""
        return self.event_stream

    def get_main_stream(self) -> EventStream:
        """Get the main event stream (conversation mode)."""
        return self._main_stream

    def create_stream(self, task_id: str, temp_dir=None) -> EventStream:
        """Create a new per-task event stream."""
        stream = EventStream(llm=self.llm, temp_dir=temp_dir)
        self._task_streams[task_id] = stream
        logger.debug(f"[EventStreamManager] Created stream for task {task_id}")
        return stream

    def remove_stream(self, task_id: str) -> None:
        """Remove a task's event stream on task completion."""
        removed = self._task_streams.pop(task_id, None)
        if removed:
            logger.debug(f"[EventStreamManager] Removed stream for task {task_id}")

    def get_stream_by_id(self, task_id: str) -> EventStream:
        """Explicit lookup by task_id (no session needed)."""
        return self._task_streams.get(task_id, self._main_stream)

    def snapshot_main(self, include_summary: bool = True) -> str:
        """Snapshot the main event stream."""
        return self._main_stream.to_prompt_snapshot(include_summary=include_summary)

    def snapshot_by_id(self, task_id: str, include_summary: bool = True) -> str:
        """Snapshot a specific task's stream (used before StateSession exists)."""
        stream = self._task_streams.get(task_id, self._main_stream)
        return stream.to_prompt_snapshot(include_summary=include_summary)

    def get_all_streams(self) -> list[EventStream]:
        """Get all event streams (main + all task streams).

        Used by the TUI to watch events from all concurrent tasks.

        Returns:
            List of all event streams, main stream first, then task streams.
        """
        return [self._main_stream] + list(self._task_streams.values())

    def get_all_streams_with_ids(self) -> list[tuple[str, EventStream]]:
        """Get all event streams with their task IDs.

        Used by the TUI to watch events from all concurrent tasks and
        correctly associate events with their source tasks.

        Returns:
            List of (task_id, stream) tuples. Main stream uses empty string as ID.
        """
        result = [("", self._main_stream)]  # Main stream has no task_id
        result.extend(self._task_streams.items())
        return result

    def record_conversation_message(self, kind: str, message: str, display_message: Optional[str] = None) -> None:
        """Record a conversation message for context injection into future tasks.

        This stores messages in a separate in-memory list that does NOT affect
        TUI display. Used to track both user and agent messages for injecting
        conversation history into new tasks.

        Args:
            kind: Event kind (e.g., "user message from platform: Telegram")
            message: The message content
            display_message: Optional display message
        """
        event = Event(
            message=message,
            kind=kind,
            severity="INFO",
            display_message=display_message,
        )
        self._conversation_history.append(event)

        # Trim to limit
        if len(self._conversation_history) > self._conversation_history_limit:
            self._conversation_history = self._conversation_history[-self._conversation_history_limit:]

    def get_recent_conversation_messages(self, limit: int = 20) -> List[Event]:
        """Retrieve recent conversation messages (user AND agent) for context injection.

        Returns messages with their full kind labels including platform info
        (e.g., "user message from platform: Telegram", "agent message to platform: Discord").

        Args:
            limit: Maximum number of messages to return. Defaults to 20.

        Returns:
            List of Event objects, oldest first (for correct injection order).
        """
        # Return last N messages from conversation history (oldest first)
        return self._conversation_history[-limit:]

    def clear_all(self) -> None:
        """Remove all event streams."""
        for stream in self._task_streams.values():
            stream.clear()
        self._task_streams.clear()
        self._main_stream.clear()

    # ───────────────────────── file-based logging ─────────────────────────

    def set_skip_unprocessed_logging(self, skip: bool) -> None:
        """
        Enable or disable logging to EVENT_UNPROCESSED.md.

        Used during memory processing tasks to prevent infinite loops where
        events generated during processing would be added to the unprocessed
        queue.

        Args:
            skip: If True, events will NOT be written to EVENT_UNPROCESSED.md
                  (but will still be written to EVENT.md for complete history).
        """
        self._skip_unprocessed_logging = skip
        # Log at INFO level so we can trace when flag changes
        logger.info(f"[EventStreamManager] skip_unprocessed_logging set to {skip}")

    def _should_skip_unprocessed(self) -> bool:
        """
        Check if logging to EVENT_UNPROCESSED.md should be skipped.

        This uses both the explicit flag AND checks if the current task
        is a memory processing task (by name). This provides a robust
        fallback in case the flag isn't properly set.

        Also checks if memory mode is disabled in settings.

        Returns:
            True if logging to EVENT_UNPROCESSED.md should be skipped.
        """
        # Check if memory is disabled in settings
        if not _is_memory_enabled():
            return True

        # Check explicit flag
        if self._skip_unprocessed_logging:
            return True

        # Fallback: check current task name from state
        try:
            state = get_state_or_none()
            if state:
                current_task = state.current_task
                if current_task and current_task.name in SKIP_UNPROCESSED_TASK_NAMES:
                    logger.debug(f"[EventStreamManager] Skipping unprocessed logging for task: {current_task.name}")
                    return True
        except Exception:
            # If we can't check state, fall back to flag only
            pass

        return False

    def _should_skip_event_type(self, kind: str) -> bool:
        """
        Check if this event type should be skipped for EVENT_UNPROCESSED.md.

        Routine events like action_start, action_end, reasoning, etc. are always
        discarded by the memory processor, so we filter them at write time.

        Args:
            kind: Event category to check

        Returns:
            True if this event type should not be written to EVENT_UNPROCESSED.md
        """
        return kind in SKIP_UNPROCESSED_EVENT_TYPES

    def _log_to_files(self, kind: str, message: str) -> None:
        """
        Append an event to EVENT.md and optionally EVENT_UNPROCESSED.md.

        This method is thread-safe and handles file I/O errors gracefully.
        Events are written in the format: [YYYY/MM/DD HH:MM:SS] [kind]: message

        Args:
            kind: Event category (e.g., "action", "trigger", "task")
            message: Event message content
        """
        if not self._agent_file_system_path:
            return

        # Format: [YYYY/MM/DD HH:MM:SS] [kind]: message
        timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M:%S")
        event_line = f"[{timestamp}] [{kind}]: {message}\n"

        with self._file_lock:
            # Always write to EVENT.md (create if doesn't exist)
            try:
                event_file = self._agent_file_system_path / "EVENT.md"
                with open(event_file, "a", encoding="utf-8") as f:
                    f.write(event_line)
            except Exception as e:
                logger.warning(f"[EventStreamManager] Failed to write to EVENT.md: {e}")

            # Write to EVENT_UNPROCESSED.md unless:
            # 1. Task-level skip is active (memory processing task)
            # 2. Event type is in the skip list (routine events)
            if not self._should_skip_unprocessed() and not self._should_skip_event_type(kind):
                try:
                    unprocessed_file = self._agent_file_system_path / "EVENT_UNPROCESSED.md"
                    with open(unprocessed_file, "a", encoding="utf-8") as f:
                        f.write(event_line)
                except Exception as e:
                    logger.warning(f"[EventStreamManager] Failed to write to EVENT_UNPROCESSED.md: {e}")

    # ───────────────────────────── utilities ─────────────────────────────

    def log(
        self,
        kind: str,
        message: str,
        severity: str = "INFO",
        *,
        display_message: str | None = None,
        action_name: str | None = None,
        task_id: str | None = None,
    ) -> int:
        """
        Log directly to a session's event stream, creating it on demand.

        The manager records debug breadcrumbs around stream creation to aid in
        tracing concurrent tasks. Returned indices match those produced by
        :meth:`EventStream.log` and can be used to correlate updates.

        Args:
            kind: Event family such as ``"action_start"`` or ``"warn"``.
            message: Main event text.
            severity: Importance level, defaulting to ``"INFO"``.
            display_message: Optional trimmed message for UI surfaces.
            action_name: Optional action label for file-based externalization.
            task_id: Optional task ID to explicitly specify which stream to log to.
                     If provided, bypasses global STATE lookup (prevents race conditions
                     in concurrent task execution). If None, falls back to get_stream().

        Returns:
            Index of the logged event within the target stream's tail.
        """
        logger.debug(f"Process Started - Logging event to stream: [{severity}] {kind} - {message}")
        # Use explicit task_id if provided (for concurrent task isolation)
        # Otherwise fall back to get_stream() which uses global STATE
        # CRITICAL: Use `is not None` instead of `if task_id` to handle empty string correctly
        if task_id is not None and task_id in self._task_streams:
            stream = self._task_streams[task_id]
        elif task_id is not None and task_id not in self._task_streams:
            # Task ID provided but stream not found - fall back to global stream
            # Only warn if other streams exist (indicates a bug/race condition).
            # If no streams exist, this is expected (conversation mode, before task creation).
            if self._task_streams:
                logger.warning(f"[EVENT_STREAM] Task stream not found for task_id={task_id!r}, falling back to global stream. "
                              f"Available streams: {list(self._task_streams.keys())}")
            stream = self.get_stream()
        else:
            stream = self.get_stream()
        idx = stream.log(
            kind,
            message,
            severity,
            display_message=display_message,
            action_name=action_name,
        )

        # Also log to markdown files for persistence
        self._log_to_files(kind, message)

        return idx

    def snapshot(self, include_summary: bool = True) -> str:
        """Return a prompt snapshot of a specific session, or '(no events)' if not found."""
        stream = self.get_stream()
        if not stream:
            return "(no events)"
        return stream.to_prompt_snapshot(include_summary=include_summary)
