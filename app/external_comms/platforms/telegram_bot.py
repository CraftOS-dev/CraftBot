# -*- coding: utf-8 -*-
"""Telegram Bot API client — direct HTTP via httpx."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import httpx

from app.external_comms.base import BasePlatformClient, PlatformMessage, MessageCallback
from app.external_comms.credentials import has_credential, load_credential, save_credential, remove_credential
from app.external_comms.registry import register_client

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

TELEGRAM_API_BASE = "https://api.telegram.org"
CREDENTIAL_FILE = "telegram_bot.json"

POLL_TIMEOUT = 30       # seconds for long-polling
RETRY_DELAY = 5         # seconds to wait after a poll error


@dataclass
class TelegramBotCredential:
    bot_token: str = ""
    bot_username: str = ""


@register_client
class TelegramBotClient(BasePlatformClient):
    """Telegram Bot API platform client with long-polling support."""

    PLATFORM_ID = "telegram_bot"

    def __init__(self):
        super().__init__()
        self._cred: Optional[TelegramBotCredential] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_offset: int = 0
        self._bot_info: Optional[Dict[str, Any]] = None
        self._catchup_done: bool = False

    # ------------------------------------------------------------------
    # Credential helpers
    # ------------------------------------------------------------------

    def has_credentials(self) -> bool:
        if has_credential(CREDENTIAL_FILE):
            return True
        # Auto-save shared bot credentials from env vars if available
        try:
            from app.config import TELEGRAM_SHARED_BOT_TOKEN, TELEGRAM_SHARED_BOT_USERNAME
            if TELEGRAM_SHARED_BOT_TOKEN:
                save_credential(CREDENTIAL_FILE, TelegramBotCredential(
                    bot_token=TELEGRAM_SHARED_BOT_TOKEN,
                    bot_username=TELEGRAM_SHARED_BOT_USERNAME or "",
                ))
                logger.info("[TELEGRAM_BOT] Auto-saved shared bot credentials from env vars")
                return True
        except Exception:
            pass
        return False

    def _load(self) -> TelegramBotCredential:
        if self._cred is None:
            self._cred = load_credential(CREDENTIAL_FILE, TelegramBotCredential)
        if self._cred is None:
            raise RuntimeError("No Telegram Bot credentials. Use /telegram_bot login first.")
        return self._cred

    def _api_url(self, method: str) -> str:
        cred = self._load()
        return f"{TELEGRAM_API_BASE}/bot{cred.bot_token}/{method}"

    # ------------------------------------------------------------------
    # BasePlatformClient overrides
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """Send a text message to a chat.

        Args:
            recipient: Chat ID or username (@channel).
            text: Message text (up to 4096 characters).
            **kwargs: Optional ``parse_mode``, ``reply_to_message_id``,
                      ``disable_notification``.

        Returns:
            API response with sent message or error.
        """
        parse_mode: Optional[str] = kwargs.get("parse_mode")
        reply_to_message_id: Optional[int] = kwargs.get("reply_to_message_id")
        disable_notification: bool = kwargs.get("disable_notification", False)

        payload: Dict[str, Any] = {
            "chat_id": recipient,
            "text": text,
        }

        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if disable_notification:
            payload["disable_notification"] = True

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self._api_url("sendMessage"), json=payload)
            data = resp.json()

        if not data.get("ok"):
            return {"error": data.get("description", "Unknown error"), "details": data}

        return data

    # ------------------------------------------------------------------
    # Listening (long-polling)
    # ------------------------------------------------------------------

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback: MessageCallback) -> None:
        """Start long-polling for incoming messages.

        Args:
            callback: Async callback invoked with a ``PlatformMessage`` for
                      every incoming text message.
        """
        if self._listening:
            return

        self._message_callback = callback

        # Verify bot token before starting the loop
        info = await self.get_me()
        if "error" in info:
            logger.error(f"[TELEGRAM_BOT] Invalid bot token: {info}")
            raise RuntimeError(f"Invalid bot token: {info.get('error', 'unknown error')}")
        self._bot_info = info.get("result", {})

        self._listening = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            f"[TELEGRAM_BOT] Poller started for @{self._bot_info.get('username', 'unknown')}"
        )

    async def stop_listening(self) -> None:
        """Stop the long-polling loop."""
        if not self._listening:
            return

        self._listening = False

        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        self._poll_task = None
        logger.info("[TELEGRAM_BOT] Poller stopped")

    async def _poll_loop(self) -> None:
        """Main long-polling loop with initial catchup."""
        # Catchup: consume all pending updates without dispatching
        logger.info("[TELEGRAM_BOT] Running initial catchup...")
        try:
            catchup_resp = await self._poll_updates()
            catchup_updates = catchup_resp.get("result", [])
            for update in catchup_updates:
                # Just advance the offset without dispatching
                update_id = update.get("update_id", 0)
                self._poll_offset = update_id + 1
            self._catchup_done = True
            logger.info(f"[TELEGRAM_BOT] Catchup complete — {len(catchup_updates)} pending update(s) skipped")
        except Exception as e:
            logger.error(f"[TELEGRAM_BOT] Catchup error: {e}")
            self._catchup_done = True  # proceed anyway

        while self._listening:
            try:
                updates_resp = await self._poll_updates()
                updates = updates_resp.get("result", [])
                for update in updates:
                    await self._process_update(update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TELEGRAM_BOT] Poll error: {e}")
                await asyncio.sleep(RETRY_DELAY)

    async def _poll_updates(self) -> Dict[str, Any]:
        """Fetch updates from Telegram using long-polling."""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(POLL_TIMEOUT + 10)
            ) as client:
                resp = await client.get(
                    self._api_url("getUpdates"),
                    params={
                        "offset": self._poll_offset,
                        "timeout": POLL_TIMEOUT,
                        "allowed_updates": ["message"],
                    },
                )
                data = resp.json()

                if data.get("ok"):
                    return data
                else:
                    logger.warning(f"[TELEGRAM_BOT] getUpdates failed: {data}")
                    return {"result": []}

        except httpx.TimeoutException:
            return {"result": []}
        except Exception as e:
            logger.error(f"[TELEGRAM_BOT] Error getting updates: {e}")
            raise

    async def _process_update(self, update: Dict[str, Any]) -> None:
        """Process a single Telegram update and dispatch to callback."""
        update_id = update.get("update_id", 0)
        self._poll_offset = update_id + 1

        message = update.get("message")
        if not message:
            return

        text = message.get("text", "")
        if not text:
            return

        from_user = message.get("from", {})
        chat = message.get("chat", {})

        # Build sender display name
        sender_name = from_user.get("first_name", "")
        if from_user.get("last_name"):
            sender_name += f" {from_user['last_name']}"
        if from_user.get("username"):
            sender_name += f" (@{from_user['username']})"

        ts = None
        if message.get("date"):
            try:
                ts = datetime.fromtimestamp(message["date"], tz=timezone.utc)
            except Exception:
                pass

        platform_msg = PlatformMessage(
            platform="telegram_bot",
            sender_id=str(from_user.get("id", "")),
            sender_name=sender_name or str(from_user.get("id", "unknown")),
            text=text,
            channel_id=str(chat.get("id", "")),
            channel_name=chat.get("title", chat.get("first_name", "")),
            message_id=str(message.get("message_id", "")),
            timestamp=ts,
            raw=update,
        )

        if self._message_callback:
            await self._message_callback(platform_msg)

    # ------------------------------------------------------------------
    # Bot API methods
    # ------------------------------------------------------------------

    async def get_me(self) -> Dict[str, Any]:
        """Get basic information about the bot.

        Returns:
            API response with bot info or error.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(self._api_url("getMe"))
            data = resp.json()

        if not data.get("ok"):
            return {"error": data.get("description", "Unknown error"), "details": data}

        return data

    async def send_photo(
        self,
        chat_id: Union[int, str],
        photo: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a photo to a chat.

        Args:
            chat_id: Chat ID or username.
            photo: File ID, URL, or file path.
            caption: Photo caption.
            parse_mode: Caption parse mode.

        Returns:
            API response with sent message or error.
        """
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "photo": photo,
        }

        if caption:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self._api_url("sendPhoto"), json=payload)
            data = resp.json()

        if not data.get("ok"):
            return {"error": data.get("description", "Unknown error"), "details": data}

        return data

    async def send_document(
        self,
        chat_id: Union[int, str],
        document: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a document to a chat.

        Args:
            chat_id: Chat ID or username.
            document: File ID, URL, or file path.
            caption: Document caption.
            parse_mode: Caption parse mode.

        Returns:
            API response with sent message or error.
        """
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "document": document,
        }

        if caption:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self._api_url("sendDocument"), json=payload)
            data = resp.json()

        if not data.get("ok"):
            return {"error": data.get("description", "Unknown error"), "details": data}

        return data

    async def get_updates(
        self,
        offset: Optional[int] = None,
        limit: int = 100,
        timeout: int = 0,
        allowed_updates: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get incoming updates using long polling.

        Args:
            offset: Identifier of the first update to return.
            limit: Maximum number of updates (1-100).
            timeout: Timeout in seconds for long polling.
            allowed_updates: List of update types to receive.

        Returns:
            API response with updates or error.
        """
        payload: Dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
        }

        if offset is not None:
            payload["offset"] = offset
        if allowed_updates:
            payload["allowed_updates"] = allowed_updates

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout + 10)
        ) as client:
            resp = await client.post(self._api_url("getUpdates"), json=payload)
            data = resp.json()

        if not data.get("ok"):
            return {"error": data.get("description", "Unknown error"), "details": data}

        return data

    async def get_chat(
        self,
        chat_id: Union[int, str],
    ) -> Dict[str, Any]:
        """Get up-to-date information about a chat.

        Args:
            chat_id: Chat ID or username.

        Returns:
            API response with chat info or error.
        """
        payload = {"chat_id": chat_id}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self._api_url("getChat"), json=payload)
            data = resp.json()

        if not data.get("ok"):
            return {"error": data.get("description", "Unknown error"), "details": data}

        return data

    async def get_chat_member(
        self,
        chat_id: Union[int, str],
        user_id: int,
    ) -> Dict[str, Any]:
        """Get information about a member of a chat.

        Args:
            chat_id: Chat ID or username.
            user_id: User ID.

        Returns:
            API response with chat member info or error.
        """
        payload = {
            "chat_id": chat_id,
            "user_id": user_id,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self._api_url("getChatMember"), json=payload)
            data = resp.json()

        if not data.get("ok"):
            return {"error": data.get("description", "Unknown error"), "details": data}

        return data

    async def get_chat_members_count(
        self,
        chat_id: Union[int, str],
    ) -> Dict[str, Any]:
        """Get the number of members in a chat.

        Args:
            chat_id: Chat ID or username.

        Returns:
            API response with member count or error.
        """
        payload = {"chat_id": chat_id}

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self._api_url("getChatMembersCount"), json=payload)
            data = resp.json()

        if not data.get("ok"):
            return {"error": data.get("description", "Unknown error"), "details": data}

        return data

    async def forward_message(
        self,
        chat_id: Union[int, str],
        from_chat_id: Union[int, str],
        message_id: int,
        disable_notification: bool = False,
    ) -> Dict[str, Any]:
        """Forward a message from one chat to another.

        Args:
            chat_id: Target chat ID.
            from_chat_id: Source chat ID.
            message_id: Message ID to forward.
            disable_notification: Send silently.

        Returns:
            API response with forwarded message or error.
        """
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
        }

        if disable_notification:
            payload["disable_notification"] = True

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self._api_url("forwardMessage"), json=payload)
            data = resp.json()

        if not data.get("ok"):
            return {"error": data.get("description", "Unknown error"), "details": data}

        return data

    async def search_contact(self, name: str) -> Dict[str, Any]:
        """Search for a contact by name from the bot's recent chat history.

        Telegram bots can only interact with users who have started a
        conversation with the bot. This searches through recent updates to
        find matching users/chats by name.

        Args:
            name: Name to search for (case-insensitive, partial match).

        Returns:
            Dict with matching contacts or error.
        """
        updates_result = await self.get_updates(limit=100)

        if "error" in updates_result:
            return updates_result

        updates = updates_result.get("result", [])

        seen_ids: set = set()
        contacts: List[Dict[str, Any]] = []
        search_lower = name.lower()

        for update in updates:
            message = update.get("message") or update.get("edited_message")
            if not message:
                continue

            # --- check the chat itself ---
            chat = message.get("chat", {})
            chat_id = chat.get("id")

            if chat_id and chat_id not in seen_ids:
                seen_ids.add(chat_id)

                chat_type = chat.get("type", "")
                if chat_type == "private":
                    first_name = chat.get("first_name", "")
                    last_name = chat.get("last_name", "")
                    username = chat.get("username", "")
                    full_name = f"{first_name} {last_name}".strip()
                    searchable = f"{full_name} {username}".lower()
                else:
                    title = chat.get("title", "")
                    username = chat.get("username", "")
                    full_name = title
                    searchable = f"{title} {username}".lower()

                if search_lower in searchable:
                    contacts.append({
                        "chat_id": chat_id,
                        "type": chat_type,
                        "name": full_name or username,
                        "username": username,
                        "first_name": chat.get("first_name", ""),
                        "last_name": chat.get("last_name", ""),
                    })

            # --- check the sender ---
            sender = message.get("from", {})
            sender_id = sender.get("id")

            if sender_id and sender_id not in seen_ids:
                seen_ids.add(sender_id)

                first_name = sender.get("first_name", "")
                last_name = sender.get("last_name", "")
                username = sender.get("username", "")
                full_name = f"{first_name} {last_name}".strip()
                searchable = f"{full_name} {username}".lower()

                if search_lower in searchable and not sender.get("is_bot"):
                    contacts.append({
                        "chat_id": sender_id,
                        "type": "private",
                        "name": full_name or username,
                        "username": username,
                        "first_name": first_name,
                        "last_name": last_name,
                    })

        if contacts:
            return {
                "ok": True,
                "result": {
                    "contacts": contacts,
                    "count": len(contacts),
                },
            }
        else:
            return {
                "error": f"No contacts found matching '{name}'",
                "details": {"searched_updates": len(updates), "name": name},
            }
