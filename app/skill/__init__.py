# -*- coding: utf-8 -*-
"""
Skill module - re-exports from agent_core.

All skill implementations are now in agent_core.
"""

# Re-export from agent_core
from agent_core import (
    Skill,
    SkillMetadata,
    SkillsConfig,
    SkillLoader,
    SkillManager,
    skill_manager,
)

__all__ = [
    "Skill",
    "SkillMetadata",
    "SkillsConfig",
    "SkillLoader",
    "SkillManager",
    "skill_manager",
]
