# -*- coding: utf-8 -*-
"""
MCP Server Connection Module

Manages connections to individual MCP servers with support for multiple transports:
- stdio: Subprocess-based communication
- sse: HTTP Server-Sent Events
- websocket: WebSocket bidirectional communication
"""

import asyncio
import os
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent_core.utils.logger import logger
from agent_core.core.impl.mcp.config import MCPServerConfig

# Default client info - can be overridden
DEFAULT_CLIENT_NAME = "Agent"
DEFAULT_CLIENT_VERSION = "1.0.0"

# Module-level client info (can be set by runtime)
_client_name: str = DEFAULT_CLIENT_NAME
_client_version: str = DEFAULT_CLIENT_VERSION


def set_client_info(name: str, version: str = "1.0.0") -> None:
    """Set the client info used in MCP protocol initialization."""
    global _client_name, _client_version
    _client_name = name
    _client_version = version


def get_client_info() -> Dict[str, str]:
    """Get the current client info."""
    return {"name": _client_name, "version": _client_version}


@dataclass
class MCPTool:
    """Represents an MCP tool discovered from a server."""

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPTool":
        """Create MCPTool from dictionary."""
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            input_schema=data.get("inputSchema", {}),
        )


class MCPTransport(ABC):
    """Abstract base class for MCP transports."""

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection. Returns True if successful."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection."""
        pass

    @abstractmethod
    async def send_request(self, method: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request and return the response."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the transport is connected."""
        pass


class StdioTransport(MCPTransport):
    """Stdio transport using subprocess communication."""

    def __init__(self, command: str, args: List[str], env: Dict[str, str]):
        self.command = command
        self.args = args
        self.env = env
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _resolve_command(self, command: str) -> str:
        """
        Resolve the command path, handling Windows-specific issues.

        On Windows, commands like 'npx' are actually 'npx.cmd' batch files.
        This method attempts to find the actual executable path.
        """
        if sys.platform != "win32":
            return command

        # On Windows, try to find the actual path
        # First check if it's already an absolute path
        if os.path.isabs(command) and os.path.exists(command):
            return command

        # Try to find the command using shutil.which
        # This handles .cmd, .bat, .exe extensions automatically on Windows
        resolved = shutil.which(command)
        if resolved:
            logger.debug(f"[StdioTransport] Resolved '{command}' to '{resolved}'")
            return resolved

        # Try common extensions on Windows
        for ext in ['.cmd', '.bat', '.exe', '']:
            resolved = shutil.which(command + ext)
            if resolved:
                logger.debug(f"[StdioTransport] Resolved '{command}' to '{resolved}'")
                return resolved

        # Return original command if not found (will likely fail later)
        logger.warning(f"[StdioTransport] Could not resolve command '{command}' in PATH")
        return command

    async def connect(self) -> bool:
        """Start the subprocess and establish connection."""
        try:
            # Merge environment
            full_env = os.environ.copy()
            full_env.update(self.env)

            # Resolve command path, especially for Windows
            command = self._resolve_command(self.command)

            logger.info(f"[StdioTransport] Starting subprocess: {command} {' '.join(self.args)}")

            # Start the subprocess
            try:
                if sys.platform == "win32":
                    # On Windows, use shell=True to properly resolve commands like npx
                    # This allows Windows to find npx.cmd in PATH
                    full_command = f'"{command}" ' + ' '.join(f'"{arg}"' for arg in self.args)
                    logger.debug(f"[StdioTransport] Windows shell command: {full_command}")
                    self._process = await asyncio.create_subprocess_shell(
                        full_command,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env=full_env,
                    )
                else:
                    self._process = await asyncio.create_subprocess_exec(
                        command,
                        *self.args,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env=full_env,
                    )
            except FileNotFoundError as e:
                logger.error(f"[StdioTransport] Command not found: '{command}'. Make sure it is installed and in PATH. Error: {e}")
                return False
            except Exception as e:
                logger.error(f"[StdioTransport] Failed to start subprocess: {type(e).__name__}: {e}")
                return False

            logger.debug(f"[StdioTransport] Subprocess started with PID {self._process.pid}")

            # Send initialize request
            client_info = get_client_info()
            init_response = await self.send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": client_info
            })

            if "error" in init_response:
                error_msg = init_response.get('error', {})
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get('message', str(error_msg))
                logger.error(f"[StdioTransport] MCP initialize failed: {error_msg}")

                # Try to read stderr for more info
                if self._process and self._process.stderr:
                    try:
                        stderr_data = await asyncio.wait_for(
                            self._process.stderr.read(1024),
                            timeout=1.0
                        )
                        if stderr_data:
                            logger.error(f"[StdioTransport] Subprocess stderr: {stderr_data.decode()}")
                    except:
                        pass

                await self.disconnect()
                return False

            # Send initialized notification
            await self._send_notification("notifications/initialized", {})

            logger.info(f"[StdioTransport] Connected successfully")
            return True

        except Exception as e:
            logger.error(f"[StdioTransport] Failed to connect: {type(e).__name__}: {e}")

            # Try to capture stderr if process exists
            if self._process and self._process.stderr:
                try:
                    stderr_data = await asyncio.wait_for(
                        self._process.stderr.read(1024),
                        timeout=1.0
                    )
                    if stderr_data:
                        logger.error(f"[StdioTransport] Subprocess stderr: {stderr_data.decode()}")
                except:
                    pass

            await self.disconnect()
            return False

    async def disconnect(self) -> None:
        """Terminate the subprocess."""
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._process = None

    async def send_request(self, method: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request and wait for response."""
        import json

        if not self.is_connected:
            return {"error": {"code": -1, "message": "Not connected"}}

        async with self._lock:
            self._request_id += 1
            request_id = self._request_id

            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
            }
            if params is not None:
                request["params"] = params

            try:
                # Send request
                request_line = json.dumps(request) + "\n"
                logger.debug(f"[StdioTransport] Sending: {request_line.strip()}")
                self._process.stdin.write(request_line.encode())
                await self._process.stdin.drain()

                # Read response - keep reading until we get a response with matching id
                # (skip notifications which don't have an id)
                while True:
                    response_line = await asyncio.wait_for(
                        self._process.stdout.readline(),
                        timeout=30.0
                    )

                    if not response_line:
                        # Check if process has died
                        if self._process.returncode is not None:
                            # Try to read stderr
                            stderr = ""
                            try:
                                stderr_data = await asyncio.wait_for(
                                    self._process.stderr.read(),
                                    timeout=1.0
                                )
                                stderr = stderr_data.decode() if stderr_data else ""
                            except:
                                pass
                            return {"error": {"code": -1, "message": f"Process exited with code {self._process.returncode}. Stderr: {stderr}"}}
                        return {"error": {"code": -1, "message": "No response from server (empty line)"}}

                    response_str = response_line.decode().strip()
                    if not response_str:
                        continue  # Skip empty lines

                    logger.debug(f"[StdioTransport] Received: {response_str[:200]}...")

                    try:
                        response = json.loads(response_str)
                    except json.JSONDecodeError as e:
                        logger.warning(f"[StdioTransport] Invalid JSON, skipping: {response_str[:100]}")
                        continue

                    # Check if this is a response to our request
                    if "id" in response and response["id"] == request_id:
                        return response
                    elif "id" not in response:
                        # This is a notification, skip it
                        logger.debug(f"[StdioTransport] Received notification: {response.get('method', 'unknown')}")
                        continue
                    else:
                        # Response for a different request (shouldn't happen with sequential requests)
                        logger.warning(f"[StdioTransport] Received response for different request id: {response.get('id')}")
                        continue

            except asyncio.TimeoutError:
                logger.error(f"[StdioTransport] Request timeout for method '{method}'")
                return {"error": {"code": -1, "message": f"Request timeout waiting for response to '{method}'"}}
            except json.JSONDecodeError as e:
                logger.error(f"[StdioTransport] Invalid JSON response: {e}")
                return {"error": {"code": -1, "message": f"Invalid JSON response: {e}"}}
            except Exception as e:
                logger.error(f"[StdioTransport] Error sending request: {type(e).__name__}: {e}")
                return {"error": {"code": -1, "message": str(e)}}

    async def _send_notification(self, method: str, params: Optional[Dict] = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        import json

        if not self.is_connected:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        try:
            notification_line = json.dumps(notification) + "\n"
            self._process.stdin.write(notification_line.encode())
            await self._process.stdin.drain()
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")


class SSETransport(MCPTransport):
    """SSE (Server-Sent Events) transport for HTTP-based MCP servers."""

    def __init__(self, url: str, env: Dict[str, str]):
        self.url = url
        self.env = env
        self._connected = False
        self._client = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._sse_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """Connect to SSE endpoint."""
        try:
            import httpx

            # Create HTTP client
            self._client = httpx.AsyncClient(timeout=30.0)

            # Start SSE listener task
            self._sse_task = asyncio.create_task(self._listen_sse())

            # Send initialize request
            client_info = get_client_info()
            init_response = await self.send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": client_info
            })

            if "error" in init_response:
                logger.error(f"SSE initialize failed: {init_response['error']}")
                await self.disconnect()
                return False

            self._connected = True
            logger.info(f"SSE transport connected to {self.url}")
            return True

        except ImportError:
            logger.error("httpx not installed. Install with: pip install httpx")
            return False
        except Exception as e:
            logger.error(f"Failed to connect SSE transport: {e}")
            await self.disconnect()
            return False

    async def disconnect(self) -> None:
        """Close SSE connection."""
        self._connected = False

        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
            self._sse_task = None

        if self._client:
            await self._client.aclose()
            self._client = None

        # Cancel pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(Exception("Connection closed"))
        self._pending_requests.clear()

    async def _listen_sse(self) -> None:
        """Listen for SSE events."""
        import json

        try:
            async with self._client.stream("GET", self.url) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        try:
                            message = json.loads(data)
                            if "id" in message and message["id"] in self._pending_requests:
                                future = self._pending_requests.pop(message["id"])
                                if not future.done():
                                    future.set_result(message)
                        except json.JSONDecodeError:
                            continue
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"SSE listener error: {e}")
            self._connected = False

    async def send_request(self, method: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request via POST and wait for SSE response."""
        import json

        if not self._client:
            return {"error": {"code": -1, "message": "Not connected"}}

        async with self._lock:
            self._request_id += 1
            request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        # Create future for response
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            # Send POST request
            post_url = self.url.replace("/sse", "/message")
            await self._client.post(post_url, json=request)

            # Wait for response via SSE
            response = await asyncio.wait_for(future, timeout=30.0)
            return response

        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            return {"error": {"code": -1, "message": "Request timeout"}}
        except Exception as e:
            self._pending_requests.pop(request_id, None)
            return {"error": {"code": -1, "message": str(e)}}


class WebSocketTransport(MCPTransport):
    """WebSocket transport for bidirectional MCP communication."""

    def __init__(self, url: str, env: Dict[str, str]):
        self.url = url
        self.env = env
        self._ws = None
        self._connected = False
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    async def connect(self) -> bool:
        """Connect to WebSocket endpoint."""
        try:
            import websockets

            self._ws = await websockets.connect(self.url)

            # Start listener task
            self._listener_task = asyncio.create_task(self._listen_messages())

            # Send initialize request
            client_info = get_client_info()
            init_response = await self.send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": client_info
            })

            if "error" in init_response:
                logger.error(f"WebSocket initialize failed: {init_response['error']}")
                await self.disconnect()
                return False

            # Send initialized notification
            await self._send_notification("notifications/initialized", {})

            self._connected = True
            logger.info(f"WebSocket transport connected to {self.url}")
            return True

        except ImportError:
            logger.error("websockets not installed. Install with: pip install websockets")
            return False
        except Exception as e:
            logger.error(f"Failed to connect WebSocket transport: {e}")
            await self.disconnect()
            return False

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._connected = False

        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        # Cancel pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(Exception("Connection closed"))
        self._pending_requests.clear()

    async def _listen_messages(self) -> None:
        """Listen for WebSocket messages."""
        import json

        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                    if "id" in data and data["id"] in self._pending_requests:
                        future = self._pending_requests.pop(data["id"])
                        if not future.done():
                            future.set_result(data)
                except json.JSONDecodeError:
                    continue
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"WebSocket listener error: {e}")
            self._connected = False

    async def send_request(self, method: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request and wait for response."""
        import json

        if not self.is_connected:
            return {"error": {"code": -1, "message": "Not connected"}}

        async with self._lock:
            self._request_id += 1
            request_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        # Create future for response
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            await self._ws.send(json.dumps(request))
            response = await asyncio.wait_for(future, timeout=30.0)
            return response

        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            return {"error": {"code": -1, "message": "Request timeout"}}
        except Exception as e:
            self._pending_requests.pop(request_id, None)
            return {"error": {"code": -1, "message": str(e)}}

    async def _send_notification(self, method: str, params: Optional[Dict] = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        import json

        if not self.is_connected:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params

        try:
            await self._ws.send(json.dumps(notification))
        except Exception as e:
            logger.warning(f"Failed to send WebSocket notification: {e}")


class MCPServerConnection:
    """
    Manages connection to a single MCP server.

    Handles transport selection, connection lifecycle, tool discovery, and tool execution.
    """

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._transport: Optional[MCPTransport] = None
        self._tools: List[MCPTool] = []

    @property
    def is_connected(self) -> bool:
        """Check if the server is connected."""
        return self._transport is not None and self._transport.is_connected

    @property
    def tools(self) -> List[MCPTool]:
        """Get the list of discovered tools."""
        return self._tools

    def _create_transport(self) -> MCPTransport:
        """Create the appropriate transport based on config."""
        if self.config.transport == "stdio":
            return StdioTransport(
                command=self.config.command,
                args=self.config.args,
                env=self.config.env,
            )
        elif self.config.transport == "sse":
            return SSETransport(
                url=self.config.url,
                env=self.config.env,
            )
        elif self.config.transport == "websocket":
            return WebSocketTransport(
                url=self.config.url,
                env=self.config.env,
            )
        else:
            raise ValueError(f"Unknown transport: {self.config.transport}")

    async def connect(self) -> bool:
        """
        Connect to the MCP server and discover tools.

        Returns:
            True if connection and tool discovery succeeded
        """
        if self.is_connected:
            logger.warning(f"Server '{self.config.name}' is already connected")
            return True

        try:
            # Create and connect transport
            logger.debug(f"[MCPServer:{self.config.name}] Creating {self.config.transport} transport...")
            self._transport = self._create_transport()

            logger.debug(f"[MCPServer:{self.config.name}] Connecting transport...")
            if not await self._transport.connect():
                logger.error(f"[MCPServer:{self.config.name}] Transport connection failed")
                self._transport = None
                return False

            # Discover tools
            logger.debug(f"[MCPServer:{self.config.name}] Discovering tools...")
            await self._discover_tools()

            if self._tools:
                logger.info(
                    f"[MCPServer:{self.config.name}] Connected via {self.config.transport}, "
                    f"discovered {len(self._tools)} tools: {[t.name for t in self._tools]}"
                )
            else:
                logger.warning(
                    f"[MCPServer:{self.config.name}] Connected but no tools discovered. "
                    "Server may not have exposed any tools."
                )

            return True

        except Exception as e:
            logger.error(f"[MCPServer:{self.config.name}] Failed to connect: {type(e).__name__}: {e}")
            await self.disconnect()
            return False

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._transport:
            await self._transport.disconnect()
            self._transport = None
        self._tools = []
        logger.info(f"Disconnected from MCP server '{self.config.name}'")

    async def reconnect(self) -> bool:
        """Attempt to reconnect to the server."""
        await self.disconnect()
        return await self.connect()

    async def _discover_tools(self) -> None:
        """Discover available tools from the server."""
        if not self.is_connected:
            logger.warning(f"[MCPServer:{self.config.name}] Cannot discover tools - not connected")
            return

        response = await self._transport.send_request("tools/list", {})

        if "error" in response:
            error_info = response.get('error', {})
            if isinstance(error_info, dict):
                error_msg = error_info.get('message', str(error_info))
            else:
                error_msg = str(error_info)
            logger.warning(f"[MCPServer:{self.config.name}] Failed to list tools: {error_msg}")
            return

        result = response.get("result", {})
        tools_data = result.get("tools", [])

        if not tools_data:
            logger.debug(f"[MCPServer:{self.config.name}] Server returned empty tools list. Response: {response}")

        self._tools = [MCPTool.from_dict(t) for t in tools_data]

        logger.debug(
            f"[MCPServer:{self.config.name}] Discovered {len(self._tools)} tools: {[t.name for t in self._tools]}"
        )

    async def list_tools(self) -> List[MCPTool]:
        """
        Get list of available tools, refreshing from server if needed.

        Returns:
            List of MCPTool objects
        """
        if not self.is_connected:
            return []

        await self._discover_tools()
        return self._tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        if not self.is_connected:
            return {
                "status": "error",
                "message": f"MCP server '{self.config.name}' is not connected",
            }

        try:
            response = await self._transport.send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            })

            if "error" in response:
                return {
                    "status": "error",
                    "message": response["error"].get("message", "Unknown error"),
                    "code": response["error"].get("code"),
                }

            result = response.get("result", {})

            # Extract content from MCP result format
            content = result.get("content", [])
            if content:
                # Combine all text content
                text_parts = []
                for item in content:
                    if item.get("type") == "text":
                        text_parts.append(item.get("text", ""))

                return {
                    "status": "success",
                    "result": "\n".join(text_parts) if text_parts else result,
                    "raw_content": content,
                }

            return {
                "status": "success",
                "result": result,
            }

        except Exception as e:
            logger.error(f"Error calling tool '{tool_name}': {e}")
            return {
                "status": "error",
                "message": str(e),
            }
