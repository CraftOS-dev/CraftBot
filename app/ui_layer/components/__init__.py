"""Component protocols and types for UI layer."""

from app.ui_layer.components.types import ChatMessage, ActionItem
from app.ui_layer.components.protocols import (
    ChatComponentProtocol,
    ActionPanelProtocol,
    StatusBarProtocol,
    InputComponentProtocol,
    FootageComponentProtocol,
)

__all__ = [
    "ChatMessage",
    "ActionItem",
    "ChatComponentProtocol",
    "ActionPanelProtocol",
    "StatusBarProtocol",
    "InputComponentProtocol",
    "FootageComponentProtocol",
]
