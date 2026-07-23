# -*- coding: utf-8 -*-
"""
Lightweight, LLM-friendly event object in event stream.

Event = { message: str, kind: str, severity: str }
- We also track ts and repeat_count internally, but we do not require callers
  to pass them; they're attached automatically.

Event types:
    Action lifecycle: start/end (duration, status, inputs/outputs summaries, not raw blobs)
    Router decisions: chosen action and contenders (top-k) with scores (tiny)
    Mode changes: GUI/CLI/BROWSER; window focus; viewport change
    Task: plan created/updated, step advanced/failed, backtracking
    Triggers: created/fired/cancelled (time, reason)
    RAG: retrieved N docs, sources/types, tokens used (no full text)
    Retries/backoff: reason, attempt count, policy used
    Anomalies: duplicate actions back-to-back, rapid oscillation, long stalls
    Resource/metrics: token usage per turn, workspace usage deltas, time spent
    Security/policy: redactions, blocked actions
    Notes: freeform observations the agent wants the LLM to "remember" in context
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


SEVERITIES = ("DEBUG", "INFO", "WARN", "ERROR")


class EventType(str, Enum):
    """Closed set of event categories.

    The UI transformer routes solely on this field. New event categories
    are added here, not invented at call sites as ad-hoc `kind` strings.

    INVARIANT: nothing in the consumer path (UI transformer, etc.) is
    allowed to look at `kind` or `message` substrings to decide how to
    handle an event. Producers MUST set `event_type` explicitly when
    calling `log()`. The only place `kind` is consulted for typing is
    `_legacy_event_type_from_kind` below — used exclusively to upgrade
    events restored from persistence written before this field existed.
    """

    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    SYSTEM = "system"
    ERROR = "error"
    REASONING = "reasoning"
    ACTION_START = "action_start"
    ACTION_END = "action_end"
    TASK_START = "task_start"
    TASK_END = "task_end"
    WAITING_FOR_USER = "waiting_for_user"
    RELEVANT_MEMORIES = "relevant_memories"
    TODOS = "todos"
    INTERNAL = "internal"
    # A non-user trigger's instruction, written into the stream when its
    # turn claims it. EVERY turn cause enters the stream at claim time
    # (user messages as USER_MESSAGE, everything else as TRIGGER) — the
    # stream is the session's single chronological record, and warm
    # session-cache LLM calls receive ONLY new stream events.
    TRIGGER = "trigger"


# Legacy `kind` → `event_type` mapping. NEW code MUST NOT call this.
# It exists solely so that EVENT.md / sessions.db entries written before
# the `event_type` field was introduced still render correctly after
# upgrade. Once all such persistence has rolled over, this map can be
# deleted along with `_legacy_event_type_from_kind`.
_LEGACY_KIND_TO_EVENT_TYPE: Dict[str, "EventType"] = {
    "action_start": EventType.ACTION_START,
    "action_end": EventType.ACTION_END,
    "action_error": EventType.ACTION_END,
    "gui action start": EventType.ACTION_START,
    "gui action end": EventType.ACTION_END,
    "task_start": EventType.TASK_START,
    "task_started": EventType.TASK_START,
    "task_end": EventType.TASK_END,
    "task_ended": EventType.TASK_END,
    "agent reasoning": EventType.REASONING,
    "reasoning": EventType.REASONING,
    "waiting_for_user": EventType.WAITING_FOR_USER,
    "relevant_memories": EventType.RELEVANT_MEMORIES,
    "system": EventType.SYSTEM,
    "error": EventType.ERROR,
    "warning": EventType.SYSTEM,
    "loop_detection_warning": EventType.SYSTEM,
    "internal": EventType.INTERNAL,
    "todos": EventType.TODOS,
}


def _legacy_event_type_from_kind(kind: Optional[str]) -> Optional["EventType"]:
    """Map a legacy free-text `kind` string to an `EventType`.

    DO NOT call this for routing decisions in new code. It is only used
    by `Event.from_dict()` to upgrade persisted events that lack an
    explicit `event_type` field.
    """
    if not kind:
        return None
    k = kind.lower().strip()
    if k in _LEGACY_KIND_TO_EVENT_TYPE:
        return _LEGACY_KIND_TO_EVENT_TYPE[k]
    if k.startswith("agent message"):
        return EventType.AGENT_MESSAGE
    if k.startswith("user message"):
        return EventType.USER_MESSAGE
    return None


@dataclass
class Event:
    """
    Public event object with prompt context and display variants.

    Attributes:
        message: The full event message for prompts and debugging.
        kind: Human-readable label for the prompt-facing snapshot
            (e.g., ``"agent message to platform: Telegram"``). NOT used
            by the UI transformer for routing — see `event_type`.
        severity: Importance level (DEBUG, INFO, WARN, ERROR).
        display_message: Optional alternative message for UI display.
        ts: Timestamp when event was created (UTC).
        event_type: Closed-set category used by consumers for routing,
            hiding, and rendering. Producers set this explicitly.
        action_name: Canonical action identifier when this event belongs
            to an action lifecycle (start/end). None otherwise.
        action_display_name: User-facing name (typically the snake_case
            action name reformatted to "Title case"). Optional; consumers
            fall back to `action_name` when absent.
        action_id: Stable identifier paired across an action's start and
            end events so consumers can correlate them without parsing.
            Set by ``ActionManager`` (which generates it as ``run_id``
            internally) so multiple parallel calls of the same action
            can still be matched start↔end.
        action_input: Structured input payload at action_start.
        action_output: Structured output payload at action_end.
        task_status: ``"completed"`` | ``"error"`` | ``"cancelled"`` for
            TASK_END events.
        platform: Originating/destination platform for chat messages
            (e.g., ``"Telegram"``, ``"CraftBot Interface"``).
    """

    message: str
    kind: str
    severity: str
    display_message: Optional[str] = None
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: Optional[EventType] = None
    action_name: Optional[str] = None
    action_display_name: Optional[str] = None
    action_id: Optional[str] = None
    action_input: Optional[Dict[str, Any]] = None
    action_output: Optional[Dict[str, Any]] = None
    task_status: Optional[str] = None
    platform: Optional[str] = None

    def display_text(self) -> Optional[str]:
        """
        Provide a concise message for UI display without altering the underlying event.

        The display text mirrors ``display_message`` if one was supplied during
        logging, allowing callers to present a friendlier or truncated value in
        dashboards while keeping the original ``message`` intact for summaries
        and debugging.

        Returns:
            The display-specific message set on the event, or ``None`` when the
            event should fall back to the full ``message`` value.
        """
        return self.display_message

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the event to a dictionary for persistence."""
        return {
            "message": self.message,
            "kind": self.kind,
            "severity": self.severity,
            "display_message": self.display_message,
            "ts": self.ts.isoformat(),
            "event_type": self.event_type.value if self.event_type else None,
            "action_name": self.action_name,
            "action_display_name": self.action_display_name,
            "action_id": self.action_id,
            "action_input": self.action_input,
            "action_output": self.action_output,
            "task_status": self.task_status,
            "platform": self.platform,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Deserialize an event from a dictionary.

        Events written before `event_type` existed have no value for that
        field; we upgrade them here by mapping `kind` once at load time.
        New events MUST set `event_type` at log() time, so this
        upgrade path stays cold for fresh writes.
        """
        ts = (
            datetime.fromisoformat(data["ts"])
            if isinstance(data.get("ts"), str)
            else datetime.now(timezone.utc)
        )
        raw_event_type = data.get("event_type")
        event_type: Optional[EventType]
        if raw_event_type:
            try:
                event_type = EventType(raw_event_type)
            except ValueError:
                event_type = None
        else:
            event_type = _legacy_event_type_from_kind(data.get("kind"))
        return cls(
            message=data["message"],
            kind=data["kind"],
            severity=data["severity"],
            display_message=data.get("display_message"),
            ts=ts,
            event_type=event_type,
            action_name=data.get("action_name"),
            action_display_name=data.get("action_display_name"),
            action_id=data.get("action_id"),
            action_input=data.get("action_input"),
            action_output=data.get("action_output"),
            task_status=data.get("task_status"),
            platform=data.get("platform"),
        )

    @property
    def iso_ts(self) -> str:
        """
        Convenience ISO-8601 string (UTC, seconds precision).

        Returns:
            ISO-8601 formatted timestamp string
        """
        return self.ts.isoformat(timespec="seconds")


@dataclass
class EventRecord:
    """
    Internal record with timing & dedupe info (not exposed externally).

    Attributes:
        event: The Event object
        ts: Timestamp for this record
        repeat_count: Number of times this event was repeated (for deduplication)
        _cached_tokens: Cached token count (computed lazily)
    """

    event: Event
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    repeat_count: int = 1
    _cached_tokens: int | None = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the event record to a dictionary for persistence."""
        return {
            "event": self.event.to_dict(),
            "ts": self.ts.isoformat(),
            "repeat_count": self.repeat_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventRecord":
        """Deserialize an event record from a dictionary."""
        event = Event.from_dict(data["event"])
        ts = (
            datetime.fromisoformat(data["ts"])
            if isinstance(data.get("ts"), str)
            else datetime.now(timezone.utc)
        )
        return cls(
            event=event,
            ts=ts,
            repeat_count=data.get("repeat_count", 1),
        )

    def compact_line(self) -> str:
        """
        Generate a compact single-line representation of this event.

        Format: "HH:MM:SS [kind]: message" with optional " xN" suffix for repeats.
        The time is rendered in LOCAL time: storage stays UTC, but everything the
        model sees must agree with the local wall clock the context engine's
        current-datetime block reports (and with the log files a human reads
        alongside). A naive ts (legacy persisted data) is assumed local.

        Returns:
            Compact string representation
        """
        t = self.ts.astimezone().strftime("%H:%M:%S")
        k = self.event.kind
        msg = self.event.message
        suffix = f" x{self.repeat_count}" if self.repeat_count > 1 else ""
        return f"{t} [{k}]: {msg}{suffix}"
