"""Clear command implementation — clears the current session's conversation."""

from __future__ import annotations

from typing import List

from agent_core.core.session import MAIN_SESSION_ID

from app.ui_layer.commands.base import Command, CommandResult


class ClearCommand(Command):
    """Clear the current session's conversation."""

    @property
    def name(self) -> str:
        return "/clear"

    @property
    def aliases(self) -> List[str]:
        return ["/cls"]

    @property
    def description(self) -> str:
        return "Clear this session's conversation"

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
        session_id: str | None = None,
    ) -> CommandResult:
        """Execute the clear command for the session it was typed in."""
        target = session_id or MAIN_SESSION_ID

        # Clear persisted chat rows for this session
        from app.usage import get_chat_storage

        get_chat_storage().clear_messages(target)

        # Clear the agent-side session state (event stream, todos, budgets)
        await self._controller.agent.clear_session(target)

        # Tell the UI to drop the session's rendered conversation
        adapter = self._controller.active_adapter
        broadcast = getattr(adapter, "broadcast_session_cleared", None)
        if broadcast is not None:
            await broadcast(target)
        elif adapter:
            await adapter.chat_component.clear()

        return CommandResult(success=True)
