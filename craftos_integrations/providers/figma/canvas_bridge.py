"""Local, account-isolated adapter for the published Talk to Figma plugin.

Protocol reference (MIT): grab/cursor-talk-to-figma-mcp, src/cursor_mcp_plugin.
This is a command endpoint, not a general relay: peers cannot issue commands,
receive each other's data, or join a channel already occupied by another peer.
No Figma credential ever crosses this endpoint. It is started explicitly.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
import weakref
from collections import OrderedDict
from dataclasses import dataclass, field

from aiohttp import WSMsgType, web

from .canvas_commands import EDIT_COMMANDS, READ_COMMANDS

PLUGIN_URL = "https://www.figma.com/community/plugin/1485687494525374295/talk-to-figma-mcp-plugin"
PORT = 3055
COMMANDS = (
    frozenset(
        {
            "get_document_info",
            "get_selection",
            "get_node_info",
            "create_frame",
            "create_rectangle",
            "create_text",
            "set_fill_color",
            "set_corner_radius",
            "move_node",
            "resize_node",
            "rename_node",
            "set_text_content",
            "delete_node",
            "set_focus",
        }
    )
    | READ_COMMANDS.keys()
    | EDIT_COMMANDS.keys()
    | {"set_image_fill", "export_node_as_image"}
)


class CanvasError(Exception):
    def __init__(self, message, **details):
        super().__init__(message)
        self.details = details


@dataclass
class Peer:
    socket: web.WebSocketResponse
    channel: str
    owner: object = None  # weak reference; never keeps an invalidated client alive
    touched: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: dict = field(default_factory=dict)
    history: OrderedDict = field(default_factory=OrderedDict)

    def record(self, request_id, value):
        # Export replies can contain megabytes of base64. Status history is
        # diagnostic metadata, not an asset store.
        if len(json.dumps(value, default=str)) > 64 * 1024:
            value = {"state": value["state"], "result_omitted": True}
        self.history[request_id] = value
        while len(self.history) > 128:
            self.history.popitem(last=False)


class CanvasBridge:
    def __init__(self):
        self.runner = None
        self.port = PORT
        self.peers = {}
        self.owners = weakref.WeakSet()
        self.lock = asyncio.Lock()
        self.reaper = None
        self.connections = set()

    async def start(self, owner, *, port=PORT):
        async with self.lock:
            if not self.runner:
                app = web.Application()
                app.router.add_get("/", self.handle)
                runner = web.AppRunner(app, access_log=None)
                await runner.setup()
                try:
                    # localhost resolves to IPv4 or IPv6 in different browsers.
                    site = web.TCPSite(runner, "127.0.0.1", port)
                    await site.start()
                    self.port = site._server.sockets[0].getsockname()[1]
                    try:
                        await web.TCPSite(runner, "::1", self.port).start()
                    except OSError:
                        pass  # IPv4-only hosts remain supported.
                except OSError as exc:
                    await runner.cleanup()
                    raise CanvasError(
                        "Cannot start the local Figma bridge. Port 3055 is in use; stop the other relay and try again."
                    ) from exc
                self.runner = runner
                self.reaper = asyncio.create_task(self.expire())
            self.owners.add(owner)
        return {
            "port": self.port,
            "plugin_url": PLUGIN_URL,
            "instructions": "Open the target Figma design in your browser, run Talk To Figma MCP Plugin, click Connect on port 3055, then pass its channel to connect_figma_canvas. Keep the plugin open.",
        }

    async def handle(self, request):
        origin = request.headers.get("Origin")
        if origin not in {None, "null", "https://www.figma.com", "https://figma.com"}:
            raise web.HTTPForbidden()
        if request.host not in {
            f"localhost:{self.port}",
            f"127.0.0.1:{self.port}",
            f"[::1]:{self.port}",
        }:
            raise web.HTTPForbidden()
        if len(self.connections) >= 8:
            raise web.HTTPServiceUnavailable()
        ws = web.WebSocketResponse(
            max_msg_size=8 * 1024 * 1024, heartbeat=30, receive_timeout=300
        )
        await ws.prepare(request)
        self.connections.add(ws)
        peer = None
        try:
            async for packet in ws:
                if packet.type != WSMsgType.TEXT:
                    break
                try:
                    data = json.loads(packet.data)
                    if not isinstance(data, dict):
                        raise ValueError()
                    kind = data.get("type")
                    if kind == "join" and peer is None:
                        channel = data.get("channel", "")
                        if (
                            not isinstance(channel, str)
                            or not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", channel)
                            or channel in self.peers
                        ):
                            raise ValueError()
                        peer = Peer(ws, channel)
                        self.peers[channel] = peer
                        await ws.send_json(
                            {
                                "type": "system",
                                "channel": channel,
                                "message": {
                                    "result": "Connected to channel: " + channel
                                },
                            }
                        )
                    elif (
                        kind == "progress_update"
                        and peer
                        and data.get("channel") == peer.channel
                    ):
                        pass  # Progress does not extend the bounded request timeout.
                    elif (
                        kind == "message"
                        and peer
                        and data.get("channel") == peer.channel
                    ):
                        message = data.get("message")
                        if not isinstance(message, dict) or "command" in message:
                            raise ValueError()
                        request_id = message.get("id")
                        if request_id not in peer.history:
                            continue  # Unsolicited/duplicate replies cannot complete a request.
                        if peer.history[request_id]["state"] not in {
                            "dispatched",
                            "unknown",
                        }:
                            continue
                        nested = message.get("result")
                        error = message.get("error")
                        if isinstance(nested, dict) and (
                            nested.get("error") or nested.get("success") is False
                        ):
                            error = (
                                nested.get("error")
                                or nested.get("message")
                                or "Plugin command failed."
                            )
                        result = {"state": "error" if error else "completed"}
                        if error:
                            result["error"] = str(error)[:500]
                        else:
                            result["result"] = message.get("result")
                        peer.record(request_id, result)
                        future = peer.pending.get(request_id)
                        if future and not future.done():
                            future.set_result(result)
                    else:
                        raise ValueError()
                except (ValueError, TypeError):
                    await ws.close(code=1008, message=b"Invalid plugin protocol")
                    break
        except asyncio.TimeoutError:
            pass  # Close an idle/unjoined socket without an application error log.
        finally:
            self.connections.discard(ws)
            if peer:
                if self.peers.get(peer.channel) is peer:
                    del self.peers[peer.channel]
                for request_id, future in peer.pending.items():
                    if not future.done():
                        result = {
                            "state": "unknown",
                            "error": "Plugin disconnected; the command may have completed. Inspect the canvas before repeating a write.",
                        }
                        peer.record(request_id, result)
                        future.set_result(result)
            await ws.close()
        return ws

    def claim(self, owner, channel):
        if owner not in self.owners:
            raise CanvasError("Start the bridge with start_figma_canvas first.")
        peer = self.peers.get(channel)
        if not peer or peer.socket.closed:
            raise CanvasError(
                "No plugin is connected on that channel. Run the plugin and copy its current channel."
            )
        if peer.owner is not None and peer.owner() is not owner:
            raise CanvasError("This canvas channel belongs to another account session.")
        peer.owner = weakref.ref(owner)
        peer.touched = time.monotonic()
        return peer

    def check(self, owner, peer):
        if (
            owner not in self.owners
            or not peer
            or peer.owner is None
            or peer.owner() is not owner
            or self.peers.get(peer.channel) is not peer
            or peer.socket.closed
        ):
            raise CanvasError(
                "Canvas is disconnected. Start the bridge and connect the plugin channel again."
            )
        peer.touched = time.monotonic()

    async def command(self, owner, peer, command, params=None, *, timeout=30):
        self.check(owner, peer)
        if command not in COMMANDS:
            raise CanvasError("Unsupported canvas command.")
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        peer.pending[request_id] = future
        peer.record(request_id, {"state": "dispatched", "command": command})
        try:
            await peer.socket.send_json(
                {
                    "type": "broadcast",
                    "channel": peer.channel,
                    "message": {
                        "id": request_id,
                        "command": command,
                        "params": params or {},
                    },
                }
            )
            result = await asyncio.wait_for(asyncio.shield(future), timeout)
            if result["state"] != "completed":
                raise CanvasError(
                    result["error"], request_id=request_id, state=result["state"]
                )
            return result.get("result")
        except (asyncio.TimeoutError, ConnectionError, RuntimeError) as exc:
            # Never resend. A late correlated reply can update status afterwards.
            peer.record(request_id, {"state": "unknown", "command": command})
            raise CanvasError(
                "Canvas command timed out or lost its connection and may have completed. Check get_figma_canvas_status with request_id and inspect the canvas before repeating a write.",
                request_id=request_id,
                state="unknown",
            ) from exc
        except asyncio.CancelledError:
            peer.record(request_id, {"state": "unknown", "command": command})
            raise
        finally:
            peer.pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    async def stop(self, owner):
        async with self.lock:
            self.owners.discard(owner)
            for peer in list(self.peers.values()):
                if peer.owner is not None and peer.owner() is owner:
                    await peer.socket.close()
            if not self.owners and self.runner:
                for ws in list(self.connections):
                    await ws.close()
                self.reaper.cancel()
                await asyncio.gather(self.reaper, return_exceptions=True)
                await self.runner.cleanup()
                self.runner = None
                self.peers.clear()

    async def expire(self):
        while True:
            await asyncio.sleep(30)
            for peer in list(self.peers.values()):
                age = time.monotonic() - peer.touched
                if (peer.owner is None and age > 300) or (
                    peer.owner is not None and (peer.owner() is None or age > 900)
                ):
                    await peer.socket.close()


_bridges = weakref.WeakKeyDictionary()


def bridge():
    loop = asyncio.get_running_loop()
    if loop not in _bridges:
        _bridges[loop] = CanvasBridge()
    return _bridges[loop]
