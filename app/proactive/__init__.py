# -*- coding: utf-8 -*-
"""
Proactive task management module.

This module provides functionality for managing recurring tasks that the agent
can execute autonomously based on scheduled heartbeats.
"""

from .types import (
    RecurringTask,
    RecurringData,
    RecurringCondition,
    RecurringOutcome,
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
    # Types (Recurring Task classes)
    "RecurringTask",
    "RecurringData",
    "RecurringCondition",
    "RecurringOutcome",
    # Parser (Proactive framework)
    "ProactiveParser",
    "validate_yaml_block",
    # Manager (Proactive framework)
    "ProactiveManager",
    "get_proactive_manager",
    "initialize_proactive_manager",
]
