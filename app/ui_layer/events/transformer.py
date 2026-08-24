"""Transform agent events to UI events.

ROUTING CONTRACT
================
Routing decisions are made *exclusively* on `event.event_type` (a closed-set
enum defined in `agent_core.core.event_stream.event.EventType`). The
transformer MUST NOT consult `event.kind` or `event.message` to decide which
UIEvent to produce, whether to hide an event, or how to classify a status —
those fields are free-text and can legitimately contain any user/agent
content (the original bug: a chat message containing the word "Ignored" was
silently hidden because `"ignore" in message_lower` matched).

If you need a new variant, add it to `EventType` and to the dispatch table
below. Producers must set `event_type` explicitly on every `log()` call.

Every transformed UI event carries the session id it came from — the second
argument of `transform()` (the owning session's event-stream id; "main" for
the main session). It is stored on `UIEvent.task_id` (a legacy field name;
see event_types.py).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

from app.ui_layer.events.event_types import UIEvent, UIEventType

if TYPE_CHECKING:
    from agent_core.core.event_stream.event import Event


def _to_wire_json(value: Optional[dict]) -> Optional[str]:
    """Serialize a structured payload to the JSON string the frontend
    expects on `ActionItem.input` / `ActionItem.output` (those fields are
    typed `string` on the wire, and the frontend's `parseDict` calls
    `.trim()` on them). Returns None when there's nothing to send.
    """
    if value is None:
        return None
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _display_name_for(action_name: str | None, display_name: str | None) -> str:
    """Pick the user-facing action name. Producers should set
    `action_display_name` explicitly; for call sites that only have a
    canonical snake_case name (e.g., the agent's action_error log), we
    apply the same transform `Action.display_name` uses on the model.
    """
    if display_name:
        return display_name
    if action_name:
        return action_name.replace("_", " ").capitalize()
    return ""


# Action names whose action_start / action_end events are not surfaced in
# the activity feed. These are internal control-flow actions, not
# user-visible work. Matched on the exact `event.action_name` field — never
# against `kind` or `message` substrings.
HIDDEN_ACTION_NAMES: frozenset[str] = frozenset(
    {
        "end_turn",
    }
)


class EventTransformer:
    """
    Transform agent runtime events to standardized UI events.

    Single dispatch on `event.event_type`. No substring matching, no kind
    parsing, no message inspection for routing.
    """

    @classmethod
    def transform(
        cls,
        event: "Event",
        session_id: Optional[str] = None,
    ) -> Optional[UIEvent]:
        """Transform an agent event to a UI event, or None if it should be hidden."""
        et = event.event_type
        if et is None:
            # Event predates structured typing (or a producer forgot to set
            # it). Legacy events restored from disk get their event_type
            # set in `Event.from_dict()` — anything still missing here is
            # either an unmigrated producer (a bug to fix at the call site)
            # or an event genuinely not meant for the UI.
            return None

        handler = cls._DISPATCH.get(et)
        if handler is None:
            return None

        timestamp = cls._parse_timestamp(event.iso_ts)
        message = event.display_message or event.message
        # `handler` is a bound classmethod descriptor — cls is supplied
        # automatically; we only pass the per-call args.
        return handler(event, message, timestamp, session_id)

    # ───────────────────────────── builders ─────────────────────────────

    @classmethod
    def _build_agent_message(
        cls, event: "Event", message: str, ts: datetime, session_id: Optional[str]
    ) -> Optional[UIEvent]:
        return UIEvent(
            type=UIEventType.AGENT_MESSAGE,
            data={
                "message": message,
                "session_id": session_id,
                "continue_work": bool(event.continue_work),
                "question": event.question,
            },
            timestamp=ts,
            task_id=session_id,
        )

    @classmethod
    def _build_user_message(
        cls, event: "Event", message: str, ts: datetime, session_id: Optional[str]
    ) -> Optional[UIEvent]:
        # User messages are emitted directly by UIController.submit_message()
        # to avoid double display in chat; we suppress the event-stream echo.
        return None

    @classmethod
    def _build_system_message(
        cls, event: "Event", message: str, ts: datetime, session_id: Optional[str]
    ) -> Optional[UIEvent]:
        return UIEvent(
            type=UIEventType.SYSTEM_MESSAGE,
            data={"message": message, "session_id": session_id},
            timestamp=ts,
            task_id=session_id,
        )

    @classmethod
    def _build_error_message(
        cls, event: "Event", message: str, ts: datetime, session_id: Optional[str]
    ) -> Optional[UIEvent]:
        return UIEvent(
            type=UIEventType.ERROR_MESSAGE,
            data={"message": message, "session_id": session_id},
            timestamp=ts,
            task_id=session_id,
        )

    @classmethod
    def _build_reasoning(
        cls, event: "Event", message: str, ts: datetime, session_id: Optional[str]
    ) -> Optional[UIEvent]:
        reasoning_id = f"{session_id or 'main'}:reasoning:{ts.timestamp()}"
        return UIEvent(
            type=UIEventType.REASONING,
            data={
                "reasoning_id": reasoning_id,
                "content": message,
                "session_id": session_id,
            },
            timestamp=ts,
            task_id=session_id,
        )

    @classmethod
    def _build_action_start(
        cls, event: "Event", message: str, ts: datetime, session_id: Optional[str]
    ) -> Optional[UIEvent]:
        canonical = event.action_name or ""
        if canonical in HIDDEN_ACTION_NAMES:
            return None
        # action_id is set by the producer (action_manager.run_id) so start
        # and end events correlate without ad-hoc dict tracking.
        action_id = (
            event.action_id or f"{session_id or 'main'}:{canonical}:{ts.timestamp()}"
        )
        return UIEvent(
            type=UIEventType.ACTION_START,
            data={
                "action_id": action_id,
                # The UI's `ActionItem.name` is the display name; the canonical
                # name is what the action library lookup uses (the frontend
                # normalizes either form).
                "action_name": _display_name_for(canonical, event.action_display_name),
                "message": message,
                "session_id": session_id,
                # Frontend `ActionItem.input` is typed `string` and gets
                # passed through `parseDict`; serialize the structured dict
                # to JSON so the existing renderers keep working.
                "input": _to_wire_json(event.action_input),
            },
            timestamp=ts,
            task_id=session_id,
        )

    @classmethod
    def _build_action_end(
        cls, event: "Event", message: str, ts: datetime, session_id: Optional[str]
    ) -> Optional[UIEvent]:
        canonical = event.action_name or ""
        if canonical in HIDDEN_ACTION_NAMES:
            return None

        output = event.action_output
        # Status is derived from the structured output, not from message text.
        is_error = bool(output and output.get("status") == "error")
        action_id = (
            event.action_id or f"{session_id or 'main'}:{canonical}:{ts.timestamp()}"
        )
        error_message = output.get("error") if is_error and output else None

        return UIEvent(
            type=UIEventType.ACTION_END,
            data={
                "action_id": action_id,
                "action_name": _display_name_for(canonical, event.action_display_name),
                "message": message,
                "status": "error" if is_error else "completed",
                "error": is_error,
                "error_message": error_message,
                "session_id": session_id,
                # Frontend `ActionItem.output` is typed `string`; serialize
                # the structured dict to JSON for `parseDict` compatibility.
                "output": _to_wire_json(output),
            },
            timestamp=ts,
            task_id=session_id,
        )

    @classmethod
    def _build_hidden(
        cls, event: "Event", message: str, ts: datetime, session_id: Optional[str]
    ) -> Optional[UIEvent]:
        """Event types that exist in the agent's stream but never surface in the UI."""
        return None

    # ───────────────────────────── dispatch ─────────────────────────────

    # Populated below the class body once EventType has been imported. The
    # dispatch table is the single routing decision in this module.
    _DISPATCH: dict = {}

    # ───────────────────────────── helpers ─────────────────────────────

    @classmethod
    def _parse_timestamp(cls, iso_ts: Any) -> datetime:
        """Parse timestamp from various formats."""
        if isinstance(iso_ts, datetime):
            return iso_ts
        if isinstance(iso_ts, str):
            try:
                return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.now(timezone.utc)


def _install_dispatch() -> None:
    """Wire EventType → builder. Done at module load, after class is defined."""
    from agent_core.core.event_stream.event import EventType

    EventTransformer._DISPATCH = {
        EventType.AGENT_MESSAGE: EventTransformer._build_agent_message,
        EventType.USER_MESSAGE: EventTransformer._build_user_message,
        EventType.SYSTEM: EventTransformer._build_system_message,
        EventType.ERROR: EventTransformer._build_error_message,
        EventType.REASONING: EventTransformer._build_reasoning,
        EventType.ACTION_START: EventTransformer._build_action_start,
        EventType.ACTION_END: EventTransformer._build_action_end,
        # Intentionally hidden from the UI (core enum values with no UI
        # surface; TODOS flows through SessionManager's post-update-todos
        # hooks instead):
        EventType.WAITING_FOR_USER: EventTransformer._build_hidden,
        EventType.RELEVANT_MEMORIES: EventTransformer._build_hidden,
        EventType.TODOS: EventTransformer._build_hidden,
        EventType.INTERNAL: EventTransformer._build_hidden,
        # Trigger claims are LLM-facing context (they ride the session-cache
        # delta); the chat-side announcement is emitted separately on the UI
        # bus by react()'s _announce_trigger, so the stream copy stays hidden
        # (also keeps the restart-restore replay from double-posting it).
        EventType.TRIGGER: EventTransformer._build_hidden,
    }


_install_dispatch()
