"""client_hello: a client declares extra frames; the browser never does."""

import asyncio
import json

from app.ui_layer.adapters.browser_adapter import BrowserAdapter
from app.ui_layer.adapters.ws_channel import CLIENT_PROTOCOL, ClientChannel


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent = []

    async def send_str(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def close(self) -> None:
        pass


async def _drain(channel: ClientChannel) -> None:
    for _ in range(50):
        if channel.pending == 0:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.01)


def test_a_channel_declares_nothing_until_hello():
    async def scenario():
        channel = ClientChannel(_FakeWebSocket())
        before = (channel.client, channel.capabilities)
        channel.declare("terminal", ["subagent_link", 7, "subagent_link"])
        after = (channel.client, channel.capabilities)
        await channel.close()
        return before, after

    before, after = asyncio.run(scenario())
    assert before == ("", frozenset())
    assert after == ("terminal", frozenset({"subagent_link"}))


def test_hello_is_acknowledged_with_edition_and_protocol(monkeypatch):
    monkeypatch.setenv("CRAFTBOT_FRONTEND", "terminal")

    async def scenario():
        ws = _FakeWebSocket()
        channel = ClientChannel(ws)
        BrowserAdapter._handle_client_hello(
            None,
            channel,
            {"type": "client_hello", "client": "terminal", "capabilities": ["x"]},
        )
        await _drain(channel)
        await channel.close()
        return ws.sent

    sent = asyncio.run(scenario())
    assert len(sent) == 1
    reply = sent[0]
    assert reply["type"] == "client_hello"
    assert reply["data"]["protocol"] == CLIENT_PROTOCOL
    assert reply["data"]["edition"] == "terminal"
    assert reply["data"]["capabilities"] == ["x"]
    assert reply["data"]["version"]


def test_the_terminal_client_never_gets_the_live_browser_view():
    import types

    from app.mini_browser.ws import MiniBrowserWS

    async def scenario():
        browser_ws, terminal_ws = _FakeWebSocket(), _FakeWebSocket()
        browser, terminal = ClientChannel(browser_ws), ClientChannel(terminal_ws)
        terminal.declare("terminal", [])
        channels = {browser_ws: browser, terminal_ws: terminal}
        stub = types.SimpleNamespace(
            _viewers={"main": {browser_ws, terminal_ws}},
            _watching=set(),
            _adapter=types.SimpleNamespace(client_channel=lambda ws: channels.get(ws)),
            _forget_viewer=lambda ws: None,
        )
        MiniBrowserWS._send_to_viewers(stub, "main", "mini_browser_frame", {"sessionId": "main", "image": "x"})
        MiniBrowserWS._send_to_viewers(stub, "main", "mini_browser_state", {"sessionId": "main", "tabs": []})
        await _drain(browser)
        await _drain(terminal)
        await browser.close()
        await terminal.close()
        return [m["type"] for m in browser_ws.sent], [m["type"] for m in terminal_ws.sent]

    browser_types, terminal_types = asyncio.run(scenario())
    assert browser_types == ["mini_browser_frame", "mini_browser_state"]
    assert terminal_types == ["mini_browser_state"]


def test_capability_gated_frames_reach_only_clients_that_declared_them():
    async def scenario():
        browser_ws, terminal_ws = _FakeWebSocket(), _FakeWebSocket()
        browser, terminal = ClientChannel(browser_ws), ClientChannel(terminal_ws)
        terminal.declare("terminal", ["subagent_link"])

        class _Adapter:
            _channels = {browser_ws: browser, terminal_ws: terminal}

        BrowserAdapter._broadcast_capable(
            _Adapter(), "subagent_link", {"type": "subagent_link", "data": {}}
        )
        await _drain(browser)
        await _drain(terminal)
        await browser.close()
        await terminal.close()
        return browser_ws.sent, terminal_ws.sent

    browser_sent, terminal_sent = asyncio.run(scenario())
    assert browser_sent == []
    assert terminal_sent == [{"type": "subagent_link", "data": {}}]
