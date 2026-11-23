"""Interoperability: CraftBot's Streamable HTTP client against the official
MCP Python SDK server (#185).

Opt-in, because the SDK is not a CraftBot dependency. Point
CRAFTBOT_MCP_INTEROP_PYTHON at any interpreter that has ``mcp`` (2.x) and
``uvicorn`` installed; the SDK server runs in that interpreter, in a
subprocess, so nothing is added to the test environment itself:

    CRAFTBOT_MCP_INTEROP_PYTHON=/path/to/venv-with-mcp/python pytest \\
        tests/test_mcp_streamable_http_interop.py

The server sits behind a small ASGI guard that requires an X-Api-Key header,
so the header path is exercised against the real protocol stack too.
"""

from __future__ import annotations

import asyncio
import os
import queue
import subprocess
import sys
import threading
import textwrap

import pytest

from agent_core.core.impl.mcp.config import MCPServerConfig
from agent_core.core.impl.mcp.server import MCPServerConnection

INTEROP_PYTHON = os.environ.get("CRAFTBOT_MCP_INTEROP_PYTHON")
pytestmark = pytest.mark.skipif(
    not INTEROP_PYTHON,
    reason="set CRAFTBOT_MCP_INTEROP_PYTHON to an interpreter with mcp installed",
)

API_KEY = "interop-test-key"  # a test value for a local, throwaway server

SERVER_SCRIPT = textwrap.dedent(
    """
    import socket
    import sys

    import uvicorn
    from mcp.server.mcpserver import MCPServer

    mode, sessions, key = sys.argv[1], sys.argv[2], sys.argv[3]
    server = MCPServer("interop")

    @server.tool()
    def add(a: int, b: int) -> int:
        \"\"\"Add two integers.\"\"\"
        return a + b

    app = server.streamable_http_app(
        json_response=(mode == "json"),
        stateless_http=(sessions == "stateless"),
        host="127.0.0.1",
    )

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            if headers.get(b"x-api-key") != key.encode():
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body",
                            "body": b'{"error": "unauthorized"}'})
                return
        await app(scope, receive, send)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    print(sock.getsockname()[1], flush=True)
    uvicorn.Server(uvicorn.Config(guarded, log_level="warning")).run(sockets=[sock])
    """
)


@pytest.fixture
def sdk_server(tmp_path, request):
    mode, sessions = request.param
    script = tmp_path / "sdk_server.py"
    script.write_text(SERVER_SCRIPT, encoding="utf-8")
    proc = subprocess.Popen(
        [INTEROP_PYTHON, str(script), mode, sessions, API_KEY],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lines: "queue.Queue[str]" = queue.Queue()
    threading.Thread(
        target=lambda: lines.put(proc.stdout.readline()), daemon=True
    ).start()
    try:
        port = int(lines.get(timeout=60).strip())
    except (queue.Empty, ValueError):
        proc.kill()
        raise RuntimeError(f"SDK server did not start: {proc.stderr.read()[-2000:]}")
    try:
        yield f"http://127.0.0.1:{port}/mcp", sessions
    finally:
        proc.kill()
        proc.wait(timeout=10)


def connection(url: str, key: str | None) -> MCPServerConnection:
    entry = {
        "name": "sdk",
        "transport": "http",
        "url": url,
        "timeout": 20,
        "headers": {"X-Api-Key": "${KEY}"},
        "env": {"KEY": key} if key else {"KEY": "wrong-key"},
    }
    return MCPServerConnection(MCPServerConfig.from_dict(entry))


MODES = [
    ("json", "stateful"),
    ("sse", "stateful"),
    ("json", "stateless"),
    ("sse", "stateless"),
]


@pytest.mark.parametrize("sdk_server", MODES, indirect=True, ids=lambda m: "-".join(m))
def test_connect_discover_and_call_against_the_sdk_server(sdk_server):
    url, sessions = sdk_server

    async def scenario():
        conn = connection(url, API_KEY)
        assert await conn.connect(), conn.last_error
        transport = conn._transport
        state = (transport.protocol_version, transport.session_id)
        tools = [t.name for t in conn.tools]
        result = await conn.call_tool("add", {"a": 2, "b": 3})
        await conn.disconnect()
        return state, tools, result

    (version, session_id), tools, result = asyncio.run(scenario())
    assert version in ("2025-03-26", "2025-06-18", "2025-11-25")
    if sessions == "stateful":
        assert session_id
    assert tools == ["add"]
    assert result["status"] == "success"
    assert result["result"] == "5"


@pytest.mark.parametrize(
    "sdk_server", [("json", "stateful")], indirect=True, ids=["json"]
)
def test_a_wrong_key_is_refused_by_the_sdk_server(sdk_server):
    url, _ = sdk_server

    async def scenario():
        conn = connection(url, None)
        return await conn.connect(), conn

    ok, conn = asyncio.run(scenario())
    assert ok is False
    assert "HTTP 401" in conn.last_error
    assert "wrong-key" not in conn.last_error


def test_the_interop_python_really_has_the_sdk():
    out = subprocess.run(
        [
            INTEROP_PYTHON,
            "-c",
            "import mcp, importlib.metadata as m; print(m.version('mcp'))",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    print(f"mcp SDK {out.stdout.strip()} on {sys.version.split()[0]} client")
