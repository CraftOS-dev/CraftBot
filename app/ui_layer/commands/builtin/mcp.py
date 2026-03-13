"""MCP (Model Context Protocol) command implementation."""

from __future__ import annotations

from typing import List

from app.ui_layer.commands.base import Command, CommandResult
from app.ui_layer.settings import (
    list_mcp_servers,
    add_mcp_server,
    add_mcp_server_from_json,
    remove_mcp_server,
    enable_mcp_server,
    disable_mcp_server,
    update_mcp_server_env,
)


class MCPCommand(Command):
    """Manage MCP servers."""

    @property
    def name(self) -> str:
        return "/mcp"

    @property
    def description(self) -> str:
        return "Manage MCP servers"

    @property
    def usage(self) -> str:
        return "/mcp <subcommand> [args]"

    @property
    def help_text(self) -> str:
        return """Manage Model Context Protocol (MCP) servers.

Subcommands:
  list                           - List configured servers
  add <name> --transport stdio -- <cmd>  - Add stdio server
  add <name> --transport http <url>      - Add HTTP server
  add-json <name> '<json>'       - Add from JSON config
  remove <name>                  - Remove server
  enable <name>                  - Enable server
  disable <name>                 - Disable server
  env <name> <key> <value>       - Set environment variable

Examples:
  /mcp list
  /mcp add myserver --transport stdio -- python server.py
  /mcp remove myserver
  /mcp enable myserver
  /mcp env myserver API_KEY my-secret-key"""

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
    ) -> CommandResult:
        """Execute the mcp command."""
        if not args:
            return await self._list_servers()

        subcommand = args[0].lower()
        sub_args = args[1:]

        handlers = {
            "list": self._list_servers,
            "add": lambda: self._add_server(sub_args),
            "add-json": lambda: self._add_server_json(sub_args),
            "remove": lambda: self._remove_server(sub_args),
            "enable": lambda: self._enable_server(sub_args),
            "disable": lambda: self._disable_server(sub_args),
            "env": lambda: self._set_env(sub_args),
        }

        handler = handlers.get(subcommand)
        if handler:
            return await handler()

        return CommandResult(
            success=False,
            message=f"Unknown subcommand: {subcommand}\nUse /help mcp for usage.",
        )

    async def _list_servers(self) -> CommandResult:
        """List configured MCP servers."""
        servers = list_mcp_servers()
        if not servers:
            return CommandResult(
                success=True,
                message="No MCP servers configured. Use /mcp add to add a server.",
            )

        lines = ["Configured MCP servers:", ""]
        for server in servers:
            status = "enabled" if server.get("enabled", True) else "disabled"
            name = server.get("name", "unknown")
            lines.append(f"  {name} [{status}]")

        return CommandResult(success=True, message="\n".join(lines))

    async def _add_server(self, args: List[str]) -> CommandResult:
        """Add an MCP server."""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /mcp add <name> --transport <type> ...",
            )

        if "--transport" not in args:
            return CommandResult(
                success=False,
                message="Server requires --transport. Use /help mcp for syntax.",
            )

        name = args[0]
        transport_idx = args.index("--transport")
        transport = args[transport_idx + 1] if len(args) > transport_idx + 1 else ""

        if transport == "stdio":
            # Find command after --
            if "--" in args:
                cmd_idx = args.index("--")
                cmd = args[cmd_idx + 1 :]
                if cmd:
                    result = add_mcp_server(
                        name=name,
                        transport="stdio",
                        command=cmd,
                    )
                    if result.get("success"):
                        return CommandResult(
                            success=True,
                            message=f"Added stdio MCP server: {name}",
                        )
                    return CommandResult(
                        success=False,
                        message=result.get("error", "Failed to add server"),
                    )

        elif transport == "http":
            url = args[transport_idx + 2] if len(args) > transport_idx + 2 else ""
            if url:
                result = add_mcp_server(
                    name=name,
                    transport="http",
                    url=url,
                )
                if result.get("success"):
                    return CommandResult(
                        success=True,
                        message=f"Added HTTP MCP server: {name}",
                    )
                return CommandResult(
                    success=False,
                    message=result.get("error", "Failed to add server"),
                )

        return CommandResult(
            success=False,
            message="Invalid arguments. Use /help mcp for syntax.",
        )

    async def _add_server_json(self, args: List[str]) -> CommandResult:
        """Add MCP server from JSON config."""
        if len(args) < 2:
            return CommandResult(
                success=False,
                message="Usage: /mcp add-json <name> '<json_config>'",
            )

        name = args[0]
        json_str = " ".join(args[1:])

        result = add_mcp_server_from_json(name, json_str)
        if result.get("success"):
            return CommandResult(
                success=True,
                message=f"Added MCP server from JSON: {name}",
            )
        return CommandResult(
            success=False,
            message=result.get("error", "Failed to add server"),
        )

    async def _remove_server(self, args: List[str]) -> CommandResult:
        """Remove an MCP server."""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /mcp remove <name>",
            )

        name = args[0]
        result = remove_mcp_server(name)
        if result.get("success"):
            return CommandResult(
                success=True,
                message=f"Removed MCP server: {name}",
            )
        return CommandResult(
            success=False,
            message=result.get("error", f"Failed to remove server: {name}"),
        )

    async def _enable_server(self, args: List[str]) -> CommandResult:
        """Enable an MCP server."""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /mcp enable <name>",
            )

        name = args[0]
        result = enable_mcp_server(name)
        if result.get("success"):
            return CommandResult(
                success=True,
                message=f"Enabled MCP server: {name}",
            )
        return CommandResult(
            success=False,
            message=result.get("error", f"Failed to enable server: {name}"),
        )

    async def _disable_server(self, args: List[str]) -> CommandResult:
        """Disable an MCP server."""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /mcp disable <name>",
            )

        name = args[0]
        result = disable_mcp_server(name)
        if result.get("success"):
            return CommandResult(
                success=True,
                message=f"Disabled MCP server: {name}",
            )
        return CommandResult(
            success=False,
            message=result.get("error", f"Failed to disable server: {name}"),
        )

    async def _set_env(self, args: List[str]) -> CommandResult:
        """Set environment variable for an MCP server."""
        if len(args) < 3:
            return CommandResult(
                success=False,
                message="Usage: /mcp env <server_name> <key> <value>",
            )

        name, key, value = args[0], args[1], " ".join(args[2:])
        result = update_mcp_server_env(name, key, value)
        if result.get("success"):
            return CommandResult(
                success=True,
                message=f"Set {key}={value} for MCP server: {name}",
            )
        return CommandResult(
            success=False,
            message=result.get("error", f"Failed to set env for server: {name}"),
        )
