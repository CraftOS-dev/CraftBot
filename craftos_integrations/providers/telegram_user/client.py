# -*- coding: utf-8 -*-
"""Telegram MTProto (user account) integration - handler (phone+code+QR) + client (Telethon listener)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timezone
from typing import Any, Dict, List, Optional, Union

from ... import (
    BasePlatformClient,
    IntegrationSpec,
    PlatformMessage,
    has_credential,
    load_config,
    load_credential,
    register_client,
)
from ...config import ConfigStore
from ...logger import get_logger

logger = get_logger(__name__)


@dataclass
class TelegramUserCredential:
    session_string: str = ""
    api_id: str = ""
    api_hash: str = ""
    phone_number: str = ""


@dataclass
class TelegramUserConfig:
    """Runtime knobs persisted to ``telegram_user_config.json``."""

    # When True, only forward messages from the user's own Saved Messages
    # chat (chat_id == own user_id). All DMs from contacts and group/channel
    # chatter are dropped before reaching the agent. Useful when the user
    # wants Telegram to act as a personal command channel only.
    self_messages_only: bool = False


TELEGRAM_USER = IntegrationSpec(
    name="telegram_user",
    cred_class=TelegramUserCredential,
    cred_file="telegram_user.json",
    platform_id="telegram_user",
)


def _telegram_user_config_file() -> str:
    """``telegram_user.json`` → ``telegram_user_config.json``."""
    stem = TELEGRAM_USER.cred_file
    return (stem[:-5] if stem.endswith(".json") else stem) + "_config.json"


# Module-level pending auth state (mirrors original handlers.py behaviour)
_pending_telegram_auth: Dict[str, Dict[str, Any]] = {}


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------
@register_client
class TelegramUserClient(BasePlatformClient):
    spec = TELEGRAM_USER
    PLATFORM_ID = TELEGRAM_USER.platform_id

    _OWNER_ALIASES = {"user", "owner", "me", "self"}

    def __init__(self):
        super().__init__()
        self._cred: Optional[TelegramUserCredential] = None
        self._live_client = None
        self._live_loop = None
        self._send_queue: Optional[asyncio.Queue] = None
        self._send_task = None
        self._my_user_id: Optional[int] = None
        self._agent_sent_ids: set = set()

    def _resolve_recipient(self, recipient: str) -> str:
        if recipient.strip().lower() in self._OWNER_ALIASES:
            if self._my_user_id:
                return str(self._my_user_id)
            return "me"
        return recipient

    @property
    def _agent_prefix(self) -> str:
        name = ConfigStore.extras.get("agent_name", "AGENT")
        return f"[{name}] "

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> TelegramUserCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, TelegramUserCredential)
        if self._cred is None:
            raise RuntimeError(
                "No Telegram User credentials. Use /telegram_user login first."
            )
        return self._cred

    def _session_params(self):
        from telethon.sessions import StringSession

        cred = self._load()
        return StringSession(cred.session_string), int(cred.api_id), cred.api_hash

    async def connect(self) -> None:
        self._load()
        self._connected = True

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback) -> None:
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
        self._live_loop = asyncio.get_event_loop()

        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError(
                "Telegram user session expired or revoked. Please re-authenticate."
            )

        me = await client.get_me()
        self._my_user_id = me.id
        self._live_client = client

        @client.on(events.NewMessage)
        async def _on_new_message(event):
            try:
                await self._handle_event(event)
            except Exception as e:
                logger.error(f"[TELEGRAM_USER] Error handling message event: {e}")

        await client.catch_up()
        self._send_queue = asyncio.Queue()

        async def _send_processor():
            while self._listening:
                try:
                    item = await asyncio.wait_for(self._send_queue.get(), timeout=60)
                    recipient, text, reply_to, result_future = item
                    try:
                        try:
                            entity = await client.get_entity(
                                int(recipient)
                                if recipient.lstrip("-").isdigit()
                                else recipient
                            )
                        except ValueError:
                            entity = await client.get_entity(recipient)
                        msg = await client.send_message(entity, text, reply_to=reply_to)
                        result_future.set_result(msg)
                    except Exception as e:
                        result_future.set_exception(e)
                except asyncio.TimeoutError:
                    try:
                        if self._live_client and self._live_client.is_connected():
                            await self._live_client.catch_up()
                    except Exception:
                        pass
                except asyncio.CancelledError:
                    break
                except Exception:
                    pass

        self._send_task = asyncio.create_task(_send_processor())
        self._listening = True

    async def stop_listening(self) -> None:
        if not self._listening:
            return
        self._listening = False
        for task in [
            getattr(self, "_run_task", None),
            getattr(self, "_send_task", None),
        ]:
            if task and not task.done():
                task.cancel()
        self._run_task = None
        self._send_task = None
        self._send_queue = None
        if self._live_client:
            try:
                await self._live_client.disconnect()
            except Exception:
                pass
            self._live_client = None

    @staticmethod
    def _extract_attachments(msg, chat_id) -> list:
        """Normalize a Telethon message's media into
        PlatformMessage.attachments. MTProto has no usable file_id
        (Telethon's ``file.id`` is unmaintained) — the fetch handle is the
        (chat_id, message_id) pair fed to download_media."""
        if not getattr(msg, "media", None):
            return []
        media_cls = type(msg.media).__name__
        if media_cls == "MessageMediaGeo":
            geo = getattr(msg.media, "geo", None)
            return [
                {
                    "kind": "location",
                    "extra": {
                        "lat": getattr(geo, "lat", None),
                        "long": getattr(geo, "long", None),
                    },
                }
            ]
        if media_cls == "MessageMediaContact":
            return [
                {
                    "kind": "contact",
                    "extra": {
                        "name": (getattr(msg.media, "first_name", "") or "").strip(),
                        "phone": getattr(msg.media, "phone_number", ""),
                    },
                }
            ]
        file_info = getattr(msg, "file", None)
        mime = (getattr(file_info, "mime_type", "") or "") if file_info else ""
        if getattr(msg, "photo", None) or mime.startswith("image/"):
            kind = "photo"
        elif mime.startswith("video/"):
            kind = "video"
        elif mime.startswith("audio/"):
            kind = "audio"
        else:
            kind = "document"
        att: dict = {
            "kind": kind,
            "id": str(msg.id),
            "extra": {"chat_id": str(chat_id)},
        }
        if file_info is not None:
            if getattr(file_info, "name", None):
                att["name"] = file_info.name
            if mime:
                att["mime"] = mime
            if getattr(file_info, "size", None):
                att["size"] = file_info.size
        return [att]

    async def _handle_event(self, event) -> None:
        msg = event.message
        # Telethon's msg.text is the caption for media messages; media-only
        # messages must not be dropped.
        if not msg or not (msg.text or getattr(msg, "media", None)):
            return
        chat_id = event.chat_id
        is_saved_messages = chat_id == self._my_user_id

        cfg = (
            load_config(_telegram_user_config_file(), TelegramUserConfig)
            or TelegramUserConfig()
        )
        if cfg.self_messages_only and not is_saved_messages:
            return

        if msg.out and not is_saved_messages:
            return

        if is_saved_messages and msg.out:
            msg_id_str = str(msg.id)
            if msg_id_str in self._agent_sent_ids:
                self._agent_sent_ids.discard(msg_id_str)
                return
            if msg.text.startswith(self._agent_prefix):
                return

        sender = await event.get_sender()
        chat = await event.get_chat()
        sender_name = _get_display_name(sender) if sender else "Unknown"
        channel_name = _get_display_name(chat) if chat else ""

        if self._message_callback:
            await self._message_callback(
                PlatformMessage(
                    platform=self.spec.platform_id,
                    sender_id=str(sender.id if sender else self._my_user_id),
                    sender_name=sender_name,
                    text=msg.text or "",
                    channel_id=str(chat_id),
                    channel_name=channel_name
                    if not is_saved_messages
                    else "Saved Messages",
                    message_id=str(msg.id),
                    timestamp=msg.date.astimezone(timezone.utc) if msg.date else None,
                    raw={"is_self_message": is_saved_messages},
                    attachments=self._extract_attachments(msg, chat_id),
                )
            )

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        reply_to: Optional[int] = kwargs.get("reply_to")
        resolved = self._resolve_recipient(recipient)
        prefixed_text = f"{self._agent_prefix}{text}"

        try:
            from telethon import TelegramClient
            from telethon.errors import AuthKeyUnregisteredError, FloodWaitError

            if (
                self._send_queue is not None
                and self._live_client
                and self._live_client.is_connected()
            ):
                loop = asyncio.get_event_loop()
                result_future = loop.create_future()
                await self._send_queue.put(
                    (resolved, prefixed_text, reply_to, result_future)
                )
                msg = await asyncio.wait_for(result_future, timeout=30)
            else:
                session, api_id, api_hash = self._session_params()
                async with TelegramClient(session, api_id, api_hash) as client:
                    try:
                        entity = await client.get_entity(
                            int(resolved)
                            if resolved.lstrip("-").isdigit()
                            else resolved
                        )
                    except ValueError:
                        entity = await client.get_entity(resolved)
                    msg = await client.send_message(
                        entity, prefixed_text, reply_to=reply_to
                    )

                self._agent_sent_ids.add(str(msg.id))
                return {
                    "ok": True,
                    "result": {
                        "message_id": msg.id,
                        "date": msg.date.isoformat() if msg.date else None,
                        "chat_id": getattr(msg, "chat_id", None) or resolved,
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

    # --- API methods ---
    async def get_me(self) -> Dict[str, Any]:
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
                "error": "Session expired. Please re-authenticate.",
                "details": {"status": "session_expired"},
            }
        except Exception as e:
            return {
                "error": f"Failed to get user info: {e}",
                "details": {"exception": type(e).__name__},
            }

    async def get_dialogs(self, limit: int = 50) -> Dict[str, Any]:
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
                    info: Dict[str, Any] = {
                        "id": dialog.id,
                        "name": dialog.name or "",
                        "unread_count": dialog.unread_count,
                        "is_pinned": dialog.pinned,
                        "is_archived": dialog.archived,
                    }
                    if isinstance(entity, User):
                        info.update(
                            {
                                "type": "private",
                                "username": entity.username or "",
                                "phone": entity.phone or "",
                                "is_bot": entity.bot,
                            }
                        )
                    elif isinstance(entity, Chat):
                        info.update(
                            {
                                "type": "group",
                                "participants_count": getattr(
                                    entity, "participants_count", None
                                ),
                            }
                        )
                    elif isinstance(entity, Channel):
                        info.update(
                            {
                                "type": "channel" if entity.broadcast else "supergroup",
                                "username": entity.username or "",
                                "participants_count": getattr(
                                    entity, "participants_count", None
                                ),
                            }
                        )
                    else:
                        info["type"] = "unknown"
                    if dialog.message:
                        info["last_message"] = {
                            "id": dialog.message.id,
                            "date": dialog.message.date.isoformat()
                            if dialog.message.date
                            else None,
                            "text": dialog.message.text[:100]
                            if dialog.message.text
                            else "",
                        }
                    result.append(info)
                return {"ok": True, "result": {"dialogs": result, "count": len(result)}}
        except ImportError:
            return {"error": "telethon is not installed", "details": {}}
        except AuthKeyUnregisteredError:
            return {
                "error": "Session expired.",
                "details": {"status": "session_expired"},
            }
        except Exception as e:
            return {
                "error": f"Failed to get dialogs: {e}",
                "details": {"exception": type(e).__name__},
            }

    async def get_messages(
        self, chat_id: Union[int, str], limit: int = 50, offset_id: int = 0
    ) -> Dict[str, Any]:
        try:
            from telethon import TelegramClient
            from telethon.errors import AuthKeyUnregisteredError

            session, api_id, api_hash = self._session_params()
            async with TelegramClient(session, api_id, api_hash) as client:
                entity = await client.get_entity(chat_id)
                messages = await client.get_messages(
                    entity, limit=limit, offset_id=offset_id
                )
                result = []
                for msg in messages:
                    info: Dict[str, Any] = {
                        "id": msg.id,
                        "date": msg.date.isoformat() if msg.date else None,
                        "text": msg.text or "",
                        "out": msg.out,
                    }
                    if msg.sender:
                        info["sender"] = {
                            "id": msg.sender.id,
                            "name": _get_display_name(msg.sender),
                            "username": getattr(msg.sender, "username", None) or "",
                        }
                    if msg.media:
                        info["has_media"] = True
                        info["media_type"] = type(msg.media).__name__
                    if msg.reply_to:
                        info["reply_to_msg_id"] = msg.reply_to.reply_to_msg_id
                    if msg.forward:
                        info["is_forwarded"] = True
                    result.append(info)
                return {
                    "ok": True,
                    "result": {
                        "chat": {
                            "id": entity.id,
                            "name": _get_display_name(entity),
                            "type": _get_entity_type(entity),
                        },
                        "messages": result,
                        "count": len(result),
                    },
                }
        except ImportError:
            return {"error": "telethon is not installed", "details": {}}
        except AuthKeyUnregisteredError:
            return {
                "error": "Session expired.",
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

    async def download_media(
        self, chat_id: Union[int, str], message_id: Union[int, str], dest_path: str
    ) -> Dict[str, Any]:
        """Re-fetch a message by id and download its media to disk.

        MTProto media has no bot-API file_id; the (chat_id, message_id)
        pair IS the fetch handle the listener forwards. The download must
        complete inside the async-with — exiting disconnects the client
        mid-transfer (docs/plans/attachment-reception-plan.md)."""
        try:
            from telethon import TelegramClient
            from telethon.errors import AuthKeyUnregisteredError, FloodWaitError

            session, api_id, api_hash = self._session_params()
            async with TelegramClient(session, api_id, api_hash) as client:
                entity = await client.get_entity(chat_id)
                # Single int id → single Message (or None if not found).
                msg = await client.get_messages(entity, ids=int(message_id))
                if msg is None:
                    return {
                        "error": f"Message {message_id} not found in chat {chat_id}",
                        "details": {"chat_id": str(chat_id)},
                    }
                if not msg.media:
                    return {
                        "error": f"Message {message_id} has no media",
                        "details": {"message_id": str(message_id)},
                    }
                # Returns the actual saved path (Telethon appends a
                # name/extension when dest is a directory).
                saved = await msg.download_media(file=dest_path)
                file_info = msg.file
                return {
                    "ok": True,
                    "result": {
                        "path": str(saved) if saved else dest_path,
                        "name": getattr(file_info, "name", None),
                        "mime_type": getattr(file_info, "mime_type", None),
                        "size": getattr(file_info, "size", None),
                    },
                }
        except ImportError:
            return {"error": "telethon is not installed", "details": {}}
        except AuthKeyUnregisteredError:
            return {
                "error": "Session expired.",
                "details": {"status": "session_expired"},
            }
        except ValueError as e:
            return {
                "error": f"Could not find chat: {e}",
                "details": {"chat_id": str(chat_id)},
            }
        except FloodWaitError as e:
            return {
                "error": f"Rate limited. Wait {e.seconds}s.",
                "details": {"flood_wait_seconds": e.seconds},
            }
        except Exception as e:
            return {
                "error": f"Failed to download media: {e}",
                "details": {"exception": type(e).__name__},
            }

    async def send_file(
        self,
        chat_id: Union[int, str],
        file_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            from telethon import TelegramClient
            from telethon.errors import AuthKeyUnregisteredError, FloodWaitError

            session, api_id, api_hash = self._session_params()
            async with TelegramClient(session, api_id, api_hash) as client:
                entity = await client.get_entity(chat_id)
                msg = await client.send_file(
                    entity, file_path, caption=caption, reply_to=reply_to
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
                "error": "Session expired.",
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
                "error": f"Rate limited. Wait {e.seconds}s.",
                "details": {"flood_wait_seconds": e.seconds},
            }
        except Exception as e:
            return {
                "error": f"Failed to send file: {e}",
                "details": {"exception": type(e).__name__},
            }

    async def search_contacts(self, query: str, limit: int = 20) -> Dict[str, Any]:
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
                        info: Dict[str, Any] = {
                            "id": entity.id,
                            "name": _get_display_name(entity),
                            "username": getattr(entity, "username", None) or "",
                            "type": _get_entity_type(entity),
                        }
                        if isinstance(entity, User):
                            info["phone"] = entity.phone or ""
                            info["is_bot"] = entity.bot
                        contacts.append(info)
                        if len(contacts) >= limit:
                            break
                return {
                    "ok": True,
                    "result": {"contacts": contacts, "count": len(contacts)},
                }
        except ImportError:
            return {"error": "telethon is not installed", "details": {}}
        except AuthKeyUnregisteredError:
            return {
                "error": "Session expired.",
                "details": {"status": "session_expired"},
            }
        except Exception as e:
            return {
                "error": f"Failed to search contacts: {e}",
                "details": {"exception": type(e).__name__},
            }


# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------


def _get_display_name(entity) -> str:
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
    return str(entity.id)


def _get_entity_type(entity) -> str:
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
    return "unknown"
