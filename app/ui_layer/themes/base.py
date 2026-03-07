"""Theme base classes and protocols."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol


class StyleType(Enum):
    """Semantic style types for UI elements."""

    # Chat message styles
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
    ERROR = "error"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"

    # Action panel styles
    TASK = "task"
    ACTION = "action"

    # Status styles
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StyleDefinition:
    """
    Abstract style definition that adapters interpret.

    This defines styling in a platform-agnostic way. Each adapter
    (CLI, TUI, Browser) converts these to their native format.

    Attributes:
        foreground: Text color (color name or hex like "#ff4f18")
        background: Background color (color name or hex)
        bold: Whether text should be bold
        italic: Whether text should be italic
        underline: Whether text should be underlined
    """

    foreground: Optional[str] = None
    background: Optional[str] = None
    bold: bool = False
    italic: bool = False
    underline: bool = False

    def to_css(self) -> str:
        """Convert to CSS style string for browser adapter."""
        parts = []
        if self.foreground:
            parts.append(f"color: {self.foreground}")
        if self.background:
            parts.append(f"background-color: {self.background}")
        if self.bold:
            parts.append("font-weight: bold")
        if self.italic:
            parts.append("font-style: italic")
        if self.underline:
            parts.append("text-decoration: underline")
        return "; ".join(parts)

    def to_ansi(self) -> str:
        """Convert to ANSI escape codes for CLI adapter."""
        codes = []

        # Bold
        if self.bold:
            codes.append("1")

        # Italic
        if self.italic:
            codes.append("3")

        # Underline
        if self.underline:
            codes.append("4")

        # Foreground color (convert hex to 256-color approximation)
        if self.foreground:
            codes.append(f"38;5;{_hex_to_256(self.foreground)}")

        # Background color
        if self.background:
            codes.append(f"48;5;{_hex_to_256(self.background)}")

        if codes:
            return f"\033[{';'.join(codes)}m"
        return ""

    def to_rich(self) -> str:
        """Convert to Rich markup style for TUI adapter."""
        parts = []
        if self.bold:
            parts.append("bold")
        if self.italic:
            parts.append("italic")
        if self.underline:
            parts.append("underline")
        if self.foreground:
            parts.append(self.foreground)
        return " ".join(parts) if parts else ""


class ThemeProtocol(Protocol):
    """Protocol for theme implementations."""

    @property
    def name(self) -> str:
        """Theme name."""
        ...

    def get_style(self, style_type: StyleType) -> StyleDefinition:
        """Get style definition for a semantic type."""
        ...

    def get_icon(self, icon_name: str) -> str:
        """Get icon/symbol for a named icon."""
        ...


class ThemeAdapter(ABC):
    """
    Adapts abstract theme to interface-specific formatting.

    Each interface (CLI, TUI, Browser) implements this to convert
    StyleDefinitions to their native format.
    """

    def __init__(self, theme: ThemeProtocol) -> None:
        """
        Initialize the theme adapter.

        Args:
            theme: The theme to adapt
        """
        self._theme = theme

    @property
    def theme(self) -> ThemeProtocol:
        """Get the underlying theme."""
        return self._theme

    @abstractmethod
    def format_text(
        self,
        text: str,
        style_type: StyleType,
    ) -> Any:
        """
        Format text with the given style.

        Args:
            text: The text to format
            style_type: The semantic style type

        Returns:
            Formatted text in the adapter's native format
        """
        pass

    @abstractmethod
    def format_chat_message(
        self,
        label: str,
        message: str,
        style_type: StyleType,
    ) -> Any:
        """
        Format a chat message with label.

        Args:
            label: The message label (e.g., "You", "Agent")
            message: The message content
            style_type: The semantic style type

        Returns:
            Formatted message in the adapter's native format
        """
        pass

    @abstractmethod
    def format_action_item(
        self,
        name: str,
        status: str,
        is_task: bool,
        indent: int = 0,
    ) -> Any:
        """
        Format an action panel item.

        Args:
            name: The item name
            status: Status ("running", "completed", "error")
            is_task: Whether this is a task (vs an action)
            indent: Indentation level

        Returns:
            Formatted item in the adapter's native format
        """
        pass

    def get_icon(self, icon_name: str) -> str:
        """Get an icon from the theme."""
        return self._theme.get_icon(icon_name)


def _hex_to_256(hex_color: str) -> int:
    """Convert hex color to nearest 256-color ANSI code."""
    if not hex_color.startswith("#"):
        # Return a default color for named colors
        color_map = {
            "white": 15,
            "black": 0,
            "red": 9,
            "green": 10,
            "blue": 12,
            "yellow": 11,
            "orange": 208,
            "gray": 8,
            "grey": 8,
        }
        return color_map.get(hex_color.lower(), 15)

    # Parse hex color
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)

    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    # Convert to 6x6x6 color cube (codes 16-231)
    if r == g == b:
        # Grayscale
        if r < 8:
            return 16
        if r > 248:
            return 231
        return round((r - 8) / 247 * 24) + 232

    # Color cube
    r_idx = round(r / 255 * 5)
    g_idx = round(g / 255 * 5)
    b_idx = round(b / 255 * 5)
    return 16 + (36 * r_idx) + (6 * g_idx) + b_idx
