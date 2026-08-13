"""ExternalCommsManager — starts platform listeners, routes messages.

The manager is decoupled from any agent class. The host passes a
callback to initialize_manager(on_message=...); incoming messages
are normalized to a dict and handed to the callback.

Payload contract (kept unchanged from the legacy implementation):
    source, integrationType, contactId, contactName, messageBody,
    channelId, channelName, messageId, is_self_message, raw
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import PlatformMessage
from .config import ConfigStore, MessageCallback
from .logger import get_logger
from .registry import (
    autoload_integrations,
    get_all_clients,
    get_client,
    invalidate_client,
)

logger = get_logger(__name__)


class ExternalCommsManager:
    def __init__(
        self,
        on_message: MessageCallback,
        exclude_platforms: Optional[List[str]] = None,
    ):
        self._on_message = on_message
        self._active_clients: Dict[str, Any] = {}
        self._running = False
        # Platforms whose listening is owned elsewhere (the
        # ListenerManager) — this manager must never start them.
        self._excluded = set(exclude_platforms or [])

    def _is_excluded(self, platform_id: str) -> bool:
        if platform_id in self._excluded:
            logger.info(
                f"[INTEGRATIONS] {platform_id} excluded from legacy listening "
                "(owned by integrations listener manager)"
            )
            return True
        return False

    async def start(self) -> None:
        if self._running:
            return

        logger.info("[INTEGRATIONS] Starting external communications manager...")
        autoload_integrations()

        started = []
        all_clients = get_all_clients()
        logger.info(f"[INTEGRATIONS] Registered platforms: {list(all_clients.keys())}")

        for platform_id, client in all_clients.items():
            if self._is_excluded(platform_id):
                continue
            if not client.supports_listening:
                continue
            if not client.has_credentials():
                logger.info(
                    f"[INTEGRATIONS] {platform_id} has no credentials, skipping"
                )
                continue

            try:
                await client.start_listening(self._handle_platform_message)
                if client.is_listening:
                    self._active_clients[platform_id] = client
                    started.append(platform_id)
                    logger.info(f"[INTEGRATIONS] Started listening on {platform_id}")
                else:
                    logger.warning(
                        f"[INTEGRATIONS] {platform_id} returned but not listening"
                    )
            except Exception as e:
                logger.warning(f"[INTEGRATIONS] Failed to start {platform_id}: {e}")

        self._running = True
        if started:
            logger.info(f"[INTEGRATIONS] Active channels: {started}")
        else:
            logger.info("[INTEGRATIONS] No external channels started")

    async def reset_platform(self, platform_id: str) -> None:
        """Stop (if listening) and discard a platform's client.

        Forces the next ``get_client()``/``start_platform()`` to rebuild the
        client from disk. Called when an account is connected or disconnected so
        a cached in-memory credential can't survive an account switch
        (issue #314).
        """
        client = self._active_clients.pop(platform_id, None)
        if client is not None:
            try:
                await client.stop_listening()
            except Exception as e:
                logger.warning(
                    f"[INTEGRATIONS] Error stopping {platform_id} during reset: {e}"
                )
        invalidate_client(platform_id)

    async def start_platform(self, platform_id: str) -> bool:
        """Start listening on a specific platform (e.g. just after it was connected).

        Always discards any existing client first and rebuilds from disk. This
        runs right after an account is (re)connected, so a lingering client
        instance may still hold the previous account's cached credential —
        reusing it would keep routing to the wrong account until restart
        (issue #314).
        """
        if self._is_excluded(platform_id):
            return False

        await self.reset_platform(platform_id)

        autoload_integrations()
        client = get_client(platform_id)
        if (
            client is None
            or not client.supports_listening
            or not client.has_credentials()
        ):
            return False

        try:
            await client.start_listening(self._handle_platform_message)
            if client.is_listening:
                self._active_clients[platform_id] = client
                logger.info(
                    f"[INTEGRATIONS] Started listening on {platform_id} (post-connect)"
                )
                return True
        except Exception as e:
            logger.warning(f"[INTEGRATIONS] Failed to start {platform_id}: {e}")
        return False

    async def stop_platform(self, platform_id: str) -> bool:
        client = self._active_clients.get(platform_id)
        if client is None:
            return False
        try:
            await client.stop_listening()
        except Exception as e:
            logger.warning(f"[INTEGRATIONS] Error stopping {platform_id}: {e}")
        del self._active_clients[platform_id]
        return True

    async def stop(self) -> None:
        if not self._running:
            return
        logger.info("[INTEGRATIONS] Stopping external communications manager...")
        for platform_id, client in list(self._active_clients.items()):
            try:
                await client.stop_listening()
            except Exception as e:
                logger.warning(f"[INTEGRATIONS] Error stopping {platform_id}: {e}")
        self._active_clients.clear()
        self._running = False

    async def reload(self) -> Dict[str, Any]:
        """Stop platforms whose creds disappeared, start ones whose appeared."""
        result: Dict[str, Any] = {
            "success": True,
            "stopped": [],
            "started": [],
            "message": "",
        }
        try:
            autoload_integrations()
            currently_active = set(self._active_clients.keys())
            all_clients = get_all_clients()

            should_be_active = {
                pid
                for pid, c in all_clients.items()
                if c.supports_listening
                and c.has_credentials()
                and not self._is_excluded(pid)
            }

            for pid in currently_active - should_be_active:
                try:
                    client = self._active_clients.get(pid)
                    if client:
                        await client.stop_listening()
                        del self._active_clients[pid]
                        result["stopped"].append(pid)
                except Exception as e:
                    logger.warning(f"[INTEGRATIONS] Error stopping {pid}: {e}")

            for pid in should_be_active - currently_active:
                try:
                    client = all_clients.get(pid)
                    if client:
                        await client.start_listening(self._handle_platform_message)
                        if client.is_listening:
                            self._active_clients[pid] = client
                            result["started"].append(pid)
                except Exception as e:
                    logger.warning(f"[INTEGRATIONS] Error starting {pid}: {e}")

            result["message"] = (
                f"Reload complete. Stopped: {len(result['stopped'])}, "
                f"Started: {len(result['started'])}, "
                f"Active: {len(self._active_clients)}"
            )
        except Exception as e:
            result["success"] = False
            result["message"] = f"Reload failed: {e}"
            logger.error(f"[INTEGRATIONS] Reload failed: {e}")
        return result

    async def _handle_platform_message(self, msg: PlatformMessage) -> None:
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
        logger.info(
            f"[INTEGRATIONS] Received from {payload['source']}: "
            f"{payload['contactName']}: {payload['messageBody'][:50]}..."
        )
        try:
            await self._on_message(payload)
        except Exception as e:
            logger.error(f"[INTEGRATIONS] Error in on_message callback: {e}")

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "channels": {
                name: {"running": client.is_listening}
                for name, client in self._active_clients.items()
            },
        }


_manager: Optional[ExternalCommsManager] = None


def get_external_comms_manager() -> Optional[ExternalCommsManager]:
    return _manager


async def initialize_manager(
    *,
    on_message: MessageCallback,
    auto_start: bool = True,
    exclude_platforms: Optional[List[str]] = None,
) -> ExternalCommsManager:
    """Create the manager and (by default) start listeners.

    ``exclude_platforms``: platform ids this manager must never listen on
    (their listening is owned by the ListenerManager). Actions and
    account handling for those platforms are unaffected.
    """
    global _manager
    ConfigStore.on_message = on_message
    _manager = ExternalCommsManager(on_message, exclude_platforms=exclude_platforms)
    if auto_start:
        await _manager.start()
    return _manager
