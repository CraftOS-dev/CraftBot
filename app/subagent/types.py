# -*- coding: utf-8 -*-
"""
Sub-agent runtime types.

Per-type configuration (system prompt, allowed actions, runtime caps)
lives in :mod:`app.subagent.definitions`, with one file per sub-agent
type registered via :mod:`app.subagent.registry`. This module holds
only the runtime objects that are agnostic to type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


# ============================================================================
# Constants
# ============================================================================

# Subagent mode marker — anything that wants to detect sub-agent execution
# (state hooks, telemetry, etc.) can compare ``sub.mode == SUBAGENT_MODE``.
SUBAGENT_MODE = "subagent"

# Terminal statuses. Anything else means the runner should keep looping.
SUBAGENT_TERMINAL_STATUSES = {"completed", "failed", "timeout", "error"}


# ============================================================================
# SubAgent dataclass
# ============================================================================


@dataclass
class SubAgent:
    """
    A single sub-agent run.

    Deliberately small. Not a Task. Not registered with TaskManager. Not
    persisted across process restarts.

    Token usage is intentionally NOT tracked on this object — the LLM
    layer's existing ``task_attribution`` mechanism already rolls each
    sub-agent's tokens up to the parent task, which is the right
    granularity for billing. A separate per-sub-agent counter would be
    misleading because it would double-count cached tokens and miss
    provider-specific accounting.
    """

    id: str
    agent_type: str
    parent_task_id: Optional[str]
    query: str
    compiled_actions: List[str]

    # Lifecycle. Allowed statuses: running | completed | failed | timeout | error.
    status: str = "running"
    result: Optional[str] = None
    iterations: int = 0

    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    ended_at: Optional[str] = None

    # Mode marker — always ``SUBAGENT_MODE`` so downstream code can detect it.
    mode: str = SUBAGENT_MODE

    def is_terminal(self) -> bool:
        """True once the sub-agent has reached any terminal status."""
        return self.status in SUBAGENT_TERMINAL_STATUSES

    def terminate(self, status: str, result: str) -> None:
        """Set the terminal status, result, and ``ended_at`` atomically.

        This is the only mutation path used by :class:`SubAgentManager` to
        finalize a sub-agent. Keeping the three writes in one place lets a
        future change (e.g. emitting a state-change event) hook them as a
        single transition.
        """
        self.status = status
        self.result = result
        self.ended_at = datetime.utcnow().isoformat()


__all__ = [
    "SUBAGENT_MODE",
    "SUBAGENT_TERMINAL_STATUSES",
    "SubAgent",
]
