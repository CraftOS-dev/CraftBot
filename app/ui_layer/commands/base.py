"""Base command class and result type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from app.ui_layer.controller.ui_controller import UIController
    from agent_core.core.errors import ErrorInfoLike


@dataclass
class CommandResult:
    """
    Result of command execution.

    Attributes:
        success: Whether the command executed successfully
        message: Optional message to display to the user
        data: Optional additional data from the command
        info: Optional classified error (category/code/severity) when
            `success` is False. `message` stays populated independently —
            existing consumers that only read `.message` (the COMMAND_ERROR
            event payload, the terminal renderer) are unaffected by this
            field's presence or absence. Use `CommandResult.failure()` to
            build both from one `ErrorInfo` at once.
    """

    success: bool
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = field(default_factory=dict)
    info: Optional["ErrorInfoLike"] = None

    @classmethod
    def failure(cls, info: "ErrorInfoLike", **data: Any) -> "CommandResult":
        """Build a failed `CommandResult` from a classified error.

        `data` is passed straight through as the result's `data` dict, same
        as constructing `CommandResult(success=False, ...)` by hand.
        """
        return cls(success=False, message=info.message, info=info, data=data or {})


class Command(ABC):
    """
    Base class for all commands.

    Commands handle user input that starts with a slash (e.g., /help, /exit).
    Each command must define a name, description, and execute method.

    Example:
        class MyCommand(Command):
            @property
            def name(self) -> str:
                return "/mycommand"

            @property
            def description(self) -> str:
                return "Does something useful"

            async def execute(self, args: List[str], adapter_id: str = "") -> CommandResult:
                # Do something
                return CommandResult(success=True, message="Done!")
    """

    def __init__(self, controller: "UIController") -> None:
        """
        Initialize the command.

        Args:
            controller: The UI controller instance
        """
        self._controller = controller

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Command name including slash (e.g., '/help').

        This is the primary way users invoke the command.
        """
        pass

    @property
    def aliases(self) -> List[str]:
        """
        Alternative names for this command.

        Override this to provide alternate ways to invoke the command.
        """
        return []

    @property
    @abstractmethod
    def description(self) -> str:
        """
        Short description for help text.

        Should be a single line explaining what the command does.
        """
        pass

    @property
    def help_text(self) -> str:
        """
        Detailed help text.

        Override this to provide more detailed usage information.
        """
        return self.description

    @property
    def usage(self) -> str:
        """
        Usage syntax (e.g., '/command <arg1> [arg2]').

        Override this to show argument syntax.
        """
        return self.name

    @property
    def hidden(self) -> bool:
        """
        Whether to hide this command from help listings.

        Override and return True for internal/debug commands.
        """
        return False

    @abstractmethod
    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
        session_id: str | None = None,
    ) -> CommandResult:
        """
        Execute the command with given arguments.

        Args:
            args: Command arguments (everything after the command name)
            adapter_id: ID of the adapter that invoked this command

        Returns:
            CommandResult indicating success/failure and any message
        """
        pass

    def parse_args(self, message: str) -> Tuple[str, List[str]]:
        """
        Parse command and arguments from a message.

        Args:
            message: The full user input (e.g., "/help mcp")

        Returns:
            Tuple of (command_name, [args])
        """
        parts = message.split()
        command = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []
        return command, args

    def emit_message(
        self,
        message: str,
        event_type: str = "system",
        session_id: str | None = None,
    ) -> None:
        """
        Emit a message to the UI.

        Helper method for commands to send messages to the user.

        Args:
            message: The message to display
            event_type: Type of message (system, info, error)
            session_id: The session the message belongs to (routes the message
                to the session the command was typed in; main when omitted).
        """
        from app.ui_layer.events import UIEvent, UIEventType

        type_map = {
            "system": UIEventType.SYSTEM_MESSAGE,
            "info": UIEventType.INFO_MESSAGE,
            "error": UIEventType.ERROR_MESSAGE,
        }

        self._controller.event_bus.emit(
            UIEvent(
                type=type_map.get(event_type, UIEventType.SYSTEM_MESSAGE),
                data={"message": message},
                task_id=session_id,
            )
        )
