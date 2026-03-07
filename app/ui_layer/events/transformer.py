"""Transform agent events to UI events."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Any, TYPE_CHECKING

from app.ui_layer.events.event_types import UIEvent, UIEventType

if TYPE_CHECKING:
    from agent_core.core.impl.event_stream.event import Event


class EventTransformer:
    """
    Transform agent runtime events to standardized UI events.

    This class handles the conversion from the agent's internal event format
    to the UI layer's event format, allowing the UI to remain decoupled from
    the agent implementation details.
    """

    # Event kinds that indicate different UI event types
    TASK_START_KINDS = {"task_start", "task_started", "task created"}
    TASK_END_KINDS = {"task_end", "task_ended", "task completed", "task_completed"}
    ACTION_START_KINDS = {"action_start", "action started", "GUI action start"}
    ACTION_END_KINDS = {"action_end", "action ended", "GUI action end"}
    USER_MESSAGE_KINDS = {"user", "user message", "user_message"}
    AGENT_MESSAGE_KINDS = {"agent", "agent message", "agent_message"}
    ERROR_KINDS = {"error", "exception"}
    SYSTEM_KINDS = {"system", "system message"}
    INFO_KINDS = {"info", "note"}

    # Actions that should be hidden from the UI (for action_start/action_end events)
    HIDDEN_ACTIONS = {"task_update_todos", "send message", "ignore"}

    # Event kinds that should be hidden from chat (reasoning, internal events)
    HIDDEN_EVENT_KINDS = {
        "reasoning", "thinking", "thought", "internal",
        "plan", "planning", "consider", "analysis",
        "reflection", "debug", "trace", "context",
        "memory", "observation", "reasoning_step",
    }

    @classmethod
    def transform(
        cls,
        event: "Event",
        task_id: Optional[str] = None,
    ) -> Optional[UIEvent]:
        """
        Transform an agent event to a UI event.

        Args:
            event: The agent event to transform
            task_id: The task ID this event belongs to (if any)

        Returns:
            UIEvent if the event should be displayed, None if it should be hidden
        """
        kind = event.kind.lower() if event.kind else ""
        message = event.display_message or event.message
        timestamp = cls._parse_timestamp(event.iso_ts)

        # Check for hidden event kinds (reasoning, thinking, etc.) FIRST
        if cls._is_hidden_event(kind, message):
            return None

        # Handle task events BEFORE hidden action check (task_start is in HIDDEN_ACTIONS
        # but we want to process task events, not hide them)
        if kind in cls.TASK_START_KINDS or "task_start" in kind:
            return cls._create_task_start_event(message, timestamp, task_id)

        if kind in cls.TASK_END_KINDS or "task_end" in kind:
            return cls._create_task_end_event(message, timestamp, task_id)

        # Check for hidden actions (applies to action events only)
        if cls._is_hidden_action(kind, message):
            return None

        if kind in cls.ACTION_START_KINDS or "action_start" in kind:
            return cls._create_action_start_event(message, timestamp, task_id)

        if kind in cls.ACTION_END_KINDS or "action_end" in kind:
            return cls._create_action_end_event(message, timestamp, task_id)

        if kind in cls.USER_MESSAGE_KINDS:
            # Skip - user messages are emitted directly by UIController.submit_message()
            # to avoid duplicate display
            return None

        if kind in cls.AGENT_MESSAGE_KINDS:
            return UIEvent(
                type=UIEventType.AGENT_MESSAGE,
                data={"message": message},
                timestamp=timestamp,
                task_id=task_id,
            )

        if kind in cls.ERROR_KINDS:
            return UIEvent(
                type=UIEventType.ERROR_MESSAGE,
                data={"message": message},
                timestamp=timestamp,
                task_id=task_id,
            )

        if kind in cls.SYSTEM_KINDS:
            return UIEvent(
                type=UIEventType.SYSTEM_MESSAGE,
                data={"message": message},
                timestamp=timestamp,
                task_id=task_id,
            )

        if kind in cls.INFO_KINDS:
            return UIEvent(
                type=UIEventType.INFO_MESSAGE,
                data={"message": message},
                timestamp=timestamp,
                task_id=task_id,
            )

        # Check for GUI mode changes
        if "gui mode" in kind.lower():
            is_gui = "start" in kind.lower() or "enter" in kind.lower()
            return UIEvent(
                type=UIEventType.GUI_MODE_CHANGED,
                data={"gui_mode": is_gui, "message": message},
                timestamp=timestamp,
                task_id=task_id,
            )

        # Don't show unknown events - they're usually internal agent events
        # that shouldn't be displayed in chat
        return None

    @classmethod
    def _is_hidden_action(cls, kind: str, message: str) -> bool:
        """Check if this action should be hidden from the UI."""
        message_lower = message.lower() if message else ""

        # Check hidden action names
        for hidden in cls.HIDDEN_ACTIONS:
            if hidden in kind or hidden in message_lower:
                return True

        # Skip screenshot events in CLI (handled separately for TUI)
        if "screen" in kind and "shot" in kind:
            return True

        return False

    @classmethod
    def _is_hidden_event(cls, kind: str, message: str) -> bool:
        """Check if this event should be hidden from the chat."""
        # Check against hidden event kinds
        for hidden_kind in cls.HIDDEN_EVENT_KINDS:
            if hidden_kind in kind:
                return True

        # Also check message content for reasoning patterns
        message_lower = message.lower() if message else ""
        reasoning_indicators = [
            "thinking about", "considering", "analyzing",
            "let me think", "i should", "i need to",
            "reasoning:", "thought:", "plan:",
        ]
        for indicator in reasoning_indicators:
            if indicator in message_lower:
                return True

        return False

    @classmethod
    def _clean_action_name(cls, name: str) -> str:
        """Clean action name by removing common prefixes."""
        prefixes_to_remove = [
            "Running ", "Starting ", "Executing ",
            "Processing ", "Performing ", "Doing ",
        ]
        for prefix in prefixes_to_remove:
            if name.startswith(prefix):
                name = name[len(prefix):]
        return name.strip()

    @classmethod
    def _create_task_start_event(
        cls,
        message: str,
        timestamp: datetime,
        task_id: Optional[str],
    ) -> UIEvent:
        """Create a task start event."""
        # Extract task name from message
        task_name = message
        if ":" in message:
            task_name = message.split(":", 1)[1].strip()
        # Clean up the task name
        task_name = cls._clean_action_name(task_name)

        return UIEvent(
            type=UIEventType.TASK_START,
            data={
                "task_id": task_id or "",
                "task_name": task_name,
                "message": message,
            },
            timestamp=timestamp,
            task_id=task_id,
        )

    @classmethod
    def _create_task_end_event(
        cls,
        message: str,
        timestamp: datetime,
        task_id: Optional[str],
    ) -> UIEvent:
        """Create a task end event."""
        # Check for error status
        is_error = "error" in message.lower() or "failed" in message.lower()

        return UIEvent(
            type=UIEventType.TASK_END,
            data={
                "task_id": task_id or "",
                "message": message,
                "status": "error" if is_error else "completed",
            },
            timestamp=timestamp,
            task_id=task_id,
        )

    @classmethod
    def _create_action_start_event(
        cls,
        message: str,
        timestamp: datetime,
        task_id: Optional[str],
    ) -> UIEvent:
        """Create an action start event."""
        # Extract action name from message
        action_name = message
        if ":" in message:
            action_name = message.split(":", 1)[1].strip()
        # Clean up the action name
        action_name = cls._clean_action_name(action_name)

        # Generate action ID
        action_id = f"{task_id or 'main'}:{action_name}:{timestamp.timestamp()}"

        return UIEvent(
            type=UIEventType.ACTION_START,
            data={
                "action_id": action_id,
                "action_name": action_name,
                "message": message,
                "task_id": task_id,
            },
            timestamp=timestamp,
            task_id=task_id,
        )

    @classmethod
    def _create_action_end_event(
        cls,
        message: str,
        timestamp: datetime,
        task_id: Optional[str],
    ) -> UIEvent:
        """Create an action end event."""
        # Check for error status
        is_error = (
            "error" in message.lower()
            or "failed" in message.lower()
            or "→ error" in message
            or "→ failed" in message
        )

        # Extract action name
        action_name = message
        if ":" in message:
            action_name = message.split(":", 1)[1].strip()
        # Clean up the action name
        action_name = cls._clean_action_name(action_name)

        return UIEvent(
            type=UIEventType.ACTION_END,
            data={
                "action_name": action_name,
                "message": message,
                "status": "error" if is_error else "completed",
                "error": is_error,
                "task_id": task_id,
            },
            timestamp=timestamp,
            task_id=task_id,
        )

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
        return datetime.utcnow()
