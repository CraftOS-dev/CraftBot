# -*- coding: utf-8 -*-
"""
app.triggers.sources

Typed trigger sources and dedup-key builders.

Phase 1 defines only the sources migrated to TriggerService so far; Phase 2
extends this enum to every producer and removes the scattered
``payload["type"]`` string branching.
"""

from __future__ import annotations

from enum import Enum


class TriggerSource(str, Enum):
    """Typed origin of a trigger. Stored in the ``triggers.source`` column.

    Replaces the stringly-typed ``payload["type"]`` convention: every
    producer states its origin once, at emit time, instead of handlers
    string-matching payload fields across files.
    """

    # User input
    USER_MESSAGE = "user_message"
    # Scheduler
    SCHEDULED = "scheduled"
    SCHEDULED_ONCE = "scheduled_once"
    SCHEDULED_IMMEDIATE = "scheduled_immediate"
    # Task lifecycle
    TASK_CONTINUATION = "task_continuation"
    RESUME = "resume"
    RESTART_NOTICE = "restart_notice"
    LIMIT_REACHED = "limit_reached"
    # Background workflows
    MEMORY = "memory"
    PROACTIVE_HEARTBEAT = "proactive_heartbeat"
    PROACTIVE_PLANNER = "proactive_planner"
    ONBOARDING = "onboarding"
    SKILL_WORKFLOW = "skill_workflow"
    # Living UI
    LIVING_UI_DEV = "living_ui_dev"
    LIVING_UI_CRASH_FIX = "living_ui_crash_fix"
    LIVING_UI_IMPORT = "living_ui_import"
    LIVING_UI_ACTION = "living_ui_action"
    # Catch-all for producers not yet migrated to TriggerService.
    LEGACY = "legacy"


# Sources whose triggers start a freshly-created task get no dedup key: the
# task id itself is new each time, so the trigger's identity IS the task.
# Dedup keys exist for work whose identity predates the trigger (a schedule
# occurrence, a task resume) where a crash retry could mint a duplicate.


def scheduled_dedup_key(schedule_id: str, fire_target: float) -> str:
    """Dedup key for one fire of a recurring schedule.

    Bucketed to the scheduled minute: re-emitting the *same* fire (crash
    retry) dedups, while the next legitimate occurrence (a different
    minute) does not.
    """
    return f"scheduled:{schedule_id}:{int(fire_target // 60)}"


def scheduled_once_dedup_key(schedule_id: str) -> str:
    """Dedup key for a one-time scheduled task — one fire, ever, per id."""
    return f"scheduled-once:{schedule_id}"


def resume_dedup_key(task_id: str) -> str:
    """Dedup key for a boot-time task resume — double-boot can't double-resume."""
    return f"resume:{task_id}"


def living_ui_action_dedup_key(project_id: str, trigger_name: str) -> str:
    """Dedup key for an app-fired Living UI trigger that opens a new session.

    Scoped to (project, trigger): while one firing is still queued or in
    flight, re-fires of the same trigger dedup instead of stacking sessions.
    A new firing is allowed as soon as the previous one settles.
    """
    return f"living-ui-action:{project_id}:{trigger_name}"
