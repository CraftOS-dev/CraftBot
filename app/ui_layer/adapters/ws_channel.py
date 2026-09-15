# -*- coding: utf-8 -*-
"""
Non-blocking outbound delivery to one browser WebSocket.

Broadcasts used to ``await ws.send_str`` client by client, so one slow tab
(throttled, frozen or on a slow link) delayed updates for every other tab.
Each connection now has a ``ClientChannel``: sending only enqueues, and a
writer task delivers in order. A client that falls too far behind is
disconnected instead; it reconnects and resyncs from the ``init`` snapshot.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from agent_core.utils.logger import logger

# Queued messages a client may lag behind before it's disconnected.
DEFAULT_MAX_PENDING = 10_000


class ClientChannel:
    """Ordered outbound queue plus writer task for one WebSocket."""

    def __init__(self, ws: Any, max_pending: int = DEFAULT_MAX_PENDING) -> None:
        self._ws = ws
        self._max_pending = max_pending
        self._queue: "asyncio.Queue[str]" = asyncio.Queue()
        self._closed = False
        self._writer = asyncio.create_task(self._write_loop())

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def send_text(self, text: str) -> None:
        """Queue a serialized message for delivery; returns immediately."""
        if self._closed:
            return
        if self._queue.qsize() >= self._max_pending:
            self._closed = True
            logger.warning(
                f"[WS CHANNEL] Client fell {self._max_pending} messages behind; "
                "disconnecting it so other clients aren't delayed"
            )
            asyncio.ensure_future(self._ws.close())
            return
        self._queue.put_nowait(text)

    def send_json(self, message: Dict[str, Any]) -> None:
        self.send_text(json.dumps(message))

    async def close(self) -> None:
        """Stop delivering; undelivered messages are dropped."""
        self._closed = True
        self._writer.cancel()
        try:
            await self._writer
        except (asyncio.CancelledError, Exception):
            pass

    async def _write_loop(self) -> None:
        try:
            while True:
                text = await self._queue.get()
                await self._ws.send_str(text)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The connection is gone; the reader loop cleans the channel up.
            self._closed = True
