# -*- coding: utf-8 -*-
"""
Sub-agent data types and per-type registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, TypedDict


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


# ============================================================================
# Per-type registry
# ============================================================================


class SubAgentConfig(TypedDict):
    """Frozen per-type configuration for a sub-agent.

    Fields:
        system_prompt_key: Name in :data:`agent_core.core.prompts.PromptRegistry`
            that may override the default. The default value is the
            module-level constant referenced by this key in
            ``agent_core/core/prompts/subagent.py``.
        actions: Frozen list of action names this type may invoke. The runner
            refuses any action outside this set.
        max_iterations: Hard cap on action turns before the runner ends the
            sub-agent as ``failed``.
        max_wall_seconds: Hard cap on wall-clock execution before the runner
            ends the sub-agent as ``timeout``.
    """

    system_prompt_key: str
    actions: List[str]
    max_iterations: int
    max_wall_seconds: int


# Adding a new type means: add an entry here, define its prompt in
# ``agent_core/core/prompts/subagent.py``, and make sure every action in its
# ``actions`` list is registered in the action library.
SUBAGENT_TYPES: Dict[str, SubAgentConfig] = {
    "research_agent": {
        "system_prompt_key": "RESEARCH_AGENT_SYSTEM_PROMPT",
        "actions": [
            "web_search",
            "web_fetch",
            "http_request",
            "convert_to_markdown",
            "sub_task_end",
        ],
        "max_iterations": 20,
        "max_wall_seconds": 300,
    },
    "validation_agent": {
        "system_prompt_key": "VALIDATION_AGENT_SYSTEM_PROMPT",
        "actions": [
            "read_file",
            "find_files",
            "grep_files",
            "list_folder",
            "run_python",
            "run_shell",
            "sub_task_end",
        ],
        "max_iterations": 25,
        "max_wall_seconds": 600,
    },
}


def get_subagent_config(agent_type: str) -> SubAgentConfig:
    """Look up a sub-agent type's config or raise ``ValueError``."""
    cfg = SUBAGENT_TYPES.get(agent_type)
    if cfg is None:
        raise ValueError(
            f"Unknown sub-agent type: {agent_type!r}. "
            f"Known types: {sorted(SUBAGENT_TYPES.keys())}"
        )
    return cfg


__all__ = [
    "SUBAGENT_MODE",
    "SUBAGENT_TERMINAL_STATUSES",
    "SubAgent",
    "SubAgentConfig",
    "SUBAGENT_TYPES",
    "get_subagent_config",
]
