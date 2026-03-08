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
    HIDDEN_ACTIONS = {
        "task_update_todos", "send message", "ignore",
        "task start", "task_start", "task end", "task_end",
    }

    # Event kinds that should be hidden from chat (reasoning, internal events)
    HIDDEN_EVENT_KINDS = {
        "reasoning", "thinking", "thought", "internal",
        "plan", "planning", "consider", "analysis",
        "reflection", "debug", "trace", "context",
        "memory", "observation", "reasoning_step",
    }

    # Track active actions: (task_id, action_name) -> action_id
    # This allows action_end events to find the corresponding action_id
    _active_actions: dict[tuple[str, str], str] = {}

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
            # Use original message for input extraction, display_message for name
            return cls._create_action_start_event(
                message, event.message, timestamp, task_id
            )

        if kind in cls.ACTION_END_KINDS or "action_end" in kind:
            # Use original message for output extraction, display_message for name
            return cls._create_action_end_event(
                message, event.message, timestamp, task_id
            )

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
        """Clean action name by removing common prefixes and suffixes."""
        # Remove prefixes like "Running ", "Starting ", etc.
        prefixes_to_remove = [
            "Running ", "Starting ", "Executing ",
            "Processing ", "Performing ", "Doing ",
        ]
        for prefix in prefixes_to_remove:
            if name.startswith(prefix):
                name = name[len(prefix):]

        # Remove suffixes like " → done", " → error", " → completed" (from action_end display_message)
        # Note: ActionManager uses "completed" and "failed" as display_status values
        suffixes_to_remove = [
            " → done", " → error", " → failed", " → completed",
            " -> done", " -> error", " -> failed", " -> completed",
        ]
        for suffix in suffixes_to_remove:
            if name.endswith(suffix):
                name = name[:-len(suffix)]

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
    def _python_str_to_json(cls, python_str: str) -> str:
        """Convert Python dict/list string representation to JSON.

        Uses ast.literal_eval to safely parse Python literals,
        then json.dumps to convert to proper JSON.
        """
        import ast
        import json

        try:
            # Parse Python literal (dict, list, etc.)
            parsed = ast.literal_eval(python_str)
            # Convert to JSON string
            return json.dumps(parsed)
        except (ValueError, SyntaxError):
            # If parsing fails, return original string
            return python_str

    @classmethod
    def _extract_input_data(cls, full_message: str) -> Optional[str]:
        """Extract input data from action start message."""
        # Pattern: "Running action X with input: {data}."
        if " with input: " in full_message:
            input_part = full_message.split(" with input: ", 1)[1]
            # Remove trailing period if present
            if input_part.endswith("."):
                input_part = input_part[:-1]
            # Convert Python dict string to JSON
            return cls._python_str_to_json(input_part)
        return None

    @classmethod
    def _extract_output_data(cls, full_message: str) -> Optional[str]:
        """Extract output data from action end message."""
        # Pattern: "Action X completed with output: {data}."
        if " with output: " in full_message:
            output_part = full_message.split(" with output: ", 1)[1]
            # Remove trailing period if present
            if output_part.endswith("."):
                output_part = output_part[:-1]
            # Convert Python dict string to JSON
            return cls._python_str_to_json(output_part)
        return None

    @classmethod
    def _create_action_start_event(
        cls,
        display_message: str,
        full_message: str,
        timestamp: datetime,
        task_id: Optional[str],
    ) -> UIEvent:
        """Create an action start event."""
        # Extract action name from display message
        action_name = display_message
        if ":" in display_message:
            action_name = display_message.split(":", 1)[1].strip()
        # Clean up the action name
        action_name = cls._clean_action_name(action_name)

        # Extract input data from full message
        input_data = cls._extract_input_data(full_message)

        # Generate action ID
        action_id = f"{task_id or 'main'}:{action_name}:{timestamp.timestamp()}"

        # Register this action for later matching by action_end
        key = (task_id or "", action_name)
        cls._active_actions[key] = action_id

        return UIEvent(
            type=UIEventType.ACTION_START,
            data={
                "action_id": action_id,
                "action_name": action_name,
                "message": display_message,
                "task_id": task_id,
                "input": input_data,
            },
            timestamp=timestamp,
            task_id=task_id,
        )

    @classmethod
    def _create_action_end_event(
        cls,
        display_message: str,
        full_message: str,
        timestamp: datetime,
        task_id: Optional[str],
    ) -> UIEvent:
        """Create an action end event."""
        # Check for error status
        is_error = (
            "error" in display_message.lower()
            or "failed" in display_message.lower()
            or "→ error" in display_message
            or "→ failed" in display_message
        )

        # Extract action name from display message
        action_name = display_message
        if ":" in display_message:
            action_name = display_message.split(":", 1)[1].strip()
        # Clean up the action name
        action_name = cls._clean_action_name(action_name)

        # Extract output data from full message
        output_data = cls._extract_output_data(full_message)

        # Extract error message if this is an error
        error_message = None
        if is_error and output_data:
            # Try to extract error from output
            if "'error':" in output_data or '"error":' in output_data:
                error_message = output_data

        # Look up the action_id from the corresponding action_start
        key = (task_id or "", action_name)
        action_id = cls._active_actions.pop(key, "")

        # Fallback: match by just action_name if exact key not found
        if not action_id:
            for (t_id, a_name), a_id in list(cls._active_actions.items()):
                if a_name == action_name:
                    action_id = a_id
                    del cls._active_actions[(t_id, a_name)]
                    break

        return UIEvent(
            type=UIEventType.ACTION_END,
            data={
                "action_id": action_id,
                "action_name": action_name,
                "message": display_message,
                "status": "error" if is_error else "completed",
                "error": is_error,
                "error_message": error_message,
                "task_id": task_id,
                "output": output_data,
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

    @classmethod
    def clear_active_actions(cls) -> None:
        """Clear all tracked active actions. Call on session reset."""
        cls._active_actions.clear()
