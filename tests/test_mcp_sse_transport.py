"""SSETransport POSTs to the endpoint the server announces (MCP SSE spec)."""

import asyncio
import json

from aiohttp import web

from agent_core.core.impl.mcp.server import SSETransport

INIT_RESULT = {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "serverInfo": {"name": "mock", "version": "0"},
}


class _MockSSEServer:
    """Serves GET /sse and POSTs on `post_path`, logging every POST."""

    def __init__(self, post_path, announce=None):
        self.post_path = post_path
        self.announce = announce  # data of the `endpoint` event; None = send none
        self.data_first = False  # emit `data:` before `event:` in the announcement
        self.posts = []  # (path, method name)
        self.result_text = None  # tools/call answers with this text
        self._queue: asyncio.Queue = asyncio.Queue()

    async def _sse(self, request):
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        if self.announce is not None:
            event, data = "event: endpoint", f"data: {self.announce}"
            lines = (data, event) if self.data_first else (event, data)
            await resp.write(("\n".join(lines) + "\n\n").encode())
        try:
            while True:
                msg = await self._queue.get()
                if msg is None:  # stop() sentinel: end the stream
                    break
                # Unescaped non-ASCII, as the official SDKs write it.
                data = json.dumps(msg, ensure_ascii=False)
                await resp.write(f"event: message\ndata: {data}\n\n".encode())
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        return resp

    async def _post(self, request):
        body = await request.json()
        self.posts.append((request.path, body.get("method")))
        if "id" in body:
            result = INIT_RESULT
            if body.get("method") == "tools/call" and self.result_text is not None:
                result = {"content": [{"type": "text", "text": self.result_text}]}
            await self._queue.put(
                {"jsonrpc": "2.0", "id": body["id"], "result": result}
            )
        return web.Response(status=202)

    async def start(self):
        app = web.Application()
        app.add_routes(
            [web.get("/sse", self._sse), web.post(self.post_path, self._post)]
        )
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0, shutdown_timeout=0.1)
        await site.start()
        port = self._runner.addresses[0][1]
        return f"http://127.0.0.1:{port}/sse"

    async def stop(self):
        self._queue.put_nowait(None)
        await asyncio.sleep(0.05)  # let the stream handler return
        await self._runner.cleanup()


def _connect(server, tweak=None):
    """Connect an SSETransport to `server`; return (connected, transport)."""

    async def run():
        url = await server.start()
        transport = SSETransport(url, {})
        if tweak:
            tweak(transport)
        try:
            return await transport.connect(), transport
        finally:
            await transport.disconnect()
            await server.stop()

    return asyncio.run(run())


def test_posts_to_the_endpoint_the_server_announces():
    # Same layout as the official MCP Python SDK: GET /sse, POST /messages/.
    server = _MockSSEServer("/messages/", announce="/messages/?session_id=abc")
    connected, transport = _connect(server)

    assert connected is True
    assert transport._endpoint.endswith("/messages/?session_id=abc")
    assert ("/messages/", "initialize") in server.posts


def test_sends_initialized_notification_after_initialize():
    server = _MockSSEServer("/messages/", announce="/messages/?session_id=abc")
    _connect(server)

    methods = [method for _, method in server.posts]
    assert methods == ["initialize", "notifications/initialized"]


def test_falls_back_to_guessed_url_when_no_endpoint_is_announced():
    # Older servers that never send an `endpoint` event but serve /message.
    server = _MockSSEServer("/message", announce=None)

    def short_timeout(transport):
        transport.ENDPOINT_TIMEOUT = 0.2

    connected, transport = _connect(server, short_timeout)

    assert connected is True
    assert transport._endpoint is None
    assert ("/message", "initialize") in server.posts


def test_ignores_an_endpoint_on_a_different_origin():
    server = _MockSSEServer("/message", announce="http://evil.example/messages/")

    def short_timeout(transport):
        transport.ENDPOINT_TIMEOUT = 0.2

    connected, transport = _connect(server, short_timeout)

    assert transport._endpoint is None
    assert connected is True
    assert all(path == "/message" for path, _ in server.posts)


def test_accepts_an_endpoint_event_with_data_before_event():
    server = _MockSSEServer("/messages/", announce="/messages/?session_id=abc")
    server.data_first = True
    connected, transport = _connect(server)

    assert connected is True
    assert transport._endpoint.endswith("/messages/?session_id=abc")
    assert ("/messages/", "initialize") in server.posts


def test_origin_ignores_default_port_and_hostname_case():
    origin = SSETransport._origin
    assert origin("https://example.com/sse") == origin("https://EXAMPLE.com:443/m/")
    assert origin("http://example.com/sse") == origin("http://example.com:80/m/")
    assert origin("https://example.com/sse") != origin("https://example.com:8443/m/")
    assert origin("https://example.com/sse") != origin("http://example.com/m/")


def test_a_result_with_unicode_line_separators_is_received_whole():
    # Only CR and LF end an SSE line; servers write U+2028 and U+0085
    # unescaped inside a data: line.
    text = "scraped\u2028web\u2029text\u0085end"
    server = _MockSSEServer("/messages/", announce="/messages/?session_id=abc")
    server.result_text = text

    async def run():
        url = await server.start()
        transport = SSETransport(url, {})
        try:
            assert await transport.connect()
            return await asyncio.wait_for(
                transport.send_request("tools/call", {"name": "x"}), timeout=10
            )
        finally:
            await transport.disconnect()
            await server.stop()

    result = asyncio.run(run())
    assert result["result"]["content"][0]["text"] == text
