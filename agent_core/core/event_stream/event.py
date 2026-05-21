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
from typing import Any, Dict, Optional


SEVERITIES = ("DEBUG", "INFO", "WARN", "ERROR")


@dataclass
class Event:
    """
    Public event object with prompt context and display variants.

    Attributes:
        message: The full event message for prompts and debugging
        kind: Category describing the event family (e.g., "action_start")
        severity: Importance level (DEBUG, INFO, WARN, ERROR)
        display_message: Optional alternative message for UI display
        ts: Timestamp when event was created (UTC)
    """

    message: str
    kind: str
    severity: str
    display_message: Optional[str] = None
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def display_text(self) -> Optional[str]:
        """
        Provide a concise message for TUI display without altering the underlying event.

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
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Deserialize an event from a dictionary."""
        ts = (
            datetime.fromisoformat(data["ts"])
            if isinstance(data.get("ts"), str)
            else datetime.now(timezone.utc)
        )
        return cls(
            message=data["message"],
            kind=data["kind"],
            severity=data["severity"],
            display_message=data.get("display_message"),
            ts=ts,
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

        Returns:
            Compact string representation
        """
        t = self.ts.strftime("%H:%M:%S")
        k = self.event.kind
        msg = self.event.message
        suffix = f" x{self.repeat_count}" if self.repeat_count > 1 else ""
        return f"{t} [{k}]: {msg}{suffix}"
