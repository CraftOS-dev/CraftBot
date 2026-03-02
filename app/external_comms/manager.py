# -*- coding: utf-8 -*-
"""
app.external_comms.manager

Manager for external communication channels (WhatsApp, Telegram).
Coordinates incoming messages from external platforms and routes them to the agent.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Dict, Optional

from app.external_comms.config import (
    ExternalCommsConfig,
    TelegramConfig,
    WhatsAppConfig,
    get_config,
)

if TYPE_CHECKING:
    from app.agent_base import AgentBase

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# Type alias for message callback
MessageCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]


class BaseChannel(ABC):
    """Base class for external communication channels."""

    def __init__(
        self,
        name: str,
        callback: MessageCallback,
    ):
        """
        Initialize channel.

        Args:
            name: Channel name (e.g., "telegram", "whatsapp").
            callback: Async callback to invoke when a message is received.
        """
        self._name = name
        self._callback = callback
        self._running = False

    @property
    def name(self) -> str:
        """Get channel name."""
        return self._name

    @property
    def is_running(self) -> bool:
        """Check if channel is running."""
        return self._running

    @abstractmethod
    async def start(self) -> None:
        """Start the channel."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel."""
        pass

    async def _dispatch_message(self, payload: Dict[str, Any]) -> None:
        """Dispatch a message to the callback."""
        try:
            await self._callback(payload)
        except Exception as e:
            logger.error(f"[{self._name.upper()}] Error dispatching message: {e}")


class TelegramChannel(BaseChannel):
    """Telegram communication channel."""

    def __init__(
        self,
        config: TelegramConfig,
        callback: MessageCallback,
    ):
        """
        Initialize Telegram channel.

        Args:
            config: Telegram configuration.
            callback: Message callback.
        """
        super().__init__("telegram", callback)
        self._config = config
        self._poller = None

    async def start(self) -> None:
        """Start Telegram polling."""
        if self._running:
            return

        if not self._config.bot_token:
            logger.warning("[TELEGRAM] No bot token configured, skipping")
            return

        try:
            from app.external_comms.telegram_poller import TelegramPoller

            self._poller = TelegramPoller(
                bot_token=self._config.bot_token,
                callback=self._dispatch_message,
            )
            await self._poller.start()
            self._running = True
            logger.info("[TELEGRAM] Channel started")
        except Exception as e:
            logger.error(f"[TELEGRAM] Failed to start channel: {e}")

    async def stop(self) -> None:
        """Stop Telegram polling."""
        if not self._running:
            return

        if self._poller:
            await self._poller.stop()
            self._poller = None

        self._running = False
        logger.info("[TELEGRAM] Channel stopped")


class WhatsAppChannel(BaseChannel):
    """WhatsApp communication channel."""

    def __init__(
        self,
        config: WhatsAppConfig,
        callback: MessageCallback,
    ):
        """
        Initialize WhatsApp channel.

        Args:
            config: WhatsApp configuration.
            callback: Message callback.
        """
        super().__init__("whatsapp", callback)
        self._config = config
        self._listener = None

    async def start(self) -> None:
        """Start WhatsApp listener."""
        if self._running:
            return

        if self._config.mode == "web":
            if not self._config.session_id:
                logger.warning("[WHATSAPP] No session_id configured for Web mode, skipping")
                return

            try:
                from app.external_comms.whatsapp_listener import WhatsAppWebListener

                self._listener = WhatsAppWebListener(
                    session_id=self._config.session_id,
                    callback=self._dispatch_message,
                )
                await self._listener.start()
                self._running = True
                logger.info("[WHATSAPP] Channel started (Web mode)")
            except Exception as e:
                logger.error(f"[WHATSAPP] Failed to start channel: {e}")

        elif self._config.mode == "business":
            # Business API mode - would need webhook server
            logger.warning("[WHATSAPP] Business API mode not yet implemented")
        else:
            logger.warning(f"[WHATSAPP] Unknown mode: {self._config.mode}")

    async def stop(self) -> None:
        """Stop WhatsApp listener."""
        if not self._running:
            return

        if self._listener:
            await self._listener.stop()
            self._listener = None

        self._running = False
        logger.info("[WHATSAPP] Channel stopped")


class ExternalCommsManager:
    """
    Manager for all external communication channels.

    Coordinates incoming messages from WhatsApp, Telegram, etc.
    and routes them to the agent's _handle_external_event method.
    """

    def __init__(self, agent: "AgentBase"):
        """
        Initialize the external communications manager.

        Args:
            agent: The agent instance to route messages to.
        """
        self._agent = agent
        self._config = get_config()
        self._channels: Dict[str, BaseChannel] = {}
        self._running = False

    async def start(self) -> None:
        """Start all enabled channels."""
        if self._running:
            return

        logger.info("[EXTERNAL_COMMS] Starting external communications manager...")

        # Check if any channels are enabled
        telegram_enabled = self._config.telegram.enabled
        whatsapp_enabled = self._config.whatsapp.enabled

        if not telegram_enabled and not whatsapp_enabled:
            logger.info("[EXTERNAL_COMMS] No external channels enabled")
            return

        # Start Telegram channel
        if telegram_enabled:
            channel = TelegramChannel(
                config=self._config.telegram,
                callback=self._handle_incoming_message,
            )
            self._channels["telegram"] = channel
            await channel.start()

        # Start WhatsApp channel
        if whatsapp_enabled:
            channel = WhatsAppChannel(
                config=self._config.whatsapp,
                callback=self._handle_incoming_message,
            )
            self._channels["whatsapp"] = channel
            await channel.start()

        self._running = True
        active_channels = [name for name, ch in self._channels.items() if ch.is_running]
        logger.info(f"[EXTERNAL_COMMS] Active channels: {active_channels}")

    async def stop(self) -> None:
        """Stop all channels."""
        if not self._running:
            return

        logger.info("[EXTERNAL_COMMS] Stopping external communications manager...")

        for name, channel in self._channels.items():
            try:
                await channel.stop()
            except Exception as e:
                logger.warning(f"[EXTERNAL_COMMS] Error stopping {name}: {e}")

        self._channels.clear()
        self._running = False
        logger.info("[EXTERNAL_COMMS] All channels stopped")

    async def _handle_incoming_message(self, payload: Dict[str, Any]) -> None:
        """
        Handle incoming message from any channel.

        Routes the message to the agent's _handle_external_event method.

        Args:
            payload: Message payload with standardized fields:
                - source: Platform name (e.g., "Telegram", "WhatsApp")
                - integrationType: Integration type (e.g., "telegram_bot", "whatsapp_web")
                - contactId: Contact/chat ID
                - contactName: Contact name
                - messageBody: Message text
        """
        source = payload.get("source", "Unknown")
        contact_name = payload.get("contactName") or payload.get("contactId", "unknown")
        message_body = payload.get("messageBody", "")

        logger.info(
            f"[EXTERNAL_COMMS] Received message from {source}: "
            f"{contact_name}: {message_body[:50]}..."
        )

        # Route to agent's external event handler
        try:
            await self._agent._handle_external_event(payload)
        except Exception as e:
            logger.error(f"[EXTERNAL_COMMS] Error handling message: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get status of all channels."""
        return {
            "running": self._running,
            "channels": {
                name: {
                    "running": channel.is_running,
                }
                for name, channel in self._channels.items()
            },
            "config": {
                "telegram_enabled": self._config.telegram.enabled,
                "whatsapp_enabled": self._config.whatsapp.enabled,
            },
        }


# Global manager instance
_manager: Optional[ExternalCommsManager] = None


def get_external_comms_manager() -> Optional[ExternalCommsManager]:
    """Get the global external communications manager."""
    return _manager


def initialize_manager(agent: "AgentBase") -> ExternalCommsManager:
    """Initialize and return the global external communications manager."""
    global _manager
    _manager = ExternalCommsManager(agent)
    return _manager
