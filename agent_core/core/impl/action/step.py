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
        self, query: str, session_id: str, reply_stream=None
    ) -> Tuple[List[Dict[str, Any]], str]:
        """The turn's decision: the chosen actions and the reasoning behind
        them. The reasoning goes into the session's event stream, where the
        next request refers to the reply holding it instead of repeating it
        (EventStream.get_delta_events).

        ``reply_stream`` (a ReplyStream) follows the reply as it streams and
        may start actions before it ends; it records the reasoning itself
        before the first of them (log_reasoning), so it is not logged twice.
        """
        decisions = await self.router.select_action_in_session(
            query=query, session_id=session_id, reply_stream=reply_stream
        )
        if not decisions:
            raise ValueError("Action router returned no decision.")

        reasoning = decisions[0].get("reasoning", "")
        logger.debug(f"[AGENT REASONING] {reasoning}")
        if reasoning and not (
            reply_stream is not None and reply_stream.reasoning_logged
        ):
            self.log_reasoning(
                session_id,
                reasoning,
                reply_stream.reasoning_id if reply_stream is not None else None,
            )
        return decisions, reasoning

    def log_reasoning(
        self, session_id: str, reasoning: str, item_id: Optional[str] = None
    ) -> None:
        """Record a reply's reasoning in the session's event stream.
        ``item_id`` names its activity row (the streamed reasoning's id), so
        the row shown while the reply streamed becomes this one."""
        self.event_stream_manager.log(
            "agent reasoning",
            reasoning,
            severity="DEBUG",
            event_type=EventType.REASONING,
            display_message=None,
            action_id=item_id,
            task_id=session_id,
        )

    def prepare_one(
        self,
        decision: Dict[str, Any],
        session_id: str,
        check: Optional[ActionCheck] = None,
    ) -> Optional[Tuple[Any, Dict[str, Any]]]:
        """One decided action with its parameters, ready to run; None when
        it does not run (see prepare)."""
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
                action_id=decision.get("_run_id"),
                action_output={"status": "error", "error": error},
                task_id=session_id,
            )
            return None

        if not action_name:
            return None

        action = self.action_library.retrieve_action(action_name)
        if action is None:
            logger.warning(f"Action '{action_name}' not found, skipping")
            return None

        return action, action_params

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
        return self.prepare_with_ids(decisions, session_id, check)[0]

    def prepare_with_ids(
        self,
        decisions: List[Dict[str, Any]],
        session_id: str,
        check: Optional[ActionCheck] = None,
    ) -> Tuple[List[Tuple[Any, Dict[str, Any]]], List[Optional[str]]]:
        """prepare, plus the run id each prepared action carries (the id of
        its row while the reply streamed; None when it did not stream)."""
        prepared = []
        run_ids: List[Optional[str]] = []
        for decision in decisions:
            ready = self.prepare_one(decision, session_id, check)
            if ready is not None:
                prepared.append(ready)
                run_ids.append(decision.get("_run_id"))
        return prepared, run_ids


__all__ = ["ActionCheck", "AgentStep"]
