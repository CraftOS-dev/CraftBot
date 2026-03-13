"""CLI interface adapter implementation."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, List, Optional

from app.ui_layer.adapters.base import InterfaceAdapter
from app.ui_layer.themes.base import ThemeAdapter, StyleType
from app.ui_layer.themes.theme import BaseTheme, CRAFTBOT_LOGO
from app.ui_layer.components.protocols import ChatComponentProtocol
from app.ui_layer.components.types import ChatMessage
from app.ui_layer.events import UIEvent, UIEventType
from app.ui_layer.onboarding import OnboardingFlowController

if TYPE_CHECKING:
    from app.ui_layer.controller.ui_controller import UIController


# Lazy import to avoid circular dependency with app.cli
_formatter = None


def _get_formatter():
    """Lazy import of CLIFormatter to avoid circular imports."""
    global _formatter
    if _formatter is None:
        from app.cli.formatter import CLIFormatter
        _formatter = CLIFormatter
    return _formatter


class CLIThemeAdapter(ThemeAdapter):
    """CLI-specific theme adapter using ANSI colors via CLIFormatter."""

    def __init__(self, theme: BaseTheme) -> None:
        super().__init__(theme)
        _get_formatter().init()

    def format_text(self, text: str, style_type: StyleType) -> str:
        """Format text with ANSI codes using CLIFormatter."""
        style_map = {
            StyleType.USER: "user",
            StyleType.AGENT: "agent",
            StyleType.SYSTEM: "system",
            StyleType.ERROR: "error",
            StyleType.INFO: "info",
            StyleType.SUCCESS: "success",
            StyleType.TASK: "task",
            StyleType.ACTION: "action",
        }
        style = style_map.get(style_type, "info")
        return _get_formatter().format_chat("", text, style).lstrip(": ")

    def format_chat_message(
        self,
        label: str,
        message: str,
        style_type: StyleType,
    ) -> str:
        """Format a chat message for CLI output."""
        style_map = {
            StyleType.USER: "user",
            StyleType.AGENT: "agent",
            StyleType.SYSTEM: "system",
            StyleType.ERROR: "error",
            StyleType.INFO: "info",
        }
        style = style_map.get(style_type, "system")
        return _get_formatter().format_chat(label, message, style)

    def format_action_item(
        self,
        name: str,
        status: str,
        is_task: bool,
        indent: int = 0,
    ) -> str:
        """Format an action panel item."""
        fmt = _get_formatter()
        if is_task:
            if status == "running":
                return fmt.format_task_start(name)
            else:
                success = status == "completed"
                return fmt.format_task_end(name, success)
        else:
            if status == "running":
                return fmt.format_action_start(name, is_sub_action=indent > 0)
            else:
                success = status == "completed"
                return fmt.format_action_end(name, success, is_sub_action=indent > 0)


class CLIChatComponent(ChatComponentProtocol):
    """CLI chat component using print statements."""

    def __init__(self, theme_adapter: CLIThemeAdapter) -> None:
        self._theme = theme_adapter
        self._messages: List[ChatMessage] = []
        self._last_output_type: str = "none"

    async def append_message(self, message: ChatMessage) -> None:
        """Append and print a message."""
        self._messages.append(message)

        # Map style to StyleType
        style_map = {
            "user": StyleType.USER,
            "agent": StyleType.AGENT,
            "system": StyleType.SYSTEM,
            "error": StyleType.ERROR,
            "info": StyleType.INFO,
        }
        style_type = style_map.get(message.style, StyleType.SYSTEM)

        # Add blank line between different message types for readability
        current_type = "chat" if message.style in ("user", "agent") else message.style
        if self._last_output_type != "none" and self._last_output_type != current_type:
            print()

        # Format and print
        formatted = self._theme.format_chat_message(
            message.sender, message.content, style_type
        )
        print(formatted)

        self._last_output_type = current_type

    async def clear(self) -> None:
        """Clear the console."""
        self._messages.clear()
        self._last_output_type = "none"
        _get_formatter().clear_screen()

    def scroll_to_bottom(self) -> None:
        """No-op for CLI."""
        pass

    def get_messages(self) -> List[ChatMessage]:
        """Get all messages."""
        return self._messages.copy()

    def reset_output_type(self) -> None:
        """Reset the output type tracker (used when printing non-chat output)."""
        self._last_output_type = "other"

    def ensure_blank_line(self) -> None:
        """Ensure a blank line before next output."""
        if self._last_output_type != "blank":
            print()
            self._last_output_type = "blank"


class CLIAdapter(InterfaceAdapter):
    """
    CLI interface adapter.

    Provides a simple command-line interface using print/input.
    """

    def __init__(self, controller: "UIController") -> None:
        super().__init__(controller, "cli")
        self._theme_adapter = CLIThemeAdapter(BaseTheme())
        self._chat = CLIChatComponent(self._theme_adapter)
        self._current_task_name: Optional[str] = None

    @property
    def theme_adapter(self) -> ThemeAdapter:
        return self._theme_adapter

    @property
    def chat_component(self) -> ChatComponentProtocol:
        return self._chat

    async def _on_start(self) -> None:
        """Start the CLI interface."""
        # Check for onboarding
        onboarding = OnboardingFlowController(self._controller)
        if onboarding.needs_hard_onboarding:
            await self._run_hard_onboarding(onboarding)

        # Print logo and welcome
        _get_formatter().print_logo()
        print("Type /help for commands, /exit to quit.\n")

        # Emit ready event
        self._controller.event_bus.emit(
            UIEvent(
                type=UIEventType.INTERFACE_READY,
                data={"adapter": "cli"},
                source_adapter=self._adapter_id,
            )
        )

        # Start input loop
        await self._input_loop()

    async def _on_stop(self) -> None:
        """Stop the CLI interface."""
        pass

    async def _input_loop(self) -> None:
        """Main input loop."""
        loop = asyncio.get_event_loop()

        while self._running and self._controller.agent.is_running:
            try:
                # Read input in executor to avoid blocking
                user_input = await loop.run_in_executor(None, self._read_input)

                if user_input is None:
                    # EOF - exit gracefully
                    break

                if user_input.strip():
                    # Clear the echoed input line for cleaner display
                    _get_formatter().clear_previous_line()
                    await self.submit_message(user_input)

            except (KeyboardInterrupt, EOFError):
                break
            except Exception:
                # Log but don't crash
                pass

    def _read_input(self) -> Optional[str]:
        """Read input from stdin."""
        try:
            return input()
        except EOFError:
            return None

    async def _run_hard_onboarding(self, onboarding: OnboardingFlowController) -> None:
        """Run the hard onboarding wizard."""
        print("\nWelcome to CraftBot! Let's set up your agent.\n")

        while not onboarding.is_complete and not onboarding.is_cancelled:
            step_info = onboarding.get_step_info()

            print(f"\n{step_info['progress']}")
            print(f"{step_info['title']}")
            print(f"{step_info['description']}\n")

            options = step_info["options"]
            if options:
                # Display options
                for i, opt in enumerate(options, 1):
                    default_marker = " (default)" if opt.default else ""
                    print(f"  {i}. {opt.label}{default_marker}")
                    if opt.description:
                        print(f"     {opt.description}")

                print()
                selection = input("Enter choice (number or value): ").strip()

                # Parse selection
                try:
                    idx = int(selection) - 1
                    if 0 <= idx < len(options):
                        value = options[idx].value
                    else:
                        print("Invalid selection.")
                        continue
                except ValueError:
                    # Treat as direct value
                    value = selection

            else:
                # Free-form input
                default = step_info["default"]
                prompt = "Enter value"
                if default:
                    prompt += f" [{default}]"
                prompt += ": "

                value = input(prompt).strip()
                if not value and default:
                    value = default

            # Submit value
            if onboarding.submit_step_value(value):
                if not onboarding.next_step():
                    print("\nSetup complete! Starting CraftBot...\n")
            else:
                print("Invalid value. Please try again.")

    # ─────────────────────────────────────────────────────────────────────
    # Override event handlers for CLI-specific behavior
    # ─────────────────────────────────────────────────────────────────────

    def _handle_system_message(self, event: UIEvent) -> None:
        """Handle system message - check for clear command."""
        message = event.data.get("message", "")
        if event.data.get("is_clear_command") or message == "__CLEAR__":
            asyncio.create_task(self._chat.clear())
        else:
            super()._handle_system_message(event)

    def _handle_task_start(self, event: UIEvent) -> None:
        """Handle task start - print task message."""
        task_name = event.data.get("task_name", "Task")
        self._current_task_name = task_name
        self._chat.ensure_blank_line()
        print(_get_formatter().format_task_start(task_name))
        self._chat.reset_output_type()

    def _handle_task_end(self, event: UIEvent) -> None:
        """Handle task end - print completion message."""
        task_name = event.data.get("task_name", "Task")
        status = event.data.get("status", "completed")
        success = status == "completed"
        self._chat.ensure_blank_line()
        print(_get_formatter().format_task_end(task_name, success))
        self._chat.reset_output_type()
        self._current_task_name = None

    def _handle_action_start(self, event: UIEvent) -> None:
        """Handle action start - print action message."""
        action_name = event.data.get("action_name", "Action")
        fmt = _get_formatter()
        # Skip hidden actions
        if fmt.is_hidden_action(action_name):
            return
        is_sub = bool(self._current_task_name)
        print(fmt.format_action_start(action_name, is_sub))
        self._chat.reset_output_type()

    def _handle_action_end(self, event: UIEvent) -> None:
        """Handle action end - print completion message."""
        action_name = event.data.get("action_name", "Action")
        fmt = _get_formatter()
        # Skip hidden actions
        if fmt.is_hidden_action(action_name):
            return
        success = not event.data.get("error")
        is_sub = bool(self._current_task_name)
        print(fmt.format_action_end(action_name, success, is_sub))
        self._chat.reset_output_type()
