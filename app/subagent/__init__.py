# -*- coding: utf-8 -*-
"""
Sub-agent system for CraftBot.

A sub-agent is an isolated agent that a session's turn spawns through the
``spawn_subagent`` action (or the Agent-App verifier) to do one focused job
in its own context. It works like the main agent — the same decision loop
(ActionRouter), turn step (AgentStep) and action execution — on a context of
its own:

- its type's system prompt and actions (:mod:`app.subagent.definitions`),
  nothing of the main agent's persona, memory or skills;
- its own event stream and LLM session history, keyed on the sub-agent id;
- only the query from its parent, and only its ``result`` back.

Sub-agents are NOT Sessions: they live in :class:`SubAgentManager`, so none
of the UI / chatserver / SessionStorage side effects fire. Importing this
package registers every type in :mod:`app.subagent.definitions`.
"""

from app.subagent.types import SubAgent
from app.subagent.registry import (
    SUB_TASK_END_ACTION,
    SubAgentDefinition,
    register_subagent,
    get_subagent_definition,
    list_subagent_names,
)

# Importing the definitions package runs each definition module, which
# calls ``register_subagent`` at module-import time. After this point,
# ``list_subagent_names()`` returns every registered type.
from app.subagent import definitions  # noqa: F401

from app.subagent.context_engine import SubAgentContextEngine
from app.subagent.runner import SubAgentRunner
from app.subagent.manager import SubAgentManager


__all__ = [
    # Runtime record
    "SubAgent",
    # Registry
    "SUB_TASK_END_ACTION",
    "SubAgentDefinition",
    "register_subagent",
    "get_subagent_definition",
    "list_subagent_names",
    # Components
    "SubAgentContextEngine",
    "SubAgentRunner",
    "SubAgentManager",
]
