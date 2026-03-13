# -*- coding: utf-8 -*-
"""
app.external_comms.platforms.whatsapp_web

WhatsApp Web platform client — uses a Node.js whatsapp-web.js bridge subprocess
for event-driven messaging (replaces the old Playwright polling approach).

The bridge subprocess is managed by ``WhatsAppBridge`` in
``app.external_comms.platforms.whatsapp_bridge.client``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.external_comms.base import BasePlatformClient, PlatformMessage, MessageCallback
from app.external_comms.credentials import has_credential, load_credential, save_credential, remove_credential
from app.external_comms.registry import register_client

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


CREDENTIAL_FILE = "whatsapp_web.json"


@dataclass
class WhatsAppWebCredential:
    session_id: str = ""
    owner_phone: str = ""
    owner_name: str = ""


# ---------------------------------------------------------------------------
# Platform client
# ---------------------------------------------------------------------------

@register_client
class WhatsAppWebClient(BasePlatformClient):
    """
    WhatsApp Web client backed by a whatsapp-web.js Node.js bridge subprocess.

    All messaging and chat operations are delegated to the bridge via
    JSON-lines IPC (stdin/stdout).
    """

    PLATFORM_ID = "whatsapp_web"

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[WhatsAppWebCredential] = None
        self._bridge = None  # WhatsAppBridge instance (lazy import)
        self._seen_ids: set = set()  # dedup incoming message IDs
        self._known_groups: set = set()
        self._agent_sent_ids: set = set()  # track IDs of messages sent by the agent

    @property
    def _agent_prefix(self) -> str:
        """Return prefix like '[AgentName] ' using the configured agent name."""
        try:
            from app.onboarding import onboarding_manager
            name = onboarding_manager.state.agent_name or "AGENT"
        except Exception:
            name = "AGENT"
        return f"[{name}] "

    # ------------------------------------------------------------------
    # Credential helpers
    # ------------------------------------------------------------------

    def has_credentials(self) -> bool:
        return has_credential(CREDENTIAL_FILE)

    def _load(self) -> WhatsAppWebCredential:
        if self._cred is None:
            self._cred = load_credential(CREDENTIAL_FILE, WhatsAppWebCredential)
        if self._cred is None:
            raise RuntimeError("No WhatsApp Web credentials found. Please log in first.")
        return self._cred

    @property
    def owner_phone(self) -> str:
        """Return the stored owner phone number, or empty string."""
        return self._load().owner_phone

    # ------------------------------------------------------------------
    # Bridge access
    # ------------------------------------------------------------------

    def _get_bridge(self):
        """Lazily import and return the WhatsAppBridge singleton."""
        if self._bridge is None:
            from app.external_comms.platforms.whatsapp_bridge.client import get_whatsapp_bridge
            self._bridge = get_whatsapp_bridge()
        return self._bridge

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the bridge and verify it becomes ready."""
        bridge = self._get_bridge()
        if not bridge.is_running:
            await bridge.start()
        if not bridge.is_ready:
            ready = await bridge.wait_for_ready(timeout=120.0)
            if not ready:
                raise RuntimeError("WhatsApp bridge did not become ready within timeout")
        self._connected = True

    async def disconnect(self) -> None:
        """Stop listening and the bridge subprocess."""
        await super().disconnect()
        bridge = self._get_bridge()
        if bridge.is_running:
            await bridge.stop()

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    # Generic terms the LLM may use to mean "send to the device owner"
    _OWNER_ALIASES = {"user", "owner", "me", "self"}

    def _resolve_recipient(self, recipient: str) -> str:
        """If *recipient* is a generic alias like 'user', replace with stored owner phone."""
        if recipient.strip().lower() in self._OWNER_ALIASES:
            phone = self.owner_phone
            if phone:
                logger.info(f"[WhatsApp Web] Resolved '{recipient}' to owner phone {phone}")
                return phone
            logger.warning(f"[WhatsApp Web] Cannot resolve '{recipient}' — owner_phone not stored in credential")
        return recipient

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """Send a text message via the bridge. Prepends [AGENT] prefix."""
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"status": "error", "error": "Bridge not ready"}
        resolved = self._resolve_recipient(recipient)
        prefixed_text = f"{self._agent_prefix}{text}"
        result = await bridge.send_message(to=resolved, text=prefixed_text)
        # Track sent message ID to filter echo in _handle_sent_message
        msg_id = result.get("message_id")
        if msg_id:
            self._agent_sent_ids.add(msg_id)
        return {"status": "success" if result.get("success") else "error", **result}

    async def send_media(
        self,
        recipient: str,
        media_path: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send media is not yet supported via the bridge — send caption as text."""
        # TODO: Add media support to bridge.js
        if caption:
            return await self.send_message(recipient, f"[Media: {media_path}]\n{caption}")
        return {"status": "error", "error": "Media sending not yet supported via bridge"}

    # ------------------------------------------------------------------
    # Chat / contact queries
    # ------------------------------------------------------------------

    async def get_chat_messages(
        self,
        phone_number: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Retrieve recent messages from a specific chat."""
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"success": False, "error": "Bridge not ready"}
        result = await bridge.get_chat_messages(chat_id=phone_number, limit=limit)
        return {"status": "success" if result.get("success") else "error", **result}

    async def get_unread_chats(self) -> Dict[str, Any]:
        """Return a list of chats with unread messages."""
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"success": False, "error": "Bridge not ready"}
        result = await bridge.get_unread_chats()
        return {"status": "success" if result.get("success") else "error", **result}

    async def search_contact(self, name: str) -> Dict[str, Any]:
        """Search contacts by name."""
        bridge = self._get_bridge()
        if not bridge.is_ready:
            return {"success": False, "error": "Bridge not ready"}
        result = await bridge.search_contact(name=name)
        return {"status": "success" if result.get("success") else "error", **result}

    async def get_session_status(self) -> Optional[Dict[str, Any]]:
        """Get bridge/client status."""
        bridge = self._get_bridge()
        if not bridge.is_running:
            return {"status": "disconnected", "ready": False}
        try:
            result = await bridge.get_status()
            return {"status": "connected" if result.get("ready") else "waiting", **result}
        except Exception:
            return {"status": "disconnected", "ready": False}

    # ------------------------------------------------------------------
    # Listening (event-driven via bridge callback)
    # ------------------------------------------------------------------

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback: MessageCallback) -> None:
        """Start the bridge and register for incoming message events."""
        if self._listening:
            return

        # Invalidate cached credential so we pick up the latest
        self._cred = None

        bridge = self._get_bridge()

        # Always restart the bridge fresh so its reader tasks run on the
        # current event loop.  The login flow may have started the bridge on
        # a background thread whose event loop is now dead.  whatsapp-web.js
        # LocalAuth persists the session, so the restart will auto-authenticate.
        if bridge.is_running:
            logger.info("[WhatsApp Web] Restarting bridge on current event loop...")
            await bridge.stop()

        await bridge.start()

        # Register event callback
        bridge.set_event_callback(self._on_bridge_event)

        # Wait for ready or QR — if QR is needed the user must login first
        logger.info("[WhatsApp Web] Waiting for bridge to become ready...")
        event_type, _ = await bridge.wait_for_qr_or_ready(timeout=120.0)

        if event_type == "qr":
            # Not authenticated — stop the bridge and tell user to login
            logger.warning("[WhatsApp Web] Bridge requires QR scan — user must run /whatsapp login first")
            bridge.set_event_callback(None)
            await bridge.stop()
            raise RuntimeError("WhatsApp not authenticated. Please run /whatsapp login to scan the QR code first.")

        if event_type != "ready":
            bridge.set_event_callback(None)
            raise RuntimeError("WhatsApp bridge did not become ready — timed out")

        # Update credential with owner info from the bridge
        if bridge.owner_phone or bridge.owner_name:
            cred = self._load()
            if cred.owner_phone != bridge.owner_phone or cred.owner_name != bridge.owner_name:
                updated = WhatsAppWebCredential(
                    session_id=cred.session_id,
                    owner_phone=bridge.owner_phone or cred.owner_phone,
                    owner_name=bridge.owner_name or cred.owner_name,
                )
                save_credential(CREDENTIAL_FILE, updated)
                self._cred = updated
                logger.info(
                    f"[WhatsApp Web] Updated credential: phone={updated.owner_phone}, "
                    f"name={updated.owner_name}"
                )

        self._message_callback = callback
        self._listening = True
        self._connected = True
        logger.info(
            f"[WhatsApp Web] Listener started — connected as "
            f"+{bridge.owner_phone} ({bridge.owner_name})"
        )

    async def stop_listening(self) -> None:
        """Stop listening for messages."""
        if not self._listening:
            return

        self._listening = False

        bridge = self._get_bridge()
        bridge.set_event_callback(None)

        logger.info("[WhatsApp Web] Listener stopped")

    # -- Bridge event handler ------------------------------------------------

    async def _on_bridge_event(self, event: str, data: Dict[str, Any]) -> None:
        """Handle events from the bridge subprocess."""
        if event == "message":
            await self._handle_incoming_message(data)
        elif event == "message_sent":
            await self._handle_sent_message(data)
        elif event == "disconnected":
            self._connected = False
            logger.warning(f"[WhatsApp Web] Disconnected: {data.get('reason', 'unknown')}")
        elif event == "ready":
            self._connected = True

    async def _handle_incoming_message(self, data: Dict[str, Any]) -> None:
        """Process an incoming message event from the bridge."""
        if not self._listening or not self._message_callback:
            return

        msg_id = data.get("id", "")
        if msg_id in self._seen_ids:
            return
        self._seen_ids.add(msg_id)

        # Skip messages from self (handled by message_sent event)
        if data.get("from_me", False):
            return

        body = data.get("body", "")
        if not body:
            return

        chat = data.get("chat", {})
        contact = data.get("contact", {})
        is_group = chat.get("is_group", False)
        is_muted = chat.get("is_muted", False)

        # Track known groups
        chat_name = chat.get("name", "")
        if is_group:
            self._known_groups.add(chat_name)

        # Skip muted group chats
        if is_muted and is_group:
            logger.debug(f"[WhatsApp Web] Skipping muted group: {chat_name}")
            return

        # In group chats, only process messages that @mention the user
        if is_group:
            if not self._is_mention_for_me(body):
                return

        sender_name = contact.get("name", "") or chat_name
        sender_id = data.get("from", "")
        timestamp = data.get("timestamp")

        ts: Optional[datetime] = None
        if timestamp:
            try:
                ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            except Exception:
                ts = datetime.now(tz=timezone.utc)

        platform_msg = PlatformMessage(
            platform=self.PLATFORM_ID,
            sender_id=sender_id,
            sender_name=sender_name,
            text=body,
            channel_id=chat.get("id", ""),
            channel_name=chat_name,
            message_id=msg_id,
            timestamp=ts,
            raw={
                "source": "WhatsApp Web",
                "integrationType": "whatsapp_web",
                "is_self_message": False,
                "is_group": is_group,
                "contactId": sender_id,
                "contactName": sender_name,
                "messageBody": body,
                "chatId": chat.get("id", ""),
                "chatName": chat_name,
                "timestamp": str(timestamp or ""),
            },
        )

        await self._message_callback(platform_msg)
        logger.info(f"[WhatsApp Web] Dispatched message from {sender_name} in {chat_name}: {body[:50]}...")

    async def _handle_sent_message(self, data: Dict[str, Any]) -> None:
        """Process a message sent by the user from another device (self-chat or outgoing)."""
        if not self._listening or not self._message_callback:
            return

        # Only dispatch self-chat messages (messages to yourself)
        if not data.get("is_self_chat", False):
            return

        msg_id = data.get("id", "")
        if msg_id in self._seen_ids:
            return
        self._seen_ids.add(msg_id)

        # Skip messages sent by the agent (prevents echo loop)
        if msg_id and msg_id in self._agent_sent_ids:
            self._agent_sent_ids.discard(msg_id)
            logger.debug(f"[WhatsApp Web] Skipping agent-sent message (ID match): {msg_id}")
            return

        body = data.get("body", "")
        if not body:
            return

        # Also skip by prefix in case of race condition (ID not yet tracked)
        if body.startswith(self._agent_prefix):
            logger.debug(f"[WhatsApp Web] Skipping agent-sent message (prefix match): {body[:50]}...")
            return

        chat = data.get("chat", {})
        chat_name = chat.get("name", "")
        timestamp = data.get("timestamp")

        ts: Optional[datetime] = None
        if timestamp:
            try:
                ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            except Exception:
                ts = datetime.now(tz=timezone.utc)

        platform_msg = PlatformMessage(
            platform=self.PLATFORM_ID,
            sender_id=data.get("from", ""),
            sender_name=chat_name or "Self",
            text=body,
            channel_id=chat.get("id", ""),
            channel_name=chat_name,
            message_id=msg_id,
            timestamp=ts,
            raw={
                "source": "WhatsApp Web",
                "integrationType": "whatsapp_web",
                "is_self_message": True,
                "is_group": False,
                "contactId": data.get("from", ""),
                "contactName": chat_name or "Self",
                "messageBody": body,
                "chatId": chat.get("id", ""),
                "chatName": chat_name,
                "timestamp": str(timestamp or ""),
            },
        )

        await self._message_callback(platform_msg)
        logger.info(f"[WhatsApp Web] Dispatched self-message: {body[:50]}...")

    # -- @mention helper ---------------------------------------------------

    def _is_mention_for_me(self, text: str) -> bool:
        """Check whether *text* contains an @mention directed at the logged-in user."""
        if "@" not in text:
            return False

        text_lower = text.lower()

        # Use owner_name from bridge
        bridge = self._get_bridge()
        own_name = bridge.owner_name if bridge else ""

        if own_name:
            own_lower = own_name.lower()
            if f"@{own_lower}" in text_lower:
                return True
            first_name = own_lower.split()[0] if " " in own_lower else ""
            if first_name and f"@{first_name}" in text_lower:
                return True
            return False

        # Fallback: no own name known — treat any @mention as potentially ours
        return True
