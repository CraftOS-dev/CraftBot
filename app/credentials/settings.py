"""Metadata-only UI adapter. The native service verifies every sensitive act.

Never forward an arbitrary operation, user-provided context, source value or
capability through WebSocket. Replies belong only to the requesting connection.
"""

from __future__ import annotations

import asyncio

from .client import CredentialHostUnavailable, request

FIELDS = {
    "profiles": (),
    "action_profile": (),
    "action_profile_set": ("profile_id",),
    "profile_add": ("label",),
    "initialize": ("profile_id",),
    "unlock": ("profile_id",),
    "lock": ("profile_id",),
    "items": ("profile_id",),
    "items_page": ("profile_id", "view_id", "offset"),
    "activity": ("profile_id",),
    "revoke": ("profile_id", "grant_id"),
    "entry": ("profile_id", "kind", "service", "account", "origins", "fields"),
    "edit": (
        "profile_id",
        "credential_id",
        "version",
        "service",
        "account",
        "origins",
        "replace_fields",
    ),
    "delete": ("profile_id", "credential_id", "version"),
    "view": ("profile_id", "credential_id", "version"),
}


async def handle(adapter, ws, data):
    operation = data.get("operation") if type(data) is dict else None
    parameters = data.get("parameters", {}) if type(data) is dict else {}
    request_id = data.get("request_id") if type(data) is dict else None
    result = {
        "operation": operation if isinstance(operation, str) else None,
        "ok": False,
        "error": "credential_use_denied",
    }
    if (
        isinstance(operation, str)
        and operation in FIELDS
        and type(parameters) is dict
        and set(parameters) == set(FIELDS[operation])
    ):
        try:
            value = await asyncio.to_thread(request, operation, **parameters)
            result = {"operation": operation, "ok": True, "value": value}
        except CredentialHostUnavailable as error:
            result["error"] = str(error)  # Client already enforces fixed codes.
        except Exception:
            result["error"] = "credential_host_unavailable"
    result["request_id"] = (
        request_id if isinstance(request_id, str) and len(request_id) <= 64 else None
    )
    adapter._send_only_to(ws, {"type": "credentials_result", "data": result})
