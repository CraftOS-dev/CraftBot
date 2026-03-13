# -*- coding: utf-8 -*-
"""
CLI interface using the unified UI layer.

This module provides a CLI interface for agent interaction using
the centralized UI layer components.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.ui_layer.controller.ui_controller import UIController, UIControllerConfig
from app.ui_layer.adapters.cli_adapter import CLIAdapter

if TYPE_CHECKING:
    from app.agent_base import AgentBase


class CLIInterface:
    """
    CLI interface wrapper that uses the unified UI layer.

    This class sets up the UIController and CLIAdapter to provide
    a command-line interface for agent interaction.
    """

    def __init__(
        self, agent: "AgentBase", *, default_provider: str, default_api_key: str
    ) -> None:
        """
        Initialize the CLI interface.

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
            enable_footage=False,  # CLI doesn't support footage display
            enable_action_panel=False,  # CLI uses inline action display
        )
        self._controller = UIController(agent, self._config)

        # Create CLI adapter
        self._adapter = CLIAdapter(self._controller)

    @property
    def controller(self) -> UIController:
        """Get the UI controller."""
        return self._controller

    @property
    def adapter(self) -> CLIAdapter:
        """Get the CLI adapter."""
        return self._adapter

    async def start(self) -> None:
        """Start the CLI interface."""
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
        await self._adapter.stop()
        await self._controller.stop()
        self._agent.is_running = False
