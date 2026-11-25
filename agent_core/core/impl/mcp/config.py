# -*- coding: utf-8 -*-
"""
MCP Configuration Module

Handles loading and validation of MCP server configurations.

Validation happens in two places, on purpose:

* Structure is checked when an entry is built (``MCPServerConfig``): the
  transport, the URL shape, header names and values, the timeout. An entry
  that fails is kept as an ``InvalidServerEntry`` and written back unchanged
  on save, so a typo never deletes a server.
* Secrets are resolved when a server connects (``resolve_headers``). A header
  value may reference ``${NAME}``, which is looked up in that server's own
  ``env`` and nowhere else. A missing or empty value fails only that server,
  and error messages name the variable, never a value.

The ``env`` and header values are credentials: nothing in this module puts
them in a log line or an exception message.
"""

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from agent_core.utils.logger import logger

# Streamable HTTP is configured as "http"; the aliases are accepted on input
# and normalised, so a saved file always says "http".
VALID_TRANSPORTS = ("stdio", "sse", "websocket", "http")
TRANSPORT_ALIASES = {"streamable_http": "http", "streamable-http": "http"}
URL_TRANSPORTS = ("sse", "websocket", "http")

DEFAULT_HTTP_TIMEOUT = 30.0
MAX_TIMEOUT = 300.0

# RFC 9110 token characters.
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
# Any control character except horizontal tab (CR/LF would split headers).
_HEADER_VALUE_FORBIDDEN_RE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
# Public: other modules (profile bundles) find ${NAME} references with it.
ENV_REF_RE = _ENV_REF_RE

# Headers the transport owns. A configured value would break the protocol
# (Accept, Content-Type, session/version headers) or HTTP framing.
RESERVED_HEADERS = frozenset(
    {
        "accept",
        "connection",
        "content-length",
        "content-type",
        "expect",
        "host",
        "keep-alive",
        "last-event-id",
        "mcp-protocol-version",
        "mcp-session-id",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

_KNOWN_SERVER_KEYS = frozenset(
    {
        "name",
        "description",
        "transport",
        "command",
        "args",
        "cwd",
        "url",
        "env",
        "headers",
        "timeout",
        "enabled",
        "action_set_name",
    }
)


class MCPConfigError(ValueError):
    """An MCP server configuration is invalid. The message is safe to show:
    it never contains an env or header value."""


def redact_url(url: Optional[str]) -> str:
    """The URL without user info, query string or fragment, for logs and
    errors. Those parts are where credentials end up in URLs."""
    if not url:
        return ""
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return "<invalid url>"
    host = parts.hostname or ""
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port else host
    redacted = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    if parts.username or parts.password or parts.query or parts.fragment:
        redacted += " (credentials/query hidden)"
    return redacted


def _env_refs(value: str) -> List[str]:
    return _ENV_REF_RE.findall(value)


def _validate_header_value(server: str, header: str, value: str) -> None:
    if _HEADER_VALUE_FORBIDDEN_RE.search(value):
        raise MCPConfigError(
            f"Server '{server}': header '{header}' contains a control character "
            "(line breaks are not allowed in header values)"
        )
    leftover = _ENV_REF_RE.sub("", value)
    if "${" in leftover:
        raise MCPConfigError(
            f"Server '{server}': header '{header}' has a malformed reference; "
            "use ${NAME} with letters, digits and underscores"
        )


def _validate_headers(server: str, headers: Any) -> Dict[str, str]:
    if headers is None:
        return {}
    if not isinstance(headers, dict):
        raise MCPConfigError(f"Server '{server}': 'headers' must be an object")
    seen: Dict[str, str] = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not _HEADER_NAME_RE.match(name):
            raise MCPConfigError(
                f"Server '{server}': invalid header name {name!r} "
                "(letters, digits and !#$%&'*+.^_`|~- only)"
            )
        lower = name.lower()
        if lower in RESERVED_HEADERS:
            raise MCPConfigError(
                f"Server '{server}': header '{name}' is set by the transport "
                "and cannot be configured"
            )
        if lower in seen:
            raise MCPConfigError(
                f"Server '{server}': header '{name}' is given twice "
                f"(also as '{seen[lower]}'); header names are case-insensitive"
            )
        seen[lower] = name
        if not isinstance(value, str):
            raise MCPConfigError(f"Server '{server}': header '{name}' must be a string")
        _validate_header_value(server, name, value)
    return dict(headers)


def _validate_url(server: str, transport: str, url: Any) -> None:
    if not url:
        raise MCPConfigError(
            f"Server '{server}' uses {transport} transport but 'url' is not specified"
        )
    if transport != "http":
        return  # sse/websocket keep their historical (presence-only) check
    if not isinstance(url, str) or url != url.strip() or any(c.isspace() for c in url):
        raise MCPConfigError(f"Server '{server}': 'url' must be a URL without spaces")
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 — raises ValueError for a bad port
    except ValueError:
        raise MCPConfigError(f"Server '{server}': 'url' is not a valid URL") from None
    if parts.scheme not in ("http", "https"):
        raise MCPConfigError(
            f"Server '{server}': http transport needs an http:// or https:// url"
        )
    if not parts.hostname:
        raise MCPConfigError(f"Server '{server}': 'url' has no host")
    if parts.username or parts.password:
        raise MCPConfigError(
            f"Server '{server}': put credentials in 'headers', not in the url"
        )
    if parts.fragment:
        raise MCPConfigError(f"Server '{server}': 'url' must not have a #fragment")


# (server, transport, keys) already warned about: the config is re-read on
# every reload and settings refresh, and one warning per entry is enough.
_WARNED_IGNORED_KEYS: set = set()


def _validate_timeout(server: str, timeout: Any) -> Optional[float]:
    if timeout is None:
        return None
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise MCPConfigError(f"Server '{server}': 'timeout' must be a number")
    if not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT:
        raise MCPConfigError(
            f"Server '{server}': 'timeout' must be between 0 and {MAX_TIMEOUT:g} seconds"
        )
    return float(timeout)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str  # Server identifier (e.g., "filesystem")
    description: str = ""  # Human-readable description
    transport: str = "stdio"  # "stdio" | "sse" | "websocket" | "http"
    command: Optional[str] = None  # For stdio: executable path
    args: List[str] = field(default_factory=list)  # For stdio: command arguments
    cwd: Optional[str] = None  # For stdio: working directory for the subprocess
    url: Optional[str] = None  # For sse/websocket/http: server URL
    env: Dict[str, str] = field(default_factory=dict)  # Environment variables
    enabled: bool = True  # Enable/disable toggle
    action_set_name: Optional[str] = None  # Custom set name (defaults to mcp_{name})
    # For http: extra request headers; values may reference ${NAME} in env.
    headers: Dict[str, str] = field(default_factory=dict)
    # For http: seconds allowed for connecting and for each request.
    timeout: Optional[float] = None
    # Keys this version does not know, written back unchanged on save.
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate the entry's structure (secrets are resolved at connect)."""
        if not isinstance(self.name, str) or not self.name.strip():
            raise MCPConfigError("MCP server 'name' must be a non-empty string")

        transport = self.transport
        if isinstance(transport, str):
            transport = transport.strip().lower()
            transport = TRANSPORT_ALIASES.get(transport, transport)
        if transport not in VALID_TRANSPORTS:
            raise MCPConfigError(
                f"Invalid transport '{self.transport}' for server '{self.name}'. "
                f"Must be one of: {', '.join(VALID_TRANSPORTS)} "
                "(streamable_http is accepted for http)"
            )
        self.transport = transport

        if transport == "stdio":
            if not self.command:
                raise MCPConfigError(
                    f"Server '{self.name}' uses stdio transport but 'command' is not specified"
                )
        else:
            _validate_url(self.name, transport, self.url)

        if self.env is None:
            self.env = {}
        if not isinstance(self.env, dict):
            raise MCPConfigError(f"Server '{self.name}': 'env' must be an object")

        if transport != "http":
            self._set_aside_http_only_fields(transport)
        self.headers = _validate_headers(self.name, self.headers)
        self.timeout = _validate_timeout(self.name, self.timeout)

    def _set_aside_http_only_fields(self, transport: str) -> None:
        """``headers`` and ``timeout`` only apply to http. Earlier versions
        ignored them on the other transports, so an entry that has them
        still loads: they are not applied, but kept unchanged (written back
        on save, and used again if the entry is switched to http)."""
        ignored: Dict[str, Any] = {}
        if self.headers:
            ignored["headers"] = self.headers
        if self.timeout is not None:
            ignored["timeout"] = self.timeout
        self.headers = {}
        self.timeout = None
        if not ignored:
            return
        self.extra = {**self.extra, **ignored}
        warned = (self.name, transport, tuple(ignored))
        if warned not in _WARNED_IGNORED_KEYS:
            _WARNED_IGNORED_KEYS.add(warned)
            logger.warning(
                f"MCP server '{self.name}': {' and '.join(ignored)} only apply "
                f"to the http transport; ignored for {transport}"
            )

    @property
    def resolved_action_set_name(self) -> str:
        """Get the action set name, defaulting to mcp_{name} if not specified."""
        return self.action_set_name or f"mcp_{self.name}"

    @property
    def effective_timeout(self) -> float:
        """Seconds the http transport allows per request."""
        return self.timeout if self.timeout is not None else DEFAULT_HTTP_TIMEOUT

    def header_env_refs(self) -> List[str]:
        """Names of the env entries the headers reference, in order."""
        refs: List[str] = []
        for value in self.headers.values():
            for ref in _env_refs(value):
                if ref not in refs:
                    refs.append(ref)
        return refs

    def resolve_headers(self) -> Dict[str, str]:
        """The headers to send, with ``${NAME}`` filled from this server's
        ``env``. Raises MCPConfigError naming every missing or empty
        variable; never substitutes an empty value."""
        missing: List[str] = []
        resolved: Dict[str, str] = {}
        for header, value in self.headers.items():

            def substitute(match: "re.Match[str]") -> str:
                ref = match.group(1)
                env_value = self.env.get(ref)
                if not isinstance(env_value, str) or env_value == "":
                    if ref not in missing:
                        missing.append(ref)
                    return ""
                return env_value

            final = _ENV_REF_RE.sub(substitute, value)
            if not missing and final.strip() == "":
                raise MCPConfigError(
                    f"Server '{self.name}': header '{header}' resolves to an empty value"
                )
            if _HEADER_VALUE_FORBIDDEN_RE.search(final):
                raise MCPConfigError(
                    f"Server '{self.name}': the value for header '{header}' "
                    "contains a line break or control character"
                )
            resolved[header] = final
        if missing:
            names = ", ".join(missing)
            raise MCPConfigError(
                f"Server '{self.name}': set {names} in this server's env "
                "(referenced by its headers)"
            )
        return resolved

    def connection_fingerprint(self) -> str:
        """Everything that changes how the server is reached. Two configs
        with the same fingerprint can share one live connection."""
        return json.dumps(
            {
                "transport": self.transport,
                "command": self.command,
                "args": self.args,
                "cwd": self.cwd,
                "url": self.url,
                "env": self.env,
                "headers": self.headers,
                "timeout": self.timeout,
            },
            sort_keys=True,
            default=str,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPServerConfig":
        """Create MCPServerConfig from a dictionary."""
        if not isinstance(data, dict):
            raise MCPConfigError("MCP server entry must be an object")
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            transport=data.get("transport", "stdio"),
            command=data.get("command"),
            args=data.get("args", []),
            cwd=data.get("cwd"),
            url=data.get("url"),
            env=data.get("env", {}),
            enabled=data.get("enabled", True),
            action_set_name=data.get("action_set_name"),
            headers=data.get("headers") or {},
            timeout=data.get("timeout"),
            extra={k: v for k, v in data.items() if k not in _KNOWN_SERVER_KEYS},
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "transport": self.transport,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "enabled": self.enabled,
        }
        # Only include optional fields if they have values
        if self.cwd:
            result["cwd"] = self.cwd
        if self.url:
            result["url"] = self.url
        if self.action_set_name:
            result["action_set_name"] = self.action_set_name
        if self.headers:
            result["headers"] = dict(self.headers)
        if self.timeout is not None:
            result["timeout"] = self.timeout
        for key, value in self.extra.items():
            result.setdefault(key, value)
        return result


@dataclass
class InvalidServerEntry:
    """An entry that failed validation. It is not connected, but it is kept
    and saved back verbatim so the user can fix it."""

    raw: Any
    error: str
    index: int  # position in the file's mcp_servers list

    @property
    def name(self) -> Optional[str]:
        if isinstance(self.raw, dict) and isinstance(self.raw.get("name"), str):
            return self.raw["name"]
        return None


@dataclass
class MCPConfig:
    """Main MCP configuration containing all server configurations."""

    mcp_servers: List[MCPServerConfig] = field(default_factory=list)
    auto_connect: bool = True  # Automatically connect to enabled servers on init
    invalid_servers: List[InvalidServerEntry] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

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
        if not isinstance(data, dict):
            raise MCPConfigError("MCP config must be a JSON object")
        servers: List[MCPServerConfig] = []
        invalid: List[InvalidServerEntry] = []
        seen: set = set()
        entries = data.get("mcp_servers", [])
        if not isinstance(entries, list):
            raise MCPConfigError("'mcp_servers' must be a list")
        for index, server_data in enumerate(entries):
            try:
                server = MCPServerConfig.from_dict(server_data)
            except KeyError:
                error = "missing 'name'"
            except (MCPConfigError, ValueError, TypeError) as e:
                error = str(e)
            else:
                if server.name in seen:
                    error = (
                        f"duplicate server name '{server.name}'; "
                        "the first entry with this name is used"
                    )
                else:
                    seen.add(server.name)
                    servers.append(server)
                    continue
            invalid.append(InvalidServerEntry(server_data, error, index))
            logger.warning(f"[MCP] Skipping invalid server config: {error}")

        return cls(
            mcp_servers=servers,
            auto_connect=data.get("auto_connect", True),
            invalid_servers=invalid,
            extra={
                k: v
                for k, v in data.items()
                if k not in ("mcp_servers", "auto_connect")
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization. Invalid entries are put
        back at their original positions, unchanged."""
        entries: List[Any] = [s.to_dict() for s in self.mcp_servers]
        for entry in sorted(self.invalid_servers, key=lambda e: e.index):
            entries.insert(min(entry.index, len(entries)), entry.raw)
        result: Dict[str, Any] = {
            "mcp_servers": entries,
            "auto_connect": self.auto_connect,
        }
        for key, value in self.extra.items():
            result.setdefault(key, value)
        return result

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

    def get_invalid_entries(self, name: str) -> List[InvalidServerEntry]:
        """Invalid entries that carry this name."""
        return [e for e in self.invalid_servers if e.name == name]

    def add_server(self, server: MCPServerConfig) -> bool:
        """
        Add a new server configuration.

        Args:
            server: Server configuration to add

        Returns:
            True if added, False if server with same name already exists
        """
        if self.get_server_by_name(server.name) or self.get_invalid_entries(
            server.name
        ):
            logger.warning(f"Server '{server.name}' already exists")
            return False
        self.mcp_servers.append(server)
        logger.info(f"Added MCP server: {server.name}")
        return True

    def replace_server(self, server: MCPServerConfig) -> bool:
        """Replace the entry with this name in place (valid or invalid),
        keeping its position. Returns False if there is none."""
        for i, existing in enumerate(self.mcp_servers):
            if existing.name == server.name:
                self.mcp_servers[i] = server
                return True
        invalid = self.get_invalid_entries(server.name)
        if invalid:
            target = invalid[0]
            self.invalid_servers = [e for e in self.invalid_servers if e is not target]
            position = sum(1 for e in self.invalid_servers if e.index < target.index)
            self.mcp_servers.insert(
                max(0, min(target.index - position, len(self.mcp_servers))), server
            )
            return True
        return False

    def remove_server(self, name: str) -> bool:
        """
        Remove a server configuration by name.

        Also removes invalid entries with that name, so a broken entry can be
        deleted from the UI.

        Args:
            name: Name of the server to remove

        Returns:
            True if removed, False if not found
        """
        removed = False
        for i, server in enumerate(self.mcp_servers):
            if server.name == name:
                del self.mcp_servers[i]
                removed = True
                break
        before = len(self.invalid_servers)
        self.invalid_servers = [e for e in self.invalid_servers if e.name != name]
        removed = removed or len(self.invalid_servers) != before
        if removed:
            logger.info(f"Removed MCP server: {name}")
        else:
            logger.warning(f"Server '{name}' not found")
        return removed

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
