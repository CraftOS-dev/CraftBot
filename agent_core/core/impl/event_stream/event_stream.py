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
  summarize_by_LLM(keep_tokens)  # force summarization of oldest chunk
"""

from __future__ import annotations
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from agent_core.core.event_stream.event import (
    SESSION_ID_INPUT_KEY,
    Event,
    EventRecord,
    EventType,
)
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

# A user message is externalized like any other long event, but its text is
# the request itself, so it is not left for the agent to look up: CraftBot
# reads the saved file back into the stream right after the pointer, before
# the turn decides (AgentBase._log_deferred_user_messages). The text comes back
# in parts of at most this many characters; with its header and footer each
# part stays under MAX_EVENT_INLINE_CHARS, so nothing collapses a part back
# into a pointer before the model has read it.
USER_MESSAGE_PART_CHARS = 15000

# Event.externalized["content"] values.
EXTERNALIZED_USER_MESSAGE = "user_message"
EXTERNALIZED_OUTPUT = "output"

# The event kind of a part of a user message read back from its file.
USER_MESSAGE_PART_KIND = "user message (full text)"


class UserMessageReadBackError(Exception):
    """A user message saved to a file could not be read back in full.

    ``code`` says why: "missing", "unreadable", "outside_storage", "empty",
    "incomplete", "corrupted", "timeout" or "not_read_back" (a request was
    about to carry the pointer without the text). The message was not
    processed; its file is left in place.
    """

    def __init__(self, code: str, reason: str, *, path: str, chars: int):
        super().__init__(f"{reason} ({path})")
        self.code = code
        self.reason = reason
        self.path = path
        self.chars = chars


def split_user_message(text: str) -> List[str]:
    """``text`` in parts of at most USER_MESSAGE_PART_CHARS characters that
    join back to exactly ``text``; a part ends after a line break or space
    when one falls in its second half."""
    parts: List[str] = []
    start = 0
    while len(text) - start > USER_MESSAGE_PART_CHARS:
        end = start + USER_MESSAGE_PART_CHARS
        floor = start + USER_MESSAGE_PART_CHARS // 2
        cut = text.rfind("\n", floor, end)
        if cut < 0:
            cut = text.rfind(" ", floor, end)
        cut = end if cut < 0 else cut + 1
        parts.append(text[start:cut])
        start = cut
    parts.append(text[start:])
    return parts


def user_message_for_query(text: str) -> str:
    """How a turn's instruction ({query}) quotes a user message.

    A long one is externalized and read back into the event stream in full,
    which the decision prompt renders above {query}; quoting it again would
    send it twice. A short one is quoted as it always was.
    """
    if len(text) <= MAX_EVENT_INLINE_CHARS:
        return text
    return (
        f"[the user's {len(text):,}-character message: its full text is in "
        "the event stream above; act on that text]"
    )


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


@dataclass(frozen=True)
class FoldRecord:
    """A fold that shrank the stream: when (epoch seconds), and by how many
    tokens, the running summary's growth already subtracted."""

    at: float
    freed_tokens: int


# How a delta shows an action_start whose input the model's own reply (the
# assistant message right before the delta) already holds.
INPUT_IN_REPLY = "Running action {name} (input as in your reply above)."


@dataclass(frozen=True)
class _ReplyInHistory:
    """A decision reply as the session history holds it: its reasoning and
    each action's name and parameters, copied when it was recorded."""

    reasoning: Optional[str]
    actions: Tuple[Tuple[str, Any], ...]

    @classmethod
    def of(cls, decision: Dict[str, Any]) -> "_ReplyInHistory":
        items = decision.get("actions")
        if not isinstance(items, list):
            items = [decision]  # the single-action reply form
        actions = tuple(
            (item.get("action_name"), copy.deepcopy(item.get("parameters") or {}))
            for item in items
            if isinstance(item, dict) and item.get("action_name")
        )
        reasoning = decision.get("reasoning")
        return cls(reasoning if isinstance(reasoning, str) else None, actions)


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
        # The stream never decides to fold on its own, nor how much a fold
        # keeps. The router asks for a fold (summarize_by_LLM) when the NEXT
        # REQUEST would not fit the model's context budget, and says how many
        # recent tokens to keep.
        self.head_summary: Optional[str] = None
        self.llm = llm
        self.tail_events: List[EventRecord] = []
        self.temp_dir = temp_dir

        self._lock = threading.RLock()
        self._total_tokens: int = 0
        # Wall-clock of the last `datetime` marker pushed into the stream (None
        # until the first event). Drives the periodic refresh in _maybe_push_datetime.
        self._last_datetime_ts: Optional[datetime] = None

        # Session cache tracking: maps call_type -> event_index of last synced event
        # Used to track which events have been sent to each session cache
        self._session_sync_points: dict[str, int] = {}
        # Why a call type has no sync point now ("fold", "clear", or the
        # reason given to reset_session_sync). The full request that starts
        # its next session history is labeled with it (unsynced_reason).
        self._unsynced_reasons: dict[str, str] = {}
        # Per call type: the decision reply its session history ends with
        # (set_reply_in_history). A delta refers to what the model wrote there
        # instead of sending it a second time (get_delta_events).
        self._replies_in_history: dict[str, _ReplyInHistory] = {}

        # The latest fold that shrank the stream (None: none since it was
        # created, restored or cleared). Until the next request reports its
        # size, the chat input's context readout subtracts it.
        self.last_fold: Optional[FoldRecord] = None

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

    def _drop_skills(self, dropped: List[EventRecord]) -> None:
        """Account for skill-instruction events a fold removed (of skills no
        longer loaded, or superseded by a newer load). The caller has already
        removed the records from tail_events and holds the lock."""
        self._total_tokens -= sum(get_cached_token_count(r) for r in dropped)

    def _loaded_skill_records(self) -> List[EventRecord]:
        """The newest SKILL_INSTRUCTIONS record of every skill the stream has
        loaded and not unloaded since, in stream order. Caller holds the lock."""
        newest: Dict[str, EventRecord] = {}
        for rec in self.tail_events:
            name = rec.event.skill_name
            if rec.event.event_type is EventType.SKILL_INSTRUCTIONS and name:
                newest.pop(name, None)  # keeps stream order on a reload
                newest[name] = rec
            elif rec.event.event_type is EventType.SKILL_UNLOADED and name:
                newest.pop(name, None)
        return list(newest.values())

    def loaded_skills(self) -> List[str]:
        """Names of the skills whose instructions the stream holds as loaded."""
        with self._lock:
            return [r.event.skill_name for r in self._loaded_skill_records()]

    def loaded_skill_tokens(self) -> int:
        """Tokens of the loaded skills' instructions: a fold always keeps them,
        so its budget counts them like the rest of what it does not shrink."""
        with self._lock:
            return sum(get_cached_token_count(r) for r in self._loaded_skill_records())

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
        skill_name: Optional[str] = None,
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
        if event_type in (EventType.ACTION_SCHEMAS, EventType.SKILL_INSTRUCTIONS):
            # Schemas and skill instructions are only useful verbatim: a
            # pointer would make the agent read them back through read_file
            # before every call.
            msg, externalized = message.strip(), None
        else:
            msg, externalized = self._externalize(
                message.strip(),
                action_name=action_name,
                event_type=event_type,
                kind=kind.strip(),
            )
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
            skill_name=skill_name,
            externalized=externalized,
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
        """The pointer _externalize writes for ``message`` (or ``message``)."""
        return self._externalize(message, action_name=action_name, force=force)[0]

    def _externalize(
        self,
        message: str,
        *,
        action_name: str | None = None,
        event_type: Optional[EventType] = None,
        kind: str = "",
        force: bool = False,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Persist an overly long message to a temp file; return the pointer
        that replaces it and its Event.externalized metadata (``(message,
        None)`` when it stays inline).

        `force` overrides the retrieval-action exemption below. It is used by
        `_shrink_pinned_oversize`, where the agent has already consumed the
        content in its own turn and the only thing left to do with an oversized
        event is stop paying for it every prompt.

        The pointer says what was saved: a user message's, that CraftBot reads
        the text back right after it (see USER_MESSAGE_PART_CHARS); an action
        output's, which action produced it and how to look it up.
        """
        if len(message) <= MAX_EVENT_INLINE_CHARS or self.temp_dir is None:
            return message, None

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
            return message, None

        is_user_message = event_type is EventType.USER_MESSAGE
        try:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S%f")
            suffix = "user_message" if is_user_message else "action"

            if action_name and not is_user_message:
                suffix = (
                    re.sub(r"[^A-Za-z0-9._-]", "_", action_name).strip("._-")
                    or "action"
                )
            # The random part keeps two events saved in the same clock tick
            # (a batch of messages, parallel actions) from sharing a file.
            file_path = (
                self.temp_dir / f"event_{suffix}_{ts}_{uuid.uuid4().hex[:8]}.txt"
            )
            meta: Dict[str, Any] = {
                "content": (
                    EXTERNALIZED_USER_MESSAGE
                    if is_user_message
                    else EXTERNALIZED_OUTPUT
                ),
                "path": str(file_path),
                "chars": len(message),
                "sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
            }
            if is_user_message:
                # newline="": the file holds exactly the text, so reading it
                # back can check it character for character.
                with open(file_path, "w", encoding="utf-8", newline="") as f:
                    f.write(message)
                parts = len(split_user_message(message))
                return (
                    f"[User message saved to a file] This message from the user "
                    f"is {len(message):,} characters, too long to keep in the "
                    f"event stream, so its full text is saved in {file_path}. "
                    f"CraftBot reads it back into the event stream right after "
                    f"this notice, in {parts} part(s) labelled "
                    f'"{USER_MESSAGE_PART_KIND}". That text is the user\'s '
                    f"request: act on it, not on this notice."
                ), meta
            file_path.write_text(message, encoding="utf-8")
            keywords = ", ".join(self._extract_keywords(message)) or "n/a"
            what = (
                f"Action {action_name} completed. The output"
                if action_name
                else f"The content of this {kind or 'event'} event"
            )
            return (
                f"{what} is too long therefore is saved in {file_path} to save "
                f"token. | keywords: {keywords} | To retrieve the content, agent "
                f"MUST use the 'grep_files' action to extract the context with "
                f"keywords or use 'read_file' with offset/limit to read the "
                f"content line by line in file."
            ), meta
        except Exception:
            logger.exception(
                "[EventStream] Failed to externalize long event message "
                f"(action={action_name or 'n/a'}, temp_dir={self.temp_dir})",
            )
            return message, None

    # ───────────────── user messages saved to a file ─────────────────

    def read_saved_user_message(self, meta: Dict[str, Any]) -> str:
        """The exact text of a user message saved by _externalize.

        Reads only a file inside this stream's temp_dir, at most one character
        more than was saved, and checks length and digest. Raises
        UserMessageReadBackError when it cannot return the whole text. Does
        not touch the stream (safe off the event loop, without the lock).
        """
        path_text = str(meta.get("path") or "")
        chars = int(meta.get("chars") or 0)

        def fail(code: str, reason: str) -> UserMessageReadBackError:
            return UserMessageReadBackError(code, reason, path=path_text, chars=chars)

        # Symlinks and junctions are resolved before the containment check,
        # and the RESOLVED path is the one opened, so the check covers the
        # file read; the open handle must still be that file. The digest check
        # below is the final guarantee: nothing but the user's own saved text
        # is ever returned, so a file swapped in can only cause a refusal.
        try:
            real = Path(path_text).resolve()
            inside = (
                bool(path_text)
                and self.temp_dir is not None
                and real.is_relative_to(Path(self.temp_dir).resolve())
            )
        except (OSError, ValueError, RuntimeError):
            inside = False
        if not inside:
            raise fail(
                "outside_storage", "the saved file is outside CraftBot's storage"
            )
        if not real.is_file():
            raise fail("missing", "the saved file no longer exists")
        try:
            with open(real, "r", encoding="utf-8", newline="") as f:
                if not os.path.samestat(os.fstat(f.fileno()), os.stat(real)):
                    raise fail("corrupted", "the saved file was replaced")
                text = f.read(chars + 1)
        except UnicodeDecodeError:
            raise fail("corrupted", "the saved file is not valid text")
        except OSError as e:
            raise fail(
                "unreadable", f"the saved file cannot be read ({e.strerror or e})"
            )
        if not text:
            raise fail("empty", "the saved file is empty")
        if len(text) != chars:
            raise fail(
                "incomplete",
                f"the saved file holds {len(text):,} characters, not {chars:,}",
            )
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != meta.get("sha256"):
            raise fail("corrupted", "the saved file no longer matches the message")
        return text

    def insert_user_message_parts(self, pointer: EventRecord, text: str) -> int:
        """Put ``text`` (read_saved_user_message) into the stream right after
        its ``pointer``, as split_user_message parts, and mark the pointer read
        back. Directly after it (and any parts already there), so a batch of
        messages reads pointer 1, text 1, pointer 2, text 2 however the reads
        interleave with other writes. Returns the number of parts.
        """
        meta = dict(pointer.event.externalized or {})
        path = meta.get("path", "")
        name = Path(path).name
        chunks = split_user_message(text)
        records = [
            EventRecord(
                event=Event(
                    message=(
                        f"[Part {i} of {len(chunks)} of the user message saved in "
                        f"{name}]\n{chunk}\n[End of part {i} of {len(chunks)}]"
                    ),
                    kind=USER_MESSAGE_PART_KIND,
                    severity="INFO",
                    event_type=EventType.INTERNAL,
                    platform=pointer.event.platform,
                    externalized={"part_of": path, "part": i, "parts": len(chunks)},
                )
            )
            for i, chunk in enumerate(chunks, start=1)
        ]
        with self._lock:
            at = next((i for i, r in enumerate(self.tail_events) if r is pointer), None)
            if at is None:
                at = len(self.tail_events)
            else:
                at += 1
                while at < len(self.tail_events) and (
                    (self.tail_events[at].event.externalized or {}).get("part_of")
                    == path
                ):
                    at += 1
            self.tail_events[at:at] = records
            self._total_tokens += sum(get_cached_token_count(r) for r in records)
            meta["retrieved"] = True
            pointer.event.externalized = meta
        return len(records)

    def unread_user_messages(self, up_to: Optional[int] = None) -> List[EventRecord]:
        """Pointers to saved user messages among the first ``up_to`` events
        that the model has not received and whose text was not read back, in
        stream order.

        A request carrying one would hand the model a file path instead of
        the user's request (#441), so the router refuses to send it.
        """
        with self._lock:
            unread = []
            for r in self.tail_events[:up_to]:
                meta = r.event.externalized or {}
                if (
                    not r.delivered
                    and r.event.event_type is EventType.USER_MESSAGE
                    and meta.get("content") == EXTERNALIZED_USER_MESSAGE
                    and not meta.get("retrieved")
                    and not meta.get("set_aside")
                ):
                    unread.append(r)
            return unread

    def set_aside_unsent_user_messages(
        self, why: str
    ) -> List[Tuple[int, int, Optional[str]]]:
        """Replace the user messages the model has not received with a note.

        For a run that ended without the model reading them: the request
        carrying them cannot fit the context window, or a saved one could not
        be read back. ``why`` completes "this message (N characters) ...".
        The user has been told; the note tells the model the same, so a later
        turn does not act on a message nobody processed, and says where the
        text is saved. Parts read back for a message are emptied with it. The
        chat bubble (display_message) is unchanged.

        Returns ``(characters, tokens, platform)`` for each message set aside;
        ``platform`` names the integration it came from, or is None for a
        message typed in CraftBot itself.
        """
        with self._lock:
            set_aside: List[Tuple[int, int, Optional[str]]] = []
            for rec in self.tail_events:
                event = rec.event
                if rec.delivered or event.event_type is not EventType.USER_MESSAGE:
                    continue
                meta = dict(event.externalized or {})
                if meta.get("set_aside"):
                    continue
                # "user message from platform: WhatsApp" (see
                # AgentBase._handle_chat_message); a UI message is "user message".
                _, _, platform = event.kind.partition("from platform: ")
                path = meta.get("path")
                if meta.get("content") == EXTERNALIZED_USER_MESSAGE:
                    chars = int(meta.get("chars") or 0)
                    parts = [
                        r
                        for r in self.tail_events
                        if not r.delivered
                        and (r.event.externalized or {}).get("part_of") == path
                    ]
                    tokens = sum(get_cached_token_count(r) for r in parts) or (
                        count_tokens(event.display_message or "")
                    )
                    for part in parts:
                        # Emptied in place, not removed: the UI's cursor and
                        # the sync points find events by identity and index.
                        before = get_cached_token_count(part)
                        info = part.event.externalized
                        part.event.message = (
                            f"[Part {info.get('part')} of {info.get('parts')}: "
                            "not processed]"
                        )
                        part._cached_tokens = None
                        self._total_tokens -= before - get_cached_token_count(part)
                else:
                    chars, tokens = len(event.message), count_tokens(event.message)
                    if self.temp_dir is not None:
                        try:
                            self.temp_dir.mkdir(parents=True, exist_ok=True)
                            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S%f")
                            target = (
                                self.temp_dir
                                / f"event_user_message_{ts}_{len(set_aside)}.txt"
                            )
                            target.write_text(event.message, encoding="utf-8")
                            path = str(target)
                        except Exception:
                            logger.exception(
                                "[EventStream] Failed to save a user message set aside"
                            )
                set_aside.append((chars, tokens, platform or None))
                where = f" Its full text is saved in {path}." if path else ""
                before = get_cached_token_count(rec)
                event.message = (
                    f"[Not processed: this message ({chars:,} characters) {why}, "
                    f"and the user was told.{where}]"
                )
                meta["set_aside"] = True
                event.externalized = meta
                rec._cached_tokens = None
                self._total_tokens -= before - get_cached_token_count(rec)
            return set_aside

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

    def _fold_cutoff(self, keep_tokens: int) -> int:
        """How many leading tail events a fold may collapse.

        The keep-recent window (``keep_tokens``) decides, except that a fold
        never reaches an event the model has not received. The router asks
        for a fold right after actions return, before their results are sent;
        folding those results then hands the agent a summary or a pointer of
        output it never saw, and it runs the same read again, which overflows
        again.
        """
        cutoff = self._find_token_cutoff(self.tail_events, keep_tokens)
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
            if rec.event.event_type in (
                EventType.ACTION_SCHEMAS,
                EventType.SKILL_INSTRUCTIONS,
            ):
                continue
            pointer, meta = self._externalize(
                message,
                action_name=rec.event.action_name,
                event_type=rec.event.event_type,
                kind=rec.event.kind,
                force=True,
            )
            if pointer is message:
                # Externalization failed (already logged); leave the event alone.
                continue
            before = get_cached_token_count(rec)
            rec.event.message = pointer
            if meta is not None and meta["content"] == EXTERNALIZED_USER_MESSAGE:
                # Collapsed after the model has read it: nothing to read back.
                meta["retrieved"] = True
            rec.event.externalized = meta
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
        the fold keeps at most its keep target of what the model had read
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

    def summarize_by_LLM(
        self,
        keep_tokens: int,
        *,
        prune: bool = True,
        summarizer: Optional[Callable[[EventRecord], Optional[str]]] = None,
    ) -> int:
        """
        Summarize the oldest tail events using the language model, keeping
        about ``keep_tokens`` of the most recent events verbatim.

        ``prune``: when the oldest events cannot be summarized (too few tokens
        to be worth an LLM call, or the call fails), drop them without a
        summary anyway. A fold the context budget requires must free room; a
        fold the user asks for passes False, and then a failed summary call
        raises and leaves the stream as it was.

        ``summarizer``: writes the new summary from a conversation that
        already holds the events being folded (the session's history),
        given the last of them; None or an empty result falls back to the
        standalone summary call, which is sent the events themselves.

        This is a SYNCHRONOUS blocking call that holds the lock for the entire
        duration, including the LLM call. This ensures no events can be added
        while summarization is in progress.

        Returns how many tokens the stream shrank by (0: unchanged).
        """
        with self._lock:
            before = self._total_tokens + count_tokens(self.head_summary or "")
            self._summarize(keep_tokens, prune, summarizer)
            freed = before - self._total_tokens - count_tokens(self.head_summary or "")
            if freed:
                self.last_fold = FoldRecord(at=time.time(), freed_tokens=freed)
            return freed

    def _summarize(
        self,
        keep_tokens: int,
        prune: bool,
        summarizer: Optional[Callable[[EventRecord], Optional[str]]] = None,
    ) -> None:
        """summarize_by_LLM's fold. Caller holds the lock."""
        if not self.tail_events:
            return

        # Find cutoff based on tokens to keep (never past what the model has read)
        cutoff = self._fold_cutoff(keep_tokens)

        # Collapse anything oversized that the recent-event pin is holding
        # verbatim BEFORE deciding whether an LLM call is warranted — that alone
        # often drops the stream back under the threshold for free.
        if self._shrink_pinned_oversize(cutoff):
            # Budget changed; the fold boundary moves with it.
            cutoff = self._fold_cutoff(keep_tokens)

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
        # - the newest instructions of every loaded skill stay verbatim too:
        #   they are the skill, for as long as it is loaded. A skill's older
        #   or unloaded instructions are dropped without a summary (its unload
        #   marker folds like any other event);
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
        loaded_skills = set(map(id, self._loaded_skill_records()))
        protected: List[EventRecord] = []
        dropped_schemas: List[EventRecord] = []
        dropped_skills: List[EventRecord] = []
        chunk: List[EventRecord] = []
        for r in region:
            if newest_protected.get(r.event.kind) is r:
                protected.append(r)
            elif r.event.event_type is EventType.ACTION_SCHEMAS:
                if in_use.intersection(r.event.schema_actions or ()):
                    protected.append(r)
                else:
                    dropped_schemas.append(r)
            elif r.event.event_type is EventType.SKILL_INSTRUCTIONS:
                if id(r) in loaded_skills:
                    protected.append(r)
                else:
                    dropped_skills.append(r)
            else:
                chunk.append(r)
        if not chunk:
            if dropped_schemas or dropped_skills:
                self.tail_events = protected + self.tail_events[cutoff:]
                self._drop_schemas(dropped_schemas)
                self._drop_skills(dropped_skills)
                self._clear_sync_points("fold")
            # Everything else old enough to summarize is protected.
            return

        chunk_tokens = sum(get_cached_token_count(r) for r in chunk)
        if chunk_tokens < MIN_FOLD_TOKENS:
            if not prune:
                # Too little to summarize, and this fold may not drop it.
                return
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
            self._drop_skills(dropped_skills)
            self._clear_sync_points("fold")
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
            new_summary = ""
            if summarizer is not None:
                # Written on the session's history, which holds every event
                # of the chunk; its input comes from the provider's cache.
                try:
                    new_summary = (summarizer(chunk[-1]) or "").strip()
                except Exception:
                    logger.exception(
                        "[EventStream] Summary on the session history failed; "
                        "falling back to the standalone summary call"
                    )
            if not new_summary:
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
                if not prune:
                    raise RuntimeError("The model returned an empty summary.")
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
            self._drop_skills(dropped_skills)

            # Reset all session sync points - event indices are now invalid
            self._clear_sync_points("fold")
            logger.info(
                f"[EventStream] Summarization complete. Tokens: {self._total_tokens}"
            )

        except Exception:
            if not prune:
                raise
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
            self._drop_skills(dropped_skills)
            self._clear_sync_points("fold")

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

    def to_prompt_snapshot(
        self, include_summary: bool = True, up_to: Optional[int] = None
    ) -> str:
        """
        Build a compact, human-readable history for inclusion in LLM prompts.

        The snapshot optionally includes the accumulated ``head_summary`` and
        then appends up to ``max_events`` of the most recent tail events in
        their compact string form. An empty stream returns ``"(no events)"`` to
        make absence explicit.

        Args:
            include_summary: Whether to prepend the rolled-up ``head_summary``.
            up_to: Only the first ``up_to`` tail events (the events a request
                carries, see get_event_count); None for all of them.

        Returns:
            A newline-delimited string ready to embed in an LLM request.
        """
        with self._lock:
            lines: List[str] = []
            if include_summary and self.head_summary:
                lines.append("Summary of folded event stream: \n" + self.head_summary)

            recent = self.tail_events[:up_to]
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
        self._clear_sync_points("clear")
        self.last_fold = None
        # A new stream: its first event gets a fresh datetime marker.
        self._last_datetime_ts = None

    # ───────────────────── Session Cache Delta Tracking ─────────────────────

    def mark_delivered(self, up_to: Optional[int] = None) -> None:
        """Record that the model has received every event now in the tail
        (or the first ``up_to`` of them).

        Called once a request carrying the stream has been answered: through
        mark_session_synced on the session-cache paths, and by the router
        after a stateless request. Events logged later stay undelivered until
        the next answered request, so a fold cannot collapse them first.
        """
        with self._lock:
            for rec in self.tail_events[:up_to]:
                rec.delivered = True

    def sync_marker(self, call_type: str) -> Optional[Dict[str, Any]]:
        """A session cache's sync point in a form that can be checked after
        a restart: the point, the timestamps of the first and last event
        before it, and a digest of the head summary. None when the call type
        has no sync point."""
        with self._lock:
            point = self._session_sync_points.get(call_type)
            return None if point is None else self._marker_at(point)

    def restore_sync_point(self, call_type: str, marker: Dict[str, Any]) -> bool:
        """Put back a sync point saved with sync_marker, but only if this
        stream still holds the same events before it (same summary, same
        first and last event). Otherwise there is none, and the next request
        sends the whole stream."""
        with self._lock:
            point = marker.get("point")
            if not isinstance(point, int) or not 0 <= point <= len(self.tail_events):
                return False
            if self._marker_at(point) != marker:
                return False
            self._session_sync_points[call_type] = point
            return True

    def _marker_at(self, point: int) -> Dict[str, Any]:
        """Caller holds the lock."""
        return {
            "point": point,
            "first": self.tail_events[0].ts.isoformat() if point else None,
            "last": self.tail_events[point - 1].ts.isoformat() if point else None,
            "summary": hashlib.sha256(
                (self.head_summary or "").encode("utf-8")
            ).hexdigest(),
        }

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

    def mark_session_synced(self, call_type: str, up_to: Optional[int] = None) -> None:
        """
        Mark that the events a request carried have been synced to the
        session cache.

        Called after sending events to a session cache to track the sync point.
        Next call to get_delta_events() will return only events added after this.

        Args:
            call_type: The type of LLM call (e.g., "action_selection", "gui_action_selection")
            up_to: How many tail events the request carried (get_event_count
                when it was built). Events logged while it was in flight were
                not in it and stay unsent. None: all events now in the tail.
        """
        with self._lock:
            point = len(self.tail_events) if up_to is None else up_to
            self.mark_delivered(point)
            self._session_sync_points[call_type] = point
            self._unsynced_reasons.pop(call_type, None)
            logger.debug(
                f"[EventStream] Session sync point for {call_type}: {self._session_sync_points[call_type]}"
            )

    def get_delta_events(
        self, call_type: str, up_to: Optional[int] = None
    ) -> Tuple[str, bool]:
        """
        Get events added since the last sync point for a given call type.

        Used for session caching where only new events should be appended
        to the session cache instead of re-sending the full event stream.

        Args:
            call_type: The type of LLM call
            up_to: Only events before this tail index (the events a request
                carries, see get_event_count); None for all of them.

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
            delta_events = self.tail_events[sync_point:up_to]

            if not delta_events:
                return "", False

            reply = self._replies_in_history.get(call_type)
            if reply is None:
                lines = [r.compact_line() for r in delta_events]
            else:
                lines = self._delta_lines(delta_events, reply)
            return "\n".join(lines), True

    @staticmethod
    def _delta_lines(records: List[EventRecord], reply: _ReplyInHistory) -> List[str]:
        """The delta's lines when the session history ends with ``reply``.

        What the model wrote in that reply is not sent a second time: its
        reasoning event is left out, and an action_start whose action and
        input are exactly as the reply has them is shown by reference. The
        input is compared without the session id the runtime adds to every
        action (SESSION_ID_INPUT_KEY); any other difference (filled defaults,
        an injected account) means the run changed it, so that action_start
        is sent in full. Full renders (a history's first request, EVENT.md, a
        fold's summary) always show everything.
        """
        reasoning = reply.reasoning
        actions = list(reply.actions)
        lines: List[str] = []
        for rec in records:
            event = rec.event
            if (
                reasoning
                and event.event_type is EventType.REASONING
                and event.message == reasoning
            ):
                reasoning = None  # the reply's reasoning, once
                continue
            if event.event_type is EventType.ACTION_START and isinstance(
                event.action_input, dict
            ):
                written = {
                    k: v
                    for k, v in event.action_input.items()
                    if k != SESSION_ID_INPUT_KEY
                }
                key = (event.action_name, written)
                if key in actions:
                    actions.remove(key)  # each emitted action, once
                    lines.append(
                        rec.compact_line(INPUT_IN_REPLY.format(name=event.action_name))
                    )
                    continue
            lines.append(rec.compact_line())
        return lines

    def set_reply_in_history(
        self, call_type: str, decision: Optional[Dict[str, Any]]
    ) -> None:
        """Record the decision reply ``call_type``'s session history now ends
        with; None when it ends with none a delta can refer to (the reply did
        not parse, or the history did not record it)."""
        with self._lock:
            if decision is None:
                self._replies_in_history.pop(call_type, None)
            else:
                self._replies_in_history[call_type] = _ReplyInHistory.of(decision)

    def reset_session_sync(self, call_type: str, reason: str = "reset") -> None:
        """
        Reset the sync point for a session cache.

        Called when the session cache is invalidated/recreated.

        Args:
            call_type: The type of LLM call
            reason: Why (e.g. "skill", "fold"); the full request that starts
                the next session history is labeled with it.
        """
        with self._lock:
            self._session_sync_points.pop(call_type, None)
            self._replies_in_history.pop(call_type, None)
            self._unsynced_reasons[call_type] = reason
            logger.debug(f"[EventStream] Reset session sync for {call_type} ({reason})")

    def _clear_sync_points(self, reason: str) -> None:
        """Drop every sync point, recording ``reason``. Caller holds the lock."""
        for call_type in self._session_sync_points:
            self._unsynced_reasons[call_type] = reason
        self._session_sync_points.clear()
        self._replies_in_history.clear()

    def unsynced_reason(self, call_type: str) -> str:
        """Why the next ``call_type`` request carries the whole stream: the
        reason its sync point was dropped; otherwise "restart" when the model
        has read this stream before (restored at boot without its session
        history), else "first"."""
        with self._lock:
            reason = self._unsynced_reasons.get(call_type)
            if reason:
                return reason
            if self.head_summary or any(r.delivered for r in self.tail_events):
                return "restart"
            return "first"

    def has_session_sync(self, call_type: str) -> bool:
        """Check if a sync point exists for the given call type."""
        return call_type in self._session_sync_points

    def get_event_count(self) -> int:
        """Get the current number of events in the tail."""
        return len(self.tail_events)
