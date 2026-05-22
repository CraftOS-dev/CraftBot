# -*- coding: utf-8 -*-
"""Telegram Bot integration - handler (token + invite via shared bot) + client (long-polling)."""

from __future__ import annotations

import asyncio
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    PlatformMessage,
    has_credential,
    load_config,
    load_credential,
    register_client,
    register_handler,
    remove_credential,
    save_credential,
)
from ...config import ConfigStore
from ...helpers import arequest, request as http_request
from ...logger import get_logger

logger = get_logger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
POLL_TIMEOUT = 30
RETRY_DELAY = 5


def _shape_telegram(result: Dict[str, Any]) -> Dict[str, Any]:
    if "error" in result:
        return result
    data = result["result"]
    if not data.get("ok"):
        return {"error": data.get("description", "Unknown error"), "details": data}
    return data


async def _telegram_acall(
    url: str,
    *,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Telegram Bot API call. Returns raw response on ``ok=True``, ``{error, details}`` otherwise.

    Layers on top of ``arequest`` to add Telegram's ``{ok: bool, result, description}`` envelope.
    """
    method = "POST" if json is not None else "GET"
    result = await arequest(
        method, url, json=json, params=params, timeout=timeout, expected=(200,)
    )
    return _shape_telegram(result)


def _telegram_call_sync(
    url: str,
    *,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Sync variant - for use from login flows where async-context detection
    can be fragile. Wrap in ``asyncio.to_thread`` from coroutines."""
    method = "POST" if json is not None else "GET"
    result = http_request(
        method, url, json=json, params=params, timeout=timeout, expected=(200,)
    )
    return _shape_telegram(result)


@dataclass
class TelegramBotCredential:
    bot_token: str = ""
    bot_username: str = ""


@dataclass
class TelegramBotConfig:
    """Runtime knobs persisted to ``telegram_bot_config.json``."""

    # When True, only forward messages from private 1:1 DMs (drops groups,
    # supergroups, and channels). Closest analog to "self-only" for a bot,
    # which has no self-chat concept of its own.
    self_messages_only: bool = False


TELEGRAM_BOT = IntegrationSpec(
    name="telegram_bot",
    cred_class=TelegramBotCredential,
    cred_file="telegram_bot.json",
    platform_id="telegram_bot",
)


def _telegram_bot_config_file() -> str:
    """``telegram_bot.json`` â†’ ``telegram_bot_config.json``."""
    stem = TELEGRAM_BOT.cred_file
    return (stem[:-5] if stem.endswith(".json") else stem) + "_config.json"


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(TELEGRAM_BOT.name)
class TelegramBotHandler(IntegrationHandler):
    spec = TELEGRAM_BOT
    display_name = "Telegram Bot"
    description = "Bot API messaging"
    auth_type = "token"
    icon = "telegram"
    connect_help = [
        "Open Telegram and search for @BotFather",
        "Send /newbot and follow the prompts (pick a name, pick a username ending in 'bot')",
        "BotFather replies with a token - copy the long string (numbers:letters)",
        "Paste it as the Bot Token below",
    ]
    fields = [
        {
            "key": "bot_token",
            "label": "Bot Token",
            "placeholder": "From @BotFather",
            "password": True,
        },
    ]

    config_class = TelegramBotConfig
    config_fields = [
        {
            "key": "self_messages_only",
            "label": "Private DMs only",
            "type": "checkbox",
            "help": "Only forward messages from 1:1 private chats with the bot. "
            "Drops group, supergroup, and channel messages before they reach the agent.",
        },
    ]

    @property
    def subcommands(self) -> List[str]:
        return ["invite", "login", "logout", "status"]

    async def invite(self, args: List[str]) -> Tuple[bool, str]:
        shared_token = ConfigStore.get_oauth("TELEGRAM_SHARED_BOT_TOKEN")
        shared_username = ConfigStore.get_oauth("TELEGRAM_SHARED_BOT_USERNAME")
        if not shared_token or not shared_username:
            return False, (
                "Shared Telegram bot not configured. Set TELEGRAM_SHARED_BOT_TOKEN and "
                "TELEGRAM_SHARED_BOT_USERNAME.\n"
                "Alternatively, use /telegram_bot login <bot_token> with your own bot from @BotFather."
            )

        data = await asyncio.to_thread(
            _telegram_call_sync,
            f"{TELEGRAM_API_BASE}/bot{shared_token}/getMe",
        )
        if "error" in data:
            return False, f"Shared bot token invalid: {data['error']}"
        info = data["result"]

        save_credential(
            self.spec.cred_file,
            TelegramBotCredential(
                bot_token=shared_token,
                bot_username=info.get("username", ""),
            ),
        )

        bot_link = f"https://t.me/{shared_username}"
        try:
            webbrowser.open(bot_link)
        except Exception:
            pass
        return True, (
            f"Shared Telegram bot connected: @{info.get('username')}\n"
            f"Start chatting or add to groups: {bot_link}"
        )

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return (
                False,
                "Usage: /telegram_bot login <bot_token>\nGet from @BotFather on Telegram.",
            )
        bot_token = args[0]

        data = await asyncio.to_thread(
            _telegram_call_sync,
            f"{TELEGRAM_API_BASE}/bot{bot_token}/getMe",
        )
        if "error" in data:
            return False, f"Invalid bot token: {data['error']}"
        info = data["result"]

        save_credential(
            self.spec.cred_file,
            TelegramBotCredential(
                bot_token=bot_token,
                bot_username=info.get("username", ""),
            ),
        )
        return (
            True,
            f"Telegram bot connected: @{info.get('username')} ({info.get('id')})",
        )

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No Telegram bot credentials found."
        try:
            from ...manager import get_external_comms_manager

            manager = get_external_comms_manager()
            if manager:
                await manager.stop_platform(self.spec.platform_id)
        except Exception:
            pass
        remove_credential(self.spec.cred_file)
        return True, "Removed Telegram bot credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "Telegram bot: Not connected"
        cred = load_credential(self.spec.cred_file, TelegramBotCredential)
        label = (
            f"@{cred.bot_username}" if cred and cred.bot_username else "Bot configured"
        )
        return True, f"Telegram bot: Connected\n  - {label}"


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------


@register_client
class TelegramBotClient(BasePlatformClient):
    spec = TELEGRAM_BOT
    PLATFORM_ID = TELEGRAM_BOT.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[TelegramBotCredential] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_offset: int = 0
        self._bot_info: Optional[Dict[str, Any]] = None
        self._catchup_done: bool = False

    def has_credentials(self) -> bool:
        if has_credential(self.spec.cred_file):
            return True
        # Auto-save shared bot credentials from configured env if available
        try:
            shared_token = ConfigStore.get_oauth("TELEGRAM_SHARED_BOT_TOKEN")
            shared_username = ConfigStore.get_oauth("TELEGRAM_SHARED_BOT_USERNAME")
            if shared_token:
                save_credential(
                    self.spec.cred_file,
                    TelegramBotCredential(
                        bot_token=shared_token,
                        bot_username=shared_username or "",
                    ),
                )
                logger.info("[TELEGRAM_BOT] Auto-saved shared bot credentials")
                return True
        except Exception:
            pass
        return False

    def _load(self) -> TelegramBotCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, TelegramBotCredential)
        if self._cred is None:
            raise RuntimeError(
                "No Telegram Bot credentials. Use /telegram_bot login first."
            )
        return self._cred

    def _api_url(self, method: str) -> str:
        cred = self._load()
        return f"{TELEGRAM_API_BASE}/bot{cred.bot_token}/{method}"

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": recipient, "text": text}
        if kwargs.get("parse_mode"):
            payload["parse_mode"] = kwargs["parse_mode"]
        if kwargs.get("reply_to_message_id"):
            payload["reply_to_message_id"] = kwargs["reply_to_message_id"]
        if kwargs.get("disable_notification"):
            payload["disable_notification"] = True
        return await _telegram_acall(self._api_url("sendMessage"), json=payload)

    @property
    def supports_listening(self) -> bool:
        return True

    async def start_listening(self, callback) -> None:
        if self._listening:
            return
        self._message_callback = callback

        info = await self.get_me()
        if "error" in info:
            raise RuntimeError(
                f"Invalid bot token: {info.get('error', 'unknown error')}"
            )
        self._bot_info = info.get("result", {})

        self._listening = True
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop_listening(self) -> None:
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

    async def _poll_loop(self) -> None:
        try:
            catchup_resp = await self._poll_updates()
            for update in catchup_resp.get("result", []):
                self._poll_offset = update.get("update_id", 0) + 1
            self._catchup_done = True
        except Exception as e:
            logger.error(f"[TELEGRAM_BOT] Catchup error: {e}")
            self._catchup_done = True

        while self._listening:
            try:
                resp = await self._poll_updates()
                for update in resp.get("result", []):
                    await self._process_update(update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TELEGRAM_BOT] Poll error: {e}")
                await asyncio.sleep(RETRY_DELAY)

    def _poll_updates_sync(self) -> Dict[str, Any]:
        """Sync long-poll - runs in a worker thread to bypass anyio."""
        try:
            resp = httpx.get(
                self._api_url("getUpdates"),
                params={
                    "offset": self._poll_offset,
                    "timeout": POLL_TIMEOUT,
                    "allowed_updates": ["message"],
                },
                timeout=POLL_TIMEOUT + 10,
            )
            data = resp.json()
            return data if data.get("ok") else {"result": []}
        except httpx.TimeoutException:
            return {"result": []}

    async def _poll_updates(self) -> Dict[str, Any]:
        return await asyncio.to_thread(self._poll_updates_sync)

    async def _process_update(self, update: Dict[str, Any]) -> None:
        self._poll_offset = update.get("update_id", 0) + 1
        message = update.get("message")
        if not message:
            return
        text = message.get("text", "")
        if not text:
            return

        from_user = message.get("from", {})
        chat = message.get("chat", {})

        cfg = (
            load_config(_telegram_bot_config_file(), TelegramBotConfig)
            or TelegramBotConfig()
        )
        if cfg.self_messages_only and chat.get("type") != "private":
            return

        sender_name = from_user.get("first_name", "")
        if from_user.get("last_name"):
            sender_name += f" {from_user['last_name']}"
        if from_user.get("username"):
            sender_name += f" (@{from_user['username']})"

        ts = None
        try:
            ts = datetime.fromtimestamp(message["date"], tz=timezone.utc)
        except Exception:
            pass

        if self._message_callback:
            await self._message_callback(
                PlatformMessage(
                    platform=self.spec.platform_id,
                    sender_id=str(from_user.get("id", "")),
                    sender_name=sender_name or str(from_user.get("id", "unknown")),
                    text=text,
                    channel_id=str(chat.get("id", "")),
                    channel_name=chat.get("title", chat.get("first_name", "")),
                    message_id=str(message.get("message_id", "")),
                    timestamp=ts,
                    raw=update,
                )
            )

    # ----- API -----
    async def get_me(self) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("getMe"))

    async def send_photo(
        self,
        chat_id: Union[int, str],
        photo: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return await _telegram_acall(self._api_url("sendPhoto"), json=payload)

    async def send_document(
        self,
        chat_id: Union[int, str],
        document: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "document": document}
        if caption:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return await _telegram_acall(self._api_url("sendDocument"), json=payload)

    async def get_updates(
        self,
        offset: Optional[int] = None,
        limit: int = 100,
        timeout: int = 0,
        allowed_updates: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"limit": limit, "timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates:
            payload["allowed_updates"] = allowed_updates
        return await _telegram_acall(
            self._api_url("getUpdates"), json=payload, timeout=timeout + 10
        )

    async def get_chat(self, chat_id: Union[int, str]) -> Dict[str, Any]:
        return await _telegram_acall(
            self._api_url("getChat"), json={"chat_id": chat_id}
        )

    async def get_chat_member(
        self, chat_id: Union[int, str], user_id: int
    ) -> Dict[str, Any]:
        return await _telegram_acall(
            self._api_url("getChatMember"),
            json={"chat_id": chat_id, "user_id": user_id},
        )

    async def get_chat_members_count(self, chat_id: Union[int, str]) -> Dict[str, Any]:
        return await _telegram_acall(
            self._api_url("getChatMembersCount"), json={"chat_id": chat_id}
        )

    async def forward_message(
        self,
        chat_id: Union[int, str],
        from_chat_id: Union[int, str],
        message_id: int,
        disable_notification: bool = False,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
        }
        if disable_notification:
            payload["disable_notification"] = True
        return await _telegram_acall(self._api_url("forwardMessage"), json=payload)

    async def search_contact(self, name: str) -> Dict[str, Any]:
        updates_result = await self.get_updates(limit=100)
        if "error" in updates_result:
            return updates_result

        seen_ids: set = set()
        contacts: List[Dict[str, Any]] = []
        search_lower = name.lower()
        updates = updates_result.get("result", [])

        for update in updates:
            message = update.get("message") or update.get("edited_message")
            if not message:
                continue
            chat = message.get("chat", {})
            chat_id = chat.get("id")
            if chat_id and chat_id not in seen_ids:
                seen_ids.add(chat_id)
                chat_type = chat.get("type", "")
                if chat_type == "private":
                    full_name = f"{chat.get('first_name', '')} {chat.get('last_name', '')}".strip()
                    searchable = f"{full_name} {chat.get('username', '')}".lower()
                else:
                    full_name = chat.get("title", "")
                    searchable = f"{full_name} {chat.get('username', '')}".lower()
                if search_lower in searchable:
                    contacts.append(
                        {
                            "chat_id": chat_id,
                            "type": chat_type,
                            "name": full_name or chat.get("username", ""),
                            "username": chat.get("username", ""),
                            "first_name": chat.get("first_name", ""),
                            "last_name": chat.get("last_name", ""),
                        }
                    )
            sender = message.get("from", {})
            sender_id = sender.get("id")
            if sender_id and sender_id not in seen_ids:
                seen_ids.add(sender_id)
                full_name = f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip()
                searchable = f"{full_name} {sender.get('username', '')}".lower()
                if search_lower in searchable and not sender.get("is_bot"):
                    contacts.append(
                        {
                            "chat_id": sender_id,
                            "type": "private",
                            "name": full_name or sender.get("username", ""),
                            "username": sender.get("username", ""),
                            "first_name": sender.get("first_name", ""),
                            "last_name": sender.get("last_name", ""),
                        }
                    )

        if contacts:
            return {
                "ok": True,
                "result": {"contacts": contacts, "count": len(contacts)},
            }
        return {
            "error": f"No contacts found matching '{name}'",
            "details": {"searched_updates": len(updates), "name": name},
        }
