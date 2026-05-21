# -*- coding: utf-8 -*-
"""
Data types for recurring task management.

This module defines dataclasses for recurring tasks, conditions, and outcomes.
"""

from dataclasses import dataclass, field
import calendar
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


@dataclass
class RecurringCondition:
    """Condition for recurring task execution.

    Attributes:
        type: Condition type (e.g., "market_hours_only", "user_available")
        params: Additional parameters for the condition
    """

    type: str
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {"type": self.type, **self.params}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecurringCondition":
        """Create from dictionary."""
        condition_type = data.pop("type", "unknown")
        return cls(type=condition_type, params=data)


@dataclass
class RecurringOutcome:
    """Record of a recurring task execution.

    Attributes:
        timestamp: When the task was executed
        result: Description of the outcome
        success: Whether the execution was successful
    """

    timestamp: datetime
    result: str
    success: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "result": self.result,
            "success": self.success,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecurringOutcome":
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        elif timestamp is None:
            timestamp = datetime.now()

        return cls(
            timestamp=timestamp,
            result=data.get("result", ""),
            success=data.get("success", True),
        )


@dataclass
class RecurringTask:
    """Definition of a recurring task.

    Attributes:
        id: Unique identifier for the task
        name: Human-readable task name
        frequency: Execution frequency (hourly, daily, weekly, monthly)
        instruction: What the agent should do
        enabled: Whether the task is active
        priority: Task priority (lower = higher priority)
        permission_tier: Permission level (0-3)
        time: Time of day for daily+ tasks (HH:MM format)
        day: Day of week for weekly tasks (e.g., "sunday")
        conditions: List of conditions that must be met
        last_run: Timestamp of last execution
        next_run: Timestamp of next scheduled execution
        run_count: Number of times the task has been executed
        outcome_history: Recent execution outcomes (limited to last 5)
    """

    id: str
    name: str
    frequency: str  # hourly, daily, weekly, monthly
    instruction: str
    enabled: bool = True
    priority: int = 50
    permission_tier: int = 0
    time: Optional[str] = None  # HH:MM for daily+
    day: Optional[str] = None  # For weekly (e.g., "sunday")
    conditions: List[RecurringCondition] = field(default_factory=list)
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    outcome_history: List[RecurringOutcome] = field(default_factory=list)

    MAX_OUTCOME_HISTORY = 5

    # Grace period: tasks must be picked up within this window after their
    # scheduled time, otherwise the run is skipped until the next period.
    # Set to 30 minutes to match the heartbeat interval (fires at :00 and :30).
    GRACE_PERIOD = timedelta(minutes=30)

    def should_run(self, current_frequency: str = "") -> bool:
        """Check if this task should run.

        When ``current_frequency`` is given, only tasks matching that exact
        frequency are considered (legacy per-frequency heartbeat behaviour).
        When empty or ``"all"``, the method checks the task's own frequency
        against the current date/time to decide if it is due.

        Tasks with a scheduled time have a 30-minute grace period. If the
        heartbeat fires more than 30 minutes after the target time, the run
        is skipped until the next period (no catch-up runs).

        Args:
            current_frequency: The frequency being processed, or "" / "all"
                               to check all frequencies against current time.

        Returns:
            True if the task should run, False otherwise.
        """
        if not self.enabled:
            return False

        # Legacy per-frequency filter
        if current_frequency and current_frequency != "all":
            return self.frequency == current_frequency

        # Unified heartbeat: check if this task is due right now
        now = datetime.now()

        if self.frequency == "hourly":
            # Hourly tasks are always due on every heartbeat
            return True

        if self.frequency == "daily":
            # Check if already ran today
            if self.last_run and self.last_run.date() == now.date():
                return False
            # Daily tasks: check time field if present
            if self.time:
                task_hour, task_minute = (int(p) for p in self.time.split(":"))
                target_time = now.replace(
                    hour=task_hour, minute=task_minute, second=0, microsecond=0
                )
                if now < target_time:
                    return False  # Too early
                if now > target_time + self.GRACE_PERIOD:
                    return False  # Missed the window, skip until tomorrow
            return True

        if self.frequency == "weekly":
            # Check if already ran this week
            if (
                self.last_run
                and self.last_run.isocalendar()[1] == now.isocalendar()[1]
                and self.last_run.year == now.year
            ):
                return False
            # Weekly tasks: check day field
            if self.day:
                today_name = now.strftime("%A").lower()
                if today_name != self.day.lower():
                    return False
            # Check time if present
            if self.time:
                task_hour, task_minute = (int(p) for p in self.time.split(":"))
                target_time = now.replace(
                    hour=task_hour, minute=task_minute, second=0, microsecond=0
                )
                if now < target_time:
                    return False
                if now > target_time + self.GRACE_PERIOD:
                    return False  # Missed the window, skip until next week
            return True

        if self.frequency == "monthly":
            # Check if already ran this month
            if (
                self.last_run
                and self.last_run.month == now.month
                and self.last_run.year == now.year
            ):
                return False
            # Monthly tasks: check day field (day of month)
            if self.day:
                try:
                    target_day = int(self.day)
                    if now.day != target_day:
                        return False
                except ValueError:
                    pass  # Non-numeric day, skip check
            # Check time if present
            if self.time:
                task_hour, task_minute = (int(p) for p in self.time.split(":"))
                target_time = now.replace(
                    hour=task_hour, minute=task_minute, second=0, microsecond=0
                )
                if now < target_time:
                    return False
                if now > target_time + self.GRACE_PERIOD:
                    return False  # Missed the window, skip until next month
            return True

        return False

    @staticmethod
    def _next_heartbeat(dt: datetime) -> datetime:
        """Snap a datetime to the next clock-aligned heartbeat slot (:00 or :30).

        Heartbeats fire at fixed 30-minute intervals aligned to the clock.
        """
        if dt.minute < 30:
            return dt.replace(minute=30, second=0, microsecond=0)
        return (dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

    def calculate_next_run(self) -> Optional[datetime]:
        """Calculate the next execution time for this task.

        Returns the next datetime when this task will actually execute,
        snapped to the next heartbeat slot (every 30 min at :00 and :30).
        Returns None for disabled tasks.
        """
        if not self.enabled:
            return None

        now = datetime.now()
        task_hour, task_minute = 0, 0
        if self.time:
            parts = self.time.split(":")
            task_hour, task_minute = int(parts[0]), int(parts[1])

        if self.frequency == "hourly":
            # Hourly tasks run on every heartbeat (every 30 min)
            return self._next_heartbeat(now)

        if self.frequency == "daily":
            today_at_time = now.replace(
                hour=task_hour, minute=task_minute, second=0, microsecond=0
            )
            if self.last_run and self.last_run.date() == now.date():
                # Already ran today — next is tomorrow
                return self._next_heartbeat(
                    today_at_time + timedelta(days=1) - timedelta(seconds=1)
                )
            if now < today_at_time:
                # Time hasn't passed yet — snap target time to heartbeat
                return self._next_heartbeat(today_at_time - timedelta(seconds=1))
            if self.time and now <= today_at_time + self.GRACE_PERIOD:
                # Within grace period — next heartbeat will pick it up
                return self._next_heartbeat(now)
            # Missed the window — skip to tomorrow
            return self._next_heartbeat(
                today_at_time + timedelta(days=1) - timedelta(seconds=1)
            )

        if self.frequency == "weekly":
            day_names = [
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ]
            target_day_name = (self.day or "monday").lower()
            target_weekday = (
                day_names.index(target_day_name) if target_day_name in day_names else 0
            )

            days_ahead = target_weekday - now.weekday()
            if days_ahead < 0:
                days_ahead += 7

            next_date = now + timedelta(days=days_ahead)
            next_time = next_date.replace(
                hour=task_hour, minute=task_minute, second=0, microsecond=0
            )

            if (
                self.last_run
                and self.last_run.isocalendar()[1] == now.isocalendar()[1]
                and self.last_run.year == now.year
            ):
                # Already ran this week — next week
                next_time = (
                    now + timedelta(days=(7 - now.weekday() + target_weekday))
                ).replace(hour=task_hour, minute=task_minute, second=0, microsecond=0)
                if next_time <= now:
                    next_time += timedelta(weeks=1)
                return self._next_heartbeat(next_time - timedelta(seconds=1))

            if next_time <= now:
                # Target time has passed this week
                if self.time and now <= next_time + self.GRACE_PERIOD:
                    # Within grace period
                    return self._next_heartbeat(now)
                # Missed the window — skip to next week
                next_time += timedelta(weeks=1)

            return self._next_heartbeat(next_time - timedelta(seconds=1))

        if self.frequency == "monthly":
            try:
                target_day = int(self.day) if self.day else 1
            except ValueError:
                target_day = 1

            max_day = calendar.monthrange(now.year, now.month)[1]
            clamped_day = min(target_day, max_day)
            this_month_time = now.replace(
                day=clamped_day,
                hour=task_hour,
                minute=task_minute,
                second=0,
                microsecond=0,
            )

            if (
                self.last_run
                and self.last_run.month == now.month
                and self.last_run.year == now.year
            ):
                # Already ran this month — go to next month
                if now.month == 12:
                    ny, nm = now.year + 1, 1
                else:
                    ny, nm = now.year, now.month + 1
                clamped = min(target_day, calendar.monthrange(ny, nm)[1])
                target = now.replace(
                    year=ny,
                    month=nm,
                    day=clamped,
                    hour=task_hour,
                    minute=task_minute,
                    second=0,
                    microsecond=0,
                )
                return self._next_heartbeat(target - timedelta(seconds=1))

            if now < this_month_time:
                return self._next_heartbeat(this_month_time - timedelta(seconds=1))

            if self.time and now <= this_month_time + self.GRACE_PERIOD:
                # Within grace period
                return self._next_heartbeat(now)

            # Missed the window — skip to next month
            if now.month == 12:
                ny, nm = now.year + 1, 1
            else:
                ny, nm = now.year, now.month + 1
            clamped = min(target_day, calendar.monthrange(ny, nm)[1])
            target = now.replace(
                year=ny,
                month=nm,
                day=clamped,
                hour=task_hour,
                minute=task_minute,
                second=0,
                microsecond=0,
            )
            return self._next_heartbeat(target - timedelta(seconds=1))

        return None

    def add_outcome(self, result: str, success: bool = True) -> None:
        """Add an execution outcome to history.

        Args:
            result: Description of the outcome
            success: Whether execution was successful
        """
        outcome = RecurringOutcome(
            timestamp=datetime.now(), result=result, success=success
        )
        self.outcome_history.append(outcome)

        # Keep only the last N outcomes
        if len(self.outcome_history) > self.MAX_OUTCOME_HISTORY:
            self.outcome_history = self.outcome_history[-self.MAX_OUTCOME_HISTORY :]

        # Update run metadata
        self.last_run = outcome.timestamp
        self.run_count += 1
        self.next_run = self.calculate_next_run()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        data = {
            "id": self.id,
            "frequency": self.frequency,
            "enabled": self.enabled,
            "priority": self.priority,
            "permission_tier": self.permission_tier,
            "run_count": self.run_count,
            "instruction": self.instruction,
        }

        if self.time:
            data["time"] = self.time
        if self.day:
            data["day"] = self.day
        if self.conditions:
            data["conditions"] = [c.to_dict() for c in self.conditions]
        else:
            data["conditions"] = []
        if self.last_run:
            data["last_run"] = self.last_run.isoformat()
        if self.next_run:
            data["next_run"] = self.next_run.isoformat()
        if self.outcome_history:
            data["outcome_history"] = [o.to_dict() for o in self.outcome_history]
        else:
            data["outcome_history"] = []

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any], name: str = "") -> "RecurringTask":
        """Create from dictionary (parsed from YAML).

        Args:
            data: Dictionary with task data
            name: Task name (from section header)

        Returns:
            RecurringTask instance
        """
        # Parse datetime fields
        last_run = data.get("last_run")
        if isinstance(last_run, str):
            last_run = datetime.fromisoformat(last_run.replace("Z", "+00:00"))

        next_run = data.get("next_run")
        if isinstance(next_run, str):
            next_run = datetime.fromisoformat(next_run.replace("Z", "+00:00"))

        # Parse conditions
        conditions = []
        for c in data.get("conditions", []):
            if isinstance(c, dict):
                conditions.append(RecurringCondition.from_dict(c.copy()))

        # Parse outcome history
        outcomes = []
        for o in data.get("outcome_history", []):
            if isinstance(o, dict):
                outcomes.append(RecurringOutcome.from_dict(o))

        return cls(
            id=data.get("id", ""),
            name=name,
            frequency=data.get("frequency", "daily"),
            instruction=data.get("instruction", ""),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 50),
            permission_tier=data.get("permission_tier", 0),
            time=data.get("time"),
            day=data.get("day"),
            conditions=conditions,
            last_run=last_run,
            next_run=next_run,
            run_count=data.get("run_count", 0),
            outcome_history=outcomes,
        )


@dataclass
class RecurringData:
    """Container for all recurring task data from PROACTIVE.md.

    Attributes:
        version: Format version
        last_updated: When the file was last updated
        tasks: List of recurring tasks
        planner_outputs: DEPRECATED - planners now update "Goals, Plan, and Status" section
                        via file operations. This field is kept for backward compatibility.
    """

    version: str = "1.0"
    last_updated: Optional[datetime] = None
    tasks: List[RecurringTask] = field(default_factory=list)
    planner_outputs: Dict[str, str] = field(default_factory=dict)  # Deprecated

    def get_tasks_by_frequency(self, frequency: str) -> List[RecurringTask]:
        """Get all tasks for a specific frequency.

        Args:
            frequency: The frequency to filter by (hourly, daily, weekly, monthly)

        Returns:
            List of tasks matching the frequency
        """
        return [t for t in self.tasks if t.frequency == frequency]

    def get_enabled_tasks(self, frequency: Optional[str] = None) -> List[RecurringTask]:
        """Get all enabled tasks, optionally filtered by frequency.

        Args:
            frequency: Optional frequency filter

        Returns:
            List of enabled tasks
        """
        tasks = [t for t in self.tasks if t.enabled]
        if frequency:
            tasks = [t for t in tasks if t.frequency == frequency]
        return tasks

    def get_task_by_id(self, task_id: str) -> Optional[RecurringTask]:
        """Find a task by its ID.

        Args:
            task_id: The task ID to find

        Returns:
            The task if found, None otherwise
        """
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def add_task(self, task: RecurringTask) -> None:
        """Add a new task.

        Args:
            task: The task to add

        Raises:
            ValueError: If a task with the same ID already exists
        """
        if self.get_task_by_id(task.id):
            raise ValueError(f"Task with ID '{task.id}' already exists")
        self.tasks.append(task)
        self.last_updated = datetime.now()

    def remove_task(self, task_id: str) -> bool:
        """Remove a task by ID.

        Args:
            task_id: The ID of the task to remove

        Returns:
            True if the task was removed, False if not found
        """
        for i, task in enumerate(self.tasks):
            if task.id == task_id:
                self.tasks.pop(i)
                self.last_updated = datetime.now()
                return True
        return False

    def update_task(
        self, task_id: str, updates: Dict[str, Any]
    ) -> Optional[RecurringTask]:
        """Update a task with new values.

        Args:
            task_id: The ID of the task to update
            updates: Dictionary of fields to update

        Returns:
            The updated task if found, None otherwise
        """
        task = self.get_task_by_id(task_id)
        if not task:
            return None

        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)

        self.last_updated = datetime.now()
        return task
