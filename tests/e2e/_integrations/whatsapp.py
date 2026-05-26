"""WhatsApp Web verification helpers for live e2e tests.

All the wwebjs-bridge-specific knowledge lives here:
  - the owner's identifier is ``owner_phone`` (bare E.164 without ``+``).
  - the self-chat id is the owner's phone (the bridge appends ``@c.us``).
  - chat history comes back from ``get_chat_messages`` as a list with
    ``{id, body, from, from_me, timestamp, type, has_media}`` per
    [bridge.js:478-486](craftos_integrations/integrations/whatsapp_web/bridge.js#L478).

Tests just call ``recent_messages_in_self_chat(since_ts=...)`` and assert
on the returned list — no platform plumbing leaks into the test body.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

from craftos_integrations import get_client
from craftos_integrations.credentials_store import (
    has_config,
    load_config,
    remove_config,
    save_config,
)
from craftos_integrations.integrations.whatsapp_web import WhatsAppWebConfig


INTEGRATION_ID = "whatsapp_web"
_CONFIG_FILE = "whatsapp_web_config.json"


@contextmanager
def self_messages_only(enabled: bool):
    """Temporarily set the WhatsApp Web ``self_messages_only`` config flag,
    snapshotting + restoring the prior value on exit.

    When ``True``, the integration drops every incoming message except
    self-chat ones BEFORE the on-message callback fires — third-party
    messages never reach the agent at all (see
    ``WhatsAppWebClient._handle_incoming_message`` in
    [whatsapp_web/__init__.py](craftos_integrations/integrations/whatsapp_web/__init__.py)).

    Usage in tests::

        with whatsapp.self_messages_only(True):
            asyncio.run(_run_scenario(...))
    """
    original = load_config(_CONFIG_FILE, WhatsAppWebConfig)
    existed_before = has_config(_CONFIG_FILE)
    save_config(_CONFIG_FILE, WhatsAppWebConfig(self_messages_only=enabled))
    try:
        yield
    finally:
        if existed_before and original is not None:
            save_config(_CONFIG_FILE, original)
        else:
            remove_config(_CONFIG_FILE)


async def recent_messages_in_self_chat(
    *,
    since_ts: float,
    contains: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Return outgoing messages in the owner's own whatsapp chat that
    landed at or after ``since_ts``.

    Args:
        since_ts: unix timestamp (seconds). Only messages with
            ``timestamp >= since_ts`` are returned. Pass ``time.time()``
            recorded BEFORE the agent runs (subtract a couple of seconds
            for clock-skew between Python and whatsapp-web.js).
        contains: optional case-insensitive substring filter on the
            message body.
        limit: how many recent messages to fetch from the bridge.

    Returns ``[]`` if the bridge isn't ready, the session has no owner
    info yet, or nothing in the window matches.
    """
    client = get_client(INTEGRATION_ID)
    if client is None:
        return []

    status = client.get_session_status()
    if asyncio.iscoroutine(status):
        status = await status
    owner_phone = (status or {}).get("owner_phone", "")
    if not owner_phone:
        return []

    response = client.get_chat_messages(phone_number=owner_phone, limit=limit)
    if asyncio.iscoroutine(response):
        response = await response
    messages = response.get("messages", []) if isinstance(response, dict) else []

    needle = contains.lower() if contains else None
    return [
        m
        for m in messages
        if m.get("from_me", False)
        and (m.get("timestamp") or 0) >= since_ts
        and (not needle or needle in (m.get("body") or "").lower())
    ]
