"""StreamableHTTPTransport against an in-process Streamable HTTP server (#185).

The mock server follows the MCP spec (2025-03-26 .. 2025-11-25): one
endpoint, POST for every client message, JSON or SSE responses, 202 for
notifications, Mcp-Session-Id issued on initialize, DELETE to end a session,
and GET + Last-Event-ID to resume a stream the server closed early.

No test sleeps for timing: waits use events, and the timeouts asserted on are
the transport's own (a server that never answers).
"""

from __future__ import annotations

import asyncio
import json
import socket
from typing import List, Optional

import httpx
import pytest
from loguru import logger

from agent_core.core.impl.mcp.config import MCPServerConfig
from agent_core.core.impl.mcp.server import (
    MCPServerConnection,
    StreamableHTTPTransport,
    _HTTPTransportError,
    _sse_lines,
)
from tests.mcp_http_mock import serve

SECRET = "sk-http-SENTINEL-9001"


@pytest.fixture
def log_lines():
    lines: List[str] = []
    sink = logger.add(
        lambda m: lines.append(str(m)),
        level="DEBUG",
        format="{level}|{message}\n{exception}",
        backtrace=True,
        diagnose=True,
    )
    try:
        yield lines
    finally:
        logger.remove(sink)


def run(coro):
    return asyncio.run(coro)


# ───────────────────────── Happy path ───────────────────────────────────────


@pytest.mark.parametrize("mode", ["json", "sse"])
def test_handshake_discovery_and_call_follow_the_spec(mode):
    async def scenario():
        server, url = await serve(mode=mode)
        try:
            transport = StreamableHTTPTransport(
                url, headers={"X-Api-Key": SECRET}, timeout=10, server_name="t"
            )
            assert await transport.connect() is True
            listed = await transport.send_request("tools/list", {})
            called = await transport.send_request(
                "tools/call", {"name": "echo", "arguments": {"text": "hi"}}
            )
            state = (transport.session_id, transport.protocol_version)
            await transport.disconnect()
            return server, listed, called, state, transport
        finally:
            await server.stop()

    server, listed, called, state, transport = run(scenario())
    assert state == ("session-1", "2025-11-25")
    assert listed["result"]["tools"][0]["name"] == "echo"
    assert called["result"]["content"][0]["text"] == "mock:hi"
    assert not transport.is_connected

    init, initialized = server.requests[0], server.requests[1]
    assert init["method"] == "initialize"
    assert init["body"]["params"]["protocolVersion"] == "2025-11-25"
    assert init["headers"]["accept"] == "application/json, text/event-stream"
    assert init["headers"]["content-type"] == "application/json"
    assert "mcp-session-id" not in init["headers"]
    assert "mcp-protocol-version" not in init["headers"]
    assert initialized["method"] == "notifications/initialized"
    # Every request after initialize carries the session and version.
    for request in server.requests[1:]:
        assert request["headers"]["mcp-session-id"] == "session-1"
        assert request["headers"]["mcp-protocol-version"] == "2025-11-25"
        assert request["headers"]["x-api-key"] == SECRET
    assert server.requests[-1]["http"] == "DELETE"


def test_a_server_without_sessions_works_and_gets_no_delete():
    async def scenario():
        server, url = await serve()
        server.session_id = None
        try:
            transport = StreamableHTTPTransport(url, timeout=10)
            assert await transport.connect()
            assert "result" in await transport.send_request("tools/list", {})
            await transport.disconnect()
            return server
        finally:
            await server.stop()

    server = run(scenario())
    assert all("mcp-session-id" not in r["headers"] for r in server.requests)
    assert not [r for r in server.requests if r["http"] == "DELETE"]


@pytest.mark.parametrize("version", ["2025-03-26", "2025-06-18", "2025-11-25"])
def test_supported_negotiated_versions_are_used_in_later_headers(version):
    async def scenario():
        server, url = await serve()
        server.version = version
        try:
            transport = StreamableHTTPTransport(url, timeout=10)
            assert await transport.connect()
            await transport.send_request("tools/list", {})
            await transport.disconnect()
            return server
        finally:
            await server.stop()

    server = run(scenario())
    assert server.calls("tools/list")[0]["headers"]["mcp-protocol-version"] == version


def test_concurrent_requests_each_get_their_own_response():
    async def scenario():
        server, url = await serve(mode="sse")
        try:
            transport = StreamableHTTPTransport(url, timeout=10)
            assert await transport.connect()
            results = await asyncio.gather(
                *[
                    transport.send_request(
                        "tools/call", {"name": "echo", "arguments": {"text": str(i)}}
                    )
                    for i in range(8)
                ]
            )
            await transport.disconnect()
            return results
        finally:
            await server.stop()

    results = run(scenario())
    assert [r["result"]["content"][0]["text"] for r in results] == [
        f"mock:{i}" for i in range(8)
    ]


# ───────────────────────── SSE stream handling ──────────────────────────────


def test_server_requests_and_notifications_before_the_response_are_handled():
    async def scenario():
        server, url = await serve(mode="sse")
        server.pre_messages = [
            {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}},
            {"jsonrpc": "2.0", "id": "srv-1", "method": "ping"},
            {"jsonrpc": "2.0", "id": "srv-2", "method": "sampling/createMessage"},
            {"not": "json-rpc"},
        ]
        try:
            transport = StreamableHTTPTransport(url, timeout=10)
            assert await transport.connect()
            await transport.disconnect()
            return server
        finally:
            await server.stop()

    server = run(scenario())
    replies = [r["body"] for r in server.requests if r["method"] == "<response>"]
    assert {"jsonrpc": "2.0", "id": "srv-1", "result": {}} in replies
    refused = [r for r in replies if r["id"] == "srv-2"][0]
    assert refused["error"]["code"] == -32601
    # The session id arrives in the initialize response's headers, before its
    # SSE body, so replies sent while reading that stream already carry it.
    reply_headers = [
        r["headers"] for r in server.requests if r["method"] == "<response>"
    ]
    assert len(reply_headers) == 2
    assert all(h.get("mcp-session-id") == "session-1" for h in reply_headers)


def test_a_stream_closed_with_an_event_id_is_resumed_with_last_event_id():
    async def scenario():
        server, url = await serve(mode="sse")
        try:
            transport = StreamableHTTPTransport(url, timeout=10)
            assert await transport.connect()
            server.resumable = True
            listed = await transport.send_request("tools/list", {})
            await transport.disconnect()
            return server, listed
        finally:
            await server.stop()

    server, listed = run(scenario())
    assert listed["result"]["tools"][0]["name"] == "echo"
    resume = [r for r in server.requests if r["http"] == "GET"][0]
    assert resume["headers"]["last-event-id"].startswith("evt-")
    assert resume["headers"]["accept"] == "text/event-stream"
    assert resume["headers"]["mcp-session-id"] == "session-1"


def test_a_stream_that_ends_without_a_response_is_an_error():
    async def scenario():
        server, url = await serve(mode="sse")
        try:
            transport = StreamableHTTPTransport(url, timeout=10)
            assert await transport.connect()
            server.close_early = True
            result = await transport.send_request("tools/list", {})
            still_connected = transport.is_connected
            await transport.disconnect()
            return result, still_connected
        finally:
            await server.stop()

    result, still_connected = run(scenario())
    assert "ended before the response" in result["error"]["message"]
    assert still_connected  # one failed request does not drop the session


# ───────────────────────── Failures ─────────────────────────────────────────


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failures_are_reported_without_the_credential(status, log_lines):
    async def scenario():
        server, url = await serve()
        server.status_for = {"initialize": status}
        try:
            transport = StreamableHTTPTransport(
                url, headers={"Authorization": f"Bearer {SECRET}"}, timeout=10
            )
            ok = await transport.connect()
            return ok, transport
        finally:
            await server.stop()

    ok, transport = run(scenario())
    assert ok is False
    assert f"HTTP {status}" in transport.last_error
    assert "check this server's headers" in transport.last_error
    assert "boom {x}" in transport.last_error  # server's JSON-RPC error text
    assert transport._client is None
    assert SECRET not in transport.last_error
    assert SECRET not in "\n".join(log_lines)


@pytest.mark.parametrize("status", [400, 404, 500, 503])
def test_http_errors_on_a_request_become_error_responses(status):
    async def scenario():
        server, url = await serve()
        server.session_id = None  # a 404 without a session is "not found"
        try:
            transport = StreamableHTTPTransport(url, timeout=10)
            assert await transport.connect()
            server.status_for = {"tools/list": status}
            result = await transport.send_request("tools/list", {})
            connected = transport.is_connected
            await transport.disconnect()
            return result, connected
        finally:
            await server.stop()

    result, connected = run(scenario())
    assert f"HTTP {status}" in result["error"]["message"]
    assert "boom {x} (code -32000)" in result["error"]["message"]
    assert connected


def test_a_404_on_a_session_starts_a_new_session_and_retries_once():
    # Spec: on 404 for a request with a session id the client MUST start a
    # new session (fresh initialize, no session id).
    async def scenario():
        server, url = await serve()
        try:
            transport = StreamableHTTPTransport(url, timeout=10)
            assert await transport.connect()
            server.expire()
            result = await transport.send_request("tools/list", {})
            state = (transport.is_connected, transport.session_id)
            await transport.disconnect()
            return server, result, state
        finally:
            await server.stop()

    server, result, (connected, session_id) = run(scenario())
    assert result["result"]["tools"][0]["name"] == "echo"
    assert connected and session_id == "session-2"
    inits = server.calls("initialize")
    assert len(inits) == 2
    assert "mcp-session-id" not in inits[1]["headers"]
    lists = server.calls("tools/list")
    assert [r["headers"]["mcp-session-id"] for r in lists] == ["session-1", "session-2"]


def test_concurrent_requests_share_one_session_renewal():
    async def scenario():
        server, url = await serve()
        try:
            transport = StreamableHTTPTransport(url, timeout=10)
            assert await transport.connect()
            server.expire()
            results = await asyncio.gather(
                *[transport.send_request("tools/list", {}) for _ in range(5)]
            )
            await transport.disconnect()
            return server, results
        finally:
            await server.stop()

    server, results = run(scenario())
    assert all("result" in r for r in results)
    assert len(server.calls("initialize")) == 2  # one renewal, not five


def test_a_failed_session_renewal_disconnects_with_the_reason():
    async def scenario():
        server, url = await serve()
        try:
            transport = StreamableHTTPTransport(url, timeout=10)
            assert await transport.connect()
            server.expire()
            server.status_for = {"initialize": 503}
            result = await transport.send_request("tools/list", {})
            connected = transport.is_connected
            await transport.disconnect()
            return result, connected
        finally:
            await server.stop()

    result, connected = run(scenario())
    message = result["error"]["message"]
    assert "ended the MCP session and a new one could not be started" in message
    assert "HTTP 503" in message
    assert connected is False


def test_redirects_are_not_followed_so_headers_stay_with_the_configured_url(log_lines):
    async def scenario():
        target, target_url = await serve(name="elsewhere")
        server, url = await serve()
        server.redirect_to = target_url + f"?token={SECRET}"
        try:
            transport = StreamableHTTPTransport(
                url, headers={"Authorization": SECRET}, timeout=10
            )
            ok = await transport.connect()
            return ok, transport, target
        finally:
            await server.stop()
            await target.stop()

    ok, transport, target = run(scenario())
    assert ok is False
    assert "redirected" in transport.last_error
    assert "redirects are not followed" in transport.last_error
    assert target.requests == []  # the credential never reached the target
    assert SECRET not in transport.last_error
    assert SECRET not in "\n".join(log_lines)


def test_an_unreachable_endpoint_fails_cleanly():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing listens here now

    async def scenario():
        transport = StreamableHTTPTransport(
            f"http://127.0.0.1:{port}/mcp?key={SECRET}", timeout=5
        )
        ok = await transport.connect()
        return ok, transport

    ok, transport = run(scenario())
    assert ok is False
    assert "could not connect to http://127.0.0.1" in transport.last_error
    assert SECRET not in transport.last_error
    assert transport._client is None


def test_initialize_that_never_answers_times_out_and_cleans_up():
    async def scenario():
        server, url = await serve()
        server.hang_on = {"initialize"}
        try:
            transport = StreamableHTTPTransport(url, timeout=0.5)
            ok = await transport.connect()
            return ok, transport
        finally:
            await server.stop()

    ok, transport = run(scenario())
    assert ok is False
    assert "timed out after 0.5s" in transport.last_error
    assert transport._client is None


def test_a_request_that_never_answers_times_out_without_dropping_the_session():
    async def scenario():
        server, url = await serve()
        try:
            transport = StreamableHTTPTransport(url, timeout=0.5)
            assert await transport.connect()
            server.hang_on = {"tools/call"}
            result = await transport.send_request("tools/call", {"name": "echo"})
            connected = transport.is_connected
            server.hang_on = set()
            after = await transport.send_request("tools/list", {})
            await transport.disconnect()
            return result, connected, after
        finally:
            await server.stop()

    result, connected, after = run(scenario())
    assert "timed out after 0.5s" in result["error"]["message"]
    assert connected
    assert "result" in after


def test_cancelling_connect_closes_the_client_and_propagates():
    async def scenario():
        server, url = await serve()
        server.hang_on = {"initialize"}
        try:
            transport = StreamableHTTPTransport(url, timeout=30)
            task = asyncio.create_task(transport.connect())
            await asyncio.wait_for(server.received.wait(), 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return transport
        finally:
            await server.stop()

    transport = run(scenario())
    assert transport._client is None
    assert not transport.is_connected


def test_an_unsupported_protocol_version_is_rejected():
    async def scenario():
        server, url = await serve()
        server.version = "2024-11-05"
        try:
            transport = StreamableHTTPTransport(url, timeout=10)
            ok = await transport.connect()
            return ok, transport, server
        finally:
            await server.stop()

    ok, transport, server = run(scenario())
    assert ok is False
    assert "protocol version '2024-11-05'" in transport.last_error
    # It asked to end the session it was given.
    assert server.requests[-1]["http"] == "DELETE"


# ── Malformed responses (httpx.MockTransport: precise wire control) ──


def mock_transport(handler) -> StreamableHTTPTransport:
    return StreamableHTTPTransport(
        "https://mcp.example.com/mcp",
        timeout=5,
        _http_transport=httpx.MockTransport(handler),
    )


def init_ok(request: httpx.Request) -> Optional[httpx.Response]:
    body = json.loads(request.content) if request.content else {}
    if body.get("method") == "initialize":
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"protocolVersion": "2025-06-18", "capabilities": {}},
            },
        )
    if "id" not in body:
        return httpx.Response(202)
    return None


@pytest.mark.parametrize(
    "response, message",
    [
        (
            httpx.Response(
                200, content=b"{not json", headers={"content-type": "application/json"}
            ),
            "malformed JSON",
        ),
        (
            httpx.Response(200, content=b"hi", headers={"content-type": "text/plain"}),
            "unexpected Content-Type",
        ),
        (httpx.Response(202), "sent no response"),
        (
            httpx.Response(200, json={"jsonrpc": "2.0", "id": 999, "result": {}}),
            "wrong id",
        ),
        (
            httpx.Response(200, json=[{"jsonrpc": "2.0", "id": 2, "result": {}}]),
            "non-response body",
        ),
    ],
)
def test_malformed_responses_become_errors(response, message):
    def handler(request):
        return init_ok(request) or response

    async def scenario():
        transport = mock_transport(handler)
        assert await transport.connect()
        result = await transport.send_request("tools/list", {})
        await transport.disconnect()
        return result

    assert message in run(scenario())["error"]["message"]


def test_a_json_rpc_error_with_a_null_id_is_matched_to_the_request():
    def handler(request):
        return init_ok(request) or httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "bad"},
            },
        )

    async def scenario():
        transport = mock_transport(handler)
        assert await transport.connect()
        return await transport.send_request("tools/list", {})

    result = run(scenario())
    assert result["error"]["message"] == "bad"


def test_an_oversized_response_is_refused(monkeypatch):
    monkeypatch.setattr(StreamableHTTPTransport, "MAX_MESSAGE_BYTES", 1024)

    def handler(request):
        return init_ok(request) or httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 2, "result": {"x": "a" * 4096}}
        )

    async def scenario():
        transport = mock_transport(handler)
        assert await transport.connect()
        return await transport.send_request("tools/list", {})

    assert "16 MB message limit" in run(scenario())["error"]["message"]


@pytest.mark.parametrize("session_id", ["", "has space", "tab\tin", "ünicode"])
def test_an_invalid_session_id_fails_the_handshake(session_id):
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(
            200,
            # Raw bytes: httpx will not build a non-ASCII str header itself.
            headers=[(b"Mcp-Session-Id", session_id.encode("latin-1"))],
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"protocolVersion": "2025-06-18"},
            },
        )

    async def scenario():
        transport = mock_transport(handler)
        return await transport.connect(), transport

    ok, transport = run(scenario())
    assert ok is False
    assert "invalid Mcp-Session-Id" in transport.last_error


def test_initialize_rejected_with_a_json_rpc_error():
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32602, "message": "Unsupported protocol version"},
            },
        )

    async def scenario():
        transport = mock_transport(handler)
        return await transport.connect(), transport

    ok, transport = run(scenario())
    assert ok is False
    assert transport.last_error == (
        "initialize rejected: Unsupported protocol version (code -32602)"
    )


def test_an_interrupted_connection_is_reported():
    def handler(request):
        if init_ok(request):
            return init_ok(request)
        raise httpx.RemoteProtocolError("peer closed", request=request)

    async def scenario():
        transport = mock_transport(handler)
        assert await transport.connect()
        return await transport.send_request("tools/list", {})

    assert "was interrupted" in run(scenario())["error"]["message"]


def test_disconnect_survives_a_failing_delete_and_always_closes():
    def handler(request):
        if request.method == "DELETE":
            raise httpx.ConnectError("gone", request=request)
        body = json.loads(request.content)
        if body.get("method") == "initialize":
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": "s"},
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"protocolVersion": "2025-06-18"},
                },
            )
        return httpx.Response(202)

    async def scenario():
        transport = mock_transport(handler)
        assert await transport.connect()
        await transport.disconnect()
        return transport

    transport = run(scenario())
    assert transport._client is None
    assert transport.session_id is None


# ───────────────────────── Through MCPServerConnection ──────────────────────


def http_config(url: str, **overrides) -> MCPServerConfig:
    entry = {"name": "remote", "transport": "http", "url": url, "timeout": 10}
    entry.update(overrides)
    return MCPServerConfig.from_dict(entry)


def test_connection_resolves_header_references_and_discovers_paginated_tools():
    tools = [{"name": f"tool{i}", "inputSchema": {"type": "object"}} for i in range(5)]

    async def scenario():
        server, url = await serve(tools=tools)
        server.page_size = 2
        server.required_headers = {"Authorization": f"Bearer {SECRET}"}
        try:
            connection = MCPServerConnection(
                http_config(
                    url,
                    headers={"Authorization": "Bearer ${TOKEN}"},
                    env={"TOKEN": SECRET},
                )
            )
            assert await connection.connect()
            names = [t.name for t in connection.tools]
            called = await connection.call_tool("tool1", {})
            await connection.disconnect()
            return server, names, called
        finally:
            await server.stop()

    server, names, called = run(scenario())
    assert names == [f"tool{i}" for i in range(5)]
    cursors = [
        (r["body"].get("params") or {}).get("cursor")
        for r in server.calls("tools/list")
    ]
    assert cursors == [None, "2", "4"]
    assert called["status"] == "success"


def test_a_missing_header_variable_fails_that_server_before_any_request(log_lines):
    async def scenario():
        server, url = await serve()
        try:
            connection = MCPServerConnection(
                http_config(url, headers={"Authorization": "Bearer ${TOKEN}"})
            )
            ok = await connection.connect()
            return ok, connection, server
        finally:
            await server.stop()

    ok, connection, server = run(scenario())
    assert ok is False
    assert connection.last_error == (
        "Server 'remote': set TOKEN in this server's env (referenced by its headers)"
    )
    assert server.requests == []  # nothing was sent without the credential


def test_connection_reports_the_transport_failure_reason():
    async def scenario():
        server, url = await serve()
        server.status_for = {"initialize": 401}
        try:
            connection = MCPServerConnection(
                http_config(url, headers={"Authorization": SECRET})
            )
            ok = await connection.connect()
            return ok, connection
        finally:
            await server.stop()

    ok, connection = run(scenario())
    assert ok is False
    assert "HTTP 401" in connection.last_error
    assert SECRET not in connection.last_error
    assert not connection.is_connected


# ── SSE framing: CR/LF/CRLF only, bounded lines ──


async def _chunks(*parts: bytes):
    for part in parts:
        yield part


def _lines(chunks, limit: int = 1024) -> List[str]:
    async def collect():
        return [line async for line in _sse_lines(chunks, limit)]

    return run(collect())


def test_sse_lines_split_only_on_cr_lf_and_crlf():
    # str.splitlines() would also split on every one of these.
    text = "a\u2028b\u2029c\u0085d\x0be\x0cf\x1cg\x1dh\x1ei"
    lines = _lines(_chunks(f"data: {text}\r\n".encode(), b"x\ry\n", b"\n"))
    assert lines == [f"data: {text}", "x", "y", ""]


def test_sse_lines_handle_line_ends_and_characters_split_across_chunks():
    lines = _lines(
        _chunks(b"one\r", b"\ntwo\r", b"three\n", b"\xe2\x80", b"\xa8four\n", b"tail")
    )
    assert lines == ["one", "two", "three", "\u2028four", "tail"]


def test_sse_lines_refuse_an_endless_line_without_buffering_it():
    pulled = 0

    async def endless():
        nonlocal pulled
        while True:
            pulled += 1
            yield b"x" * 1000

    with pytest.raises(_HTTPTransportError, match="16 MB message limit"):
        _lines(endless(), limit=10_000)
    assert pulled <= 11  # stopped just past the limit, not at the end


def test_a_result_with_unicode_line_separators_survives_an_sse_response():
    text = "scraped\u2028web\u2029text\u0085end"

    def handler(request):
        body = json.loads(request.content) if request.content else {}
        response = {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {"content": [{"type": "text", "text": text}]},
        }
        event = (
            "event: message\ndata: " + json.dumps(response, ensure_ascii=False) + "\n\n"
        )
        return init_ok(request) or httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=event.encode()
        )

    async def scenario():
        transport = mock_transport(handler)
        assert await transport.connect()
        result = await transport.send_request("tools/call", {"name": "x"})
        await transport.disconnect()
        return result

    assert run(scenario())["result"]["content"][0]["text"] == text


def test_an_sse_line_that_never_ends_is_refused_at_the_message_limit(monkeypatch):
    monkeypatch.setattr(StreamableHTTPTransport, "MAX_MESSAGE_BYTES", 4096)

    async def body():
        yield b"event: message\ndata: "
        for _ in range(64):
            yield b"a" * 1024

    def handler(request):
        return init_ok(request) or httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body()
        )

    async def scenario():
        transport = mock_transport(handler)
        assert await transport.connect()
        result = await transport.send_request("tools/list", {})
        await transport.disconnect()
        return result

    assert "16 MB message limit" in run(scenario())["error"]["message"]


# ── Session renewal: a new session without an id ──


def test_a_renewed_session_without_an_id_stops_sending_the_old_one():
    # The server restarts stateless: the old session gets 404, the new
    # initialize returns no Mcp-Session-Id, so nothing may carry the old id.
    seen = []
    state = {"inits": 0, "restarted": False}

    def handler(request):
        body = json.loads(request.content) if request.content else {}
        method = body.get("method", request.method)
        sid = request.headers.get("mcp-session-id")
        seen.append((method, sid))
        if request.method == "DELETE":
            return httpx.Response(405)
        if method == "initialize":
            state["inits"] += 1
            headers = {"mcp-session-id": "s1"} if state["inits"] == 1 else {}
            return httpx.Response(
                200,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"protocolVersion": "2025-06-18", "capabilities": {}},
                },
            )
        if state["restarted"] and sid == "s1":
            return httpx.Response(404)
        if "id" not in body:
            return httpx.Response(202)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": []}}
        )

    async def scenario():
        transport = mock_transport(handler)
        assert await transport.connect()
        assert transport.session_id == "s1"
        state["restarted"] = True
        first = await transport.send_request("tools/list", {})
        second = await transport.send_request("tools/list", {})
        status = (transport.session_id, transport.is_connected)
        await transport.disconnect()
        return first, second, status

    first, second, (session_id, connected) = run(scenario())
    assert "result" in first and "result" in second
    assert session_id is None and connected
    renewal = seen.index(("initialize", None), 1)
    assert all(sid is None for _, sid in seen[renewal:])
