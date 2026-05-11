"""Clear-tasks command implementation."""

from __future__ import annotations

from typing import List

from app.ui_layer.commands.base import Command, CommandResult


class ClearTasksCommand(Command):
    """Clear finished tasks (completed/failed/aborted) from the action panel."""

    @property
    def name(self) -> str:
        return "/clear-tasks"

    @property
    def aliases(self) -> List[str]:
        return ["/cleartasks"]

    @property
    def description(self) -> str:
        return "Remove completed, failed, and aborted tasks from the panel"

    @property
    def help_text(self) -> str:
        return (
            "Remove tasks whose status is completed, error, or cancelled "
            "(failed/aborted) from the action panel, along with their child "
            "actions. Running and waiting tasks are preserved.\n\n"
            "Dashboard usage data and task history are not affected."
        )

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
    ) -> CommandResult:
        """Execute the clear-tasks command."""
        adapter = self._controller.active_adapter
        if not adapter or not adapter.action_panel:
            self.emit_message(
                "No action panel is available in this interface.",
                "error",
            )
            return CommandResult(success=False)

        removed = await adapter.action_panel.clear_terminal_tasks()

        if removed:
            self.emit_message(
                f"Cleared {removed} finished task{'s' if removed != 1 else ''} from the panel.",
                "system",
            )
        else:
            self.emit_message("No finished tasks to clear.", "system")

        return CommandResult(success=True)
