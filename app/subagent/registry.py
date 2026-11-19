# -*- coding: utf-8 -*-
"""
Sub-agent registry.

Every sub-agent type lives in its own module under :mod:`app.subagent.definitions`
and calls :func:`register_subagent` at import time. That gives each type a
single place where its prompt, allowed actions, and runtime caps are
defined.

``sub_task_end`` is the universal terminator action. The registry appends
it to every definition's action list automatically; it must NEVER be
listed by the definition itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Dict, Iterable, List, Optional, Tuple

if TYPE_CHECKING:
    from app.subagent.types import SubAgent

from app.logger import logger


# The action that ends a sub-agent's run. Auto-injected by the registry so
# definitions cannot accidentally omit it or list it twice.
SUB_TASK_END_ACTION = "sub_task_end"

# A veto on premature sub_task_end calls: (sub, parameters) → rejection text,
# or None to allow the end.
EarlyEndGuard = Callable[["SubAgent", Dict[str, object]], Optional[str]]


@dataclass(frozen=True)
class SubAgentDefinition:
    """Frozen per-type configuration.

    Fields:
        name: The agent_type string used by ``spawn_subagent``.
        description: One short sentence describing what this type does and
            any special query requirement (e.g. "must include a DoD").
            Shown to the spawning agent in the ``spawn_subagent`` action's
            description — keep it tight: ~80–120 chars, no trailing period
            needed.
        system_prompt: The type's own system prompt: its role, workflow,
            rules and ending. The runtime appends the decision instructions
            (batching rules, reply format, the <actions> list) and the
            environment, so the prompt never lists actions or the format.
        actions: Frozen tuple of action names this type may invoke,
            INCLUDING ``sub_task_end`` (auto-injected). Anything outside
            this set is refused by the runner.
        max_iterations: Hard cap on turns before the runner ends the
            sub-agent as ``failed``.
        max_wall_seconds: Hard cap on wall-clock execution before the
            runner ends the sub-agent as ``timeout``.
        early_end_guard: Optional veto on premature sub_task_end calls. The
            runner logs the rejection into the sub's stream (costing one
            turn) and the loop continues; on the final turn it is not
            consulted, so it can never trap a sub-agent into the turn cap.
    """

    name: str
    description: str
    system_prompt: str
    actions: Tuple[str, ...]
    max_iterations: int
    max_wall_seconds: int
    early_end_guard: Optional[EarlyEndGuard] = None

    @property
    def compiled_actions(self) -> List[str]:
        """Mutable list copy for handing to a :class:`SubAgent`."""
        return list(self.actions)


# Process-wide registry. Populated by ``register_subagent`` calls in
# ``app.subagent.definitions.*`` modules at import time.
_REGISTRY: Dict[str, SubAgentDefinition] = {}


def register_subagent(
    *,
    name: str,
    description: str,
    system_prompt: str,
    actions: Iterable[str],
    max_iterations: int,
    max_wall_seconds: int,
    early_end_guard: Optional[EarlyEndGuard] = None,
) -> None:
    """Register a sub-agent type.

    Args:
        name: Unique agent_type identifier (e.g. ``"research_agent"``).
        description: One short sentence shown to the spawning agent in
            the ``spawn_subagent`` action description. Keep it tight.
        system_prompt: The type's own system prompt (see
            :class:`SubAgentDefinition`).
        actions: Action names this type may invoke. ``sub_task_end`` is
            auto-appended; do NOT list it here.
        max_iterations: Hard cap on turns.
        max_wall_seconds: Hard cap on wall-clock execution.
        early_end_guard: Optional veto on premature sub_task_end calls.

    Raises:
        ValueError: if ``name`` is already registered, ``description`` is
            empty, ``actions`` contains ``sub_task_end`` (which is
            auto-injected), or ``actions`` is empty after de-duplication.
    """
    if name in _REGISTRY:
        raise ValueError(
            f"Sub-agent type {name!r} is already registered. "
            "Each definition file should call register_subagent exactly once."
        )

    description = (description or "").strip()
    if not description:
        raise ValueError(
            f"Definition for {name!r} has no description. Every sub-agent "
            "needs a one-line description for the spawn_subagent action."
        )

    cleaned: List[str] = []
    seen = set()
    for action in actions:
        if action == SUB_TASK_END_ACTION:
            raise ValueError(
                f"Definition for {name!r} listed {SUB_TASK_END_ACTION!r} "
                "explicitly. This action is auto-injected by the registry — "
                "remove it from the actions list."
            )
        if action in seen:
            continue
        seen.add(action)
        cleaned.append(action)

    if not cleaned:
        raise ValueError(
            f"Definition for {name!r} has no actions. Every sub-agent "
            "needs at least one tool besides sub_task_end."
        )

    cleaned.append(SUB_TASK_END_ACTION)

    _REGISTRY[name] = SubAgentDefinition(
        name=name,
        description=description,
        system_prompt=system_prompt,
        actions=tuple(cleaned),
        max_iterations=max_iterations,
        max_wall_seconds=max_wall_seconds,
        early_end_guard=early_end_guard,
    )
    logger.debug(
        f"[SubAgentRegistry] Registered {name!r} "
        f"with {len(cleaned)} actions (max_iter={max_iterations})"
    )


def get_subagent_definition(name: str) -> SubAgentDefinition:
    """Look up a sub-agent definition or raise ``ValueError``."""
    defn = _REGISTRY.get(name)
    if defn is None:
        raise ValueError(
            f"Unknown sub-agent type: {name!r}. "
            f"Registered types: {list_subagent_names()}"
        )
    return defn


def list_subagent_names() -> List[str]:
    """Return the sorted list of registered sub-agent type names."""
    return sorted(_REGISTRY)


__all__ = [
    "SUB_TASK_END_ACTION",
    "EarlyEndGuard",
    "SubAgentDefinition",
    "register_subagent",
    "get_subagent_definition",
    "list_subagent_names",
]
