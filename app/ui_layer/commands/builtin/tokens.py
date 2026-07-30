"""Tokens command implementation — shows this session's token usage."""

from __future__ import annotations

from typing import List

from agent_core.core.session import MAIN_SESSION_ID

from app.ui_layer.commands.base import Command, CommandResult


class TokensCommand(Command):
    """Show cumulative token usage for the session it was typed in."""

    @property
    def name(self) -> str:
        return "/tokens"

    @property
    def description(self) -> str:
        return "Show this session's token usage"

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
        session_id: str | None = None,
    ) -> CommandResult:
        """Report this session's token totals as a chat message."""
        target = session_id or MAIN_SESSION_ID
        # Sessions are created lazily on first message, so a brand-new chat
        # has no session object yet — that reads as zero usage, not an error.
        session = self._controller.agent.session_manager.get(target)

        # Providers report input as the full prompt, cache reads included, so
        # `cached` is a subset of `total_input_tokens` — never a sibling.
        cached = getattr(session, "total_cache_tokens", 0) or 0
        new_input = max(0, (getattr(session, "total_input_tokens", 0) or 0) - cached)
        output = getattr(session, "total_output_tokens", 0) or 0
        total = new_input + output

        message = (
            "Session token usage\n"
            f"  Input:  {new_input:,}\n"
            f"  Cached: {cached:,}\n"
            f"  Output: {output:,}\n"
            f"  Total:  {total:,}"
        )
        return CommandResult(
            success=True,
            message=message,
            data={
                "session_id": target,
                "input": new_input,
                "cached": cached,
                "output": output,
                "total": total,
            },
        )
