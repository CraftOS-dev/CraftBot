# -*- coding: utf-8 -*-
"""
Skill Configuration Module

Handles loading and validation of skill configurations.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from agent_core.utils.logger import logger


@dataclass
class SkillMetadata:
    """Metadata parsed from SKILL.md frontmatter."""

    name: str                                           # Required: Unique identifier
    description: str = ""                               # Required: Brief description for LLM selection
    argument_hint: str = ""                             # Usage hint for invocation
    user_invocable: bool = True                         # Can user invoke via /<name>?
    allowed_tools: List[str] = field(default_factory=list)    # Restrict available actions
    action_sets: List[str] = field(default_factory=list)      # Action sets to auto-include

    def __post_init__(self):
        """Validate metadata after initialization."""
        if not self.name:
            raise ValueError("Skill name is required")
        # Normalize name to lowercase with hyphens
        self.name = self.name.lower().replace("_", "-").strip()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillMetadata":
        """Create SkillMetadata from a dictionary (parsed YAML frontmatter)."""
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            argument_hint=data.get("argument-hint", data.get("argument_hint", "")),
            user_invocable=data.get("user-invocable", data.get("user_invocable", True)),
            allowed_tools=data.get("allowed-tools", data.get("allowed_tools", [])),
            action_sets=data.get("action-sets", data.get("action_sets", [])),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "argument-hint": self.argument_hint,
            "user-invocable": self.user_invocable,
            "allowed-tools": self.allowed_tools,
            "action-sets": self.action_sets,
        }


@dataclass
class Skill:
    """Full skill definition including instructions."""

    metadata: SkillMetadata
    instructions: str                                   # Markdown content after frontmatter
    source_path: Path                                   # Path to SKILL.md file
    directory: Path                                     # Skill directory (for supporting files)
    enabled: bool = True

    @property
    def name(self) -> str:
        """Get the skill name."""
        return self.metadata.name

    @property
    def description(self) -> str:
        """Get the skill description."""
        return self.metadata.description

    def get_supporting_file(self, relative_path: str) -> Optional[Path]:
        """
        Get path to a supporting file in the skill directory.

        Args:
            relative_path: Path relative to the skill directory.

        Returns:
            Absolute path to the file if it exists, None otherwise.
        """
        file_path = self.directory / relative_path
        if file_path.exists():
            return file_path
        return None

    def get_supporting_file_content(self, relative_path: str) -> Optional[str]:
        """
        Read content of a supporting file.

        Args:
            relative_path: Path relative to the skill directory.

        Returns:
            File content as string if exists, None otherwise.
        """
        file_path = self.get_supporting_file(relative_path)
        if file_path:
            try:
                return file_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to read supporting file {file_path}: {e}")
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "metadata": self.metadata.to_dict(),
            "instructions": self.instructions,
            "source_path": str(self.source_path),
            "directory": str(self.directory),
            "enabled": self.enabled,
        }


@dataclass
class SkillsConfig:
    """Skills configuration."""

    project_skills_dir: Path = field(default_factory=lambda: Path("skills"))
    auto_load: bool = True
    enabled_skills: List[str] = field(default_factory=list)
    disabled_skills: List[str] = field(default_factory=list)

    @classmethod
    def load(cls, config_path: Path) -> "SkillsConfig":
        """
        Load skills configuration from a JSON file.

        Args:
            config_path: Path to the configuration file.

        Returns:
            SkillsConfig instance.
        """
        config_path = Path(config_path)

        if not config_path.exists():
            logger.info(f"Skills config file not found: {config_path}, using defaults")
            return cls()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in skills config file: {e}")
            raise

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillsConfig":
        """Create SkillsConfig from a dictionary."""
        project_dir = data.get("project_skills_dir", "skills")
        project_path = Path(project_dir)

        return cls(
            project_skills_dir=project_path,
            auto_load=data.get("auto_load", True),
            enabled_skills=data.get("enabled_skills", []),
            disabled_skills=data.get("disabled_skills", []),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "auto_load": self.auto_load,
            "enabled_skills": self.enabled_skills,
            "disabled_skills": self.disabled_skills,
            "project_skills_dir": str(self.project_skills_dir),
        }

    def save(self, config_path: Path) -> None:
        """Save configuration to a JSON file."""
        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def is_skill_enabled(self, skill_name: str) -> bool:
        """
        Check if a skill is enabled.

        Logic:
        - If skill is in disabled_skills list, return False
        - If enabled_skills list is empty, all skills are enabled by default
        - If enabled_skills list has items, skill must be in the list
        """
        if skill_name in self.disabled_skills:
            return False
        if not self.enabled_skills:
            return True  # No whitelist = all enabled
        return skill_name in self.enabled_skills

    def get_search_directories(self) -> List[Path]:
        """
        Get list of directories to search for skills.

        Returns the project skills directory.
        """
        return [self.project_skills_dir]
