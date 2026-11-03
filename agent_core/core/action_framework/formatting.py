# -*- coding: utf-8 -*-
"""
Shared formatters for action lists embedded in LLM prompts.

This module owns the canonical compact representation used to describe
available actions to the LLM. It is intentionally tight on tokens:

- One JSON object per action with ``name``, ``description``, ``params``,
  one action per line, without padding whitespace.
- Each parameter collapses to a single string ``"<type>, required|optional - <desc>"``,
  required or optional as its schema's ``required`` flag declares.
- A parameter every action of the list takes, with the same text, is written
  once above the list instead of in each action (e.g. an integration's
  ``account``).
- No ``example`` fields, no nested type-definitions.

Both ``ActionRouter`` (main agent) and ``SubAgentContextEngine`` (sub-agents)
should call ``format_action_candidates`` so the format stays in sync.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def candidate_dict_from_action(action) -> Dict[str, Any]:
    """Project an ``Action`` (or registry equivalent) into the candidate dict
    shape consumed by ``format_action_candidates``.

    Tolerates the duck-typed shape used throughout agent_core: anything with
    ``name``, ``description``, ``action_type``, ``input_schema``,
    ``output_schema`` attributes (or matching dict keys).
    """
    if isinstance(action, dict):
        return {
            "name": action.get("name"),
            "description": action.get("description", ""),
            "type": action.get("action_type") or action.get("type"),
            "input_schema": action.get("input_schema") or {},
            "output_schema": action.get("output_schema") or {},
        }
    return {
        "name": getattr(action, "name", None),
        "description": getattr(action, "description", "") or "",
        "type": getattr(action, "action_type", None),
        "input_schema": getattr(action, "input_schema", {}) or {},
        "output_schema": getattr(action, "output_schema", {}) or {},
    }


def format_action_candidates(candidates: List[Dict[str, Any]]) -> str:
    """Render a candidate list as the compact JSON block sent to the LLM.

    Args:
        candidates: List of dicts each with ``name``, ``description``,
            ``input_schema`` keys. Use :func:`candidate_dict_from_action`
            to build entries from ``Action`` objects.

    Returns:
        A JSON array of the candidates, one per line, preceded by a line
        listing the parameters every candidate takes when there are any.
        Returns ``"[]"`` when the list is empty.
    """
    if not candidates:
        return "[]"

    compact: List[Dict[str, Any]] = []
    for c in candidates:
        input_schema = c.get("input_schema") or {}
        params: Dict[str, str] = {}
        for param_name, param_def in input_schema.items():
            if isinstance(param_def, dict):
                ptype = param_def.get("type", "any")
                desc = param_def.get("description", "") or ""
                # Required or optional as the schema declares it. A schema
                # that declares neither gets no label: nothing is inferred.
                required = param_def.get("required")
                if isinstance(required, bool):
                    req = "required" if required else "optional"
                    params[param_name] = f"{ptype}, {req} - {desc}"
                else:
                    params[param_name] = f"{ptype} - {desc}"
            else:
                params[param_name] = str(param_def)

        compact.append(
            {
                "name": c.get("name"),
                "description": c.get("description", "") or "",
                "params": params,
            }
        )

    shared = _params_every_action_takes(compact)
    for entry in compact:
        for param_name in shared:
            del entry["params"][param_name]

    def dump(value) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    block = "[\n" + ",\n".join(dump(entry) for entry in compact) + "\n]"
    if shared:
        block = f"Every action below also takes these params: {dump(shared)}\n{block}"
    return block


def _params_every_action_takes(compact: List[Dict[str, Any]]) -> Dict[str, str]:
    """The parameters (name and rendered text) every action of the list has,
    in the first action's order. A list of one action shares nothing."""
    if len(compact) < 2:
        return {}
    first, rest = compact[0]["params"], compact[1:]
    return {
        name: text
        for name, text in first.items()
        if all(entry["params"].get(name) == text for entry in rest)
    }


def format_actions_by_name(
    action_names: List[str],
    action_library,
    *,
    on_missing: Optional[str] = None,
) -> str:
    """Convenience: look up actions by name and render them.

    Args:
        action_names: Ordered list of action names to include.
        action_library: Anything with ``retrieve_action(name) -> Action | None``.
        on_missing: Optional log-message prefix for actions that aren't found;
            when None, missing actions are silently skipped.

    Returns:
        Compact JSON block (or ``"[]"`` if nothing resolved).
    """
    candidates: List[Dict[str, Any]] = []
    for name in action_names:
        act = action_library.retrieve_action(name)
        if act is None:
            if on_missing is not None:
                # Use late import to avoid pulling logging deps at module load.
                from agent_core.utils.logger import logger

                logger.warning(f"{on_missing}: action {name!r} not found in library")
            continue
        candidates.append(candidate_dict_from_action(act))
    return format_action_candidates(candidates)


__all__ = [
    "candidate_dict_from_action",
    "format_action_candidates",
    "format_actions_by_name",
]
