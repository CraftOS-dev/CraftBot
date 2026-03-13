# -*- coding: utf-8 -*-
"""
MCP Configuration Module

Handles loading and validation of MCP server configurations.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from agent_core.utils.logger import logger


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str                                    # Server identifier (e.g., "filesystem")
    description: str = ""                        # Human-readable description
    transport: str = "stdio"                     # "stdio" | "sse" | "websocket"
    command: Optional[str] = None                # For stdio: executable path
    args: List[str] = field(default_factory=list)  # For stdio: command arguments
    url: Optional[str] = None                    # For sse/websocket: server URL
    env: Dict[str, str] = field(default_factory=dict)  # Environment variables
    enabled: bool = True                         # Enable/disable toggle
    action_set_name: Optional[str] = None        # Custom set name (defaults to mcp_{name})

    def __post_init__(self):
        """Validate configuration after initialization."""
        # Validate transport type
        valid_transports = {"stdio", "sse", "websocket"}
        if self.transport not in valid_transports:
            raise ValueError(
                f"Invalid transport '{self.transport}' for server '{self.name}'. "
                f"Must be one of: {valid_transports}"
            )

        # Validate required fields based on transport
        if self.transport == "stdio":
            if not self.command:
                raise ValueError(
                    f"Server '{self.name}' uses stdio transport but 'command' is not specified"
                )
        elif self.transport in ("sse", "websocket"):
            if not self.url:
                raise ValueError(
                    f"Server '{self.name}' uses {self.transport} transport but 'url' is not specified"
                )

    @property
    def resolved_action_set_name(self) -> str:
        """Get the action set name, defaulting to mcp_{name} if not specified."""
        return self.action_set_name or f"mcp_{self.name}"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPServerConfig":
        """Create MCPServerConfig from a dictionary."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            transport=data.get("transport", "stdio"),
            command=data.get("command"),
            args=data.get("args", []),
            url=data.get("url"),
            env=data.get("env", {}),
            enabled=data.get("enabled", True),
            action_set_name=data.get("action_set_name"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "name": self.name,
            "description": self.description,
            "transport": self.transport,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "enabled": self.enabled,
        }
        # Only include optional fields if they have values
        if self.url:
            result["url"] = self.url
        if self.action_set_name:
            result["action_set_name"] = self.action_set_name
        return result


@dataclass
class MCPConfig:
    """Main MCP configuration containing all server configurations."""

    mcp_servers: List[MCPServerConfig] = field(default_factory=list)
    auto_connect: bool = True  # Automatically connect to enabled servers on init

    @classmethod
    def load(cls, config_path: Path) -> "MCPConfig":
        """
        Load MCP configuration from a JSON file.

        Args:
            config_path: Path to the configuration file

        Returns:
            MCPConfig instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            json.JSONDecodeError: If config file is invalid JSON
            ValueError: If config validation fails
        """
        config_path = Path(config_path)

        if not config_path.exists():
            logger.warning(f"MCP config file not found: {config_path}")
            return cls()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in MCP config file: {e}")
            raise

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPConfig":
        """Create MCPConfig from a dictionary."""
        servers = []
        for server_data in data.get("mcp_servers", []):
            try:
                server = MCPServerConfig.from_dict(server_data)
                servers.append(server)
            except (KeyError, ValueError) as e:
                logger.warning(f"Skipping invalid server config: {e}")
                continue

        return cls(
            mcp_servers=servers,
            auto_connect=data.get("auto_connect", True),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "mcp_servers": [s.to_dict() for s in self.mcp_servers],
            "auto_connect": self.auto_connect,
        }

    def save(self, config_path: Path) -> None:
        """Save configuration to a JSON file."""
        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def get_enabled_servers(self) -> List[MCPServerConfig]:
        """Get list of enabled server configurations."""
        return [s for s in self.mcp_servers if s.enabled]

    def get_server_by_name(self, name: str) -> Optional[MCPServerConfig]:
        """Get a server configuration by name."""
        for server in self.mcp_servers:
            if server.name == name:
                return server
        return None

    def add_server(self, server: MCPServerConfig) -> bool:
        """
        Add a new server configuration.

        Args:
            server: Server configuration to add

        Returns:
            True if added, False if server with same name already exists
        """
        if self.get_server_by_name(server.name):
            logger.warning(f"Server '{server.name}' already exists")
            return False
        self.mcp_servers.append(server)
        logger.info(f"Added MCP server: {server.name}")
        return True

    def remove_server(self, name: str) -> bool:
        """
        Remove a server configuration by name.

        Args:
            name: Name of the server to remove

        Returns:
            True if removed, False if not found
        """
        for i, server in enumerate(self.mcp_servers):
            if server.name == name:
                del self.mcp_servers[i]
                logger.info(f"Removed MCP server: {name}")
                return True
        logger.warning(f"Server '{name}' not found")
        return False

    def enable_server(self, name: str) -> bool:
        """Enable a server by name."""
        server = self.get_server_by_name(name)
        if server:
            server.enabled = True
            logger.info(f"Enabled MCP server: {name}")
            return True
        return False

    def disable_server(self, name: str) -> bool:
        """Disable a server by name."""
        server = self.get_server_by_name(name)
        if server:
            server.enabled = False
            logger.info(f"Disabled MCP server: {name}")
            return True
        return False
