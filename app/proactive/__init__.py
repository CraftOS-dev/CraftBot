# -*- coding: utf-8 -*-
"""
Proactive task management module.

This module provides functionality for managing proactive tasks that the agent
can execute autonomously based on scheduled heartbeats.
"""

from .types import (
    ProactiveTask,
    ProactiveData,
    ProactiveCondition,
    ProactiveOutcome,
)
from .parser import (
    ProactiveParser,
    validate_yaml_block,
)
from .manager import (
    ProactiveManager,
    get_proactive_manager,
    initialize_proactive_manager,
)

__all__ = [
    # Types
    "ProactiveTask",
    "ProactiveData",
    "ProactiveCondition",
    "ProactiveOutcome",
    # Parser
    "ProactiveParser",
    "validate_yaml_block",
    # Manager
    "ProactiveManager",
    "get_proactive_manager",
    "initialize_proactive_manager",
]
