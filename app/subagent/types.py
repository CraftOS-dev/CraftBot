# -*- coding: utf-8 -*-
"""
Sub-agent runtime types.

Per-type configuration (system prompt, allowed actions, runtime caps)
lives with each type's workflow (``app/workflows/<domain>/subagents/``),
one file per sub-agent type registered via :mod:`app.subagent.registry`.
This module holds only the runtime objects that are agnostic to type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


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

    # Self-declared plan: [{"content": str, "status": "pending"|"in_progress"
    # |"completed"}]. Maintained via the sub_task_todos action; exit checks
    # can require completion before sub_task_end accepts "completed".
    todos: List[Dict[str, str]] = field(default_factory=list)
    # Files this agent wrote during the run (write_file/stream_edit paths),
    # recorded by the runner — exit checks scope tsc/pytest to these.
    written_files: List[str] = field(default_factory=list)
    # Every action name this agent has invoked this run, recorded by the
    # runner — lets exit checks require real work (e.g. that a coding agent
    # actually drove the browser before claiming a feature works).
    actions_run: List[str] = field(default_factory=list)
    # The subset of those attempts that came back status="error". Attempts
    # alone cannot tell "the agent never tried" from "the agent tried and the
    # tool is dead" — a distinction an exit check MUST make, or a broken tool
    # becomes an unsatisfiable gate the agent can only escape by failing.
    actions_failed: List[str] = field(default_factory=list)

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
