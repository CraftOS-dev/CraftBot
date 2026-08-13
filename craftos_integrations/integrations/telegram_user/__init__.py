# -*- coding: utf-8 -*-
"""Telegram MTProto (user account) integration - handler (phone+code+QR) + client (Telethon listener)."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import webbrowser
from dataclasses import dataclass
from datetime import timezone
from typing import Any, Dict, List, Optional, Tuple, Union

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
    """``telegram_user.json`` â†’ ``telegram_user_config.json``."""
    stem = TELEGRAM_USER.cred_file
    return (stem[:-5] if stem.endswith(".json") else stem) + "_config.json"


# Module-level pending auth state (mirrors original handlers.py behaviour)
_pending_telegram_auth: Dict[str, Dict[str, Any]] = {}


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(TELEGRAM_USER.name)
class TelegramUserHandler(IntegrationHandler):
    spec = TELEGRAM_USER
    display_name = "Telegram (User)"
    description = "MTProto user account"
    # Two-phase token connect: submit #1 (phone only) sends the login code
    # and reports back; submit #2 (phone + code [+ 2FA password]) completes.
    # The CLI `/telegram_user login` subcommand flow is unchanged.
    auth_type = "token"
    icon = "telegram"
    connect_help = [
        "One-time app credentials: open my.telegram.org, log in, click "
        "'API development tools', submit the form (any app name works)",
        "Set the api_id and api_hash as TELEGRAM_API_ID and "
        "TELEGRAM_API_HASH in CraftBot config (they are NOT entered below)",
        "Connect step 1: enter your phone number only (international "
        "format, e.g. +923001234567) and submit - a login code is sent "
        "to your Telegram app",
        "Connect step 2: submit again with the same phone number AND the "
        "code filled in (add your 2FA password if your account has one)",
    ]
    # `code` and `password` stay empty on the first submit — the label
    # "(optional)" / "(optional…" placeholder mark them non-required for
    # the connect flow's missing-field check.
    fields: List = [
        {
            "key": "phone_number",
            "label": "Phone Number",
            "placeholder": "+923001234567",
            "password": False,
        },
        {
            "key": "code",
            "label": "Login Code (optional)",
            "placeholder": "(optional) leave empty on first submit",
            "password": False,
        },
        {
            "key": "password",
            "label": "2FA Password (optional)",
            "placeholder": "(optional) only if two-step verification is on",
            "password": True,
        },
    ]

    config_class = TelegramUserConfig
    config_fields = [
        {
            "key": "self_messages_only",
            "label": "Self-messages only",
            "type": "checkbox",
            "help": "Only forward messages from your own Saved Messages chat. "
            "Drops DMs from contacts and group/channel messages before they reach the agent.",
        },
    ]

    @property
    def subcommands(self) -> List[str]:
        return ["login", "login-qr", "logout", "status"]

    async def handle(self, sub: str, args: List[str]) -> Tuple[bool, str]:
        if sub == "login-qr":
            return await self._login_qr(args)
        if sub == "login":
            # Two-step: phone (+code) flow
            return await self._login_phone(args)
        return await super().handle(sub, args)

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        return await self._login_phone(args)

    async def _login_phone(self, args: List[str]) -> Tuple[bool, str]:
        if not args:
            return False, (
                "Usage:\n"
                "  Step 1: /telegram_user login <phone_number>\n"
                "  Step 2: /telegram_user login <phone_number> <code> [2fa_password]\n\n"
                "Requires TELEGRAM_API_ID and TELEGRAM_API_HASH env vars or configure(oauth=...).\n"
                "Get them from https://my.telegram.org"
            )

        phone = args[0]
        api_id_str = ConfigStore.get_oauth("TELEGRAM_API_ID")
        api_hash = ConfigStore.get_oauth("TELEGRAM_API_HASH")
        if not api_id_str or not api_hash:
            return False, (
                "Not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH.\n"
                "Get them from https://my.telegram.org â†’ API development tools."
            )
        try:
            api_id = int(api_id_str)
        except ValueError:
            return False, "TELEGRAM_API_ID must be a number."

        from . import _telegram_mtproto as helpers

        # Step 2: phone + code â†’ complete
        if len(args) >= 2:
            code = args[1]
            password = args[2] if len(args) > 2 else None

            pending = _pending_telegram_auth.get(phone)
            if not pending:
                return (
                    False,
                    f"No pending auth for {phone}. Run /telegram_user login {phone} first.",
                )

            result = await helpers.complete_auth(
                api_id=api_id,
                api_hash=api_hash,
                phone_number=phone,
                code=code,
                phone_code_hash=pending["phone_code_hash"],
                password=password,
                pending_session_string=pending["session_string"],
            )

            if "error" in result:
                details = result.get("details", {})
                if details.get("status") == "2fa_required":
                    return (
                        False,
                        "2FA enabled.\nUsage: /telegram_user login <phone> <code> <2fa_password>",
                    )
                if details.get("status") == "invalid_code":
                    return False, "Invalid verification code. Try again."
                if details.get("status") == "code_expired":
                    _pending_telegram_auth.pop(phone, None)
                    return (
                        False,
                        "Code expired. Run /telegram_user login <phone> again.",
                    )
                return False, f"Auth failed: {result['error']}"

            auth = result["result"]
            _pending_telegram_auth.pop(phone, None)

            save_credential(
                self.spec.cred_file,
                TelegramUserCredential(
                    session_string=auth["session_string"],
                    api_id=str(api_id),
                    api_hash=api_hash,
                    phone_number=auth.get("phone", phone),
                ),
            )

            account_name = (
                f"{auth.get('first_name', '')} {auth.get('last_name', '')}".strip()
            )
            username = f" (@{auth['username']})" if auth.get("username") else ""
            return True, f"Telegram user connected: {account_name}{username}"

        # Step 1: send OTP
        result = await helpers.start_auth(
            api_id=api_id, api_hash=api_hash, phone_number=phone
        )
        if "error" in result:
            return False, f"Failed to send code: {result['error']}"

        _pending_telegram_auth[phone] = {
            "phone_code_hash": result["result"]["phone_code_hash"],
            "session_string": result["result"]["session_string"],
        }
        return True, (
            f"Verification code sent to {phone}.\n"
            f"Check your Telegram app (or SMS) for the code, then run:\n"
            f"  /telegram_user login {phone} <code>"
        )

    async def _login_qr(self, args: List[str]) -> Tuple[bool, str]:
        api_id_str = ConfigStore.get_oauth("TELEGRAM_API_ID")
        api_hash = ConfigStore.get_oauth("TELEGRAM_API_HASH")
        if not api_id_str or not api_hash:
            return False, "Not configured. Set TELEGRAM_API_ID and TELEGRAM_API_HASH."
        try:
            api_id = int(api_id_str)
        except ValueError:
            return False, "TELEGRAM_API_ID must be a number."

        try:
            import qrcode as _qrcode_check  # noqa: F401
        except ImportError:
            return False, "qrcode package not installed. Run: pip install qrcode[pil]"

        qr_file_path = None
        qr_error = None

        def on_qr_url(url: str):
            nonlocal qr_file_path, qr_error
            try:
                import qrcode

                qr = qrcode.QRCode(version=1, box_size=10, border=4)
                qr.add_data(url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                qr_file_path = os.path.join(
                    tempfile.gettempdir(), "telegram_qr_login.png"
                )
                img.save(qr_file_path)
                if sys.platform == "win32":
                    os.startfile(qr_file_path)
                else:
                    webbrowser.open(f"file://{qr_file_path}")
            except Exception as e:
                qr_error = str(e)

        from . import _telegram_mtproto as helpers

        result = await helpers.qr_login(
            api_id=api_id,
            api_hash=api_hash,
            on_qr_url=on_qr_url,
            timeout=120,
        )

        if qr_file_path and os.path.exists(qr_file_path):
            try:
                os.remove(qr_file_path)
            except Exception:
                pass

        if "error" in result:
            details = result.get("details", {})
            if details.get("status") == "2fa_required":
                session_str = details.get("session_string", "")
                if session_str:
                    _pending_telegram_auth["__qr_2fa__"] = {
                        "session_string": session_str
                    }
                return False, (
                    "QR scan succeeded but 2FA is enabled.\n"
                    "Complete login with: /telegram_user login <phone> <code> <2fa_password>"
                )
            return False, f"QR login failed: {result['error']}"

        auth = result["result"]
        save_credential(
            self.spec.cred_file,
            TelegramUserCredential(
                session_string=auth["session_string"],
                api_id=str(api_id),
                api_hash=api_hash,
                phone_number=auth.get("phone", ""),
            ),
        )
        account_name = (
            f"{auth.get('first_name', '')} {auth.get('last_name', '')}".strip()
        )
        username = f" (@{auth['username']})" if auth.get("username") else ""
        return True, f"Telegram user linked: {account_name}{username}"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No Telegram user credentials found."
        try:
            from ...manager import get_external_comms_manager

            manager = get_external_comms_manager()
            if manager:
                await manager.stop_platform(self.spec.platform_id)
        except Exception:
            pass
        remove_credential(self.spec.cred_file)
        return True, "Removed Telegram user credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "Telegram user: Not connected"
        cred = load_credential(self.spec.cred_file, TelegramUserCredential)
        label = cred.phone_number if cred and cred.phone_number else "User configured"
        return True, f"Telegram user: Connected\n  - {label}"


# -----------------------------------------------------------------
# Client
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

    async def _handle_event(self, event) -> None:
        msg = event.message
        if not msg or not msg.text:
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
                    text=msg.text,
                    channel_id=str(chat_id),
                    channel_name=channel_name
                    if not is_saved_messages
                    else "Saved Messages",
                    message_id=str(msg.id),
                    timestamp=msg.date.astimezone(timezone.utc) if msg.date else None,
                    raw={"is_self_message": is_saved_messages},
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
