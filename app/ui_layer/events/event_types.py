"""UI Event types and data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, Optional


class UIEventType(Enum):
    """All UI event types that can be published through the event bus."""

    # Chat events
    USER_MESSAGE = auto()
    AGENT_MESSAGE = auto()
    SYSTEM_MESSAGE = auto()
    ERROR_MESSAGE = auto()
    INFO_MESSAGE = auto()

    # Task/Action events
    TASK_START = auto()
    TASK_END = auto()
    TASK_UPDATE = auto()
    ACTION_START = auto()
    ACTION_END = auto()
    ACTION_UPDATE = auto()

    # State events
    AGENT_STATE_CHANGED = auto()
    GUI_MODE_CHANGED = auto()

    # Footage events (for GUI mode screenshots)
    FOOTAGE_UPDATE = auto()
    FOOTAGE_CLEAR = auto()

    # Navigation events
    SHOW_MENU = auto()
    SHOW_SETTINGS = auto()
    SHOW_CHAT = auto()

    # Command events
    COMMAND_EXECUTED = auto()
    COMMAND_ERROR = auto()

    # Lifecycle events
    INTERFACE_READY = auto()
    INTERFACE_SHUTDOWN = auto()

    # Onboarding events
    ONBOARDING_STARTED = auto()
    ONBOARDING_STEP_CHANGED = auto()
    ONBOARDING_COMPLETED = auto()


@dataclass
class UIEvent:
    """
    A UI event that can be published and subscribed to.

    Attributes:
        type: The type of event (UIEventType enum)
        data: Event-specific data payload
        timestamp: When the event occurred
        source_adapter: ID of the adapter that triggered this event (if any)
        task_id: Associated task ID (if applicable)
    """

    type: UIEventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source_adapter: Optional[str] = None
    task_id: Optional[str] = None

    def __repr__(self) -> str:
        return f"UIEvent(type={self.type.name}, task_id={self.task_id})"
