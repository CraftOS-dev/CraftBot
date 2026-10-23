"""Clear command implementation: starts the current session over."""

from __future__ import annotations

from typing import List

from agent_core.core.session import MAIN_SESSION_ID

from app.ui_layer.commands.base import Command, CommandResult


class ClearCommand(Command):
    """Start the current session over: its conversation and the agent's
    context of it are cleared, and it continues as a new session."""

    @property
    def name(self) -> str:
        return "/clear"

    @property
    def aliases(self) -> List[str]:
        return ["/cls"]

    @property
    def description(self) -> str:
        return "Clear this session's conversation and context (starts it over)"

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

        # Start the session over on the agent side (stops a run in flight,
        # resets its context and files). First, so the stopped run's last
        # rows are cleared with the rest of the conversation.
        if not await self._controller.agent.clear_session(target):
            return CommandResult(success=False, message="Session could not be cleared.")
        await self._controller.event_bus.drain(target)

        # Clear persisted chat + activity rows for this session
        from app.usage import get_action_storage, get_chat_storage

        adapter = self._controller.active_adapter
        if adapter:
            # Use the adapter's ordered worker so an insert already in flight
            # cannot land after the delete and restore the old conversation.
            await adapter.chat_component.clear(target)
        else:
            get_chat_storage().clear_messages(target)
        get_action_storage().clear_items(target)

        # Tell the UI to drop the session's rendered conversation. Always
        # session-scoped: a /clear must never touch other sessions.
        broadcast = getattr(adapter, "broadcast_session_cleared", None)
        if broadcast is not None:
            await broadcast(target)

        # Confirm in the now-empty conversation (emitted after the clear so
        # it survives instead of being wiped with the old rows).
        self.emit_message("Conversation cleared.", "system", session_id=target)

        return CommandResult(success=True)
