# -*- coding: utf-8 -*-
"""
Skill System Module

Provides skill management for agents, including:
- SkillConfig: Configuration dataclasses
- SkillLoader: SKILL.md parsing
- SkillManager: Singleton for skill lifecycle management
"""

from agent_core.core.impl.skill.config import (
    Skill,
    SkillMetadata,
    SkillsConfig,
)
from agent_core.core.impl.skill.loader import SkillLoader
from agent_core.core.impl.skill.manager import (
    SkillManager,
    skill_manager,
)

__all__ = [
    # Config
    "Skill",
    "SkillMetadata",
    "SkillsConfig",
    # Loader
    "SkillLoader",
    # Manager
    "SkillManager",
    "skill_manager",
]
