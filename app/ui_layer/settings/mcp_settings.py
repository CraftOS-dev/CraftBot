"""MCP settings management.

The one path by which the UI and the ``/mcp`` command change
``mcp_config.json``. Every write builds an ``MCPServerConfig`` first, so they
share the runtime's validation, and a rejected change is never saved.

Secrets: env values and header values are write-only here. Listing a server
reports which env keys are set and which headers exist, never their values,
so nothing sent to the browser or shown in chat contains a credential.
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


def _env_status(env: Dict[str, Any]) -> Dict[str, bool]:
    """Which env keys have a value. The values themselves stay server-side."""
    return {key: bool(value) for key, value in (env or {}).items()}


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
        # Arguments can carry tokens (--api-key ...): count only. The
        # editor keeps them unless the user enters a new list.
        "args": None,
        "args_count": len(server.args or []),
        "url": redact_url(server.url) if server.url else None,
        "timeout": server.timeout,
        "action_set": server.resolved_action_set_name,
        # Key -> whether a value is set (values are never sent).
        "env": _env_status(server.env),
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
                "args": None,
                "args_count": 0,
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


def get_server_env_status(server_name: str) -> Optional[Dict[str, bool]]:
    """Which env keys of a server are set (None if there is no such server)."""
    server = load_mcp_config().get_server_by_name(server_name)
    if server is None:
        return None
    status = _env_status(server.env)
    for ref in server.header_env_refs():
        status.setdefault(ref, False)
    return status


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


def save_mcp_server(form: Dict[str, Any], *, create: bool) -> Tuple[bool, str]:
    """Add or edit a server from the settings form.

    Secrets are write-only: in ``headers`` and ``env`` (lists of
    ``{"name"/"key", "value"}``) a ``value`` of None keeps the stored value,
    so the browser never needs to hold existing credentials. An item that is
    left out is removed. On edit, ``url: None`` keeps the stored URL (the
    list shows a redacted one). Fields the form does not know are preserved.
    """
    name = form.get("name")
    if not isinstance(name, str) or not name.strip():
        return False, "Server name is required"
    config = load_mcp_config()
    existing = config.get_server_by_name(name)
    if create and (existing or config.get_invalid_entries(name)):
        return False, f"Server '{name}' already exists"
    if not create and existing is None:
        if config.get_invalid_entries(name):
            return False, (
                f"Server '{name}' has an invalid entry; fix it in the JSON file "
                "or remove it and add it again"
            )
        return False, f"Server '{name}' not found"

    data: Dict[str, Any] = existing.to_dict() if existing else {"name": name}
    for key in ("description", "transport", "enabled"):
        if key in form:
            data[key] = form[key]
    if "timeout" in form:
        data["timeout"] = form["timeout"] if form["timeout"] not in ("", None) else None
    if form.get("url") is not None:
        data["url"] = form["url"]
    if "command" in form:
        data["command"] = form["command"] or None
    if form.get("args") is not None:  # None keeps the stored arguments
        data["args"] = list(form["args"])

    old_headers = existing.headers if existing else {}
    old_env = existing.env if existing else {}
    try:
        if "headers" in form:
            data["headers"] = _merge_write_only(
                form["headers"], old_headers, "name", "header", case_insensitive=True
            )
        if "env" in form:
            data["env"] = _merge_write_only(form["env"], old_env, "key", "env key")
    except MCPConfigError as e:
        return False, str(e)
    if data.get("transport") not in ("http", "streamable_http", "streamable-http"):
        data.pop("headers", None)

    server, error = _build_server(data)
    if server is None:
        return False, error
    if existing:
        config.replace_server(server)
    else:
        config.add_server(server)
    if not save_mcp_config(config):
        return False, f"Could not save the MCP config for '{name}'"
    return True, f"{'Added' if create else 'Updated'} MCP server: {name}"


def _merge_write_only(
    items: Any,
    old: Dict[str, str],
    key_field: str,
    label: str,
    *,
    case_insensitive: bool = False,
) -> Dict[str, str]:
    if not isinstance(items, list):
        raise MCPConfigError(f"'{label}s' must be a list")
    lookup = {(k.lower() if case_insensitive else k): v for k, v in old.items()}
    merged: Dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get(key_field), str):
            raise MCPConfigError(f"Each {label} needs a {key_field}")
        key = item[key_field].strip()
        if not key:
            raise MCPConfigError(f"A {label} name cannot be empty")
        value = item.get("value")
        if value is None:
            lookup_key = key.lower() if case_insensitive else key
            if lookup_key not in lookup:
                raise MCPConfigError(f"Enter a value for {label} '{key}'")
            value = lookup[lookup_key]
        elif not isinstance(value, str):
            raise MCPConfigError(f"The value for {label} '{key}' must be text")
        merged[key] = value
    return merged


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
