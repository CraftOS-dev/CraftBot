"""Component data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List
import time


@dataclass
class Attachment:
    """
    Data structure for a message attachment.

    Represents a file attached to a chat message.

    Attributes:
        name: Original filename
        path: Path relative to workspace (where the file is stored)
        type: MIME type of the file
        size: File size in bytes
        url: URL to access the file (for browser display)
    """

    name: str
    path: str
    type: str
    size: int
    url: str


@dataclass
class ChatMessageOption:
    """
    Data structure for an interactive option/button in a chat message.

    Attributes:
        label: Button text displayed to the user (e.g. "Continue")
        value: Machine-readable value sent back on click (e.g. "continue_limit")
        style: Visual style - "primary", "danger", or "default"
        url: If set, clicking the button also opens this URL in a new tab
            (e.g. a billing/top-up link from a classified error's actions),
            in addition to dispatching `value` back over the socket.
    """

    label: str
    value: str
    style: str = "default"
    url: Optional[str] = None


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
        attachments: Optional list of file attachments
        session_id: The chat session this message belongs to ("main" default)
        options: Optional list of interactive options/buttons
        option_selected: Value of the option that was selected, if any
        error_category: ErrorCategory value (e.g. "auth", "rate_limit") when
            this message represents a classified error — lets the frontend
            pick a category-aware icon/color instead of a flat error style.
        error_code: Stable error code (e.g. "LLM_AUTH", "CONFIG_NO_API_KEY").
        error_severity: Severity value ("info"/"warning"/"error"/"critical").
    """

    sender: str
    content: str
    style: str
    timestamp: float = field(default_factory=time.time)
    message_id: Optional[str] = None
    attachments: Optional[List[Attachment]] = None
    session_id: str = "main"
    options: Optional[List[ChatMessageOption]] = None
    option_selected: Optional[str] = None
    # Client-generated UUID from the sender; echoed back so the browser can
    # reconcile optimistic-pending messages with the server-acknowledged copy.
    client_id: Optional[str] = None
    error_category: Optional[str] = None
    error_code: Optional[str] = None
    error_severity: Optional[str] = None

    def __post_init__(self) -> None:
        """Generate message_id if not provided; normalize session id."""
        if self.message_id is None:
            self.message_id = f"{self.sender}:{self.timestamp}"
        if not self.session_id:
            self.session_id = "main"

    def to_dict(self) -> dict:
        """Serialize for the WS wire format. Always emits sessionId."""
        data: dict = {
            "sender": self.sender,
            "content": self.content,
            "style": self.style,
            "timestamp": self.timestamp,
            "messageId": self.message_id,
            "sessionId": self.session_id,
        }
        if self.client_id:
            data["clientId"] = self.client_id
        if self.attachments:
            data["attachments"] = [
                {
                    "name": att.name,
                    "path": att.path,
                    "type": att.type,
                    "size": att.size,
                    "url": att.url,
                }
                for att in self.attachments
            ]
        if self.options:
            data["options"] = [
                {
                    "label": o.label,
                    "value": o.value,
                    "style": o.style,
                    **({"url": o.url} if o.url else {}),
                }
                for o in self.options
            ]
        if self.option_selected:
            data["optionSelected"] = self.option_selected
        if self.error_category:
            data["errorCategory"] = self.error_category
        if self.error_code:
            data["errorCode"] = self.error_code
        if self.error_severity:
            data["errorSeverity"] = self.error_severity
        return data


@dataclass
class ActionItem:
    """
    Data structure for an activity feed item.

    Represents an action or reasoning entry rendered inline in a
    session's chat (the per-session activity feed).

    Attributes:
        id: Unique identifier
        name: Display name
        status: Current status ("running", "completed", "error")
        item_type: Either "action" or "reasoning"
        session_id: The session whose stream produced this item
        created_at: Unix timestamp when created
        completed_at: Unix timestamp when completed/errored
        input_data: Input parameters/schema for the action
        output_data: Output/result of the action
        error_message: Error message if action failed
    """

    id: str
    name: str
    status: str  # "running", "completed", "error"
    item_type: str  # "action" or "reasoning"
    session_id: str = "main"
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    input_data: Optional[str] = None
    output_data: Optional[str] = None
    error_message: Optional[str] = None

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

    @property
    def duration(self) -> Optional[int]:
        """Get duration in milliseconds, or None if still running."""
        if self.completed_at is not None:
            return int((self.completed_at - self.created_at) * 1000)
        return None


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
