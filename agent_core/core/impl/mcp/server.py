# -*- coding: utf-8 -*-
"""
MCP Server Connection Module

Manages connections to individual MCP servers with support for multiple transports:
- stdio: Subprocess-based communication
- sse: HTTP Server-Sent Events
- websocket: WebSocket bidirectional communication
- http: Streamable HTTP (one endpoint, POST + JSON or SSE responses)
"""

import asyncio
import json
import os
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from agent_core.utils.logger import logger
from agent_core.utils.windows_process import hidden_console_kwargs
from agent_core.core.impl.mcp.config import MCPConfigError, MCPServerConfig, redact_url

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


# Working directory for stdio server subprocesses whose config has no "cwd".
# Without it they inherit the host process cwd, and servers that write
# cwd-relative artifacts (e.g. playwright's .playwright-mcp/) litter the
# install root with files the agent's own file tools can't find.
_default_stdio_cwd: Optional[str] = None


def set_default_stdio_cwd(path: Optional[str]) -> None:
    """Set the default working directory for stdio MCP server subprocesses."""
    global _default_stdio_cwd
    _default_stdio_cwd = path


def get_default_stdio_cwd() -> Optional[str]:
    """Get the default working directory for stdio MCP server subprocesses."""
    return _default_stdio_cwd


# Windows runs a .cmd/.bat through cmd.exe however it is spawned, and cmd.exe
# re-parses the whole command line — so an argument carrying one of these
# escapes into a second command even when the arguments are passed as a list.
# No quoting closes it (this is the "BatBadBut" class, CVE-2024-24576 in other
# runtimes), so the argument is refused rather than pretended to be escaped.
# `^` and `%` are deliberately absent: `^` only escapes the next character and
# cannot start a command, and rejecting `%` would break percent-encoded URLs,
# which are ordinary MCP arguments. The worst `%` can do is expand an
# environment variable into a value the same config already controls.
_CMD_METACHARACTERS = '"&|<>\r\n'


def _reject_unsafe_batch_args(command: str, args: List[str]) -> None:
    """Refuse arguments cmd.exe would reinterpret when the target is a batch
    wrapper. No-op off Windows and for real executables, where the argument
    list reaches the process untouched."""
    if sys.platform != "win32":
        return
    if os.path.splitext(command)[1].lower() not in (".cmd", ".bat"):
        return
    for arg in args:
        found = sorted({c for c in str(arg) if c in _CMD_METACHARACTERS})
        if found:
            shown = "".join(c if c not in "\r\n" else repr(c).strip("'") for c in found)
            raise ValueError(
                f"MCP server argument {arg!r} contains {shown!r}, which cmd.exe "
                f"would interpret while running the batch wrapper "
                f"{os.path.basename(command)} — it could run a second command. "
                f"Rewrite the argument, or point the server at the real "
                f"executable instead of the .cmd shim."
            )


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

    # Why the last connect() failed, when the transport can say so safely
    # (no header or env values). None means "see the log".
    last_error: Optional[str] = None

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection. Returns True if successful."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection."""
        pass

    @abstractmethod
    async def send_request(
        self, method: str, params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Send a JSON-RPC request and return the response."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the transport is connected."""
        pass


class StdioTransport(MCPTransport):
    """Stdio transport using subprocess communication."""

    def __init__(
        self,
        command: str,
        args: List[str],
        env: Dict[str, str],
        cwd: Optional[str] = None,
    ):
        self.command = command
        self.args = args
        self.env = env
        self.cwd = cwd
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
        for ext in [".cmd", ".bat", ".exe", ""]:
            resolved = shutil.which(command + ext)
            if resolved:
                logger.debug(f"[StdioTransport] Resolved '{command}' to '{resolved}'")
                return resolved

        # Return original command if not found (will likely fail later)
        logger.warning(
            f"[StdioTransport] Could not resolve command '{command}' in PATH"
        )
        return command

    async def connect(self) -> bool:
        """Start the subprocess and establish connection."""
        try:
            # Merge environment
            full_env = os.environ.copy()
            full_env.update(self.env)

            # Resolve command path, especially for Windows
            command = self._resolve_command(self.command)

            cwd = self.cwd or _default_stdio_cwd

            logger.info(
                f"[StdioTransport] Starting subprocess: {command} {' '.join(self.args)}"
                f" (cwd={cwd or os.getcwd()})"
            )

            # Start the subprocess. One exec path for both platforms: the
            # arguments reach the OS as a list, so an argument can never be
            # read back as part of the command line. _resolve_command has
            # already turned `command` into a concrete path (npx.cmd, uvx.exe,
            # ...), so there is nothing left for a shell to look up.
            _reject_unsafe_batch_args(command, self.args)
            try:
                self._process = await asyncio.create_subprocess_exec(
                    command,
                    *self.args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=full_env,
                    cwd=cwd,
                    **hidden_console_kwargs(),
                    limit=10
                    * 1024
                    * 1024,  # 10MB limit for large MCP responses (e.g., screenshots)
                )
            except FileNotFoundError as e:
                logger.error(
                    f"[StdioTransport] Command not found: '{command}'. Make sure it is installed and in PATH. Error: {e}"
                )
                return False
            except Exception as e:
                logger.error(
                    f"[StdioTransport] Failed to start subprocess: {type(e).__name__}: {e}"
                )
                return False

            logger.debug(
                f"[StdioTransport] Subprocess started with PID {self._process.pid}"
            )

            # Send initialize request
            client_info = get_client_info()
            init_response = await self.send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": client_info,
                },
            )

            if "error" in init_response:
                error_msg = init_response.get("error", {})
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))
                logger.error(f"[StdioTransport] MCP initialize failed: {error_msg}")

                # Try to read stderr for more info
                if self._process and self._process.stderr:
                    try:
                        stderr_data = await asyncio.wait_for(
                            self._process.stderr.read(1024), timeout=1.0
                        )
                        if stderr_data:
                            logger.error(
                                f"[StdioTransport] Subprocess stderr: {stderr_data.decode()}"
                            )
                    except Exception:
                        pass

                await self.disconnect()
                return False

            # Send initialized notification
            await self._send_notification("notifications/initialized", {})

            logger.info("[StdioTransport] Connected successfully")
            return True

        except Exception as e:
            logger.error(f"[StdioTransport] Failed to connect: {type(e).__name__}: {e}")

            # Try to capture stderr if process exists
            if self._process and self._process.stderr:
                try:
                    stderr_data = await asyncio.wait_for(
                        self._process.stderr.read(1024), timeout=1.0
                    )
                    if stderr_data:
                        logger.error(
                            f"[StdioTransport] Subprocess stderr: {stderr_data.decode()}"
                        )
                except Exception:
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

    async def send_request(
        self, method: str, params: Optional[Dict] = None
    ) -> Dict[str, Any]:
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
                        self._process.stdout.readline(), timeout=30.0
                    )

                    if not response_line:
                        # Check if process has died
                        if self._process.returncode is not None:
                            # Try to read stderr
                            stderr = ""
                            try:
                                stderr_data = await asyncio.wait_for(
                                    self._process.stderr.read(), timeout=1.0
                                )
                                stderr = stderr_data.decode() if stderr_data else ""
                            except Exception:
                                pass
                            return {
                                "error": {
                                    "code": -1,
                                    "message": f"Process exited with code {self._process.returncode}. Stderr: {stderr}",
                                }
                            }
                        return {
                            "error": {
                                "code": -1,
                                "message": "No response from server (empty line)",
                            }
                        }

                    response_str = response_line.decode().strip()
                    if not response_str:
                        continue  # Skip empty lines

                    logger.debug(f"[StdioTransport] Received: {response_str[:200]}...")

                    try:
                        response = json.loads(response_str)
                    except json.JSONDecodeError:
                        logger.warning(
                            f"[StdioTransport] Invalid JSON, skipping: {response_str[:100]}"
                        )
                        continue

                    # Check if this is a response to our request
                    if "id" in response and response["id"] == request_id:
                        return response
                    elif "id" not in response:
                        # This is a notification, skip it
                        logger.debug(
                            f"[StdioTransport] Received notification: {response.get('method', 'unknown')}"
                        )
                        continue
                    else:
                        # Response for a different request (shouldn't happen with sequential requests)
                        logger.warning(
                            f"[StdioTransport] Received response for different request id: {response.get('id')}"
                        )
                        continue

            except asyncio.TimeoutError:
                logger.error(f"[StdioTransport] Request timeout for method '{method}'")
                return {
                    "error": {
                        "code": -1,
                        "message": f"Request timeout waiting for response to '{method}'",
                    }
                }
            except json.JSONDecodeError as e:
                logger.error(f"[StdioTransport] Invalid JSON response: {e}")
                return {"error": {"code": -1, "message": f"Invalid JSON response: {e}"}}
            except Exception as e:
                logger.error(
                    f"[StdioTransport] Error sending request: {type(e).__name__}: {e}"
                )
                return {"error": {"code": -1, "message": str(e)}}

    async def _send_notification(
        self, method: str, params: Optional[Dict] = None
    ) -> None:
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
    """SSE (Server-Sent Events) transport for HTTP-based MCP servers.

    Per the MCP SSE spec, the server's first event is ``endpoint`` and carries
    the URL that JSON-RPC requests must be POSTed to. That URL is not derivable
    from the SSE URL (the official Python SDK serves ``/sse`` and
    ``/messages/?session_id=...``), so it is read from the stream.
    """

    # How long connect() waits for the server's ``endpoint`` event.
    ENDPOINT_TIMEOUT = 10.0

    def __init__(self, url: str, env: Dict[str, str]):
        self.url = url
        self.env = env
        self._connected = False
        self._endpoint: Optional[str] = None
        self._endpoint_ready = asyncio.Event()
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

            # The server announces where to POST in its first event.
            try:
                await asyncio.wait_for(
                    self._endpoint_ready.wait(), timeout=self.ENDPOINT_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"SSE server at {self.url} sent no endpoint event; "
                    f"falling back to {self._post_url()}"
                )

            # Send initialize request
            client_info = get_client_info()
            init_response = await self.send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": client_info,
                },
            )

            if "error" in init_response:
                logger.error(f"SSE initialize failed: {init_response['error']}")
                await self.disconnect()
                return False

            self._connected = True
            await self._send_notification("notifications/initialized", {})
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

    def _post_url(self) -> str:
        """URL requests are POSTed to: the announced endpoint, else a guess."""
        return self._endpoint or self.url.replace("/sse", "/message")

    @staticmethod
    def _origin(url: str) -> tuple:
        """(scheme, hostname, effective port), so `:443` equals the default."""
        parts = urlparse(url)
        port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
        return (parts.scheme, parts.hostname, port)

    def _accept_endpoint(self, data: str) -> None:
        """Record the endpoint the server announced, if it is same-origin."""
        endpoint = urljoin(self.url, data)
        if self._origin(self.url) != self._origin(endpoint):
            logger.warning(
                f"Ignoring SSE endpoint {endpoint}: origin differs from {self.url}"
            )
            return
        self._endpoint = endpoint
        self._endpoint_ready.set()

    async def _listen_sse(self) -> None:
        """Listen for SSE events."""
        import json

        # SSE fields arrive in any order; an event is complete at the blank line.
        event_name = ""
        data_lines: List[str] = []
        try:
            async with self._client.stream("GET", self.url) as response:
                async for line in response.aiter_lines():
                    if line:
                        field_name, _, value = line.partition(":")
                        value = value[1:] if value.startswith(" ") else value
                        if field_name == "event":
                            event_name = value
                        elif field_name == "data":
                            data_lines.append(value)
                        continue
                    data = "\n".join(data_lines)
                    name, event_name, data_lines = event_name, "", []
                    if not data:
                        continue
                    if name == "endpoint":
                        self._accept_endpoint(data.strip())
                        continue
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

    async def send_request(
        self, method: str, params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Send a JSON-RPC request via POST and wait for SSE response."""

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
            await self._client.post(self._post_url(), json=request)

            # Wait for response via SSE
            response = await asyncio.wait_for(future, timeout=30.0)
            return response

        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            return {"error": {"code": -1, "message": "Request timeout"}}
        except Exception as e:
            self._pending_requests.pop(request_id, None)
            return {"error": {"code": -1, "message": str(e)}}

    async def _send_notification(
        self, method: str, params: Optional[Dict] = None
    ) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._client:
            return

        notification: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            notification["params"] = params

        try:
            await self._client.post(self._post_url(), json=notification)
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")


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
            init_response = await self.send_request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": client_info,
                },
            )

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
            logger.error(
                "websockets not installed. Install with: pip install websockets"
            )
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

    async def send_request(
        self, method: str, params: Optional[Dict] = None
    ) -> Dict[str, Any]:
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

    async def _send_notification(
        self, method: str, params: Optional[Dict] = None
    ) -> None:
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


class _HTTPTransportError(Exception):
    """A Streamable HTTP failure whose message is safe to log and show: it
    never contains header values, and URLs in it are redacted."""


class _SessionExpired(_HTTPTransportError):
    """HTTP 404 on a request that carried a session id: the session ended."""


def _clean_server_text(text: Any, limit: int = 300) -> str:
    """Server-supplied text for a log line or error: printable, bounded."""
    text = "".join(c if c.isprintable() else " " for c in str(text))
    return text if len(text) <= limit else text[: limit - 3] + "..."


class StreamableHTTPTransport(MCPTransport):
    """Streamable HTTP transport (MCP 2025-03-26 and later).

    Every client message is a POST to one endpoint. A request is answered
    either with one JSON body or with an SSE stream that may carry server
    requests and notifications before the response; notifications and
    responses are accepted with 202. The server may issue an
    ``Mcp-Session-Id`` on the initialize response; it is sent back on every
    later request, together with ``MCP-Protocol-Version``.

    Each instance owns one ``httpx.AsyncClient`` with this server's headers
    only. Redirects are never followed, so configured credentials cannot be
    sent to another URL. Requests run concurrently (no transport lock);
    each is bounded by ``timeout`` from start to response.

    Not implemented (optional in the spec): the standalone GET stream for
    unsolicited server messages, and sampling/elicitation/roots, which this
    client does not advertise. A server request on a response stream is
    answered (``ping``) or refused with "method not found".
    """

    # Requested in initialize; the server may answer with any version below.
    PROTOCOL_VERSION = "2025-11-25"
    SUPPORTED_PROTOCOL_VERSIONS = ("2025-03-26", "2025-06-18", "2025-11-25")
    MAX_MESSAGE_BYTES = 16 * 1024 * 1024
    MAX_ERROR_BODY_BYTES = 64 * 1024
    # Streams a 2025-11-25 server closes before answering are resumed with
    # GET + Last-Event-ID this many times, within the request deadline.
    MAX_RESUME_ATTEMPTS = 2
    DEFAULT_RETRY_MS = 1000
    MAX_RETRY_MS = 5000
    DELETE_TIMEOUT = 5.0
    # How long to keep reading a stream after its response (see _drain).
    DRAIN_TIMEOUT = 1.0

    def __init__(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
        server_name: str = "",
        *,
        _http_transport: Any = None,
    ):
        self.url = url
        self.timeout = float(timeout)
        self.server_name = server_name or redact_url(url)
        # Copied: this transport never shares a header dict with another.
        self._headers: Dict[str, str] = dict(headers or {})
        self._http_transport = _http_transport  # test seam (httpx.MockTransport)
        self._client: Any = None  # httpx.AsyncClient while connected
        self._connected = False
        self._session_id: Optional[str] = None
        self._protocol_version: Optional[str] = None
        self._renew_lock = asyncio.Lock()
        self._request_id = 0
        self.server_info: Dict[str, Any] = {}
        self.last_error: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def protocol_version(self) -> Optional[str]:
        return self._protocol_version

    def _log_prefix(self) -> str:
        return f"[MCP:{self.server_name}]"

    # ─────────────────────── Lifecycle ──────────────────────────────────────

    async def connect(self) -> bool:
        """Run the initialize handshake. False (with ``last_error`` set) when
        the server cannot be reached, rejects the client, or negotiates a
        protocol version this client does not speak."""
        import httpx

        self.last_error = None
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=False,
            transport=self._http_transport,
        )
        try:
            await asyncio.wait_for(self._initialize(), timeout=self.timeout)
        except asyncio.CancelledError:
            await self._close(send_delete=False)
            raise
        except asyncio.TimeoutError:
            self.last_error = f"initialize timed out after {self.timeout:g}s"
        except _HTTPTransportError as e:
            self.last_error = str(e)
        except Exception as e:  # noqa: BLE001 — reported, never swallowed
            self.last_error = f"initialize failed: {type(e).__name__}"
        else:
            self._connected = True
            logger.info(
                f"{self._log_prefix()} Connected to {redact_url(self.url)} "
                f"(protocol {self._protocol_version}"
                f"{', session' if self._session_id else ''})"
            )
            return True
        logger.error(f"{self._log_prefix()} {self.last_error}")
        await self._close(send_delete=True)
        return False

    async def _initialize(self) -> None:
        response = await self._exchange(
            "initialize",
            {
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": get_client_info(),
            },
            initializing=True,
        )
        if "error" in response:
            raise _HTTPTransportError(
                f"initialize rejected: {self._error_text(response['error'])}"
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise _HTTPTransportError("initialize returned no result")
        version = result.get("protocolVersion")
        if version not in self.SUPPORTED_PROTOCOL_VERSIONS:
            raise _HTTPTransportError(
                f"server negotiated protocol version {_clean_server_text(version, 40)!r}, "
                f"supported: {', '.join(self.SUPPORTED_PROTOCOL_VERSIONS)}"
            )
        self._protocol_version = version
        info = result.get("serverInfo")
        self.server_info = info if isinstance(info, dict) else {}
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def disconnect(self) -> None:
        """End the session (DELETE, best effort) and close the client."""
        await self._close(send_delete=True)

    async def _close(self, *, send_delete: bool) -> None:
        self._connected = False
        client, self._client = self._client, None
        session_id, self._session_id = self._session_id, None
        if client is None:
            return
        try:
            if send_delete and session_id:
                headers = {**self._headers, "Mcp-Session-Id": session_id}
                if self._protocol_version:
                    headers["MCP-Protocol-Version"] = self._protocol_version
                try:
                    response = await asyncio.wait_for(
                        client.delete(self.url, headers=headers),
                        timeout=min(self.DELETE_TIMEOUT, self.timeout),
                    )
                    if response.status_code not in (200, 202, 204, 404, 405):
                        logger.debug(
                            f"{self._log_prefix()} Session DELETE returned "
                            f"HTTP {response.status_code}"
                        )
                except Exception as e:  # noqa: BLE001 — best effort
                    logger.debug(
                        f"{self._log_prefix()} Session DELETE failed: {type(e).__name__}"
                    )
        finally:
            await client.aclose()

    # ─────────────────────── Requests ───────────────────────────────────────

    async def send_request(
        self, method: str, params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Send a JSON-RPC request; returns the response, or an error dict."""
        if not self.is_connected:
            return {"error": {"code": -1, "message": "Not connected"}}
        try:
            return await asyncio.wait_for(
                self._exchange_renewing(method, params), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            message = f"'{method}' timed out after {self.timeout:g}s"
        except _HTTPTransportError as e:
            message = str(e)
        except Exception as e:  # noqa: BLE001 — reported to the caller
            message = f"'{method}' failed: {type(e).__name__}"
        logger.warning(f"{self._log_prefix()} {message}")
        return {"error": {"code": -1, "message": message}}

    async def _exchange_renewing(
        self, method: str, params: Optional[Dict]
    ) -> Dict[str, Any]:
        """``_exchange``, and if the server says the session ended (404 with
        a session id) start a new session and retry once, as the spec
        requires. The server rejected the original request without running
        it, so the retry cannot run it twice."""
        expired = self._session_id
        try:
            return await self._exchange(method, params)
        except _SessionExpired:
            pass
        try:
            await self._renew_session(expired)
        except _HTTPTransportError as e:
            self._connected = False
            raise _HTTPTransportError(
                f"the server ended the MCP session and a new one could not be started: {e}"
            ) from None
        return await self._exchange(method, params)

    async def _renew_session(self, expired: Optional[str]) -> None:
        """Run a fresh initialize, once for all requests that saw ``expired``
        end (concurrent requests share one renewal)."""
        async with self._renew_lock:
            if self._session_id != expired:
                return  # another request already renewed it
            logger.info(f"{self._log_prefix()} Session ended; starting a new one")
            # The old id stays in place until the new initialize replaces it:
            # requests running meanwhile keep a session header, get their own
            # 404, and then wait here for this renewal.
            await self._initialize()

    async def _exchange(
        self, method: str, params: Optional[Dict], *, initializing: bool = False
    ) -> Dict[str, Any]:
        self._request_id += 1
        request: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params
        response = await self._post(request, initializing=initializing)
        if response is None:
            raise _HTTPTransportError(f"server answered '{method}' with no response")
        return response

    def _request_headers(
        self, *, accept: str, with_session: bool = True
    ) -> Dict[str, str]:
        headers = dict(self._headers)
        headers["Accept"] = accept
        # initialize never carries a session or version: it starts a session.
        if with_session and self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if with_session and self._protocol_version:
            headers["MCP-Protocol-Version"] = self._protocol_version
        return headers

    async def _post(
        self, message: Dict[str, Any], *, initializing: bool = False
    ) -> Optional[Dict[str, Any]]:
        """POST one message. For a request, returns its response; for a
        notification or response, returns None once the server accepted it."""
        import httpx

        if self._client is None:
            raise _HTTPTransportError("not connected")
        is_request = "method" in message and "id" in message
        # The session this very request carries: a 404 means *that* session
        # ended, whatever another request has done to the shared state since.
        sent_session = None if initializing else self._session_id
        headers = self._request_headers(
            accept="application/json, text/event-stream",
            with_session=not initializing,
        )
        headers["Content-Type"] = "application/json"
        body = json.dumps(message).encode("utf-8")
        try:
            async with self._client.stream(
                "POST", self.url, content=body, headers=headers
            ) as response:
                if initializing:
                    self._capture_session_id(response)
                return await self._handle_post_response(
                    response, message, is_request, sent_session
                )
        except _HTTPTransportError:
            raise
        except httpx.TimeoutException:
            raise _HTTPTransportError(
                f"timed out after {self.timeout:g}s waiting for {redact_url(self.url)}"
            ) from None
        except httpx.ConnectError:
            raise _HTTPTransportError(
                f"could not connect to {redact_url(self.url)}"
            ) from None
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError):
            raise _HTTPTransportError(
                f"connection to {redact_url(self.url)} was interrupted"
            ) from None
        except httpx.HTTPError as e:
            raise _HTTPTransportError(
                f"HTTP error talking to {redact_url(self.url)}: {type(e).__name__}"
            ) from None

    def _capture_session_id(self, response) -> None:
        session_id = response.headers.get("mcp-session-id")
        if session_id is None:
            return
        if not session_id or any(not 0x21 <= ord(c) <= 0x7E for c in session_id):
            raise _HTTPTransportError(
                "server sent an invalid Mcp-Session-Id (visible ASCII only)"
            )
        self._session_id = session_id

    async def _handle_post_response(
        self,
        response,
        message: Dict[str, Any],
        is_request: bool,
        sent_session: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        status = response.status_code
        method = message.get("method", "response")
        if 300 <= status < 400:
            location = response.headers.get("location", "")
            raise _HTTPTransportError(
                f"server redirected to {redact_url(location) or 'another URL'} "
                f"(HTTP {status}); redirects are not followed so headers are not "
                "sent elsewhere; configure the final URL if you trust it"
            )
        if status >= 400:
            await self._raise_for_status(response, message, is_request, sent_session)
        if not is_request:
            return None  # 202 (or any 2xx) for a notification/response
        if status == 202:
            raise _HTTPTransportError(
                f"server accepted '{method}' but sent no response"
            )
        content_type = response.headers.get("content-type", "").lower()
        if content_type.startswith("application/json"):
            return self._match_response(await self._read_json(response), message)
        if content_type.startswith("text/event-stream"):
            return await self._read_event_stream(response, message)
        raise _HTTPTransportError(
            f"unexpected Content-Type {_clean_server_text(content_type, 60)!r} "
            f"for '{method}'"
        )

    async def _raise_for_status(
        self,
        response,
        message: Dict[str, Any],
        is_request: bool,
        sent_session: Optional[str] = None,
    ) -> None:
        status = response.status_code
        method = message.get("method", "response")
        detail = ""
        body = await self._read_limited(response, self.MAX_ERROR_BODY_BYTES)
        if body and "json" in response.headers.get("content-type", "").lower():
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            # A JSON-RPC error carried by an HTTP error status.
            if (
                is_request
                and isinstance(parsed, dict)
                and isinstance(parsed.get("error"), dict)
            ):
                detail = self._error_text(parsed["error"])
        if status in (401, 403):
            raise _HTTPTransportError(
                f"'{method}' was refused with HTTP {status} (authentication "
                "failed or not permitted); check this server's headers"
                + (f": {detail}" if detail else "")
            )
        if status == 404 and sent_session:
            # The session ended on the server; send_request starts a new one.
            raise _SessionExpired("the server ended the MCP session (HTTP 404)")
        raise _HTTPTransportError(
            f"'{method}' failed with HTTP {status}" + (f": {detail}" if detail else "")
        )

    async def _read_limited(self, response, limit: int) -> Optional[bytes]:
        """The body, or None if it is longer than ``limit`` (reading stops
        there, so an oversized body is never held in memory)."""
        chunks: List[bytes] = []
        size = 0
        body = response.aiter_bytes()
        async for chunk in body:
            size += len(chunk)
            if size > limit:
                await self._drain(body)
                return None
            chunks.append(chunk)
        return b"".join(chunks)

    async def _drain(self, iterator) -> None:
        """Read an httpx stream iterator to its end, discarding the data,
        for at most DRAIN_TIMEOUT seconds.

        Stopping half way leaves httpx's chain of async generators (lines →
        text → bytes → httpcore's connection stream) suspended; the garbage
        collector then finalises httpcore's generator in another task, which
        it rejects ("exit cancel scope in a different task"). Reading to the
        end — or being cancelled at a socket read by the timeout — unwinds the
        whole chain here instead. Servers close a response stream after the
        response, so this normally returns at once."""

        async def exhaust() -> None:
            async for _ in iterator:
                pass

        try:
            await asyncio.wait_for(exhaust(), timeout=self.DRAIN_TIMEOUT)
        except asyncio.TimeoutError:
            logger.debug(
                f"{self._log_prefix()} Server kept a response stream open; closing it"
            )
        except Exception:  # noqa: BLE001 — the stream is being discarded
            pass

    async def _read_json(self, response) -> Any:
        body = await self._read_limited(response, self.MAX_MESSAGE_BYTES)
        if body is None:
            raise _HTTPTransportError("response exceeds the 16 MB message limit")
        try:
            return json.loads(body)
        except ValueError:
            raise _HTTPTransportError("server sent malformed JSON") from None

    def _match_response(self, payload: Any, request: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict) or (
            "result" not in payload and "error" not in payload
        ):
            raise _HTTPTransportError(
                f"server sent a non-response body for '{request['method']}'"
            )
        if payload.get("id") != request["id"]:
            if "error" in payload and payload.get("id") is None:
                return {**payload, "id": request["id"]}
            raise _HTTPTransportError(
                f"server answered '{request['method']}' with the wrong id"
            )
        return payload

    @staticmethod
    def _error_text(error: Any) -> str:
        if isinstance(error, dict):
            message = error.get("message", "")
            code = error.get("code")
            text = _clean_server_text(message) or "error"
            return f"{text} (code {code})" if code is not None else text
        return _clean_server_text(error)

    # ─────────────────────── SSE response streams ───────────────────────────

    async def _read_event_stream(
        self, response, request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Read SSE events until this request's response. A stream that ends
        early after carrying an event id is resumed with GET + Last-Event-ID
        (2025-11-25 servers may close it on purpose), up to
        MAX_RESUME_ATTEMPTS times."""
        outcome = await self._consume_events(response, request)
        attempts = 0
        while outcome.response is None:
            if outcome.last_event_id is None or attempts >= self.MAX_RESUME_ATTEMPTS:
                raise _HTTPTransportError(
                    f"the response stream for '{request['method']}' ended "
                    "before the response arrived"
                )
            attempts += 1
            retry_ms = outcome.retry_ms or self.DEFAULT_RETRY_MS
            await asyncio.sleep(min(retry_ms, self.MAX_RETRY_MS) / 1000)
            stream = await self._resume(outcome.last_event_id)
            try:
                content_type = stream.headers.get("content-type", "").lower()
                if stream.status_code >= 400 or not content_type.startswith(
                    "text/event-stream"
                ):
                    raise _HTTPTransportError(
                        f"could not resume the stream for '{request['method']}' "
                        f"(HTTP {stream.status_code})"
                    )
                resumed = await self._consume_events(stream, request)
            finally:
                await stream.aclose()
            resumed.last_event_id = resumed.last_event_id or outcome.last_event_id
            if resumed.retry_ms is None:
                resumed.retry_ms = outcome.retry_ms
            outcome = resumed
        return outcome.response

    async def _resume(self, last_event_id: str):
        headers = self._request_headers(accept="text/event-stream")
        headers["Last-Event-ID"] = last_event_id
        request = self._client.build_request("GET", self.url, headers=headers)
        return await self._client.send(request, stream=True)

    async def _consume_events(
        self, stream, request: Dict[str, Any]
    ) -> "_StreamOutcome":
        outcome = _StreamOutcome()
        lines = stream.aiter_lines()
        messages = self._sse_messages(lines, outcome)
        cancelled = False
        try:
            async for message in messages:
                if "method" in message:
                    if "id" in message:
                        await self._answer_server_request(message)
                    continue  # notification
                if message.get("id") == request["id"] and (
                    "result" in message or "error" in message
                ):
                    outcome.response = message
                    break
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            await messages.aclose()  # our parser: no I/O, closes at its yield
            # Whatever ended the loop (the response, an oversized event),
            # read on to the end of this same stream instead of abandoning
            # httpx's generators mid-iteration (see _drain). A finished
            # stream makes this a no-op; a cancellation already unwound it.
            if not cancelled:
                await self._drain(lines)
        return outcome

    async def _sse_messages(self, lines, outcome: "_StreamOutcome"):
        """JSON-RPC objects from an SSE line stream; records event ids and
        retry hints on ``outcome`` for resumption."""
        event = "message"
        data: List[str] = []
        size = 0
        async for line in lines:
            if line:
                if line.startswith(":"):
                    continue
                field_name, _, value = line.partition(":")
                value = value[1:] if value.startswith(" ") else value
                if field_name == "event":
                    event = value or "message"
                elif field_name == "data":
                    size += len(value)
                    if size > self.MAX_MESSAGE_BYTES:
                        raise _HTTPTransportError(
                            "stream event exceeds the 16 MB message limit"
                        )
                    data.append(value)
                elif field_name == "id":
                    if "\x00" not in value:
                        outcome.last_event_id = value
                elif field_name == "retry" and value.isdigit():
                    outcome.retry_ms = int(value)
                continue
            payload, kind, data, size, event = "\n".join(data), event, [], 0, "message"
            if kind != "message" or not payload.strip():
                continue
            try:
                message = json.loads(payload)
            except ValueError:
                logger.debug(f"{self._log_prefix()} Ignoring malformed stream event")
                continue
            if isinstance(message, dict):
                yield message

    async def _answer_server_request(self, message: Dict[str, Any]) -> None:
        if message.get("method") == "ping":
            reply: Dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {},
            }
        else:
            reply = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": -32601, "message": "Method not found"},
            }
        try:
            await self._post(reply)
        except _HTTPTransportError as e:
            logger.debug(f"{self._log_prefix()} Could not answer server request: {e}")


@dataclass
class _StreamOutcome:
    response: Optional[Dict[str, Any]] = None
    last_event_id: Optional[str] = None
    retry_ms: Optional[int] = None


class MCPServerConnection:
    """
    Manages connection to a single MCP server.

    Handles transport selection, connection lifecycle, tool discovery, and tool execution.
    """

    # tools/list pages followed via nextCursor before giving up.
    MAX_TOOL_PAGES = 50

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._transport: Optional[MCPTransport] = None
        self._tools: List[MCPTool] = []
        # Why the last connect() failed; safe to show (no credentials).
        self.last_error: Optional[str] = None

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
                cwd=self.config.cwd,
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
        elif self.config.transport == "http":
            # Resolved per connect from this server's env; raises
            # MCPConfigError naming any missing variable.
            return StreamableHTTPTransport(
                url=self.config.url or "",
                headers=self.config.resolve_headers(),
                timeout=self.config.effective_timeout,
                server_name=self.config.name,
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

        self.last_error = None
        try:
            # Create and connect transport
            logger.debug(
                f"[MCPServer:{self.config.name}] Creating {self.config.transport} transport..."
            )
            try:
                self._transport = self._create_transport()
            except MCPConfigError as e:
                self.last_error = str(e)
                logger.error(f"[MCPServer:{self.config.name}] {self.last_error}")
                return False

            logger.debug(f"[MCPServer:{self.config.name}] Connecting transport...")
            if not await self._transport.connect():
                self.last_error = self._transport.last_error or "connection failed"
                logger.error(
                    f"[MCPServer:{self.config.name}] Transport connection failed"
                )
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

        except asyncio.CancelledError:
            # Never leave a half-open transport (or a spawned process) behind.
            await self.disconnect()
            raise
        except Exception as e:
            logger.error(
                f"[MCPServer:{self.config.name}] Failed to connect: {type(e).__name__}: {e}"
            )
            self.last_error = f"connect failed: {type(e).__name__}"
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
            logger.warning(
                f"[MCPServer:{self.config.name}] Cannot discover tools - not connected"
            )
            return

        tools_data: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(self.MAX_TOOL_PAGES):
            params: Dict[str, Any] = {"cursor": cursor} if cursor else {}
            response = await self._transport.send_request("tools/list", params)

            if "error" in response:
                error_info = response.get("error", {})
                if isinstance(error_info, dict):
                    error_msg = error_info.get("message", str(error_info))
                else:
                    error_msg = str(error_info)
                logger.warning(
                    f"[MCPServer:{self.config.name}] Failed to list tools: {error_msg}"
                )
                if not tools_data:
                    return
                break

            result = response.get("result", {}) or {}
            page = result.get("tools", [])
            if isinstance(page, list):
                tools_data.extend(t for t in page if isinstance(t, dict))
            next_cursor = result.get("nextCursor")
            if (
                not isinstance(next_cursor, str)
                or not next_cursor
                or next_cursor == cursor
            ):
                break
            cursor = next_cursor
        else:
            logger.warning(
                f"[MCPServer:{self.config.name}] Stopped listing tools after "
                f"{self.MAX_TOOL_PAGES} pages"
            )

        if not tools_data:
            logger.debug(
                f"[MCPServer:{self.config.name}] Server returned empty tools list."
            )

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

    async def call_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
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
            response = await self._transport.send_request(
                "tools/call",
                {
                    "name": tool_name,
                    "arguments": arguments,
                },
            )

            if "error" in response:
                return {
                    "status": "error",
                    "message": response["error"].get("message", "Unknown error"),
                    "code": response["error"].get("code"),
                }

            result = response.get("result", {})
            status = "error" if result.get("isError") is True else "success"
            # Presence matters: null, false, zero and empty structured values
            # are still evidence. Keep the existing result/raw_content shape.
            metadata = {
                key: result[key]
                for key in ("isError", "structuredContent", "_meta")
                if key in result
            }

            # Extract content from MCP result format
            content = result.get("content", [])
            if content:
                # Combine all text content
                text_parts = []
                for item in content:
                    if item.get("type") == "text":
                        text_parts.append(item.get("text", ""))

                return {
                    "status": status,
                    "result": "\n".join(text_parts) if text_parts else result,
                    "raw_content": content,
                    **metadata,
                }

            return {
                "status": status,
                "result": result,
                **metadata,
            }

        except Exception as e:
            logger.error(f"Error calling tool '{tool_name}': {e}")
            return {
                "status": "error",
                "message": str(e),
            }
