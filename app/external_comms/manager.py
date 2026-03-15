# -*- coding: utf-8 -*-
"""
app.external_comms.manager

Manager for external communication channels.
Uses the platform registry to discover and start all platforms that support listening.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from app.external_comms.base import PlatformMessage
from app.external_comms.config import get_config

if TYPE_CHECKING:
    from app.agent_base import AgentBase

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def _import_all_platforms() -> None:
    """Import all platform modules to trigger @register_client decorators."""
    # Each import registers the client class in the registry
    platform_modules = [
        "app.external_comms.platforms.telegram_bot",
        "app.external_comms.platforms.telegram_user",
        "app.external_comms.platforms.slack",
        "app.external_comms.platforms.discord",
        "app.external_comms.platforms.whatsapp_web",
        "app.external_comms.platforms.whatsapp_business",
        "app.external_comms.platforms.gmail",
        "app.external_comms.platforms.notion",
        "app.external_comms.platforms.linkedin",
        "app.external_comms.platforms.outlook",
        "app.external_comms.platforms.google_workspace",
    ]
    import importlib
    for mod in platform_modules:
        try:
            importlib.import_module(mod)
        except Exception:
            pass  # Platform not installed or missing deps — skip silently


class ExternalCommsManager:
    """
    Manager for all external communication channels.

    Discovers platforms with listening support from the registry,
    starts them if they have credentials, and routes incoming messages
    to the agent's _handle_external_event method.
    """

    def __init__(self, agent: "AgentBase"):
        self._agent = agent
        self._config = get_config()
        self._active_clients: Dict[str, Any] = {}
        self._running = False

    async def start(self) -> None:
        """Start all platforms that support listening and have credentials."""
        if self._running:
            return

        logger.info("[EXTERNAL_COMMS] Starting external communications manager...")

        # Ensure all platforms are registered
        _import_all_platforms()

        from app.external_comms.registry import get_all_clients

        started = []
        all_clients = get_all_clients()
        logger.info(f"[EXTERNAL_COMMS] Registered platforms: {list(all_clients.keys())}")
        for platform_id, client in all_clients.items():
            if not client.supports_listening:
                continue
            if not client.has_credentials():
                logger.info(f"[EXTERNAL_COMMS] {platform_id} supports listening but has no credentials, skipping")
                continue

            try:
                await client.start_listening(self._handle_platform_message)
                if client.is_listening:
                    self._active_clients[platform_id] = client
                    started.append(platform_id)
                    logger.info(f"[EXTERNAL_COMMS] Started listening on {platform_id}")
                else:
                    logger.warning(f"[EXTERNAL_COMMS] {platform_id} start_listening returned but not actually listening")
            except Exception as e:
                logger.warning(f"[EXTERNAL_COMMS] Failed to start {platform_id}: {e}")

        self._running = True
        if started:
            logger.info(f"[EXTERNAL_COMMS] Active channels: {started}")
        else:
            logger.info("[EXTERNAL_COMMS] No external channels started")

    async def start_platform(self, platform_id: str) -> bool:
        """Start listening on a specific platform (e.g. after it was just connected).

        If the platform is already in active_clients but not actually listening
        (stale entry from a failed startup), it will be removed and re-started.

        Returns True if the platform was successfully started.
        """
        # Check if already listening (truly active, not stale)
        if platform_id in self._active_clients:
            client = self._active_clients[platform_id]
            if client.is_listening:
                return True  # Already listening
            # Stale entry — remove and re-start
            logger.info(f"[EXTERNAL_COMMS] Removing stale entry for {platform_id}")
            del self._active_clients[platform_id]

        _import_all_platforms()

        from app.external_comms.registry import get_client

        client = get_client(platform_id)
        if client is None:
            logger.warning(f"[EXTERNAL_COMMS] Platform '{platform_id}' not found in registry")
            return False

        if not client.supports_listening:
            return False

        if not client.has_credentials():
            return False

        try:
            await client.start_listening(self._handle_platform_message)
            if client.is_listening:
                self._active_clients[platform_id] = client
                logger.info(f"[EXTERNAL_COMMS] Started listening on {platform_id} (post-connect)")
                return True
            else:
                logger.warning(f"[EXTERNAL_COMMS] {platform_id} start_listening returned but not actually listening")
                return False
        except Exception as e:
            logger.warning(f"[EXTERNAL_COMMS] Failed to start {platform_id}: {e}")
            return False

    async def stop(self) -> None:
        """Stop all listening clients."""
        if not self._running:
            return

        logger.info("[EXTERNAL_COMMS] Stopping external communications manager...")

        for platform_id, client in self._active_clients.items():
            try:
                await client.stop_listening()
            except Exception as e:
                logger.warning(f"[EXTERNAL_COMMS] Error stopping {platform_id}: {e}")

        self._active_clients.clear()
        self._running = False
        logger.info("[EXTERNAL_COMMS] All channels stopped")

    async def _handle_platform_message(self, msg: PlatformMessage) -> None:
        """Convert a PlatformMessage into the legacy payload format and route to agent."""
        payload = {
            "source": msg.platform.replace("_", " ").title(),
            "integrationType": msg.platform,
            "contactId": msg.sender_id,
            "contactName": msg.sender_name or msg.sender_id,
            "messageBody": msg.text,
            "channelId": msg.channel_id,
            "channelName": msg.channel_name,
            "messageId": msg.message_id,
            "is_self_message": msg.raw.get("is_self_message", False),
            "raw": msg.raw,
        }

        source = payload["source"]
        contact_name = payload["contactName"]
        message_body = payload["messageBody"]

        logger.info(
            f"[EXTERNAL_COMMS] Received message from {source}: "
            f"{contact_name}: {message_body[:50]}..."
        )

        try:
            await self._agent._handle_external_event(payload)
        except Exception as e:
            logger.error(f"[EXTERNAL_COMMS] Error handling message: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get status of all channels."""
        return {
            "running": self._running,
            "channels": {
                name: {"running": client.is_listening}
                for name, client in self._active_clients.items()
            },
        }

    async def reload(self) -> Dict[str, Any]:
        """
        Hot-reload external communications configuration.

        This method:
        1. Reloads the config from external_comms_config.json
        2. Stops clients that are no longer enabled
        3. Starts clients that are newly enabled

        Returns:
            Dictionary with reload results.
        """
        from app.external_comms.config import reload_config
        from app.external_comms.registry import get_all_clients

        result = {
            "success": True,
            "stopped": [],
            "started": [],
            "message": "",
        }

        try:
            # Reload config from file
            self._config = reload_config()
            logger.info("[EXTERNAL_COMMS] Configuration reloaded")

            # Get current state
            currently_active = set(self._active_clients.keys())
            _import_all_platforms()
            all_clients = get_all_clients()

            # Determine which platforms should be active based on new config
            should_be_active = set()
            for platform_id, client in all_clients.items():
                if not client.supports_listening:
                    continue
                if not client.has_credentials():
                    continue
                should_be_active.add(platform_id)

            # Stop platforms that should no longer be active
            to_stop = currently_active - should_be_active
            for platform_id in to_stop:
                try:
                    client = self._active_clients.get(platform_id)
                    if client:
                        await client.stop_listening()
                        del self._active_clients[platform_id]
                        result["stopped"].append(platform_id)
                        logger.info(f"[EXTERNAL_COMMS] Stopped {platform_id}")
                except Exception as e:
                    logger.warning(f"[EXTERNAL_COMMS] Error stopping {platform_id}: {e}")

            # Start platforms that should now be active but aren't
            to_start = should_be_active - currently_active
            for platform_id in to_start:
                try:
                    client = all_clients.get(platform_id)
                    if client:
                        await client.start_listening(self._handle_platform_message)
                        if client.is_listening:
                            self._active_clients[platform_id] = client
                            result["started"].append(platform_id)
                            logger.info(f"[EXTERNAL_COMMS] Started {platform_id}")
                except Exception as e:
                    logger.warning(f"[EXTERNAL_COMMS] Error starting {platform_id}: {e}")

            result["message"] = (
                f"Reload complete. Stopped: {len(result['stopped'])}, "
                f"Started: {len(result['started'])}, "
                f"Active: {len(self._active_clients)}"
            )
            logger.info(f"[EXTERNAL_COMMS] {result['message']}")

        except Exception as e:
            result["success"] = False
            result["message"] = f"Reload failed: {e}"
            logger.error(f"[EXTERNAL_COMMS] Reload failed: {e}")

        return result


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
