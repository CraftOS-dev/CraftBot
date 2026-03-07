"""Exit command implementation."""

from __future__ import annotations

from typing import List

from app.ui_layer.commands.base import Command, CommandResult
from app.ui_layer.events import UIEvent, UIEventType


class ExitCommand(Command):
    """Exit the application."""

    @property
    def name(self) -> str:
        return "/exit"

    @property
    def aliases(self) -> List[str]:
        return ["/quit", "/q"]

    @property
    def description(self) -> str:
        return "Exit CraftBot"

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
    ) -> CommandResult:
        """Execute the exit command."""
        # Emit shutdown event
        self._controller.event_bus.emit(
            UIEvent(
                type=UIEventType.INTERFACE_SHUTDOWN,
                data={"reason": "user_exit"},
                source_adapter=adapter_id,
            )
        )

        # Stop the agent
        self._controller.agent.is_running = False

        return CommandResult(
            success=True,
            message="Goodbye!",
        )
