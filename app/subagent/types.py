# -*- coding: utf-8 -*-
"""
Sub-agent data types and per-type registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


# ============================================================================
# SubAgent dataclass
# ============================================================================

# Subagent mode constant — kept here so anything else that wants to detect
# sub-agent execution can import it without pulling in the manager/runner.
SUBAGENT_MODE = "subagent"

# Terminal statuses. Anything else means the runner should keep looping.
SUBAGENT_TERMINAL_STATUSES = {"completed", "failed", "timeout", "error"}


@dataclass
class SubAgent:
    """
    A single sub-agent run.

    Deliberately small. Not a Task. Not registered with TaskManager. Not
    persisted across process restarts.

    Token usage is intentionally NOT tracked on this object — the LLM
    layer's existing ``task_attribution`` mechanism already rolls each
    sub-agent's tokens up to the parent task, which is the right granularity
    for billing. A separate per-sub-agent counter would be misleading
    because it would double-count cached tokens and miss provider-specific
    accounting.
    """

    id: str
    agent_type: str
    parent_task_id: Optional[str]
    query: str
    compiled_actions: List[str]

    status: str = "running"  # running | completed | failed | timeout | error
    result: Optional[str] = None
    iterations: int = 0

    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    ended_at: Optional[str] = None

    # Mode marker — always "subagent" so downstream code can detect it.
    mode: str = SUBAGENT_MODE

    def is_terminal(self) -> bool:
        return self.status in SUBAGENT_TERMINAL_STATUSES


# ============================================================================
# Per-type registry
# ============================================================================
#
# Each entry defines:
#   system_prompt_key   — name in agent_core.core.prompts.PromptRegistry that
#                         can override the default; default is taken from the
#                         module-level constant in agent_core/core/prompts/subagent.py
#   default_system_prompt — the fallback prompt string (referenced by key)
#   actions             — FROZEN list of action names this type may use. The
#                         runner refuses anything else.
#   max_iterations      — hard cap on action turns
#   max_wall_seconds    — hard cap on wall-clock execution time
#
# Adding a new type means adding an entry here, defining its prompt in
# agent_core/core/prompts/subagent.py, and (optionally) ensuring every action
# in its `actions` list already exists in the action library.


SUBAGENT_TYPES: Dict[str, Dict] = {
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


def get_subagent_config(agent_type: str) -> Dict:
    """Look up a sub-agent type's config or raise."""
    if agent_type not in SUBAGENT_TYPES:
        raise ValueError(
            f"Unknown sub-agent type: {agent_type!r}. "
            f"Known types: {sorted(SUBAGENT_TYPES.keys())}"
        )
    return SUBAGENT_TYPES[agent_type]


__all__ = [
    "SUBAGENT_MODE",
    "SUBAGENT_TERMINAL_STATUSES",
    "SubAgent",
    "SUBAGENT_TYPES",
    "get_subagent_config",
]
