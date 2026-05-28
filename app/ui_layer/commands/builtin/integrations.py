"""Integration-specific command implementation.

All connect / disconnect / status operations go through the
``craftos_integrations`` package so that terminal, browser, and agent
share the same logic and side-effects (e.g. platform-listener startup).
"""

from __future__ import annotations

from typing import List

from app.ui_layer.commands.base import Command, CommandResult
from craftos_integrations import (
    connect_token as connect_integration_token,
    connect_oauth as connect_integration_oauth,
    connect_interactive as connect_integration_interactive,
    disconnect as _disconnect_integration,
    get_handler,
    get_integration_auth_type,
    get_integration_fields,
    get_integration_info_sync as get_integration_info,
    get_metadata,
)


class IntegrationCommand(Command):
    """Command for a specific integration."""

    def __init__(self, controller, integration_name: str) -> None:
        super().__init__(controller)
        self._integration_name = integration_name

    @property
    def name(self) -> str:
        return f"/{self._integration_name}"

    @property
    def description(self) -> str:
        meta = get_metadata(self._integration_name)
        if meta:
            return f"{meta['name']} — {meta['description']}"
        return f"Manage {self._integration_name} integration"

    @property
    def usage(self) -> str:
        return f"/{self._integration_name} <subcommand>"

    @property
    def help_text(self) -> str:
        lines = [f"Manage {self._integration_name} integration.", ""]
        lines.append("Common commands:")
        lines.append("  connect    - Connect to integration")
        lines.append("  disconnect - Disconnect from integration")
        lines.append("  status     - Show connection status")

        # Surface handler-specific subcommands (login-qr, invite, etc.)
        handler = get_handler(self._integration_name)
        if handler:
            extras = [
                s
                for s in getattr(handler, "subcommands", [])
                if s not in {"login", "logout", "status"}
            ]
            if extras:
                lines.append("")
                lines.append("Integration-specific subcommands:")
                for sub in extras:
                    lines.append(f"  {sub}")

        return "\n".join(lines)

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
    ) -> CommandResult:
        if get_metadata(self._integration_name) is None:
            return CommandResult(
                success=False,
                message=f"Integration not available: {self._integration_name}",
            )

        if not args:
            return CommandResult(success=True, message=self.help_text)

        subcommand = args[0].lower()
        sub_args = args[1:]

        if subcommand == "status":
            return await self._show_status()
        elif subcommand == "connect":
            return await self._connect(sub_args)
        elif subcommand == "disconnect":
            return await self._disconnect()

        # Delegate handler-specific subcommands (login-qr, invite, etc.)
        handler = get_handler(self._integration_name)
        if handler:
            try:
                success, message = await handler.handle(subcommand, sub_args)
                return CommandResult(success=success, message=message)
            except Exception as e:
                return CommandResult(success=False, message=f"Command error: {e}")

        return CommandResult(
            success=False,
            message=f"Unknown command: {subcommand}\nUse /help {self._integration_name} for usage.",
        )

    async def _show_status(self) -> CommandResult:
        """Show integration status (metadata + live connection state)."""
        try:
            info = get_integration_info(self._integration_name)
            if not info:
                return CommandResult(success=False, message="Integration not found.")

            lines = [f"{info['name']} integration status:", ""]
            lines.append(f"  Connected: {'Yes' if info['connected'] else 'No'}")

            for account in info.get("accounts", []):
                display = account.get("display", "")
                acct_id = account.get("id", "")
                if display and acct_id and display != acct_id:
                    lines.append(f"  Account: {display} ({acct_id})")
                else:
                    lines.append(f"  Account: {display or acct_id}")

            return CommandResult(success=True, message="\n".join(lines))
        except Exception as e:
            return CommandResult(success=False, message=f"Failed to get status: {e}")

    async def _connect(self, args: List[str]) -> CommandResult:
        """Dispatch to the right craftos_integrations connect_* helper.

        Picks the auth path (token / oauth / interactive) from the handler's
        declared ``auth_type``.
        """
        try:
            auth_type = get_integration_auth_type(self._integration_name)
            fields = get_integration_fields(self._integration_name)

            # Token-based: args should provide credential values in field order
            if auth_type in ("token", "both", "token_with_interactive") and (
                args or fields
            ):
                credentials: dict[str, str] = {}
                for i, field in enumerate(fields):
                    if i < len(args):
                        credentials[field["key"]] = args[i]

                if credentials:
                    success, message = await connect_integration_token(
                        self._integration_name, credentials
                    )
                    return CommandResult(success=success, message=message)

                # No args provided — show required fields
                if fields:
                    field_list = ", ".join(f["label"] for f in fields)
                    return CommandResult(
                        success=False,
                        message=f"Usage: /{self._integration_name} connect <{field_list}>",
                    )

            # OAuth-based
            if auth_type in ("oauth", "both"):
                success, message = await connect_integration_oauth(
                    self._integration_name
                )
                return CommandResult(success=success, message=message)

            # Interactive (QR code, etc.)
            if auth_type in ("interactive", "token_with_interactive"):
                success, message = await connect_integration_interactive(
                    self._integration_name
                )
                return CommandResult(success=success, message=message)

            return CommandResult(
                success=False,
                message=f"Unsupported auth type '{auth_type}' for {self._integration_name}.",
            )
        except Exception as e:
            return CommandResult(success=False, message=f"Connection failed: {e}")

    async def _disconnect(self) -> CommandResult:
        try:
            success, message = await _disconnect_integration(self._integration_name)
            return CommandResult(success=success, message=message)
        except Exception as e:
            return CommandResult(success=False, message=f"Disconnect failed: {e}")
