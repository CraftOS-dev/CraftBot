# -*- coding: utf-8 -*-
"""
MCP Client Module

Singleton manager for all MCP server connections. Handles initialization,
connection management, tool discovery, and action registration.

Servers are independent: each has its own connection, headers and error, and
a reload only touches the servers whose configuration changed.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from agent_core.utils.logger import logger
from agent_core.core.impl.mcp.config import MCPConfig, MCPServerConfig
from agent_core.core.impl.mcp.server import MCPServerConnection, MCPTool

# How long a tool handler waits for a call when the server sets no longer
# timeout; http servers get their own timeout plus HANDLER_MARGIN.
DEFAULT_HANDLER_TIMEOUT = 60.0
HANDLER_MARGIN = 10.0


def _default_config_path() -> Path:
    """The user-editable MCP config.

    app.config.APP_CONFIG_PATH is the one authority on where editable config
    lives. Deriving it from __file__ here was wrong for a managed install:
    that points into the INSTALL directory, while the copy the user edits is
    bootstrapped into the per-user state directory. Edits to
    mcp_config.json would have had no effect, silently.

    (The old code had a frozen branch that read CWD, which happened to be
    right because run.py chdir'd there — but the agent is no longer frozen,
    so that branch stopped running and took the correct behaviour with it.)
    """
    from app.config import APP_CONFIG_PATH

    return Path(APP_CONFIG_PATH) / "mcp_config.json"


DEFAULT_CONFIG_PATH = _default_config_path()


class MCPClient:
    """
    Singleton managing all MCP server connections.

    Provides a unified interface for:
    - Loading MCP configuration
    - Connecting/disconnecting servers
    - Tool discovery
    - Tool execution
    - Action registration
    """

    _instance: Optional["MCPClient"] = None

    def __new__(cls) -> "MCPClient":
        if cls._instance is None:
            cls._instance = super(MCPClient, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._servers: Dict[str, MCPServerConnection] = {}
        self._config: Optional[MCPConfig] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        # Why each enabled server that is not connected failed (safe text).
        self._last_errors: Dict[str, str] = {}
        # Exact action names registered for each server.
        self._registered_actions: Dict[str, Set[str]] = {}
        # Serialises initialize/reload so two config writes cannot interleave.
        self._lifecycle_lock: Optional[asyncio.Lock] = None
        self._initialized = True

    @property
    def servers(self) -> Dict[str, MCPServerConnection]:
        """Get all server connections."""
        return self._servers

    @property
    def config(self) -> Optional[MCPConfig]:
        """Get the current configuration."""
        return self._config

    @property
    def event_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Get the event loop used by this client for MCP connections."""
        return self._event_loop

    @property
    def last_errors(self) -> Dict[str, str]:
        """Why each enabled server that is not connected failed."""
        return dict(self._last_errors)

    def _lock(self) -> asyncio.Lock:
        if self._lifecycle_lock is None:
            self._lifecycle_lock = asyncio.Lock()
        return self._lifecycle_lock

    def handler_timeout(self, server_name: str) -> float:
        """Seconds a tool handler waits for a call on this server: long
        enough for the server's own request timeout to fire first."""
        connection = self._servers.get(server_name)
        config = connection.config if connection else None
        if config is None and self._config is not None:
            config = self._config.get_server_by_name(server_name)
        if config is not None and config.transport == "http":
            return max(
                DEFAULT_HANDLER_TIMEOUT, config.effective_timeout + HANDLER_MARGIN
            )
        return DEFAULT_HANDLER_TIMEOUT

    async def initialize(self, config_path: Optional[Path] = None) -> None:
        """
        Initialize the MCP client with configuration.

        Args:
            config_path: Path to the configuration file. If None, uses default path.
        """
        config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

        # Store the event loop for later use by handlers running in other threads
        self._event_loop = asyncio.get_running_loop()

        # Load configuration
        try:
            self._config = MCPConfig.load(config_path)
            server_names = [s.name for s in self._config.mcp_servers]
            enabled_names = [s.name for s in self._config.get_enabled_servers()]
            logger.info(
                f"[MCP] Loaded config with {len(self._config.mcp_servers)} server(s): {server_names}"
            )
            logger.info(f"[MCP] Enabled servers: {enabled_names}")
        except Exception as e:
            logger.error(f"[MCP] Failed to load MCP config from {config_path}: {e}")
            import traceback

            logger.debug(f"[MCP] Traceback: {traceback.format_exc()}")
            self._config = MCPConfig()
            return

        # Auto-connect to enabled servers if configured
        if self._config.auto_connect:
            async with self._lock():
                await self._connect_enabled_servers()

    async def _connect_enabled_servers(self) -> None:
        """Connect to all enabled servers in parallel for faster startup."""
        if not self._config:
            logger.warning("MCP config is None, cannot connect to servers")
            return

        enabled_servers = self._config.get_enabled_servers()
        if not enabled_servers:
            logger.info("No enabled MCP servers to connect")
            return

        logger.info(
            f"Connecting to {len(enabled_servers)} MCP server(s) in parallel..."
        )
        await self._connect_many([s.name for s in enabled_servers])

    async def _connect_many(self, names: Iterable[str]) -> Dict[str, bool]:
        """Connect several servers concurrently; one failing (or raising)
        never stops the others."""

        async def connect_with_logging(name: str) -> bool:
            server = self._config.get_server_by_name(name) if self._config else None
            if server is not None:
                logger.info(
                    f"[MCP] Connecting to '{name}' ({server.transport}): {_describe(server)}"
                )
            try:
                result = await self.connect_server(name)
            except Exception as e:  # connect_server reports its own failures
                self._last_errors[name] = f"connect failed: {type(e).__name__}"
                logger.error(
                    f"[MCP] Exception connecting to '{name}': {type(e).__name__}: {e}"
                )
                return False
            if result:
                tools = self._servers[name].tools
                logger.info(
                    f"[MCP] Successfully connected to '{name}' with {len(tools)} tools"
                )
            else:
                logger.warning(
                    f"[MCP] Failed to connect to '{name}' - check server configuration"
                )
            return result

        names = list(names)
        results = await asyncio.gather(*[connect_with_logging(n) for n in names])
        return dict(zip(names, results))

    async def connect_server(self, server_name: str) -> bool:
        """
        Connect to a specific MCP server by name.

        Args:
            server_name: Name of the server (as defined in config)

        Returns:
            True if connection succeeded
        """
        if not self._config:
            logger.error("MCP client not initialized")
            return False

        # Check if already connected
        if server_name in self._servers:
            if self._servers[server_name].is_connected:
                logger.info(f"Server '{server_name}' is already connected")
                return True
            else:
                # Remove stale connection
                await self.disconnect_server(server_name)

        # Get server config
        server_config = self._config.get_server_by_name(server_name)
        if not server_config:
            logger.error(f"Server '{server_name}' not found in config")
            return False

        # Create and connect
        connection = MCPServerConnection(server_config)
        if await connection.connect():
            self._servers[server_name] = connection
            self._last_errors.pop(server_name, None)
            return True
        self._last_errors[server_name] = connection.last_error or "connection failed"
        return False

    async def disconnect_server(self, server_name: str) -> None:
        """
        Disconnect from a specific MCP server and remove its actions.

        Args:
            server_name: Name of the server to disconnect
        """
        connection = self._servers.pop(server_name, None)
        self._unregister_server_actions(server_name)
        if connection is not None:
            await connection.disconnect()
            logger.info(f"Disconnected from server '{server_name}'")

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers (concurrently, so one slow
        server does not delay the others at shutdown)."""
        names = list(self._servers.keys())
        results = await asyncio.gather(
            *[self.disconnect_server(name) for name in names],
            return_exceptions=True,
        )
        for name, result in zip(names, results):
            if isinstance(result, BaseException):
                logger.warning(
                    f"[MCP] Error disconnecting '{name}': {type(result).__name__}"
                )
        logger.info("Disconnected from all MCP servers")

    def get_all_tools(self) -> Dict[str, List[MCPTool]]:
        """
        Get all tools from all connected servers.

        Returns:
            Dictionary mapping server names to their tool lists
        """
        return {
            name: server.tools
            for name, server in self._servers.items()
            if server.is_connected
        }

    def get_server_tools(self, server_name: str) -> List[MCPTool]:
        """
        Get tools from a specific server.

        Args:
            server_name: Name of the server

        Returns:
            List of tools from the server, empty if not connected
        """
        if server_name not in self._servers:
            return []
        return self._servers[server_name].tools

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call a tool on a specific MCP server.

        Args:
            server_name: Name of the server
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        if server_name not in self._servers:
            return {
                "status": "error",
                "message": f"MCP server '{server_name}' is not connected",
            }

        server = self._servers[server_name]
        if not server.is_connected:
            return {
                "status": "error",
                "message": f"MCP server '{server_name}' connection lost",
            }

        result = await server.call_tool(tool_name, arguments)

        # Record MCP tool call for metrics (only if not an error)
        if result.get("status") != "error":
            try:
                from app.ui_layer.metrics.collector import MetricsCollector

                collector = MetricsCollector.get_instance()
                if collector:
                    collector.record_mcp_tool_call(tool_name, server_name)
            except Exception:
                pass  # Don't fail tool execution if metrics recording fails

        return result

    async def refresh_tools(self, server_name: Optional[str] = None) -> None:
        """
        Refresh tool list from server(s).

        Args:
            server_name: Specific server to refresh, or None for all servers
        """
        if server_name:
            if server_name in self._servers:
                await self._servers[server_name].list_tools()
        else:
            for server in self._servers.values():
                if server.is_connected:
                    await server.list_tools()

    def _unregister_server_actions(self, server_name: str) -> int:
        from agent_core.core.impl.mcp.adapter import MCPActionAdapter

        names = self._registered_actions.pop(server_name, set())
        return MCPActionAdapter.unregister_actions(names)

    def register_tools_as_actions(self) -> int:
        """
        Register all MCP tools as actions in the ActionRegistry.

        Actions of servers that are gone, and tools a server no longer
        offers, are unregistered by exact name (never by prefix: server
        "foo" must not remove "foo_bar"'s actions).

        Returns:
            Number of tools registered
        """
        from agent_core.core.impl.mcp.adapter import MCPActionAdapter

        total_registered = 0

        for server_name in list(self._registered_actions):
            server = self._servers.get(server_name)
            if server is None or not server.is_connected:
                self._unregister_server_actions(server_name)

        if not self._servers:
            logger.warning("[MCP] No servers connected, cannot register tools")
            return 0

        for server_name, server in self._servers.items():
            if not server.is_connected:
                logger.warning(
                    f"[MCP] Server '{server_name}' is not connected, skipping tool registration"
                )
                continue

            previous = self._registered_actions.get(server_name, set())
            if not server.tools:
                logger.warning(f"[MCP] Server '{server_name}' has no tools to register")
                MCPActionAdapter.unregister_actions(previous)
                self._registered_actions.pop(server_name, None)
                continue

            action_set_name = server.config.resolved_action_set_name

            count = MCPActionAdapter.register_mcp_tools(
                server_name=server_name,
                tools=server.tools,
                action_set_name=action_set_name,
                server_description=server.config.description,
            )
            current = {
                MCPActionAdapter.action_name(server_name, tool.name)
                for tool in server.tools
            }
            MCPActionAdapter.unregister_actions(previous - current)
            self._registered_actions[server_name] = current
            total_registered += count

            logger.info(
                f"[MCP] Registered {count} tools from server '{server_name}' "
                f"into action set '{action_set_name}'"
            )

        return total_registered

    def get_status(self) -> Dict[str, Any]:
        """
        Get current status of all MCP connections.

        Servers that are enabled but failed to connect are included with
        ``connected: False`` and a safe ``error``.

        Returns:
            Status information for each server
        """
        status: Dict[str, Any] = {
            "initialized": self._config is not None,
            "servers": {},
        }

        for name, server in self._servers.items():
            status["servers"][name] = {
                "connected": server.is_connected,
                "transport": server.config.transport,
                "tool_count": len(server.tools),
                "tools": [t.name for t in server.tools],
                "action_set": server.config.resolved_action_set_name,
                "error": None if server.is_connected else self._last_errors.get(name),
            }

        for name, error in self._last_errors.items():
            if name in status["servers"]:
                continue
            config = self._config.get_server_by_name(name) if self._config else None
            status["servers"][name] = {
                "connected": False,
                "transport": config.transport if config else None,
                "tool_count": 0,
                "tools": [],
                "action_set": config.resolved_action_set_name if config else None,
                "error": error,
            }

        return status

    async def reload(self, config_path: Optional[Path] = None) -> Dict[str, Any]:
        """
        Hot-reload MCP configuration and reconnect servers.

        This method:
        1. Reloads the config file from disk
        2. Disconnects servers that were removed or disabled
        3. Reconnects only servers whose connection settings changed
        4. Keeps a running server on its last good settings when its entry
           became invalid, and reports the error
        5. Connects servers that are new, or that failed before
        6. Re-registers all tools as actions

        Servers whose settings did not change are left connected.

        Args:
            config_path: Path to the configuration file. If None, uses the
                        path from initialization or default path.

        Returns:
            Dictionary with reload results including connected/disconnected servers
        """
        result: Dict[str, Any] = {
            "success": True,
            "disconnected": [],
            "reconnected": [],
            "connected": [],
            "failed": [],
            "kept": [],
            "invalid": [],
            "total_tools": 0,
            "message": "",
        }

        # Use provided path, stored path, or default
        config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

        async with self._lock():
            # Reload configuration
            try:
                new_config = MCPConfig.load(config_path)
                logger.info(
                    f"[MCP] Reloaded config with {len(new_config.mcp_servers)} server(s)"
                )
            except Exception as e:
                logger.error(f"[MCP] Failed to reload config: {e}")
                result["success"] = False
                result["message"] = f"Failed to reload config: {e}"
                return result

            enabled: Dict[str, MCPServerConfig] = {
                s.name: s for s in new_config.get_enabled_servers()
            }
            invalid = {e.name: e.error for e in new_config.invalid_servers if e.name}
            result["invalid"] = [
                {"name": name, "error": error} for name, error in invalid.items()
            ]

            to_disconnect: List[str] = []
            to_reconnect: List[str] = []
            for name, connection in self._servers.items():
                new = enabled.get(name)
                if new is not None:
                    if (
                        new.connection_fingerprint()
                        != connection.config.connection_fingerprint()
                        # A connection that died (e.g. its session could not
                        # be renewed) is retried even if nothing changed.
                        or not connection.is_connected
                    ):
                        to_reconnect.append(name)
                    else:
                        # Same connection; pick up description/action set.
                        connection.config = new
                elif name in invalid and new_config.get_server_by_name(name) is None:
                    # The edit broke the entry: keep serving the last good one.
                    result["kept"].append(name)
                    logger.warning(
                        f"[MCP] Keeping '{name}' connected on its previous settings: "
                        f"{invalid[name]}"
                    )
                else:
                    to_disconnect.append(name)

            # Update config before connecting new servers
            self._config = new_config
            # Errors are kept only for servers that are still enabled.
            self._last_errors = {
                n: e for n, e in self._last_errors.items() if n in enabled
            }

            for name in to_disconnect + to_reconnect:
                try:
                    await self.disconnect_server(name)
                    if name in to_disconnect:
                        result["disconnected"].append(name)
                        logger.info(
                            f"[MCP] Disconnected server '{name}' (no longer enabled)"
                        )
                except Exception as e:
                    logger.warning(
                        f"[MCP] Error disconnecting '{name}': {type(e).__name__}"
                    )

            to_connect = to_reconnect + [
                name
                for name in enabled
                if name not in self._servers and name not in to_reconnect
            ]
            outcomes = await self._connect_many(to_connect)
            for name, ok in outcomes.items():
                if not ok:
                    result["failed"].append(name)
                elif name in to_reconnect:
                    result["reconnected"].append(name)
                else:
                    result["connected"].append(name)
                    logger.info(f"[MCP] Connected new server '{name}'")

            # Re-register all tools as actions
            result["total_tools"] = self.register_tools_as_actions()

        result["message"] = (
            f"Reload complete. Connected: {len(result['connected'])}, "
            f"Reconnected: {len(result['reconnected'])}, "
            f"Disconnected: {len(result['disconnected'])}, "
            f"Failed: {len(result['failed'])}, "
            f"Kept on previous settings: {len(result['kept'])}, "
            f"Total tools: {result['total_tools']}"
        )

        logger.info(f"[MCP] {result['message']}")
        return result


def _describe(server: MCPServerConfig) -> str:
    """How a server is reached, for logs. Never includes env or header
    values; URLs lose their user info and query."""
    from agent_core.core.impl.mcp.config import redact_url

    if server.transport == "stdio":
        return f"{server.command} {server.args}"
    headers = f", headers: {sorted(server.headers)}" if server.headers else ""
    return f"{redact_url(server.url)}{headers}"


# Global singleton instance
mcp_client = MCPClient()
