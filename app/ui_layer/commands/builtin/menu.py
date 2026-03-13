"""Menu command implementation."""

from __future__ import annotations

from typing import List

from app.ui_layer.commands.base import Command, CommandResult
from app.ui_layer.events import UIEvent, UIEventType


class MenuCommand(Command):
    """Show the main menu."""

    @property
    def name(self) -> str:
        return "/menu"

    @property
    def description(self) -> str:
        return "Show the main menu (TUI/Browser only)"

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
    ) -> CommandResult:
        """Execute the menu command."""
        # Check if we're in CLI mode
        if adapter_id == "cli":
            return CommandResult(
                success=True,
                message="Menu is not available in CLI mode. Use /help to see commands.",
            )

        # Show menu
        self._controller.state_store.dispatch("SHOW_MENU", True)

        # Emit navigation event
        self._controller.event_bus.emit(
            UIEvent(
                type=UIEventType.SHOW_MENU,
                data={},
                source_adapter=adapter_id,
            )
        )

        return CommandResult(success=True)
