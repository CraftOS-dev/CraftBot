"""Proactive and scheduler settings management for UI layer.

Provides functions for managing proactive tasks and scheduler configuration
that can be used by any interface adapter (Browser, CLI).
"""

import json
import shutil
from typing import Dict, Any, Optional, List

from app.settings_store import settings_transaction, write_settings
from app.config import (
    AGENT_FILE_SYSTEM_PATH,
    AGENT_FILE_SYSTEM_TEMPLATE_PATH,
    PROJECT_ROOT,
    SETTINGS_CONFIG_PATH,
)


# Config paths
SCHEDULER_CONFIG_PATH = PROJECT_ROOT / "app" / "config" / "scheduler_config.json"

# Built-in schedule ids (scheduler_config.json)
HEARTBEAT_SCHEDULE_ID = "heartbeat"
DAY_PLANNER_SCHEDULE_ID = "day-planner"
WEEK_PLANNER_SCHEDULE_ID = "week-planner"
MONTH_PLANNER_SCHEDULE_ID = "month-planner"

WEEKDAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# How often the heartbeat checks for due or missed proactive tasks, in
# minutes. Tasks also fire at their exact time between checks.
HEARTBEAT_INTERVAL_OPTIONS = (5, 10, 15, 30, 60, 120)
HEARTBEAT_INTERVAL_DEFAULT = 30
DAY_PLANNER_HOUR_DEFAULT = 7
DAY_PLANNER_MINUTE_DEFAULT = 0
WEEK_PLANNER_DAY_DEFAULT = "sunday"
WEEK_PLANNER_HOUR_DEFAULT = 17
WEEK_PLANNER_MINUTE_DEFAULT = 0
MONTH_PLANNER_DAY_DEFAULT = 1
MONTH_PLANNER_HOUR_DEFAULT = 8
MONTH_PLANNER_MINUTE_DEFAULT = 0


def heartbeat_schedule_expression(minutes: int) -> str:
    """Clock-aligned cron for a heartbeat interval (e.g. 30 -> '*/30 * * * *')."""
    if minutes not in HEARTBEAT_INTERVAL_OPTIONS:
        raise ValueError(
            f"Heartbeat interval must be one of {HEARTBEAT_INTERVAL_OPTIONS} minutes"
        )
    if minutes < 60:
        return f"*/{minutes} * * * *"
    hours = minutes // 60
    return "0 * * * *" if hours == 1 else f"0 */{hours} * * *"


def heartbeat_interval_minutes(expression: str) -> Optional[int]:
    """The interval option a heartbeat expression encodes (None if custom)."""
    for minutes in HEARTBEAT_INTERVAL_OPTIONS:
        if heartbeat_schedule_expression(minutes) == expression.strip():
            return minutes
    return None


def _planner_time_phrase(hour: int, minute: int) -> str:
    from app.ui_layer.settings.memory_settings import _time_phrase

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Planner time must be a valid HH:MM")
    return _time_phrase(hour, minute)


def day_planner_schedule_expression(hour: int, minute: int) -> str:
    """Daily expression for the day planner (only the time is configurable)."""
    return f"every day at {_planner_time_phrase(hour, minute)}"


def week_planner_schedule_expression(weekday: str, hour: int, minute: int) -> str:
    """Weekly expression for the week planner (weekday + time)."""
    weekday = str(weekday).lower()
    if weekday not in WEEKDAY_NAMES:
        raise ValueError(f"Week planner day must be one of {WEEKDAY_NAMES}")
    return f"every {weekday} at {_planner_time_phrase(hour, minute)}"


def month_planner_schedule_expression(day: int, hour: int, minute: int) -> str:
    """Monthly expression for the month planner (day of month + time)."""
    if not (1 <= day <= 31):
        raise ValueError("Month planner day must be 1-31")
    return f"every month on day {day} at {_planner_time_phrase(hour, minute)}"


def get_proactive_schedule() -> Dict[str, Any]:
    """Heartbeat interval and planner times, read from the scheduler config."""
    from app.scheduler.parser import ScheduleParser, ScheduleParseError

    result = get_scheduler_config()
    if not result.get("success"):
        return result
    schedules = {s.get("id"): s for s in result["config"].get("schedules", [])}

    heartbeat = schedules.get(HEARTBEAT_SCHEDULE_ID) or {}
    minutes = heartbeat_interval_minutes(heartbeat.get("schedule", ""))

    def parsed(schedule_id: str, schedule_type: str):
        expression = (schedules.get(schedule_id) or {}).get("schedule", "")
        try:
            result = ScheduleParser.parse(expression)
        except ScheduleParseError:
            return None
        return result if result.schedule_type == schedule_type else None

    def clock(expr, hour_default: int, minute_default: int) -> str:
        hour, minute = (
            (expr.hour, expr.minute or 0) if expr else (hour_default, minute_default)
        )
        return f"{hour:02d}:{minute:02d}"

    day = parsed(DAY_PLANNER_SCHEDULE_ID, "daily")
    week = parsed(WEEK_PLANNER_SCHEDULE_ID, "weekly")
    month = parsed(MONTH_PLANNER_SCHEDULE_ID, "monthly")

    return {
        "success": True,
        "heartbeat_minutes": minutes or HEARTBEAT_INTERVAL_DEFAULT,
        "heartbeat_options": list(HEARTBEAT_INTERVAL_OPTIONS),
        "day_planner_time": clock(
            day, DAY_PLANNER_HOUR_DEFAULT, DAY_PLANNER_MINUTE_DEFAULT
        ),
        "week_planner_day": (
            WEEKDAY_NAMES[week.weekday] if week else WEEK_PLANNER_DAY_DEFAULT
        ),
        "week_planner_time": clock(
            week, WEEK_PLANNER_HOUR_DEFAULT, WEEK_PLANNER_MINUTE_DEFAULT
        ),
        "month_planner_day": (
            month.day_of_month if month else MONTH_PLANNER_DAY_DEFAULT
        ),
        "month_planner_time": clock(
            month, MONTH_PLANNER_HOUR_DEFAULT, MONTH_PLANNER_MINUTE_DEFAULT
        ),
    }


# ─────────────────────────────────────────────────────────────────────
# Proactive Mode Control
# ─────────────────────────────────────────────────────────────────────


@settings_transaction
def _load_settings() -> Dict[str, Any]:
    """Load settings from settings.json."""
    if not SETTINGS_CONFIG_PATH.exists():
        return {"proactive": {"enabled": True}, "general": {"agent_name": "CraftBot"}}

    try:
        with open(SETTINGS_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"proactive": {"enabled": True}, "general": {"agent_name": "CraftBot"}}


def _save_settings(settings: Dict[str, Any]) -> bool:
    """Save settings to settings.json."""
    try:
        write_settings(SETTINGS_CONFIG_PATH, settings)
        return True
    except Exception:
        return False


def is_proactive_enabled() -> bool:
    """Check if proactive mode is enabled.

    Returns:
        True if proactive mode is enabled, False otherwise.
    """
    settings = _load_settings()
    return settings.get("proactive", {}).get("enabled", True)


def get_proactive_mode() -> Dict[str, Any]:
    """Get the current proactive mode status.

    Returns:
        Dict with 'success' and 'enabled' fields.
    """
    try:
        enabled = is_proactive_enabled()
        return {"success": True, "enabled": enabled}
    except Exception as e:
        return {"success": False, "error": f"Failed to get proactive mode: {str(e)}"}


@settings_transaction
def set_proactive_mode(enabled: bool) -> Dict[str, Any]:
    """Set the proactive mode on or off.

    Args:
        enabled: True to enable proactive mode, False to disable.

    Returns:
        Dict with 'success' and optional 'error' fields.
    """
    try:
        settings = _load_settings()
        if "proactive" not in settings:
            settings["proactive"] = {}
        settings["proactive"]["enabled"] = enabled

        if _save_settings(settings):
            return {"success": True, "enabled": enabled}
        else:
            return {"success": False, "error": "Failed to save settings"}
    except Exception as e:
        return {"success": False, "error": f"Failed to set proactive mode: {str(e)}"}


# ─────────────────────────────────────────────────────────────────────
# Scheduler Configuration
# ─────────────────────────────────────────────────────────────────────


def get_scheduler_config() -> Dict[str, Any]:
    """Get the current scheduler configuration.

    Returns:
        Dict containing scheduler config with schedules
    """
    try:
        if not SCHEDULER_CONFIG_PATH.exists():
            return {"success": False, "error": "Scheduler config not found"}

        with open(SCHEDULER_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        return {"success": True, "config": config}
    except Exception as e:
        return {"success": False, "error": f"Failed to read scheduler config: {str(e)}"}


def update_scheduler_config(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update scheduler configuration.

    Args:
        updates: Dict of updates to apply. Can include:
            - enabled: bool - master enable/disable
            - schedule_updates: Dict[str, Dict] - per-schedule updates by ID

    Returns:
        Dict with 'success' and optional 'error' fields
    """
    try:
        if not SCHEDULER_CONFIG_PATH.exists():
            return {"success": False, "error": "Scheduler config not found"}

        # Read current config
        with open(SCHEDULER_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Apply master enabled update
        if "enabled" in updates:
            config["enabled"] = updates["enabled"]

        # Apply per-schedule updates
        if "schedule_updates" in updates:
            schedule_map = {s["id"]: s for s in config.get("schedules", [])}
            for schedule_id, schedule_updates in updates["schedule_updates"].items():
                if schedule_id in schedule_map:
                    schedule_map[schedule_id].update(schedule_updates)

            config["schedules"] = list(schedule_map.values())

        # Write updated config
        with open(SCHEDULER_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        return {"success": True}
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to update scheduler config: {str(e)}",
        }


def toggle_schedule(schedule_id: str, enabled: bool) -> Dict[str, Any]:
    """Toggle a specific schedule on/off.

    Args:
        schedule_id: The schedule ID
        enabled: Whether to enable or disable

    Returns:
        Dict with 'success' and optional 'error' fields
    """
    return update_scheduler_config(
        {"schedule_updates": {schedule_id: {"enabled": enabled}}}
    )


async def toggle_schedule_runtime(
    scheduler_manager, schedule_id: str, enabled: bool
) -> Dict[str, Any]:
    """Toggle a schedule in both config and runtime.

    This updates the config file AND the running scheduler manager.

    Args:
        scheduler_manager: The SchedulerManager instance
        schedule_id: The schedule ID
        enabled: Whether to enable or disable

    Returns:
        Dict with 'success' and optional 'error' fields
    """
    # Update config file
    result = toggle_schedule(schedule_id, enabled)
    if not result.get("success"):
        return result

    # Update runtime scheduler if manager is available
    if scheduler_manager:
        try:
            if enabled:
                scheduler_manager.enable_schedule(schedule_id)
            else:
                scheduler_manager.disable_schedule(schedule_id)
        except Exception as e:
            return {
                "success": False,
                "error": f"Config updated but runtime toggle failed: {str(e)}",
            }

    return {"success": True}


# ─────────────────────────────────────────────────────────────────────
# Cron Jobs and the Heartbeat checklist (PROACTIVE.md)
# ─────────────────────────────────────────────────────────────────────


def get_cron_jobs(
    proactive_manager,
    frequency: Optional[str] = None,
    enabled_only: bool = False,
) -> Dict[str, Any]:
    """Get the cron jobs from PROACTIVE.md.

    Returns:
        Dict with 'success', 'jobs' or 'error' fields
    """
    if not proactive_manager:
        return {"success": False, "error": "Proactive manager not initialized"}

    try:
        jobs_data = []
        for job in proactive_manager.get_jobs(
            frequency=frequency, enabled_only=enabled_only
        ):
            next_run = job.calculate_next_run()
            jobs_data.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "frequency": job.frequency,
                    "instruction": job.instruction,
                    "time": job.time,
                    "day": job.day,
                    "priority": job.priority,
                    "permission_tier": job.permission_tier,
                    "enabled": job.enabled,
                    "run_count": job.run_count,
                    "next_run": next_run.isoformat() if next_run else None,
                    "conditions": [
                        {"type": c.type, **c.params} for c in (job.conditions or [])
                    ],
                    "last_executed": job.last_run.isoformat() if job.last_run else None,
                    "outcome_history": [
                        {
                            "timestamp": o.timestamp.isoformat(),
                            "result": o.result,
                            "success": o.success,
                        }
                        for o in (job.outcome_history or [])[-5:]
                    ],
                }
            )
        return {"success": True, "jobs": jobs_data}
    except Exception as e:
        return {"success": False, "error": f"Failed to get cron jobs: {str(e)}"}


def add_cron_job(
    proactive_manager,
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
) -> Dict[str, Any]:
    """Add a cron job. Returns 'success' and 'job' or 'error'."""
    if not proactive_manager:
        return {"success": False, "error": "Proactive manager not initialized"}

    try:
        job = proactive_manager.add_job(
            name=name,
            frequency=frequency,
            instruction=instruction,
            job_id=job_id,
            time=time,
            day=day,
            priority=priority,
            permission_tier=permission_tier,
            enabled=enabled,
            conditions=conditions,
        )
        return {
            "success": True,
            "job": {
                "id": job.id,
                "name": job.name,
                "frequency": job.frequency,
                "instruction": job.instruction,
                "enabled": job.enabled,
            },
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Failed to add cron job: {str(e)}"}


def update_cron_job(
    proactive_manager, job_id: str, updates: Dict[str, Any]
) -> Dict[str, Any]:
    """Update a cron job. Returns 'success' and 'job' or 'error'."""
    if not proactive_manager:
        return {"success": False, "error": "Proactive manager not initialized"}

    try:
        job = proactive_manager.update_job(job_id, updates=updates)
        if not job:
            return {"success": False, "error": f"Cron job not found: {job_id}"}
        return {
            "success": True,
            "job": {
                "id": job.id,
                "name": job.name,
                "frequency": job.frequency,
                "instruction": job.instruction,
                "enabled": job.enabled,
            },
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to update cron job: {str(e)}"}


def remove_cron_job(proactive_manager, job_id: str) -> Dict[str, Any]:
    """Remove a cron job. Returns 'success' or 'error'."""
    if not proactive_manager:
        return {"success": False, "error": "Proactive manager not initialized"}

    try:
        if proactive_manager.remove_job(job_id):
            return {"success": True}
        return {"success": False, "error": f"Cron job not found: {job_id}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to remove cron job: {str(e)}"}


def toggle_cron_job(proactive_manager, job_id: str, enabled: bool) -> Dict[str, Any]:
    """Turn a cron job on or off."""
    return update_cron_job(proactive_manager, job_id, {"enabled": enabled})


def get_heartbeat_checklist(proactive_manager) -> Dict[str, Any]:
    """The Heartbeat checklist the heartbeat reads on every tick."""
    if not proactive_manager:
        return {"success": False, "error": "Proactive manager not initialized"}
    try:
        return {
            "success": True,
            "checklist": proactive_manager.get_heartbeat_checklist(),
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to read the checklist: {str(e)}"}


def set_heartbeat_checklist(proactive_manager, checklist: str) -> Dict[str, Any]:
    """Replace the Heartbeat checklist."""
    if not proactive_manager:
        return {"success": False, "error": "Proactive manager not initialized"}
    try:
        proactive_manager.set_heartbeat_checklist(checklist)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": f"Failed to save the checklist: {str(e)}"}


def reset_cron_jobs() -> Dict[str, Any]:
    """Reset cron jobs by restoring PROACTIVE.md from the template.

    Returns:
        Dict with 'success', 'content' or 'error' fields
    """
    template_path = AGENT_FILE_SYSTEM_TEMPLATE_PATH / "PROACTIVE.md"
    target_path = AGENT_FILE_SYSTEM_PATH / "PROACTIVE.md"

    try:
        if not template_path.exists():
            return {"success": False, "error": "PROACTIVE.md template not found"}

        # Copy template to target
        shutil.copy(template_path, target_path)

        # Read restored content
        content = target_path.read_text(encoding="utf-8")

        return {"success": True, "content": content}
    except Exception as e:
        return {"success": False, "error": f"Failed to reset cron jobs: {str(e)}"}


def reload_proactive_manager(proactive_manager) -> Dict[str, Any]:
    """Reload the proactive manager from file.

    Call this after resetting PROACTIVE.md to reload the manager.

    Args:
        proactive_manager: The ProactiveManager instance

    Returns:
        Dict with 'success' or 'error' fields
    """
    if not proactive_manager:
        return {"success": False, "error": "Proactive manager not initialized"}

    try:
        proactive_manager.load()
        return {"success": True}
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to reload proactive manager: {str(e)}",
        }
