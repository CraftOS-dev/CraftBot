# -*- coding: utf-8 -*-
"""
Sub-agent registry.

Every sub-agent type lives in its own module with the workflow that owns
it (``app/workflows/<domain>/subagents/``; cross-domain types under
``app/workflows/common/subagents/``) and calls :func:`register_subagent`
at import time. That gives each type a single place where its prompt,
allowed actions, and runtime caps are defined — no scattering across
``types.py`` + ``prompts/``.

``sub_task_end`` is the universal terminator action. The registry appends
it to every definition's action list automatically; it must NEVER be
listed by the definition itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

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

    All types are data-only and register through :func:`register_subagent`.
    """

    name: str
    description: str
    system_prompt: str
    actions: Tuple[str, ...]
    max_iterations: int
    max_wall_seconds: int
    # Deterministic checks (see app.subagent.exit_checks) that must ALL pass
    # before sub_task_end(status="completed") is accepted. A failing check
    # refuses the end with an instructional error — the agent keeps its
    # remaining iterations to actually fix the problems instead of shipping
    # them (observed: builders ending at 9-18/60 iterations with dirty tsc
    # and unrun tests, because stopping was free).
    exit_checks: Tuple[str, ...] = ()
    # Parameters FORCED onto specific actions at execution time, as
    # ((action_name, ((param, value), ...)), ...). A guarantee the prompt
    # can't give: e.g. walk_verify pins browser_console_messages all=False —
    # the shared browser's full history contains OLD builds' crashes, and a
    # walk that read it condemned a freshly built app with errors from code
    # that no longer existed (session 20260717150105).
    param_overrides: Tuple[Tuple[str, Tuple[Tuple[str, object], ...]], ...] = ()

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


# Process-wide registry. Populated by ``register_subagent`` calls in the
# workflow packages' ``subagents/*`` modules at import time.
_REGISTRY: Dict[str, SubAgentDefinition] = {}


def register_subagent(
    *,
    name: str,
    description: str,
    system_prompt: str,
    actions: Iterable[str],
    max_iterations: int,
    max_wall_seconds: int,
    exit_checks: Iterable[str] = (),
    param_overrides: Tuple[Tuple[str, Tuple[Tuple[str, object], ...]], ...] = (),
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
        exit_checks: Deterministic check names run before a "completed"
            ``sub_task_end`` is accepted (see :mod:`app.subagent.exit_checks`).
        param_overrides: Parameters forced onto specific actions at
            execution time (see :class:`SubAgentDefinition.param_overrides`).

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
        exit_checks=tuple(exit_checks),
        param_overrides=tuple(param_overrides),
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
