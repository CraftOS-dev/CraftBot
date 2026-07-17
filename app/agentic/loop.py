# -*- coding: utf-8 -*-
"""AgentLoop — the ONE turn shape every agentic loop runs (Template Method).

Every driver's turn has the same skeleton:

    1. consult the step program (code may decide this turn);
    2. a code step (actions/wait/end) is handled by the driver — no LLM;
    3. an "llm" step becomes a turn directive that MUST reach the model
       this turn;
    4. otherwise (or on step fallback) the driver runs its LLM turn.

Before this class, that skeleton was written out once per driver (the
router's ``select_action_in_task`` and the sub-agent runner's
``_run_one_step``) — the same ~30 lines with driver-local names. The
skeleton now lives HERE exactly once; drivers subclass and override only
their policy:

- :class:`~app.subagent.runner.SubAgentRunner` — blocking loop: code
  steps dispatch straight to the ActionManager; the LLM turn is
  engine-decide + a capped ordered batch dispatch.
- the router's task turn — decisions are RETURNED (agent_base executes
  them between limits/persistence/trigger policy); the LLM turn is
  prompt building + engine-decide + format-retry + validation.

The decide phase itself (session-delta orchestration, parse, retry) is
NOT here — it is :func:`app.agentic.engine.decide`, which both drivers'
``llm_turn`` implementations call. This class owns only the turn's
control flow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

from app.agentic._log import logger
from app.agentic.steps import consult_step_program

# Sentinel a driver's on_code_step returns to decline the step and hand
# the turn to the LLM (e.g. every action failed validation, or the step
# kind has no meaning for this driver). Distinct from None, which is a
# perfectly good "handled, nothing to return" outcome.
FALLBACK = object()


class AgentLoop(ABC):
    """Template method for one agentic turn.

    ``subject`` is whatever the driver loops over — the Task for the task
    driver, the SubAgent for the sub-agent driver. The base class never
    inspects it; it only threads it through the hooks.
    """

    # ------------------------------------------------------------------
    # The template — do not override.
    # ------------------------------------------------------------------

    async def run_turn(self, subject: Any, **turn_kwargs: Any) -> Any:
        """One turn: consult → code step | directive → LLM turn."""
        turn_context = self.turn_context(subject, **turn_kwargs)
        step = consult_step_program(self.step_program(subject), subject, turn_context)
        directive: Optional[str] = None
        if step is not None:
            if step.get("kind") == "llm":
                # Code delegates ONE bounded decision; its prompt rides
                # THIS turn (the driver's llm_turn guarantees delivery).
                directive = str(step["prompt"])
                logger.info(
                    f"[AGENTIC:LOOP] llm-delegated turn: "
                    f"{step.get('purpose') or 'unlabeled'}"
                )
            else:
                outcome = await self.on_code_step(subject, step)
                if outcome is not FALLBACK:
                    return outcome
                step = None  # declined — this is a plain LLM turn now
        return await self.llm_turn(subject, directive, step)

    # ------------------------------------------------------------------
    # Hooks — driver policy.
    # ------------------------------------------------------------------

    def step_program(self, subject: Any) -> Optional[Callable]:
        """The step program consulted before the LLM. Base: none."""
        return None

    def turn_context(self, subject: Any, **turn_kwargs: Any) -> Dict[str, Any]:
        """The turn_context handed to the step program. Base: the kwargs."""
        return dict(turn_kwargs)

    async def on_code_step(self, subject: Any, step: Dict[str, Any]) -> Any:
        """Handle a validated actions/wait/end step. Return FALLBACK to
        decline it and let the LLM take the turn instead. Base: decline —
        a driver without a step program never sees a code step."""
        return FALLBACK

    @abstractmethod
    async def llm_turn(
        self, subject: Any, directive: Optional[str], step: Optional[Dict[str, Any]]
    ) -> Any:
        """The driver's LLM-decided turn. ``directive`` (an "llm" step's
        prompt) must reach the model THIS turn — delta turns included;
        ``step`` is that llm step (for allowed_actions bounds) or None."""


__all__ = ["AgentLoop", "FALLBACK"]
