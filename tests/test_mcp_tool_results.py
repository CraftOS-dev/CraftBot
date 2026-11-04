"""MCP tool discovery pagination and tool-reported errors.

tools/list is paginated by the MCP spec, so every page has to be fetched, and
a tool signals its own failure with ``isError: true`` in a normal result, which
must not be reported to the agent as a success.
"""

import asyncio

from agent_core.core.impl.mcp.config import MCPServerConfig
from agent_core.core.impl.mcp.server import MCPServerConnection


class FakeTransport:
    is_connected = True

    def __init__(self, pages=None, call_result=None):
        self.pages = pages or {}
        self.call_result = call_result
        self.list_params = []

    async def send_request(self, method, params=None):
        if method == "tools/list":
            self.list_params.append(params)
            return {"result": self.pages[(params or {}).get("cursor")]}
        return {"result": self.call_result}


def _connection(transport):
    conn = MCPServerConnection(
        MCPServerConfig(name="fake", transport="stdio", command="fake")
    )
    conn._transport = transport
    return conn


def _tool(name):
    return {"name": name, "inputSchema": {}}


def test_discover_tools_follows_next_cursor():
    transport = FakeTransport(
        pages={
            None: {"tools": [_tool("a")], "nextCursor": "p2"},
            "p2": {"tools": [_tool("b")], "nextCursor": "p3"},
            "p3": {"tools": [_tool("c")]},
        }
    )
    conn = _connection(transport)

    asyncio.run(conn._discover_tools())

    assert [t.name for t in conn.tools] == ["a", "b", "c"]
    assert transport.list_params == [{}, {"cursor": "p2"}, {"cursor": "p3"}]


def test_discover_tools_stops_on_repeated_cursor():
    transport = FakeTransport(
        pages={
            None: {"tools": [_tool("a")], "nextCursor": "loop"},
            "loop": {"tools": [_tool("b")], "nextCursor": "loop"},
        }
    )
    conn = _connection(transport)

    asyncio.run(conn._discover_tools())

    assert [t.name for t in conn.tools] == ["a", "b"]


def test_call_tool_reports_is_error_as_error():
    transport = FakeTransport(
        call_result={
            "isError": True,
            "content": [{"type": "text", "text": "file not found"}],
        }
    )
    conn = _connection(transport)

    result = asyncio.run(conn.call_tool("read", {}))

    assert result["status"] == "error"
    assert result["message"] == "file not found"


def test_call_tool_success_unchanged():
    transport = FakeTransport(call_result={"content": [{"type": "text", "text": "ok"}]})
    conn = _connection(transport)

    result = asyncio.run(conn.call_tool("read", {}))

    assert result["status"] == "success"
    assert result["result"] == "ok"
