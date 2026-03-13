# -*- coding: utf-8 -*-
"""
Scheduler Types Module

Defines dataclasses for schedule expressions and scheduled tasks.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ScheduleExpression:
    """
    Parsed schedule expression.

    Supports five types:
    - "daily": Fire at a specific time every day
    - "weekly": Fire at a specific time on specific weekday(s)
    - "interval": Fire at regular intervals
    - "cron": Fire based on cron expression
    - "once": Fire once at a specific time (one-time scheduled task)
    """
    schedule_type: str  # "daily", "weekly", "interval", "cron", "once"
    raw_expression: str  # Original string (e.g., "every day at 7am")

    # For time-based schedules (daily, weekly)
    hour: Optional[int] = None  # 0-23
    minute: Optional[int] = 0   # 0-59

    # For weekly schedules
    weekday: Optional[int] = None  # 0=Monday, 6=Sunday

    # For interval-based schedules
    interval_seconds: Optional[float] = None

    # For cron schedules
    cron_expression: Optional[str] = None

    # For one-time schedules
    fire_at: Optional[float] = None  # Unix timestamp for when to fire

    def __post_init__(self):
        """Validate schedule expression."""
        valid_types = {"daily", "weekly", "interval", "cron", "once"}
        if self.schedule_type not in valid_types:
            raise ValueError(f"Invalid schedule_type: {self.schedule_type}. Must be one of {valid_types}")

        if self.schedule_type in ("daily", "weekly"):
            if self.hour is None:
                raise ValueError(f"hour is required for {self.schedule_type} schedules")
            if not (0 <= self.hour <= 23):
                raise ValueError(f"hour must be 0-23, got {self.hour}")
            if not (0 <= self.minute <= 59):
                raise ValueError(f"minute must be 0-59, got {self.minute}")

        if self.schedule_type == "weekly" and self.weekday is None:
            raise ValueError("weekday is required for weekly schedules")

        if self.schedule_type == "weekly" and self.weekday is not None:
            if not (0 <= self.weekday <= 6):
                raise ValueError(f"weekday must be 0-6 (Monday=0), got {self.weekday}")

        if self.schedule_type == "interval":
            if self.interval_seconds is None or self.interval_seconds <= 0:
                raise ValueError(f"interval_seconds must be positive, got {self.interval_seconds}")

        if self.schedule_type == "cron" and not self.cron_expression:
            raise ValueError("cron_expression is required for cron schedules")

        if self.schedule_type == "once":
            if self.fire_at is None:
                raise ValueError("fire_at is required for once schedules")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "schedule_type": self.schedule_type,
            "raw_expression": self.raw_expression,
            "hour": self.hour,
            "minute": self.minute,
            "weekday": self.weekday,
            "interval_seconds": self.interval_seconds,
            "cron_expression": self.cron_expression,
            "fire_at": self.fire_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduleExpression":
        """Create from dictionary."""
        return cls(
            schedule_type=data["schedule_type"],
            raw_expression=data["raw_expression"],
            hour=data.get("hour"),
            minute=data.get("minute", 0),
            weekday=data.get("weekday"),
            interval_seconds=data.get("interval_seconds"),
            cron_expression=data.get("cron_expression"),
            fire_at=data.get("fire_at"),
        )


@dataclass
class ScheduledTask:
    """
    Definition of a scheduled task.

    Contains both configuration (what to run and when) and runtime state
    (last run time, next scheduled time).
    """
    id: str                  # Unique identifier
    name: str                # Human-readable name
    instruction: str         # What the agent should do (task instruction)
    schedule: ScheduleExpression  # When to run

    # Configuration
    enabled: bool = True
    priority: int = 50       # Trigger priority (lower = higher priority)
    mode: str = "simple"     # Task mode: "simple" or "complex"
    recurring: bool = True   # True for recurring tasks, False for one-time immediate tasks
    action_sets: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)  # Extra trigger payload

    # Runtime state (not persisted to config)
    last_run: Optional[float] = None   # Unix timestamp of last run
    next_run: Optional[float] = None   # Unix timestamp of next scheduled run
    run_count: int = 0                 # Number of times this schedule has fired

    def __post_init__(self):
        """Validate scheduled task."""
        if not self.id:
            raise ValueError("id is required")
        if not self.name:
            raise ValueError("name is required")
        if self.mode not in ("simple", "complex"):
            raise ValueError(f"mode must be 'simple' or 'complex', got {self.mode}")

    def to_dict(self, include_runtime: bool = False) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Args:
            include_runtime: Include runtime state (last_run, next_run, run_count)
        """
        data = {
            "id": self.id,
            "name": self.name,
            "instruction": self.instruction,
            "schedule": self.schedule.raw_expression,  # Store raw expression for human readability
            "enabled": self.enabled,
            "priority": self.priority,
            "mode": self.mode,
            "recurring": self.recurring,
            "action_sets": self.action_sets,
            "skills": self.skills,
            "payload": self.payload,
        }

        if include_runtime:
            data["last_run"] = self.last_run
            data["next_run"] = self.next_run
            data["run_count"] = self.run_count

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any], parsed_schedule: ScheduleExpression) -> "ScheduledTask":
        """
        Create from dictionary.

        Args:
            data: Dictionary with task configuration
            parsed_schedule: Pre-parsed schedule expression
        """
        return cls(
            id=data["id"],
            name=data["name"],
            instruction=data.get("instruction", ""),
            schedule=parsed_schedule,
            enabled=data.get("enabled", True),
            priority=data.get("priority", 50),
            mode=data.get("mode", "simple"),
            recurring=data.get("recurring", True),
            action_sets=data.get("action_sets", []),
            skills=data.get("skills", []),
            payload=data.get("payload", {}),
            last_run=data.get("last_run"),
            next_run=data.get("next_run"),
            run_count=data.get("run_count", 0),
        )


@dataclass
class SchedulerConfig:
    """
    Global scheduler configuration.

    Loaded from scheduler_config.json.
    """
    enabled: bool = True
    schedules: List[ScheduledTask] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "enabled": self.enabled,
            "schedules": [s.to_dict(include_runtime=False) for s in self.schedules],
        }
