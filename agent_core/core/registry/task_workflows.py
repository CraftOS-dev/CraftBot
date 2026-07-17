# -*- coding: utf-8 -*-
"""Workflow registry — the string→object map for deterministic task workflows.

A task persists across restarts, so it can only carry a NAME
(``Task.workflow_id``); this registry turns that name back into the live
workflow object. The objects themselves are deterministic workflows
defined app-side (see :mod:`app.workflows.workflow` — ``Task → workflow
→ actions``); the core stays domain-free and duck-types the few
attributes it reads each turn:

- ``system_prompt``       — replaces the general system prompt verbatim.
- ``select_action_prompt``— optional per-turn protocol replacement.
- ``include_skills`` / ``inject_essentials`` / ``inject_memory`` — context
  injection opt-outs.
- ``task_state(task)``    — optional per-turn computed context block.
- ``step(task, turn_context)`` — the deterministic step for this turn, or
  None (= the LLM decides). Consulted before any LLM decision.

``get_workflow`` returning ``None`` means "no workflow — behave exactly as
today", so every consumer is fail-open by construction.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_REGISTRY: Dict[str, Any] = {}

# The attribute surface the core consumes each turn. Validated at
# registration so a bad definition fails loudly at import time, not
# silently at task time.
_REQUIRED = ("name", "system_prompt", "step")


def register_workflow(workflow: Any, *, alias: Optional[str] = None) -> None:
    """Register a workflow instance (a steps-workflow object).

    ``alias``: optional additional name resolving to the same instance —
    keeps PERSISTED tasks working across a workflow rename (tasks carry
    the id string across restarts).

    Raises on a missing surface or duplicate/empty names."""
    for attr in _REQUIRED:
        if not hasattr(workflow, attr):
            raise TypeError(
                f"register_workflow expects an object with '{attr}' "
                f"(a steps workflow); got {type(workflow).__name__}"
            )
    name = (workflow.name or "").strip()
    if not name:
        raise ValueError("Workflow name must be non-empty")
    if name in _REGISTRY:
        raise ValueError(
            f"Workflow {name!r} is already registered. Each definition "
            "module should call register_workflow exactly once."
        )
    if not (workflow.system_prompt or "").strip():
        raise ValueError(f"Workflow {name!r} has an empty system_prompt")
    if not callable(workflow.step):
        raise TypeError(f"Workflow {name!r}.step must be callable")
    _REGISTRY[name] = workflow
    if alias:
        alias = alias.strip()
        if alias and alias != name and alias not in _REGISTRY:
            _REGISTRY[alias] = workflow


def get_workflow(name: Optional[str]) -> Optional[Any]:
    """The workflow for ``name``, or None (= default task behavior).

    Safe to call with None/unknown ids; every caller treats None as
    "no override"."""
    if not name:
        return None
    return _REGISTRY.get(name)


def resolve_task_workflow(task: Optional[Any]) -> Optional[Any]:
    """The workflow attached to ``task`` via its ``workflow_id``, or None.

    The one canonical way consumers go from a persisted task back to its
    live workflow object. Safe on None tasks and tasks without the field."""
    if task is None:
        return None
    return get_workflow(getattr(task, "workflow_id", None))


def list_workflow_names() -> List[str]:
    return sorted(_REGISTRY)
