# -*- coding: utf-8 -*-
"""
Memory event injector.

Trigger-driven memory retrieval. Hook this into the chokepoints that
introduce new context (user messages arriving, tasks being created) so
the agent sees relevant memories in its event stream right next to the
event that prompted the retrieval.

Behaviour:
- Runs `MemoryManager.retrieve()` with min_relevance=0.5.
- If nothing passes the threshold, nothing is logged.
- Otherwise emits one event with kind="relevant_memories" into the
  caller's event stream (per-task when session_id is provided, otherwise
  the main stream).

Single-purpose module so the call sites stay one line.
"""

from __future__ import annotations

from typing import Optional

from agent_core.core.registry.memory import get_memory_manager_or_none
from agent_core.core.registry.event_stream import get_event_stream_manager_or_none
from agent_core.core.event_stream.event import EventType
from agent_core.utils.logger import logger


_MEMORY_EVENT_KIND = "relevant_memories"
_MIN_RELEVANCE = 0.5
_TOP_K = 5


def _is_memory_enabled() -> bool:
    """Honour the memory toggle in settings.json. Defaults to True when the
    host app's settings module isn't importable (agent_core stays usable
    outside the CraftBot app)."""
    try:
        from app.ui_layer.settings.memory_settings import is_memory_enabled

        return is_memory_enabled()
    except ImportError:
        return True


def inject_memory_event(query: str, session_id: Optional[str] = None) -> None:
    """Retrieve memory for `query` and log a `relevant_memories` event.

    Args:
        query: Natural-language query — typically the user message that
            just arrived, or the instruction of a task just created.
        session_id: Target task/event-stream id. When None, the main
            (conversation) stream is used.
    """
    if not query or not query.strip():
        return

    if not _is_memory_enabled():
        return

    memory_manager = get_memory_manager_or_none()
    event_stream_manager = get_event_stream_manager_or_none()
    if memory_manager is None or event_stream_manager is None:
        return

    try:
        pointers = memory_manager.retrieve(
            query, top_k=_TOP_K, min_relevance=_MIN_RELEVANCE
        )
    except Exception as e:
        logger.warning(f"[MEMORY] inject_memory_event retrieval failed: {e}")
        return

    if not pointers:
        return

    # These are TRUNCATED previews (pointers), not full memories: each line is
    # a snippet centred on the query match, and a leading/trailing "..." marks
    # omitted text. The header says so explicitly because "..." alone is an
    # ambiguous cut-off signal — the agent must know to expand a relevant-but-
    # clipped preview (memory_search / grep_files / read the source file)
    # before relying on it.
    header = (
        "Relevant memory previews (TRUNCATED pointers, not full records; "
        '"..." marks omitted text). If a preview is relevant but clipped, '
        "read the source file or memory_search/grep for the full memory "
        "before relying on it:"
    )
    lines = []
    for ptr in pointers:
        lines.append(
            f"- [{ptr.file_path}] {ptr.section_path}: {ptr.summary} "
            f"(relevance: {ptr.relevance_score:.2f})"
        )
    message = header + "\n" + "\n".join(lines)

    # session_id=None means "no task context" — log directly to the main
    # stream rather than going through .log(task_id=None), which would fall
    # back to get_stream() / global STATE and could route the event to a
    # stale task's stream.
    try:
        if session_id is None:
            event_stream_manager.get_main_stream().log(
                _MEMORY_EVENT_KIND,
                message,
                event_type=EventType.RELEVANT_MEMORIES,
            )
        else:
            event_stream_manager.log(
                _MEMORY_EVENT_KIND,
                message,
                event_type=EventType.RELEVANT_MEMORIES,
                task_id=session_id,
            )
    except Exception as e:
        logger.warning(f"[MEMORY] inject_memory_event log failed: {e}")
