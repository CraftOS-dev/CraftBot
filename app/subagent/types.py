# -*- coding: utf-8 -*-
"""
Sub-agent runtime record.

Per-type configuration (system prompt, allowed actions, runtime caps) lives
in :mod:`app.subagent.definitions`, one file per type registered through
:mod:`app.subagent.registry`. This module holds only the record of one run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


# Terminal statuses. Anything else means the sub-agent is still running.
SUBAGENT_TERMINAL_STATUSES = frozenset({"completed", "failed", "timeout", "error"})


@dataclass
class SubAgent:
    """
    A single sub-agent run.

    Not a Session: it is never persisted, never listed in the UI and lives
    only until its run ends. Its LLM usage is attributed to the spawning
    session by the LLM layer.
    """

    id: str
    agent_type: str
    # The session whose turn spawned it (None: none, the main session's
    # workspace and browser are used).
    parent_session_id: Optional[str]
    query: str
    compiled_actions: List[str]

    # Lifecycle. Allowed statuses: running | completed | failed | timeout | error.
    status: str = "running"
    result: Optional[str] = None
    # Turns taken (each turn is one decision, which may batch actions).
    iterations: int = 0

    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    ended_at: Optional[str] = None

    def is_terminal(self) -> bool:
        """True once the sub-agent has reached any terminal status."""
        return self.status in SUBAGENT_TERMINAL_STATUSES

    def terminate(self, status: str, result: str) -> None:
        """Set the terminal status, result, and ``ended_at`` together."""
        self.status = status
        self.result = result
        self.ended_at = datetime.utcnow().isoformat()


__all__ = [
    "SUBAGENT_TERMINAL_STATUSES",
    "SubAgent",
]
