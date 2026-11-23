"""In-process Streamable HTTP MCP server for tests (#185).

Follows the MCP spec (2025-03-26 .. 2025-11-25): one endpoint, POST for every
client message, JSON or SSE responses, 202 for notifications, Mcp-Session-Id
issued on initialize, DELETE to end a session, and GET + Last-Event-ID to
resume a stream the server closed early. Behaviour switches let tests make it
misbehave in specific ways.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from aiohttp import web

TOOLS = [
    {
        "name": "echo",
        "description": "Echo text",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }
]


class MockStreamableServer:
    """A spec-shaped Streamable HTTP MCP server with switchable misbehaviour."""

    def __init__(self, *, mode: str = "json", tools=None, name: str = "mock"):
        self.mode = mode  # "json" | "sse"
        self.tools = TOOLS if tools is None else tools
        self.name = name
        self.version = "2025-11-25"
        self.session_id: Optional[str] = "session-1"
        self.required_headers: Dict[str, str] = {}
        self.status_for: Dict[str, int] = {}  # method -> HTTP status
        self.hang_on: set = set()  # methods that never answer
        self.received = asyncio.Event()  # set when a hung method arrives
        self.pre_messages: List[Dict[str, Any]] = []  # SSE before response
        self.close_early = False  # SSE: end the stream without a response
        self.resumable = False  # SSE: close after an event id, resume via GET
        self.expired: set = set()  # session ids that now get HTTP 404
        self._sessions_issued = 1
        self.redirect_to: Optional[str] = None
        self.page_size: Optional[int] = None
        self.requests: List[Dict[str, Any]] = []
        self._pending: Dict[str, Dict[str, Any]] = {}

    def expire(self) -> None:
        """End the current session: requests carrying it get HTTP 404, and
        the next initialize issues a new session id."""
        if self.session_id:
            self.expired.add(self.session_id)

    # ── recording ──
    def calls(self, method: str) -> List[Dict[str, Any]]:
        return [r for r in self.requests if r["method"] == method]

    def _record(self, request: web.Request, body: Optional[dict]) -> None:
        self.requests.append(
            {
                "http": request.method,
                "method": (body or {}).get("method")
                or ("<response>" if body and "id" in body else request.method),
                "headers": {k.lower(): v for k, v in request.headers.items()},
                "body": body,
            }
        )

    # ── routes ──
    async def _post(self, request: web.Request) -> web.StreamResponse:
        body = await request.json()
        self._record(request, body)
        if self.redirect_to:
            return web.Response(status=307, headers={"Location": self.redirect_to})
        for header, value in self.required_headers.items():
            if request.headers.get(header) != value:
                return web.json_response(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32001, "message": "unauthorized"},
                    },
                    status=401,
                )
        if "method" not in body:  # a response to our ping
            return web.Response(status=202)
        method = body["method"]
        if method == "initialize" and self.session_id in self.expired:
            self._sessions_issued += 1
            self.session_id = f"session-{self._sessions_issued}"
        if method != "initialize" and self.session_id:
            sent = request.headers.get("Mcp-Session-Id")
            if sent in self.expired:
                return web.Response(status=404)
            if sent != self.session_id:
                return web.Response(status=400, text="missing session")
        if "id" not in body:  # notification
            return web.Response(status=202)
        if method in self.status_for:
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"code": -32000, "message": "boom {x}"},
                },
                status=self.status_for[method],
            )
        if method in self.hang_on:
            self.received.set()
            await asyncio.Event().wait()
        response = {"jsonrpc": "2.0", "id": body["id"], "result": self._result(body)}
        headers = {}
        if method == "initialize" and self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.mode == "json":
            return web.json_response(response, headers=headers)
        return await self._sse(request, response, headers)

    def _result(self, body: dict) -> Dict[str, Any]:
        method, params = body["method"], body.get("params") or {}
        if method == "initialize":
            return {
                "protocolVersion": self.version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.name, "version": "0"},
            }
        if method == "tools/list":
            if not self.page_size:
                return {"tools": self.tools}
            start = int(params.get("cursor") or 0)
            page = self.tools[start : start + self.page_size]
            result: Dict[str, Any] = {"tools": page}
            if start + self.page_size < len(self.tools):
                result["nextCursor"] = str(start + self.page_size)
            return result
        if method == "tools/call":
            text = params.get("arguments", {}).get("text", "")
            return {"content": [{"type": "text", "text": f"{self.name}:{text}"}]}
        return {}

    async def _sse(self, request, response, headers) -> web.StreamResponse:
        stream = web.StreamResponse(
            headers={"Content-Type": "text/event-stream", **headers}
        )
        await stream.prepare(request)
        for message in self.pre_messages:
            await stream.write(f"data: {json.dumps(message)}\n\n".encode())
        if self.close_early:
            return stream
        if self.resumable:
            event_id = f"evt-{response['id']}"
            self._pending[event_id] = response
            await stream.write(f"id: {event_id}\nretry: 10\ndata:\n\n".encode())
            return stream
        await stream.write(
            f"event: message\nid: 1\ndata: {json.dumps(response)}\n\n".encode()
        )
        return stream

    async def _get(self, request: web.Request) -> web.StreamResponse:
        self._record(request, None)
        response = self._pending.pop(request.headers.get("Last-Event-ID", ""), None)
        if response is None:
            return web.Response(status=405)
        stream = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await stream.prepare(request)
        await stream.write(f"data: {json.dumps(response)}\n\n".encode())
        return stream

    async def _delete(self, request: web.Request) -> web.Response:
        self._record(request, None)
        return web.Response(status=200)

    async def start(self) -> str:
        app = web.Application()
        app.add_routes(
            [
                web.post("/mcp", self._post),
                web.get("/mcp", self._get),
                web.delete("/mcp", self._delete),
            ]
        )
        self._runner = web.AppRunner(app, shutdown_timeout=0.1)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = self._runner.addresses[0][1]
        return f"http://127.0.0.1:{self.port}/mcp"

    async def stop(self) -> None:
        await self._runner.cleanup()


async def serve(**kwargs) -> tuple:
    server = MockStreamableServer(**kwargs)
    url = await server.start()
    return server, url
