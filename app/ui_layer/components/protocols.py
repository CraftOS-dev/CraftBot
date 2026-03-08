"""Component protocols defining interfaces for UI components."""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from app.ui_layer.components.types import ChatMessage, ActionItem


@runtime_checkable
class ChatComponentProtocol(Protocol):
    """
    Protocol for chat display components.

    Defines the interface that any chat display implementation must follow.
    Used by CLI (print), TUI (ConversationLog), and Browser (ChatPanel).
    """

    async def append_message(self, message: ChatMessage) -> None:
        """
        Append a message to the chat log.

        Args:
            message: The chat message to append
        """
        ...

    async def clear(self) -> None:
        """Clear all messages from the chat log."""
        ...

    def scroll_to_bottom(self) -> None:
        """Scroll to show the latest message."""
        ...

    def get_messages(self) -> List[ChatMessage]:
        """
        Get all messages in the chat log.

        Returns:
            List of all chat messages
        """
        ...


@runtime_checkable
class ActionPanelProtocol(Protocol):
    """
    Protocol for action panel components.

    Defines the interface for displaying tasks and actions.
    Used by TUI and Browser interfaces.
    """

    async def add_item(self, item: ActionItem) -> None:
        """
        Add an action item to the panel.

        Args:
            item: The action item to add
        """
        ...

    async def update_item(self, item_id: str, status: str) -> None:
        """
        Update an item's status by ID.

        Args:
            item_id: ID of the item to update
            status: New status ("running", "completed", "error")
        """
        ...

    async def update_item_by_name(
        self,
        action_name: str,
        task_id: str,
        status: str,
        action_id: str = "",
        output: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Update an item's status by matching name and task.

        Finds the most recent running action with the given name under the task
        and updates its status. Falls back to ID matching if action_id provided.

        Args:
            action_name: Name of the action to update
            task_id: Parent task ID
            status: New status ("running", "completed", "error")
            action_id: Optional exact action ID to match first
            output: Output data from the action
            error: Error message if action failed
        """
        ...

    async def update_item_data(
        self,
        item_id: str,
        output: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Update an item's output/error data.

        Args:
            item_id: ID of the item to update
            output: Output data from the action
            error: Error message if action failed
        """
        ...

    async def remove_item(self, item_id: str) -> None:
        """
        Remove an item from the panel.

        Args:
            item_id: ID of the item to remove
        """
        ...

    async def clear(self) -> None:
        """Clear all items from the panel."""
        ...

    def select_task(self, task_id: Optional[str]) -> None:
        """
        Select a task for detail view.

        Args:
            task_id: ID of task to select, or None to deselect
        """
        ...

    def get_items(self) -> List[ActionItem]:
        """
        Get all items in the panel.

        Returns:
            List of all action items
        """
        ...


@runtime_checkable
class StatusBarProtocol(Protocol):
    """
    Protocol for status bar components.

    Defines the interface for displaying status messages.
    """

    async def set_status(self, message: str) -> None:
        """
        Set the status message.

        Args:
            message: The status message to display
        """
        ...

    async def set_loading(self, loading: bool) -> None:
        """
        Show or hide loading indicator.

        Args:
            loading: Whether to show loading indicator
        """
        ...

    def get_status(self) -> str:
        """
        Get the current status message.

        Returns:
            Current status message
        """
        ...


@runtime_checkable
class InputComponentProtocol(Protocol):
    """
    Protocol for input components.

    Defines the interface for user input handling.
    """

    async def get_input(self) -> str:
        """
        Get user input (may block until input received).

        Returns:
            The user's input string
        """
        ...

    def set_placeholder(self, text: str) -> None:
        """
        Set placeholder text shown when input is empty.

        Args:
            text: Placeholder text
        """
        ...

    def set_enabled(self, enabled: bool) -> None:
        """
        Enable or disable the input.

        Args:
            enabled: Whether input should be enabled
        """
        ...

    def focus(self) -> None:
        """Focus the input component."""
        ...

    def clear(self) -> None:
        """Clear the input value."""
        ...


@runtime_checkable
class FootageComponentProtocol(Protocol):
    """
    Protocol for VM footage display components.

    Defines the interface for displaying screenshots during GUI mode.
    """

    async def update(self, image_bytes: bytes) -> None:
        """
        Update the displayed image.

        Args:
            image_bytes: PNG image data
        """
        ...

    async def clear(self) -> None:
        """Clear the display and show placeholder."""
        ...

    def set_visible(self, visible: bool) -> None:
        """
        Show or hide the footage display.

        Args:
            visible: Whether display should be visible
        """
        ...


@runtime_checkable
class MenuComponentProtocol(Protocol):
    """
    Protocol for menu components.

    Defines the interface for the main menu (TUI/Browser).
    """

    async def show(self) -> None:
        """Show the menu."""
        ...

    async def hide(self) -> None:
        """Hide the menu."""
        ...

    def set_items(self, items: List[str]) -> None:
        """
        Set menu items.

        Args:
            items: List of menu item labels
        """
        ...

    async def get_selection(self) -> Optional[str]:
        """
        Get the selected menu item.

        Returns:
            Selected item label, or None if cancelled
        """
        ...
