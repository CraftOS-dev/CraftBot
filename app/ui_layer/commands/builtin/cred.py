"""Credential management command implementation."""

from __future__ import annotations

from typing import List

from app.ui_layer.commands.base import Command, CommandResult
from app.credentials.handlers import INTEGRATION_HANDLERS


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
  /telegram     - Telegram integration
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
    ) -> CommandResult:
        """Execute the cred command."""
        if not args:
            return await self._show_status()

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

        for name, handler in INTEGRATION_HANDLERS.items():
            try:
                status = handler.get_status() if hasattr(handler, "get_status") else {}
                connected = status.get("connected", False)
                status_text = "connected" if connected else "not connected"
                lines.append(f"  {name}: {status_text}")
            except Exception:
                lines.append(f"  {name}: unknown")

        return CommandResult(success=True, message="\n".join(lines))

    async def _show_status(self) -> CommandResult:
        """Show integration status."""
        lines = ["Integration status:", ""]

        connected_count = 0
        total_count = len(INTEGRATION_HANDLERS)

        for name, handler in INTEGRATION_HANDLERS.items():
            try:
                status = handler.get_status() if hasattr(handler, "get_status") else {}
                connected = status.get("connected", False)
                if connected:
                    connected_count += 1
                    account = status.get("account", "")
                    account_info = f" ({account})" if account else ""
                    lines.append(f"  [+] {name}{account_info}")
                else:
                    lines.append(f"  [ ] {name}")
            except Exception:
                lines.append(f"  [?] {name}")

        lines.append("")
        lines.append(f"{connected_count}/{total_count} integrations connected")
        lines.append("")
        lines.append("Use /<integration> to manage a specific integration.")

        return CommandResult(success=True, message="\n".join(lines))

    async def _list_integrations(self) -> CommandResult:
        """List available integrations."""
        lines = ["Available integrations:", ""]

        for name, handler in INTEGRATION_HANDLERS.items():
            desc = ""
            if hasattr(handler, "description"):
                desc = f" - {handler.description}"
            lines.append(f"  /{name}{desc}")

        lines.append("")
        lines.append("Use /<integration> to see commands for that integration.")

        return CommandResult(success=True, message="\n".join(lines))
