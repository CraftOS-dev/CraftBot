"""Reset command implementation."""

from __future__ import annotations

import asyncio
from typing import List

from app.ui_layer.commands.base import Command, CommandResult


class ResetCommand(Command):
    """Reset the agent state."""

    @property
    def name(self) -> str:
        return "/reset"

    @property
    def description(self) -> str:
        return "Reset agent state and clear history"

    @property
    def help_text(self) -> str:
        return """Reset the agent to its initial state.

This will:
- Delete all chat sessions and clear the main session
- Clear action history
- Reset the conversation context

Note: This does not affect saved settings or credentials."""

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
        session_id: str | None = None,
    ) -> CommandResult:
        """Execute the reset command."""
        # Show immediate feedback, then perform reset in background
        self.emit_message("Resetting agent state...", "system", session_id=session_id)

        asyncio.create_task(self._perform_reset(session_id))

        return CommandResult(success=True)

    async def _perform_reset(self, session_id: str | None = None) -> None:
        """Perform the actual reset in the background."""
        try:
            # Reset UI state
            self._controller.state_store.reset()

            # Reset agent state
            await self._controller.agent.reset_agent_state()

            # Clear chat and action panel in the UI
            adapter = self._controller.active_adapter
            if adapter:
                await adapter.chat_component.clear()
                if adapter.action_panel:
                    await adapter.action_panel.clear()

            self.emit_message(
                "Agent state has been reset.", "system", session_id=session_id
            )
        except Exception as e:
            self.emit_message(
                f"Failed to reset agent state: {e}", "error", session_id=session_id
            )
