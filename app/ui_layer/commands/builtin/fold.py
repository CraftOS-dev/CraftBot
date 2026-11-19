"""Fold command implementation: summarizes the session's event stream now."""

from __future__ import annotations

import asyncio
from typing import List

from agent_core.core.session import MAIN_SESSION_ID

from app.ui_layer.commands.base import Command, CommandResult


class FoldCommand(Command):
    """Summarize the current session's event stream now: the fold a request
    that would not fit the context window gets, made early. The chat input's
    context menu sends this command too."""

    @property
    def name(self) -> str:
        return "/fold"

    @property
    def description(self) -> str:
        return "Summarize this session's event stream now to free context"

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
        session_id: str | None = None,
    ) -> CommandResult:
        """Start the fold of the session it was typed in."""
        target = session_id or MAIN_SESSION_ID
        if target in self._controller.agent.folding_sessions:
            return CommandResult(
                success=False, message="This session is already being folded."
            )
        # The summary is a model call: fold in the background, so the client
        # that sent the command keeps being served meanwhile.
        asyncio.create_task(self._fold(target))
        return CommandResult(success=True)

    async def _fold(self, session_id: str) -> None:
        """Fold, then report what did not fold. A fold that happened reports
        itself: the stream's own notice lands in the chat."""
        try:
            freed = await self._controller.agent.fold_session(session_id)
        except Exception as e:
            self.emit_message(
                f"Folding the event stream failed: {e}", "error", session_id=session_id
            )
            return
        if freed is None:
            self.emit_message(
                "This session is already being folded.", "error", session_id=session_id
            )
        elif freed == 0:
            self.emit_message(
                "Nothing to fold yet: recent events always stay in full.",
                "system",
                session_id=session_id,
            )
