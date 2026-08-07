# -*- coding: utf-8 -*-
"""
app.triggers.sources

Typed trigger sources and dedup-key builders.
"""

from __future__ import annotations

from enum import Enum


class TriggerSource(str, Enum):
    """Typed origin of a trigger. Stored in the ``triggers.source`` column.

    Every producer states its origin once, at emit time, instead of handlers
    string-matching payload fields across files.
    """

    # User input
    USER_MESSAGE = "user_message"
    # Scheduler
    SCHEDULED = "scheduled"
    SCHEDULED_ONCE = "scheduled_once"
    SCHEDULED_IMMEDIATE = "scheduled_immediate"
    # Run lifecycle
    RUN_CONTINUATION = "run_continuation"
    RESTART_NOTICE = "restart_notice"
    LIMIT_REACHED = "limit_reached"
    # Background workflows (all land in the main session)
    MEMORY = "memory"
    PROACTIVE_HEARTBEAT = "proactive_heartbeat"
    PROACTIVE_PLANNER = "proactive_planner"
    ONBOARDING = "onboarding"
    SKILL_WORKFLOW = "skill_workflow"
    # Living UI (land in the project's session)
    LIVING_UI_DEV = "living_ui_dev"
    LIVING_UI_CRASH_FIX = "living_ui_crash_fix"
    LIVING_UI_IMPORT = "living_ui_import"
    # Lands in the ORIGIN session (the chat that ran living_ui_scaffold):
    # tells that agent the wizard finalized and which project resulted, so
    # later references ("add data to it") resolve without asking the user.
    LIVING_UI_CREATED = "living_ui_created"
    # A Living UI app fired a declared trigger at the agent (spec
    # TRIGGERS-PLAN): a validated agent_requests row exists and the bridge's
    # capability/consent/era gates all passed. Lands in the project's session.
    LIVING_UI_APP_REQUEST = "living_ui_app_request"
    # Catch-all for producers not yet migrated to TriggerService.
    LEGACY = "legacy"


# Dedup keys exist for work whose identity predates the trigger (a schedule
# occurrence) where a crash retry could mint a duplicate.


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
