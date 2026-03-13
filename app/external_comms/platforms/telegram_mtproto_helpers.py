"""
Telegram MTProto (User Account) helper functions using Telethon.

These functions provide full access to Telegram features including:
- Reading message history from any chat
- Listing all conversations (dialogs)
- Sending messages as a user (not bot)
- Accessing private chats and groups
"""

import asyncio
from typing import Optional, Dict, Any, List, Union
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
    FloodWaitError,
    AuthKeyUnregisteredError,
)
from telethon.tl.types import User, Chat, Channel, Message


# Legacy: no longer used, kept for cleanup in complete_auth
_pending_auth_sessions: Dict[str, TelegramClient] = {}


async def start_auth(
    api_id: int,
    api_hash: str,
    phone_number: str,
) -> Dict[str, Any]:
    """
    Start the MTProto authentication flow by sending OTP to phone.

    Args:
        api_id: Telegram API ID from my.telegram.org
        api_hash: Telegram API hash from my.telegram.org
        phone_number: Phone number with country code (+1234567890)

    Returns:
        Dict with status, phone_code_hash, and session_string for completing auth
    """
    client = None
    try:
        # Create a new client with StringSession for portability
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()

        # Send code request
        result = await client.send_code_request(phone_number)

        # Save the session string - we need to reuse this session in complete_auth
        # Telegram requires the same session for send_code_request and sign_in
        session_string = client.session.save()

        await client.disconnect()

        return {
            "ok": True,
            "result": {
                "phone_code_hash": result.phone_code_hash,
                "phone_number": phone_number,
                "session_string": session_string,  # Pass this to complete_auth
                "status": "code_sent",
            }
        }

    except FloodWaitError as e:
        if client:
            await client.disconnect()
        return {
            "error": f"Too many attempts. Please wait {e.seconds} seconds.",
            "details": {"flood_wait_seconds": e.seconds}
        }
    except Exception as e:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        return {
            "error": f"Failed to start auth: {str(e)}",
            "details": {"exception": type(e).__name__}
        }


async def qr_login(
    api_id: int,
    api_hash: str,
    on_qr_url: Optional[Any] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    """
    Login to Telegram by scanning a QR code with the phone app.

    Uses Telethon's built-in ``client.qr_login()`` which handles the full
    ExportLoginToken → AcceptLoginToken → ImportLoginToken flow.

    Args:
        api_id: Telegram API ID from my.telegram.org
        api_hash: Telegram API hash from my.telegram.org
        on_qr_url: Optional callback(url: str) called with the ``tg://login?token=...``
                    URL so the caller can render it as a QR code.
        timeout: Seconds to wait for the user to scan (default 120).

    Returns:
        Dict with session_string and user info on success, or error details.
    """
    client = None
    try:
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()

        qr = await client.qr_login()

        # Notify caller so it can display the QR code
        if on_qr_url:
            on_qr_url(qr.url)

        # Wait for the user to scan the QR code
        # If the token expires (every ~30s) Telethon auto-refreshes,
        # but we need to re-notify the caller with the new URL.
        try:
            user = await asyncio.wait_for(qr.wait(timeout), timeout=timeout)
        except asyncio.TimeoutError:
            await client.disconnect()
            return {
                "error": "QR login timed out. Please try again.",
                "details": {"status": "timeout"},
            }

    except SessionPasswordNeededError:
        # 2FA is enabled — need password to finish.
        # Save session so handler can call sign_in(password=...) later.
        session_string = client.session.save()
        await client.disconnect()
        return {
            "error": "Two-factor authentication is enabled. Please provide your 2FA password.",
            "details": {
                "status": "2fa_required",
                "session_string": session_string,
            },
        }
    except Exception as e:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        return {
            "error": f"QR login failed: {str(e)}",
            "details": {"exception": type(e).__name__},
        }

    # Success — extract user info and session string
    try:
        me = await client.get_me()
        session_string = client.session.save()
        await client.disconnect()

        return {
            "ok": True,
            "result": {
                "session_string": session_string,
                "user_id": me.id,
                "first_name": me.first_name or "",
                "last_name": me.last_name or "",
                "username": me.username or "",
                "phone": me.phone or "",
                "status": "authenticated",
            },
        }
    except Exception as e:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        return {
            "error": f"QR login succeeded but failed to get user info: {str(e)}",
            "details": {"exception": type(e).__name__},
        }


async def complete_auth(
    api_id: int,
    api_hash: str,
    phone_number: str,
    code: str,
    phone_code_hash: str,
    password: Optional[str] = None,
    pending_session_string: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Complete MTProto authentication with OTP code (and optional 2FA password).

    Args:
        api_id: Telegram API ID
        api_hash: Telegram API hash
        phone_number: Phone number used in start_auth
        code: OTP code received via SMS/Telegram
        phone_code_hash: Hash returned from start_auth
        password: Optional 2FA password if enabled
        pending_session_string: Session string from start_auth (required)

    Returns:
        Dict with session_string and user info on success
    """
    client = None
    try:
        # Use the session from start_auth - Telegram requires the same session
        # for send_code_request and sign_in
        session = StringSession(pending_session_string) if pending_session_string else StringSession()
        client = TelegramClient(session, api_id, api_hash)
        await client.connect()

        try:
            # Try to sign in with code
            await client.sign_in(
                phone=phone_number,
                code=code,
                phone_code_hash=phone_code_hash,
            )

        except SessionPasswordNeededError:
            # 2FA is enabled
            if not password:
                await client.disconnect()
                return {
                    "error": "Two-factor authentication is enabled. Please provide password.",
                    "details": {"requires_2fa": True, "status": "2fa_required"}
                }

            try:
                await client.sign_in(password=password)
            except PasswordHashInvalidError:
                await client.disconnect()
                return {
                    "error": "Invalid 2FA password.",
                    "details": {"status": "invalid_password"}
                }

        # Get user info
        me = await client.get_me()
        session_string = client.session.save()

        # Clean up pending session (from start_auth, if any)
        if phone_number in _pending_auth_sessions:
            try:
                old_client = _pending_auth_sessions.pop(phone_number)
                await old_client.disconnect()
            except Exception:
                pass

        await client.disconnect()

        return {
            "ok": True,
            "result": {
                "session_string": session_string,
                "user_id": me.id,
                "first_name": me.first_name or "",
                "last_name": me.last_name or "",
                "username": me.username or "",
                "phone": me.phone or phone_number,
                "status": "authenticated",
            }
        }

    except PhoneCodeInvalidError:
        if client:
            await client.disconnect()
        return {
            "error": "Invalid verification code.",
            "details": {"status": "invalid_code"}
        }
    except PhoneCodeExpiredError:
        if client:
            await client.disconnect()
        return {
            "error": "Verification code has expired. Please request a new one.",
            "details": {"status": "code_expired"}
        }
    except FloodWaitError as e:
        if client:
            await client.disconnect()
        return {
            "error": f"Too many attempts. Please wait {e.seconds} seconds.",
            "details": {"flood_wait_seconds": e.seconds}
        }
    except Exception as e:
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        return {
            "error": f"Failed to complete auth: {str(e)}",
            "details": {"exception": type(e).__name__}
        }


async def get_me(
    session_string: str,
    api_id: int,
    api_hash: str,
) -> Dict[str, Any]:
    """
    Get information about the authenticated user.

    Args:
        session_string: Telethon StringSession
        api_id: Telegram API ID
        api_hash: Telegram API hash

    Returns:
        Dict with user info
    """
    try:
        async with TelegramClient(StringSession(session_string), api_id, api_hash) as client:
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
                }
            }

    except AuthKeyUnregisteredError:
        return {
            "error": "Session has expired or been revoked. Please re-authenticate.",
            "details": {"status": "session_expired"}
        }
    except Exception as e:
        return {
            "error": f"Failed to get user info: {str(e)}",
            "details": {"exception": type(e).__name__}
        }


async def get_dialogs(
    session_string: str,
    api_id: int,
    api_hash: str,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Get list of all conversations (dialogs/chats).

    Args:
        session_string: Telethon StringSession
        api_id: Telegram API ID
        api_hash: Telegram API hash
        limit: Maximum number of dialogs to return

    Returns:
        Dict with list of dialogs
    """
    try:
        async with TelegramClient(StringSession(session_string), api_id, api_hash) as client:
            dialogs = await client.get_dialogs(limit=limit)

            result = []
            for dialog in dialogs:
                entity = dialog.entity

                dialog_info = {
                    "id": dialog.id,
                    "name": dialog.name or "",
                    "unread_count": dialog.unread_count,
                    "is_pinned": dialog.pinned,
                    "is_archived": dialog.archived,
                }

                # Determine type and add type-specific info
                if isinstance(entity, User):
                    dialog_info["type"] = "private"
                    dialog_info["username"] = entity.username or ""
                    dialog_info["phone"] = entity.phone or ""
                    dialog_info["is_bot"] = entity.bot
                elif isinstance(entity, Chat):
                    dialog_info["type"] = "group"
                    dialog_info["participants_count"] = getattr(entity, 'participants_count', None)
                elif isinstance(entity, Channel):
                    dialog_info["type"] = "channel" if entity.broadcast else "supergroup"
                    dialog_info["username"] = entity.username or ""
                    dialog_info["participants_count"] = getattr(entity, 'participants_count', None)
                else:
                    dialog_info["type"] = "unknown"

                # Last message preview
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
                }
            }

    except AuthKeyUnregisteredError:
        return {
            "error": "Session has expired or been revoked. Please re-authenticate.",
            "details": {"status": "session_expired"}
        }
    except Exception as e:
        return {
            "error": f"Failed to get dialogs: {str(e)}",
            "details": {"exception": type(e).__name__}
        }


async def get_messages(
    session_string: str,
    api_id: int,
    api_hash: str,
    chat_id: Union[int, str],
    limit: int = 50,
    offset_id: int = 0,
) -> Dict[str, Any]:
    """
    Get message history from a chat.

    Args:
        session_string: Telethon StringSession
        api_id: Telegram API ID
        api_hash: Telegram API hash
        chat_id: Chat ID, username, or phone number
        limit: Maximum number of messages to return
        offset_id: Message ID to start from (for pagination)

    Returns:
        Dict with list of messages
    """
    try:
        async with TelegramClient(StringSession(session_string), api_id, api_hash) as client:
            # Get entity (handles various formats)
            entity = await client.get_entity(chat_id)

            # Get messages
            messages = await client.get_messages(
                entity,
                limit=limit,
                offset_id=offset_id,
            )

            result = []
            for msg in messages:
                message_info = {
                    "id": msg.id,
                    "date": msg.date.isoformat() if msg.date else None,
                    "text": msg.text or "",
                    "out": msg.out,  # True if sent by us
                }

                # Sender info
                if msg.sender:
                    sender = msg.sender
                    message_info["sender"] = {
                        "id": sender.id,
                        "name": _get_display_name(sender),
                        "username": getattr(sender, 'username', None) or "",
                    }

                # Media info
                if msg.media:
                    message_info["has_media"] = True
                    message_info["media_type"] = type(msg.media).__name__

                # Reply info
                if msg.reply_to:
                    message_info["reply_to_msg_id"] = msg.reply_to.reply_to_msg_id

                # Forward info
                if msg.forward:
                    message_info["is_forwarded"] = True

                result.append(message_info)

            # Get chat info
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
                }
            }

    except AuthKeyUnregisteredError:
        return {
            "error": "Session has expired or been revoked. Please re-authenticate.",
            "details": {"status": "session_expired"}
        }
    except ValueError as e:
        return {
            "error": f"Could not find chat: {str(e)}",
            "details": {"chat_id": str(chat_id)}
        }
    except Exception as e:
        return {
            "error": f"Failed to get messages: {str(e)}",
            "details": {"exception": type(e).__name__}
        }


async def send_message(
    session_string: str,
    api_id: int,
    api_hash: str,
    chat_id: Union[int, str],
    text: str,
    reply_to: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Send a text message to a chat.

    Args:
        session_string: Telethon StringSession
        api_id: Telegram API ID
        api_hash: Telegram API hash
        chat_id: Chat ID, username, or phone number
        text: Message text
        reply_to: Optional message ID to reply to

    Returns:
        Dict with sent message info
    """
    try:
        async with TelegramClient(StringSession(session_string), api_id, api_hash) as client:
            entity = await client.get_entity(chat_id)

            msg = await client.send_message(
                entity,
                text,
                reply_to=reply_to,
            )

            return {
                "ok": True,
                "result": {
                    "message_id": msg.id,
                    "date": msg.date.isoformat() if msg.date else None,
                    "chat_id": entity.id,
                    "text": msg.text,
                }
            }

    except AuthKeyUnregisteredError:
        return {
            "error": "Session has expired or been revoked. Please re-authenticate.",
            "details": {"status": "session_expired"}
        }
    except ValueError as e:
        return {
            "error": f"Could not find chat: {str(e)}",
            "details": {"chat_id": str(chat_id)}
        }
    except FloodWaitError as e:
        return {
            "error": f"Rate limited. Please wait {e.seconds} seconds.",
            "details": {"flood_wait_seconds": e.seconds}
        }
    except Exception as e:
        return {
            "error": f"Failed to send message: {str(e)}",
            "details": {"exception": type(e).__name__}
        }


async def send_file(
    session_string: str,
    api_id: int,
    api_hash: str,
    chat_id: Union[int, str],
    file_path: str,
    caption: Optional[str] = None,
    reply_to: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Send a file/media to a chat.

    Args:
        session_string: Telethon StringSession
        api_id: Telegram API ID
        api_hash: Telegram API hash
        chat_id: Chat ID, username, or phone number
        file_path: Path to file or URL
        caption: Optional caption for the file
        reply_to: Optional message ID to reply to

    Returns:
        Dict with sent message info
    """
    try:
        async with TelegramClient(StringSession(session_string), api_id, api_hash) as client:
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
                }
            }

    except AuthKeyUnregisteredError:
        return {
            "error": "Session has expired or been revoked. Please re-authenticate.",
            "details": {"status": "session_expired"}
        }
    except ValueError as e:
        return {
            "error": f"Could not find chat: {str(e)}",
            "details": {"chat_id": str(chat_id)}
        }
    except FileNotFoundError:
        return {
            "error": f"File not found: {file_path}",
            "details": {"file_path": file_path}
        }
    except Exception as e:
        return {
            "error": f"Failed to send file: {str(e)}",
            "details": {"exception": type(e).__name__}
        }


async def search_contacts(
    session_string: str,
    api_id: int,
    api_hash: str,
    query: str,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Search for contacts/users by name or username.

    Args:
        session_string: Telethon StringSession
        api_id: Telegram API ID
        api_hash: Telegram API hash
        query: Search query (name or username)
        limit: Maximum results to return

    Returns:
        Dict with matching contacts
    """
    try:
        async with TelegramClient(StringSession(session_string), api_id, api_hash) as client:
            # Search global
            result = await client.get_dialogs(limit=100)

            contacts = []
            query_lower = query.lower()

            for dialog in result:
                entity = dialog.entity
                name = _get_display_name(entity).lower()
                username = (getattr(entity, 'username', '') or '').lower()

                if query_lower in name or query_lower in username:
                    contact_info = {
                        "id": entity.id,
                        "name": _get_display_name(entity),
                        "username": getattr(entity, 'username', None) or "",
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
                }
            }

    except AuthKeyUnregisteredError:
        return {
            "error": "Session has expired or been revoked. Please re-authenticate.",
            "details": {"status": "session_expired"}
        }
    except Exception as e:
        return {
            "error": f"Failed to search contacts: {str(e)}",
            "details": {"exception": type(e).__name__}
        }


async def validate_session(
    session_string: str,
    api_id: int,
    api_hash: str,
) -> Dict[str, Any]:
    """
    Validate if a session is still active.

    Args:
        session_string: Telethon StringSession
        api_id: Telegram API ID
        api_hash: Telegram API hash

    Returns:
        Dict with validation status
    """
    try:
        async with TelegramClient(StringSession(session_string), api_id, api_hash) as client:
            me = await client.get_me()

            return {
                "ok": True,
                "result": {
                    "valid": True,
                    "user_id": me.id,
                    "username": me.username or "",
                }
            }

    except AuthKeyUnregisteredError:
        return {
            "ok": True,
            "result": {
                "valid": False,
                "reason": "session_expired",
            }
        }
    except Exception as e:
        return {
            "ok": True,
            "result": {
                "valid": False,
                "reason": str(e),
            }
        }


def _get_display_name(entity) -> str:
    """Get display name for any entity type."""
    if isinstance(entity, User):
        parts = []
        if entity.first_name:
            parts.append(entity.first_name)
        if entity.last_name:
            parts.append(entity.last_name)
        return " ".join(parts) or entity.username or str(entity.id)
    elif hasattr(entity, 'title'):
        return entity.title or ""
    else:
        return str(entity.id)


def _get_entity_type(entity) -> str:
    """Get type string for any entity."""
    if isinstance(entity, User):
        return "bot" if entity.bot else "user"
    elif isinstance(entity, Chat):
        return "group"
    elif isinstance(entity, Channel):
        return "channel" if entity.broadcast else "supergroup"
    else:
        return "unknown"
