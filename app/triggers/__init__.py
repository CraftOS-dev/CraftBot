# -*- coding: utf-8 -*-
"""
app.triggers

Durable trigger execution: typed sources, the SQLite-backed TriggerStore,
the TriggerService producer front door, and the per-session runtime
(SessionRuntimeManager) that drives one serial agent loop per session.
"""

from app.triggers.sources import (
    TriggerSource,
    scheduled_dedup_key,
    scheduled_once_dedup_key,
)
from app.triggers.store import TriggerStore, get_trigger_store
from app.triggers.service import EmitResult, TriggerService, TriggerSpec
from app.triggers.runtime import SessionRuntimeManager

__all__ = [
    "TriggerSource",
    "TriggerStore",
    "TriggerService",
    "TriggerSpec",
    "EmitResult",
    "SessionRuntimeManager",
    "get_trigger_store",
    "scheduled_dedup_key",
    "scheduled_once_dedup_key",
]
