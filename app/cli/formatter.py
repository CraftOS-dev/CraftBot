# -*- coding: utf-8 -*-
"""
Output formatting utilities for CLI mode.

Provides ANSI color formatting for chat messages, tasks, and actions.
"""

import os
import sys
from typing import Optional


class CLIFormatter:
    """Format output for CLI display with ANSI colors."""

    # ASCII art logo lines (CRAFT portion is first 41 chars, BOT is the rest)
    LOGO_LINES = [
        (" ██████╗██████╗  █████╗ ███████╗████████╗", "██████╗  ██████╗ ████████╗"),
        ("██╔════╝██╔══██╗██╔══██╗██╔════╝╚══██╔══╝", "██╔══██╗██╔═══██╗╚══██╔══╝"),
        ("██║     ██████╔╝███████║█████╗     ██║   ", "██████╔╝██║   ██║   ██║   "),
        ("██║     ██╔══██╗██╔══██║██╔══╝     ██║   ", "██╔══██╗██║   ██║   ██║   "),
        ("╚██████╗██║  ██║██║  ██║██║        ██║   ", "██████╔╝╚██████╔╝   ██║   "),
        (" ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝        ╚═╝   ", "╚═════╝  ╚═════╝    ╚═╝   "),
    ]

    # Actions to hide from output (internal actions that clutter the display)
    HIDDEN_ACTIONS = {
        "send message",
        "ignore",
        "task start",
        "task end",
    }

    # ANSI escape codes for colors
    # Using true color (24-bit) for exact color matching with TUI
    COLORS = {
        "user": "\033[1;37m",           # Bold white
        "agent": "\033[1;38;2;255;79;24m",    # Bold orange (#ff4f18)
        "task": "\033[1;38;2;255;79;24m",     # Bold orange (#ff4f18)
        "action": "\033[1;90m",         # Bold gray
        "error": "\033[1;31m",          # Bold red
        "system": "\033[1;90m",         # Bold gray
        "info": "\033[0;37m",           # Normal gray
        "success": "\033[1;32m",        # Bold green
        "reset": "\033[0m",
    }

    # Status icons (ASCII-safe for broad terminal compatibility)
    ICON_PENDING = "o"
    ICON_RUNNING = "*"
    ICON_COMPLETED = "+"
    ICON_ERROR = "x"

    _colors_enabled: bool = True

    @classmethod
    def init(cls) -> None:
        """Initialize color support, enabling colorama on Windows if available."""
        # Check if output is a TTY
        if not sys.stdout.isatty():
            cls._colors_enabled = False
            return

        # Check for NO_COLOR environment variable (standard for disabling colors)
        if os.getenv("NO_COLOR"):
            cls._colors_enabled = False
            return

        # On Windows, try to enable ANSI escape sequences
        if sys.platform == "win32":
            try:
                # Try colorama first for broad Windows compatibility
                import colorama
                colorama.init()
            except ImportError:
                # Fallback: enable VT processing on Windows 10+
                try:
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    # Enable ENABLE_VIRTUAL_TERMINAL_PROCESSING
                    kernel32.SetConsoleMode(
                        kernel32.GetStdHandle(-11), 7
                    )
                except Exception:
                    cls._colors_enabled = False

    @classmethod
    def _color(cls, style: str) -> str:
        """Get color code for style, or empty string if colors disabled."""
        if not cls._colors_enabled:
            return ""
        return cls.COLORS.get(style, "")

    @classmethod
    def _reset(cls) -> str:
        """Get reset code, or empty string if colors disabled."""
        if not cls._colors_enabled:
            return ""
        return cls.COLORS["reset"]

    @classmethod
    def format_chat(cls, label: str, message: str, style: str = "info") -> str:
        """
        Format a chat message with color and label.

        Args:
            label: The label (e.g., "You", "Agent", "System")
            message: The message text
            style: Color style to use

        Returns:
            Formatted string with colors
        """
        color = cls._color(style)
        reset = cls._reset()
        return f"{color}{label}:{reset} {message}"

    @classmethod
    def format_task_start(cls, task_name: str) -> str:
        """Format task start message."""
        color = cls._color("task")
        reset = cls._reset()
        return f"{color}[{cls.ICON_RUNNING}] Task: {task_name}{reset}"

    @classmethod
    def format_task_end(cls, task_name: str, success: bool = True) -> str:
        """Format task completion message."""
        icon = cls.ICON_COMPLETED if success else cls.ICON_ERROR
        style = "task" if success else "error"
        color = cls._color(style)
        reset = cls._reset()
        status = "completed" if success else "failed"
        return f"{color}[{icon}] Task {status}: {task_name}{reset}"

    @classmethod
    def format_action_start(
        cls, action_name: str, is_sub_action: bool = False
    ) -> str:
        """Format action start message."""
        color = cls._color("action")
        reset = cls._reset()
        return f"{color}[{cls.ICON_RUNNING}] Running: {action_name}{reset}"

    @classmethod
    def format_action_end(
        cls, action_name: str, success: bool = True, is_sub_action: bool = False
    ) -> str:
        """Format action completion message."""
        icon = cls.ICON_COMPLETED if success else cls.ICON_ERROR
        # Always use action color (gray) for consistency
        color = cls._color("action")
        reset = cls._reset()
        return f"{color}[{icon}] {action_name}{reset}"

    @classmethod
    def format_error(cls, message: str) -> str:
        """Format an error message."""
        color = cls._color("error")
        reset = cls._reset()
        return f"{color}Error: {message}{reset}"

    @classmethod
    def format_success(cls, message: str) -> str:
        """Format a success message."""
        color = cls._color("success")
        reset = cls._reset()
        return f"{color}{message}{reset}"

    @classmethod
    def format_info(cls, message: str) -> str:
        """Format an info message."""
        color = cls._color("info")
        reset = cls._reset()
        return f"{color}{message}{reset}"

    @classmethod
    def format_header(cls, text: str) -> str:
        """Format a header/title."""
        color = cls._color("agent")
        reset = cls._reset()
        return f"\n{color}=== {text} ==={reset}\n"

    # Version and tagline
    VERSION = "V1.2.0"
    TAGLINE = "Your Personal AI Assistant that works 24/7 in your machine."

    @classmethod
    def print_logo(cls) -> None:
        """Print the CraftBot ASCII logo with CRAFT in white and BOT in orange."""
        white = cls._color("user")  # Bold white
        orange = cls._color("agent")  # Bold orange
        reset = cls._reset()
        print()  # Blank line before logo
        for craft_part, bot_part in cls.LOGO_LINES:
            print(f"{white}{craft_part}{orange}{bot_part}{reset}")
        # Print version and tagline
        print(f"{orange}CraftBot {cls.VERSION}. {cls.TAGLINE}{reset}")

    @classmethod
    def is_hidden_action(cls, action_name: str) -> bool:
        """Check if an action should be hidden from output."""
        return action_name.lower() in cls.HIDDEN_ACTIONS

    @classmethod
    def format_divider(cls) -> str:
        """Format a divider line."""
        return "-" * 50

    @classmethod
    def clear_screen(cls) -> None:
        """Clear the terminal screen."""
        if sys.platform == "win32":
            os.system("cls")
        else:
            os.system("clear")

    @classmethod
    def clear_previous_line(cls) -> None:
        """Move cursor up one line and clear it (to remove echoed input)."""
        # ANSI escape: move up one line and clear the entire line
        sys.stdout.write("\033[A\033[2K")
        sys.stdout.flush()
