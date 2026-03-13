"""Reset command implementation."""

from __future__ import annotations

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
- Clear the current task
- Clear action history
- Reset the conversation context

Note: This does not affect saved settings or credentials."""

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
    ) -> CommandResult:
        """Execute the reset command."""
        # Reset UI state
        self._controller.state_store.reset()

        # Reset agent state
        await self._controller.agent.reset_agent_state()

        return CommandResult(
            success=True,
            message="Agent state has been reset.",
        )
