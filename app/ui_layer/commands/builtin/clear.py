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

    @property
    def requires_session(self) -> bool:
        # Operates on the session it was typed in. In a draft this commits a
        # real session and navigates to it, so the "Conversation cleared."
        # note lands in a live chat instead of leaving the draft stuck.
        return True

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
        session_id: str | None = None,
    ) -> CommandResult:
        """Execute the clear command for the session it was typed in."""
        target = session_id or MAIN_SESSION_ID

        # Clear persisted chat + activity rows for this session
        from app.usage import get_action_storage, get_chat_storage

        get_chat_storage().clear_messages(target)
        get_action_storage().clear_items(target)

        # Clear the agent-side session state (event stream, todos, budgets)
        await self._controller.agent.clear_session(target)

        # Tell the UI to drop the session's rendered conversation. Always
        # session-scoped: a /clear must never touch other sessions.
        adapter = self._controller.active_adapter
        broadcast = getattr(adapter, "broadcast_session_cleared", None)
        if broadcast is not None:
            await broadcast(target)
        elif adapter:
            await adapter.chat_component.clear(target)

        # Confirm in the now-empty conversation (emitted after the clear so
        # it survives instead of being wiped with the old rows).
        self.emit_message("Conversation cleared.", "system", session_id=target)

        return CommandResult(success=True)
