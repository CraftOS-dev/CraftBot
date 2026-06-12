# -*- coding: utf-8 -*-
"""
app.triggers

Durable trigger execution (issue #321): typed sources, the SQLite-backed
TriggerStore, and the TriggerService producer/consumer front door.
"""

from app.triggers.sources import (
    TriggerSource,
    resume_dedup_key,
    scheduled_dedup_key,
    scheduled_once_dedup_key,
)
from app.triggers.store import TriggerStore, get_trigger_store
from app.triggers.service import EmitResult, TriggerService, TriggerSpec
from app.triggers.router import SessionRouter

__all__ = [
    "TriggerSource",
    "TriggerStore",
    "TriggerService",
    "TriggerSpec",
    "EmitResult",
    "SessionRouter",
    "get_trigger_store",
    "resume_dedup_key",
    "scheduled_dedup_key",
    "scheduled_once_dedup_key",
]
