# -*- coding: utf-8 -*-
"""
Trigger queue implementation module.

Provides SessionTriggerQueue — the per-session trigger ordering primitive.
"""

from agent_core.core.impl.trigger.session_queue import SessionTriggerQueue, QueueClosed

__all__ = [
    "SessionTriggerQueue",
    "QueueClosed",
]
