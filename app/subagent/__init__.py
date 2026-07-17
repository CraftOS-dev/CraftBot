# -*- coding: utf-8 -*-
"""
Sub-agent system for CraftBot.

A sub-agent is a lightweight, isolated agent that the main agent (or a
task) can spawn through the ``spawn_subagent`` action to do a focused job
in its own context.

Key isolation properties:

- Sub-agents are NOT Tasks. They live in :class:`SubAgentManager`, not in
  ``TaskManager.tasks``, so none of the UI / chatserver / SessionStorage
  side effects fire.
- Each sub-agent has its own per-id event stream (via the existing
  ``EventStreamManager._task_streams`` buffer) and its own LLM session
  caches keyed on the sub-agent id.
- Each sub-agent type has a hard-coded action list and a minimal,
  type-specific system prompt — no memory, no skills, no soul.md.

Only ``result`` is fed back to the spawning agent as the action output.

Per-type configuration (system prompt, allowed actions, runtime caps) is
defined one file per type, living with the WORKFLOW that owns it:
``app/workflows/<domain>/subagents/*.py`` (cross-domain ones under
``app/workflows/common/subagents/``). Importing this package triggers all
those modules to register themselves with :mod:`app.subagent.registry`.
"""

from app.subagent.types import (
    SubAgent,
    SUBAGENT_MODE,
    SUBAGENT_TERMINAL_STATUSES,
)
from app.subagent.registry import (
    SUB_TASK_END_ACTION,
    SubAgentDefinition,
    register_subagent,
    get_subagent_definition,
    list_subagent_names,
    is_subagent_registered,
)

# Registration trigger: importing the workflow packages runs each
# definition module, which calls ``register_subagent`` at import time —
# BEFORE the action registry builds ``spawn_subagent``'s type enum. After
# this point, ``list_subagent_names()`` returns every registered type.
from app.workflows.common.subagents import research_agent  # noqa: F401
from app.workflows import living_ui  # noqa: F401

from app.subagent.manager import SubAgentManager
from app.subagent.context_engine import SubAgentContextEngine, SUBAGENT_OUTPUT_FORMAT
from app.subagent.runner import SubAgentRunner


__all__ = [
    # Runtime types
    "SubAgent",
    "SUBAGENT_MODE",
    "SUBAGENT_TERMINAL_STATUSES",
    # Registry
    "SUB_TASK_END_ACTION",
    "SubAgentDefinition",
    "register_subagent",
    "get_subagent_definition",
    "list_subagent_names",
    "is_subagent_registered",
    # Components
    "SubAgentManager",
    "SubAgentContextEngine",
    "SubAgentRunner",
    "SUBAGENT_OUTPUT_FORMAT",
]
