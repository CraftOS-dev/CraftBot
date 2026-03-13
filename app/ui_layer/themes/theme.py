"""Default theme implementation."""

from __future__ import annotations

from typing import Dict, List

from app.ui_layer.themes.base import StyleType, StyleDefinition


class BaseTheme:
    """
    Default theme implementation for CraftBot.

    Defines the standard CraftBot color scheme and icons that are
    used across all interfaces.
    """

    name = "craftbot"

    # Color definitions
    COLOR_PRIMARY = "#ff4f18"  # CraftBot orange
    COLOR_WHITE = "#ffffff"
    COLOR_GRAY = "#a0a0a0"
    COLOR_DARK_GRAY = "#666666"
    COLOR_BLACK = "#000000"
    COLOR_RED = "#ff3333"
    COLOR_GREEN = "#00cc00"
    COLOR_BLUE = "#0088ff"
    COLOR_YELLOW = "#ffcc00"

    # Style definitions for each semantic type
    STYLES: Dict[StyleType, StyleDefinition] = {
        # Chat message styles
        StyleType.USER: StyleDefinition(foreground=COLOR_WHITE, bold=True),
        StyleType.AGENT: StyleDefinition(foreground=COLOR_PRIMARY, bold=True),
        StyleType.SYSTEM: StyleDefinition(foreground=COLOR_GRAY, bold=True),
        StyleType.ERROR: StyleDefinition(foreground=COLOR_RED, bold=True),
        StyleType.INFO: StyleDefinition(foreground=COLOR_DARK_GRAY),
        StyleType.SUCCESS: StyleDefinition(foreground=COLOR_GREEN, bold=True),
        StyleType.WARNING: StyleDefinition(foreground=COLOR_YELLOW, bold=True),
        # Action panel styles
        StyleType.TASK: StyleDefinition(foreground=COLOR_PRIMARY, bold=True),
        StyleType.ACTION: StyleDefinition(foreground=COLOR_GRAY, bold=True),
        # Status styles
        StyleType.PENDING: StyleDefinition(foreground=COLOR_GRAY),
        StyleType.RUNNING: StyleDefinition(foreground=COLOR_PRIMARY),
        StyleType.COMPLETED: StyleDefinition(foreground=COLOR_GREEN),
        StyleType.FAILED: StyleDefinition(foreground=COLOR_RED),
    }

    # Icon definitions
    ICONS: Dict[str, str] = {
        "pending": "o",
        "running": "*",
        "completed": "+",
        "error": "x",
        "arrow_right": "→",
        "bullet": "•",
        "checkbox_empty": "[ ]",
        "checkbox_checked": "[x]",
    }

    # Loading animation frames
    LOADING_FRAMES: List[str] = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    # Alternative loading frames for terminals without Unicode support
    LOADING_FRAMES_ASCII: List[str] = ["|", "/", "-", "\\"]

    def get_style(self, style_type: StyleType) -> StyleDefinition:
        """
        Get style definition for a semantic type.

        Args:
            style_type: The semantic style type

        Returns:
            StyleDefinition for the type, or default if not found
        """
        return self.STYLES.get(style_type, StyleDefinition())

    def get_icon(self, icon_name: str) -> str:
        """
        Get icon/symbol for a named icon.

        Args:
            icon_name: The icon name

        Returns:
            Icon string, or empty string if not found
        """
        return self.ICONS.get(icon_name, "")

    def get_loading_frame(self, index: int, use_ascii: bool = False) -> str:
        """
        Get a loading animation frame.

        Args:
            index: Frame index (will wrap around)
            use_ascii: Use ASCII-only frames for compatibility

        Returns:
            Loading frame character
        """
        frames = self.LOADING_FRAMES_ASCII if use_ascii else self.LOADING_FRAMES
        return frames[index % len(frames)]

    def get_status_icon(self, status: str) -> str:
        """
        Get the icon for a status.

        Args:
            status: Status string ("running", "completed", "error", etc.)

        Returns:
            Icon character for the status
        """
        status_lower = status.lower()
        if status_lower in ("completed", "done", "success"):
            return self.ICONS["completed"]
        if status_lower in ("error", "failed"):
            return self.ICONS["error"]
        if status_lower in ("running", "in_progress"):
            return self.ICONS["running"]
        return self.ICONS["pending"]

    def get_status_style(self, status: str) -> StyleType:
        """
        Get the style type for a status.

        Args:
            status: Status string

        Returns:
            StyleType for the status
        """
        status_lower = status.lower()
        if status_lower in ("completed", "done", "success"):
            return StyleType.COMPLETED
        if status_lower in ("error", "failed"):
            return StyleType.FAILED
        if status_lower in ("running", "in_progress"):
            return StyleType.RUNNING
        return StyleType.PENDING


# ASCII art logo for CraftBot
CRAFTBOT_LOGO = r"""
   ______           ______     ____        __
  / ____/________ _/ __/ /_   / __ )____  / /_
 / /   / ___/ __ `/ /_/ __/  / __  / __ \/ __/
/ /___/ /  / /_/ / __/ /_   / /_/ / /_/ / /_
\____/_/   \__,_/_/  \__/  /_____/\____/\__/
"""

CRAFTBOT_LOGO_COLORED = {
    "craft": r"""
   ______           ______
  / ____/________ _/ __/ /_
 / /   / ___/ __ `/ /_/ __/
/ /___/ /  / /_/ / __/ /_
\____/_/   \__,_/_/  \__/""",
    "bot": r"""
     ____        __
    / __ )____  / /_
   / __  / __ \/ __/
  / /_/ / /_/ / /_
 /_____/\____/\__/""",
}
