# -*- coding: utf-8 -*-
"""
app.external_comms.base

Base classes for platform clients.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


@dataclass
class PlatformMessage:
    """Standardized incoming message from any platform."""
    platform: str               # e.g. "telegram", "slack", "discord"
    sender_id: str              # Platform-specific sender/chat ID
    sender_name: str = ""       # Human-readable name
    text: str = ""              # Message text
    channel_id: str = ""        # Channel/conversation/group ID (if applicable)
    channel_name: str = ""      # Human-readable channel name
    message_id: str = ""        # Platform-specific message ID
    timestamp: Optional[datetime] = None
    raw: Dict[str, Any] = field(default_factory=dict)  # Original platform payload


# Callback type for incoming messages
MessageCallback = Callable[[PlatformMessage], Coroutine[Any, Any, None]]


class BasePlatformClient(ABC):
    """
    Abstract base class for all platform clients.

    Each platform implements this with its own credential loading,
    API calls, and optional listening/polling support.
    """

    PLATFORM_ID: str = ""  # Override in subclasses: "slack", "telegram_bot", etc.

    def __init__(self):
        self._connected = False
        self._listening = False
        self._message_callback: Optional[MessageCallback] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_listening(self) -> bool:
        return self._listening

    @abstractmethod
    def has_credentials(self) -> bool:
        """Check if credentials are available for this platform."""
        ...

    @abstractmethod
    async def connect(self) -> None:
        """Initialize the client and verify credentials work."""
        ...

    async def disconnect(self) -> None:
        """Clean up resources."""
        if self._listening:
            await self.stop_listening()
        self._connected = False

    @abstractmethod
    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """
        Send a message on this platform.

        Args:
            recipient: Platform-specific recipient ID (chat ID, channel ID, etc.)
            text: Message text to send.

        Returns:
            Dict with at least {"ok": True/False} and platform-specific details.
        """
        ...

    # --- Optional listening support (for platforms with incoming messages) ---

    @property
    def supports_listening(self) -> bool:
        """Whether this client supports receiving messages (polling/websocket)."""
        return False

    async def start_listening(self, callback: MessageCallback) -> None:
        """Start receiving messages. Override in platforms that support it."""
        raise NotImplementedError(f"{self.PLATFORM_ID} does not support listening")

    async def stop_listening(self) -> None:
        """Stop receiving messages. Override in platforms that support it."""
        self._listening = False
