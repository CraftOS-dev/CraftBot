"""Integration-specific command implementation.

All connect / disconnect / status operations go through the
``craftos_integrations`` package so that terminal, browser, and agent
share the same logic and side-effects (e.g. platform-listener startup).
"""

from __future__ import annotations

from typing import List

from app.errors import make_error
from app.ui_layer.commands.base import Command, CommandResult
from craftos_integrations import (
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

        # Integration-specific subcommands (login-qr, invite, ...) come from
        # the provider now that the metadata has moved off the handlers.
        meta = get_metadata(self._integration_name) or {}
        extras = [
            sub
            for sub in meta.get("subcommands", [])
            if sub not in {"login", "logout", "status"}
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
        session_id: str | None = None,
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

        if subcommand == "invite":
            return await self._connect_shared(sub_args)
        if subcommand == "login":
            return await self._connect(sub_args)
        if subcommand == "login-qr":
            return await self._connect_interactive()
        if subcommand == "logout":
            return await self._disconnect()

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

    def _system(self):
        """The configured IntegrationSystem for this integration, or None."""
        from app.data.action.integrations._helpers import system_for

        return system_for(self._integration_name)

    async def _connect_shared(self, args: List[str]) -> CommandResult:
        """`invite` — connect through a shared application rather than the
        user's own credentials.

        Two shapes exist. Providers with a ``shared_credentials()`` hand back a
        token the deployment owns (Telegram's shared bot); everything else
        means shared-app OAuth (Slack, HubSpot), which is what `_connect` runs.
        """
        import asyncio

        from app.data.action.integrations._helpers import system_connect_token

        system = self._system()
        provider = system.registry.get(self._integration_name) if system else None
        shared = getattr(provider, "shared_credentials", None)
        credentials = shared() if callable(shared) else None
        if credentials is None:
            return await self._connect(args)

        success, message = await asyncio.to_thread(
            system_connect_token, system, self._integration_name, credentials
        )
        hint = getattr(provider, "shared_hint", "")
        if success and hint:
            message = "\n".join([message, hint])
        return CommandResult(success=success, message=message)

    async def _connect_interactive(self) -> CommandResult:
        """QR login. WhatsApp's QR panel lives in the settings page — the
        terminal cannot render or poll it, so point the user there rather than
        start a session nothing will finish."""
        if self._integration_name == "whatsapp_web":
            return CommandResult(
                success=False,
                message=(
                    "WhatsApp connects by scanning a QR code. Open Settings → "
                    "Integrations → WhatsApp and scan it from your phone."
                ),
            )
        return CommandResult(
            success=False,
            message=(
                f"No interactive connect flow is implemented for "
                f"{self._integration_name}."
            ),
        )

    async def _connect(self, args: List[str]) -> CommandResult:
        """Connect through the IntegrationSystem.

        Picks the auth path (token / oauth / interactive) from the provider's
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
                    import asyncio

                    from app.data.action.integrations._helpers import (
                        system_connect_token,
                    )

                    system = self._system()
                    if system is None:
                        return CommandResult(
                            success=False,
                            message=f"Unknown integration: {self._integration_name}",
                        )
                    success, message = await asyncio.to_thread(
                        system_connect_token,
                        system,
                        self._integration_name,
                        credentials,
                    )
                    return CommandResult(success=success, message=message)

                # No args provided — show required fields
                if fields:
                    field_list = ", ".join(f["label"] for f in fields)
                    return CommandResult(
                        success=False,
                        message=f"Usage: /{self._integration_name} connect <{field_list}>",
                    )

            # OAuth-based — add_account runs the provider's OAuth and stores
            # the result as an account (what the "invite" did, except
            # multi-account and without the credential file).
            if auth_type in ("oauth", "both"):
                system = self._system()
                if system is None:
                    return CommandResult(
                        success=False,
                        message=f"Unknown integration: {self._integration_name}",
                    )
                success, message, _accounts = await system.add_account(
                    self._integration_name
                )
                return CommandResult(success=success, message=message)

            # Interactive (QR code, etc.)
            if auth_type in ("interactive", "token_with_interactive"):
                return await self._connect_interactive()

            return CommandResult(
                success=False,
                message=f"Unsupported auth type '{auth_type}' for {self._integration_name}.",
            )
        except Exception as e:
            info = make_error(
                "CONNECTION_FAILED", target=self._integration_name, detail=str(e)
            )
            return CommandResult(success=False, message=info.message)

    async def _disconnect(self) -> CommandResult:
        """Remove every account through the IntegrationSystem."""
        try:
            import asyncio

            from app.data.action.integrations._helpers import system_disconnect

            system = self._system()
            if system is None:
                return CommandResult(
                    success=False,
                    message=f"Unknown integration: {self._integration_name}",
                )
            success, message = await asyncio.to_thread(
                system_disconnect, system, self._integration_name, None
            )
            return CommandResult(success=success, message=message)
        except Exception as e:
            return CommandResult(success=False, message=f"Disconnect failed: {e}")
