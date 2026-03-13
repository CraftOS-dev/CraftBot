# -*- coding: utf-8 -*-
"""Telegram MTProto (user account) client — uses Telethon with StringSession."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timezone
from typing import Any, Dict, List, Optional, Union

from app.external_comms.base import BasePlatformClient, PlatformMessage, MessageCallback
from app.external_comms.credentials import has_credential, load_credential, save_credential, remove_credential
from app.external_comms.registry import register_client

try:
    from app.logger import logger
except Exception:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

CREDENTIAL_FILE = "telegram_user.json"


@dataclass
class TelegramUserCredential:
    session_string: str = ""
    api_id: str = ""        # stored as str; cast to int when used
    api_hash: str = ""
    phone_number: str = ""


@register_client
class TelegramUserClient(BasePlatformClient):
    """Telegram MTProto client for user-account operations via Telethon."""

    PLATFORM_ID = "telegram_user"

    def __init__(self):
        super().__init__()
        self._cred: Optional[TelegramUserCredential] = None
        self._live_client = None          # persistent TelegramClient for listening
        self._my_user_id: Optional[int] = None
        self._agent_sent_ids: set = set()  # track IDs of messages sent by the agent

    # Generic terms the LLM may use to mean "send to self / Saved Messages"
    _OWNER_ALIASES = {"user", "owner", "me", "self"}

    def _resolve_recipient(self, recipient: str) -> str:
        """If *recipient* is a generic alias like 'user', resolve to Saved Messages."""
        if recipient.strip().lower() in self._OWNER_ALIASES:
            # "me" is Telethon's built-in shortcut for Saved Messages
            if self._my_user_id:
                logger.info(f"[TELEGRAM_USER] Resolved '{recipient}' to own user ID {self._my_user_id}")
                return str(self._my_user_id)
            logger.info(f"[TELEGRAM_USER] Resolved '{recipient}' to 'me' (Saved Messages)")
            return "me"
        return recipient

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

    def _load(self) -> TelegramUserCredential:
        if self._cred is None:
            self._cred = load_credential(CREDENTIAL_FILE, TelegramUserCredential)
        if self._cred is None:
            raise RuntimeError("No Telegram User credentials. Use /telegram_user login first.")
        return self._cred

    def _session_params(self):
        """Return (session, api_id, api_hash) for creating a TelegramClient."""
        from telethon.sessions import StringSession

        cred = self._load()
        return StringSession(cred.session_string), int(cred.api_id), cred.api_hash

    # ------------------------------------------------------------------
    # BasePlatformClient overrides
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self._load()
        self._connected = True

    # ------------------------------------------------------------------
    # Listening (Telethon event handler)
    # ------------------------------------------------------------------

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback: MessageCallback) -> None:
        """Start listening for incoming messages via MTProto.

        Captures:
        - Saved Messages (self-messages) → is_self_message = True
        - Incoming messages from others → is_self_message = False
        - Outgoing messages to others are ignored.
        """
        if self._listening:
            return

        self._message_callback = callback

        try:
            from telethon import TelegramClient, events
        except ImportError:
            raise RuntimeError("telethon is not installed")

        session, api_id, api_hash = self._session_params()
        client = TelegramClient(session, api_id, api_hash)
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError("Telegram user session expired or revoked. Please re-authenticate.")

        me = await client.get_me()
        self._my_user_id = me.id
        self._live_client = client

        @client.on(events.NewMessage)
        async def _on_new_message(event):
            try:
                await self._handle_event(event)
            except Exception as e:
                logger.error(f"[TELEGRAM_USER] Error handling message event: {e}")

        self._listening = True
        logger.info(
            f"[TELEGRAM_USER] Listener started for user {me.first_name or ''} "
            f"(@{me.username or 'N/A'}, id={me.id})"
        )

    async def stop_listening(self) -> None:
        """Stop listening and disconnect the persistent client."""
        if not self._listening:
            return

        self._listening = False

        if self._live_client:
            try:
                await self._live_client.disconnect()
            except Exception:
                pass
            self._live_client = None

        logger.info("[TELEGRAM_USER] Listener stopped")

    async def _handle_event(self, event) -> None:
        """Process a Telethon NewMessage event."""
        msg = event.message
        if not msg or not msg.text:
            return

        chat_id = event.chat_id
        is_saved_messages = (chat_id == self._my_user_id)

        # Outgoing message to someone else → ignore
        if msg.out and not is_saved_messages:
            return

        # Skip agent-sent self-messages (prevents echo loop)
        if is_saved_messages and msg.out:
            msg_id_str = str(msg.id)
            if msg_id_str in self._agent_sent_ids:
                self._agent_sent_ids.discard(msg_id_str)
                logger.debug(f"[TELEGRAM_USER] Skipping agent-sent message (ID match): {msg_id_str}")
                return
            if msg.text.startswith(self._agent_prefix):
                logger.debug(f"[TELEGRAM_USER] Skipping agent-sent message (prefix match): {msg.text[:50]}...")
                return

        sender = await event.get_sender()
        chat = await event.get_chat()

        sender_name = _get_display_name(sender) if sender else "Unknown"
        channel_name = _get_display_name(chat) if chat else ""

        platform_msg = PlatformMessage(
            platform="telegram_user",
            sender_id=str(sender.id if sender else self._my_user_id),
            sender_name=sender_name,
            text=msg.text,
            channel_id=str(chat_id),
            channel_name=channel_name if not is_saved_messages else "Saved Messages",
            message_id=str(msg.id),
            timestamp=msg.date.astimezone(timezone.utc) if msg.date else None,
            raw={"is_self_message": is_saved_messages},
        )

        if self._message_callback:
            await self._message_callback(platform_msg)

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        """Send a text message to a chat as the user account. Prepends agent prefix.

        Args:
            recipient: Chat ID, username, or phone number.
            text: Message text.
            **kwargs: Optional ``reply_to`` (int) message ID.

        Returns:
            Dict with sent message info or error.
        """
        reply_to: Optional[int] = kwargs.get("reply_to")
        resolved = self._resolve_recipient(recipient)
        prefixed_text = f"{self._agent_prefix}{text}"

        try:
            from telethon import TelegramClient
            from telethon.errors import AuthKeyUnregisteredError, FloodWaitError

            session, api_id, api_hash = self._session_params()

            async with TelegramClient(session, api_id, api_hash) as client:
                entity = await client.get_entity(resolved)
                msg = await client.send_message(entity, prefixed_text, reply_to=reply_to)

                # Track sent message ID to filter echo in _handle_event
                self._agent_sent_ids.add(str(msg.id))

                return {
                    "ok": True,
                    "result": {
                        "message_id": msg.id,
                        "date": msg.date.isoformat() if msg.date else None,
                        "chat_id": entity.id,
                        "text": msg.text,
                    },
                }

        except ImportError:
            return {"error": "telethon is not installed", "details": {}}
        except AuthKeyUnregisteredError:
            return {
                "error": "Session has expired or been revoked. Please re-authenticate.",
                "details": {"status": "session_expired"},
            }
        except ValueError as e:
            return {
                "error": f"Could not find chat: {e}",
                "details": {"chat_id": str(recipient)},
            }
        except FloodWaitError as e:
            return {
                "error": f"Rate limited. Please wait {e.seconds} seconds.",
                "details": {"flood_wait_seconds": e.seconds},
            }
        except Exception as e:
            return {
                "error": f"Failed to send message: {e}",
                "details": {"exception": type(e).__name__},
            }

    # ------------------------------------------------------------------
    # MTProto API methods
    # ------------------------------------------------------------------

    async def get_me(self) -> Dict[str, Any]:
        """Get information about the authenticated user.

        Returns:
            Dict with user info or error.
        """
        try:
            from telethon import TelegramClient
            from telethon.errors import AuthKeyUnregisteredError

            session, api_id, api_hash = self._session_params()

            async with TelegramClient(session, api_id, api_hash) as client:
                me = await client.get_me()

                return {
                    "ok": True,
                    "result": {
                        "user_id": me.id,
                        "first_name": me.first_name or "",
                        "last_name": me.last_name or "",
                        "username": me.username or "",
                        "phone": me.phone or "",
                        "is_bot": me.bot,
                    },
                }

        except ImportError:
            return {"error": "telethon is not installed", "details": {}}
        except AuthKeyUnregisteredError:
            return {
                "error": "Session has expired or been revoked. Please re-authenticate.",
                "details": {"status": "session_expired"},
            }
        except Exception as e:
            return {
                "error": f"Failed to get user info: {e}",
                "details": {"exception": type(e).__name__},
            }

    async def get_dialogs(self, limit: int = 50) -> Dict[str, Any]:
        """Get list of all conversations (dialogs/chats).

        Args:
            limit: Maximum number of dialogs to return.

        Returns:
            Dict with list of dialogs or error.
        """
        try:
            from telethon import TelegramClient
            from telethon.errors import AuthKeyUnregisteredError
            from telethon.tl.types import User, Chat, Channel

            session, api_id, api_hash = self._session_params()

            async with TelegramClient(session, api_id, api_hash) as client:
                dialogs = await client.get_dialogs(limit=limit)

                result = []
                for dialog in dialogs:
                    entity = dialog.entity

                    dialog_info: Dict[str, Any] = {
                        "id": dialog.id,
                        "name": dialog.name or "",
                        "unread_count": dialog.unread_count,
                        "is_pinned": dialog.pinned,
                        "is_archived": dialog.archived,
                    }

                    if isinstance(entity, User):
                        dialog_info["type"] = "private"
                        dialog_info["username"] = entity.username or ""
                        dialog_info["phone"] = entity.phone or ""
                        dialog_info["is_bot"] = entity.bot
                    elif isinstance(entity, Chat):
                        dialog_info["type"] = "group"
                        dialog_info["participants_count"] = getattr(entity, "participants_count", None)
                    elif isinstance(entity, Channel):
                        dialog_info["type"] = "channel" if entity.broadcast else "supergroup"
                        dialog_info["username"] = entity.username or ""
                        dialog_info["participants_count"] = getattr(entity, "participants_count", None)
                    else:
                        dialog_info["type"] = "unknown"

                    if dialog.message:
                        dialog_info["last_message"] = {
                            "id": dialog.message.id,
                            "date": dialog.message.date.isoformat() if dialog.message.date else None,
                            "text": dialog.message.text[:100] if dialog.message.text else "",
                        }

                    result.append(dialog_info)

                return {
                    "ok": True,
                    "result": {
                        "dialogs": result,
                        "count": len(result),
                    },
                }

        except ImportError:
            return {"error": "telethon is not installed", "details": {}}
        except AuthKeyUnregisteredError:
            return {
                "error": "Session has expired or been revoked. Please re-authenticate.",
                "details": {"status": "session_expired"},
            }
        except Exception as e:
            return {
                "error": f"Failed to get dialogs: {e}",
                "details": {"exception": type(e).__name__},
            }

    async def get_messages(
        self,
        chat_id: Union[int, str],
        limit: int = 50,
        offset_id: int = 0,
    ) -> Dict[str, Any]:
        """Get message history from a chat.

        Args:
            chat_id: Chat ID, username, or phone number.
            limit: Maximum number of messages to return.
            offset_id: Message ID to start from (for pagination).

        Returns:
            Dict with list of messages or error.
        """
        try:
            from telethon import TelegramClient
            from telethon.errors import AuthKeyUnregisteredError
            from telethon.tl.types import User, Chat, Channel

            session, api_id, api_hash = self._session_params()

            async with TelegramClient(session, api_id, api_hash) as client:
                entity = await client.get_entity(chat_id)
                messages = await client.get_messages(entity, limit=limit, offset_id=offset_id)

                result = []
                for msg in messages:
                    message_info: Dict[str, Any] = {
                        "id": msg.id,
                        "date": msg.date.isoformat() if msg.date else None,
                        "text": msg.text or "",
                        "out": msg.out,
                    }

                    if msg.sender:
                        sender = msg.sender
                        message_info["sender"] = {
                            "id": sender.id,
                            "name": _get_display_name(sender),
                            "username": getattr(sender, "username", None) or "",
                        }

                    if msg.media:
                        message_info["has_media"] = True
                        message_info["media_type"] = type(msg.media).__name__

                    if msg.reply_to:
                        message_info["reply_to_msg_id"] = msg.reply_to.reply_to_msg_id

                    if msg.forward:
                        message_info["is_forwarded"] = True

                    result.append(message_info)

                chat_info = {
                    "id": entity.id,
                    "name": _get_display_name(entity),
                    "type": _get_entity_type(entity),
                }

                return {
                    "ok": True,
                    "result": {
                        "chat": chat_info,
                        "messages": result,
                        "count": len(result),
                    },
                }

        except ImportError:
            return {"error": "telethon is not installed", "details": {}}
        except AuthKeyUnregisteredError:
            return {
                "error": "Session has expired or been revoked. Please re-authenticate.",
                "details": {"status": "session_expired"},
            }
        except ValueError as e:
            return {
                "error": f"Could not find chat: {e}",
                "details": {"chat_id": str(chat_id)},
            }
        except Exception as e:
            return {
                "error": f"Failed to get messages: {e}",
                "details": {"exception": type(e).__name__},
            }

    async def send_file(
        self,
        chat_id: Union[int, str],
        file_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Send a file/media to a chat.

        Args:
            chat_id: Chat ID, username, or phone number.
            file_path: Path to file or URL.
            caption: Optional caption for the file.
            reply_to: Optional message ID to reply to.

        Returns:
            Dict with sent message info or error.
        """
        try:
            from telethon import TelegramClient
            from telethon.errors import AuthKeyUnregisteredError, FloodWaitError

            session, api_id, api_hash = self._session_params()

            async with TelegramClient(session, api_id, api_hash) as client:
                entity = await client.get_entity(chat_id)
                msg = await client.send_file(
                    entity,
                    file_path,
                    caption=caption,
                    reply_to=reply_to,
                )

                return {
                    "ok": True,
                    "result": {
                        "message_id": msg.id,
                        "date": msg.date.isoformat() if msg.date else None,
                        "chat_id": entity.id,
                        "has_media": True,
                    },
                }

        except ImportError:
            return {"error": "telethon is not installed", "details": {}}
        except AuthKeyUnregisteredError:
            return {
                "error": "Session has expired or been revoked. Please re-authenticate.",
                "details": {"status": "session_expired"},
            }
        except ValueError as e:
            return {
                "error": f"Could not find chat: {e}",
                "details": {"chat_id": str(chat_id)},
            }
        except FileNotFoundError:
            return {
                "error": f"File not found: {file_path}",
                "details": {"file_path": file_path},
            }
        except FloodWaitError as e:
            return {
                "error": f"Rate limited. Please wait {e.seconds} seconds.",
                "details": {"flood_wait_seconds": e.seconds},
            }
        except Exception as e:
            return {
                "error": f"Failed to send file: {e}",
                "details": {"exception": type(e).__name__},
            }

    async def search_contacts(
        self,
        query: str,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Search for contacts/users by name or username.

        Args:
            query: Search query (name or username).
            limit: Maximum results to return.

        Returns:
            Dict with matching contacts or error.
        """
        try:
            from telethon import TelegramClient
            from telethon.errors import AuthKeyUnregisteredError
            from telethon.tl.types import User

            session, api_id, api_hash = self._session_params()

            async with TelegramClient(session, api_id, api_hash) as client:
                dialogs = await client.get_dialogs(limit=100)

                contacts: List[Dict[str, Any]] = []
                query_lower = query.lower()

                for dialog in dialogs:
                    entity = dialog.entity
                    name = _get_display_name(entity).lower()
                    username = (getattr(entity, "username", "") or "").lower()

                    if query_lower in name or query_lower in username:
                        contact_info: Dict[str, Any] = {
                            "id": entity.id,
                            "name": _get_display_name(entity),
                            "username": getattr(entity, "username", None) or "",
                            "type": _get_entity_type(entity),
                        }

                        if isinstance(entity, User):
                            contact_info["phone"] = entity.phone or ""
                            contact_info["is_bot"] = entity.bot

                        contacts.append(contact_info)

                        if len(contacts) >= limit:
                            break

                return {
                    "ok": True,
                    "result": {
                        "contacts": contacts,
                        "count": len(contacts),
                    },
                }

        except ImportError:
            return {"error": "telethon is not installed", "details": {}}
        except AuthKeyUnregisteredError:
            return {
                "error": "Session has expired or been revoked. Please re-authenticate.",
                "details": {"status": "session_expired"},
            }
        except Exception as e:
            return {
                "error": f"Failed to search contacts: {e}",
                "details": {"exception": type(e).__name__},
            }


# ------------------------------------------------------------------
# Private helpers (mirror of mtproto_helpers utilities)
# ------------------------------------------------------------------

def _get_display_name(entity) -> str:
    """Get display name for any Telethon entity type."""
    try:
        from telethon.tl.types import User
    except ImportError:
        return str(getattr(entity, "id", ""))

    if isinstance(entity, User):
        parts = []
        if entity.first_name:
            parts.append(entity.first_name)
        if entity.last_name:
            parts.append(entity.last_name)
        return " ".join(parts) or entity.username or str(entity.id)
    elif hasattr(entity, "title"):
        return entity.title or ""
    else:
        return str(entity.id)


def _get_entity_type(entity) -> str:
    """Get type string for any Telethon entity."""
    try:
        from telethon.tl.types import User, Chat, Channel
    except ImportError:
        return "unknown"

    if isinstance(entity, User):
        return "bot" if entity.bot else "user"
    elif isinstance(entity, Chat):
        return "group"
    elif isinstance(entity, Channel):
        return "channel" if entity.broadcast else "supergroup"
    else:
        return "unknown"
