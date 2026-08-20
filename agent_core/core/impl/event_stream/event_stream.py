# -*- coding: utf-8 -*-
"""
core.impl.event_stream.event_stream

The event stream maintains:
- head_summary (str | None): a compact summary of older events
- tail_events (List[EventRecord]): recent full-fidelity events

APIs:
  log(kind, message, severity="INFO") -> int (event index)
  to_prompt_snapshot(max_events=60, include_summary=True) -> str
  summarize_if_needed()  # auto-rollup when thresholds exceeded
  summarize_by_rule()        # force summarization of oldest chunk
  summarize_by_LLM()        # force summarization of oldest chunk
"""

from __future__ import annotations
from datetime import datetime, timezone
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple
from agent_core.core.event_stream.event import Event, EventRecord, EventType
from agent_core.core.protocols.llm import LLMInterfaceProtocol
from agent_core.core.prompts import EVENT_STREAM_SUMMARIZATION_PROMPT
from sklearn.feature_extraction.text import TfidfVectorizer
from agent_core.utils.logger import logger
from agent_core.decorators import profiler, OperationCategory
from agent_core.utils.token import count_tokens
import threading

SEVERITIES = ("DEBUG", "INFO", "WARN", "ERROR")
# Messages longer than this are externalized to a temp file and replaced with a
# pointer (+keywords) so a single large action output (e.g. get_notion, read_pdf,
# an http_request body) can't bloat the prompt. ~8000 chars ≈ ~2000 tokens; the
# agent retrieves the full content with grep_files / read_file when it needs it.
MAX_EVENT_INLINE_CHARS = 16000
# Always preserve at least this many most-recent events in tail_events when summarizing.
# Guards against a single oversized event (e.g. a large read_pdf result) being purged in the
# same tick it arrives — the UI consumer polls tail_events and would otherwise miss it,
# leaving the action displayed as "running" forever.
MIN_KEEP_RECENT_EVENTS = 2

# Event kinds that summarization must NEVER collapse — they are kept verbatim in
# tail_events forever, so the contract they carry survives any number of
# summarization passes. `requirements` (from set_requirement) defines the task's
# scope/definition-of-done and lives ONLY in the event stream, so losing it to a
# summary would drop the agent's success criteria. Add other kinds here to pin them.
PROTECTED_SUMMARY_KINDS = frozenset({"requirements"})

# How often to push a fresh `datetime` marker into the stream (minute-precision
# wall-clock). Kept coarse on purpose: each new marker changes the cached prompt
# prefix, so we refresh at most every 30 min (plus once right after every
# summarization, which already invalidates the cache) rather than per minute.
DATETIME_REFRESH_SECONDS = 30 * 60


def get_cached_token_count(rec: "EventRecord") -> int:
    """Get token count for an EventRecord, using cached value if available.

    This avoids repeated calls to tiktoken.encode() which is CPU-intensive.
    The token count is computed once per event and cached for subsequent access.
    """
    if rec._cached_tokens is None:
        # Cache miss - need to compute tokens (this is the slow path)
        start = time.perf_counter()
        rec._cached_tokens = count_tokens(rec.compact_line())
        duration_ms = (time.perf_counter() - start) * 1000
        profiler.record(
            "token_count_compute",
            duration_ms,
            OperationCategory.OTHER,
            {"text_length": len(rec.compact_line()), "token_count": rec._cached_tokens},
        )
    return rec._cached_tokens


class EventStream:
    """
    Per-session event stream.
    - Keep recent events verbatim (tail_events)
    - Roll older events into head_summary when hitting thresholds
    - Track session cache sync points for delta event retrieval
    """

    def __init__(
        self,
        *,
        llm: LLMInterfaceProtocol,
        summarize_at_tokens: int = 30000,
        tail_keep_after_summarize_tokens: int = 10000,
        temp_dir: Path | None = None,
    ) -> None:
        self.head_summary: Optional[str] = None
        self.llm = llm
        self.tail_events: List[EventRecord] = []
        self.summarize_at_tokens = summarize_at_tokens
        self.tail_keep_after_summarize_tokens = tail_keep_after_summarize_tokens
        self.temp_dir = temp_dir

        MINIMUM_BUFFER_TOKENS_BEFORE_NEXT_SUMMARIZATION = 2000
        if (
            tail_keep_after_summarize_tokens
            + MINIMUM_BUFFER_TOKENS_BEFORE_NEXT_SUMMARIZATION
            > summarize_at_tokens
        ):
            logger.warning(
                f"[EventStream] Value for tail_keep_after_summarize_tokens ({tail_keep_after_summarize_tokens}) "
                f"is too large relative to summarize_at_tokens ({summarize_at_tokens}). "
                f"Resetting tail_keep_after_summarize_tokens to {summarize_at_tokens - MINIMUM_BUFFER_TOKENS_BEFORE_NEXT_SUMMARIZATION}"
            )
            self.tail_keep_after_summarize_tokens = (
                summarize_at_tokens - MINIMUM_BUFFER_TOKENS_BEFORE_NEXT_SUMMARIZATION
            )

        self._lock = threading.RLock()
        self._total_tokens: int = 0
        # Wall-clock of the last `datetime` marker pushed into the stream (None
        # until the first event). Drives the periodic refresh in _maybe_push_datetime.
        self._last_datetime_ts: Optional[datetime] = None

        # Session cache tracking: maps call_type -> event_index of last synced event
        # Used to track which events have been sent to each session cache
        self._session_sync_points: dict[str, int] = {}

    # ───────────────────────────── datetime tag ──────────────────────────
    def _append_datetime_event(self) -> None:
        """Append a current date/time marker (minute precision) to the tail. Uses
        LOCAL time to match the per-event timestamps in compact_line and the
        context engine's current-datetime block — otherwise the stream shows two
        disagreeing clocks (UTC events vs local "now"). Cheap, and deliberately
        NOT in PROTECTED_SUMMARY_KINDS — if it gets summarized away a fresh one
        is pushed right after each summarization. Caller holds the lock."""
        now = datetime.now(timezone.utc)
        local = now.astimezone()
        try:
            from tzlocal import get_localzone

            tz_label = str(get_localzone())
        except Exception:
            tz_label = local.tzname() or "local"
        ev = Event(
            message=f"{local.strftime('%Y-%m-%d %H:%M')} ({tz_label})",
            kind="datetime",
            severity="INFO",
            event_type=EventType.INTERNAL,
        )
        rec = EventRecord(event=ev)
        self.tail_events.append(rec)
        self._total_tokens += get_cached_token_count(rec)
        self._last_datetime_ts = now

    def _append_summarization_notice(
        self, *, folded_events: int, folded_tokens: int, summary: str | None
    ) -> None:
        """Append a SYSTEM event announcing that summarization ran, so the UI
        surfaces it as a system message in the session's chat. Both the
        LLM-facing `message` and the UI-facing `display_message` are
        one-liners: the summary text itself lives only in head_summary
        (repeating it in the tail would double its token cost, and dumping
        it into the chat drowns the conversation). Caller holds the lock."""
        line = (
            f"Summarized {folded_events} older events (~{folded_tokens} tokens) "
            "into the running head summary."
        )
        if summary is None:
            line = (
                f"Summarization failed; pruned {folded_events} older events "
                f"(~{folded_tokens} tokens) without a summary."
            )
            display = (
                f"Event stream summarization failed, {folded_tokens} tokens "
                "were pruned without a summary"
            )
        else:
            display = (
                f"Summarized event stream, {folded_tokens} tokens were folded "
                "into summary"
            )
        ev = Event(
            message=line,
            kind="summarization",
            severity="INFO",
            display_message=display,
            event_type=EventType.SYSTEM,
        )
        rec = EventRecord(event=ev)
        self.tail_events.append(rec)
        self._total_tokens += get_cached_token_count(rec)

    def _maybe_push_datetime(self) -> None:
        """Push a fresh datetime marker on the first event and then at most once
        every DATETIME_REFRESH_SECONDS, so the stream always carries a recent
        wall-clock without churning the prompt cache every minute."""
        last = self._last_datetime_ts
        if (
            last is None
            or (datetime.now(timezone.utc) - last).total_seconds()
            >= DATETIME_REFRESH_SECONDS
        ):
            self._append_datetime_event()

    # ────────────────────────────── logging ──────────────────────────────

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
    ) -> int:
        """
        Append a new event to the stream and trigger summarization if needed.

        Messages are optionally externalized to disk when they exceed the inline
        threshold to keep prompt context lean. The returned index reflects the
        event's position in the current tail buffer, which can help correlate
        follow-up updates with prior logs.

        Args:
            kind: Human-readable label used in the prompt-facing snapshot
                (e.g., ``"action_start"``, ``"agent message to platform: X"``).
                Consumers route on `event_type`, not on this string.
            message: Full event message that may be externalized if too long.
            severity: Importance level; defaults to ``"INFO"`` if unrecognized.
            event_type: Closed-set category for UI routing. Producers should
                always pass this; calls without it are accepted only for the
                small number of internal/legacy paths that don't surface in
                the UI.
            display_message: Optional alternative string for UI display.
            action_name: Canonical action name, set on ACTION_START / ACTION_END.
            action_id: Stable identifier paired across an action's start and
                end events. Lets the UI pair a unique ``action_start`` with
                its matching ``action_end`` even when multiple parallel calls
                of the same action fire within the same second. Set by
                ``ActionManager`` (which generates it as ``run_id`` internally).
            action_input: Structured input dict for ACTION_START events.
            action_output: Structured output dict for ACTION_END events.
            platform: Originating/destination platform for chat messages.
            continue_work: For AGENT_MESSAGE events: True when this is a
                mid-run progress update and the agent keeps working after
                sending it (drives the UI's persistent "Working…" row).
            question: For AGENT_MESSAGE events: suggested-response payload
                (``{"options": [...], "allow_free_text": bool}``) when the
                message is a question the UI should pin above the composer.

        Returns:
            The zero-based index of the event within ``tail_events``.
        """
        if severity not in SEVERITIES:
            severity = "INFO"
        msg = self._externalize_message(message.strip(), action_name=action_name)
        display = display_message.strip() if display_message is not None else None
        ev = Event(
            message=msg,
            kind=kind.strip(),
            severity=severity,
            display_message=display,
            event_type=event_type,
            action_name=action_name,
            action_display_name=action_display_name,
            action_id=action_id,
            action_input=action_input,
            action_output=action_output,
            platform=platform,
            continue_work=continue_work,
            question=question,
        )
        rec = EventRecord(event=ev)

        with self._lock:
            # Pin a recent wall-clock marker ahead of this event (first event, or
            # every 30 min). Skips datetime markers themselves to avoid recursion.
            if kind != "datetime":
                self._maybe_push_datetime()
            self.tail_events.append(rec)
            self._total_tokens += get_cached_token_count(rec)
            # Summarization runs inside the lock - blocks other log() calls
            # until summarization completes
            self.summarize_if_needed()
            return len(self.tail_events) - 1

    # Convenience wrappers for common event families (optional use)
    def log_action_start(self, name: str) -> int:
        return self.log("action_start", f"{name}")

    def log_action_end(self, name: str, status: str, extra: str = "") -> int:
        msg = f"{name} -> {status}"
        if extra:
            msg += f" ({extra})"
        return self.log("action_end", msg)

    # ───────────────────── summarization & pruning ───────────────────────

    def _externalize_message(
        self, message: str, *, action_name: str | None = None
    ) -> str:
        """Persist overly long messages to a temp file and return a pointer event."""
        if len(message) <= MAX_EVENT_INLINE_CHARS or self.temp_dir is None:
            return message

        # Never externalize the retrieval actions' own outputs: they are how
        # the agent reads externalized content back, so pointering them would
        # send the agent chasing a pointer to a pointer. ("grep" / "stream
        # read" are legacy names kept for safety; the live actions are
        # grep_files / read_file.)
        if action_name in ("grep_files", "read_file", "grep", "stream read"):
            return message

        try:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S%f")
            suffix = "action"

            if action_name:
                suffix = (
                    re.sub(r"[^A-Za-z0-9._-]", "_", action_name).strip("._-")
                    or "action"
                )
            file_path = self.temp_dir / f"event_{suffix}_{ts}.txt"
            file_path.write_text(message, encoding="utf-8")
            keywords = ", ".join(self._extract_keywords(message)) or "n/a"
            return f"Action {action_name} completed. The output is too long therefore is saved in {file_path} to save token. | keywords: {keywords} | To retrieve the content, agent MUST use the 'grep_files' action to extract the context with keywords or use 'read_file' with offset/limit to read the content line by line in file."
        except Exception:
            logger.exception(
                "[EventStream] Failed to externalize long event message "
                f"(action={action_name or 'n/a'}, temp_dir={self.temp_dir})",
            )
            return message

    def summarize_if_needed(self) -> None:
        """
        Trigger summarization when the tail token count exceeds the configured threshold.

        This is a SYNCHRONOUS blocking call - if summarization is needed, it runs
        immediately and waits for completion before returning.
        """
        if self._total_tokens < self.summarize_at_tokens:
            return

        logger.debug(
            f"[EventStream] Triggering summarization: {self._total_tokens} tokens >= {self.summarize_at_tokens} threshold"
        )
        self.summarize_by_LLM()

    def _find_token_cutoff(self, events: List[EventRecord], keep_tokens: int) -> int:
        """
        Find the cutoff index such that events from cutoff to end have approximately keep_tokens.
        Returns the number of events to summarize (from the beginning).
        """
        start = time.perf_counter()
        if not events:
            return 0

        # Calculate tokens from the end, accumulating until we reach keep_tokens.
        # MIN_KEEP_RECENT_EVENTS overrides the token budget so the most recent events
        # always survive a summarization pass — needed because the UI polls tail_events
        # and would never see an event that's purged in the same tick it arrived.
        tokens_from_end = 0
        keep_count = 0
        for rec in reversed(events):
            event_tokens = get_cached_token_count(rec)
            if (
                tokens_from_end + event_tokens > keep_tokens
                and keep_count >= MIN_KEEP_RECENT_EVENTS
            ):
                break
            tokens_from_end += event_tokens
            keep_count += 1

        # Return how many events to summarize (from the beginning)
        cutoff = max(0, len(events) - keep_count)
        duration_ms = (time.perf_counter() - start) * 1000
        profiler.record(
            "find_token_cutoff",
            duration_ms,
            OperationCategory.OTHER,
            {
                "event_count": len(events),
                "events_processed": len(events),
                "cutoff": cutoff,
            },
        )
        return cutoff

    def summarize_by_LLM(self) -> None:
        """
        Summarize the oldest tail events using the language model.

        This is a SYNCHRONOUS blocking call that holds the lock for the entire
        duration, including the LLM call. This ensures no events can be added
        while summarization is in progress.

        Called from log() which already holds the lock (RLock allows reentry).
        """
        if not self.tail_events:
            return

        # Find cutoff based on tokens to keep
        cutoff = self._find_token_cutoff(
            self.tail_events, self.tail_keep_after_summarize_tokens
        )

        if cutoff <= 0:
            # Nothing old enough to summarize
            return

        # Pull protected events (e.g. requirements) out of the region being
        # summarized — they stay verbatim in the tail and are never collapsed.
        region = list(self.tail_events[:cutoff])
        protected = [r for r in region if r.event.kind in PROTECTED_SUMMARY_KINDS]
        chunk = [r for r in region if r.event.kind not in PROTECTED_SUMMARY_KINDS]
        if not chunk:
            # Everything old enough to summarize is protected — nothing to collapse.
            return

        first_ts = chunk[0].ts
        last_ts = chunk[-1].ts
        window = f"{first_ts.isoformat()} to {last_ts.isoformat()}"

        compact_lines = "\n".join(r.compact_line() for r in chunk)
        previous_summary = self.head_summary or "(none)"

        prompt = EVENT_STREAM_SUMMARIZATION_PROMPT.format(
            window=window,
            previous_summary=previous_summary,
            compact_lines=compact_lines,
        )

        try:
            # Skip LLM call if the LLM is already in a consecutive failure state
            max_failures = getattr(self.llm, "_max_consecutive_failures", 5)
            current_failures = getattr(self.llm, "consecutive_failures", 0)
            if current_failures >= max_failures:
                logger.warning(
                    f"[EventStream] Skipping LLM summarization: LLM has {current_failures} "
                    f"consecutive failures (max={max_failures}). Falling back to prune."
                )
                raise RuntimeError(
                    "LLM in consecutive failure state, skip summarization"
                )

            logger.info(
                f"[EventStream] Running synchronous summarization ({self._total_tokens} tokens)"
            )
            llm_output = self.llm.generate_response(
                user_prompt=prompt, prompt_name="EVENT_STREAM_SUMMARIZATION"
            )
            new_summary = (llm_output or "").strip()

            logger.debug(
                f"[EVENT STREAM SUMMARIZATION] llm_output_len={len(llm_output or '')}"
            )

            if not new_summary:
                logger.warning(
                    "[EVENT STREAM SUMMARIZATION] LLM returned empty summary; not updating."
                )
                return

            # Apply summary and prune events
            self.head_summary = new_summary
            # Calculate tokens being removed from the snapshotted chunk
            removed_tokens = sum(get_cached_token_count(r) for r in chunk)
            self._total_tokens -= removed_tokens
            # Keep protected events verbatim at the front of the surviving tail.
            self.tail_events = protected + self.tail_events[cutoff:]
            # Summarization breaks the prompt cache anyway, so re-stamp the time.
            self._append_datetime_event()
            self._append_summarization_notice(
                folded_events=len(chunk),
                folded_tokens=removed_tokens,
                summary=new_summary,
            )

            # Reset all session sync points - event indices are now invalid
            self._session_sync_points.clear()
            logger.info(
                f"[EventStream] Summarization complete. Tokens: {self._total_tokens}"
            )

        except Exception:
            logger.exception(
                "[EventStream] LLM summarization failed. "
                "Pruning oldest events without a summary to prevent retry spam."
            )
            # Fallback: drop the oldest chunk without generating a summary so that
            # _total_tokens falls below the threshold.  Without this, every subsequent
            # log() call would immediately re-trigger summarization and flood the logs.
            removed_tokens = sum(get_cached_token_count(r) for r in chunk)
            self._total_tokens -= removed_tokens
            # Keep protected events verbatim even on the no-LLM prune fallback.
            self.tail_events = protected + self.tail_events[cutoff:]
            self._append_datetime_event()
            self._append_summarization_notice(
                folded_events=len(chunk),
                folded_tokens=removed_tokens,
                summary=None,
            )
            self._session_sync_points.clear()

    # ───────────────────── utilities ─────────────────────

    @staticmethod
    def _extract_keywords(message: str, top_n: int = 5) -> List[str]:
        text = (message or "").strip()
        if not text:
            return []

        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        try:
            tfidf_matrix = vectorizer.fit_transform([text])
        except ValueError:
            return []

        scores = tfidf_matrix.toarray()[0]
        terms = vectorizer.get_feature_names_out()
        sorted_terms = sorted(zip(scores, terms), key=lambda kv: kv[0], reverse=True)

        keywords: List[str] = []
        for _, term in sorted_terms:
            if term and not term.isspace():
                keywords.append(term)
            if len(keywords) >= top_n:
                break
        return keywords

    # ───────────────────────── prompt accessors ──────────────────────────

    def to_prompt_snapshot(self, include_summary: bool = True) -> str:
        """
        Build a compact, human-readable history for inclusion in LLM prompts.

        The snapshot optionally includes the accumulated ``head_summary`` and
        then appends up to ``max_events`` of the most recent tail events in
        their compact string form. An empty stream returns ``"(no events)"`` to
        make absence explicit.

        Args:
            include_summary: Whether to prepend the rolled-up ``head_summary``.

        Returns:
            A newline-delimited string ready to embed in an LLM request.
        """
        lines: List[str] = []
        if include_summary and self.head_summary:
            lines.append("Summary of folded event stream: \n" + self.head_summary)

        recent = self.tail_events
        if recent:
            lines.append("Recent Event: ")
            lines.extend(r.compact_line() for r in recent)

        return "\n".join(lines) if lines else "(no events)"

    # ─────────────────────────── util / export ───────────────────────────

    def as_list(self, limit: Optional[int] = None) -> List[Event]:
        items = self.tail_events if limit is None else self.tail_events[-limit:]
        return [r.event for r in items]

    def clear(self) -> None:
        """
        Reset the stream by removing all summaries and tail events.

        This is typically used in tests or when reusing a session identifier for
        a new task to ensure no stale context leaks between runs.
        """
        self.head_summary = None
        self.tail_events.clear()
        self._total_tokens = 0
        self._session_sync_points.clear()

    # ───────────────────── Session Cache Delta Tracking ─────────────────────

    def mark_session_synced(self, call_type: str) -> None:
        """
        Mark that all current events have been synced to the session cache.

        Called after sending events to a session cache to track the sync point.
        Next call to get_delta_events() will return only events added after this.

        Args:
            call_type: The type of LLM call (e.g., "action_selection", "gui_action_selection")
        """
        with self._lock:
            # Store the current tail length as the sync point
            self._session_sync_points[call_type] = len(self.tail_events)
            logger.debug(
                f"[EventStream] Session sync point for {call_type}: {self._session_sync_points[call_type]}"
            )

    def get_delta_events(self, call_type: str) -> Tuple[str, bool]:
        """
        Get events added since the last sync point for a given call type.

        Used for session caching where only new events should be appended
        to the session cache instead of re-sending the full event stream.

        Args:
            call_type: The type of LLM call

        Returns:
            Tuple of (delta_events_string, has_delta).
            - delta_events_string: Newline-delimited string of new events
            - has_delta: True if there are new events since last sync
        """
        with self._lock:
            sync_point = self._session_sync_points.get(call_type, 0)

            # Check if summarization happened (events were pruned)
            # If sync_point is greater than current tail length, summarization occurred
            if sync_point > len(self.tail_events):
                # Return None to signal that cache needs to be invalidated
                logger.info(
                    f"[EventStream] Summarization detected for {call_type}, cache invalidation needed"
                )
                return "", False

            # Get events since sync point
            delta_events = self.tail_events[sync_point:]

            if not delta_events:
                return "", False

            lines = [r.compact_line() for r in delta_events]
            return "\n".join(lines), True

    def reset_session_sync(self, call_type: str) -> None:
        """
        Reset the sync point for a session cache.

        Called when the session cache is invalidated/recreated.

        Args:
            call_type: The type of LLM call
        """
        with self._lock:
            self._session_sync_points.pop(call_type, None)
            logger.debug(f"[EventStream] Reset session sync for {call_type}")

    def has_session_sync(self, call_type: str) -> bool:
        """Check if a sync point exists for the given call type."""
        return call_type in self._session_sync_points

    def get_event_count(self) -> int:
        """Get the current number of events in the tail."""
        return len(self.tail_events)
