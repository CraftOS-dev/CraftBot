"""Custom widgets for the TUI interface."""
from __future__ import annotations

import io
from typing import Optional, Tuple

from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.widget import Widget
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option
from textual.widgets import Input
from textual.widgets import RichLog as _BaseLog


class TaskSelected(Message):
    """Posted when a task is clicked in the action panel."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__()

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

try:
    from textual_image.widget import Image as TextualImage
    from textual_image.renderable import HalfcellImage
    from PIL import Image as PILImage
    HAS_TEXTUAL_IMAGE = True
except ImportError:
    HAS_TEXTUAL_IMAGE = False
    TextualImage = None
    HalfcellImage = None
    PILImage = None


class ContextMenu(OptionList):
    """Simple context menu for copy operations."""

    DEFAULT_CSS = """
    ContextMenu {
        width: 20;
        height: auto;
        border: ascii #ff4f18;
        background: #0a0a0a;
        layer: overlay;
    }

    ContextMenu > .option-list--option {
        color: #e5e5e5;
        padding: 0 1;
    }

    ContextMenu > .option-list--option-highlighted {
        background: #ff4f18;
        color: #ffffff;
    }
    """

    def __init__(self, text_to_copy: str, x: int, y: int) -> None:
        super().__init__(Option("Copy text", id="copy"))
        self.text_to_copy = text_to_copy
        self.styles.offset = (x, y)
        # Set border to use ASCII characters
        self.border_title = None
        self.styles.border = ("ascii", "#ff4f18")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle menu selection."""
        if event.option_id == "copy":
            try:
                # Try using pyperclip first for better compatibility
                import pyperclip
                pyperclip.copy(self.text_to_copy)
                self.app.notify("Text copied!", severity="information", timeout=2)
            except ImportError:
                # Fallback to Textual's method if pyperclip not available
                try:
                    self.app.copy_to_clipboard(self.text_to_copy)
                    self.app.notify("Text copied!", severity="information", timeout=2)
                except Exception as e:
                    self.app.notify(f"Copy failed: {str(e)}", severity="error", timeout=3)
        self.remove()

    def on_blur(self) -> None:
        """Close menu when focus is lost."""
        self.remove()

    def on_key(self, event: events.Key) -> None:
        """Handle escape key to close the menu."""
        if event.key == "escape":
            self.remove()
            event.stop()


class PasteableInput(Input):
    """Input widget with enhanced paste support using pyperclip."""

    BINDINGS = [
        ("ctrl+v", "paste_from_clipboard", "Paste"),
        ("shift+insert", "paste_from_clipboard", "Paste"),
    ]

    def action_paste_from_clipboard(self) -> None:
        """Paste text from clipboard using pyperclip for better compatibility."""
        try:
            import pyperclip
            text = pyperclip.paste()
            if text:
                # Insert text at cursor position
                self.insert_text_at_cursor(text)
        except ImportError:
            # Fallback to default paste action
            self.action_paste()
        except Exception:
            # Fallback to default paste action on any error
            self.action_paste()


class ConversationLog(_BaseLog):
    """RichLog wrapper with robust wrapping + reflow on resize."""

    can_focus = True

    def __init__(self, *args, **kwargs) -> None:
        # RichLog params: wrap off by default, min_width=78; override both
        kwargs.setdefault("markup", True)
        kwargs.setdefault("highlight", False)
        kwargs.setdefault("wrap", True)  # enable word-wrapping (RichLog)
        kwargs.setdefault("min_width", 1)  # let width track the pane size
        super().__init__(*args, **kwargs)

        # Keep a copy of everything written so it can be reflowed on resize
        self._history: list[RenderableType] = []
        # Track entry keys to their history index for updates
        self._entry_keys: dict[str, int] = {}
        # Reverse mapping: index -> entry_key (for click detection)
        self._index_to_key: list[Optional[str]] = []
        # Store plain text for each entry for copy functionality
        self._text_content: list[str] = []
        # Track line ranges for each message entry (start_line, end_line)
        self._line_ranges: list[Tuple[int, int]] = []

    def append_text(self, content) -> None:
        # Normalize to Rich Text, enable folding of long tokens
        text: Text = content if isinstance(content, Text) else Text(str(content))
        text.no_wrap = False
        text.overflow = "fold"  # split unbreakable runs (URLs / IDs)
        self.append_renderable(text)

    def append_markup(self, markup: str) -> None:
        self.append_text(Text.from_markup(markup))

    def append_renderable(self, renderable: RenderableType, entry_key: Optional[str] = None) -> None:
        # Write using expand/shrink so width follows the widget on resize
        index = len(self._history)
        self._history.append(renderable)
        if entry_key:
            self._entry_keys[entry_key] = index
        # Track index -> entry_key mapping (for click detection)
        self._index_to_key.append(entry_key)

        # Extract and store plain text content
        text_content = self._extract_text(renderable)
        self._text_content.append(text_content)

        # Track the line range before writing
        start_line = len(self.lines)

        self.write(renderable, expand=True, shrink=True)

        # Track the line range after writing
        end_line = len(self.lines) - 1
        self._line_ranges.append((start_line, end_line))

    def update_renderable(self, entry_key: str, renderable: RenderableType) -> None:
        """Update an existing entry by key."""
        if entry_key not in self._entry_keys:
            return
        index = self._entry_keys[entry_key]
        if 0 <= index < len(self._history):
            self._history[index] = renderable
            # Re-render the entire history
            self._reflow_history()

    def clear(self) -> None:
        """Clear the log and the preserved history."""

        self._history.clear()
        self._entry_keys.clear()
        self._index_to_key.clear()
        self._text_content.clear()
        self._line_ranges.clear()
        super().clear()

    def _reflow_history(self) -> None:
        """Re-render stored entries so Rich recalculates wrapping."""

        if not self._history:
            return

        history = list(self._history)
        saved_scroll_y = self.scroll_offset.y  # Save scroll position
        super().clear()

        # Rebuild line ranges as we reflow
        self._line_ranges.clear()
        for renderable in history:
            start_line = len(self.lines)
            self.write(renderable, expand=True, shrink=True)
            end_line = len(self.lines) - 1
            self._line_ranges.append((start_line, end_line))

        # Schedule scroll restoration after DOM update
        self.call_after_refresh(self._restore_scroll, saved_scroll_y)

    def _restore_scroll(self, scroll_y: int) -> None:
        """Restore scroll position after content refresh."""
        # Clamp to max scroll position in case content height changed
        max_scroll = max(0, self.virtual_size.height - self.size.height)
        clamped_y = min(scroll_y, max_scroll)
        self.scroll_to(y=clamped_y, animate=False)

    def _extract_text(self, renderable: RenderableType) -> str:
        """Extract plain text from a renderable object, excluding labels."""
        if isinstance(renderable, Text):
            return renderable.plain
        elif isinstance(renderable, str):
            return renderable
        elif isinstance(renderable, Table):
            # Extract only the message content (second column), skip the label (first column)
            try:
                # Access the table columns - we want the second column (index 1)
                if len(renderable.columns) >= 2:
                    message_column = renderable.columns[1]
                    # Extract text from all cells in the message column
                    text_parts = []
                    if hasattr(message_column, '_cells'):
                        for cell in message_column._cells:
                            if isinstance(cell, Text):
                                text_parts.append(cell.plain)
                            elif isinstance(cell, str):
                                text_parts.append(cell)
                            else:
                                text_parts.append(str(cell))
                    return " ".join(text_parts)
                else:
                    # Fallback if table structure is unexpected
                    from io import StringIO
                    from rich.console import Console
                    string_io = StringIO()
                    console = Console(file=string_io, force_terminal=False, force_jupyter=False, width=200)
                    console.print(renderable)
                    return string_io.getvalue().strip()
            except (AttributeError, IndexError, TypeError):
                # Fallback: use Rich Console to render to plain text
                from io import StringIO
                from rich.console import Console
                string_io = StringIO()
                console = Console(file=string_io, force_terminal=False, force_jupyter=False, width=200)
                console.print(renderable)
                return string_io.getvalue().strip()
        else:
            # Fallback: try to convert to string
            return str(renderable)

    def _get_message_at_line(self, line_number: int) -> Optional[int]:
        """Get the message index for a given line number."""
        if not self._line_ranges:
            return None

        # Find which message contains this line number
        for msg_index, (start_line, end_line) in enumerate(self._line_ranges):
            if start_line <= line_number <= end_line:
                return msg_index

        return None

    def _get_entry_key_at_index(self, index: int) -> Optional[str]:
        """Get the entry_key for a given message index."""
        if 0 <= index < len(self._index_to_key):
            return self._index_to_key[index]
        return None

    def on_click(self, event: events.Click) -> None:
        """Handle click events to show copy menu or select task."""
        # Remove any existing context menu
        for menu in self.app.query("ContextMenu"):
            menu.remove()

        # Calculate the actual line number accounting for scroll offset
        clicked_y = event.y + self.scroll_offset.y

        # Find which message was clicked using line ranges
        clicked_index = self._get_message_at_line(clicked_y)

        if clicked_index is None:
            return

        # Get the entry key for this click
        entry_key = self._get_entry_key_at_index(clicked_index)

        # If this is the action log and we have an entry key, post TaskSelected
        if self.id == "action-log" and entry_key:
            self.post_message(TaskSelected(entry_key))
            return

        # Otherwise show copy menu (for chat log)
        if 0 <= clicked_index < len(self._text_content):
            text_to_copy = self._text_content[clicked_index]
        else:
            return

        if text_to_copy.strip():
            menu = ContextMenu(text_to_copy, event.screen_x, event.screen_y)
            self.app.screen.mount(menu)
            menu.focus()

    def on_resize(self, event: events.Resize) -> None:  # pragma: no cover - UI layout
        """Force a reflow when the widget width changes.

        Without this, RichLog may retain the old line breaks, causing text to
        overflow or leave unused space until new content is added.
        """

        super().on_resize(event)
        self._reflow_history()
        self.refresh(layout=True, repaint=True)


class VMFootageWidget(Widget):
    """Widget for displaying VM screenshots with auto-update capability."""

    DEFAULT_CSS = """
    VMFootageWidget {
        height: 100%;
        width: 100%;
        background: #0a0a0a;
    }

    VMFootageWidget .vm-placeholder {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: #666666;
        text-style: italic;
    }

    VMFootageWidget .vm-image-container {
        width: 100%;
        height: 100%;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._current_image_bytes: Optional[bytes] = None
        self._image_widget: Optional[Widget] = None

    def compose(self) -> ComposeResult:
        yield Static("No VM footage available", id="vm-placeholder", classes="vm-placeholder")

    def update_footage(self, image_bytes: bytes) -> None:
        """Update the displayed footage from PNG bytes."""
        if not HAS_TEXTUAL_IMAGE:
            return

        if image_bytes == self._current_image_bytes:
            return

        self._current_image_bytes = image_bytes

        try:
            pil_image = PILImage.open(io.BytesIO(image_bytes))

            placeholder = self.query("#vm-placeholder")
            if placeholder:
                for p in placeholder:
                    p.remove()

            existing = self.query(".vm-image-container")
            if existing:
                for e in existing:
                    e.remove()

            img_widget = TextualImage(pil_image, classes="vm-image-container")
            self.mount(img_widget)
            self._image_widget = img_widget

        except Exception as e:
            self.log.error(f"Failed to update footage: {e}")

    def clear_footage(self) -> None:
        """Clear the footage and show placeholder."""
        self._current_image_bytes = None

        if self._image_widget:
            self._image_widget.remove()
            self._image_widget = None

        for img in self.query(".vm-image-container"):
            img.remove()

        if not self.query("#vm-placeholder"):
            self.mount(Static("No VM footage available", id="vm-placeholder", classes="vm-placeholder"))
