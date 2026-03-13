# -*- coding: utf-8 -*-
"""
Skill Loader Module

Handles discovery and parsing of SKILL.md files from the filesystem.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml

from agent_core.utils.logger import logger
from agent_core.core.impl.skill.config import Skill, SkillMetadata, SkillsConfig


class SkillLoader:
    """Loads and parses skill definitions from filesystem."""

    # Regex pattern to extract YAML frontmatter from SKILL.md
    FRONTMATTER_PATTERN = re.compile(
        r'^---\s*\n(.*?)\n---\s*\n(.*)$',
        re.DOTALL
    )

    @staticmethod
    def discover_skills(search_dirs: List[Path], config: Optional[SkillsConfig] = None) -> List[Skill]:
        """
        Find all valid skill directories and parse SKILL.md files.

        Args:
            search_dirs: List of directories to search for skills.
            config: Optional config to check enabled/disabled status.

        Returns:
            List of parsed Skill objects.
        """
        skills: Dict[str, Skill] = {}  # name -> Skill (later dirs override earlier)

        for search_dir in search_dirs:
            if not search_dir.exists():
                logger.debug(f"Skills directory does not exist: {search_dir}")
                continue

            # Look for skill directories (each contains SKILL.md)
            for skill_dir in search_dir.iterdir():
                if not skill_dir.is_dir():
                    continue

                skill_file = skill_dir / "SKILL.md"
                if not skill_file.exists():
                    continue

                try:
                    skill = SkillLoader.parse_skill_file(skill_file)

                    # Check if skill is enabled via config
                    if config and not config.is_skill_enabled(skill.name):
                        skill.enabled = False
                        logger.debug(f"Skill '{skill.name}' is disabled by config")

                    # Earlier directories have lower priority, later ones override
                    skills[skill.name] = skill
                    logger.debug(f"Loaded skill: {skill.name} from {skill_file}")

                except Exception as e:
                    logger.warning(f"Failed to parse skill at {skill_file}: {e}")
                    continue

        return list(skills.values())

    @staticmethod
    def parse_skill_file(skill_path: Path) -> Skill:
        """
        Parse a single SKILL.md file.

        Args:
            skill_path: Path to the SKILL.md file.

        Returns:
            Parsed Skill object.

        Raises:
            ValueError: If the file cannot be parsed.
        """
        skill_path = Path(skill_path)

        if not skill_path.exists():
            raise ValueError(f"Skill file does not exist: {skill_path}")

        content = skill_path.read_text(encoding="utf-8")

        # Parse frontmatter and instructions
        match = SkillLoader.FRONTMATTER_PATTERN.match(content)

        if not match:
            raise ValueError(f"Invalid SKILL.md format (missing frontmatter): {skill_path}")

        frontmatter_str = match.group(1)
        instructions = match.group(2).strip()

        # Parse YAML frontmatter
        try:
            frontmatter = yaml.safe_load(frontmatter_str)
            if not isinstance(frontmatter, dict):
                raise ValueError("Frontmatter must be a YAML dictionary")
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML frontmatter: {e}")

        # Validate required fields
        if "name" not in frontmatter:
            # Try to infer name from directory
            frontmatter["name"] = skill_path.parent.name

        if "description" not in frontmatter:
            # Try to extract description from first paragraph
            first_para = instructions.split("\n\n")[0] if instructions else ""
            # Remove markdown headers
            first_para = re.sub(r'^#+\s+.*\n', '', first_para).strip()
            frontmatter["description"] = first_para[:200] if first_para else "No description"

        # Create metadata
        metadata = SkillMetadata.from_dict(frontmatter)

        # Create skill
        return Skill(
            metadata=metadata,
            instructions=instructions,
            source_path=skill_path,
            directory=skill_path.parent,
            enabled=True,
        )

    @staticmethod
    def substitute_variables(instructions: str, arguments: str) -> str:
        """
        Replace variable placeholders in skill instructions.

        Supported variables:
        - $ARGUMENTS - Full argument string
        - $ARGUMENTS[N] - Positional argument (0-indexed)
        - $N - Shorthand for $ARGUMENTS[N]

        Args:
            instructions: The skill instructions with variable placeholders.
            arguments: The arguments string passed to the skill.

        Returns:
            Instructions with variables substituted.
        """
        if not arguments:
            arguments = ""

        # Split arguments
        args_list = arguments.split() if arguments.strip() else []

        result = instructions

        # Replace $ARGUMENTS[N] first (more specific)
        def replace_indexed(match):
            index = int(match.group(1))
            if index < len(args_list):
                return args_list[index]
            return ""  # Return empty if index out of range

        result = re.sub(r'\$ARGUMENTS\[(\d+)\]', replace_indexed, result)

        # Replace $N shorthand
        def replace_shorthand(match):
            index = int(match.group(1))
            if index < len(args_list):
                return args_list[index]
            return ""

        result = re.sub(r'\$(\d+)(?!\d)', replace_shorthand, result)

        # Replace $ARGUMENTS (full string) last
        result = result.replace('$ARGUMENTS', arguments)

        return result

    @staticmethod
    def get_skill_names_from_dir(skill_dir: Path) -> List[str]:
        """
        Get list of skill names from a directory without fully parsing.

        Args:
            skill_dir: Directory to scan for skills.

        Returns:
            List of skill directory names.
        """
        names = []
        if not skill_dir.exists():
            return names

        for item in skill_dir.iterdir():
            if item.is_dir() and (item / "SKILL.md").exists():
                names.append(item.name)

        return names
