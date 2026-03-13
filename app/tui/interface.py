"""
TUI interface using the unified UI layer.

This module provides a TUI interface for agent interaction using
the centralized UI layer components.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.ui_layer.controller.ui_controller import UIController, UIControllerConfig
from app.ui_layer.adapters.tui_adapter import TUIAdapter

if TYPE_CHECKING:
    from app.agent_base import AgentBase


class TUIInterface:
    """
    TUI interface wrapper that uses the unified UI layer.

    This class sets up the UIController and TUIAdapter to provide
    a Textual-based TUI for agent interaction.
    """

    def __init__(
        self, agent: "AgentBase", *, default_provider: str, default_api_key: str
    ) -> None:
        """
        Initialize the TUI interface.

        Args:
            agent: The agent runtime instance
            default_provider: Default LLM provider name
            default_api_key: Default API key
        """
        self._agent = agent

        # Create UI controller with configuration
        self._config = UIControllerConfig(
            default_provider=default_provider,
            default_api_key=default_api_key,
            enable_footage=True,  # TUI supports footage display
            enable_action_panel=True,  # TUI has action panel
        )
        self._controller = UIController(agent, self._config)

        # Create TUI adapter
        self._adapter = TUIAdapter(self._controller)

    @property
    def controller(self) -> UIController:
        """Get the UI controller."""
        return self._controller

    @property
    def adapter(self) -> TUIAdapter:
        """Get the TUI adapter."""
        return self._adapter

    # ─────────────────────────────────────────────────────────────────────
    # Delegate properties and methods to adapter for backwards compatibility
    # ─────────────────────────────────────────────────────────────────────

    @property
    def chat_updates(self):
        """Get chat updates queue (for CraftApp compatibility)."""
        return self._adapter.chat_updates

    @property
    def action_updates(self):
        """Get action updates queue (for CraftApp compatibility)."""
        return self._adapter.action_updates

    @property
    def status_updates(self):
        """Get status updates queue (for CraftApp compatibility)."""
        return self._adapter.status_updates

    @property
    def footage_updates(self):
        """Get footage updates queue (for CraftApp compatibility)."""
        return self._adapter.footage_updates

    @property
    def _action_items(self):
        """Get action items dict (for CraftApp compatibility)."""
        return self._adapter._action_panel._items

    @property
    def _action_order(self):
        """Get action order list (for CraftApp compatibility)."""
        return self._adapter._action_panel._order

    @property
    def _loading_frame_index(self):
        """Get loading frame index (for CraftApp compatibility)."""
        return self._adapter._loading_frame_index

    @_loading_frame_index.setter
    def _loading_frame_index(self, value):
        """Set loading frame index (for CraftApp compatibility)."""
        self._adapter._loading_frame_index = value

    def get_actions_for_task(self, task_id: str):
        """Get actions for a task (for CraftApp compatibility)."""
        return self._adapter.get_actions_for_task(task_id)

    def get_task_items(self):
        """Get task items (for CraftApp compatibility)."""
        return self._adapter.get_task_items()

    def format_chat_entry(self, label: str, message: str, style: str):
        """Format a chat entry (for CraftApp compatibility)."""
        return self._adapter.format_chat_entry(label, message, style)

    def format_action_item(self, item):
        """Format an action item (for CraftApp compatibility)."""
        return self._adapter.format_action_item(item)

    def configure_provider(self, provider: str, api_key: str) -> None:
        """Configure provider (for CraftApp compatibility)."""
        return self._adapter.configure_provider(provider, api_key)

    def notify_provider(self, provider: str) -> None:
        """Notify about provider (for CraftApp compatibility)."""
        return self._adapter.notify_provider(provider)

    async def push_footage(self, image_bytes: bytes, container_id: str = "") -> None:
        """Push footage update (for CraftApp compatibility)."""
        return await self._adapter.push_footage(image_bytes, container_id)

    def signal_gui_mode_end(self) -> None:
        """Signal GUI mode end (for CraftApp compatibility)."""
        return self._adapter.signal_gui_mode_end()

    def gui_mode_ended(self) -> bool:
        """Check if GUI mode ended (for CraftApp compatibility)."""
        return self._adapter.gui_mode_ended()

    def clear_logs(self) -> None:
        """Clear logs (for CraftApp compatibility)."""
        return self._adapter.clear_logs()

    async def submit_user_message(self, message: str) -> None:
        """Submit user message (for CraftApp compatibility)."""
        await self._adapter.submit_message(message)

    async def start(self) -> None:
        """Start the TUI interface."""
        # Start the UI controller
        await self._controller.start()

        try:
            # Start the adapter (this blocks until the adapter exits)
            await self._adapter.start()
        finally:
            # Ensure cleanup
            await self._adapter.stop()
            await self._controller.stop()

    async def request_shutdown(self) -> None:
        """Request interface shutdown."""
        await self._adapter.request_shutdown()
