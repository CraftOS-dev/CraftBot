# -*- coding: utf-8 -*-
"""
app.memory.unprocessed_queue

Per-session unprocessed-event queue helpers.

Each session owns an ``EVENT_UNPROCESSED.md`` inside its workspace directory
(``agent_file_system/workspace/sessions/<id>/``), written by the
EventStreamManager. Memory processing aggregates every session's queue into a
single, strictly time-ordered staging file that the ``memory-processor`` skill
consumes; after the run succeeds the processed events are cleared from the
source queues. The distilled memory itself stays global (one MEMORY.md).

Wiring: app/agent_base.py :: _prepare_memory_run (build_staging) and
_on_run_end / _on_run_stopped (clear_processed / discard_staging).

Notes
-----
- Enumeration is NON-recursive: ``sessions/*/EVENT_UNPROCESSED.md`` only, so a
  subagent's queue under ``sessions/<parent>/sub_<id>/`` is excluded — subagent
  event streams are ephemeral (deleted on release) and never feed memory,
  matching their DB-unpersisted treatment.
- An "event" is a line beginning with ``[`` plus any following continuation
  lines (a message can span several lines) up to the next ``[`` line. The
  10-line header (``UNPROCESSED_HEADER``) is never treated as an event.
- Timestamps use the fixed ``YYYY-MM-DD HH:MM:SS`` format, so lexicographic
  ordering of the leading stamp IS chronological ordering.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

from agent_core.core.impl.event_stream.manager import UNPROCESSED_HEADER
from app.config import AGENT_SESSIONS_ROOT, MEMORY_STAGING_DIR
from app.logger import logger

# The single file the memory-processor skill reads each run. Rebuilt fresh
# every run and removed on run-end, so a leftover from a crashed run is
# harmless: sources are only cleared on success, and the next run overwrites
# this file before reuse.
STAGING_FILE = MEMORY_STAGING_DIR / "EVENT_UNPROCESSED.md"

# Leading timestamp of an event line, e.g. "[2026-09-07 14:23:01] ...".
_STAMP_LEN = len("YYYY-MM-DD HH:MM:SS")
# An event STARTS only on a canonically-stamped line. A line that merely starts
# with "[" is NOT enough: multi-line event messages can contain their own
# bracketed lines (e.g. "[Offered suggested responses: ...]") which must stay
# attached to their parent event, not be treated as separate events — otherwise
# they get a bogus sort key and are torn away from their event during merge.
_EVENT_START = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")


def _is_event_start(line: str) -> bool:
    """True for a line that begins a new event ("[YYYY-MM-DD HH:MM:SS] [kind]: ...")."""
    return _EVENT_START.match(line) is not None


def iter_session_queue_files() -> List[Path]:
    """Every session's EVENT_UNPROCESSED.md (non-recursive; excludes subagents)."""
    if not AGENT_SESSIONS_ROOT.exists():
        return []
    return sorted(AGENT_SESSIONS_ROOT.glob("*/EVENT_UNPROCESSED.md"))


def _split_events(text: str) -> List[str]:
    """Split a queue file's body into event blocks (header lines dropped).

    Each returned block keeps its own trailing newline(s) so blocks can be
    concatenated back verbatim.
    """
    events: List[str] = []
    current: List[str] = []
    for line in text.splitlines(keepends=True):
        if _is_event_start(line):
            if current:
                events.append("".join(current))
            current = [line]
        elif current:
            # Continuation line of the in-progress event (multi-line message).
            current.append(line)
        # else: header / blank lines before the first event — ignore.
    if current:
        events.append("".join(current))
    return events


def _sort_key(block: str) -> str:
    """Chronological sort key: the leading ``YYYY-MM-DD HH:MM:SS`` stamp.

    The stamp starts at index 1 (past the ``[``). Malformed blocks sort by
    their full text, which keeps them grouped rather than crashing the run.
    """
    return block[1 : 1 + _STAMP_LEN]


def count_unprocessed_events() -> int:
    """Total unprocessed events across every session queue.

    Counts canonically-stamped event lines only, so continuation lines of a
    multi-line event (which may themselves start with "[") are not miscounted
    as separate events. This matches the event grouping used by build_staging.
    """
    total = 0
    for path in iter_session_queue_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        total += sum(1 for line in text.splitlines() if _is_event_start(line))
    return total


def build_staging() -> Tuple[int, Dict[str, int]]:
    """Merge every session queue into the staging file, oldest event first.

    Returns ``(event_count, snapshot)`` where ``snapshot`` maps each source
    queue path (str) to the number of events taken from it. The snapshot's keys
    tell :func:`reconcile_sources` which source queues to reconcile after the
    run (only the ones whose events were staged).
    Returns ``(0, {})`` and writes nothing when there is nothing to process.
    """
    per_file: List[Tuple[Path, List[str]]] = []
    for path in iter_session_queue_files():
        try:
            events = _split_events(path.read_text(encoding="utf-8"))
        except OSError as e:
            logger.warning(f"[MEMORY] Failed to read {path}: {e}")
            continue
        if events:
            per_file.append((path, events))

    if not per_file:
        return 0, {}

    merged: List[str] = [block for _, blocks in per_file for block in blocks]
    # Stable sort keeps same-timestamp events in their original per-file order.
    merged.sort(key=_sort_key)

    MEMORY_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    STAGING_FILE.write_text(UNPROCESSED_HEADER + "".join(merged), encoding="utf-8")

    snapshot = {str(path): len(blocks) for path, blocks in per_file}
    return len(merged), snapshot


def reconcile_sources(snapshot: Dict[str, int]) -> None:
    """Remove from each source queue ONLY the events the run actually processed.

    Invariant (matches the pre-per-session logic): an event leaves its
    EVENT_UNPROCESSED.md **only after** it has been processed. The
    memory-processor distills events into MEMORY.md and *then* deletes them from
    the staging file, batch by batch — so whatever REMAINS in the staging file
    is exactly the set of events that were NOT processed. We mirror that back
    onto the per-session source queues: a source event is kept if (and only if)
    it is still present in staging, and dropped if the processor consumed it.

    Consequences:
    - Full run  → staging ends empty → every processed event removed.
    - Partial / interrupted run → the un-consumed remainder stays in staging →
      those events are kept in their source queues and reprocessed next time.
    - Run that touched nothing → staging still holds everything → no source
      event is removed. Nothing is ever removed before it is processed.

    Only the queues named in ``snapshot`` are reconciled, so a session created
    mid-run (whose events never entered staging) is never touched.
    """
    from collections import Counter

    # A completed run leaves the staging file PRESENT with just its header
    # (the processor deletes event lines, not the file). A MISSING staging file
    # therefore means we cannot tell what was processed — keep every source
    # queue intact rather than risk removing an unprocessed event.
    if not STAGING_FILE.exists():
        logger.warning(
            "[MEMORY] Staging file missing at reconcile; keeping all source "
            "queues intact (events will be reprocessed next run)."
        )
        return
    try:
        remaining: "Counter[str]" = Counter(
            _split_events(STAGING_FILE.read_text(encoding="utf-8"))
        )
    except OSError as e:
        logger.warning(f"[MEMORY] Failed to read staging for reconcile: {e}")
        return

    for path_str in snapshot:
        path = Path(path_str)
        try:
            if not path.exists():
                continue
            kept: List[str] = []
            for block in _split_events(path.read_text(encoding="utf-8")):
                if remaining.get(block, 0) > 0:
                    remaining[block] -= 1  # still unprocessed → keep
                    kept.append(block)
                # else: consumed by the processor → drop
            path.write_text(UNPROCESSED_HEADER + "".join(kept), encoding="utf-8")
        except OSError as e:
            logger.warning(f"[MEMORY] Failed to reconcile source queue {path}: {e}")


def discard_staging() -> None:
    """Delete the staging file (run-end cleanup; safe if it does not exist)."""
    try:
        STAGING_FILE.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"[MEMORY] Failed to remove staging file {STAGING_FILE}: {e}")


def reset_all_queues() -> None:
    """Reset every session queue to just the header (UI "clear buffer")."""
    for path in iter_session_queue_files():
        try:
            path.write_text(UNPROCESSED_HEADER, encoding="utf-8")
        except OSError as e:
            logger.warning(f"[MEMORY] Failed to reset queue {path}: {e}")
    discard_staging()
