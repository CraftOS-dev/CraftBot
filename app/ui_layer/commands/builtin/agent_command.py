"""Wrapper for agent-provided commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from app.ui_layer.commands.base import Command, CommandResult

if TYPE_CHECKING:
    from app.agent_base import AgentCommand


class AgentCommandWrapper(Command):
    """
    Wrapper for commands provided by the agent.

    This allows the agent to register custom commands that are handled
    by the UI layer's command system.
    """

    def __init__(
        self,
        controller,
        cmd_name: str,
        cmd_info: "AgentCommand",
    ) -> None:
        """
        Initialize the agent command wrapper.

        Args:
            controller: The UI controller instance
            cmd_name: The command name (without slash)
            cmd_info: AgentCommand dataclass with description and handler
        """
        super().__init__(controller)
        self._cmd_name = cmd_name
        self._cmd_info = cmd_info
        self._handler = cmd_info.handler

    @property
    def name(self) -> str:
        return f"/{self._cmd_name}"

    @property
    def description(self) -> str:
        return self._cmd_info.description

    @property
    def help_text(self) -> str:
        return self._cmd_info.description

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
    ) -> CommandResult:
        """Execute the agent command."""
        if not self._handler:
            return CommandResult(
                success=False,
                message=f"Command handler not available: {self._cmd_name}",
            )

        try:
            # Call the handler
            result = await self._handler(args)

            # Handle different result types
            if isinstance(result, str):
                return CommandResult(success=True, message=result)
            elif isinstance(result, dict):
                return CommandResult(
                    success=result.get("success", True),
                    message=result.get("message", ""),
                    data=result.get("data"),
                )
            else:
                return CommandResult(success=True)

        except Exception as e:
            return CommandResult(
                success=False,
                message=f"Command error: {e}",
            )
