# -*- coding: utf-8 -*-
"""
AgentStep: the decide-and-prepare half of one agent turn.

Shared by every agent loop: the main agent's session turn (AgentBase.react)
and each sub-agent's turn (app.subagent.runner). Each loop then runs the
prepared actions with ActionManager.execute_actions_parallel, under its own
checks.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from agent_core.core.event_stream.event import EventType
from agent_core.utils.logger import logger

# A loop's check of one chosen action: (action_name, parameters) → why it
# may not run, or None.
ActionCheck = Callable[[str, Dict[str, Any]], Optional[str]]


class AgentStep:
    """Decide a turn's actions and prepare them to run."""

    def __init__(self, router, action_library, event_stream_manager):
        self.router = router
        self.action_library = action_library
        self.event_stream_manager = event_stream_manager

    async def decide(
        self, query: str, session_id: str
    ) -> Tuple[List[Dict[str, Any]], str]:
        """The turn's decision: the chosen actions and the reasoning behind
        them. The reasoning goes into the session's event stream, where the
        next request refers to the reply holding it instead of repeating it
        (EventStream.get_delta_events)."""
        decisions = await self.router.select_action_in_session(
            query=query, session_id=session_id
        )
        if not decisions:
            raise ValueError("Action router returned no decision.")

        reasoning = decisions[0].get("reasoning", "")
        logger.debug(f"[AGENT REASONING] {reasoning}")
        if reasoning:
            self.event_stream_manager.log(
                "agent reasoning",
                reasoning,
                severity="DEBUG",
                event_type=EventType.REASONING,
                display_message=None,
                task_id=session_id,
            )
        return decisions, reasoning

    def prepare(
        self,
        decisions: List[Dict[str, Any]],
        session_id: str,
        check: Optional[ActionCheck] = None,
    ) -> List[Tuple[Any, Dict[str, Any]]]:
        """The decided actions with their parameters, ready to run.

        An action the router dropped (``_error``) or ``check`` refuses does
        not run: the session's stream gets an action error saying why, so
        the next turn sees it.
        """
        prepared = []
        for decision in decisions:
            action_name = decision.get("action_name")
            action_params = decision.get("parameters", {})
            error = decision.get("_error")
            if error is None and action_name and check is not None:
                error = check(action_name, action_params)

            if error is not None:
                logger.warning(f"Action '{action_name}' has error: {error}")
                self.event_stream_manager.log(
                    kind="action_error",
                    message=f"Action {action_name} failed: {error}",
                    event_type=EventType.ACTION_END,
                    display_message=f"{action_name} → failed",
                    action_name=action_name,
                    action_output={"status": "error", "error": error},
                    task_id=session_id,
                )
                continue

            if not action_name:
                continue

            action = self.action_library.retrieve_action(action_name)
            if action is None:
                logger.warning(f"Action '{action_name}' not found, skipping")
                continue

            prepared.append((action, action_params))

        return prepared


__all__ = ["ActionCheck", "AgentStep"]
