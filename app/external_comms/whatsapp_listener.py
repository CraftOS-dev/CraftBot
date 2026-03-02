# -*- coding: utf-8 -*-
"""
app.external_comms.whatsapp_listener

WhatsApp Web message listener for CraftBot.
Uses the existing WhatsApp Web infrastructure from agent_core.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# Type alias for message callback
MessageCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]


class WhatsAppWebListener:
    """
    Listens for incoming WhatsApp Web messages.

    Uses the existing WhatsApp Web infrastructure from agent_core
    to watch for new messages and forward them to the agent.
    """

    POLL_INTERVAL = 10  # seconds between polling for new messages
    RETRY_DELAY = 5  # seconds after error

    def __init__(
        self,
        session_id: str,
        callback: MessageCallback,
    ):
        """
        Initialize WhatsApp Web listener.

        Args:
            session_id: WhatsApp Web session ID (from credentials).
            callback: Async callback to invoke when a message is received.
        """
        self._session_id = session_id
        self._callback = callback
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._last_processed: Dict[str, int] = {}  # Track processed messages per chat

    async def start(self) -> None:
        """Start listening for messages."""
        if self._running:
            return

        # Verify session exists
        if not await self._verify_session():
            logger.error("[WHATSAPP] Session not found or not connected")
            return

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"[WHATSAPP] Listener started for session: {self._session_id}")

    async def stop(self) -> None:
        """Stop listening."""
        if not self._running:
            return

        self._running = False

        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        logger.info("[WHATSAPP] Listener stopped")

    async def _verify_session(self) -> bool:
        """Verify WhatsApp Web session is connected."""
        try:
            from agent_core.external_libraries.whatsapp.external_app_library import (
                WhatsAppAppLibrary,
            )

            # Check if session exists in credentials
            credential = WhatsAppAppLibrary.get_credential(session_id=self._session_id)
            if not credential:
                logger.warning(f"[WHATSAPP] No credential found for session: {self._session_id}")
                return False

            logger.info(f"[WHATSAPP] Session verified: {self._session_id}")
            return True

        except ImportError:
            logger.error("[WHATSAPP] WhatsApp external library not available")
            return False
        except Exception as e:
            logger.error(f"[WHATSAPP] Error verifying session: {e}")
            return False

    async def _poll_loop(self) -> None:
        """Main polling loop for checking new messages."""
        while self._running:
            try:
                await self._check_for_messages()
                await asyncio.sleep(self.POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WHATSAPP] Poll error: {e}")
                await asyncio.sleep(self.RETRY_DELAY)

    async def _check_for_messages(self) -> None:
        """
        Check for new messages across all chats.

        This uses the WhatsApp Web helpers to fetch unread messages.
        """
        try:
            from agent_core.external_libraries.whatsapp.helpers.whatsapp_web_helpers import (
                get_whatsapp_web_unread_chats,
                get_whatsapp_web_chat_messages,
            )

            # Get chats with unread messages
            unread_result = await get_whatsapp_web_unread_chats(
                session_id=self._session_id
            )

            if unread_result.get("status") != "success":
                return

            unread_chats = unread_result.get("unread_chats", [])

            for chat in unread_chats:
                chat_id = chat.get("jid", "")
                unread_count = chat.get("unread_count", 0)

                if not chat_id or unread_count == 0:
                    continue

                # Fetch recent messages for this chat
                messages_result = await get_whatsapp_web_chat_messages(
                    session_id=self._session_id,
                    jid=chat_id,
                    limit=unread_count + 5,  # Get a few extra for context
                )

                if messages_result.get("status") != "success":
                    continue

                messages = messages_result.get("messages", [])

                # Process new messages (those we haven't seen)
                last_processed = self._last_processed.get(chat_id, 0)

                for msg in messages:
                    msg_timestamp = msg.get("timestamp", 0)

                    # Skip already processed messages
                    if msg_timestamp <= last_processed:
                        continue

                    # Skip outgoing messages (from us)
                    if msg.get("fromMe", False):
                        continue

                    # Process this message
                    await self._process_message(msg, chat)

                    # Update last processed
                    if msg_timestamp > self._last_processed.get(chat_id, 0):
                        self._last_processed[chat_id] = msg_timestamp

        except ImportError:
            logger.warning("[WHATSAPP] WhatsApp Web helpers not available")
        except Exception as e:
            logger.error(f"[WHATSAPP] Error checking messages: {e}")

    async def _process_message(
        self,
        message: Dict[str, Any],
        chat: Dict[str, Any],
    ) -> None:
        """
        Process a single WhatsApp message.

        Args:
            message: WhatsApp message object.
            chat: Chat info object.
        """
        # Extract message details
        sender = message.get("from", "")
        text = message.get("body", "")
        msg_type = message.get("type", "chat")

        # Skip non-text messages for now
        if msg_type not in ("chat", "text"):
            logger.debug(f"[WHATSAPP] Skipping non-text message type: {msg_type}")
            return

        # Skip empty messages
        if not text:
            return

        # Get contact name
        contact_name = message.get("notifyName", "") or chat.get("name", "") or sender

        # Build standardized payload
        payload = {
            "source": "WhatsApp Web",
            "integrationType": "whatsapp_web",
            "contactId": sender,
            "contactName": contact_name,
            "messageBody": text,
            "chatId": chat.get("jid", ""),
            "chatName": chat.get("name", ""),
            "messageId": message.get("id", {}).get("id", ""),
            "timestamp": message.get("timestamp"),
            "isGroup": "@g.us" in chat.get("jid", ""),
        }

        logger.debug(f"[WHATSAPP] Received message: {payload}")

        # Dispatch to callback
        await self._callback(payload)

    def get_status(self) -> Dict[str, Any]:
        """Get listener status."""
        return {
            "running": self._running,
            "session_id": self._session_id,
            "chats_tracked": len(self._last_processed),
        }
