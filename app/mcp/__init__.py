# -*- coding: utf-8 -*-
"""
MCP module - re-exports from agent_core.

All MCP implementations are now in agent_core.
"""

# Re-export from agent_core
from agent_core import (
    MCPServerConfig,
    MCPConfig,
    MCPTool,
    MCPServerConnection,
    MCPClient,
    mcp_client,
    MCPActionAdapter,
    set_mcp_client_info,
)
from agent_core.core.impl.mcp import (
    MCPTransport,
    StdioTransport,
    SSETransport,
    WebSocketTransport,
    get_client_info,
    DEFAULT_CONFIG_PATH,
)

__all__ = [
    # Config
    "MCPServerConfig",
    "MCPConfig",
    # Server / Transports
    "MCPTool",
    "MCPTransport",
    "StdioTransport",
    "SSETransport",
    "WebSocketTransport",
    "MCPServerConnection",
    "set_mcp_client_info",
    "get_client_info",
    # Client
    "MCPClient",
    "mcp_client",
    "DEFAULT_CONFIG_PATH",
    # Adapter
    "MCPActionAdapter",
]
