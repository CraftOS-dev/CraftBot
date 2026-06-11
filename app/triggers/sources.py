# -*- coding: utf-8 -*-
"""
app.triggers.sources

Typed trigger sources and dedup-key builders (issue #321).

Phase 1 defines only the sources migrated to TriggerService so far; Phase 2
extends this enum to every producer and removes the scattered
``payload["type"]`` string branching.
"""

from __future__ import annotations

from enum import Enum


class TriggerSource(str, Enum):
    """Typed origin of a trigger. Stored in the ``triggers.source`` column."""

    SCHEDULED = "scheduled"
    SCHEDULED_ONCE = "scheduled_once"
    SCHEDULED_IMMEDIATE = "scheduled_immediate"
    RESUME = "resume"
    RESTART_NOTICE = "restart_notice"
    # Catch-all for producers not yet migrated to TriggerService.
    LEGACY = "legacy"


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
