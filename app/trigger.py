# -*- coding: utf-8 -*-
"""
app.trigger

Trigger in this framework is the entry point of ALL reactions by the agent.

This module re-exports Trigger and TriggerQueue from agent_core.
"""
from __future__ import annotations

# Re-export from agent_core
from agent_core import Trigger, TriggerQueue

__all__ = [
    "Trigger",
    "TriggerQueue",
]
