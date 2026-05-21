# -*- coding: utf-8 -*-
"""Telegram MTProto auth helpers — underscore-prefixed so the autoloader skips it.

Used only by the telegram_user handler for the phone-code and QR login flows.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import (
        FloodWaitError,
        PasswordHashInvalidError,
        PhoneCodeExpiredError,
        PhoneCodeInvalidError,
        SessionPasswordNeededError,
    )

    _TELETHON_AVAILABLE = True
except ImportError:
    _TELETHON_AVAILABLE = False

_TELETHON_MISSING = {"error": "Telethon not installed. Run: pip install telethon"}


def _unexpected(prefix: str, e: Exception) -> Dict[str, Any]:
    return {"error": f"{prefix}: {e}", "details": {"exception": type(e).__name__}}


@asynccontextmanager
async def _client_for_auth(api_id: int, api_hash: str, session_string: str = ""):
    """Connect a Telethon client and guarantee disconnect on exit (success or error)."""
    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    await client.connect()
    try:
        yield client
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def start_auth(api_id: int, api_hash: str, phone_number: str) -> Dict[str, Any]:
    if not _TELETHON_AVAILABLE:
        return _TELETHON_MISSING
    try:
        async with _client_for_auth(api_id, api_hash) as client:
            result = await client.send_code_request(phone_number)
            return {
                "ok": True,
                "result": {
                    "phone_code_hash": result.phone_code_hash,
                    "phone_number": phone_number,
                    "session_string": client.session.save(),
                    "status": "code_sent",
                },
            }
    except FloodWaitError as e:
        return {
            "error": f"Too many attempts. Please wait {e.seconds} seconds.",
            "details": {"flood_wait_seconds": e.seconds},
        }
    except Exception as e:
        return _unexpected("Failed to start auth", e)


async def qr_login(
    api_id: int, api_hash: str, on_qr_url: Optional[Any] = None, timeout: int = 120
) -> Dict[str, Any]:
    if not _TELETHON_AVAILABLE:
        return _TELETHON_MISSING
    try:
        async with _client_for_auth(api_id, api_hash) as client:
            try:
                qr = await client.qr_login()
                if on_qr_url:
                    on_qr_url(qr.url)
                try:
                    await asyncio.wait_for(qr.wait(timeout), timeout=timeout)
                except asyncio.TimeoutError:
                    return {
                        "error": "QR login timed out. Please try again.",
                        "details": {"status": "timeout"},
                    }
            except SessionPasswordNeededError:
                return {
                    "error": "Two-factor authentication is enabled. Please provide your 2FA password.",
                    "details": {
                        "status": "2fa_required",
                        "session_string": client.session.save(),
                    },
                }

            try:
                me = await client.get_me()
            except Exception as e:
                return _unexpected("QR login succeeded but failed to get user info", e)

            return {
                "ok": True,
                "result": {
                    "session_string": client.session.save(),
                    "user_id": me.id,
                    "first_name": me.first_name or "",
                    "last_name": me.last_name or "",
                    "username": me.username or "",
                    "phone": me.phone or "",
                    "status": "authenticated",
                },
            }
    except Exception as e:
        return _unexpected("QR login failed", e)


async def complete_auth(
    api_id: int,
    api_hash: str,
    phone_number: str,
    code: str,
    phone_code_hash: str,
    password: Optional[str] = None,
    pending_session_string: Optional[str] = None,
) -> Dict[str, Any]:
    if not _TELETHON_AVAILABLE:
        return _TELETHON_MISSING
    try:
        async with _client_for_auth(
            api_id, api_hash, pending_session_string or ""
        ) as client:
            try:
                await client.sign_in(
                    phone=phone_number, code=code, phone_code_hash=phone_code_hash
                )
            except SessionPasswordNeededError:
                if not password:
                    return {
                        "error": "Two-factor authentication is enabled. Please provide password.",
                        "details": {"requires_2fa": True, "status": "2fa_required"},
                    }
                try:
                    await client.sign_in(password=password)
                except PasswordHashInvalidError:
                    return {
                        "error": "Invalid 2FA password.",
                        "details": {"status": "invalid_password"},
                    }

            me = await client.get_me()
            return {
                "ok": True,
                "result": {
                    "session_string": client.session.save(),
                    "user_id": me.id,
                    "first_name": me.first_name or "",
                    "last_name": me.last_name or "",
                    "username": me.username or "",
                    "phone": me.phone or phone_number,
                    "status": "authenticated",
                },
            }

    except PhoneCodeInvalidError:
        return {
            "error": "Invalid verification code.",
            "details": {"status": "invalid_code"},
        }
    except PhoneCodeExpiredError:
        return {
            "error": "Verification code has expired. Please request a new one.",
            "details": {"status": "code_expired"},
        }
    except FloodWaitError as e:
        return {
            "error": f"Too many attempts. Please wait {e.seconds} seconds.",
            "details": {"flood_wait_seconds": e.seconds},
        }
    except Exception as e:
        return _unexpected("Failed to complete auth", e)
