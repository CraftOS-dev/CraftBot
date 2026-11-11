# -*- coding: utf-8 -*-
"""
Scheduler Module

Provides scheduling capabilities for agent tasks.

Usage:
    from app.scheduler import SchedulerManager, ScheduleParser

    scheduler = SchedulerManager()
    await scheduler.initialize(config_path, trigger_service=trigger_service)
    await scheduler.start()

    # Add a schedule programmatically
    scheduler.add_schedule(
        name="Daily Report",
        instruction="Generate and send daily report",
        schedule_expression="every day at 9am",
    )
"""

from .types import ScheduleExpression, ScheduledTask, SchedulerConfig
from .parser import ScheduleParser, ScheduleParseError
from .manager import SchedulerManager
from .background import BackgroundRun, background_runs

__all__ = [
    # Types
    "ScheduleExpression",
    "ScheduledTask",
    "SchedulerConfig",
    # Parser
    "ScheduleParser",
    "ScheduleParseError",
    # Manager
    "SchedulerManager",
    # Background run ledger
    "BackgroundRun",
    "background_runs",
]
