# -*- coding: utf-8 -*-
"""
core.impl.event_stream.event_stream

The event stream maintains:
- head_summary (str | None): a compact summary of older events
- tail_events (List[EventRecord]): recent full-fidelity events

APIs:
  log(kind, message, severity="INFO") -> int (event index)
  to_prompt_snapshot(max_events=60, include_summary=True) -> str
  summarize_by_rule()        # force summarization of oldest chunk
  summarize_by_LLM()        # force summarization of oldest chunk
"""

from __future__ import annotations
from datetime import datetime, timezone
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from agent_core.core.event_stream.event import Event, EventRecord, EventType
from agent_core.core.protocols.llm import LLMInterfaceProtocol
from agent_core.core.prompts import EVENT_STREAM_SUMMARIZATION_PROMPT
from sklearn.feature_extraction.text import TfidfVectorizer
from agent_core.utils.logger import logger
from agent_core.decorators import profiler, OperationCategory
from agent_core.utils.token import count_tokens
import threading

SEVERITIES = ("DEBUG", "INFO", "WARN", "ERROR")


def _configured_keep_recent_tokens() -> int:
    """Read context.keep_recent_tokens from settings.json.

    app.config owns the defaults and already absorbs a missing file, bad JSON
    and out-of-range values, so there is nothing left to guard here — a raised
    ImportError means the app package is genuinely gone, which is a broken
    install, not a case to paper over with a second copy of the numbers.

    The import is deferred because app.config imports agent_core at module
    scope (``from agent_core import get_credential``), and agent_core's
    __init__ loads this module — a module-scope import would close that cycle.
    By stream-construction time every module is loaded and the import is fine.

    Read once per stream, so a settings.json edit applies to sessions created
    after it; the main session's stream needs a restart.
    """
    from app.config import get_keep_recent_tokens

    return get_keep_recent_tokens()


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

# Smallest fold worth an LLM call. Summarization is a blocking ~15s round trip;
# collapsing a couple of hundred tokens with one is a straight loss and the
# threshold is breached again on the very next event, so we prune instead.
MIN_FOLD_TOKENS = 2000

# Event kinds whose NEWEST event summarization must never collapse. Each event of
# these kinds is a complete snapshot that supersedes every earlier one, so the
# newest is kept verbatim at the front of the surviving tail across any number
# of folds, and the older ones fold like any other event. `requirements` (from
# set_requirement, which always re-issues the COMPLETE list) defines the task's
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
        temp_dir: Path | None = None,
    ) -> None:
        # The stream never decides to fold on its own. The router asks for a
        # fold (summarize_by_LLM) when the NEXT REQUEST would not fit the
        # context budget; the only stream-side setting is how much recent
        # history a fold keeps. Tests pin it by patching
        # _configured_keep_recent_tokens (see the event_stream_limits fixture).
        self.head_summary: Optional[str] = None
        self.llm = llm
        self.tail_events: List[EventRecord] = []
        self.tail_keep_after_summarize_tokens = _configured_keep_recent_tokens()
        self.temp_dir = temp_dir

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
        line += " Detail from those events is gone; read your NOTE.md if you need it."
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

    def _drop_schemas(self, dropped: List[EventRecord]) -> None:
        """Account for action-schema events a fold removed and tell the agent
        which schemas left its context. INTERNAL: the agent needs to know it
        must reload them; the user's chat does not. The caller has already
        removed the records from tail_events and holds the lock."""
        if not dropped:
            return
        self._total_tokens -= sum(get_cached_token_count(r) for r in dropped)
        names = [name for r in dropped for name in (r.event.schema_actions or ())]
        ev = Event(
            message=(
                "These action schemas are no longer in context; call "
                f"add_action_sets to see them again: {', '.join(names)}."
            ),
            kind="action_schemas_dropped",
            severity="INFO",
            event_type=EventType.INTERNAL,
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
        ui_artifact: Optional[dict] = None,
        schema_actions: Optional[List[str]] = None,
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
            schema_actions: For ACTION_SCHEMAS events: the action names whose
                schemas ``message`` carries (drives the fold rule).

        Returns:
            The zero-based index of the event within ``tail_events``.
        """
        if severity not in SEVERITIES:
            severity = "INFO"
        if event_type is EventType.ACTION_SCHEMAS:
            # Schemas are only useful verbatim: a pointer would make the agent
            # read the registry back through read_file before every call.
            msg = message.strip()
        else:
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
            ui_artifact=ui_artifact,
            schema_actions=schema_actions,
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
        self,
        message: str,
        *,
        action_name: str | None = None,
        force: bool = False,
    ) -> str:
        """Persist overly long messages to a temp file and return a pointer event.

        `force` overrides the retrieval-action exemption below. It is used by
        `_shrink_pinned_oversize`, where the agent has already consumed the
        content in its own turn and the only thing left to do with an oversized
        event is stop paying for it every prompt.
        """
        if len(message) <= MAX_EVENT_INLINE_CHARS or self.temp_dir is None:
            return message

        # Never externalize the retrieval actions' own outputs: they are how
        # the agent reads externalized content back, so pointering them would
        # send the agent chasing a pointer to a pointer. ("grep" / "stream
        # read" are legacy names kept for safety; the live actions are
        # grep_files / read_file.)
        if not force and action_name in (
            "grep_files",
            "read_file",
            "grep",
            "stream read",
        ):
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

    def _fold_cutoff(self) -> int:
        """How many leading tail events a fold may collapse.

        The keep-recent window decides, except that a fold never reaches an
        event the model has not received. The router asks for a fold right
        after actions return, before their results are sent; folding those
        results then hands the agent a summary or a pointer of output it never
        saw, and it runs the same read again, which overflows again.
        """
        cutoff = self._find_token_cutoff(
            self.tail_events, self.tail_keep_after_summarize_tokens
        )
        first_undelivered = next(
            (i for i, r in enumerate(self.tail_events) if not r.delivered),
            len(self.tail_events),
        )
        return min(cutoff, first_undelivered)

    def _collapse_oversize(self, records: List[EventRecord]) -> int:
        """Externalize every oversized message among ``records``, in place.

        The record survives with its `action_id` intact so the UI (which
        mirrors `tail_events`) still pairs start↔end, and its message becomes
        a pointer the agent can re-read on demand. Action schemas stay
        verbatim on purpose; summarize_by_LLM decides their fate. Caller holds
        the lock.

        Returns the number of tokens reclaimed.
        """
        if self.temp_dir is None:
            return 0

        reclaimed = 0
        for rec in records:
            message = rec.event.message
            if len(message) <= MAX_EVENT_INLINE_CHARS:
                continue
            if rec.event.event_type is EventType.ACTION_SCHEMAS:
                continue
            pointer = self._externalize_message(
                message, action_name=rec.event.action_name, force=True
            )
            if pointer is message:
                # Externalization failed (already logged); leave the event alone.
                continue
            before = get_cached_token_count(rec)
            rec.event.message = pointer
            rec._cached_tokens = None
            reclaimed += before - get_cached_token_count(rec)

        self._total_tokens -= reclaimed
        return reclaimed

    def _shrink_pinned_oversize(self, cutoff: int) -> int:
        """Externalize oversized events the model has read in the surviving tail.

        MIN_KEEP_RECENT_EVENTS pins the newest events so the UI never loses an
        `action_end` in the tick it arrives — an action purged that early
        renders as "running" forever. But the pin is blind to size: when a
        retrieval action returns a huge payload (grep_files and read_file are
        exempt from log-time externalization, because they ARE how the agent
        reads externalized content back), the pin holds tens of thousands of
        tokens verbatim and a summarization pass cannot get under the
        threshold.

        Only delivered records are shrunk: the agent has consumed them in its
        own turn, so the only thing left to do with them is stop paying for
        them every prompt. Caller holds the lock.

        Returns the number of tokens reclaimed.
        """
        reclaimed = self._collapse_oversize(
            [r for r in self.tail_events[cutoff:] if r.delivered]
        )
        if reclaimed:
            logger.info(
                f"[EventStream] Collapsed oversized pinned event(s) in place, "
                f"reclaiming {reclaimed} tokens (now {self._total_tokens})"
            )
        return reclaimed

    def collapse_undelivered_oversize(self) -> int:
        """Externalize oversized events the model has not received yet.

        For the router only, when a request still does not fit after a fold:
        the fold keeps at most keep_recent_tokens of what the model had read
        (new events count against it), so the events it has not received are
        too large to send in full. Pointers are the only way to hand them over.

        Returns the number of tokens reclaimed (0: nothing left to shrink).
        """
        with self._lock:
            reclaimed = self._collapse_oversize(
                [r for r in self.tail_events if not r.delivered]
            )
            if reclaimed:
                logger.warning(
                    f"[EventStream] New events do not fit any request in full; "
                    f"collapsed the oversized ones to pointers, reclaiming "
                    f"{reclaimed} tokens (now {self._total_tokens})"
                )
            return reclaimed

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

        # Find cutoff based on tokens to keep (never past what the model has read)
        cutoff = self._fold_cutoff()

        # Collapse anything oversized that the recent-event pin is holding
        # verbatim BEFORE deciding whether an LLM call is warranted — that alone
        # often drops the stream back under the threshold for free.
        if self._shrink_pinned_oversize(cutoff):
            # Budget changed; the fold boundary moves with it.
            cutoff = self._fold_cutoff()

        if cutoff <= 0:
            # Nothing old enough to summarize
            return

        # Split the region being folded:
        # - the newest event of each protected kind (e.g. requirements) stays
        #   verbatim at the front of the surviving tail; older ones are
        #   superseded snapshots and fold like any other event. So do action
        #   schemas whose actions the kept tail still calls (the agent is
        #   mid-use; folding them would make it load them again next turn);
        # - every other action schema is dropped without a summary: it is a
        #   copy of the registry, and add_action_sets brings it back on demand;
        # - the rest is the chunk the LLM summarizes.
        region = list(self.tail_events[:cutoff])
        in_use = {
            r.event.action_name
            for r in self.tail_events[cutoff:]
            if r.event.action_name
        }
        newest_protected = {
            r.event.kind: r
            for r in self.tail_events
            if r.event.kind in PROTECTED_SUMMARY_KINDS
        }
        protected: List[EventRecord] = []
        dropped_schemas: List[EventRecord] = []
        chunk: List[EventRecord] = []
        for r in region:
            if newest_protected.get(r.event.kind) is r:
                protected.append(r)
            elif r.event.event_type is EventType.ACTION_SCHEMAS:
                if in_use.intersection(r.event.schema_actions or ()):
                    protected.append(r)
                else:
                    dropped_schemas.append(r)
            else:
                chunk.append(r)
        if not chunk:
            if dropped_schemas:
                self.tail_events = protected + self.tail_events[cutoff:]
                self._drop_schemas(dropped_schemas)
                self._session_sync_points.clear()
            # Everything else old enough to summarize is protected.
            return

        chunk_tokens = sum(get_cached_token_count(r) for r in chunk)
        if chunk_tokens < MIN_FOLD_TOKENS:
            # The foldable region is smaller than the LLM call is worth — the tail
            # is dominated by events we're required to keep (protected kinds, the
            # recent-event pin, or events the model has not received yet). Prune
            # the chunk without a summary rather than burn ~15s and a full
            # prompt to reclaim a rounding error. Losing this
            # little detail is cheaper than the alternative, which is re-triggering
            # on every subsequent log() call.
            logger.warning(
                f"[EventStream] Foldable region is only {chunk_tokens} tokens "
                f"(< {MIN_FOLD_TOKENS}); pruning {len(chunk)} event(s) without an "
                f"LLM call. Tail is dominated by pinned/protected events."
            )
            self._total_tokens -= chunk_tokens
            self.tail_events = protected + self.tail_events[cutoff:]
            self._append_summarization_notice(
                folded_events=len(chunk),
                folded_tokens=chunk_tokens,
                summary=None,
            )
            self._drop_schemas(dropped_schemas)
            self._session_sync_points.clear()
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
            # json_mode=False: this prompt asks for a prose summary, and
            # forcing a provider's JSON mode onto it degenerates (DeepSeek
            # returns whitespace-only output that reads as empty).
            llm_output = self.llm.generate_response(
                user_prompt=prompt,
                prompt_name="EVENT_STREAM_SUMMARIZATION",
                json_mode=False,
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
            # Tokens being removed from the snapshotted chunk (measured above).
            removed_tokens = chunk_tokens
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
            self._drop_schemas(dropped_schemas)

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
            removed_tokens = chunk_tokens
            self._total_tokens -= removed_tokens
            # Keep protected events verbatim even on the no-LLM prune fallback.
            self.tail_events = protected + self.tail_events[cutoff:]
            self._append_datetime_event()
            self._append_summarization_notice(
                folded_events=len(chunk),
                folded_tokens=removed_tokens,
                summary=None,
            )
            self._drop_schemas(dropped_schemas)
            self._session_sync_points.clear()

    def actions_with_schemas(self) -> Set[str]:
        """Names of the actions whose schemas are in the live tail."""
        with self._lock:
            return {
                name
                for r in self.tail_events
                if r.event.event_type is EventType.ACTION_SCHEMAS
                for name in (r.event.schema_actions or ())
            }

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

    def mark_delivered(self) -> None:
        """Record that the model has received every event now in the tail.

        Called once a request carrying the stream has been answered: through
        mark_session_synced on the session-cache paths, and by the router
        after a stateless request. Events logged later stay undelivered until
        the next answered request, so a fold cannot collapse them first.
        """
        with self._lock:
            for rec in self.tail_events:
                rec.delivered = True

    def replace_ui_artifact(
        self, artifact_id: str, replace: Callable[[Dict[str, Any]], Dict[str, Any]]
    ) -> int:
        """Swap the UI artifact payload of every event that carries artifact
        ``artifact_id`` for ``replace(payload)`` (the user closed it). Returns
        how many events carried it."""
        count = 0
        with self._lock:
            for rec in self.tail_events:
                artifact = rec.event.ui_artifact
                if artifact and artifact.get("id") == artifact_id:
                    rec.event.ui_artifact = replace(artifact)
                    count += 1
        return count

    def mark_session_synced(self, call_type: str) -> None:
        """
        Mark that all current events have been synced to the session cache.

        Called after sending events to a session cache to track the sync point.
        Next call to get_delta_events() will return only events added after this.

        Args:
            call_type: The type of LLM call (e.g., "action_selection", "gui_action_selection")
        """
        with self._lock:
            self.mark_delivered()
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
