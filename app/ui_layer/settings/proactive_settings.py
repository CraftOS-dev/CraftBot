"""Proactive and scheduler settings management for UI layer.

Provides functions for managing proactive tasks and scheduler configuration
that can be used by any interface adapter (Browser, TUI, CLI).
"""

import json
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List

from app.config import (
    AGENT_FILE_SYSTEM_PATH,
    AGENT_FILE_SYSTEM_TEMPLATE_PATH,
    PROJECT_ROOT,
    SETTINGS_CONFIG_PATH,
)


# Config paths
SCHEDULER_CONFIG_PATH = PROJECT_ROOT / "app" / "config" / "scheduler_config.json"


# ─────────────────────────────────────────────────────────────────────
# Proactive Mode Control
# ─────────────────────────────────────────────────────────────────────

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
        SETTINGS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
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
        return {
            "success": True,
            "enabled": enabled
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get proactive mode: {str(e)}"
        }


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
        return {
            "success": False,
            "error": f"Failed to set proactive mode: {str(e)}"
        }


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
            return {
                "success": False,
                "error": "Scheduler config not found"
            }

        with open(SCHEDULER_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        return {
            "success": True,
            "config": config
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read scheduler config: {str(e)}"
        }


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
            return {
                "success": False,
                "error": "Scheduler config not found"
            }

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
            "error": f"Failed to update scheduler config: {str(e)}"
        }


def toggle_schedule(schedule_id: str, enabled: bool) -> Dict[str, Any]:
    """Toggle a specific schedule on/off.

    Args:
        schedule_id: The schedule ID
        enabled: Whether to enable or disable

    Returns:
        Dict with 'success' and optional 'error' fields
    """
    return update_scheduler_config({
        "schedule_updates": {
            schedule_id: {"enabled": enabled}
        }
    })


async def toggle_schedule_runtime(
    scheduler_manager,
    schedule_id: str,
    enabled: bool
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
                "error": f"Config updated but runtime toggle failed: {str(e)}"
            }

    return {"success": True}


# ─────────────────────────────────────────────────────────────────────
# Proactive Tasks
# ─────────────────────────────────────────────────────────────────────

def get_proactive_tasks(
    proactive_manager,
    frequency: Optional[str] = None,
    enabled_only: bool = False
) -> Dict[str, Any]:
    """Get proactive tasks from PROACTIVE.md.

    Args:
        proactive_manager: The ProactiveManager instance
        frequency: Optional filter by frequency
        enabled_only: Whether to filter to enabled tasks only

    Returns:
        Dict with 'success', 'tasks' or 'error' fields
    """
    if not proactive_manager:
        return {
            "success": False,
            "error": "Proactive manager not initialized"
        }

    try:
        tasks = proactive_manager.get_tasks(
            frequency=frequency,
            enabled_only=enabled_only
        )

        # Convert to serializable format
        tasks_data = []
        for task in tasks:
            task_dict = {
                "id": task.id,
                "name": task.name,
                "frequency": task.frequency,
                "instruction": task.instruction,
                "time": task.time,
                "day": task.day,
                "priority": task.priority,
                "permission_tier": task.permission_tier,
                "enabled": task.enabled,
                "run_count": task.run_count,
                "conditions": [
                    {
                        "type": c.type,
                        **c.params  # Include all params from the condition
                    }
                    for c in (task.conditions or [])
                ],
                "last_executed": task.last_run.isoformat() if task.last_run else None,
                "outcome_history": [
                    {
                        "timestamp": o.timestamp.isoformat(),
                        "result": o.result,
                        "success": o.success
                    }
                    for o in (task.outcome_history or [])[-5:]  # Last 5 outcomes
                ]
            }
            tasks_data.append(task_dict)

        return {
            "success": True,
            "tasks": tasks_data
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get proactive tasks: {str(e)}"
        }


def add_proactive_task(
    proactive_manager,
    name: str,
    frequency: str,
    instruction: str,
    task_id: Optional[str] = None,
    time: Optional[str] = None,
    day: Optional[str] = None,
    priority: int = 50,
    permission_tier: int = 0,
    enabled: bool = True,
    conditions: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Add a new proactive task.

    Args:
        proactive_manager: The ProactiveManager instance
        name: Human-readable task name
        frequency: Execution frequency (hourly, daily, weekly, monthly)
        instruction: What the agent should do
        task_id: Optional custom ID
        time: Time of day for daily+ tasks (HH:MM)
        day: Day of week for weekly tasks
        priority: Task priority
        permission_tier: Permission level
        enabled: Whether task is active
        conditions: Optional conditions

    Returns:
        Dict with 'success', 'task' or 'error' fields
    """
    if not proactive_manager:
        return {
            "success": False,
            "error": "Proactive manager not initialized"
        }

    try:
        task = proactive_manager.add_task(
            name=name,
            frequency=frequency,
            instruction=instruction,
            task_id=task_id,
            time=time,
            day=day,
            priority=priority,
            permission_tier=permission_tier,
            enabled=enabled,
            conditions=conditions
        )

        return {
            "success": True,
            "task": {
                "id": task.id,
                "name": task.name,
                "frequency": task.frequency,
                "instruction": task.instruction,
                "enabled": task.enabled
            }
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e)
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to add proactive task: {str(e)}"
        }


def update_proactive_task(
    proactive_manager,
    task_id: str,
    updates: Dict[str, Any]
) -> Dict[str, Any]:
    """Update an existing proactive task.

    Args:
        proactive_manager: The ProactiveManager instance
        task_id: ID of task to update
        updates: Dict of fields to update

    Returns:
        Dict with 'success' or 'error' fields
    """
    if not proactive_manager:
        return {
            "success": False,
            "error": "Proactive manager not initialized"
        }

    try:
        task = proactive_manager.update_task(task_id, updates=updates)

        if task:
            return {
                "success": True,
                "task": {
                    "id": task.id,
                    "name": task.name,
                    "frequency": task.frequency,
                    "instruction": task.instruction,
                    "enabled": task.enabled
                }
            }
        else:
            return {
                "success": False,
                "error": f"Task not found: {task_id}"
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to update proactive task: {str(e)}"
        }


def remove_proactive_task(proactive_manager, task_id: str) -> Dict[str, Any]:
    """Remove a proactive task.

    Args:
        proactive_manager: The ProactiveManager instance
        task_id: ID of task to remove

    Returns:
        Dict with 'success' or 'error' fields
    """
    if not proactive_manager:
        return {
            "success": False,
            "error": "Proactive manager not initialized"
        }

    try:
        removed = proactive_manager.remove_task(task_id)

        if removed:
            return {"success": True}
        else:
            return {
                "success": False,
                "error": f"Task not found: {task_id}"
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to remove proactive task: {str(e)}"
        }


def toggle_proactive_task(
    proactive_manager,
    task_id: str,
    enabled: bool
) -> Dict[str, Any]:
    """Toggle a proactive task on/off.

    Args:
        proactive_manager: The ProactiveManager instance
        task_id: The task ID
        enabled: Whether to enable or disable

    Returns:
        Dict with 'success' or 'error' fields
    """
    return update_proactive_task(proactive_manager, task_id, {"enabled": enabled})


def reset_proactive_tasks() -> Dict[str, Any]:
    """Reset proactive tasks by restoring PROACTIVE.md from template.

    Returns:
        Dict with 'success', 'content' or 'error' fields
    """
    template_path = AGENT_FILE_SYSTEM_TEMPLATE_PATH / "PROACTIVE.md"
    target_path = AGENT_FILE_SYSTEM_PATH / "PROACTIVE.md"

    try:
        if not template_path.exists():
            return {
                "success": False,
                "error": "PROACTIVE.md template not found"
            }

        # Copy template to target
        shutil.copy(template_path, target_path)

        # Read restored content
        content = target_path.read_text(encoding="utf-8")

        return {
            "success": True,
            "content": content
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to reset proactive tasks: {str(e)}"
        }


def reload_proactive_manager(proactive_manager) -> Dict[str, Any]:
    """Reload the proactive manager from file.

    Call this after resetting proactive tasks to reload the manager.

    Args:
        proactive_manager: The ProactiveManager instance

    Returns:
        Dict with 'success' or 'error' fields
    """
    if not proactive_manager:
        return {
            "success": False,
            "error": "Proactive manager not initialized"
        }

    try:
        proactive_manager.load()
        return {"success": True}
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to reload proactive manager: {str(e)}"
        }
