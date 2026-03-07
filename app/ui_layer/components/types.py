"""Component data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import time


@dataclass
class ChatMessage:
    """
    Data structure for a chat message.

    Represents a single message in the chat interface.

    Attributes:
        sender: Who sent the message ("user", "agent", "system", "error")
        content: The message content
        style: Style identifier for rendering
        timestamp: Unix timestamp when the message was created
        message_id: Optional unique identifier for the message
    """

    sender: str
    content: str
    style: str
    timestamp: float = field(default_factory=time.time)
    message_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Generate message_id if not provided."""
        if self.message_id is None:
            self.message_id = f"{self.sender}:{self.timestamp}"


@dataclass
class ActionItem:
    """
    Data structure for action panel item.

    Represents a task or action in the action panel.

    Attributes:
        id: Unique identifier
        name: Display name
        status: Current status ("running", "completed", "error")
        item_type: Either "task" or "action"
        parent_id: Parent task ID (for actions under a task)
        created_at: Unix timestamp when created
    """

    id: str
    name: str
    status: str  # "running", "completed", "error"
    item_type: str  # "task" or "action"
    parent_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    @property
    def is_task(self) -> bool:
        """Check if this is a task."""
        return self.item_type == "task"

    @property
    def is_action(self) -> bool:
        """Check if this is an action."""
        return self.item_type == "action"

    @property
    def is_running(self) -> bool:
        """Check if this item is running."""
        return self.status == "running"

    @property
    def is_completed(self) -> bool:
        """Check if this item is completed."""
        return self.status == "completed"

    @property
    def is_error(self) -> bool:
        """Check if this item errored."""
        return self.status == "error"


@dataclass
class FootageUpdate:
    """
    Data structure for VM footage update.

    Used to pass screenshot data to the footage display component.

    Attributes:
        image_bytes: PNG image data as bytes
        timestamp: Unix timestamp when captured
        container_id: Optional container/VM identifier
    """

    image_bytes: bytes
    timestamp: float = field(default_factory=time.time)
    container_id: Optional[str] = None


@dataclass
class StatusUpdate:
    """
    Data structure for status bar update.

    Attributes:
        message: Status message to display
        is_loading: Whether to show loading indicator
        progress: Optional progress value (0.0 to 1.0)
    """

    message: str
    is_loading: bool = False
    progress: Optional[float] = None
