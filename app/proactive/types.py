# -*- coding: utf-8 -*-
"""
Data types for PROACTIVE.md: cron jobs, their conditions and outcomes, and
the container for the whole file.
"""

from dataclasses import dataclass, field
import calendar
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


FREQUENCIES = ("hourly", "daily", "weekly", "monthly")
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def validate_schedule_fields(
    frequency: str, time: Optional[str], day: Optional[str]
) -> None:
    """Raise ValueError unless frequency/time/day describe a valid schedule.

    time: "HH:MM" 24-hour (hourly jobs use only the minute).
    day: weekday name for weekly jobs, 1-31 for monthly jobs.
    """
    if frequency not in FREQUENCIES:
        raise ValueError(f"Invalid frequency. Must be one of: {', '.join(FREQUENCIES)}")
    if time:
        parts = str(time).split(":")
        if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
            raise ValueError(f"time must be HH:MM (24-hour), got {time!r}")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"time must be HH:MM (24-hour), got {time!r}")
    if day:
        if frequency == "weekly" and str(day).lower() not in WEEKDAYS:
            raise ValueError(f"day must be a weekday name for weekly jobs, got {day!r}")
        if frequency == "monthly":
            if not str(day).isdigit() or not (1 <= int(day) <= 31):
                raise ValueError(f"day must be 1-31 for monthly jobs, got {day!r}")


def _month_slot(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """The job's slot in a given month, clamping day 29-31 to the month's end."""
    clamped = min(day, calendar.monthrange(year, month)[1])
    return datetime(year, month, clamped, hour, minute)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


@dataclass
class CronJobCondition:
    """Condition for a cron job run.

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
    def from_dict(cls, data: Dict[str, Any]) -> "CronJobCondition":
        """Create from dictionary."""
        condition_type = data.pop("type", "unknown")
        return cls(type=condition_type, params=data)


@dataclass
class CronJobOutcome:
    """Record of a cron job run.

    Attributes:
        timestamp: When the job was executed
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
    def from_dict(cls, data: Dict[str, Any]) -> "CronJobOutcome":
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
class CronJob:
    """Definition of a cron job.

    Scheduling is slot-based and owned by code, never by the model. Every
    job has a fixed slot per period (hourly at :MM, daily at HH:MM, weekly
    on a weekday at HH:MM, monthly on a date at HH:MM; HH:MM defaults to
    00:00, weekly to Monday, monthly to the 1st). A job is due when its most
    recent slot is at or after ``active_since`` and it has not been
    dispatched since that slot. Missed slots are not replayed one by one:
    only the most recent one runs, late, the next time CraftBot checks.

    Attributes:
        id: Unique identifier for the job
        name: Human-readable job name
        frequency: Execution frequency (hourly, daily, weekly, monthly)
        instruction: What the agent should do
        enabled: Whether the job is active
        priority: Job priority (lower = higher priority)
        permission_tier: Permission level (0 = silent, 1 = notify)
        time: HH:MM slot time (hourly jobs use only the minute)
        day: Weekday name for weekly jobs, 1-31 for monthly jobs
        conditions: List of conditions that must be met
        active_since: When the current schedule took effect (created,
            re-enabled or rescheduled); slots before it never run
        last_run: When the job was last dispatched (stamped by code)
        run_count: Number of times the job has been dispatched
        outcome_history: Recent execution outcomes (limited to last 5)
    """

    id: str
    name: str
    frequency: str  # hourly, daily, weekly, monthly
    instruction: str
    enabled: bool = True
    priority: int = 50
    permission_tier: int = 0
    time: Optional[str] = None  # HH:MM
    day: Optional[str] = None  # weekday name (weekly) or 1-31 (monthly)
    conditions: List[CronJobCondition] = field(default_factory=list)
    active_since: Optional[datetime] = None
    last_run: Optional[datetime] = None
    run_count: int = 0
    outcome_history: List[CronJobOutcome] = field(default_factory=list)

    MAX_OUTCOME_HISTORY = 5

    # ─────────────── Slots ───────────────

    def _hour_minute(self) -> tuple[int, int]:
        if not self.time:
            return 0, 0
        hour, minute = (int(p) for p in str(self.time).split(":"))
        return hour, minute

    def _weekday(self) -> int:
        name = (self.day or "monday").lower()
        return WEEKDAYS.index(name) if name in WEEKDAYS else 0

    def _month_day(self) -> int:
        try:
            return int(self.day) if self.day else 1
        except ValueError:
            return 1

    def latest_slot(self, now: datetime) -> datetime:
        """The most recent slot at or before ``now``."""
        hour, minute = self._hour_minute()
        if self.frequency == "hourly":
            slot = now.replace(minute=minute, second=0, microsecond=0)
            return slot if slot <= now else slot - timedelta(hours=1)
        if self.frequency == "daily":
            slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return slot if slot <= now else slot - timedelta(days=1)
        if self.frequency == "weekly":
            back = (now.weekday() - self._weekday()) % 7
            slot = (now - timedelta(days=back)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            return slot if slot <= now else slot - timedelta(weeks=1)
        if self.frequency == "monthly":
            day = self._month_day()
            slot = _month_slot(now.year, now.month, day, hour, minute)
            if slot <= now:
                return slot
            year, month = _shift_month(now.year, now.month, -1)
            return _month_slot(year, month, day, hour, minute)
        raise ValueError(f"Unknown frequency: {self.frequency}")

    def next_slot(self, now: datetime) -> datetime:
        """The earliest slot strictly after ``now``."""
        hour, minute = self._hour_minute()
        if self.frequency == "hourly":
            slot = now.replace(minute=minute, second=0, microsecond=0)
            return slot if slot > now else slot + timedelta(hours=1)
        if self.frequency == "daily":
            slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return slot if slot > now else slot + timedelta(days=1)
        if self.frequency == "weekly":
            ahead = (self._weekday() - now.weekday()) % 7
            slot = (now + timedelta(days=ahead)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            return slot if slot > now else slot + timedelta(weeks=1)
        if self.frequency == "monthly":
            day = self._month_day()
            slot = _month_slot(now.year, now.month, day, hour, minute)
            if slot > now:
                return slot
            year, month = _shift_month(now.year, now.month, 1)
            return _month_slot(year, month, day, hour, minute)
        raise ValueError(f"Unknown frequency: {self.frequency}")

    def is_due(self, now: Optional[datetime] = None) -> bool:
        """Whether the most recent slot is owed a run."""
        if not self.enabled:
            return False
        now = now or datetime.now()
        slot = self.latest_slot(now)
        if self.active_since is not None and slot < self.active_since:
            return False
        if self.last_run is not None and self.last_run >= slot:
            return False
        return True

    def next_due_at(self, now: Optional[datetime] = None) -> Optional[datetime]:
        """When the job next becomes due: ``now`` if it is due already,
        None while disabled."""
        if not self.enabled:
            return None
        now = now or datetime.now()
        if self.is_due(now):
            return now
        start = now
        if self.active_since is not None and self.active_since > start:
            start = self.active_since
        return self.next_slot(start)

    def calculate_next_run(self) -> Optional[datetime]:
        """Next execution time for display (None for disabled jobs)."""
        return self.next_due_at()

    def mark_dispatched(self, when: datetime) -> None:
        """Record that a run for the current slot was dispatched."""
        self.last_run = when
        self.run_count += 1

    def add_outcome(self, result: str, success: bool = True) -> None:
        """Add an execution outcome to history.

        Outcomes are a log only. Dispatch (last_run / run_count) is stamped
        by code in mark_dispatched, so recording an outcome never changes
        when the job runs next.
        """
        outcome = CronJobOutcome(
            timestamp=datetime.now(), result=result, success=success
        )
        self.outcome_history.append(outcome)

        # Keep only the last N outcomes
        if len(self.outcome_history) > self.MAX_OUTCOME_HISTORY:
            self.outcome_history = self.outcome_history[-self.MAX_OUTCOME_HISTORY :]

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
        if self.active_since:
            data["active_since"] = self.active_since.isoformat()
        if self.last_run:
            data["last_run"] = self.last_run.isoformat()
        if self.outcome_history:
            data["outcome_history"] = [o.to_dict() for o in self.outcome_history]
        else:
            data["outcome_history"] = []

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any], name: str = "") -> "CronJob":
        """Create from dictionary (parsed from YAML).

        Args:
            data: Dictionary with job data
            name: Job name (from section header)

        Returns:
            CronJob instance
        """

        def _when(value: Any) -> Optional[datetime]:
            if isinstance(value, datetime):
                return value.replace(tzinfo=None)
            if isinstance(value, str):
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
            return None

        # Parse conditions
        conditions = []
        for c in data.get("conditions", []):
            if isinstance(c, dict):
                conditions.append(CronJobCondition.from_dict(c.copy()))

        # Parse outcome history
        outcomes = []
        for o in data.get("outcome_history", []):
            if isinstance(o, dict):
                outcomes.append(CronJobOutcome.from_dict(o))

        time_value = data.get("time")
        if isinstance(time_value, int) and not isinstance(time_value, bool):
            # YAML 1.1 reads an unquoted 09:00 as base-60 (540).
            time_value = "%02d:%02d" % divmod(time_value, 60)
        day_value = data.get("day")
        return cls(
            id=data.get("id", ""),
            name=name,
            frequency=data.get("frequency", "daily"),
            instruction=data.get("instruction", ""),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 50),
            permission_tier=data.get("permission_tier", 0),
            time=str(time_value) if time_value is not None else None,
            day=str(day_value) if day_value is not None else None,
            conditions=conditions,
            active_since=_when(data.get("active_since")),
            last_run=_when(data.get("last_run")),
            run_count=data.get("run_count", 0),
            outcome_history=outcomes,
        )


@dataclass
class ProactiveData:
    """Everything code reads from PROACTIVE.md.

    Attributes:
        version: Format version
        last_updated: When the file was last updated
        jobs: The cron jobs (the "Cron Jobs" section)
        heartbeat_checklist: The checklist the heartbeat reads (the
            "Heartbeat" section), as written, without its marker comments
    """

    version: str = "1.0"
    last_updated: Optional[datetime] = None
    jobs: List[CronJob] = field(default_factory=list)
    heartbeat_checklist: str = ""

    def get_job_by_id(self, job_id: str) -> Optional[CronJob]:
        """Find a cron job by its ID."""
        for job in self.jobs:
            if job.id == job_id:
                return job
        return None

    def remove_job(self, job_id: str) -> bool:
        """Remove a cron job by ID. True if it was removed."""
        for i, job in enumerate(self.jobs):
            if job.id == job_id:
                self.jobs.pop(i)
                self.last_updated = datetime.now()
                return True
        return False
