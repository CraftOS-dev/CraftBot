# -*- coding: utf-8 -*-
"""
core.impl.event_stream.manager

Event stream manager that owns one event stream per session (the main
session included — it is just a session with the well-known id ``main``).

Also handles file-based event logging. Each session logs to files inside its
own workspace directory (agent_file_system/workspace/sessions/<id>/):
- EVENT.md: complete event history for that session
- EVENT_UNPROCESSED.md: that session's events pending memory processing

The memory pipeline later aggregates every session's EVENT_UNPROCESSED.md in
timestamp order (see app/memory/unprocessed_queue.py).
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional
import threading

from agent_core.core.impl.event_stream.event_stream import EventStream
from agent_core.core.event_stream.event import EventType
from agent_core.core.protocols.llm import LLMInterfaceProtocol
from agent_core.core.session import MAIN_SESSION_ID
from agent_core.utils.logger import logger
from agent_core.utils.file_utils import rotate_md_file_if_needed
from agent_core.core.state.base import get_state_or_none


# Import memory mode check (deferred to avoid circular imports)
def _is_memory_enabled() -> bool:
    """Check if memory mode is enabled. Returns True if unknown."""
    try:
        from app.ui_layer.settings.memory_settings import is_memory_enabled

        return is_memory_enabled()
    except ImportError:
        return True  # Default to enabled if settings module not available


# Header seeded into a session's EVENT_UNPROCESSED.md before its first event.
# The memory-processor skill reads events from a fixed line offset and deletes
# processed events by line number, so this header MUST stay exactly this shape
# (it mirrors app/data/agent_file_system_template/EVENT_UNPROCESSED.md).
UNPROCESSED_HEADER = (
    "# Unprocessed Event Log\n"
    "\n"
    "Agent DO NOT append to this file, only delete processed event during memory processing.\n"
    "\n"
    "## Overview\n"
    "\n"
    "This file store all the unprocessed events run by the agent.\n"
    "Once the agent run 'process memory' action, all the processed events will "
    "learned by the agent (move to MEMORY.md) and wiped from this file.\n"
    "\n"
    "## Unprocessed Events\n"
    "\n"
)


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
    "todos",
    "error",
    # System events
    "waiting_for_user",
    # Memory retrieval pointers — re-derivable on demand, not a distillable fact
    "relevant_memories",
}


class EventStreamManager:
    def __init__(
        self,
        llm: LLMInterfaceProtocol,
        agent_file_system_path: Optional[Path] = None,
        on_stream_persist: Optional[Callable[[str, "EventStream"], None]] = None,
        on_stream_remove_persist: Optional[Callable[[str], None]] = None,
    ) -> None:
        # Per-session event streams, keyed by session_id. The main session's
        # stream always exists so early boot logging has a destination.
        self._streams: Dict[str, EventStream] = {
            MAIN_SESSION_ID: EventStream(llm=llm, temp_dir=None)
        }
        self.llm = llm

        # File-based event logging
        self._agent_file_system_path = agent_file_system_path
        self._skip_unprocessed_logging = False
        self._file_lock = threading.Lock()

        # Session persistence hooks
        self._on_stream_persist = on_stream_persist
        self._on_stream_remove_persist = on_stream_remove_persist

    # ───────────────────────────── lifecycle ─────────────────────────────

    @property
    def event_stream(self) -> EventStream:
        """Current stream based on context. Backward-compatible property.

        Returns the current turn's session stream if resolvable, otherwise
        the main session's stream.
        """
        state = get_state_or_none()
        if state:
            session_id = state.get_agent_property("current_task_id", "")
            if session_id and session_id in self._streams:
                return self._streams[session_id]
        return self._streams[MAIN_SESSION_ID]

    def get_stream(self) -> EventStream:
        """Return the current turn's event stream."""
        return self.event_stream

    def get_main_stream(self) -> EventStream:
        """Get the main session's event stream."""
        return self._streams[MAIN_SESSION_ID]

    def create_stream(self, session_id: str, temp_dir=None) -> EventStream:
        """Create a session's event stream (idempotent: returns existing)."""
        existing = self._streams.get(session_id)
        if existing is not None:
            if temp_dir is not None:
                existing.temp_dir = temp_dir
            return existing
        stream = EventStream(llm=self.llm, temp_dir=temp_dir)
        self._streams[session_id] = stream
        logger.debug(f"[EventStreamManager] Created stream for session {session_id}")
        return stream

    def remove_stream(self, session_id: str) -> None:
        """Remove a session's event stream on session deletion."""
        if session_id == MAIN_SESSION_ID:
            logger.warning(
                "[EventStreamManager] Refusing to remove the main session's stream"
            )
            return
        removed = self._streams.pop(session_id, None)
        if removed:
            logger.debug(
                f"[EventStreamManager] Removed stream for session {session_id}"
            )

    def get_stream_by_id(self, session_id: str) -> EventStream:
        """Explicit lookup by session_id (falls back to the main stream)."""
        return self._streams.get(session_id, self._streams[MAIN_SESSION_ID])

    def has_stream(self, session_id: str) -> bool:
        """Whether a dedicated stream exists for this session."""
        return session_id in self._streams

    def snapshot_main(self, include_summary: bool = True) -> str:
        """Snapshot the main session's event stream."""
        return self.get_main_stream().to_prompt_snapshot(
            include_summary=include_summary
        )

    def snapshot_by_id(self, session_id: str, include_summary: bool = True) -> str:
        """Snapshot a specific session's stream."""
        return self.get_stream_by_id(session_id).to_prompt_snapshot(
            include_summary=include_summary
        )

    def get_all_streams(self) -> list[EventStream]:
        """Get all event streams (used by the UI to watch every session)."""
        return list(self._streams.values())

    def get_all_streams_with_ids(self) -> list[tuple[str, EventStream]]:
        """Get all event streams with their session IDs.

        Used by the UI to watch events from all sessions and associate
        events with their source session.

        Returns:
            List of (session_id, stream) tuples, main session first.
        """
        result = [(MAIN_SESSION_ID, self._streams[MAIN_SESSION_ID])]
        result.extend(
            (sid, stream)
            for sid, stream in self._streams.items()
            if sid != MAIN_SESSION_ID
        )
        return result

    def clear_all(self) -> None:
        """Clear all session streams (main stays registered, emptied)."""
        for stream in self._streams.values():
            stream.clear()
        main = self._streams[MAIN_SESSION_ID]
        self._streams.clear()
        self._streams[MAIN_SESSION_ID] = main

    # ───────────────────────── file-based logging ─────────────────────────

    def set_skip_unprocessed_logging(self, skip: bool) -> None:
        """
        Enable or disable logging to EVENT_UNPROCESSED.md.

        Used during memory-processing runs to prevent infinite loops where
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

        Returns:
            True if logging to EVENT_UNPROCESSED.md should be skipped.
        """
        # Check if memory is disabled in settings
        if not _is_memory_enabled():
            return True

        # Check explicit flag (set during memory-processing runs)
        return self._skip_unprocessed_logging

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

    def _log_to_files(self, kind: str, message: str, temp_dir: Optional[Path]) -> None:
        """
        Append an event to the writing session's EVENT.md and (optionally)
        EVENT_UNPROCESSED.md.

        Both files live in the session's own workspace directory (``temp_dir``
        = ``agent_file_system/workspace/sessions/<id>/``), so each session keeps
        an isolated event log and memory-staging queue. This method is
        thread-safe and handles file I/O errors gracefully. Events are written
        in the format: [YYYY-MM-DD HH:MM:SS] [kind]: message

        Args:
            kind: Event category (e.g., "action", "trigger")
            message: Event message content
            temp_dir: The writing session's workspace dir. ``None`` during very
                early boot (main stream before its workspace is wired) — the
                event stays in memory and no file is written.
        """
        if temp_dir is None:
            return

        # Format: [YYYY-MM-DD HH:MM:SS] [kind]: message — LOCAL time, in the
        # canonical stamp format shared with MEMORY.md items.
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        event_line = f"[{timestamp}] [{kind}]: {message}\n"

        with self._file_lock:
            # Always write to EVENT.md (create if doesn't exist)
            try:
                event_file = temp_dir / "EVENT.md"
                rotate_md_file_if_needed(event_file)
                with open(event_file, "a", encoding="utf-8") as f:
                    f.write(event_line)
            except Exception as e:
                logger.warning(f"[EventStreamManager] Failed to write to EVENT.md: {e}")

            # Write to EVENT_UNPROCESSED.md unless:
            # 1. Skip is active (memory-processing run)
            # 2. Event type is in the skip list (routine events)
            if not self._should_skip_unprocessed() and not self._should_skip_event_type(
                kind
            ):
                try:
                    unprocessed_file = temp_dir / "EVENT_UNPROCESSED.md"
                    # Seed the standard header on first write so the
                    # memory-processor skill's fixed line offsets stay valid.
                    if not unprocessed_file.exists():
                        unprocessed_file.write_text(
                            UNPROCESSED_HEADER, encoding="utf-8"
                        )
                    rotate_md_file_if_needed(unprocessed_file)
                    with open(unprocessed_file, "a", encoding="utf-8") as f:
                        f.write(event_line)
                except Exception as e:
                    logger.warning(
                        f"[EventStreamManager] Failed to write to EVENT_UNPROCESSED.md: {e}"
                    )

    # ───────────────────────────── utilities ─────────────────────────────

    def log(
        self,
        kind: str,
        message: str,
        severity: str = "INFO",
        *,
        event_type: Optional[EventType] = None,
        display_message: str | None = None,
        action_name: str | None = None,
        action_display_name: str | None = None,
        action_id: str | None = None,
        action_input: Optional[dict] = None,
        action_output: Optional[dict] = None,
        platform: Optional[str] = None,
        continue_work: Optional[bool] = None,
        question: Optional[dict] = None,
        task_id: str | None = None,
    ) -> int:
        """
        Log directly to a session's event stream.

        Args:
            kind: Event family such as ``"action_start"`` or ``"warn"``.
            message: Main event text.
            severity: Importance level, defaulting to ``"INFO"``.
            display_message: Optional trimmed message for UI surfaces.
            action_name: Optional action label for file-based externalization.
            task_id: The session id whose stream receives the event. If None,
                     falls back to the current turn's stream. (The parameter
                     keeps its historical name because every producer in the
                     codebase passes it as a keyword.)

        Returns:
            Index of the logged event within the target stream's tail.
        """
        logger.debug(
            f"Process Started - Logging event to stream: [{severity}] {kind} - {message}"
        )
        # Use explicit session id if provided (for cross-session isolation);
        # otherwise fall back to the current turn's stream.
        if task_id is not None and task_id in self._streams:
            stream = self._streams[task_id]
        elif task_id is not None:
            # Session id provided but stream not found — fall back to the MAIN
            # stream so no event is silently attributed to whatever session
            # happens to be active.
            logger.warning(
                f"[EVENT_STREAM] Stream not found for session_id={task_id!r}, "
                f"falling back to main stream."
            )
            stream = self._streams[MAIN_SESSION_ID]
        else:
            stream = self.get_stream()
        idx = stream.log(
            kind,
            message,
            severity,
            event_type=event_type,
            display_message=display_message,
            action_name=action_name,
            action_display_name=action_display_name,
            action_id=action_id,
            action_input=action_input,
            action_output=action_output,
            platform=platform,
            continue_work=continue_work,
            question=question,
        )

        # Also log to the writing session's markdown files for persistence.
        # `stream` is the resolved per-session stream, so stream.temp_dir points
        # at that session's workspace dir (its own EVENT.md / EVENT_UNPROCESSED.md).
        self._log_to_files(kind, message, stream.temp_dir)

        return idx

    def snapshot(self, include_summary: bool = True) -> str:
        """Return a prompt snapshot of the current turn's stream."""
        stream = self.get_stream()
        if not stream:
            return "(no events)"
        return stream.to_prompt_snapshot(include_summary=include_summary)
