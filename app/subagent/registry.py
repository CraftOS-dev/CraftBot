# -*- coding: utf-8 -*-
"""
Sub-agent registry.

Every sub-agent type lives in its own module under :mod:`app.subagent.definitions`
and calls :func:`register_subagent` at import time. That gives each type a
single place where its prompt, allowed actions, and runtime caps are
defined — no scattering across ``types.py`` + ``prompts/``.

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
        system_prompt: The system-prompt template. Must contain
            ``{action_list}`` and ``{output_format}`` placeholders — the
            context engine fills these in per turn.
        actions: Frozen tuple of action names this type may invoke,
            INCLUDING ``sub_task_end`` (auto-injected). Anything outside
            this set is refused by the runner.
        max_iterations: Hard cap on action turns before the runner ends
            the sub-agent as ``failed``.
        max_wall_seconds: Hard cap on wall-clock execution before the
            runner ends the sub-agent as ``timeout``.
    """

    name: str
    description: str
    system_prompt: str
    actions: Tuple[str, ...]
    max_iterations: int
    max_wall_seconds: int
    # Forced parameters per action: ((action_name, ((param, value), ...)), ...)
    # e.g. scope shared-browser console reads to recent entries only.
    param_overrides: Tuple[Tuple[str, Tuple[Tuple[str, object], ...]], ...] = ()
    # Optional veto on premature sub_task_end calls: (sub, parameters) →
    # rejection text, or None to allow the end. The runner logs the rejection
    # into the sub's stream (costing one turn) and the loop continues —
    # structural enforcement for types whose models surrender early (a
    # verifier with 50 turns concluded at turn 8 citing "limited turns").
    early_end_guard: Optional[
        Callable[["SubAgent", Dict[str, object]], Optional[str]]
    ] = None

    def overrides_for(self, action_name: str) -> Dict[str, object]:
        """The forced parameters for one action ({} when none)."""
        for name, pairs in self.param_overrides:
            if name == action_name:
                return dict(pairs)
        return {}

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
    param_overrides: Tuple[Tuple[str, Tuple[Tuple[str, object], ...]], ...] = (),
    early_end_guard: Optional[
        Callable[["SubAgent", Dict[str, object]], Optional[str]]
    ] = None,
) -> None:
    """Register a sub-agent type.

    Args:
        name: Unique agent_type identifier (e.g. ``"research_agent"``).
        description: One short sentence shown to the spawning agent in
            the ``spawn_subagent`` action description. Keep it tight.
        system_prompt: System-prompt template with ``{action_list}`` and
            ``{output_format}`` placeholders.
        actions: Action names this type may invoke. ``sub_task_end`` is
            auto-appended; do NOT list it here.
        max_iterations: Hard cap on action turns.
        max_wall_seconds: Hard cap on wall-clock execution.

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
        param_overrides=param_overrides,
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


def is_subagent_registered(name: str) -> bool:
    return name in _REGISTRY


__all__ = [
    "SUB_TASK_END_ACTION",
    "SubAgentDefinition",
    "register_subagent",
    "get_subagent_definition",
    "list_subagent_names",
    "is_subagent_registered",
]
