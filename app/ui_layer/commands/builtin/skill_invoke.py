"""Skill invocation command - allows invoking skills as slash commands."""

from __future__ import annotations

from typing import List, TYPE_CHECKING

from app.ui_layer.commands.base import Command, CommandResult

if TYPE_CHECKING:
    from app.ui_layer.controller.ui_controller import UIController


class SkillInvokeCommand(Command):
    """
    Wraps a single skill as a slash command.

    When a user types /<skill-name> [args], this command invokes the
    skill by routing the message through the agent with the skill
    pre-selected. If no args are provided, the agent will ask the
    user for further requirements if the skill requires context.
    """

    def __init__(
        self,
        controller: "UIController",
        skill_name: str,
        skill_description: str,
        argument_hint: str = "",
    ) -> None:
        super().__init__(controller)
        self._skill_name = skill_name
        self._skill_description = skill_description
        self._argument_hint = argument_hint

    @property
    def name(self) -> str:
        return f"/{self._skill_name}"

    @property
    def description(self) -> str:
        return self._skill_description

    @property
    def usage(self) -> str:
        if self._argument_hint:
            return f"/{self._skill_name} {self._argument_hint}"
        return f"/{self._skill_name} [description of what you want]"

    @property
    def help_text(self) -> str:
        return self._skill_description

    @property
    def hidden(self) -> bool:
        return True

    @property
    def requires_session(self) -> bool:
        # Skill invocations route into an agent turn; without a real session
        # the turn falls back to the main session (see _handle_chat_message),
        # so a draft must be committed to a real session first.
        return True

    @property
    def starts_run(self) -> bool:
        # invoke_skill() routes into _handle_chat_message, launching an agent
        # turn — the committed session should show the typing indicator.
        return True

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
        session_id: str | None = None,
    ) -> CommandResult:
        """Execute the skill invocation command."""
        args_text = " ".join(args).strip()
        await self._controller.invoke_skill(
            self._skill_name, args_text, adapter_id, session_id=session_id
        )
        # System message is emitted by invoke_skill() directly
        return CommandResult(success=True, message=None)
