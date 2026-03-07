"""Skill command implementation."""

from __future__ import annotations

from typing import List

from app.ui_layer.commands.base import Command, CommandResult
from app.ui_layer.settings import (
    list_skills,
    get_skill_info,
    enable_skill,
    disable_skill,
    reload_skills,
    get_skill_search_directories,
    install_skill_from_path,
    install_skill_from_git,
    create_skill_scaffold,
    remove_skill,
)


class SkillCommand(Command):
    """Manage agent skills."""

    @property
    def name(self) -> str:
        return "/skill"

    @property
    def description(self) -> str:
        return "Manage agent skills"

    @property
    def usage(self) -> str:
        return "/skill <subcommand> [args]"

    @property
    def help_text(self) -> str:
        return """Manage agent skills (action packages).

Subcommands:
  list                    - List discovered skills
  info <name>             - Show skill details
  enable <name>           - Enable a skill
  disable <name>          - Disable a skill
  install <path>          - Install from local path
  install <git-url>       - Install from GitHub/GitLab
  create <name> [desc]    - Create skill scaffold
  remove <name>           - Remove a skill
  reload                  - Reload skills from disk
  dirs                    - Show skill search directories

Examples:
  /skill list
  /skill info web_search
  /skill enable web_search
  /skill install ./my_skill
  /skill install https://github.com/user/skill.git
  /skill create my_skill "My custom skill"
  /skill remove my_skill"""

    async def execute(
        self,
        args: List[str],
        adapter_id: str = "",
    ) -> CommandResult:
        """Execute the skill command."""
        if not args:
            return await self._list_skills()

        subcommand = args[0].lower()
        sub_args = args[1:]

        handlers = {
            "list": self._list_skills,
            "info": lambda: self._skill_info(sub_args),
            "enable": lambda: self._enable_skill(sub_args),
            "disable": lambda: self._disable_skill(sub_args),
            "install": lambda: self._install_skill(sub_args),
            "create": lambda: self._create_skill(sub_args),
            "remove": lambda: self._remove_skill(sub_args),
            "reload": self._reload_skills,
            "dirs": self._show_dirs,
        }

        handler = handlers.get(subcommand)
        if handler:
            return await handler()

        return CommandResult(
            success=False,
            message=f"Unknown subcommand: {subcommand}\nUse /help skill for usage.",
        )

    async def _list_skills(self) -> CommandResult:
        """List all discovered skills."""
        skills = list_skills()
        if not skills:
            return CommandResult(
                success=True,
                message="No skills discovered. Use /skill dirs to see search paths.",
            )

        lines = ["Discovered skills:", ""]
        for skill in skills:
            status = "enabled" if skill.get("enabled", True) else "disabled"
            name = skill.get("name", "unknown")
            desc = skill.get("description", "")[:50]
            lines.append(f"  {name} [{status}] - {desc}")

        return CommandResult(success=True, message="\n".join(lines))

    async def _skill_info(self, args: List[str]) -> CommandResult:
        """Show skill details."""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /skill info <name>",
            )

        name = args[0]
        info = get_skill_info(name)
        if not info:
            return CommandResult(
                success=False,
                message=f"Skill not found: {name}",
            )

        lines = [
            f"Skill: {info.get('name', name)}",
            f"Description: {info.get('description', 'N/A')}",
            f"Version: {info.get('version', 'N/A')}",
            f"Author: {info.get('author', 'N/A')}",
            f"Enabled: {info.get('enabled', True)}",
            f"Path: {info.get('path', 'N/A')}",
        ]

        actions = info.get("actions", [])
        if actions:
            lines.append(f"\nActions ({len(actions)}):")
            for action in actions[:10]:  # Show first 10
                lines.append(f"  - {action}")
            if len(actions) > 10:
                lines.append(f"  ... and {len(actions) - 10} more")

        return CommandResult(success=True, message="\n".join(lines))

    async def _enable_skill(self, args: List[str]) -> CommandResult:
        """Enable a skill."""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /skill enable <name>",
            )

        name = args[0]
        result = enable_skill(name)
        if result.get("success"):
            return CommandResult(
                success=True,
                message=f"Enabled skill: {name}",
            )
        return CommandResult(
            success=False,
            message=result.get("error", f"Failed to enable skill: {name}"),
        )

    async def _disable_skill(self, args: List[str]) -> CommandResult:
        """Disable a skill."""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /skill disable <name>",
            )

        name = args[0]
        result = disable_skill(name)
        if result.get("success"):
            return CommandResult(
                success=True,
                message=f"Disabled skill: {name}",
            )
        return CommandResult(
            success=False,
            message=result.get("error", f"Failed to disable skill: {name}"),
        )

    async def _install_skill(self, args: List[str]) -> CommandResult:
        """Install a skill from path or git URL."""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /skill install <path_or_url>",
            )

        source = args[0]

        # Check if it's a git URL
        if source.startswith("http") or source.startswith("git@"):
            result = install_skill_from_git(source)
        else:
            result = install_skill_from_path(source)

        if result.get("success"):
            return CommandResult(
                success=True,
                message=f"Installed skill from: {source}",
            )
        return CommandResult(
            success=False,
            message=result.get("error", f"Failed to install skill from: {source}"),
        )

    async def _create_skill(self, args: List[str]) -> CommandResult:
        """Create a new skill scaffold."""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /skill create <name> [description]",
            )

        name = args[0]
        description = " ".join(args[1:]) if len(args) > 1 else ""

        result = create_skill_scaffold(name, description)
        if result.get("success"):
            path = result.get("path", "")
            return CommandResult(
                success=True,
                message=f"Created skill scaffold: {name}\nPath: {path}",
            )
        return CommandResult(
            success=False,
            message=result.get("error", f"Failed to create skill: {name}"),
        )

    async def _remove_skill(self, args: List[str]) -> CommandResult:
        """Remove a skill."""
        if not args:
            return CommandResult(
                success=False,
                message="Usage: /skill remove <name>",
            )

        name = args[0]
        result = remove_skill(name)
        if result.get("success"):
            return CommandResult(
                success=True,
                message=f"Removed skill: {name}",
            )
        return CommandResult(
            success=False,
            message=result.get("error", f"Failed to remove skill: {name}"),
        )

    async def _reload_skills(self) -> CommandResult:
        """Reload skills from disk."""
        result = reload_skills()
        if result.get("success"):
            count = result.get("count", 0)
            return CommandResult(
                success=True,
                message=f"Reloaded {count} skills from disk.",
            )
        return CommandResult(
            success=False,
            message=result.get("error", "Failed to reload skills"),
        )

    async def _show_dirs(self) -> CommandResult:
        """Show skill search directories."""
        dirs = get_skill_search_directories()
        if not dirs:
            return CommandResult(
                success=True,
                message="No skill search directories configured.",
            )

        lines = ["Skill search directories:", ""]
        for d in dirs:
            lines.append(f"  {d}")

        return CommandResult(success=True, message="\n".join(lines))
