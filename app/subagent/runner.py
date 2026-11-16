# -*- coding: utf-8 -*-
"""
SubAgentRunner — drives one sub-agent until its run ends.

A sub-agent runs the main agent's turn on a context of its own: the same
ActionRouter (requests, retries, folds, session caching), the same AgentStep
(reasoning event, prepared actions) and the same
ActionManager.execute_actions_parallel. What is its own:

- its context (SubAgentContextEngine) and the two decision templates;
- the check on every chosen action: only the definition's actions run, and
  the definition's early_end_guard may refuse a sub_task_end (except on the
  final turn);
- how the run ends: sub_task_end (the action ends it), the turn cap
  (failed), the time cap (timeout; whatever is in flight is cancelled), an
  error (failed), or the spawning run being stopped (failed, and the
  cancellation propagates).

It runs on the event loop of the turn that spawned it, so stopping that run
stops the sub-agent. SubAgentManager.run wraps it (log sink, release).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, Optional

from agent_core.core.event_stream.event import EventType
from agent_core.core.impl.action import ActionRouter, AgentStep
from agent_core.core.impl.llm import LLMCallType, LLMConsecutiveFailureError
from agent_core.core.prompts import decision_system_prompt
from app.logger import logger
from app.subagent.context_engine import (
    SUBAGENT_DECISION_INSTRUCTIONS,
    SUBAGENT_DECISION_PROMPT,
    SubAgentContextEngine,
)
from app.subagent.registry import SUB_TASK_END_ACTION, get_subagent_definition
from app.subagent.types import SubAgent

if TYPE_CHECKING:
    from app.subagent.manager import SubAgentManager


# The session history a sub-agent's decisions continue (the router's).
_CALL_TYPE = LLMCallType.ACTION_SELECTION


class SubAgentRunner:
    """Drives a single sub-agent to a terminal state."""

    def __init__(self, manager: "SubAgentManager", sub: SubAgent):
        self.manager = manager
        self.sub = sub
        self.definition = get_subagent_definition(sub.agent_type)
        self.context = SubAgentContextEngine(sub, manager.event_stream_manager)
        self.router = ActionRouter(
            manager.action_library,
            manager.llm_interface,
            self.context,
            instructions=SUBAGENT_DECISION_INSTRUCTIONS,
            user_prompt=SUBAGENT_DECISION_PROMPT,
            prompt_name=f"SUBAGENT_{sub.agent_type.upper()}",
        )
        self.step = AgentStep(
            self.router, manager.action_library, manager.event_stream_manager
        )

    async def run(self) -> None:
        """Take turns until the sub-agent ends, within its time cap."""
        sub, cap_seconds = self.sub, self.definition.max_wall_seconds
        logger.info(
            f"[SubAgentRunner] starting {sub.id} type={sub.agent_type} "
            f"max_iter={self.definition.max_iterations} max_wall={cap_seconds}s"
        )
        # Register the session history the router's requests continue, on
        # the system prompt they send.
        self.manager.llm_interface.create_session_cache(
            sub.id,
            _CALL_TYPE,
            decision_system_prompt(
                self.context.make_prompt()[0], self.router.decision_instructions(sub.id)
            ),
        )
        try:
            await asyncio.wait_for(self._turns(), timeout=cap_seconds)
        except asyncio.TimeoutError:
            logger.warning(
                f"[SubAgentRunner] {sub.id} hit its time cap ({cap_seconds}s)"
            )
            self.manager.end(
                sub.id,
                "timeout",
                f"(sub-agent ran past its time cap of {cap_seconds}s without "
                "calling sub_task_end)",
            )
        except asyncio.CancelledError:
            self.manager.end(
                sub.id, "failed", "(sub-agent stopped with the run that spawned it)"
            )
            raise
        logger.info(
            f"[SubAgentRunner] {sub.id} done. status={sub.status} "
            f"iterations={sub.iterations}"
        )

    async def _turns(self) -> None:
        sub, cap = self.sub, self.definition.max_iterations
        while not sub.is_terminal():
            if sub.iterations >= cap:
                logger.warning(f"[SubAgentRunner] {sub.id} used all {cap} turns")
                self.manager.end(
                    sub.id,
                    "failed",
                    f"(sub-agent used all {cap} turns without calling sub_task_end)",
                )
                return
            sub.iterations += 1
            self._warn_when_turns_run_low()
            try:
                await self._turn()
            except LLMConsecutiveFailureError as e:
                # Out of credits, auth, repeated provider errors: name the
                # real cause, not the generic retry message.
                info = e.last_error_info
                self._fail(info.message if info is not None else str(e))
            except Exception as e:
                # The router gave up (unparseable or wrong-format replies,
                # provider errors) after its own retries: the run ends, as a
                # main-agent run does.
                self._fail(str(e))

    async def _turn(self) -> None:
        sub = self.sub
        decisions, reasoning = await self.step.decide(sub.query, sub.id)
        prepared = self.step.prepare(decisions, sub.id, check=self._check)
        if prepared:
            await self.manager.action_manager.execute_actions_parallel(
                actions=prepared,
                context=reasoning,
                event_stream="",
                session_id=sub.id,
                is_running_task=True,
            )

    def _check(self, action_name: str, parameters: Dict[str, Any]) -> Optional[str]:
        """Why a chosen action may not run, or None (AgentStep.prepare)."""
        sub, definition = self.sub, self.definition
        if action_name not in sub.compiled_actions:
            return (
                f"'{action_name}' is not one of your actions. You can only use: "
                f"{', '.join(sub.compiled_actions)}."
            )
        guard = definition.early_end_guard
        if (
            action_name == SUB_TASK_END_ACTION
            and guard is not None
            and sub.iterations < definition.max_iterations
        ):
            try:
                return guard(sub, parameters)
            except Exception as e:
                logger.warning(
                    f"[SubAgentRunner] {sub.id} early_end_guard failed "
                    f"(allowing the end): {e}"
                )
        return None

    def _warn_when_turns_run_low(self) -> None:
        """Once a fifth of the turns are left, say so in the stream."""
        cap = self.definition.max_iterations
        left = cap - self.sub.iterations + 1  # this turn included
        if left == max(1, cap // 5):
            self.manager.event_stream_manager.log(
                kind="warning",
                message=(
                    f"Turn budget: {left} of {cap} turns left, this one "
                    "included. Finish the query and end with sub_task_end "
                    "before they run out."
                ),
                event_type=EventType.INTERNAL,
                task_id=self.sub.id,
            )

    def _fail(self, cause: str) -> None:
        sub = self.sub
        logger.error(
            f"[SubAgentRunner] {sub.id} turn {sub.iterations} failed: {cause}"
        )
        self.manager.event_stream_manager.log(
            kind="subagent_error",
            message=f"Turn {sub.iterations} failed: {cause}",
            severity="ERROR",
            event_type=EventType.ERROR,
            task_id=sub.id,
        )
        self.manager.end(sub.id, "failed", f"(sub-agent stopped on an error: {cause})")


__all__ = ["SubAgentRunner"]
