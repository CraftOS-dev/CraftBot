"""Non-blocking outbound WebSocket delivery."""

import asyncio

from app.ui_layer.adapters.ws_channel import ClientChannel


class _FakeWebSocket:
    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.sent = []
        self.closed = False
        self._delay = delay
        self._fail = fail

    async def send_str(self, text: str) -> None:
        if self._fail:
            raise ConnectionResetError("gone")
        await asyncio.sleep(self._delay)
        self.sent.append(text)

    async def close(self) -> None:
        self.closed = True


def test_delivers_in_order_without_blocking_the_sender():
    async def scenario():
        ws = _FakeWebSocket(delay=0.01)
        channel = ClientChannel(ws)
        loop = asyncio.get_running_loop()
        started = loop.time()
        for index in range(20):
            channel.send_text(str(index))
        enqueue_seconds = loop.time() - started
        for _ in range(100):
            if len(ws.sent) == 20:
                break
            await asyncio.sleep(0.01)
        await channel.close()
        return ws.sent, enqueue_seconds

    sent, enqueue_seconds = asyncio.run(scenario())
    assert sent == [str(i) for i in range(20)]
    assert enqueue_seconds < 0.05


def test_disconnects_a_client_that_falls_too_far_behind():
    async def scenario():
        ws = _FakeWebSocket(delay=10)
        channel = ClientChannel(ws, max_pending=5)
        for index in range(10):
            channel.send_text(str(index))
        await asyncio.sleep(0.01)
        closed = channel.closed
        await channel.close()
        return closed, ws.closed

    channel_closed, ws_closed = asyncio.run(scenario())
    assert channel_closed is True
    assert ws_closed is True


def test_marks_itself_closed_when_the_connection_is_gone():
    async def scenario():
        channel = ClientChannel(_FakeWebSocket(fail=True))
        channel.send_json({"type": "x"})
        await asyncio.sleep(0.01)
        closed = channel.closed
        channel.send_json({"type": "ignored"})  # no error after close
        await channel.close()
        return closed

    assert asyncio.run(scenario()) is True
