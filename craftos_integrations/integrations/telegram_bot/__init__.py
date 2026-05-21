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


async def _telegram_acall(url: str, *, json: Optional[Dict[str, Any]] = None,
                          params: Optional[Dict[str, Any]] = None,
                          timeout: float = 10.0) -> Dict[str, Any]:
    """Telegram Bot API call. Returns raw response on ``ok=True``, ``{error, details}`` otherwise.

    Layers on top of ``arequest`` to add Telegram's ``{ok: bool, result, description}`` envelope.
    """
    method = "POST" if json is not None else "GET"
    result = await arequest(method, url, json=json, params=params,
                            timeout=timeout, expected=(200,))
    return _shape_telegram(result)


def _telegram_call_sync(url: str, *, json: Optional[Dict[str, Any]] = None,
                        params: Optional[Dict[str, Any]] = None,
                        timeout: float = 10.0) -> Dict[str, Any]:
    """Sync variant - for use from login flows where async-context detection
    can be fragile. Wrap in ``asyncio.to_thread`` from coroutines."""
    method = "POST" if json is not None else "GET"
    result = http_request(method, url, json=json, params=params,
                          timeout=timeout, expected=(200,))
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
        {"key": "bot_token", "label": "Bot Token", "placeholder": "From @BotFather", "password": True},
    ]

    config_class = TelegramBotConfig
    config_fields = [
        {"key": "self_messages_only", "label": "Private DMs only", "type": "checkbox",
         "help": "Only forward messages from 1:1 private chats with the bot. "
                 "Drops group, supergroup, and channel messages before they reach the agent."},
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
            _telegram_call_sync, f"{TELEGRAM_API_BASE}/bot{shared_token}/getMe",
        )
        if "error" in data:
            return False, f"Shared bot token invalid: {data['error']}"
        info = data["result"]

        save_credential(self.spec.cred_file, TelegramBotCredential(
            bot_token=shared_token, bot_username=info.get("username", ""),
        ))

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
            return False, "Usage: /telegram_bot login <bot_token>\nGet from @BotFather on Telegram."
        bot_token = args[0]

        data = await asyncio.to_thread(
            _telegram_call_sync, f"{TELEGRAM_API_BASE}/bot{bot_token}/getMe",
        )
        if "error" in data:
            return False, f"Invalid bot token: {data['error']}"
        info = data["result"]

        save_credential(self.spec.cred_file, TelegramBotCredential(
            bot_token=bot_token, bot_username=info.get("username", ""),
        ))
        return True, f"Telegram bot connected: @{info.get('username')} ({info.get('id')})"

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
        label = f"@{cred.bot_username}" if cred and cred.bot_username else "Bot configured"
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
                save_credential(self.spec.cred_file, TelegramBotCredential(
                    bot_token=shared_token, bot_username=shared_username or "",
                ))
                logger.info("[TELEGRAM_BOT] Auto-saved shared bot credentials")
                return True
        except Exception:
            pass
        return False

    def _load(self) -> TelegramBotCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, TelegramBotCredential)
        if self._cred is None:
            raise RuntimeError("No Telegram Bot credentials. Use /telegram_bot login first.")
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
            raise RuntimeError(f"Invalid bot token: {info.get('error', 'unknown error')}")
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
            resp = httpx.get(self._api_url("getUpdates"), params={
                "offset": self._poll_offset,
                "timeout": POLL_TIMEOUT,
                "allowed_updates": ["message"],
            }, timeout=POLL_TIMEOUT + 10)
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

        cfg = load_config(_telegram_bot_config_file(), TelegramBotConfig) or TelegramBotConfig()
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
            await self._message_callback(PlatformMessage(
                platform=self.spec.platform_id,
                sender_id=str(from_user.get("id", "")),
                sender_name=sender_name or str(from_user.get("id", "unknown")),
                text=text,
                channel_id=str(chat.get("id", "")),
                channel_name=chat.get("title", chat.get("first_name", "")),
                message_id=str(message.get("message_id", "")),
                timestamp=ts,
                raw=update,
            ))

    # ----- API -----
    async def get_me(self) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("getMe"))

    async def send_photo(self, chat_id: Union[int, str], photo: str,
                         caption: Optional[str] = None, parse_mode: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return await _telegram_acall(self._api_url("sendPhoto"), json=payload)

    async def send_document(self, chat_id: Union[int, str], document: str,
                            caption: Optional[str] = None, parse_mode: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "document": document}
        if caption:
            payload["caption"] = caption
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return await _telegram_acall(self._api_url("sendDocument"), json=payload)

    async def get_updates(self, offset: Optional[int] = None, limit: int = 100,
                          timeout: int = 0, allowed_updates: Optional[List[str]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"limit": limit, "timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates:
            payload["allowed_updates"] = allowed_updates
        return await _telegram_acall(self._api_url("getUpdates"), json=payload, timeout=timeout + 10)

    async def get_chat(self, chat_id: Union[int, str]) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("getChat"), json={"chat_id": chat_id})

    async def get_chat_member(self, chat_id: Union[int, str], user_id: int) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("getChatMember"),
                                      json={"chat_id": chat_id, "user_id": user_id})

    async def get_chat_members_count(self, chat_id: Union[int, str]) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("getChatMembersCount"), json={"chat_id": chat_id})

    async def forward_message(self, chat_id: Union[int, str], from_chat_id: Union[int, str],
                              message_id: int, disable_notification: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
        if disable_notification:
            payload["disable_notification"] = True
        return await _telegram_acall(self._api_url("forwardMessage"), json=payload)

    # ==================================================================
    # Messages: extended send (with reply_markup support) + lifecycle
    # ==================================================================

    async def send_text_message(self, chat_id: Union[int, str], text: str,
                                parse_mode: Optional[str] = None,
                                reply_to_message_id: Optional[int] = None,
                                disable_notification: bool = False,
                                reply_markup: Optional[Dict[str, Any]] = None,
                                entities: Optional[List[Dict[str, Any]]] = None,
                                disable_web_page_preview: bool = False,
                                message_thread_id: Optional[int] = None) -> Dict[str, Any]:
        """Full-featured sendMessage with inline-keyboard support via reply_markup."""
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode: payload["parse_mode"] = parse_mode
        if reply_to_message_id: payload["reply_to_message_id"] = reply_to_message_id
        if disable_notification: payload["disable_notification"] = True
        if reply_markup is not None: payload["reply_markup"] = reply_markup
        if entities is not None: payload["entities"] = entities
        if disable_web_page_preview: payload["disable_web_page_preview"] = True
        if message_thread_id is not None: payload["message_thread_id"] = message_thread_id
        return await _telegram_acall(self._api_url("sendMessage"), json=payload)

    async def edit_message_text(self, chat_id: Union[int, str], message_id: int,
                                text: str,
                                parse_mode: Optional[str] = None,
                                reply_markup: Optional[Dict[str, Any]] = None,
                                entities: Optional[List[Dict[str, Any]]] = None,
                                disable_web_page_preview: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if parse_mode: payload["parse_mode"] = parse_mode
        if reply_markup is not None: payload["reply_markup"] = reply_markup
        if entities is not None: payload["entities"] = entities
        if disable_web_page_preview: payload["disable_web_page_preview"] = True
        return await _telegram_acall(self._api_url("editMessageText"), json=payload)

    async def edit_message_caption(self, chat_id: Union[int, str], message_id: int,
                                   caption: Optional[str] = None,
                                   parse_mode: Optional[str] = None,
                                   reply_markup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id}
        if caption is not None: payload["caption"] = caption
        if parse_mode: payload["parse_mode"] = parse_mode
        if reply_markup is not None: payload["reply_markup"] = reply_markup
        return await _telegram_acall(self._api_url("editMessageCaption"), json=payload)

    async def edit_message_reply_markup(self, chat_id: Union[int, str], message_id: int,
                                        reply_markup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id,
                                    "reply_markup": reply_markup}
        return await _telegram_acall(self._api_url("editMessageReplyMarkup"), json=payload)

    async def delete_message(self, chat_id: Union[int, str], message_id: int) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("deleteMessage"),
                                      json={"chat_id": chat_id, "message_id": message_id})

    async def delete_messages(self, chat_id: Union[int, str],
                              message_ids: List[int]) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("deleteMessages"),
                                      json={"chat_id": chat_id, "message_ids": message_ids})

    async def copy_message(self, chat_id: Union[int, str],
                           from_chat_id: Union[int, str], message_id: int,
                           caption: Optional[str] = None,
                           parse_mode: Optional[str] = None,
                           reply_markup: Optional[Dict[str, Any]] = None,
                           reply_to_message_id: Optional[int] = None,
                           disable_notification: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id,
        }
        if caption is not None: payload["caption"] = caption
        if parse_mode: payload["parse_mode"] = parse_mode
        if reply_markup is not None: payload["reply_markup"] = reply_markup
        if reply_to_message_id: payload["reply_to_message_id"] = reply_to_message_id
        if disable_notification: payload["disable_notification"] = True
        return await _telegram_acall(self._api_url("copyMessage"), json=payload)

    async def forward_messages(self, chat_id: Union[int, str],
                               from_chat_id: Union[int, str],
                               message_ids: List[int],
                               disable_notification: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id, "from_chat_id": from_chat_id, "message_ids": message_ids,
        }
        if disable_notification: payload["disable_notification"] = True
        return await _telegram_acall(self._api_url("forwardMessages"), json=payload)

    async def pin_message(self, chat_id: Union[int, str], message_id: int,
                          disable_notification: bool = True) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("pinChatMessage"),
                                      json={"chat_id": chat_id, "message_id": message_id,
                                            "disable_notification": disable_notification})

    async def unpin_message(self, chat_id: Union[int, str],
                            message_id: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id}
        if message_id is not None: payload["message_id"] = message_id
        return await _telegram_acall(self._api_url("unpinChatMessage"), json=payload)

    async def unpin_all_messages(self, chat_id: Union[int, str]) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("unpinAllChatMessages"),
                                      json={"chat_id": chat_id})

    async def set_message_reaction(self, chat_id: Union[int, str], message_id: int,
                                   reaction: Optional[List[Dict[str, Any]]] = None,
                                   is_big: bool = False) -> Dict[str, Any]:
        """reaction: list of ReactionType, e.g. [{type:'emoji',emoji:'👍'}]. Pass [] or None to clear."""
        payload: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id,
                                    "reaction": reaction or []}
        if is_big: payload["is_big"] = True
        return await _telegram_acall(self._api_url("setMessageReaction"), json=payload)

    async def send_chat_action(self, chat_id: Union[int, str], action: str) -> Dict[str, Any]:
        """action: typing | upload_photo | record_video | upload_video | record_voice | upload_voice | upload_document | choose_sticker | find_location | record_video_note | upload_video_note."""
        return await _telegram_acall(self._api_url("sendChatAction"),
                                      json={"chat_id": chat_id, "action": action})

    # ==================================================================
    # Media — video / audio / voice / video_note / animation / sticker /
    #          location / venue / contact / dice / poll / media group / files
    # ==================================================================

    async def send_video(self, chat_id: Union[int, str], video: str,
                         caption: Optional[str] = None,
                         duration: Optional[int] = None,
                         width: Optional[int] = None, height: Optional[int] = None,
                         supports_streaming: bool = False,
                         parse_mode: Optional[str] = None,
                         reply_markup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "video": video}
        if caption: payload["caption"] = caption
        if duration is not None: payload["duration"] = duration
        if width is not None: payload["width"] = width
        if height is not None: payload["height"] = height
        if supports_streaming: payload["supports_streaming"] = True
        if parse_mode: payload["parse_mode"] = parse_mode
        if reply_markup is not None: payload["reply_markup"] = reply_markup
        return await _telegram_acall(self._api_url("sendVideo"), json=payload, timeout=60.0)

    async def send_audio(self, chat_id: Union[int, str], audio: str,
                         caption: Optional[str] = None,
                         duration: Optional[int] = None,
                         performer: Optional[str] = None, title: Optional[str] = None,
                         parse_mode: Optional[str] = None,
                         reply_markup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "audio": audio}
        if caption: payload["caption"] = caption
        if duration is not None: payload["duration"] = duration
        if performer: payload["performer"] = performer
        if title: payload["title"] = title
        if parse_mode: payload["parse_mode"] = parse_mode
        if reply_markup is not None: payload["reply_markup"] = reply_markup
        return await _telegram_acall(self._api_url("sendAudio"), json=payload, timeout=60.0)

    async def send_voice(self, chat_id: Union[int, str], voice: str,
                         caption: Optional[str] = None,
                         duration: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "voice": voice}
        if caption: payload["caption"] = caption
        if duration is not None: payload["duration"] = duration
        return await _telegram_acall(self._api_url("sendVoice"), json=payload, timeout=60.0)

    async def send_video_note(self, chat_id: Union[int, str], video_note: str,
                              duration: Optional[int] = None,
                              length: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "video_note": video_note}
        if duration is not None: payload["duration"] = duration
        if length is not None: payload["length"] = length
        return await _telegram_acall(self._api_url("sendVideoNote"), json=payload, timeout=60.0)

    async def send_animation(self, chat_id: Union[int, str], animation: str,
                             caption: Optional[str] = None,
                             duration: Optional[int] = None,
                             width: Optional[int] = None, height: Optional[int] = None,
                             parse_mode: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "animation": animation}
        if caption: payload["caption"] = caption
        if duration is not None: payload["duration"] = duration
        if width is not None: payload["width"] = width
        if height is not None: payload["height"] = height
        if parse_mode: payload["parse_mode"] = parse_mode
        return await _telegram_acall(self._api_url("sendAnimation"), json=payload, timeout=60.0)

    async def send_sticker(self, chat_id: Union[int, str], sticker: str,
                           emoji: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "sticker": sticker}
        if emoji: payload["emoji"] = emoji
        return await _telegram_acall(self._api_url("sendSticker"), json=payload)

    async def send_location(self, chat_id: Union[int, str],
                            latitude: float, longitude: float,
                            live_period: Optional[int] = None,
                            heading: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id,
                                    "latitude": latitude, "longitude": longitude}
        if live_period is not None: payload["live_period"] = live_period
        if heading is not None: payload["heading"] = heading
        return await _telegram_acall(self._api_url("sendLocation"), json=payload)

    async def send_venue(self, chat_id: Union[int, str],
                         latitude: float, longitude: float,
                         title: str, address: str,
                         foursquare_id: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id,
                                    "latitude": latitude, "longitude": longitude,
                                    "title": title, "address": address}
        if foursquare_id: payload["foursquare_id"] = foursquare_id
        return await _telegram_acall(self._api_url("sendVenue"), json=payload)

    async def send_contact(self, chat_id: Union[int, str],
                           phone_number: str, first_name: str,
                           last_name: Optional[str] = None,
                           vcard: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id,
                                    "phone_number": phone_number,
                                    "first_name": first_name}
        if last_name: payload["last_name"] = last_name
        if vcard: payload["vcard"] = vcard
        return await _telegram_acall(self._api_url("sendContact"), json=payload)

    async def send_dice(self, chat_id: Union[int, str],
                        emoji: str = "🎲") -> Dict[str, Any]:
        """emoji: 🎲 (dice) | 🎯 (darts) | 🏀 (basketball) | ⚽ (football) | 🎳 (bowling) | 🎰 (slot machine)."""
        return await _telegram_acall(self._api_url("sendDice"),
                                      json={"chat_id": chat_id, "emoji": emoji})

    async def send_poll(self, chat_id: Union[int, str], question: str,
                        options: List[str],
                        is_anonymous: bool = True,
                        poll_type: str = "regular",
                        allows_multiple_answers: bool = False,
                        correct_option_id: Optional[int] = None,
                        explanation: Optional[str] = None,
                        open_period: Optional[int] = None,
                        is_closed: bool = False) -> Dict[str, Any]:
        """poll_type: regular | quiz."""
        payload: Dict[str, Any] = {
            "chat_id": chat_id, "question": question, "options": options,
            "is_anonymous": is_anonymous, "type": poll_type,
            "allows_multiple_answers": allows_multiple_answers,
        }
        if correct_option_id is not None: payload["correct_option_id"] = correct_option_id
        if explanation: payload["explanation"] = explanation
        if open_period is not None: payload["open_period"] = open_period
        if is_closed: payload["is_closed"] = True
        return await _telegram_acall(self._api_url("sendPoll"), json=payload)

    async def stop_poll(self, chat_id: Union[int, str], message_id: int,
                        reply_markup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id}
        if reply_markup is not None: payload["reply_markup"] = reply_markup
        return await _telegram_acall(self._api_url("stopPoll"), json=payload)

    async def send_media_group(self, chat_id: Union[int, str],
                               media: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send 2-10 photos/videos/audios/documents as an album. media: [{type:'photo',media:'url',caption:'...'}, ...]."""
        return await _telegram_acall(self._api_url("sendMediaGroup"),
                                      json={"chat_id": chat_id, "media": media},
                                      timeout=60.0)

    async def get_file(self, file_id: str) -> Dict[str, Any]:
        """Resolve a file_id to a downloadable file_path."""
        return await _telegram_acall(self._api_url("getFile"), json={"file_id": file_id})

    async def download_file(self, file_id: str, dest_path: str) -> Dict[str, Any]:
        """Resolve file_id, then download the file to dest_path."""
        import os
        info = await self.get_file(file_id)
        if "error" in info:
            return info
        file_path = info.get("result", {}).get("file_path")
        if not file_path:
            return {"error": "getFile returned no file_path"}
        cred = self._load()
        url = f"{TELEGRAM_API_BASE}/file/bot{cred.bot_token}/{file_path}"
        try:
            with httpx.stream("GET", url, timeout=120.0) as resp:
                if resp.status_code != 200:
                    return {"error": f"Download failed: HTTP {resp.status_code}",
                            "details": resp.read().decode("utf-8", errors="replace")[:500]}
                dest_path = os.path.abspath(dest_path)
                parent = os.path.dirname(dest_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                bytes_written = 0
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                        f.write(chunk)
                        bytes_written += len(chunk)
                return {"ok": True, "result": {"path": dest_path,
                                                "bytes_written": bytes_written,
                                                "file_path": file_path}}
        except (httpx.HTTPError, OSError) as e:
            return {"error": str(e)}

    # ==================================================================
    # Chat admin — ban / restrict / promote / permissions / title / photo / invites
    # ==================================================================

    async def ban_chat_member(self, chat_id: Union[int, str], user_id: int,
                              until_date: Optional[int] = None,
                              revoke_messages: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "user_id": user_id}
        if until_date is not None: payload["until_date"] = until_date
        if revoke_messages: payload["revoke_messages"] = True
        return await _telegram_acall(self._api_url("banChatMember"), json=payload)

    async def unban_chat_member(self, chat_id: Union[int, str], user_id: int,
                                only_if_banned: bool = True) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("unbanChatMember"),
                                      json={"chat_id": chat_id, "user_id": user_id,
                                            "only_if_banned": only_if_banned})

    async def restrict_chat_member(self, chat_id: Union[int, str], user_id: int,
                                   permissions: Dict[str, Any],
                                   until_date: Optional[int] = None) -> Dict[str, Any]:
        """permissions: ChatPermissions object (can_send_messages, can_send_media, ...)."""
        payload: Dict[str, Any] = {"chat_id": chat_id, "user_id": user_id,
                                    "permissions": permissions}
        if until_date is not None: payload["until_date"] = until_date
        return await _telegram_acall(self._api_url("restrictChatMember"), json=payload)

    async def promote_chat_member(self, chat_id: Union[int, str], user_id: int,
                                  is_anonymous: Optional[bool] = None,
                                  can_manage_chat: Optional[bool] = None,
                                  can_delete_messages: Optional[bool] = None,
                                  can_manage_video_chats: Optional[bool] = None,
                                  can_restrict_members: Optional[bool] = None,
                                  can_promote_members: Optional[bool] = None,
                                  can_change_info: Optional[bool] = None,
                                  can_invite_users: Optional[bool] = None,
                                  can_post_messages: Optional[bool] = None,
                                  can_edit_messages: Optional[bool] = None,
                                  can_pin_messages: Optional[bool] = None,
                                  can_manage_topics: Optional[bool] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "user_id": user_id}
        for k, v in {
            "is_anonymous": is_anonymous, "can_manage_chat": can_manage_chat,
            "can_delete_messages": can_delete_messages,
            "can_manage_video_chats": can_manage_video_chats,
            "can_restrict_members": can_restrict_members,
            "can_promote_members": can_promote_members,
            "can_change_info": can_change_info, "can_invite_users": can_invite_users,
            "can_post_messages": can_post_messages, "can_edit_messages": can_edit_messages,
            "can_pin_messages": can_pin_messages, "can_manage_topics": can_manage_topics,
        }.items():
            if v is not None:
                payload[k] = v
        return await _telegram_acall(self._api_url("promoteChatMember"), json=payload)

    async def set_chat_administrator_custom_title(self, chat_id: Union[int, str],
                                                  user_id: int,
                                                  custom_title: str) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("setChatAdministratorCustomTitle"),
                                      json={"chat_id": chat_id, "user_id": user_id,
                                            "custom_title": custom_title})

    async def set_chat_permissions(self, chat_id: Union[int, str],
                                   permissions: Dict[str, Any]) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("setChatPermissions"),
                                      json={"chat_id": chat_id, "permissions": permissions})

    async def set_chat_title(self, chat_id: Union[int, str], title: str) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("setChatTitle"),
                                      json={"chat_id": chat_id, "title": title})

    async def set_chat_description(self, chat_id: Union[int, str],
                                   description: str) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("setChatDescription"),
                                      json={"chat_id": chat_id, "description": description})

    async def delete_chat_photo(self, chat_id: Union[int, str]) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("deleteChatPhoto"),
                                      json={"chat_id": chat_id})

    async def leave_chat(self, chat_id: Union[int, str]) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("leaveChat"), json={"chat_id": chat_id})

    async def export_chat_invite_link(self, chat_id: Union[int, str]) -> Dict[str, Any]:
        """Revoke previous primary invite link and generate a new one."""
        return await _telegram_acall(self._api_url("exportChatInviteLink"),
                                      json={"chat_id": chat_id})

    async def create_chat_invite_link(self, chat_id: Union[int, str],
                                      name: Optional[str] = None,
                                      expire_date: Optional[int] = None,
                                      member_limit: Optional[int] = None,
                                      creates_join_request: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id}
        if name: payload["name"] = name
        if expire_date is not None: payload["expire_date"] = expire_date
        if member_limit is not None: payload["member_limit"] = member_limit
        if creates_join_request: payload["creates_join_request"] = True
        return await _telegram_acall(self._api_url("createChatInviteLink"), json=payload)

    async def edit_chat_invite_link(self, chat_id: Union[int, str], invite_link: str,
                                    name: Optional[str] = None,
                                    expire_date: Optional[int] = None,
                                    member_limit: Optional[int] = None,
                                    creates_join_request: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"chat_id": chat_id, "invite_link": invite_link}
        if name is not None: payload["name"] = name
        if expire_date is not None: payload["expire_date"] = expire_date
        if member_limit is not None: payload["member_limit"] = member_limit
        if creates_join_request: payload["creates_join_request"] = True
        return await _telegram_acall(self._api_url("editChatInviteLink"), json=payload)

    async def revoke_chat_invite_link(self, chat_id: Union[int, str],
                                      invite_link: str) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("revokeChatInviteLink"),
                                      json={"chat_id": chat_id, "invite_link": invite_link})

    async def approve_chat_join_request(self, chat_id: Union[int, str],
                                        user_id: int) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("approveChatJoinRequest"),
                                      json={"chat_id": chat_id, "user_id": user_id})

    async def decline_chat_join_request(self, chat_id: Union[int, str],
                                        user_id: int) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("declineChatJoinRequest"),
                                      json={"chat_id": chat_id, "user_id": user_id})

    async def get_chat_administrators(self, chat_id: Union[int, str]) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("getChatAdministrators"),
                                      json={"chat_id": chat_id})

    # ==================================================================
    # Bot config — commands / description / menu button / default admin rights
    # ==================================================================

    async def set_my_commands(self, commands: List[Dict[str, str]],
                              scope: Optional[Dict[str, Any]] = None,
                              language_code: Optional[str] = None) -> Dict[str, Any]:
        """commands: [{command, description}, ...]. scope: BotCommandScope object (optional)."""
        payload: Dict[str, Any] = {"commands": commands}
        if scope is not None: payload["scope"] = scope
        if language_code: payload["language_code"] = language_code
        return await _telegram_acall(self._api_url("setMyCommands"), json=payload)

    async def get_my_commands(self, scope: Optional[Dict[str, Any]] = None,
                              language_code: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if scope is not None: payload["scope"] = scope
        if language_code: payload["language_code"] = language_code
        return await _telegram_acall(self._api_url("getMyCommands"), json=payload)

    async def delete_my_commands(self, scope: Optional[Dict[str, Any]] = None,
                                 language_code: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if scope is not None: payload["scope"] = scope
        if language_code: payload["language_code"] = language_code
        return await _telegram_acall(self._api_url("deleteMyCommands"), json=payload)

    async def set_my_description(self, description: str,
                                 language_code: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"description": description}
        if language_code: payload["language_code"] = language_code
        return await _telegram_acall(self._api_url("setMyDescription"), json=payload)

    async def get_my_description(self, language_code: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if language_code: payload["language_code"] = language_code
        return await _telegram_acall(self._api_url("getMyDescription"), json=payload)

    async def set_my_short_description(self, short_description: str,
                                       language_code: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"short_description": short_description}
        if language_code: payload["language_code"] = language_code
        return await _telegram_acall(self._api_url("setMyShortDescription"), json=payload)

    async def set_my_name(self, name: str,
                          language_code: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"name": name}
        if language_code: payload["language_code"] = language_code
        return await _telegram_acall(self._api_url("setMyName"), json=payload)

    async def set_chat_menu_button(self, chat_id: Optional[Union[int, str]] = None,
                                   menu_button: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """menu_button: MenuButton object (commands | web_app | default). chat_id: omit for default."""
        payload: Dict[str, Any] = {}
        if chat_id is not None: payload["chat_id"] = chat_id
        if menu_button is not None: payload["menu_button"] = menu_button
        return await _telegram_acall(self._api_url("setChatMenuButton"), json=payload)

    async def get_chat_menu_button(self, chat_id: Optional[Union[int, str]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if chat_id is not None: payload["chat_id"] = chat_id
        return await _telegram_acall(self._api_url("getChatMenuButton"), json=payload)

    async def set_my_default_administrator_rights(
        self, rights: Optional[Dict[str, Any]] = None,
        for_channels: bool = False,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"for_channels": for_channels}
        if rights is not None: payload["rights"] = rights
        return await _telegram_acall(self._api_url("setMyDefaultAdministratorRights"),
                                      json=payload)

    async def get_my_default_administrator_rights(self, for_channels: bool = False) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("getMyDefaultAdministratorRights"),
                                      json={"for_channels": for_channels})

    # ==================================================================
    # Callback queries (for inline-keyboard interactions)
    # ==================================================================

    async def answer_callback_query(self, callback_query_id: str,
                                    text: Optional[str] = None,
                                    show_alert: bool = False,
                                    url: Optional[str] = None,
                                    cache_time: int = 0) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id,
                                    "show_alert": show_alert, "cache_time": cache_time}
        if text: payload["text"] = text
        if url: payload["url"] = url
        return await _telegram_acall(self._api_url("answerCallbackQuery"), json=payload)

    # ==================================================================
    # Webhook configuration
    # ==================================================================

    async def set_webhook(self, url: str,
                          secret_token: Optional[str] = None,
                          ip_address: Optional[str] = None,
                          max_connections: Optional[int] = None,
                          allowed_updates: Optional[List[str]] = None,
                          drop_pending_updates: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"url": url, "drop_pending_updates": drop_pending_updates}
        if secret_token: payload["secret_token"] = secret_token
        if ip_address: payload["ip_address"] = ip_address
        if max_connections is not None: payload["max_connections"] = max_connections
        if allowed_updates is not None: payload["allowed_updates"] = allowed_updates
        return await _telegram_acall(self._api_url("setWebhook"), json=payload)

    async def delete_webhook(self, drop_pending_updates: bool = False) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("deleteWebhook"),
                                      json={"drop_pending_updates": drop_pending_updates})

    async def get_webhook_info(self) -> Dict[str, Any]:
        return await _telegram_acall(self._api_url("getWebhookInfo"))

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
                    contacts.append({
                        "chat_id": chat_id, "type": chat_type, "name": full_name or chat.get("username", ""),
                        "username": chat.get("username", ""),
                        "first_name": chat.get("first_name", ""), "last_name": chat.get("last_name", ""),
                    })
            sender = message.get("from", {})
            sender_id = sender.get("id")
            if sender_id and sender_id not in seen_ids:
                seen_ids.add(sender_id)
                full_name = f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip()
                searchable = f"{full_name} {sender.get('username', '')}".lower()
                if search_lower in searchable and not sender.get("is_bot"):
                    contacts.append({
                        "chat_id": sender_id, "type": "private",
                        "name": full_name or sender.get("username", ""), "username": sender.get("username", ""),
                        "first_name": sender.get("first_name", ""), "last_name": sender.get("last_name", ""),
                    })

        if contacts:
            return {"ok": True, "result": {"contacts": contacts, "count": len(contacts)}}
        return {"error": f"No contacts found matching '{name}'",
                "details": {"searched_updates": len(updates), "name": name}}
