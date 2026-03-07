"""Help command implementation."""

from __future__ import annotations

from typing import List

from app.ui_layer.commands.base import Command, CommandResult


class HelpCommand(Command):
    """Display help information about available commands."""

    @property
    def name(self) -> str:
        return "/help"

    @property
    def aliases(self) -> List[str]:
        return ["/h", "/?"]

    @property
    def description(self) -> str:
        return "Show available commands"

    @property
    def usage(self) -> str:
        return "/help [command]"

    @property
    def help_text(self) -> str:
        return """Show help information about available commands.

Usage:
  /help           - List all available commands
  /help <command> - Show detailed help for a specific command

Examples:
  /help
  /help mcp
  /help skill"""

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
    ) -> CommandResult:
        """Execute the help command."""
        if args:
            # Show help for specific command
            cmd_name = args[0].lower()
            if not cmd_name.startswith("/"):
                cmd_name = "/" + cmd_name

            cmd = self._controller.command_registry.get(cmd_name)
            if cmd:
                help_text = f"{cmd.name} - {cmd.description}\n\n"
                help_text += f"Usage: {cmd.usage}\n\n"
                help_text += cmd.help_text
                return CommandResult(success=True, message=help_text)
            else:
                return CommandResult(
                    success=False,
                    message=f"Unknown command: {cmd_name}",
                )

        # Show all commands
        help_text = self._controller.command_registry.get_help_text()
        return CommandResult(success=True, message=help_text)
