# -*- coding: utf-8 -*-
"""
core.trigger

Trigger dataclass - the entry point for all agent reactions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass(order=True)
class Trigger:
    """A trigger event that causes the agent to react.

    Triggers are the fundamental unit of work in the agent loop. They specify
    when the agent should act, what priority the action has, and what context
    is available for the action.

    Attributes:
        fire_at: Unix timestamp when this trigger should fire.
        priority: Lower values = higher priority. Used for ordering.
        next_action_description: Human-readable description of what action to take.
        payload: Additional context data for the action.
        session_id: Optional session identifier for multi-user scenarios.
        waiting_for_reply: Whether this trigger is waiting for a user response
            (used by CraftBot for multi-user chat scenarios).
        id: Durable-store row id when this trigger is backed by a TriggerStore
            row; None for in-memory-only triggers. Claim/ack/nack operate on
            this id (the queue holds at most one trigger per session, so one
            trigger maps to exactly one row).
        source: Typed origin of the trigger (TriggerSource value); empty for
            producers that haven't been migrated to TriggerService.
    """

    fire_at: float
    priority: int
    next_action_description: str
    payload: Dict[str, Any] = field(default_factory=dict, compare=False)
    session_id: Optional[str] = field(default=None, compare=False)
    waiting_for_reply: bool = field(default=False, compare=False)
    id: Optional[int] = field(default=None, compare=False)
    source: str = field(default="", compare=False)
