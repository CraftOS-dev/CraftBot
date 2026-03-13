"""Integration-specific command implementation."""

from __future__ import annotations

from typing import List

from app.ui_layer.commands.base import Command, CommandResult
from app.credentials.handlers import INTEGRATION_HANDLERS


class IntegrationCommand(Command):
    """Command for a specific integration."""

    def __init__(self, controller, integration_name: str) -> None:
        """
        Initialize the integration command.

        Args:
            controller: The UI controller instance
            integration_name: Name of the integration (e.g., "google", "slack")
        """
        super().__init__(controller)
        self._integration_name = integration_name
        self._handler = INTEGRATION_HANDLERS.get(integration_name)

    @property
    def name(self) -> str:
        return f"/{self._integration_name}"

    @property
    def description(self) -> str:
        if self._handler and hasattr(self._handler, "description"):
            return self._handler.description
        return f"Manage {self._integration_name} integration"

    @property
    def usage(self) -> str:
        return f"/{self._integration_name} <subcommand>"

    @property
    def help_text(self) -> str:
        lines = [f"Manage {self._integration_name} integration.", ""]

        if self._handler:
            # Get available commands from handler
            if hasattr(self._handler, "get_commands"):
                commands = self._handler.get_commands()
                if commands:
                    lines.append("Commands:")
                    for cmd_name, cmd_desc in commands.items():
                        lines.append(f"  {cmd_name} - {cmd_desc}")
                    lines.append("")

        lines.append("Common commands:")
        lines.append("  connect    - Connect to integration")
        lines.append("  disconnect - Disconnect from integration")
        lines.append("  status     - Show connection status")

        return "\n".join(lines)

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
    ) -> CommandResult:
        """Execute the integration command."""
        if not self._handler:
            return CommandResult(
                success=False,
                message=f"Integration not available: {self._integration_name}",
            )

        if not args:
            return await self._show_status()

        subcommand = args[0].lower()
        sub_args = args[1:]

        # Handle common commands
        if subcommand == "status":
            return await self._show_status()
        elif subcommand == "connect":
            return await self._connect(sub_args)
        elif subcommand == "disconnect":
            return await self._disconnect()

        # Try handler-specific command
        if hasattr(self._handler, "handle_command"):
            try:
                result = await self._handler.handle_command(subcommand, sub_args)
                if result:
                    return CommandResult(
                        success=result.get("success", False),
                        message=result.get("message", ""),
                    )
            except Exception as e:
                return CommandResult(
                    success=False,
                    message=f"Command error: {e}",
                )

        return CommandResult(
            success=False,
            message=f"Unknown command: {subcommand}\nUse /help {self._integration_name} for usage.",
        )

    async def _show_status(self) -> CommandResult:
        """Show integration status."""
        try:
            if hasattr(self._handler, "get_status"):
                status = self._handler.get_status()
                connected = status.get("connected", False)

                lines = [f"{self._integration_name.title()} integration status:", ""]
                lines.append(f"  Connected: {'Yes' if connected else 'No'}")

                if connected:
                    account = status.get("account", "")
                    if account:
                        lines.append(f"  Account: {account}")

                return CommandResult(success=True, message="\n".join(lines))
            else:
                return CommandResult(
                    success=True,
                    message=f"{self._integration_name}: Status not available",
                )
        except Exception as e:
            return CommandResult(
                success=False,
                message=f"Failed to get status: {e}",
            )

    async def _connect(self, args: List[str]) -> CommandResult:
        """Connect to the integration."""
        try:
            if hasattr(self._handler, "connect"):
                result = await self._handler.connect(*args)
                return CommandResult(
                    success=result.get("success", False),
                    message=result.get("message", "Connected successfully" if result.get("success") else "Connection failed"),
                )
            else:
                return CommandResult(
                    success=False,
                    message=f"{self._integration_name}: Connect not supported",
                )
        except Exception as e:
            return CommandResult(
                success=False,
                message=f"Connection failed: {e}",
            )

    async def _disconnect(self) -> CommandResult:
        """Disconnect from the integration."""
        try:
            if hasattr(self._handler, "disconnect"):
                result = await self._handler.disconnect()
                return CommandResult(
                    success=result.get("success", False),
                    message=result.get("message", "Disconnected successfully" if result.get("success") else "Disconnect failed"),
                )
            else:
                return CommandResult(
                    success=False,
                    message=f"{self._integration_name}: Disconnect not supported",
                )
        except Exception as e:
            return CommandResult(
                success=False,
                message=f"Disconnect failed: {e}",
            )
