"""Fixed Telegram login operations inside the protected host.

No TL method, proxy, destination, file, code or SDK object is caller-selected.
Generated StringSessions return to their original owner; app hashes and saved
2FA passwords never leave this module. Only in-memory Telethon sessions exist.
"""

import asyncio
import logging
import re

from .helpers import JsonResult, _sanitize_json_payloads
from .use_errors import CredentialUseError, UseCode

# Production DCs only. New DC addresses require a reviewed package update.
DC_ADDRESSES = {
    1: "149.154.175.50",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "149.154.171.5",
}


def validate(operation, body):
    required = {
        "send_code": {"api_id", "phone_number"},
        "complete": {
            "api_id",
            "phone_number",
            "code",
            "phone_code_hash",
            "session_string",
        },
        "complete_password": {"api_id", "session_string"},
        "qr_login": {"api_id"},
    }[operation]
    if (
        type(body) is not dict
        or set(body) != required
        or any(not isinstance(v, str) or len(v) > 4096 for v in body.values())
    ):
        raise CredentialUseError(UseCode.DENIED)
    if (
        not re.fullmatch(r"[1-9][0-9]{0,9}", body["api_id"])
        or int(body["api_id"]) > 2147483647
    ):
        raise CredentialUseError(UseCode.DENIED)
    if "phone_number" in body and not re.fullmatch(
        r"\+?[0-9]{5,20}", body["phone_number"]
    ):
        raise CredentialUseError(UseCode.DENIED)
    if "code" in body and not re.fullmatch(r"[0-9]{3,10}", body["code"]):
        raise CredentialUseError(UseCode.DENIED)
    if "phone_code_hash" in body and not re.fullmatch(
        r"[A-Za-z0-9_-]{1,256}", body["phone_code_hash"]
    ):
        raise CredentialUseError(UseCode.DENIED)


def execute(specification, fields, guard, payload, execution, after_send):
    body, operation = payload["body"], specification.operation.operation
    validate(operation, body)
    if set(fields.reveal()) - {"api_hash", "password"} or not re.fullmatch(
        r"[a-fA-F0-9]{32}", fields.reveal().get("api_hash", "")
    ):
        raise CredentialUseError(UseCode.DENIED)
    if operation == "complete_password" and not fields.reveal().get("password"):
        raise CredentialUseError(UseCode.DENIED)
    return asyncio.run(_perform(operation, body, fields, guard, execution, after_send))


async def _perform(operation, body, fields, guard, execution, after_send):
    from telethon import TelegramClient, errors
    from telethon.sessions import StringSession
    from telethon.network.connection import ConnectionTcpFull

    class FixedConnection(ConnectionTcpFull):
        async def _connect(self, timeout=None, ssl=None):
            if (
                self._dc_id not in DC_ADDRESSES
                or self._proxy
                or self._local_addr
                or ssl is not None
            ):
                raise CredentialUseError(UseCode.DENIED)
            # Telethon also reads addresses from GetConfig during DC migration.
            # Select the reviewed DC address again at every socket creation.
            self._ip, self._port = DC_ADDRESSES[self._dc_id], 443
            return await super()._connect(timeout=min(timeout or 10, 10), ssl=None)

    class PrivateLogger(logging.Logger):
        def getChild(self, suffix):
            return self  # Never create a child attached to the process root.

    logger = PrivateLogger("credential_mtproto_private")
    logger.disabled = True
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    session = StringSession(body.get("session_string") or "")
    dc = session.dc_id or 2
    if dc not in DC_ADDRESSES:
        raise CredentialUseError(UseCode.DENIED)
    # A staged StringSession can contain a caller-chosen address/port. Ignore
    # both and retain only its DC and generated auth key.
    session.set_dc(dc, DC_ADDRESSES[dc], 443)
    client = TelegramClient(
        session,
        int(body["api_id"]),
        fields.reveal()["api_hash"],
        connection=FixedConnection,
        proxy=None,
        use_ipv6=False,
        timeout=10,
        request_retries=1,
        connection_retries=1,
        auto_reconnect=False,
        flood_sleep_threshold=0,
        receive_updates=operation == "qr_login",
        base_logger=logger,
    )

    def checked(value):
        return _sanitize_json_payloads([value], fields)[0]

    def emit(value):
        text = checked(value)
        if execution is not None:
            execution.emit("data: " + text + "\n\n")

    async def authenticate():
        guard()
        await client.connect()
        guard()
        # Commit this fixed dispatch; no further caller input is accepted.
        if after_send is not None:
            after_send()
        try:
            if operation == "send_code":
                code = await client.send_code_request(body["phone_number"])
                return {
                    "ok": True,
                    "result": {
                        "phone_code_hash": code.phone_code_hash,
                        "phone_number": body["phone_number"],
                        "session_string": client.session.save(),
                        "status": "code_sent",
                    },
                }
            if operation == "qr_login":
                if execution is None:
                    raise CredentialUseError(UseCode.DENIED)
                execution.start(200, "text/event-stream")
                qr = await client.qr_login()
                # The QR token is generated login state, not an app hash.
                emit({"qr_url": qr.url})
                await qr.wait(timeout=120)
            elif operation == "complete_password":
                await client.sign_in(password=fields.reveal()["password"])
            else:
                try:
                    await client.sign_in(
                        phone=body["phone_number"],
                        code=body["code"],
                        phone_code_hash=body["phone_code_hash"],
                    )
                except errors.SessionPasswordNeededError:
                    if not fields.reveal().get("password"):
                        raise
                    await client.sign_in(password=fields.reveal()["password"])
            me = await client.get_me()
            return {
                "ok": True,
                "result": {
                    "session_string": client.session.save(),
                    "user_id": me.id,
                    "first_name": me.first_name or "",
                    "last_name": me.last_name or "",
                    "username": me.username or "",
                    "phone": me.phone or body.get("phone_number", ""),
                    "status": "authenticated",
                },
            }
        except errors.SessionPasswordNeededError:
            return {
                "error": "Two-factor authentication required",
                "details": {
                    "status": "2fa_required",
                    "session_string": client.session.save(),
                },
            }
        except errors.PhoneCodeInvalidError:
            return {
                "error": "Invalid verification code",
                "details": {"status": "invalid_code"},
            }
        except errors.PhoneCodeExpiredError:
            return {
                "error": "Verification code expired",
                "details": {"status": "code_expired"},
            }
        except errors.PasswordHashInvalidError:
            return {
                "error": "Invalid 2FA password",
                "details": {"status": "invalid_password"},
            }
        except errors.FloodWaitError as error:
            return {
                "error": "Telegram rate limit",
                "details": {"flood_wait_seconds": max(0, min(error.seconds, 86400))},
            }

    async def cancel_when_locked(task):
        while not task.done():
            await asyncio.sleep(0.05)
            if execution is not None and execution.cancelled.is_set():
                task.cancel()
                return

    task = asyncio.create_task(authenticate())
    watcher = asyncio.create_task(cancel_when_locked(task))
    try:
        result = await asyncio.wait_for(task, timeout=180)
        if (
            operation == "qr_login"
            and execution is not None
            and execution.status is not None
        ):
            emit(result)
            return JsonResult(200, "", "text/event-stream")
        return JsonResult(200, checked(result), "application/json")
    except asyncio.CancelledError:
        raise CredentialUseError(UseCode.INTERRUPTED) from None
    finally:
        watcher.cancel()
        try:
            await asyncio.wait_for(client.disconnect(), 5)
        except (Exception, asyncio.CancelledError):
            pass
