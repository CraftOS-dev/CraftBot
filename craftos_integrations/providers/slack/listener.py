"""Slack listener — the legacy channel poll loop re-homed onto a bound client.

The legacy ``SlackClient`` listens by *polling*, not Socket Mode: every
POLL_INTERVAL it walks the joined channels (``conversations.list``) and
fetches ``conversations.history`` newer than each channel's last-seen
``ts`` watermark, dispatching human messages (bot/self/subtype messages
filtered) — see ``integrations/slack/__init__.py``. All of that channel
walking and message filtering (``_get_joined_channels`` /
``_poll_channels`` / ``_process_message``) is inherited by
``BoundSlackClient`` and reused unchanged here.

What could NOT be reused is the outer loop: the legacy ``_poll_loop``
unconditionally runs a "catch-up" that stamps every channel's watermark to
*now* — correct for a fresh start (no backlog flood) but it would clobber
a persisted cursor on restart and drop everything received while the host
was down. So this class owns a small outer loop (same retry cadence as
legacy) and chooses at start: cursor present → seed ``_last_timestamps``
from it; no cursor → run the legacy catch-up. Channels joined later are
picked up by the inherited ``_poll_channels`` (it stamps unknown channels
at now, same as legacy).

One listener = one workspace (the account identity is the team id); bot
tokens don't expire, so there is no refresh plumbing.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from ...integrations.slack import POLL_INTERVAL, RETRY_DELAY, _slack_acall
from ...logger import get_logger
from .._shared import EmitFn, emit_callback

logger = get_logger(__name__)


class SlackListener:
    """One Slack workspace poll loop for one bound account."""

    def __init__(
        self, client: Any, cursor: Optional[Dict[str, Any]], emit: EmitFn
    ) -> None:
        self._client = client
        self._initial_cursor = dict(cursor) if cursor else None
        self._emit = emit
        self._task: Optional[asyncio.Task] = None
        self.poll_interval: float = POLL_INTERVAL  # legacy cadence (3s)

    async def start(self) -> None:
        client = self._client
        if client._listening:
            return
        client._message_callback = emit_callback(self._emit)

        # Same auth sanity check as the legacy start_listening: it both
        # validates the bot token and captures the bot user id used to
        # filter the bot's own messages out of the stream.
        cred = client._load()
        data = await _slack_acall(
            "POST", "auth.test", {"Authorization": f"Bearer {cred.bot_token}"}
        )
        if "error" in data:
            raise RuntimeError(f"Invalid Slack token: {data['error']}")
        client._bot_user_id = data.get("user_id")
        logger.info(f"[SLACK] listener bot user ID: {client._bot_user_id}")

        saved = (self._initial_cursor or {}).get("last_timestamps") or {}
        if saved:
            # Resume: keep the per-channel ts watermarks so messages posted
            # while we were down are still delivered (and nothing before
            # the watermarks is replayed).
            client._last_timestamps = {str(k): str(v) for k, v in saved.items()}
        else:
            # Fresh start: legacy catch-up — stamp every joined channel at
            # "now" so history is not flooded into the agent. Failures are
            # tolerated exactly like the legacy loop tolerated them.
            try:
                await client._refresh_channel_timestamps()
            except Exception as e:
                logger.error(f"[SLACK] Catchup error: {e}")
        client._catchup_done = True

        client._listening = True
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        """Legacy ``_poll_loop`` minus the catch-up (handled in start())."""
        client = self._client
        while client._listening:
            try:
                await client._poll_channels()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SLACK] Poll error: {e}")
                await asyncio.sleep(RETRY_DELAY)
                continue
            await asyncio.sleep(self.poll_interval)

    async def stop(self) -> None:
        client = self._client
        if not client._listening:
            return
        client._listening = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def cursor(self) -> Optional[Dict[str, Any]]:
        timestamps = self._client._last_timestamps
        if not timestamps:
            # Never started (or no channels yet): hand back what we were
            # given so a persisted cursor is never destroyed.
            return self._initial_cursor
        return {"last_timestamps": dict(timestamps)}
