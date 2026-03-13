# -*- coding: utf-8 -*-
"""
MCP Client Module

Singleton manager for all MCP server connections. Handles initialization,
connection management, tool discovery, and action registration.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core.utils.logger import logger
from agent_core.core.impl.mcp.config import MCPConfig, MCPServerConfig
from agent_core.core.impl.mcp.server import MCPServerConnection, MCPTool

# Default config path
DEFAULT_CONFIG_PATH = Path("app/config/mcp_config.json")


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

        logger.info(f"Connecting to {len(enabled_servers)} MCP server(s) in parallel...")

        async def connect_with_logging(server):
            """Connect to a single server with logging."""
            try:
                logger.info(f"[MCP] Connecting to '{server.name}' ({server.transport}): {server.command} {server.args}")
                result = await self.connect_server(server.name)
                if result:
                    tools = self._servers[server.name].tools
                    logger.info(f"[MCP] Successfully connected to '{server.name}' with {len(tools)} tools")
                else:
                    logger.warning(f"[MCP] Failed to connect to '{server.name}' - check server configuration")
                return result
            except Exception as e:
                import traceback
                logger.error(f"[MCP] Exception connecting to '{server.name}': {type(e).__name__}: {e}")
                logger.debug(f"[MCP] Traceback: {traceback.format_exc()}")
                return False

        # Connect to all servers in parallel
        await asyncio.gather(*[connect_with_logging(s) for s in enabled_servers])

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
                del self._servers[server_name]

        # Get server config
        server_config = self._config.get_server_by_name(server_name)
        if not server_config:
            logger.error(f"Server '{server_name}' not found in config")
            return False

        # Create and connect
        connection = MCPServerConnection(server_config)
        if await connection.connect():
            self._servers[server_name] = connection
            return True
        else:
            return False

    async def disconnect_server(self, server_name: str) -> None:
        """
        Disconnect from a specific MCP server.

        Args:
            server_name: Name of the server to disconnect
        """
        if server_name in self._servers:
            await self._servers[server_name].disconnect()
            del self._servers[server_name]
            logger.info(f"Disconnected from server '{server_name}'")

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        for server_name in list(self._servers.keys()):
            await self.disconnect_server(server_name)
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

        return await server.call_tool(tool_name, arguments)

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

    def register_tools_as_actions(self) -> int:
        """
        Register all MCP tools as actions in the ActionRegistry.

        Returns:
            Number of tools registered
        """
        from agent_core.core.impl.mcp.adapter import MCPActionAdapter

        total_registered = 0

        if not self._servers:
            logger.warning("[MCP] No servers connected, cannot register tools")
            return 0

        for server_name, server in self._servers.items():
            if not server.is_connected:
                logger.warning(f"[MCP] Server '{server_name}' is not connected, skipping tool registration")
                continue

            if not server.tools:
                logger.warning(f"[MCP] Server '{server_name}' has no tools to register")
                continue

            action_set_name = server.config.resolved_action_set_name

            count = MCPActionAdapter.register_mcp_tools(
                server_name=server_name,
                tools=server.tools,
                action_set_name=action_set_name,
                server_description=server.config.description,
            )
            total_registered += count

            logger.info(
                f"[MCP] Registered {count} tools from server '{server_name}' "
                f"into action set '{action_set_name}'"
            )

        return total_registered

    def get_status(self) -> Dict[str, Any]:
        """
        Get current status of all MCP connections.

        Returns:
            Status information for each server
        """
        status = {
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
            }

        return status


# Global singleton instance
mcp_client = MCPClient()
