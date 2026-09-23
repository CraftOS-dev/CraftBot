"""Update command implementation."""

from __future__ import annotations

import asyncio
from typing import List

from app.i18n import tui
from app.ui_layer.commands.base import Command, CommandResult


class UpdateCommand(Command):
    """Check for updates and update CraftBot to the latest version."""

    @property
    def name(self) -> str:
        return "/update"

    @property
    def aliases(self) -> List[str]:
        return ["/upgrade"]

    @property
    def description(self) -> str:
        return "Check for updates and update CraftBot to the latest version"

    @property
    def usage(self) -> str:
        return "/update [--check]"

    @property
    def help_text(self) -> str:
        return """Check for and install CraftBot updates from GitHub.

Usage:
  /update          Check for updates and install if available
  /update --check  Only check for updates without installing

This will pull the latest code from the main branch, install
dependencies, and restart CraftBot automatically."""

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
        session_id: str | None = None,
    ) -> CommandResult:
        """Execute the update command."""
        from app.updater import UPDATE_BRANCH, check_for_update

        self.emit_message(
            tui("update_checking"), "system", session_id=session_id
        )

        try:
            status = await check_for_update()
        except Exception as e:
            self.emit_message(
                tui("update_check_failed", error=str(e)),
                "error",
                session_id=session_id,
            )
            return CommandResult(success=False, message=str(e))

        current, latest = status.current, status.latest

        if not status.available:
            if status.branch:
                self.emit_message(
                    tui(
                        "update_off_branch",
                        branch=status.branch,
                        current=current,
                        update_branch=UPDATE_BRANCH,
                    ),
                    "system",
                    session_id=session_id,
                )
            else:
                self.emit_message(
                    tui("update_up_to_date", current=current),
                    "system",
                    session_id=session_id,
                )
            return CommandResult(success=True)

        # --check flag: report only, don't install
        if "--check" in args:
            self.emit_message(
                tui("update_available", current=current, latest=latest),
                "system",
                session_id=session_id,
            )
            return CommandResult(
                success=True,
                data={"updateAvailable": True, "current": current, "latest": latest},
            )

        # Perform the update in the background so the command returns immediately
        self.emit_message(
            tui("update_available_starting", current=current, latest=latest),
            "system",
            session_id=session_id,
        )
        asyncio.create_task(self._do_update(session_id))
        return CommandResult(success=True)

    async def _do_update(self, session_id: str | None = None) -> None:
        """Run the actual update via app.updater."""
        from app.updater import perform_update

        async def progress(msg: str) -> None:
            self.emit_message(msg, "system", session_id=session_id)

        try:
            await perform_update(progress_callback=progress)
        except Exception as e:
            self.emit_message(
                tui("update_failed", error=str(e)), "error", session_id=session_id
            )
