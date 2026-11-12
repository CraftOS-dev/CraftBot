# -*- coding: utf-8 -*-
"""
Proactive module.

Manages PROACTIVE.md: the cron jobs the scheduler runs at their set times,
and the checklist the heartbeat reads on every tick.
"""

from .types import (
    CronJob,
    ProactiveData,
    CronJobCondition,
    CronJobOutcome,
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
    "CronJob",
    "ProactiveData",
    "CronJobCondition",
    "CronJobOutcome",
    # Parser
    "ProactiveParser",
    "validate_yaml_block",
    # Manager
    "ProactiveManager",
    "get_proactive_manager",
    "initialize_proactive_manager",
]
