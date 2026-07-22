"""Credential management command implementation."""

from __future__ import annotations

from typing import List

from app.ui_layer.commands.base import Command, CommandResult
from craftos_integrations import (
    get_all_handlers,
    is_connected,
    parse_status_accounts,
)


class CredCommand(Command):
    """Manage credentials and integrations."""

    @property
    def name(self) -> str:
        return "/cred"

    @property
    def description(self) -> str:
        return "Manage credentials and integrations"

    @property
    def usage(self) -> str:
        return "/cred <subcommand>"

    @property
    def help_text(self) -> str:
        return """Manage credentials and integrations.

Subcommands:
  list          - List all credentials
  status        - Show integration status
  integrations  - List available integrations

Use /<integration> commands to manage specific integrations:
  /google       - Google integration
  /slack        - Slack integration
  /telegram_bot - Telegram Bot integration
  etc.

Examples:
  /cred list
  /cred status
  /cred integrations
  /google connect"""

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
        session_id: str | None = None,
    ) -> CommandResult:
        """Execute the cred command."""
        if not args:
            return CommandResult(success=True, message=self.help_text)

        subcommand = args[0].lower()

        handlers = {
            "list": self._list_credentials,
            "status": self._show_status,
            "integrations": self._list_integrations,
        }

        handler = handlers.get(subcommand)
        if handler:
            return await handler()

        return CommandResult(
            success=False,
            message=f"Unknown subcommand: {subcommand}\nUse /help cred for usage.",
        )

    async def _list_credentials(self) -> CommandResult:
        """List all configured credentials."""
        lines = ["Configured credentials:", ""]

        for name in get_all_handlers():
            connected = is_connected(name)
            lines.append(f"  {name}: {'connected' if connected else 'not connected'}")

        return CommandResult(success=True, message="\n".join(lines))

    async def _show_status(self) -> CommandResult:
        """Show integration status with per-account info when connected."""
        lines = ["Integration status:", ""]

        connected_count = 0
        all_handlers = get_all_handlers()

        for name, handler in all_handlers.items():
            display = handler.display_name or name
            try:
                _, status_msg = await handler.status()
                first = status_msg.split("\n", 1)[0]
                connected = "Connected" in first and "Not connected" not in first
                if connected:
                    connected_count += 1
                    accounts = parse_status_accounts(status_msg)
                    if accounts:
                        account_label = ", ".join(
                            a.get("display") or a.get("id", "") for a in accounts
                        )
                        lines.append(f"  [+] {display} ({account_label})")
                    else:
                        lines.append(f"  [+] {display}")
                else:
                    lines.append(f"  [ ] {display}")
            except Exception:
                lines.append(f"  [?] {display}")

        lines.append("")
        lines.append(f"{connected_count}/{len(all_handlers)} integrations connected")
        lines.append("")
        lines.append("Use /<integration> to manage a specific integration.")

        return CommandResult(success=True, message="\n".join(lines))

    async def _list_integrations(self) -> CommandResult:
        """List available integrations."""
        lines = ["Available integrations:", ""]

        for name, handler in get_all_handlers().items():
            display = handler.display_name or name
            description = handler.description
            suffix = f" — {description}" if description else ""
            lines.append(f"  /{name}  ({display}){suffix}")

        lines.append("")
        lines.append("Use /<integration> to see commands for that integration.")

        return CommandResult(success=True, message="\n".join(lines))
