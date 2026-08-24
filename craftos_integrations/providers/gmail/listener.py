"""Gmail listener — the legacy poll loop re-homed onto a bound client.

The loop machinery is NOT rewritten: ``BoundGmailClient`` inherits the legacy
``GmailClient``'s ``_poll_loop`` / ``_check_history`` /
``_fetch_and_dispatch`` (history.list on INBOX every POLL_INTERVAL,
404-expired-historyId recovery, seen-id dedup, self-message filtering)
unchanged. This class replaces only the two things that were host-global
in the legacy design:

* callback plumbing — ``_message_callback`` is a shim converting each
  ``PlatformMessage`` into the host event payload and awaiting the
  account-bound ``emit``;
* startup state — instead of always baselining from the live profile's
  ``historyId``, a persisted cursor seeds ``_history_id`` +
  ``_seen_message_ids`` so a restart resumes where it left off (catching
  mail that arrived while the host was down) without re-emitting events.

Config gating: the legacy ``GmailConfig.process_incoming`` toggle needs no
porting — the inherited ``_fetch_and_dispatch`` re-reads
``gmail_config.json`` on every dispatch and drops incoming mail when the
toggle is off, so it keeps working exactly as before for the integration listeners.

Token refresh during long polls is the binding's job: ``_auth_header``
resolves through ``GoogleClientBinding.refresh_access_token``, which
persists rotated tokens through the core.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from ...integrations.gmail import POLL_INTERVAL
from ...logger import get_logger
from .._shared import EmitFn, emit_callback

logger = get_logger(__name__)

# How many recently-seen message ids survive into the cursor. Matches the
# legacy in-memory trim floor (sets over 500 were cut back to 200).
CURSOR_SEEN_IDS = 200


class GmailListener:
    """One Gmail inbox poll loop for one bound account."""

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

        saved = self._initial_cursor or {}
        history_id = saved.get("history_id")
        if history_id:
            # Resume: trust the persisted baseline so mail that arrived
            # while we were down is still delivered (history.list replays
            # from it); seen ids stop replayed records from double-emitting.
            client._history_id = str(history_id)
            client._seen_message_ids = set(saved.get("seen_ids") or [])
        else:
            # Fresh start: baseline at the live profile, exactly like the
            # legacy start_listening — no historical backfill.
            try:
                profile = await client._async_get_profile()
            except Exception as e:
                raise RuntimeError(f"Failed to connect to Gmail: {e}")
            client._history_id = profile.get("historyId")
            client._seen_message_ids = set()
            logger.info(
                f"[GMAIL] listener baseline: {profile.get('emailAddress')}, "
                f"historyId: {client._history_id}"
            )

        client._listening = True
        client._poll_task = asyncio.create_task(client._poll_loop())

    async def stop(self) -> None:
        # Legacy stop_listening already does exactly what we need:
        # flag off, cancel the poll task, await it.
        await self._client.stop_listening()

    def cursor(self) -> Optional[Dict[str, Any]]:
        client = self._client
        if not client._history_id:
            # Never started (or fresh baseline failed): hand back what we
            # were given so a persisted cursor is never destroyed.
            return self._initial_cursor
        return {
            "history_id": str(client._history_id),
            "seen_ids": sorted(client._seen_message_ids)[-CURSOR_SEEN_IDS:],
        }
