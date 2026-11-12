# -*- coding: utf-8 -*-
"""
Proactive manager.

ProactiveManager owns the parts of PROACTIVE.md that code acts on: the cron
jobs and the heartbeat checklist.
"""

import logging
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Any, Optional

from agent_core import MAIN_SESSION_ID

from .types import CronJob, ProactiveData, validate_schedule_fields
from .parser import ProactiveParser

logger = logging.getLogger(__name__)


class ProactiveManager:
    """Manager for the cron jobs and heartbeat checklist in PROACTIVE.md.

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
        self._data: Optional[ProactiveData] = None
        self._loaded_mtime: Optional[tuple[int, int]] = None
        # Called after every save; the scheduler re-arms its cron-job runner
        # so a new or rescheduled job fires at its exact slot.
        self._on_change: Optional[Callable[[], None]] = None

    def set_change_listener(self, callback: Optional[Callable[[], None]]) -> None:
        """Register a callback invoked after PROACTIVE.md is saved."""
        self._on_change = callback

    def _file_mtime(self) -> Optional[tuple[int, int]]:
        """(mtime_ns, size) fingerprint of the file, None when missing."""
        try:
            stat = self.file_path.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def load(self) -> ProactiveData:
        """Load PROACTIVE.md.

        Cron jobs without ``active_since`` (written by hand) take effect from
        when the file was last modified, the closest known moment to when
        they were written, and that moment is saved so restarts don't move
        it. A job added by hand at 08:50 for 09:00 therefore still runs at
        09:00 even if CraftBot only reads the file later.

        Returns:
            ProactiveData object
        """
        if not self.file_path.exists():
            logger.warning(f"[PROACTIVE] File not found: {self.file_path}")
            self._data = ProactiveData()
            self._loaded_mtime = None
            return self._data

        content = self.file_path.read_text(encoding="utf-8")
        self._loaded_mtime = self._file_mtime()
        self._data = ProactiveParser.parse(content)

        unanchored = [j for j in self._data.jobs if j.active_since is None]
        if unanchored:
            written = datetime.fromtimestamp(self.file_path.stat().st_mtime)
            for job in unanchored:
                job.active_since = written
            self._write(self._data)
            logger.info(
                f"[PROACTIVE] Anchored {len(unanchored)} new cron job(s) at "
                f"{written.isoformat(timespec='seconds')}"
            )

        logger.info(
            f"[PROACTIVE] Loaded {len(self._data.jobs)} cron jobs from {self.file_path}"
        )
        return self._data

    def _refresh(self) -> ProactiveData:
        """Reload when the file changed (or appeared/vanished) since last load."""
        if self._data is None or self._file_mtime() != self._loaded_mtime:
            return self.load()
        return self._data

    def _write(self, data: ProactiveData) -> None:
        """Serialize ``data`` over the file's CURRENT content, atomically.

        Only the frontmatter, the Cron Jobs section and the Heartbeat section
        are regenerated; every other section (Goals, Plan, and Status
        included) is kept exactly as it is on disk at the moment of writing.
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
        """Save the loaded data to file and notify the change listener."""
        if self._data is None:
            raise RuntimeError("No data loaded. Call load() first.")
        self._write(self._data)
        logger.info(
            f"[PROACTIVE] Saved {len(self._data.jobs)} cron jobs to {self.file_path}"
        )
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception as e:
                logger.warning(f"[PROACTIVE] Change listener failed: {e}")

    @property
    def data(self) -> ProactiveData:
        """Current data, reloaded from disk if the file changed."""
        return self._refresh()

    # ─────────────── Cron jobs ───────────────

    def get_jobs(
        self, frequency: Optional[str] = None, enabled_only: bool = True
    ) -> List[CronJob]:
        """Cron jobs, optionally filtered by frequency and enabled state."""
        jobs = self.data.jobs
        if enabled_only:
            jobs = [j for j in jobs if j.enabled]
        if frequency:
            jobs = [j for j in jobs if j.frequency == frequency]
        return jobs

    def get_job(self, job_id: str) -> Optional[CronJob]:
        """A cron job by ID, or None."""
        return self.data.get_job_by_id(job_id)

    def add_job(
        self,
        name: str,
        frequency: str,
        instruction: str,
        job_id: Optional[str] = None,
        time: Optional[str] = None,
        day: Optional[str] = None,
        priority: int = 50,
        permission_tier: int = 0,
        enabled: bool = True,
        conditions: Optional[List[Dict[str, Any]]] = None,
        session_id: str = MAIN_SESSION_ID,
    ) -> CronJob:
        """Add a new cron job.

        Args:
            name: Human-readable job name
            frequency: hourly, daily, weekly or monthly
            instruction: What the agent should do
            job_id: Optional custom ID (generated from frequency + name)
            time: Slot time HH:MM (hourly jobs use only the minute)
            day: Weekday name for weekly jobs, 1-31 for monthly jobs
            priority: Job priority (lower = higher)
            permission_tier: 0 = silent, 1 = notify
            enabled: Whether the job is active
            conditions: List of condition dictionaries
            session_id: The session the job runs in (the one adding it)

        Raises:
            ValueError: If the ID already exists or the schedule is invalid
        """
        validate_schedule_fields(frequency, time, day)
        data = self._refresh()

        if not job_id:
            job_id = f"{frequency}_{name.lower().replace(' ', '_')}"
        if data.get_job_by_id(job_id):
            raise ValueError(f"Cron job with ID '{job_id}' already exists")

        from .types import CronJobCondition

        job = CronJob(
            id=job_id,
            name=name,
            frequency=frequency,
            instruction=instruction,
            time=time,
            day=day,
            priority=priority,
            permission_tier=permission_tier,
            enabled=enabled,
            conditions=[CronJobCondition.from_dict(c.copy()) for c in conditions or []],
            session_id=session_id,
            active_since=datetime.now(),
        )

        data.jobs.append(job)
        self.save()
        logger.info(f"[PROACTIVE] Added cron job: {job_id}")
        return job

    def update_job(
        self,
        job_id: str,
        updates: Optional[Dict[str, Any]] = None,
        add_outcome: Optional[Dict[str, Any]] = None,
    ) -> Optional[CronJob]:
        """Update an existing cron job.

        Re-enabling a job, changing its frequency/time/day or moving it to
        another session restarts its schedule from now (``active_since``),
        so slots missed while it was off, unavailable or under the old
        schedule are not run late.

        Returns:
            The updated job if found, None otherwise
        """
        job = self._refresh().get_job_by_id(job_id)
        if not job:
            logger.warning(f"[PROACTIVE] Cron job not found: {job_id}")
            return None

        if updates:
            validate_schedule_fields(
                updates.get("frequency", job.frequency),
                updates.get("time", job.time),
                updates.get("day", job.day),
            )
            reschedules = any(
                key in updates and updates[key] != getattr(job, key)
                for key in ("frequency", "time", "day", "session_id")
            ) or (updates.get("enabled") is True and not job.enabled)
            for key, value in updates.items():
                if hasattr(job, key) and key not in [
                    "id",
                    "outcome_history",
                    "active_since",
                    "last_run",
                    "run_count",
                ]:
                    setattr(job, key, value)
            if reschedules:
                job.active_since = datetime.now()

        if add_outcome:
            job.add_outcome(
                result=add_outcome.get("result", ""),
                success=add_outcome.get("success", True),
            )

        self.save()
        logger.info(f"[PROACTIVE] Updated cron job: {job_id}")
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a cron job by ID. True if removed."""
        removed = self._refresh().remove_job(job_id)
        if removed:
            self.save()
            logger.info(f"[PROACTIVE] Removed cron job: {job_id}")
        else:
            logger.warning(f"[PROACTIVE] Cron job not found for removal: {job_id}")
        return removed

    def toggle_job(self, job_id: str, enabled: bool) -> Optional[CronJob]:
        """Enable or disable a cron job."""
        return self.update_job(job_id, updates={"enabled": enabled})

    # ─────────────── Due computation (code-owned) ───────────────

    def _valid_jobs(
        self, runnable: Optional[Callable[[CronJob], bool]] = None
    ) -> List[CronJob]:
        """Enabled (and runnable) cron jobs whose schedule fields are usable.

        A malformed hand-edited job is skipped with a warning instead of
        breaking every other job's schedule.
        """
        valid = []
        for job in self.get_jobs(enabled_only=True):
            if runnable is not None and not runnable(job):
                continue
            try:
                validate_schedule_fields(job.frequency, job.time, job.day)
            except ValueError as e:
                logger.warning(f"[PROACTIVE] Skipping cron job {job.id}: {e}")
                continue
            valid.append(job)
        return valid

    def get_due_jobs(
        self,
        now: Optional[datetime] = None,
        runnable: Optional[Callable[[CronJob], bool]] = None,
    ) -> List[CronJob]:
        """Cron jobs whose most recent slot is owed a run, by priority.

        ``runnable`` leaves out jobs that cannot run now (their session
        was deleted); they are not due and never stamped.
        """
        now = now or datetime.now()
        due = [j for j in self._valid_jobs(runnable) if j.is_due(now)]
        due.sort(key=lambda j: j.priority)
        return due

    def next_due_at(
        self,
        now: Optional[datetime] = None,
        runnable: Optional[Callable[[CronJob], bool]] = None,
    ) -> Optional[datetime]:
        """Earliest moment any enabled, runnable cron job becomes due."""
        now = now or datetime.now()
        times = [j.next_due_at(now) for j in self._valid_jobs(runnable)]
        times = [t for t in times if t is not None]
        return min(times) if times else None

    def mark_dispatched(self, job_ids: List[str], when: datetime) -> None:
        """Stamp last_run/run_count for jobs handed to a run, then save.

        Stamping at dispatch is what keeps a slot from running twice (a later
        check sees last_run >= slot), whatever the run itself does.
        """
        data = self._refresh()
        stamped = []
        for job_id in job_ids:
            job = data.get_job_by_id(job_id)
            if job is not None:
                job.mark_dispatched(when)
                stamped.append(job_id)
        if stamped:
            self.save()
            logger.info(
                f"[PROACTIVE] Dispatched {len(stamped)} cron job(s): {', '.join(stamped)}"
            )

    # ─────────────── Heartbeat checklist ───────────────

    def get_heartbeat_checklist(self) -> str:
        """The Heartbeat section's checklist ("" when empty)."""
        return self.data.heartbeat_checklist

    def set_heartbeat_checklist(self, checklist: str) -> None:
        """Replace the Heartbeat section's checklist and save."""
        data = self._refresh()
        data.heartbeat_checklist = (checklist or "").strip()
        self.save()
        logger.info("[PROACTIVE] Updated the heartbeat checklist")


# Singleton instance (initialized by AgentBase)
_manager: Optional[ProactiveManager] = None


def get_proactive_manager() -> Optional[ProactiveManager]:
    """Get the singleton proactive manager instance."""
    return _manager


def initialize_proactive_manager(file_path: Path) -> ProactiveManager:
    """Initialize the singleton proactive manager."""
    global _manager
    _manager = ProactiveManager(file_path)
    _manager.load()
    return _manager
