"""Clear command implementation."""

from __future__ import annotations

from typing import List

from app.ui_layer.commands.base import Command, CommandResult
from app.ui_layer.events import UIEvent, UIEventType


class ClearCommand(Command):
    """Clear the screen/chat log."""

    @property
    def name(self) -> str:
        return "/clear"

    @property
    def aliases(self) -> List[str]:
        return ["/cls"]

    @property
    def description(self) -> str:
        return "Clear the chat and action log"

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
    ) -> CommandResult:
        """Execute the clear command."""
        # Clear action items state
        self._controller.state_store.dispatch("CLEAR_ACTION_ITEMS", None)

        # Emit event for adapters to clear their displays
        self._controller.event_bus.emit(
            UIEvent(
                type=UIEventType.SYSTEM_MESSAGE,
                data={"message": "__CLEAR__", "is_clear_command": True},
                source_adapter=adapter_id,
            )
        )

        return CommandResult(success=True)
