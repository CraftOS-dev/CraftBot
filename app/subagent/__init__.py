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
"""

from app.subagent.types import SubAgent, SUBAGENT_TYPES
from app.subagent.manager import SubAgentManager
from app.subagent.context_engine import SubAgentContextEngine
from app.subagent.runner import SubAgentRunner

__all__ = [
    "SubAgent",
    "SUBAGENT_TYPES",
    "SubAgentManager",
    "SubAgentContextEngine",
    "SubAgentRunner",
]
