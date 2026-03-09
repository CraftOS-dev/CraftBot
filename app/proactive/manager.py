# -*- coding: utf-8 -*-
"""
Proactive task manager.

This module provides the ProactiveManager class for managing proactive tasks
stored in PROACTIVE.md.
"""

import logging
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from .types import ProactiveTask, ProactiveData, ProactiveOutcome
from .parser import ProactiveParser

logger = logging.getLogger(__name__)


class ProactiveManager:
    """Manager for proactive tasks stored in PROACTIVE.md.

    Provides thread-safe operations for reading, adding, updating, and
    removing proactive tasks. Uses atomic file writes to prevent corruption.
    """

    def __init__(self, proactive_file_path: Path):
        """Initialize the manager.

        Args:
            proactive_file_path: Path to PROACTIVE.md file
        """
        self.file_path = proactive_file_path
        self._data: Optional[ProactiveData] = None
        self._template: Optional[str] = None

    def load(self) -> ProactiveData:
        """Load proactive data from file.

        Returns:
            ProactiveData object

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        if not self.file_path.exists():
            logger.warning(f"[PROACTIVE] File not found: {self.file_path}")
            self._data = ProactiveData()
            self._template = None
            return self._data

        content = self.file_path.read_text(encoding="utf-8")
        self._template = content
        self._data = ProactiveParser.parse(content)
        logger.info(f"[PROACTIVE] Loaded {len(self._data.tasks)} tasks from {self.file_path}")
        return self._data

    def save(self) -> None:
        """Save proactive data to file atomically.

        Uses atomic write (write to temp file, then rename) to prevent corruption.
        """
        if self._data is None:
            raise RuntimeError("No data loaded. Call load() first.")

        self._data.last_updated = datetime.now()
        content = ProactiveParser.serialize(self._data, self._template)

        # Atomic write
        temp_path = None
        try:
            # Write to temporary file first
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                suffix='.md',
                delete=False,
                dir=self.file_path.parent
            ) as f:
                f.write(content)
                temp_path = Path(f.name)

            # Atomic rename
            shutil.move(str(temp_path), str(self.file_path))
            logger.info(f"[PROACTIVE] Saved {len(self._data.tasks)} tasks to {self.file_path}")

        except Exception as e:
            # Clean up temp file on error
            if temp_path and temp_path.exists():
                temp_path.unlink()
            logger.error(f"[PROACTIVE] Failed to save: {e}")
            raise

    @property
    def data(self) -> ProactiveData:
        """Get loaded data, loading from file if necessary."""
        if self._data is None:
            self.load()
        return self._data

    def get_tasks(
        self,
        frequency: Optional[str] = None,
        enabled_only: bool = True
    ) -> List[ProactiveTask]:
        """Get tasks, optionally filtered.

        Args:
            frequency: Filter by frequency (hourly, daily, weekly, monthly)
            enabled_only: Only return enabled tasks

        Returns:
            List of matching tasks
        """
        tasks = self.data.tasks

        if enabled_only:
            tasks = [t for t in tasks if t.enabled]

        if frequency:
            tasks = [t for t in tasks if t.frequency == frequency]

        return tasks

    def get_task(self, task_id: str) -> Optional[ProactiveTask]:
        """Get a task by ID.

        Args:
            task_id: The task ID

        Returns:
            The task if found, None otherwise
        """
        return self.data.get_task_by_id(task_id)

    def add_task(
        self,
        name: str,
        frequency: str,
        instruction: str,
        task_id: Optional[str] = None,
        time: Optional[str] = None,
        day: Optional[str] = None,
        priority: int = 50,
        permission_tier: int = 0,
        enabled: bool = True,
        conditions: Optional[List[Dict[str, Any]]] = None,
    ) -> ProactiveTask:
        """Add a new proactive task.

        Args:
            name: Human-readable task name
            frequency: Execution frequency (hourly, daily, weekly, monthly)
            instruction: What the agent should do
            task_id: Optional custom ID (auto-generated if not provided)
            time: Time of day for daily+ tasks (HH:MM)
            day: Day of week for weekly tasks
            priority: Task priority (lower = higher)
            permission_tier: Permission level (0-3)
            enabled: Whether task is active
            conditions: List of condition dictionaries

        Returns:
            The created ProactiveTask

        Raises:
            ValueError: If task ID already exists or frequency is invalid
        """
        # Validate frequency
        valid_frequencies = ["hourly", "daily", "weekly", "monthly"]
        if frequency not in valid_frequencies:
            raise ValueError(f"Invalid frequency. Must be one of: {', '.join(valid_frequencies)}")

        # Generate ID if not provided
        if not task_id:
            task_id = f"{frequency}_{name.lower().replace(' ', '_')}"

        # Check for duplicate
        if self.data.get_task_by_id(task_id):
            raise ValueError(f"Task with ID '{task_id}' already exists")

        # Parse conditions
        from .types import ProactiveCondition
        parsed_conditions = []
        if conditions:
            for c in conditions:
                parsed_conditions.append(ProactiveCondition.from_dict(c.copy()))

        task = ProactiveTask(
            id=task_id,
            name=name,
            frequency=frequency,
            instruction=instruction,
            time=time,
            day=day,
            priority=priority,
            permission_tier=permission_tier,
            enabled=enabled,
            conditions=parsed_conditions,
        )

        self.data.tasks.append(task)
        self.save()

        logger.info(f"[PROACTIVE] Added task: {task_id}")
        return task

    def update_task(
        self,
        task_id: str,
        updates: Optional[Dict[str, Any]] = None,
        add_outcome: Optional[Dict[str, Any]] = None,
    ) -> Optional[ProactiveTask]:
        """Update an existing task.

        Args:
            task_id: ID of task to update
            updates: Dictionary of fields to update
            add_outcome: Optional outcome to add to history

        Returns:
            The updated task if found, None otherwise
        """
        task = self.data.get_task_by_id(task_id)
        if not task:
            logger.warning(f"[PROACTIVE] Task not found: {task_id}")
            return None

        # Apply updates
        if updates:
            for key, value in updates.items():
                if hasattr(task, key) and key not in ['id', 'outcome_history']:
                    setattr(task, key, value)

        # Add outcome
        if add_outcome:
            task.add_outcome(
                result=add_outcome.get("result", ""),
                success=add_outcome.get("success", True)
            )

        self.save()
        logger.info(f"[PROACTIVE] Updated task: {task_id}")
        return task

    def remove_task(self, task_id: str) -> bool:
        """Remove a task by ID.

        Args:
            task_id: ID of task to remove

        Returns:
            True if removed, False if not found
        """
        removed = self.data.remove_task(task_id)
        if removed:
            self.save()
            logger.info(f"[PROACTIVE] Removed task: {task_id}")
        else:
            logger.warning(f"[PROACTIVE] Task not found for removal: {task_id}")
        return removed

    def toggle_task(self, task_id: str, enabled: bool) -> Optional[ProactiveTask]:
        """Enable or disable a task.

        Args:
            task_id: ID of task to toggle
            enabled: New enabled state

        Returns:
            The updated task if found, None otherwise
        """
        return self.update_task(task_id, updates={"enabled": enabled})

    def record_outcome(
        self,
        task_id: str,
        result: str,
        success: bool = True
    ) -> Optional[ProactiveTask]:
        """Record an execution outcome for a task.

        Args:
            task_id: ID of task that was executed
            result: Description of the outcome
            success: Whether execution was successful

        Returns:
            The updated task if found, None otherwise
        """
        return self.update_task(
            task_id,
            add_outcome={"result": result, "success": success}
        )

    def update_planner_output(self, scope: str, date_info: str, content: str) -> None:
        """Update planner output section.

        Args:
            scope: Planner scope (day, week, month)
            date_info: Date information (e.g., "2026-02-26" or "Week 9, 2026")
            content: The planner output content
        """
        key = f"{scope}_planner_{date_info}"
        self.data.planner_outputs[key] = content
        self.save()
        logger.info(f"[PROACTIVE] Updated planner output: {key}")

    def get_due_tasks(self, frequency: str) -> List[ProactiveTask]:
        """Get tasks that are due for execution.

        This is used by the heartbeat processor to determine which tasks
        should be executed for the current heartbeat.

        Args:
            frequency: The current heartbeat frequency

        Returns:
            List of tasks that should run
        """
        tasks = self.get_tasks(frequency=frequency, enabled_only=True)

        # Filter by should_run logic
        due_tasks = [t for t in tasks if t.should_run(frequency)]

        logger.info(f"[PROACTIVE] Found {len(due_tasks)} due tasks for {frequency} heartbeat")
        return due_tasks


# Singleton instance (initialized by InternalActionInterface)
_manager: Optional[ProactiveManager] = None


def get_proactive_manager() -> Optional[ProactiveManager]:
    """Get the singleton proactive manager instance."""
    return _manager


def initialize_proactive_manager(file_path: Path) -> ProactiveManager:
    """Initialize the singleton proactive manager.

    Args:
        file_path: Path to PROACTIVE.md file

    Returns:
        The initialized ProactiveManager
    """
    global _manager
    _manager = ProactiveManager(file_path)
    _manager.load()
    return _manager
