# -*- coding: utf-8 -*-
"""
Skill Manager Module

Singleton manager for all skill lifecycle operations.
"""

from pathlib import Path
from typing import Dict, List, Optional, Any

from agent_core.utils.logger import logger
from agent_core.core.impl.skill.config import Skill, SkillsConfig
from agent_core.core.impl.skill.loader import SkillLoader


class SkillManager:
    """
    Singleton managing all skills lifecycle.

    Handles skill discovery, loading, and provides methods for
    skill selection and instruction retrieval.
    """

    _instance: Optional["SkillManager"] = None

    def __new__(cls) -> "SkillManager":
        """Ensure singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the skill manager (only runs once due to singleton)."""
        if getattr(self, "_initialized", False):
            return

        self._skills: Dict[str, Skill] = {}
        self._config: Optional[SkillsConfig] = None
        self._config_path: Optional[Path] = None
        self._initialized = True

    async def initialize(self, config_path: Optional[Path] = None) -> None:
        """
        Load configuration and discover skills.

        Args:
            config_path: Path to skills_config.json. If None, uses defaults.
        """
        self._config_path = config_path

        # Load configuration
        if config_path and Path(config_path).exists():
            try:
                self._config = SkillsConfig.load(config_path)
                logger.info(f"[SKILLS] Loaded config from {config_path}")
            except Exception as e:
                logger.warning(f"[SKILLS] Failed to load config: {e}, using defaults")
                self._config = SkillsConfig()
        else:
            self._config = SkillsConfig()

        # Discover skills
        if self._config.auto_load:
            await self._discover_skills()

    async def _discover_skills(self) -> None:
        """Discover and load all skills from configured directories."""
        search_dirs = self._config.get_search_directories()

        logger.info(f"[SKILLS] Searching for skills in: {search_dirs}")

        skills = SkillLoader.discover_skills(search_dirs, self._config)

        # Store skills by name
        self._skills.clear()
        for skill in skills:
            self._skills[skill.name] = skill

        logger.info(f"[SKILLS] Discovered {len(self._skills)} skills")

    def reload_skills(self) -> int:
        """
        Reload skills from disk synchronously.

        Returns:
            Number of skills loaded.
        """
        import asyncio
        asyncio.get_event_loop().run_until_complete(self._discover_skills())
        return len(self._skills)

    # ─────────────────────── Getters ───────────────────────

    def get_all_skills(self) -> List[Skill]:
        """Get all discovered skills."""
        return list(self._skills.values())

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get skill by name."""
        return self._skills.get(name)

    def get_enabled_skills(self) -> List[Skill]:
        """Get all enabled skills (for LLM selection)."""
        return [s for s in self._skills.values() if s.enabled]

    def get_user_invocable_skills(self) -> List[Skill]:
        """Get skills that users can invoke via /<name>."""
        return [
            s for s in self._skills.values()
            if s.enabled and s.metadata.user_invocable
        ]

    # ─────────────────────── Selection Helpers ───────────────────────

    def list_skills_for_selection(self) -> Dict[str, str]:
        """
        Format skills for LLM selection prompt.

        Returns:
            Dictionary mapping skill name to description.
        """
        return {
            skill.name: skill.description
            for skill in self.get_enabled_skills()
        }

    # Maximum tokens for skill instructions (approximate: ~4 chars per token)
    # This prevents skill instructions from overwhelming the context
    MAX_SKILL_INSTRUCTIONS_TOKENS = 2000

    def get_skill_instructions(self, skill_names: List[str], max_tokens: Optional[int] = None) -> str:
        """
        Get combined instructions for selected skills with token limit.

        Args:
            skill_names: List of skill names to get instructions for.
            max_tokens: Optional override for maximum tokens (default: MAX_SKILL_INSTRUCTIONS_TOKENS).

        Returns:
            Combined instructions string, truncated if exceeds token limit.
        """
        if not skill_names:
            return ""

        max_tokens = max_tokens or self.MAX_SKILL_INSTRUCTIONS_TOKENS
        # Approximate character limit (4 chars per token)
        max_chars = max_tokens * 4

        instructions_parts = []
        total_chars = 0

        for name in skill_names:
            skill = self.get_skill(name)
            if skill and skill.enabled:
                skill_text = f"## Skill: {skill.name}\n\n{skill.instructions}"

                # Check if adding this skill would exceed the limit
                if total_chars + len(skill_text) > max_chars:
                    # Truncate the skill instructions
                    remaining_chars = max_chars - total_chars - 50  # Leave room for truncation message
                    if remaining_chars > 100:  # Only add if we have meaningful space
                        truncated_text = skill_text[:remaining_chars]
                        # Find last complete sentence or paragraph
                        last_newline = truncated_text.rfind('\n\n')
                        if last_newline > remaining_chars // 2:
                            truncated_text = truncated_text[:last_newline]
                        instructions_parts.append(truncated_text + "\n\n[... instructions truncated due to length limit]")
                        logger.info(f"[SKILLS] Truncated instructions for skill '{name}' to fit token limit")
                    break
                else:
                    instructions_parts.append(skill_text)
                    total_chars += len(skill_text)

        return "\n\n---\n\n".join(instructions_parts)

    def get_skill_action_sets(self, skill_names: List[str]) -> List[str]:
        """
        Get action sets required by selected skills.

        Args:
            skill_names: List of skill names.

        Returns:
            Deduplicated list of action set names.
        """
        action_sets = set()

        for name in skill_names:
            skill = self.get_skill(name)
            if skill and skill.enabled:
                action_sets.update(skill.metadata.action_sets)

        return list(action_sets)

    # ─────────────────────── Management ───────────────────────

    def enable_skill(self, name: str) -> bool:
        """
        Enable a skill.

        Args:
            name: Skill name to enable.

        Returns:
            True if skill was found and enabled.
        """
        skill = self.get_skill(name)
        if skill:
            skill.enabled = True

            # Update config
            if self._config:
                if name in self._config.disabled_skills:
                    self._config.disabled_skills.remove(name)
                self._save_config()

            logger.info(f"[SKILLS] Enabled skill: {name}")
            return True
        return False

    def disable_skill(self, name: str) -> bool:
        """
        Disable a skill.

        Args:
            name: Skill name to disable.

        Returns:
            True if skill was found and disabled.
        """
        skill = self.get_skill(name)
        if skill:
            skill.enabled = False

            # Update config
            if self._config:
                if name not in self._config.disabled_skills:
                    self._config.disabled_skills.append(name)
                self._save_config()

            logger.info(f"[SKILLS] Disabled skill: {name}")
            return True
        return False

    def _save_config(self) -> None:
        """Save configuration to file if config_path is set."""
        if self._config and self._config_path:
            try:
                self._config.save(self._config_path)
            except Exception as e:
                logger.warning(f"[SKILLS] Failed to save config: {e}")

    # ─────────────────────── Status ───────────────────────

    def get_status(self) -> Dict[str, Any]:
        """
        Get current status of the skill system.

        Returns:
            Status dictionary with skill counts and details.
        """
        all_skills = self.get_all_skills()
        enabled_skills = self.get_enabled_skills()

        return {
            "total_skills": len(all_skills),
            "enabled_skills": len(enabled_skills),
            "skills": {
                skill.name: {
                    "enabled": skill.enabled,
                    "description": skill.description,
                    "action_sets": skill.metadata.action_sets,
                    "user_invocable": skill.metadata.user_invocable,
                    "source": str(skill.source_path),
                }
                for skill in all_skills
            },
            "search_dirs": [str(d) for d in (self._config.get_search_directories() if self._config else [])],
        }


# Global singleton instance
skill_manager = SkillManager()
