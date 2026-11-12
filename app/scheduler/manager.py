# -*- coding: utf-8 -*-
"""
Scheduler Manager

Manages scheduled tasks with background asyncio loops, plus the runner for
the cron jobs in PROACTIVE.md. Fires durable triggers into the MAIN session
when work is due.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_core import MAIN_SESSION_ID
from agent_core.utils.logger import logger

from .parser import ScheduleParser, ScheduleParseError
from .types import ScheduledTask, SchedulerConfig


# A cron job dispatched more than this long after its slot carries a
# lateness note (CraftBot was closed or the machine was asleep at the slot).
CRON_JOB_LATE_SECONDS = 120

# The cron-job runner re-reads PROACTIVE.md at least this often even when no
# job is due sooner, so hand edits to the file and clock jumps after sleep
# are picked up. Changes made through the actions or Settings re-arm it at once.
CRON_RECHECK_SECONDS = 300

# What the cron-job and heartbeat runs load for their whole run.
PROACTIVE_ACTION_SETS = ["file_operations", "proactive", "web_research"]


class SchedulerManager:
    """
    Manager for scheduled tasks.

    Creates background asyncio tasks for each enabled schedule.
    Fires durable triggers when schedules are due (see module docstring).

    Two proactive mechanisms, separate on purpose:
    - Cron jobs (PROACTIVE.md "Cron Jobs"): an internal runner wakes exactly
      at the next job's slot, hands the due jobs to one run and stamps them.
      It re-arms whenever the jobs change.
    - Heartbeat (scheduler_config.json "heartbeat"): every interval tick, if
      the PROACTIVE.md "Heartbeat" checklist is not empty, one run reads it
      and acts only on what needs attention.
    """

    # A one-time task firing more than this many seconds after its scheduled
    # time is treated as a "catch-up" (it became overdue while CraftBot was
    # offline) and the executing agent is given staleness context so it can
    # decide whether to proceed, confirm with the user, or skip.
    CATCHUP_THRESHOLD_SECONDS = 120

    def __init__(self):
        self._schedules: Dict[str, ScheduledTask] = {}
        self._scheduler_tasks: Dict[str, asyncio.Task] = {}
        self._config_path: Optional[Path] = None
        self._trigger_service = None  # TriggerService — durable emit path
        self._is_running: bool = False
        self._master_enabled: bool = True  # Track master enabled state for config saves
        self._lock = asyncio.Lock()
        # Per-loop wake-up events: setting one makes that loop recompute its
        # next fire now instead of finishing its sleep.
        self._wake_events: Dict[str, asyncio.Event] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._proactive_manager = None  # ProactiveManager, see set_proactive_manager
        # "job_id@slot_minute" keys this process already dispatched: a slot
        # never fires twice even if stamping PROACTIVE.md failed (file locked).
        self._dispatched_slots: set[str] = set()
        # The cron-job runner and its wake-up event (see _cron_jobs_loop).
        self._cron_task: Optional[asyncio.Task] = None
        self._cron_wake: Optional[asyncio.Event] = None

    async def initialize(
        self,
        config_path: Path,
        trigger_service=None,
    ) -> None:
        """
        Initialize the scheduler with configuration.

        Args:
            config_path: Path to scheduler_config.json
            trigger_service: TriggerService — fires are emitted durably with
                dedup keys into the main session's queue.
        """
        self._config_path = Path(config_path)
        self._trigger_service = trigger_service

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
        self._loop = asyncio.get_running_loop()

        async with self._lock:
            for schedule_id, schedule in self._schedules.items():
                if schedule.enabled:
                    await self._start_schedule_loop(schedule_id)

        self._cron_wake = asyncio.Event()
        self._cron_task = asyncio.create_task(self._cron_jobs_loop())

        logger.info(
            f"[SCHEDULER] Started {len(self._scheduler_tasks)} schedule loop(s) "
            f"and the cron-job runner"
        )

    async def shutdown(self) -> None:
        """Stop all scheduler loops gracefully."""
        self._is_running = False

        if self._cron_task is not None and not self._cron_task.done():
            self._cron_task.cancel()
            try:
                await self._cron_task
            except asyncio.CancelledError:
                pass
        self._cron_task = None

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
            enabled: Whether to enable immediately
            recurring: True for recurring tasks, False for one-time tasks
            action_sets: Action sets to preload for the run
            skills: Skills to preload for the run
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
            recurring=recurring,
            action_sets=action_sets or [],
            skills=skills or [],
            payload=payload or {},
        )

        # Calculate next fire time
        task.next_run = ScheduleParser.calculate_next_fire_time(task.schedule)

        # Add to schedules
        self._schedules[schedule_id] = task

        # Start loop if running and enabled (BEFORE saving config)
        # This ensures the loop is in _scheduler_tasks when reload() runs
        if self._is_running and enabled:
            asyncio.create_task(self._start_schedule_loop(schedule_id))

        # Save config (triggers hot-reload via file watcher)
        self._save_config()

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
            # A sleeping loop recomputes its next fire from the new expression.
            self._wake(schedule_id)

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

    # ─────────────── Proactive: cron jobs and the heartbeat ───────────────

    def set_proactive_manager(self, proactive_manager) -> None:
        """Give the cron-job runner and the heartbeat PROACTIVE.md; every save
        to it re-arms the cron-job runner."""
        self._proactive_manager = proactive_manager
        proactive_manager.set_change_listener(self.rearm_proactive)

    def rearm_proactive(self) -> None:
        """Make the cron-job runner recompute its next wake now (thread-safe).

        Called after the cron jobs change and when proactive mode is switched,
        so a new, edited or re-enabled job fires at its exact slot.
        """
        self._set_event(self._cron_wake)

    def _wake(self, schedule_id: str) -> None:
        self._set_event(self._wake_events.get(schedule_id))

    def _set_event(self, event: Optional[asyncio.Event]) -> None:
        """Set an event owned by the scheduler's loop, from any thread."""
        loop = self._loop
        if event is None or loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            event.set()
        else:
            loop.call_soon_threadsafe(event.set)

    @staticmethod
    def _proactive_enabled() -> bool:
        from app.ui_layer.settings.proactive_settings import is_proactive_enabled

        return is_proactive_enabled()

    def _heartbeat_checklist(self) -> str:
        if self._proactive_manager is None:
            return ""
        return self._proactive_manager.get_heartbeat_checklist()

    async def queue_immediate_trigger(
        self,
        name: str,
        instruction: str,
        priority: int = 50,
        action_sets: Optional[List[str]] = None,
        skills: Optional[List[str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Queue a trigger for immediate execution in the MAIN session.

        Args:
            name: Human-readable name for the work
            instruction: What the agent should do
            priority: Trigger priority (lower = higher priority)
            action_sets: Action sets to preload for the run
            skills: Skills to preload for the run
            payload: Additional payload data to pass to the run

        Returns:
            Dictionary with status and message
        """
        if not self._trigger_service:
            return {"status": "error", "error": "Trigger service not initialized"}

        fire_id = f"immediate_{uuid.uuid4().hex[:8]}"

        # Build trigger payload (matching the format used by _fire_schedule)
        trigger_payload = {
            "schedule_id": fire_id,
            "schedule_name": name,
            "instruction": instruction,
            "workflow_action_sets": action_sets or [],
            "workflow_skills": skills or [],
            **(payload or {}),
        }

        from app.triggers import TriggerSource, TriggerSpec

        # No dedup key: each immediate request is intentionally a new fire.
        await self._trigger_service.emit(
            TriggerSpec(
                source=TriggerSource.SCHEDULED_IMMEDIATE,
                description=f"[Immediate] {name}: {instruction}",
                fire_at=time.time(),  # Fire immediately
                priority=priority,
                session_id=MAIN_SESSION_ID,
                payload=trigger_payload,
            )
        )

        logger.info(f"[SCHEDULER] Queued immediate trigger: {name}")

        return {
            "status": "ok",
            "schedule_id": fire_id,
            "name": name,
            "recurring": False,
            "scheduled_for": "immediate",
            "message": f"Task '{name}' queued for immediate execution",
        }

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
                    "last_run": datetime.fromtimestamp(s.last_run).isoformat()
                    if s.last_run
                    else None,
                    "next_run": datetime.fromtimestamp(s.next_run).isoformat()
                    if s.next_run
                    else None,
                    "run_count": s.run_count,
                }
                for s in self._schedules.values()
            ],
        }

    async def reload(self, config_path: Optional[Path] = None) -> Dict[str, Any]:
        """
        Hot-reload scheduler configuration from disk.

        Stops all loops, clears schedules, re-reads config, and restarts.
        """
        try:
            # 1. Stop all existing loops
            for schedule_id in list(self._scheduler_tasks.keys()):
                await self._stop_schedule_loop(schedule_id)

            # 2. Clear schedules
            self._schedules.clear()

            # 3. Load config from disk
            config = self._load_config()
            self._master_enabled = config.enabled

            if not config.enabled:
                logger.info("[SCHEDULER] Scheduler disabled in config")
                return {"success": True, "message": "Scheduler disabled", "total": 0}

            # 4. Add schedules and start loops
            for task in config.schedules:
                self._schedules[task.id] = task
                if self._is_running and task.enabled:
                    await self._start_schedule_loop(task.id)

            logger.info(f"[SCHEDULER] Reloaded {len(self._schedules)} schedule(s)")
            return {
                "success": True,
                "message": f"Reloaded {len(self._schedules)} schedules",
                "total": len(self._schedules),
            }
        except Exception as e:
            logger.error(f"[SCHEDULER] Reload failed: {e}")
            return {"success": False, "message": str(e), "total": 0}

    async def _stop_schedule_loop(self, schedule_id: str) -> None:
        """Stop a background loop for a schedule."""
        if schedule_id not in self._scheduler_tasks:
            return

        task = self._scheduler_tasks[schedule_id]
        if not task.done():
            try:
                task.cancel()
                await task
            except (asyncio.CancelledError, RuntimeError, Exception):
                pass  # Ignore all errors during cancellation

        del self._scheduler_tasks[schedule_id]

    # ─────────────── Internal Methods ───────────────

    async def _start_schedule_loop(self, schedule_id: str) -> None:
        """Start a background loop for a schedule."""
        if schedule_id in self._scheduler_tasks:
            existing_task = self._scheduler_tasks[schedule_id]
            if not existing_task.done():
                return  # Already running
            # Task exists but is done - clean up before creating new one
            del self._scheduler_tasks[schedule_id]
            logger.debug(f"[SCHEDULER] Cleaned up done task for: {schedule_id}")

        task = asyncio.create_task(self._schedule_loop(schedule_id))
        self._scheduler_tasks[schedule_id] = task

        schedule = self._schedules[schedule_id]
        logger.info(f"[SCHEDULER] Started loop for: {schedule_id} - {schedule.name}")

    async def _schedule_loop(self, schedule_id: str) -> None:
        """
        Background loop for a single schedule.

        Calculates delay to next fire time, sleeps, then fires the trigger.
        """
        logger.info(f"[SCHEDULER] Loop starting for: {schedule_id}")

        while self._is_running:
            try:
                schedule = self._schedules.get(schedule_id)
                if not schedule:
                    logger.warning(
                        f"[SCHEDULER] Schedule {schedule_id} not found, exiting loop"
                    )
                    break
                if not schedule.enabled:
                    logger.info(
                        f"[SCHEDULER] Schedule {schedule_id} disabled, exiting loop"
                    )
                    break

                # Clear the wake-up flag BEFORE computing the next fire: a
                # re-arm that lands after this point cuts the sleep short.
                wake = self._wake_events.setdefault(schedule_id, asyncio.Event())
                wake.clear()

                # Calculate next fire time
                now = time.time()
                next_fire = ScheduleParser.calculate_next_fire_time(
                    schedule.schedule, from_time=now
                )
                schedule.next_run = next_fire

                # Calculate sleep duration
                delay = next_fire - now
                if delay > 0:
                    next_fire_str = datetime.fromtimestamp(next_fire).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    logger.info(
                        f"[SCHEDULER] {schedule_id} ({schedule.name}) sleeping until {next_fire_str} "
                        f"({delay:.1f}s / {delay / 60:.1f}min)"
                    )
                    try:
                        await asyncio.wait_for(wake.wait(), timeout=delay)
                        logger.info(
                            f"[SCHEDULER] {schedule_id} re-armed, recomputing next fire"
                        )
                        continue
                    except asyncio.TimeoutError:
                        pass

                # Check if still running and schedule still exists
                schedule = self._schedules.get(schedule_id)
                logger.info(
                    f"[SCHEDULER] {schedule_id} woke up, checking conditions before fire"
                )
                if not schedule:
                    logger.warning(
                        f"[SCHEDULER] {schedule_id} schedule was removed while sleeping"
                    )
                    break
                if not schedule.enabled:
                    logger.info(
                        f"[SCHEDULER] {schedule_id} was disabled while sleeping"
                    )
                    break
                if not self._is_running:
                    logger.info(
                        f"[SCHEDULER] {schedule_id} scheduler stopped while sleeping"
                    )
                    break

                # Fire the schedule
                logger.info(f"[SCHEDULER] {schedule_id} about to fire!")
                await self._fire_schedule(schedule)

                # Small delay before recalculating (for interval schedules)
                if schedule.schedule.schedule_type == "interval":
                    await asyncio.sleep(0.1)
                else:
                    # For time-based schedules, sleep past the current minute
                    await asyncio.sleep(60)

            except asyncio.CancelledError:
                logger.info(f"[SCHEDULER] Loop cancelled for: {schedule_id}")
                break
            except Exception as e:
                logger.error(f"[SCHEDULER] Error in loop for {schedule_id}: {e}")
                import traceback

                logger.error(f"[SCHEDULER] Traceback: {traceback.format_exc()}")
                # Wait before retrying to avoid tight error loops
                await asyncio.sleep(60)

        logger.info(f"[SCHEDULER] Loop exited for: {schedule_id}")

    def _should_fire(self, schedule: ScheduledTask) -> bool:
        """Whether firing this schedule should proceed.

        Gates the built-in memory-processing schedule by the event threshold:
        the daily run fires only when enough unprocessed events have piled up
        (or pruning is due), so quiet days skip instead of processing nothing
        at the set time. Planners fire only while proactive mode is on, and
        the heartbeat also needs a non-empty checklist (an empty one costs
        nothing). Every other schedule always fires.
        """
        if schedule.payload.get("type") == "memory_processing":
            from app.ui_layer.settings.memory_settings import (
                memory_scheduled_run_due,
            )

            return memory_scheduled_run_due()
        kind = schedule.payload.get("type")
        if kind == "proactive_heartbeat":
            return self._proactive_enabled() and bool(self._heartbeat_checklist())
        if kind == "proactive_planner":
            return self._proactive_enabled()
        return True

    async def _fire_schedule(self, schedule: ScheduledTask) -> None:
        """
        Fire a scheduled task trigger into the MAIN session. The heartbeat's
        instruction carries its checklist.
        """
        if not self._trigger_service:
            logger.warning(
                "[SCHEDULER] No trigger service configured, cannot fire schedule"
            )
            return

        # Emit-gate: a built-in workflow may have nothing to do on most fires
        # (memory processing on an idle day). Skip firing entirely so no empty
        # run or task ever surfaces; the loop still advances next_run.
        if not self._should_fire(schedule):
            logger.debug(
                f"[SCHEDULER] {schedule.id} has no work pending, skipping fire"
            )
            return

        now = time.time()

        # Update runtime state
        schedule.last_run = now
        schedule.run_count += 1

        # Build trigger payload. Preloaded skills/action sets ride as
        # workflow capabilities: loaded at run start, unloaded at run end.
        payload = {
            "schedule_id": schedule.id,
            "schedule_name": schedule.name,
            "instruction": schedule.instruction,
            "workflow_action_sets": schedule.action_sets,
            "workflow_skills": schedule.skills,
            **schedule.payload,  # Merge custom payload
        }

        if payload.get("type") == "proactive_heartbeat":
            description = self._heartbeat_instruction(self._heartbeat_checklist())
        else:
            description = f"[Scheduled] {schedule.name}: {schedule.instruction}"

        # Catch-up handling: a one-time task can become overdue while CraftBot is
        # offline. Rather than apply a hard drop/fire cutoff, fire it but hand
        # the executing agent the staleness context so it can use judgment —
        # proceed if only slightly late, otherwise confirm with the user or skip
        # if no longer relevant.
        if (
            schedule.schedule.schedule_type == "once"
            and schedule.schedule.fire_at is not None
        ):
            overdue = now - schedule.schedule.fire_at
            if overdue > self.CATCHUP_THRESHOLD_SECONDS:
                scheduled_for = datetime.fromtimestamp(
                    schedule.schedule.fire_at
                ).strftime("%Y-%m-%d %H:%M:%S")
                overdue_human = self._format_duration(overdue)
                catch_up_note = (
                    f"NOTE: This one-time task was scheduled for {scheduled_for} "
                    f"but is running about {overdue_human} late because CraftBot "
                    f"was offline at the scheduled time. Use your judgment: if it "
                    f"is only slightly late and still relevant, carry it out "
                    f"normally. If it is significantly late, or the action is "
                    f"time-sensitive or irreversible (e.g. sending a message or "
                    f"email), confirm with the user before proceeding, or skip it "
                    f"if it is no longer relevant."
                )
                payload["is_catch_up"] = True
                payload["overdue_seconds"] = overdue
                payload["originally_scheduled_for"] = scheduled_for
                payload["catch_up_note"] = catch_up_note
                description = f"{description}\n\n{catch_up_note}"
                logger.info(
                    f"[SCHEDULER] One-time task {schedule.id} is overdue by "
                    f"{overdue_human}; firing as catch-up with agent-judgment note"
                )

        # Durable path: emit FIRST — the dedup key is the crash guard. A
        # crash anywhere after the INSERT can't lose the fire, and a re-fire
        # attempt (config not yet saved, or the run_count>0 reload skip
        # missed) collides with the active row and is a no-op. Then remove
        # one-time tasks from the config.
        from app.triggers import (
            TriggerSource,
            TriggerSpec,
            scheduled_dedup_key,
            scheduled_once_dedup_key,
        )

        if not schedule.recurring:
            source = TriggerSource.SCHEDULED_ONCE
            dedup_key = scheduled_once_dedup_key(schedule.id)
        else:
            source = TriggerSource.SCHEDULED
            # Bucket by this fire's scheduled minute (next_run was set to
            # this fire's target by the schedule loop) so retrying the
            # same fire dedups but the next occurrence does not.
            dedup_key = scheduled_dedup_key(schedule.id, schedule.next_run or now)

        # Built-in schedules (scheduler_config.json) carry their workflow
        # type in their custom payload — promote it to the typed source so
        # react() runs the matching pre-check.
        payload_type_to_source = {
            "memory_processing": TriggerSource.MEMORY,
            "proactive_heartbeat": TriggerSource.PROACTIVE_HEARTBEAT,
            "proactive_planner": TriggerSource.PROACTIVE_PLANNER,
        }
        promoted = payload_type_to_source.get(payload.get("type"))
        if promoted is not None:
            source = promoted

        result = await self._trigger_service.emit(
            TriggerSpec(
                source=source,
                description=description,
                fire_at=now,
                priority=schedule.priority,
                session_id=MAIN_SESSION_ID,
                payload=payload,
                dedup_key=dedup_key,
            )
        )
        if result.deduped:
            logger.info(
                f"[SCHEDULER] Fire deduped (already queued/in-flight): "
                f"{schedule.id} - {schedule.name}"
            )

        if not schedule.recurring:
            self._schedules.pop(schedule.id, None)
            self._save_config()
            logger.info(
                f"[SCHEDULER] One-time task fired, removed from config: {schedule.id}"
            )

        logger.info(
            f"[SCHEDULER] Fired schedule: {schedule.id} - {schedule.name} "
            f"(run #{schedule.run_count})"
        )

    # ─────────────── Cron-job runner ───────────────

    async def _cron_jobs_loop(self) -> None:
        """Fire PROACTIVE.md cron jobs at their slots.

        Wakes at the next job's slot, at least every CRON_RECHECK_SECONDS
        (hand edits to the file, clock jumps after sleep), and immediately
        on rearm_proactive(). A slot missed while CraftBot was off is due on
        the first pass and runs once, late.
        """
        logger.info("[SCHEDULER] Cron-job runner started")
        while self._is_running:
            try:
                self._cron_wake.clear()
                await self._fire_cron_jobs()

                now = time.time()
                delay = float(CRON_RECHECK_SECONDS)
                if self._proactive_manager is not None and self._proactive_enabled():
                    due_at = self._proactive_manager.next_due_at(
                        datetime.fromtimestamp(now)
                    )
                    # A job already due here was just dispatched by this
                    # process (stamping failed): wait for the recheck instead
                    # of spinning on it.
                    if due_at is not None and due_at.timestamp() > now:
                        delay = min(delay, due_at.timestamp() - now)
                try:
                    await asyncio.wait_for(self._cron_wake.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SCHEDULER] Cron-job runner error: {e}")
                await asyncio.sleep(60)
        logger.info("[SCHEDULER] Cron-job runner stopped")

    async def _fire_cron_jobs(self) -> None:
        """Hand every due cron job to one run, then stamp them."""
        if (
            self._proactive_manager is None
            or not self._trigger_service
            or not self._proactive_enabled()
        ):
            return
        now = time.time()
        now_dt = datetime.fromtimestamp(now)
        due = [
            job
            for job in self._proactive_manager.get_due_jobs(now_dt)
            if self._slot_key(job, now_dt) not in self._dispatched_slots
        ]
        if not due:
            return

        from app.triggers import TriggerSource, TriggerSpec

        job_ids = [job.id for job in due]
        slot_keys = [self._slot_key(job, now_dt) for job in due]
        # Durable emit first; one fire per (job, slot), so a crash-retry of
        # the same dispatch dedups and the next slot of any job does not.
        await self._trigger_service.emit(
            TriggerSpec(
                source=TriggerSource.CRON_JOB,
                description=self._cron_jobs_description(due, now_dt),
                fire_at=now,
                priority=min(job.priority for job in due),
                session_id=MAIN_SESSION_ID,
                payload={
                    "cron_job_ids": job_ids,
                    "workflow_skills": ["cron-job-runner"],
                    "workflow_action_sets": list(PROACTIVE_ACTION_SETS),
                },
                dedup_key="cron:" + ",".join(slot_keys),
            )
        )
        # Stamp after the durable emit: a crash in between re-fires the same
        # (job, slot) set, which the dedup key collapses.
        self._dispatched_slots.update(slot_keys)
        self._proactive_manager.mark_dispatched(job_ids, now_dt)
        logger.info(f"[SCHEDULER] Fired {len(due)} cron job(s): {', '.join(job_ids)}")

    @staticmethod
    def _slot_key(job, now: datetime) -> str:
        """Identity of one job slot: "job_id@slot_minute"."""
        return f"{job.id}@{int(job.latest_slot(now).timestamp() // 60)}"

    def _cron_jobs_description(self, jobs, now: datetime) -> str:
        """The cron-job run's instruction: the due jobs, spelled out."""
        lines = [
            "Run these due cron jobs from PROACTIVE.md. The scheduler already "
            "selected them and recorded them as run: do not re-check their "
            "schedules. After each job, record its outcome with "
            "cron_job_update(job_id, add_outcome={result, success}).",
            "",
        ]
        for i, job in enumerate(jobs, start=1):
            slot = job.latest_slot(now)
            when = {
                "hourly": f"hourly at :{slot:%M}",
                "daily": f"daily at {slot:%H:%M}",
                "weekly": f"weekly on {slot:%A} at {slot:%H:%M}",
                "monthly": f"monthly on day {slot.day} at {slot:%H:%M}",
            }.get(job.frequency, job.frequency)
            tier = (
                "notify the user"
                if job.permission_tier >= 1
                else "silent unless the instruction asks to report"
            )
            lines.append(f"{i}. {job.name} (id: {job.id}; {when}; {tier})")
            lines.append(f"   Instruction: {job.instruction.strip()}")
            if job.conditions:
                conditions = ", ".join(c.type for c in job.conditions)
                lines.append(
                    f"   Conditions: {conditions}. If one does not hold now, "
                    f"skip this job."
                )
            late = (now - slot).total_seconds()
            if late > CRON_JOB_LATE_SECONDS:
                lines.append(
                    f"   Late: due {slot:%Y-%m-%d %H:%M}, running about "
                    f"{self._format_duration(late)} late because CraftBot was not "
                    f"running then. If it no longer makes sense now, skip it and "
                    f"say so."
                )
        lines += [
            "",
            "Finish with ONE send_message covering every job that has "
            "something for the user. If nothing needs their attention, end "
            "with end_turn instead.",
        ]
        return "\n".join(lines)

    @staticmethod
    def _heartbeat_instruction(checklist: str) -> str:
        """The heartbeat run's instruction: the checklist it must go through."""
        return (
            "Heartbeat check. Go through the checklist below (the Heartbeat "
            "section of PROACTIVE.md, written by the user) and check each item "
            "now. Act only where something needs attention.\n\n"
            f"{checklist}\n\n"
            "If something needs the user, finish with ONE send_message covering "
            "it. If nothing needs attention, end with end_turn."
        )

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format a duration in seconds into a short human-readable string."""
        seconds = int(seconds)
        if seconds < 60:
            unit = "second"
            value = seconds
        elif seconds < 3600:
            unit = "minute"
            value = seconds // 60
        elif seconds < 86400:
            unit = "hour"
            value = seconds // 3600
        else:
            unit = "day"
            value = seconds // 86400
        return f"{value} {unit}{'s' if value != 1 else ''}"

    def _load_config(self) -> SchedulerConfig:
        """Load configuration from file."""
        if not self._config_path or not self._config_path.exists():
            logger.info("[SCHEDULER] No config file found, using defaults")
            return SchedulerConfig()

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"[SCHEDULER] Config read error, using defaults: {e}")
            return SchedulerConfig()

        # Parse schedules
        schedules = []
        for schedule_data in data.get("schedules", []):
            try:
                # Parse the schedule expression
                expression = schedule_data.get("schedule", "")
                parsed_schedule = ScheduleParser.parse(expression)

                # One-time tasks: restore the persisted absolute fire time
                # instead of re-anchoring the raw expression to "now". Re-parsing
                # "in 10 minutes" on every restart pushed the fire time forward,
                # delaying the task indefinitely across restarts.
                if parsed_schedule.schedule_type == "once":
                    stored_fire_at = schedule_data.get("fire_at")
                    if stored_fire_at is not None:
                        parsed_schedule.fire_at = stored_fire_at

                task = ScheduledTask.from_dict(schedule_data, parsed_schedule)

                # Skip one-time tasks that already fired in a previous run but
                # weren't removed before a crash/restart. Prevents the task from
                # being executed (e.g. an email sent) a second time.
                if not task.recurring and task.run_count > 0:
                    logger.info(
                        f"[SCHEDULER] Skipping already-fired one-time task: "
                        f"{task.id} - {task.name}"
                    )
                    continue

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

        # Write atomically (write to temp, then rename).
        # On Windows the rename can fail with "Access is denied" when
        # another process (e.g. an IDE) holds the target file open, so
        # fall back to a direct overwrite in that case.
        temp_path = self._config_path.with_suffix(".tmp")
        data = json.dumps(config.to_dict(), indent=2)
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(data)
            try:
                temp_path.replace(self._config_path)
            except OSError:
                # Atomic rename failed (Windows lock) — write directly
                with open(self._config_path, "w", encoding="utf-8") as f:
                    f.write(data)
                if temp_path.exists():
                    temp_path.unlink()
        except Exception as e:
            logger.error(f"[SCHEDULER] Failed to save config: {e}")
