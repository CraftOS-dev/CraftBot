"""Base classes for integrations.

Two abstract lifecycles, intentionally separate:

  * BasePlatformClient — connect / send_message / start_listening (runtime)

Each integration declares one of each, both holding the same IntegrationSpec
(composition). The two classes do not share a base — they are collaborators.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional


# ════════════════════════════════════════════════════════════════════════
# Runtime side: PlatformMessage + BasePlatformClient
# ════════════════════════════════════════════════════════════════════════


@dataclass
class PlatformMessage:
    platform: str
    sender_id: str
    sender_name: str = ""
    text: str = ""
    channel_id: str = ""
    channel_name: str = ""
    message_id: str = ""
    timestamp: Optional[datetime] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    # Normalized non-text payloads. Each entry: {"kind": ..., and any of
    # "id", "name", "mime", "size", "url", "extra"}.
    #   kind:  photo|video|audio|voice|document|sticker|location|contact|
    #          poll|embed
    #   id:    the platform's fetch handle (file_id / attachmentId /
    #          message_id / file_key) for its download action
    #   url:   only when directly fetchable without an API call
    #   extra: small inline data for non-file kinds (lat/long, phone, …)
    # The HOST formats these into descriptor text + retrieval hints —
    # listeners only normalize (docs/plans/attachment-reception-plan.md).
    attachments: List[Dict[str, Any]] = field(default_factory=list)


MessageCallback = Callable[[PlatformMessage], Awaitable[None]]


class BasePlatformClient(ABC):
    PLATFORM_ID: str = ""

    def __init__(self) -> None:
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
    def has_credentials(self) -> bool: ...

    @abstractmethod
    async def connect(self) -> None: ...

    async def disconnect(self) -> None:
        if self._listening:
            await self.stop_listening()
        self._connected = False

    @abstractmethod
    async def send_message(
        self, recipient: str, text: str, **kwargs
    ) -> Dict[str, Any]: ...

    @property
    def supports_listening(self) -> bool:
        return False

    async def start_listening(self, callback: MessageCallback) -> None:
        raise NotImplementedError(f"{self.PLATFORM_ID} does not support listening")

    async def stop_listening(self) -> None:
        self._listening = False
