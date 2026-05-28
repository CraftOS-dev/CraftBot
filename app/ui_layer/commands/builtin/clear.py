"""Clear command implementation."""

from __future__ import annotations

from typing import List

from app.ui_layer.commands.base import Command, CommandResult


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

        # Clear chat and action panel via the active adapter's components
        adapter = self._controller.active_adapter
        if adapter:
            await adapter.chat_component.clear()
            if adapter.action_panel:
                await adapter.action_panel.clear()

        # Drop the agent's persisted conversation memory so a restart does
        # not resurrect cleared chat from session_storage.
        await self._controller.agent.clear_conversation_persistence()

        return CommandResult(success=True)
