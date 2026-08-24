"""Outlook listener — the legacy Graph poll loop re-homed onto a bound client.

The loop machinery is NOT rewritten: ``BoundOutlookClient`` inherits the
legacy ``OutlookClient``'s ``_poll_loop`` / ``_check_new_messages`` /
``_dispatch_message`` (``/me/messages`` filtered by ``receivedDateTime``
every POLL_INTERVAL, 401-triggered refresh, seen-id dedup, self-message
filtering) unchanged. This class replaces only:

* callback plumbing — ``_message_callback`` becomes a shim converting each
  ``PlatformMessage`` into the host event payload and awaiting the
  account-bound ``emit``;
* startup state — instead of always starting the ``receivedDateTime``
  watermark at "now", a persisted cursor seeds ``_last_poll_time`` +
  ``_seen_message_ids`` so a restart picks up mail received while the host
  was down without re-emitting what was already delivered.

Mid-poll 401s resolve through ``OutlookClientBinding.refresh_access_token``
(inherited via MRO by the loop's refresh calls), so Microsoft's rotating
refresh tokens persist through the core automatically.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ...integrations.outlook import POLL_INTERVAL
from ...logger import get_logger
from .._shared import EmitFn, emit_callback

logger = get_logger(__name__)

# How many recently-seen message ids survive into the cursor. Matches the
# legacy in-memory trim floor (sets over 500 were cut back to 200).
CURSOR_SEEN_IDS = 200


class OutlookListener:
    """One Outlook mailbox poll loop for one bound account."""

    def __init__(
        self, client: Any, cursor: Optional[Dict[str, Any]], emit: EmitFn
    ) -> None:
        self._client = client
        self._initial_cursor = dict(cursor) if cursor else None
        self._emit = emit
        self.poll_interval: float = POLL_INTERVAL  # legacy cadence (5s)

    async def start(self) -> None:
        client = self._client
        if client._listening:
            return
        client._message_callback = emit_callback(self._emit)

        # Same connectivity/token sanity check the legacy start_listening
        # performed (also warms the access token via the credential binding).
        try:
            profile = await client._async_get_profile()
            email_addr = profile.get("mail") or profile.get("userPrincipalName", "")
            logger.info(f"[OUTLOOK] listener connected as: {email_addr}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Outlook: {e}")

        saved = self._initial_cursor or {}
        last_poll_time = saved.get("last_poll_time")
        if last_poll_time:
            # Resume: keep the persisted receivedDateTime watermark so mail
            # that arrived while we were down is still delivered; seen ids
            # stop the overlapping window from double-emitting.
            client._last_poll_time = str(last_poll_time)
            client._seen_message_ids = set(saved.get("seen_ids") or [])
        else:
            # Fresh start: watermark at "now", exactly like the legacy
            # start_listening — no historical backfill.
            client._last_poll_time = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            client._seen_message_ids = set()

        client._listening = True
        client._poll_task = asyncio.create_task(client._poll_loop())

    async def stop(self) -> None:
        # Legacy stop_listening already does exactly what we need.
        await self._client.stop_listening()

    def cursor(self) -> Optional[Dict[str, Any]]:
        client = self._client
        if not client._last_poll_time:
            # Never started: hand back what we were given so a persisted
            # cursor is never destroyed.
            return self._initial_cursor
        return {
            "last_poll_time": client._last_poll_time,
            "seen_ids": sorted(client._seen_message_ids)[-CURSOR_SEEN_IDS:],
        }
