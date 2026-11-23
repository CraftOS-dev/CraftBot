"""MCP settings management.

The one path by which the UI and the ``/mcp`` command change
``mcp_config.json``. Every write builds an ``MCPServerConfig`` first, so they
share the runtime's validation, and a rejected change is never saved.

Header values are never listed: a server's headers are reported by name
(and the env keys they reference) only.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional, Tuple

from app.config import APP_CONFIG_PATH
from app.logger import logger
from app.mcp import MCPConfig, MCPServerConfig
from agent_core.core.impl.mcp.config import MCPConfigError, redact_url

# Default MCP config path
MCP_CONFIG_PATH = APP_CONFIG_PATH / "mcp_config.json"


def _is_windows_path(path: str) -> bool:
    """Check if a path uses Windows drive-letter syntax (e.g. C:/...)."""
    return bool(path) and len(path) >= 2 and path[0].isalpha() and path[1] == ":"


def _path_usable_on_current_platform(command: str, args: list) -> bool:
    """Return False if command/args reference paths not valid on this OS."""
    if sys.platform == "win32":
        return True
    if _is_windows_path(command):
        return False
    for arg in args or []:
        if _is_windows_path(arg):
            return False
    return True


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


def _missing_config(server: MCPServerConfig) -> List[str]:
    """Env keys the server needs but has no value for: empty env entries,
    and variables its headers reference."""
    missing = [k for k, v in (server.env or {}).items() if not v]
    for ref in server.header_env_refs():
        if not server.env.get(ref) and ref not in missing:
            missing.append(ref)
    return missing


def describe_server(server: MCPServerConfig) -> Dict[str, Any]:
    """A server as the UI and /mcp see it: no env or header values."""
    platform_blocked = not _path_usable_on_current_platform(
        server.command or "", getattr(server, "args", []) or []
    )
    if platform_blocked:
        logger.debug(
            "MCP server %s has platform-specific paths — skipping on %s",
            server.name,
            sys.platform,
        )
    missing = _missing_config(server)
    return {
        "name": server.name,
        "description": server.description,
        "enabled": server.enabled,
        "transport": server.transport,
        "command": server.command,
        "url": redact_url(server.url) if server.url else None,
        "timeout": server.timeout,
        "action_set": server.resolved_action_set_name,
        # Unchanged shape for the existing editors (see mcp_get_env).
        "env": dict(server.env or {}),
        # Header names and the env keys each references; no values.
        "headers": [
            {
                "name": name,
                "uses": [r for r in server.header_env_refs() if f"${{{r}}}" in value],
            }
            for name, value in server.headers.items()
        ],
        "missing_env": missing,
        "needs_config": bool(missing),
        "platform_blocked": platform_blocked,
        "invalid": False,
        "error": None,
    }


def list_mcp_servers() -> List[Dict[str, Any]]:
    """Get list of configured MCP servers with their status.

    Servers with platform-incompatible paths (e.g. Windows paths on macOS)
    are annotated with a ``platform_blocked`` flag so the UI can explain why
    they cannot be started. Entries that fail validation are listed with
    ``invalid: True`` and the (credential-free) reason, so they can be fixed
    or removed instead of silently disappearing.
    """
    try:
        config = load_mcp_config()
    except Exception as exc:
        logger.error(f"Failed to load MCP config: {exc}")
        return []
    servers = [describe_server(server) for server in config.mcp_servers]
    for entry in config.invalid_servers:
        raw = entry.raw if isinstance(entry.raw, dict) else {}
        servers.append(
            {
                "name": entry.name or f"<entry {entry.index + 1}>",
                "description": raw.get("description", "")
                if isinstance(raw.get("description"), str)
                else "",
                "enabled": bool(raw.get("enabled", True)),
                "transport": raw.get("transport", "stdio")
                if isinstance(raw.get("transport"), str)
                else None,
                "command": None,
                "url": None,
                "timeout": None,
                "action_set": None,
                "env": {},
                "headers": [],
                "missing_env": [],
                "needs_config": False,
                "platform_blocked": False,
                "invalid": True,
                "error": entry.error,
            }
        )
    return servers


def get_server_env_vars(server_name: str) -> Dict[str, str]:
    """Get the environment variables for an existing server.

    Returns raw values: for server-side use only. Anything sent to a client
    should use ``get_server_env_status``.
    """
    config = load_mcp_config()
    server = config.get_server_by_name(server_name)
    if server:
        return server.env
    return {}


def _build_server(data: Dict[str, Any]) -> Tuple[Optional[MCPServerConfig], str]:
    try:
        return MCPServerConfig.from_dict(data), ""
    except KeyError:
        return None, "Server 'name' is required"
    except (MCPConfigError, ValueError, TypeError) as e:
        return None, str(e)


def add_mcp_server(
    name: str,
    description: str = "",
    transport: str = "stdio",
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    url: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    enabled: bool = True,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
) -> tuple[bool, str]:
    """
    Add a new MCP server configuration.

    Returns:
        Tuple of (success, message)
    """
    data: Dict[str, Any] = {
        "name": name,
        "description": description,
        "transport": transport,
        "command": command,
        "args": args or [],
        "url": url,
        "env": env or {},
        "enabled": enabled,
    }
    if headers:
        data["headers"] = headers
    if timeout is not None:
        data["timeout"] = timeout
    return _add_entry(data)


def _add_entry(data: Dict[str, Any]) -> Tuple[bool, str]:
    config = load_mcp_config()
    name = data.get("name")
    if isinstance(name, str) and (
        config.get_server_by_name(name) or config.get_invalid_entries(name)
    ):
        return False, f"Server '{name}' already exists"
    server, error = _build_server(data)
    if server is None:
        return False, error
    config.add_server(server)
    if not save_mcp_config(config):
        return False, f"Could not save the MCP config for '{server.name}'"
    return True, f"Added MCP server: {server.name}"


def add_mcp_server_from_json(name: str, json_config: str) -> tuple[bool, str]:
    """
    Add an MCP server from a JSON configuration string.

    Args:
        name: Server name
        json_config: JSON string with server configuration
            Fields: transport, command, args, url, env, headers, timeout,
            description, enabled; unknown fields are kept as-is.

    Returns:
        Tuple of (success, message)

    Example:
        add_mcp_server_from_json("my-server", '{"transport":"stdio","command":"python","args":["-m","my_server"]}')
        add_mcp_server_from_json("remote", '{"transport":"http","url":"https://host/mcp","headers":{"Authorization":"Bearer ${TOKEN}"},"env":{"TOKEN":""}}')
    """
    try:
        config_dict = json.loads(json_config)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e.msg} (line {e.lineno}, column {e.colno})"
    if not isinstance(config_dict, dict):
        return False, "The server configuration must be a JSON object"

    return _add_entry({**config_dict, "name": name})


def remove_mcp_server(name: str) -> tuple[bool, str]:
    """
    Remove an MCP server configuration (valid or invalid entry).

    Returns:
        Tuple of (success, message)
    """
    config = load_mcp_config()

    if not config.get_server_by_name(name) and not config.get_invalid_entries(name):
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


def set_mcp_server_header(
    name: str, header: str, value: Optional[str]
) -> Tuple[bool, str]:
    """Set (or, with ``value=None``, remove) one header of an http server.
    Validated exactly like the JSON file; nothing is saved on error."""
    config = load_mcp_config()
    server = config.get_server_by_name(name)
    if not server:
        return False, f"Server '{name}' not found"
    headers = {k: v for k, v in server.headers.items() if k.lower() != header.lower()}
    if value is not None:
        headers[header] = value
    elif len(headers) == len(server.headers):
        return False, f"Server '{name}' has no header '{header}'"
    updated, error = _build_server({**server.to_dict(), "headers": headers})
    if updated is None:
        return False, error
    config.replace_server(updated)
    if not save_mcp_config(config):
        return False, f"Could not save the MCP config for '{name}'"
    action = "Set" if value is not None else "Removed"
    return True, f"{action} header '{header}' for server '{name}'"
