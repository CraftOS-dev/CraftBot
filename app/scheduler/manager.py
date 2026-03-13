# -*- coding: utf-8 -*-
"""
Scheduler Manager

Manages scheduled tasks with background asyncio loops.
Fires triggers into the TriggerQueue when schedules are due.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core import Trigger, TriggerQueue
from agent_core.utils.logger import logger

from .parser import ScheduleParser, ScheduleParseError
from .types import ScheduledTask, ScheduleExpression, SchedulerConfig


class SchedulerManager:
    """
    Manager for scheduled tasks.

    Creates background asyncio tasks for each enabled schedule.
    Fires triggers into the TriggerQueue when schedules are due.
    """

    def __init__(self):
        self._schedules: Dict[str, ScheduledTask] = {}
        self._scheduler_tasks: Dict[str, asyncio.Task] = {}
        self._config_path: Optional[Path] = None
        self._trigger_queue: Optional[TriggerQueue] = None
        self._is_running: bool = False
        self._master_enabled: bool = True  # Track master enabled state for config saves
        self._lock = asyncio.Lock()

    async def initialize(
        self,
        config_path: Path,
        trigger_queue: TriggerQueue,
    ) -> None:
        """
        Initialize the scheduler with configuration.

        Args:
            config_path: Path to scheduler_config.json
            trigger_queue: TriggerQueue to fire triggers into
        """
        self._config_path = Path(config_path)
        self._trigger_queue = trigger_queue

        # Load configuration
        config = self._load_config()

        # Track master enabled state for config saves
        self._master_enabled = config.enabled

        if not config.enabled:
            logger.info("[SCHEDULER] Scheduler is disabled in config")
            return

        # Register schedules
        for task in config.schedules:
            self._schedules[task.id] = task
            logger.debug(f"[SCHEDULER] Loaded schedule: {task.id} - {task.name}")

        logger.info(f"[SCHEDULER] Initialized with {len(self._schedules)} schedule(s)")

    async def start(self) -> None:
        """Start all scheduler loops."""
        if self._is_running:
            logger.warning("[SCHEDULER] Already running")
            return

        self._is_running = True

        async with self._lock:
            for schedule_id, schedule in self._schedules.items():
                if schedule.enabled:
                    await self._start_schedule_loop(schedule_id)

        logger.info(f"[SCHEDULER] Started {len(self._scheduler_tasks)} schedule loop(s)")

    async def shutdown(self) -> None:
        """Stop all scheduler loops gracefully."""
        self._is_running = False

        async with self._lock:
            for task_id, task in list(self._scheduler_tasks.items()):
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                del self._scheduler_tasks[task_id]

        logger.info("[SCHEDULER] Shutdown complete")

    # ─────────────── Schedule Management ───────────────

    def add_schedule(
        self,
        name: str,
        instruction: str,
        schedule_expression: str,
        priority: int = 50,
        mode: str = "simple",
        enabled: bool = True,
        recurring: bool = True,
        action_sets: Optional[List[str]] = None,
        skills: Optional[List[str]] = None,
        payload: Optional[Dict[str, Any]] = None,
        schedule_id: Optional[str] = None,
    ) -> str:
        """
        Add a new scheduled task.

        Args:
            name: Human-readable name
            instruction: What the agent should do
            schedule_expression: When to run (e.g., "every day at 7am")
            priority: Trigger priority (lower = higher priority)
            mode: Task mode ("simple" or "complex")
            enabled: Whether to enable immediately
            recurring: True for recurring tasks, False for one-time tasks
            action_sets: Action sets to use
            skills: Skills to use
            payload: Extra trigger payload
            schedule_id: Optional custom ID (auto-generated if not provided)

        Returns:
            The schedule ID
        """
        # Parse the schedule expression
        parsed_schedule = ScheduleParser.parse(schedule_expression)

        # Generate ID if not provided
        if schedule_id is None:
            schedule_id = str(uuid.uuid4())[:8]

        # Create the scheduled task
        task = ScheduledTask(
            id=schedule_id,
            name=name,
            instruction=instruction,
            schedule=parsed_schedule,
            enabled=enabled,
            priority=priority,
            mode=mode,
            recurring=recurring,
            action_sets=action_sets or [],
            skills=skills or [],
            payload=payload or {},
        )

        # Calculate next fire time
        task.next_run = ScheduleParser.calculate_next_fire_time(task.schedule)

        # Add to schedules
        self._schedules[schedule_id] = task

        # Save config
        self._save_config()

        # Start loop if running and enabled
        if self._is_running and enabled:
            asyncio.create_task(self._start_schedule_loop(schedule_id))

        logger.info(f"[SCHEDULER] Added schedule: {schedule_id} - {name}")
        return schedule_id

    def remove_schedule(self, schedule_id: str) -> bool:
        """
        Remove a scheduled task.

        Args:
            schedule_id: ID of the schedule to remove

        Returns:
            True if removed, False if not found
        """
        if schedule_id not in self._schedules:
            return False

        # Stop the loop if running
        if schedule_id in self._scheduler_tasks:
            task = self._scheduler_tasks[schedule_id]
            if not task.done():
                task.cancel()
            del self._scheduler_tasks[schedule_id]

        # Remove from schedules
        del self._schedules[schedule_id]

        # Save config
        self._save_config()

        logger.info(f"[SCHEDULER] Removed schedule: {schedule_id}")
        return True

    def update_schedule(self, schedule_id: str, **updates) -> bool:
        """
        Update an existing scheduled task.

        Args:
            schedule_id: ID of the schedule to update
            **updates: Fields to update (name, instruction, schedule, enabled, etc.)

        Returns:
            True if updated, False if not found
        """
        if schedule_id not in self._schedules:
            return False

        schedule = self._schedules[schedule_id]

        # Handle schedule expression update
        if "schedule" in updates:
            parsed = ScheduleParser.parse(updates.pop("schedule"))
            schedule.schedule = parsed
            schedule.next_run = ScheduleParser.calculate_next_fire_time(parsed)

        # Update other fields
        for key, value in updates.items():
            if hasattr(schedule, key):
                setattr(schedule, key, value)

        # Restart loop if enabled status changed
        if "enabled" in updates:
            if updates["enabled"] and schedule_id not in self._scheduler_tasks:
                asyncio.create_task(self._start_schedule_loop(schedule_id))
            elif not updates["enabled"] and schedule_id in self._scheduler_tasks:
                task = self._scheduler_tasks[schedule_id]
                if not task.done():
                    task.cancel()
                del self._scheduler_tasks[schedule_id]

        # Save config
        self._save_config()

        logger.info(f"[SCHEDULER] Updated schedule: {schedule_id}")
        return True

    def enable_schedule(self, schedule_id: str) -> bool:
        """Enable a schedule."""
        return self.update_schedule(schedule_id, enabled=True)

    def disable_schedule(self, schedule_id: str) -> bool:
        """Disable a schedule."""
        return self.update_schedule(schedule_id, enabled=False)

    def set_master_enabled(self, enabled: bool) -> None:
        """Set the master scheduler enabled state.

        This controls the top-level 'enabled' flag in the config file.
        Call this before enabling/disabling individual schedules to ensure
        the correct state is saved when _save_config() is called.

        Note: This does NOT write to the config file directly - it only
        updates the internal state. The file is expected to be updated
        separately (e.g., by the UI layer's update_scheduler_config).
        """
        self._master_enabled = enabled
        logger.info(f"[SCHEDULER] Master enabled set to: {enabled}")

    def list_schedules(self) -> List[ScheduledTask]:
        """List all scheduled tasks."""
        return list(self._schedules.values())

    def get_schedule(self, schedule_id: str) -> Optional[ScheduledTask]:
        """Get a schedule by ID."""
        return self._schedules.get(schedule_id)

    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status for monitoring."""
        return {
            "is_running": self._is_running,
            "total_schedules": len(self._schedules),
            "active_loops": len(self._scheduler_tasks),
            "schedules": [
                {
                    "id": s.id,
                    "name": s.name,
                    "enabled": s.enabled,
                    "schedule": s.schedule.raw_expression,
                    "last_run": datetime.fromtimestamp(s.last_run).isoformat() if s.last_run else None,
                    "next_run": datetime.fromtimestamp(s.next_run).isoformat() if s.next_run else None,
                    "run_count": s.run_count,
                }
                for s in self._schedules.values()
            ],
        }

    # ─────────────── Internal Methods ───────────────

    async def _start_schedule_loop(self, schedule_id: str) -> None:
        """Start a background loop for a schedule."""
        if schedule_id in self._scheduler_tasks:
            return  # Already running

        task = asyncio.create_task(self._schedule_loop(schedule_id))
        self._scheduler_tasks[schedule_id] = task

        schedule = self._schedules[schedule_id]
        logger.debug(f"[SCHEDULER] Started loop for: {schedule_id} - {schedule.name}")

    async def _schedule_loop(self, schedule_id: str) -> None:
        """
        Background loop for a single schedule.

        Calculates delay to next fire time, sleeps, then fires the trigger.
        """
        while self._is_running:
            try:
                schedule = self._schedules.get(schedule_id)
                if not schedule or not schedule.enabled:
                    break

                # Calculate next fire time
                now = time.time()
                next_fire = ScheduleParser.calculate_next_fire_time(
                    schedule.schedule, from_time=now
                )
                schedule.next_run = next_fire

                # Calculate sleep duration
                delay = next_fire - now
                if delay > 0:
                    next_fire_str = datetime.fromtimestamp(next_fire).strftime("%Y-%m-%d %H:%M:%S")
                    logger.debug(
                        f"[SCHEDULER] {schedule_id} sleeping until {next_fire_str} "
                        f"({delay / 3600:.2f} hours)"
                    )
                    await asyncio.sleep(delay)

                # Check if still running and schedule still exists
                schedule = self._schedules.get(schedule_id)
                if not schedule or not schedule.enabled or not self._is_running:
                    break

                # Fire the schedule
                await self._fire_schedule(schedule)

                # Small delay before recalculating (for interval schedules)
                if schedule.schedule.schedule_type == "interval":
                    await asyncio.sleep(0.1)
                else:
                    # For time-based schedules, sleep past the current minute
                    await asyncio.sleep(60)

            except asyncio.CancelledError:
                logger.debug(f"[SCHEDULER] Loop cancelled for: {schedule_id}")
                break
            except Exception as e:
                logger.warning(f"[SCHEDULER] Error in loop for {schedule_id}: {e}")
                # Wait before retrying to avoid tight error loops
                await asyncio.sleep(60)

    async def _fire_schedule(self, schedule: ScheduledTask) -> None:
        """
        Fire a scheduled task trigger.

        Creates a Trigger and puts it into the TriggerQueue.
        """
        if not self._trigger_queue:
            logger.warning("[SCHEDULER] No trigger queue configured, cannot fire schedule")
            return

        # Update runtime state
        schedule.last_run = time.time()
        schedule.run_count += 1

        # Create unique session ID for this run
        session_id = f"scheduled_{schedule.id}_{int(time.time())}"

        # Build trigger payload
        payload = {
            "type": "scheduled",
            "schedule_id": schedule.id,
            "schedule_name": schedule.name,
            "instruction": schedule.instruction,
            "mode": schedule.mode,
            "action_sets": schedule.action_sets,
            "skills": schedule.skills,
            **schedule.payload,  # Merge custom payload
        }

        # Create trigger
        trigger = Trigger(
            fire_at=time.time(),
            priority=schedule.priority,
            next_action_description=f"[Scheduled] {schedule.name}: {schedule.instruction}",
            payload=payload,
            session_id=session_id,
        )

        # Fire!
        await self._trigger_queue.put(trigger)

        logger.info(
            f"[SCHEDULER] Fired schedule: {schedule.id} - {schedule.name} "
            f"(run #{schedule.run_count})"
        )

        # Auto-remove non-recurring (immediate) tasks after firing
        if not schedule.recurring:
            logger.info(f"[SCHEDULER] One-time task fired, removing: {schedule.id}")
            asyncio.create_task(self._remove_after_fire(schedule.id))

    async def _remove_after_fire(self, schedule_id: str) -> None:
        """Remove a one-time schedule after it has fired."""
        await asyncio.sleep(1)  # Brief delay to ensure trigger is processed
        self.remove_schedule(schedule_id)

    def _load_config(self) -> SchedulerConfig:
        """Load configuration from file."""
        if not self._config_path or not self._config_path.exists():
            logger.info("[SCHEDULER] No config file found, using defaults")
            return SchedulerConfig()

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"[SCHEDULER] Invalid JSON in config: {e}")
            return SchedulerConfig()

        # Parse schedules
        schedules = []
        for schedule_data in data.get("schedules", []):
            try:
                # Parse the schedule expression
                expression = schedule_data.get("schedule", "")
                parsed_schedule = ScheduleParser.parse(expression)

                task = ScheduledTask.from_dict(schedule_data, parsed_schedule)
                task.next_run = ScheduleParser.calculate_next_fire_time(task.schedule)
                schedules.append(task)

            except (ScheduleParseError, ValueError) as e:
                logger.warning(
                    f"[SCHEDULER] Skipping invalid schedule '{schedule_data.get('id', '?')}': {e}"
                )

        return SchedulerConfig(
            enabled=data.get("enabled", True),
            schedules=schedules,
        )

    def _save_config(self) -> None:
        """Save configuration to file."""
        if not self._config_path:
            return

        # Build config data (preserve master enabled state)
        config = SchedulerConfig(
            enabled=self._master_enabled,
            schedules=list(self._schedules.values()),
        )

        # Ensure directory exists
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write atomically (write to temp, then rename)
        temp_path = self._config_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(config.to_dict(), f, indent=2)
            temp_path.replace(self._config_path)
        except Exception as e:
            logger.error(f"[SCHEDULER] Failed to save config: {e}")
            if temp_path.exists():
                temp_path.unlink()
