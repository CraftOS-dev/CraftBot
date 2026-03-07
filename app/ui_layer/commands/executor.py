"""Command executor for parsing and executing commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.ui_layer.commands.base import CommandResult
from app.ui_layer.commands.registry import CommandRegistry
from app.ui_layer.events import UIEvent, UIEventType

if TYPE_CHECKING:
    from app.ui_layer.controller.ui_controller import UIController


class CommandExecutor:
    """
    Executes commands from the registry.

    Handles parsing user input, looking up commands, executing them,
    and emitting appropriate events for the results.

    Example:
        executor = CommandExecutor(registry, controller)

        # Try to execute a command
        was_command = await executor.try_execute("/help mcp", "cli")
        if was_command:
            print("Command was executed")
        else:
            print("Not a command, handle as regular message")
    """

    def __init__(
        self,
        registry: CommandRegistry,
        controller: "UIController",
    ) -> None:
        """
        Initialize the command executor.

        Args:
            registry: The command registry to use
            controller: The UI controller instance
        """
        self._registry = registry
        self._controller = controller

    async def try_execute(
        self,
        message: str,
        adapter_id: str = "",
    ) -> bool:
        """
        Try to execute a command from a message.

        If the message starts with '/', attempts to find and execute
        the corresponding command. Emits appropriate events for the result.

        Args:
            message: The user's input message
            adapter_id: ID of the adapter that sent the message

        Returns:
            True if a command was executed (even if it failed),
            False if the message is not a command
        """
        if not message.startswith("/"):
            return False

        parts = message.split()
        command_name = parts[0].lower()
        args = parts[1:]

        command = self._registry.get(command_name)

        if not command:
            # Unknown command - emit error
            self._controller.event_bus.emit(
                UIEvent(
                    type=UIEventType.ERROR_MESSAGE,
                    data={
                        "message": f"Unknown command: {command_name}. Use /help for available commands.",
                    },
                    source_adapter=adapter_id,
                )
            )
            return True

        # Execute the command
        try:
            result = await command.execute(args, adapter_id)
        except Exception as e:
            result = CommandResult(
                success=False,
                message=f"Command error: {str(e)}",
            )

        # Emit result event
        event_type = (
            UIEventType.COMMAND_EXECUTED if result.success else UIEventType.COMMAND_ERROR
        )
        self._controller.event_bus.emit(
            UIEvent(
                type=event_type,
                data={
                    "command": command_name,
                    "args": args,
                    "result": {
                        "success": result.success,
                        "message": result.message,
                        "data": result.data,
                    },
                },
                source_adapter=adapter_id,
            )
        )

        # If there's a message, emit it as a system message
        if result.message:
            msg_type = UIEventType.SYSTEM_MESSAGE if result.success else UIEventType.ERROR_MESSAGE
            self._controller.event_bus.emit(
                UIEvent(
                    type=msg_type,
                    data={"message": result.message},
                    source_adapter=adapter_id,
                )
            )

        return True

    def is_command(self, message: str) -> bool:
        """
        Check if a message is a command.

        Args:
            message: The message to check

        Returns:
            True if the message starts with '/' and matches a known command
        """
        if not message.startswith("/"):
            return False

        parts = message.split()
        command_name = parts[0].lower()
        return self._registry.has(command_name)
