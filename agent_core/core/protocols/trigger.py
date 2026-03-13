# -*- coding: utf-8 -*-
"""
Protocol definition for TriggerQueue.
"""
from __future__ import annotations

from typing import List, Protocol, Optional, runtime_checkable

from agent_core.core.trigger import Trigger


@runtime_checkable
class TriggerQueueProtocol(Protocol):
    """Protocol for trigger queue implementations."""

    async def put(self, trig: Trigger, skip_merge: bool = False) -> None:
        """Insert a trigger into the queue."""
        ...

    async def get(self) -> Trigger:
        """Retrieve the next trigger to execute."""
        ...

    async def size(self) -> int:
        """Count how many triggers are currently queued."""
        ...

    async def list_triggers(self) -> List[Trigger]:
        """List the triggers currently in the queue."""
        ...

    async def fire(self, session_id: str, *, message: Optional[str] = None) -> bool:
        """Mark a trigger for a given session as ready to fire immediately."""
        ...

    async def remove_sessions(self, session_ids: List[str]) -> None:
        """Remove all triggers that belong to the provided session identifiers."""
        ...

    async def clear(self) -> None:
        """Remove all pending triggers from the queue."""
        ...

    def create_event_stream_state(self) -> str:
        """Return formatted event stream content."""
        ...

    def create_task_state(self) -> str:
        """Return formatted task/plan context."""
        ...
