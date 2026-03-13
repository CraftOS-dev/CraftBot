# -*- coding: utf-8 -*-
"""
MCP (Model Context Protocol) implementation module.

This module provides MCP client/server connectivity for integrating
external tools into the agent action system.
"""

from agent_core.core.impl.mcp.config import (
    MCPServerConfig,
    MCPConfig,
)
from agent_core.core.impl.mcp.server import (
    MCPTool,
    MCPTransport,
    StdioTransport,
    SSETransport,
    WebSocketTransport,
    MCPServerConnection,
    set_client_info,
    get_client_info,
)
from agent_core.core.impl.mcp.client import (
    MCPClient,
    mcp_client,
    DEFAULT_CONFIG_PATH,
)
from agent_core.core.impl.mcp.adapter import MCPActionAdapter

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
    "set_client_info",
    "get_client_info",
    # Client
    "MCPClient",
    "mcp_client",
    "DEFAULT_CONFIG_PATH",
    # Adapter
    "MCPActionAdapter",
]
