"""
Browser interface using the unified UI layer.

This module provides a browser interface for agent interaction using
the centralized UI layer components.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.ui_layer.controller.ui_controller import UIController, UIControllerConfig
from app.ui_layer.adapters.browser_adapter import BrowserAdapter
from app.internal_action_interface import InternalActionInterface

if TYPE_CHECKING:
    from app.agent_base import AgentBase


class BrowserInterface:
    """
    Browser interface wrapper that uses the unified UI layer.

    This class sets up the UIController and BrowserAdapter to provide
    a web-based interface for agent interaction via WebSocket.
    """

    def __init__(
        self, agent: "AgentBase", *, default_provider: str, default_api_key: str
    ) -> None:
        """
        Initialize the browser interface.

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
            enable_footage=True,  # Browser supports footage display
            enable_action_panel=True,  # Browser has action panel
        )
        self._controller = UIController(agent, self._config)

        # Create browser adapter
        self._adapter = BrowserAdapter(self._controller)

    @property
    def controller(self) -> UIController:
        """Get the UI controller."""
        return self._controller

    @property
    def adapter(self) -> BrowserAdapter:
        """Get the browser adapter."""
        return self._adapter

    async def start(self) -> None:
        """Start the browser interface."""
        # Start the UI controller
        await self._controller.start()

        # Set UI adapter reference for actions that need direct UI access (e.g., attachments)
        InternalActionInterface.set_ui_adapter(self._adapter)

        try:
            # Start the adapter (this blocks until the adapter exits)
            await self._adapter.start()
        finally:
            # Clear UI adapter reference
            InternalActionInterface.set_ui_adapter(None)
            # Stop the controller
            await self._controller.stop()
