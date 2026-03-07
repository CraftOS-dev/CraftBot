"""Command registry for managing available commands."""

from __future__ import annotations

from typing import Dict, List, Optional

from app.ui_layer.commands.base import Command


class CommandRegistry:
    """
    Central registry for all commands.

    Commands are registered by name and can have aliases. The registry
    provides methods to look up commands, list all commands, and generate
    help text.

    Example:
        registry = CommandRegistry()
        registry.register(HelpCommand(controller))
        registry.register(ExitCommand(controller))

        # Look up command
        cmd = registry.get("/help")
        if cmd:
            result = await cmd.execute([], "")

        # Get all commands
        commands = registry.list_commands()
    """

    def __init__(self) -> None:
        """Initialize an empty command registry."""
        self._commands: Dict[str, Command] = {}
        self._aliases: Dict[str, str] = {}

    def register(self, command: Command) -> None:
        """
        Register a command.

        Args:
            command: The command instance to register
        """
        name_lower = command.name.lower()
        self._commands[name_lower] = command

        # Register aliases
        for alias in command.aliases:
            self._aliases[alias.lower()] = name_lower

    def unregister(self, name: str) -> None:
        """
        Unregister a command.

        Args:
            name: The command name to unregister
        """
        name_lower = name.lower()
        if name_lower in self._commands:
            cmd = self._commands.pop(name_lower)
            # Remove aliases
            for alias in cmd.aliases:
                self._aliases.pop(alias.lower(), None)

    def get(self, name: str) -> Optional[Command]:
        """
        Get a command by name or alias.

        Args:
            name: The command name or alias

        Returns:
            The command instance, or None if not found
        """
        name_lower = name.lower()

        # Check direct name
        if name_lower in self._commands:
            return self._commands[name_lower]

        # Check aliases
        if name_lower in self._aliases:
            return self._commands[self._aliases[name_lower]]

        return None

    def has(self, name: str) -> bool:
        """
        Check if a command exists.

        Args:
            name: The command name or alias

        Returns:
            True if the command exists
        """
        return self.get(name) is not None

    def list_commands(self, include_hidden: bool = False) -> List[Command]:
        """
        List all registered commands.

        Args:
            include_hidden: Whether to include hidden commands

        Returns:
            List of command instances
        """
        commands = list(self._commands.values())
        if not include_hidden:
            commands = [c for c in commands if not c.hidden]
        return commands

    def get_help_text(self, include_hidden: bool = False) -> str:
        """
        Generate help text for all commands.

        Args:
            include_hidden: Whether to include hidden commands

        Returns:
            Formatted help text string
        """
        lines = ["Available commands:", ""]

        commands = sorted(
            self.list_commands(include_hidden=include_hidden),
            key=lambda c: c.name,
        )

        for cmd in commands:
            aliases = f" (aliases: {', '.join(cmd.aliases)})" if cmd.aliases else ""
            lines.append(f"  {cmd.name}  - {cmd.description}{aliases}")

        return "\n".join(lines)

    def get_command_names(self) -> List[str]:
        """
        Get all command names (not aliases).

        Returns:
            List of command names
        """
        return list(self._commands.keys())
