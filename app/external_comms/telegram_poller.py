# -*- coding: utf-8 -*-
"""
app.external_comms.telegram_poller

Telegram Bot API polling for CraftBot.
Polls the Telegram Bot API directly without requiring a server.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

try:
    import httpx
except ImportError:
    httpx = None

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# Type alias for message callback
MessageCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]


class TelegramPoller:
    """
    Polls Telegram Bot API for incoming messages.

    Uses long-polling (getUpdates with timeout) for efficiency.
    No external server required - polls directly from CraftBot.
    """

    POLL_TIMEOUT = 30  # seconds
    RETRY_DELAY = 5  # seconds after error
    API_BASE = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: str,
        callback: MessageCallback,
    ):
        """
        Initialize Telegram poller.

        Args:
            bot_token: Telegram bot token from @BotFather.
            callback: Async callback to invoke when a message is received.
        """
        if httpx is None:
            raise ImportError("httpx is required for Telegram polling")

        self._bot_token = bot_token
        self._callback = callback
        self._offset = 0
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._bot_info: Optional[Dict[str, Any]] = None

    async def start(self) -> None:
        """Start polling for updates."""
        if self._running:
            return

        # Verify bot token
        if not await self._verify_bot():
            logger.error("[TELEGRAM] Invalid bot token")
            return

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"[TELEGRAM] Poller started for @{self._bot_info.get('username', 'unknown')}")

    async def stop(self) -> None:
        """Stop polling."""
        if not self._running:
            return

        self._running = False

        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        logger.info("[TELEGRAM] Poller stopped")

    async def _verify_bot(self) -> bool:
        """Verify bot token and get bot info."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.API_BASE}/bot{self._bot_token}/getMe"
                )
                data = resp.json()

                if data.get("ok"):
                    self._bot_info = data.get("result", {})
                    logger.info(
                        f"[TELEGRAM] Bot verified: @{self._bot_info.get('username')} "
                        f"(ID: {self._bot_info.get('id')})"
                    )
                    return True
                else:
                    logger.error(f"[TELEGRAM] Bot verification failed: {data}")
                    return False

        except Exception as e:
            logger.error(f"[TELEGRAM] Error verifying bot: {e}")
            return False

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    await self._process_update(update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TELEGRAM] Poll error: {e}")
                await asyncio.sleep(self.RETRY_DELAY)

    async def _get_updates(self) -> List[Dict[str, Any]]:
        """
        Fetch updates from Telegram using long-polling.

        Returns:
            List of update objects.
        """
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.POLL_TIMEOUT + 10)
            ) as client:
                resp = await client.get(
                    f"{self.API_BASE}/bot{self._bot_token}/getUpdates",
                    params={
                        "offset": self._offset,
                        "timeout": self.POLL_TIMEOUT,
                        "allowed_updates": ["message"],  # Only fetch messages
                    },
                )
                data = resp.json()

                if data.get("ok"):
                    return data.get("result", [])
                else:
                    logger.warning(f"[TELEGRAM] getUpdates failed: {data}")
                    return []

        except httpx.TimeoutException:
            # Normal timeout - just return empty
            return []
        except Exception as e:
            logger.error(f"[TELEGRAM] Error getting updates: {e}")
            raise

    async def _process_update(self, update: Dict[str, Any]) -> None:
        """
        Process a single update from Telegram.

        Args:
            update: Telegram update object.
        """
        update_id = update.get("update_id", 0)

        # Update offset to acknowledge this update
        self._offset = update_id + 1

        # Handle message updates
        message = update.get("message")
        if not message:
            logger.debug(f"[TELEGRAM] Skipping non-message update: {update_id}")
            return

        # Extract message details
        from_user = message.get("from", {})
        chat = message.get("chat", {})
        text = message.get("text", "")

        # Skip empty messages
        if not text:
            return

        # Build standardized payload
        contact_name = from_user.get("first_name", "")
        if from_user.get("last_name"):
            contact_name += f" {from_user.get('last_name')}"
        if from_user.get("username"):
            contact_name += f" (@{from_user.get('username')})"

        payload = {
            "source": "Telegram",
            "integrationType": "telegram_bot",
            "contactId": str(from_user.get("id", "")),
            "contactName": contact_name or str(from_user.get("id", "unknown")),
            "messageBody": text,
            "chatId": str(chat.get("id", "")),
            "chatType": chat.get("type", "private"),
            "messageId": str(message.get("message_id", "")),
            "timestamp": message.get("date"),
        }

        logger.debug(f"[TELEGRAM] Received message: {payload}")

        # Dispatch to callback
        await self._callback(payload)

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = None,
    ) -> bool:
        """
        Send a message to a chat.

        Args:
            chat_id: Target chat ID.
            text: Message text.
            parse_mode: Optional parse mode ("HTML", "Markdown", "MarkdownV2").

        Returns:
            True if message was sent successfully.
        """
        try:
            params = {
                "chat_id": chat_id,
                "text": text,
            }
            if parse_mode:
                params["parse_mode"] = parse_mode

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.API_BASE}/bot{self._bot_token}/sendMessage",
                    json=params,
                )
                data = resp.json()

                if data.get("ok"):
                    logger.debug(f"[TELEGRAM] Message sent to {chat_id}")
                    return True
                else:
                    logger.error(f"[TELEGRAM] Failed to send message: {data}")
                    return False

        except Exception as e:
            logger.error(f"[TELEGRAM] Error sending message: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get poller status."""
        return {
            "running": self._running,
            "offset": self._offset,
            "bot_info": self._bot_info,
        }
