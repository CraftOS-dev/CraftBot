"""Consumer-side fixed login controllers, holding references and generated state."""

import asyncio
import json
from threading import Event

from .invocation import invoke, invoke_async, open_response
from .client import CredentialHostUnavailable
from .references import parse


def lark_request(operation, app_id, reference):
    parse(reference)
    if operation not in ("tenant_token", "websocket_endpoint"):
        raise CredentialHostUnavailable("credential_use_denied")
    response = invoke(
        reference,
        "auth_lark",
        operation,
        {"app_id": app_id},
        subject="Lark " + operation,
    )
    if response["status"] != 200:
        raise CredentialHostUnavailable("credential_operation_failed")
    return json.loads(response["body"])


async def telegram_auth(operation, api_id, reference, **data):
    parse(reference)
    if operation not in ("send_code", "complete", "qr_login", "complete_password"):
        raise CredentialHostUnavailable("credential_use_denied")
    callback = data.pop("on_qr_url", None)
    data.pop("timeout", None)  # Host pins its own deadline.
    if operation != "qr_login":
        result = await invoke_async(
            reference,
            "auth_telegram_user",
            operation,
            {"api_id": api_id, **data},
            subject="Telegram " + operation,
        )
        if result["status"] != 200:
            raise CredentialHostUnavailable("credential_operation_failed")
        return json.loads(result["body"])
    cancelled = Event()

    def qr():
        response = open_response(
            reference,
            "auth_telegram_user",
            operation,
            {"api_id": api_id},
            subject="Telegram QR login",
            cancelled=cancelled,
        )
        pending, result = "", None
        try:
            if response.status != 200:
                raise CredentialHostUnavailable("credential_operation_failed")
            for chunk in response:
                pending += chunk
                if len(pending) > 32000:
                    raise CredentialHostUnavailable("credential_use_limit")
                while "\n\n" in pending:
                    record, pending = pending.split("\n\n", 1)
                    if not record.startswith("data: "):
                        raise CredentialHostUnavailable("credential_operation_failed")
                    value = json.loads(record[6:])
                    if "qr_url" in value:
                        if callback:
                            callback(value["qr_url"])
                    else:
                        result = value
            if result is None:
                raise CredentialHostUnavailable("credential_operation_failed")
            return result
        finally:
            response.close()

    task = asyncio.create_task(asyncio.to_thread(qr))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled.set()
        task.add_done_callback(
            lambda future: future.exception() if not future.cancelled() else None
        )
        raise
