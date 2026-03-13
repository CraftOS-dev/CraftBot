"""MCP settings management for the TUI interface."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Any

from app.logger import logger
from app.mcp import MCPConfig, MCPServerConfig

# Default MCP config path
MCP_CONFIG_PATH = Path("app/config/mcp_config.json")


def load_mcp_config() -> MCPConfig:
    """Load MCP configuration from file."""
    try:
        return MCPConfig.load(MCP_CONFIG_PATH)
    except Exception as e:
        logger.error(f"Failed to load MCP config: {e}")
        return MCPConfig()


def save_mcp_config(config: MCPConfig) -> bool:
    """Save MCP configuration to file."""
    try:
        config.save(MCP_CONFIG_PATH)
        logger.info(f"Saved MCP config to {MCP_CONFIG_PATH}")
        return True
    except Exception as e:
        logger.error(f"Failed to save MCP config: {e}")
        return False


def list_mcp_servers() -> List[Dict[str, Any]]:
    """Get list of configured MCP servers with their status."""
    config = load_mcp_config()
    servers = []
    for server in config.mcp_servers:
        servers.append({
            "name": server.name,
            "description": server.description,
            "enabled": server.enabled,
            "transport": server.transport,
            "command": server.command,
            "action_set": server.resolved_action_set_name,
            "env": server.env,
        })
    return servers


def get_server_env_vars(server_name: str) -> Dict[str, str]:
    """Get the environment variables for an existing server."""
    config = load_mcp_config()
    server = config.get_server_by_name(server_name)
    if server:
        return server.env
    return {}


def add_mcp_server(
    name: str,
    description: str = "",
    transport: str = "stdio",
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    url: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    enabled: bool = True,
) -> tuple[bool, str]:
    """
    Add a new MCP server configuration.

    Returns:
        Tuple of (success, message)
    """
    config = load_mcp_config()

    # Check if server already exists
    if config.get_server_by_name(name):
        return False, f"Server '{name}' already exists"

    try:
        server = MCPServerConfig(
            name=name,
            description=description,
            transport=transport,
            command=command,
            args=args or [],
            url=url,
            env=env or {},
            enabled=enabled,
        )
        config.add_server(server)
        save_mcp_config(config)
        return True, f"Added MCP server: {name}"
    except ValueError as e:
        return False, str(e)


def add_mcp_server_from_json(name: str, json_config: str) -> tuple[bool, str]:
    """
    Add an MCP server from a JSON configuration string.

    Args:
        name: Server name
        json_config: JSON string with server configuration
            Expected fields: transport, command, args, url, env, description, enabled

    Returns:
        Tuple of (success, message)

    Example:
        add_mcp_server_from_json("my-server", '{"transport":"stdio","command":"python","args":["-m","my_server"]}')
    """
    try:
        config_dict = json.loads(json_config)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"

    return add_mcp_server(
        name=name,
        description=config_dict.get("description", ""),
        transport=config_dict.get("transport", "stdio"),
        command=config_dict.get("command"),
        args=config_dict.get("args", []),
        url=config_dict.get("url"),
        env=config_dict.get("env", {}),
        enabled=config_dict.get("enabled", True),
    )


def remove_mcp_server(name: str) -> tuple[bool, str]:
    """
    Remove an MCP server configuration.

    Returns:
        Tuple of (success, message)
    """
    config = load_mcp_config()

    if not config.get_server_by_name(name):
        return False, f"Server '{name}' not found"

    config.remove_server(name)
    save_mcp_config(config)
    return True, f"Removed MCP server: {name}"


def enable_mcp_server(name: str) -> tuple[bool, str]:
    """
    Enable an MCP server.

    Returns:
        Tuple of (success, message)
    """
    config = load_mcp_config()

    if not config.get_server_by_name(name):
        return False, f"Server '{name}' not found"

    config.enable_server(name)
    save_mcp_config(config)
    return True, f"Enabled MCP server: {name}"


def disable_mcp_server(name: str) -> tuple[bool, str]:
    """
    Disable an MCP server.

    Returns:
        Tuple of (success, message)
    """
    config = load_mcp_config()

    if not config.get_server_by_name(name):
        return False, f"Server '{name}' not found"

    config.disable_server(name)
    save_mcp_config(config)
    return True, f"Disabled MCP server: {name}"


def update_mcp_server_env(name: str, env_key: str, env_value: str) -> tuple[bool, str]:
    """
    Update an environment variable for an MCP server.

    Returns:
        Tuple of (success, message)
    """
    config = load_mcp_config()
    server = config.get_server_by_name(name)

    if not server:
        return False, f"Server '{name}' not found"

    server.env[env_key] = env_value
    save_mcp_config(config)
    return True, f"Updated {env_key} for server '{name}'"
