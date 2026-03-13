# -*- coding: utf-8 -*-
"""
Data types for recurring task management.

This module defines dataclasses for recurring tasks, conditions, and outcomes.
"""

from dataclasses import dataclass, field
from datetime import datetime
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
        return {
            "type": self.type,
            **self.params
        }

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
            "success": self.success
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
            success=data.get("success", True)
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

    def should_run(self, current_frequency: str) -> bool:
        """Check if this task should run for the given frequency.

        Args:
            current_frequency: The frequency being processed (hourly, daily, etc.)

        Returns:
            True if the task should run, False otherwise.
        """
        if not self.enabled:
            return False
        if self.frequency != current_frequency:
            return False
        # Conditions are checked by the heartbeat processor
        return True

    def add_outcome(
        self,
        result: str,
        success: bool = True
    ) -> None:
        """Add an execution outcome to history.

        Args:
            result: Description of the outcome
            success: Whether execution was successful
        """
        outcome = RecurringOutcome(
            timestamp=datetime.now(),
            result=result,
            success=success
        )
        self.outcome_history.append(outcome)

        # Keep only the last N outcomes
        if len(self.outcome_history) > self.MAX_OUTCOME_HISTORY:
            self.outcome_history = self.outcome_history[-self.MAX_OUTCOME_HISTORY:]

        # Update run metadata
        self.last_run = outcome.timestamp
        self.run_count += 1

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

    def update_task(self, task_id: str, updates: Dict[str, Any]) -> Optional[RecurringTask]:
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
