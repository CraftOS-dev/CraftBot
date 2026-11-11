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
from typing import Callable, Dict, List, Any, Optional

from .types import RecurringTask, RecurringData, validate_schedule_fields
from .parser import ProactiveParser

logger = logging.getLogger(__name__)


class ProactiveManager:
    """Manager for recurring tasks stored in PROACTIVE.md.

    PROACTIVE.md is shared with the planners (they edit its Goals section
    with file operations) and with anyone editing it by hand, so the file on
    disk is always the source of truth: every read reloads it when it changed
    since the last load, and every write starts from the file as it is now.
    Writes are atomic (temp file + rename).
    """

    def __init__(self, proactive_file_path: Path):
        """Initialize the manager.

        Args:
            proactive_file_path: Path to PROACTIVE.md file
        """
        self.file_path = proactive_file_path
        self._data: Optional[RecurringData] = None
        self._loaded_mtime: Optional[tuple[int, int]] = None
        # Called after every save; the scheduler re-arms the heartbeat so a
        # new or rescheduled task fires at its exact slot.
        self._on_change: Optional[Callable[[], None]] = None

    def set_change_listener(self, callback: Optional[Callable[[], None]]) -> None:
        """Register a callback invoked after the task list is saved."""
        self._on_change = callback

    def _file_mtime(self) -> Optional[tuple[int, int]]:
        """(mtime_ns, size) fingerprint of the file, None when missing."""
        try:
            stat = self.file_path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def load(self) -> RecurringData:
        """Load recurring task data from file.

        Tasks without ``active_since`` (written by hand) take effect from the
        moment they are first loaded, and that moment is saved so restarts
        don't move it.

        Returns:
            RecurringData object
        """
        if not self.file_path.exists():
            logger.warning(f"[PROACTIVE] File not found: {self.file_path}")
            self._data = RecurringData()
            self._loaded_mtime = None
            return self._data

        content = self.file_path.read_text(encoding="utf-8")
        self._loaded_mtime = self._file_mtime()
        self._data = ProactiveParser.parse(content)

        unanchored = [t for t in self._data.tasks if t.active_since is None]
        if unanchored:
            now = datetime.now()
            for task in unanchored:
                task.active_since = now
            self._write(self._data)
            logger.info(
                f"[PROACTIVE] Anchored {len(unanchored)} new task(s) at "
                f"{now.isoformat(timespec='seconds')}"
            )

        logger.info(
            f"[PROACTIVE] Loaded {len(self._data.tasks)} tasks from {self.file_path}"
        )
        return self._data

    def _refresh(self) -> RecurringData:
        """Reload when the file changed (or appeared/vanished) since last load."""
        if self._data is None or self._file_mtime() != self._loaded_mtime:
            return self.load()
        return self._data

    def _write(self, data: RecurringData) -> None:
        """Serialize ``data`` over the file's CURRENT content, atomically.

        Only the frontmatter and the tasks section are regenerated; every
        other section (Goals, Plan, and Status included) is kept exactly as
        it is on disk at the moment of writing.
        """
        data.last_updated = datetime.now()
        template = (
            self.file_path.read_text(encoding="utf-8")
            if self.file_path.exists()
            else None
        )
        content = ProactiveParser.serialize(data, template)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".md",
                delete=False,
                dir=self.file_path.parent,
            ) as f:
                f.write(content)
                temp_path = Path(f.name)

            shutil.move(str(temp_path), str(self.file_path))
            self._loaded_mtime = self._file_mtime()
        except Exception as e:
            if temp_path and temp_path.exists():
                temp_path.unlink()
            logger.error(f"[PROACTIVE] Failed to save: {e}")
            raise

    def save(self) -> None:
        """Save the loaded task list to file and notify the change listener."""
        if self._data is None:
            raise RuntimeError("No data loaded. Call load() first.")
        self._write(self._data)
        logger.info(
            f"[PROACTIVE] Saved {len(self._data.tasks)} tasks to {self.file_path}"
        )
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception as e:
                logger.warning(f"[PROACTIVE] Change listener failed: {e}")

    @property
    def data(self) -> RecurringData:
        """Current task data, reloaded from disk if the file changed."""
        return self._refresh()

    def get_tasks(
        self, frequency: Optional[str] = None, enabled_only: bool = True
    ) -> List[RecurringTask]:
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

    def get_task(self, task_id: str) -> Optional[RecurringTask]:
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
    ) -> RecurringTask:
        """Add a new recurring task.

        Args:
            name: Human-readable task name
            frequency: Execution frequency (hourly, daily, weekly, monthly)
            instruction: What the agent should do
            task_id: Optional custom ID (auto-generated if not provided)
            time: Slot time HH:MM (hourly tasks use only the minute)
            day: Weekday name for weekly tasks, 1-31 for monthly tasks
            priority: Task priority (lower = higher)
            permission_tier: Permission level (0 = silent, 1 = notify)
            enabled: Whether task is active
            conditions: List of condition dictionaries

        Returns:
            The created RecurringTask

        Raises:
            ValueError: If task ID already exists or the schedule is invalid
        """
        validate_schedule_fields(frequency, time, day)
        data = self._refresh()

        # Generate ID if not provided
        if not task_id:
            task_id = f"{frequency}_{name.lower().replace(' ', '_')}"

        # Check for duplicate
        if data.get_task_by_id(task_id):
            raise ValueError(f"Task with ID '{task_id}' already exists")

        # Parse conditions
        from .types import RecurringCondition

        parsed_conditions = []
        if conditions:
            for c in conditions:
                parsed_conditions.append(RecurringCondition.from_dict(c.copy()))

        task = RecurringTask(
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
            active_since=datetime.now(),
        )

        data.tasks.append(task)
        self.save()

        logger.info(f"[PROACTIVE] Added task: {task_id}")
        return task

    def update_task(
        self,
        task_id: str,
        updates: Optional[Dict[str, Any]] = None,
        add_outcome: Optional[Dict[str, Any]] = None,
    ) -> Optional[RecurringTask]:
        """Update an existing task.

        Re-enabling a task or changing its frequency/time/day restarts its
        schedule from now (``active_since``), so slots missed while it was
        off or under the old schedule are not run late.

        Args:
            task_id: ID of task to update
            updates: Dictionary of fields to update
            add_outcome: Optional outcome to add to history

        Returns:
            The updated task if found, None otherwise
        """
        task = self._refresh().get_task_by_id(task_id)
        if not task:
            logger.warning(f"[PROACTIVE] Task not found: {task_id}")
            return None

        if updates:
            validate_schedule_fields(
                updates.get("frequency", task.frequency),
                updates.get("time", task.time),
                updates.get("day", task.day),
            )
            reschedules = any(
                key in updates and updates[key] != getattr(task, key)
                for key in ("frequency", "time", "day")
            ) or (updates.get("enabled") is True and not task.enabled)
            for key, value in updates.items():
                if hasattr(task, key) and key not in [
                    "id",
                    "outcome_history",
                    "active_since",
                    "last_run",
                    "run_count",
                ]:
                    setattr(task, key, value)
            if reschedules:
                task.active_since = datetime.now()

        if add_outcome:
            task.add_outcome(
                result=add_outcome.get("result", ""),
                success=add_outcome.get("success", True),
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
        removed = self._refresh().remove_task(task_id)
        if removed:
            self.save()
            logger.info(f"[PROACTIVE] Removed task: {task_id}")
        else:
            logger.warning(f"[PROACTIVE] Task not found for removal: {task_id}")
        return removed

    def toggle_task(self, task_id: str, enabled: bool) -> Optional[RecurringTask]:
        """Enable or disable a task.

        Args:
            task_id: ID of task to toggle
            enabled: New enabled state

        Returns:
            The updated task if found, None otherwise
        """
        return self.update_task(task_id, updates={"enabled": enabled})

    def record_outcome(
        self, task_id: str, result: str, success: bool = True
    ) -> Optional[RecurringTask]:
        """Record an execution outcome for a task.

        Args:
            task_id: ID of task that was executed
            result: Description of the outcome
            success: Whether execution was successful

        Returns:
            The updated task if found, None otherwise
        """
        return self.update_task(
            task_id, add_outcome={"result": result, "success": success}
        )

    # ─────────────── Due computation (code-owned) ───────────────

    def _valid_tasks(self) -> List[RecurringTask]:
        """Enabled tasks whose schedule fields are usable.

        A malformed hand-edited task is skipped with a warning instead of
        breaking every other task's schedule.
        """
        valid = []
        for task in self.get_tasks(enabled_only=True):
            try:
                validate_schedule_fields(task.frequency, task.time, task.day)
            except ValueError as e:
                logger.warning(f"[PROACTIVE] Skipping task {task.id}: {e}")
                continue
            valid.append(task)
        return valid

    def get_due_tasks(self, now: Optional[datetime] = None) -> List[RecurringTask]:
        """Tasks whose most recent slot is owed a run, by priority."""
        now = now or datetime.now()
        due = [t for t in self._valid_tasks() if t.is_due(now)]
        due.sort(key=lambda t: t.priority)
        return due

    def next_due_at(self, now: Optional[datetime] = None) -> Optional[datetime]:
        """Earliest moment any enabled task becomes due (None if none)."""
        now = now or datetime.now()
        times = [t.next_due_at(now) for t in self._valid_tasks()]
        times = [t for t in times if t is not None]
        return min(times) if times else None

    def mark_dispatched(self, task_ids: List[str], when: datetime) -> None:
        """Stamp last_run/run_count for tasks handed to a run, then save.

        Stamping at dispatch is what keeps a slot from running twice (a later
        check sees last_run >= slot), whatever the run itself does.
        """
        data = self._refresh()
        stamped = []
        for task_id in task_ids:
            task = data.get_task_by_id(task_id)
            if task is not None:
                task.mark_dispatched(when)
                stamped.append(task_id)
        if stamped:
            self.save()
            logger.info(
                f"[PROACTIVE] Dispatched {len(stamped)} task(s): {', '.join(stamped)}"
            )


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
