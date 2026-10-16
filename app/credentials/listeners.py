"""Source listeners retain normal event shaping; their transport has no sources."""

import asyncio
import json
from functools import partial
from threading import Event

from craftos_integrations.helpers.source_requests import using
from .invocation import open_response


class SourceListener:
    def __init__(self, source, provider, cursor, emit):
        self.source, self.provider, self.emit = source, provider, emit
        self.cancelled, self.task = Event(), None
        self.inner = (
            None
            if provider.id == "discord"
            else provider.make_listener(source.client, cursor, emit)
        )
        self.poll_interval = getattr(self.inner, "poll_interval", 3)

    async def start(self):
        if self.provider.id == "discord":
            if self.task is None:
                self.task = asyncio.create_task(self._discord())
            if self.task.done():
                await self.task
            return
        if self.inner is not None:
            with using(
                partial(self.source._request, cancelled=self.cancelled, repeat=True)
            ):
                await self.inner.start()

    async def stop(self):
        self.cancelled.set()
        try:
            if self.task is not None:
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
            if self.inner is not None:
                await self.inner.stop()
        finally:
            await asyncio.to_thread(self.source.close_sessions)

    def cursor(self):
        return self.inner.cursor() if self.inner is not None else None

    async def _discord(self):
        from craftos_integrations.providers._shared import emit_callback

        client = self.source.client
        client._message_callback = emit_callback(self.emit)
        response = None
        try:
            response = await asyncio.to_thread(
                open_response,
                self.source.reference,
                "integration_discord",
                "gateway_events",
                subject="Discord listener",
                cancelled=self.cancelled,
            )
            iterator, buffer = iter(response), ""
            while not self.cancelled.is_set():
                part = await asyncio.to_thread(next, iterator, None)
                if part is None:
                    break
                buffer += part
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    data = json.loads(frame.removeprefix("data: "))
                    if data.get("t") == "READY":
                        client._bot_user_id = data["d"]["user"]["id"]
                        client._catchup_done = True
                    elif data.get("t") == "MESSAGE_CREATE":
                        with using(
                            partial(
                                self.source._request,
                                cancelled=self.cancelled,
                                repeat=True,
                            )
                        ):
                            await client._handle_message_create(data["d"])
            raise RuntimeError("credential_listener_expired")
        finally:
            self.cancelled.set()
            if response is not None:
                await asyncio.to_thread(response.close)
