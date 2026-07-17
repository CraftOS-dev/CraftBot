# -*- coding: utf-8 -*-
"""TaskTurn — the task driver's turn, on the shared AgentLoop skeleton.

One instance per ``ActionRouter.select_action_in_task`` call (a turn
object: per-turn prompt state lives here, not on the long-lived router).
The router remains the toolbox — candidates, prompt templates, decision
parsing/validation, the session-cached decide — while this class is the
POLICY of a task turn:

- code steps become validated decision payloads RETURNED to agent_base
  (which executes them between limits/persistence/trigger scheduling —
  the task driver never executes actions itself);
- the LLM turn builds the candidates + prompt (essentials gate, workflow
  template override), runs the decide through the router (engine-backed
  when the session is registered), and applies the format-retry +
  validation policy;
- an "llm" step's prompt REPLACES the turn query, bounds the candidate
  list, rides delta turns as the turn directive, and drops non-allowed
  actions post-parse.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent_core.core.impl.llm import LLMCallType
from agent_core.core.prompts import SELECT_ACTION_IN_TASK_PROMPT

from app.agentic._log import logger
from app.agentic.loop import FALLBACK, AgentLoop
from app.agentic.steps import step_to_decisions


class TaskTurn(AgentLoop):
    """One complex-task decision turn."""

    def __init__(
        self,
        router: Any,
        *,
        query: str,
        GUI_mode: bool = False,
        session_id: Optional[str] = None,
        user_message: Optional[str] = None,
    ):
        self.router = router
        self.query = query
        self.GUI_mode = GUI_mode
        self.session_id = session_id
        self.user_message = user_message
        self.workflow = router._get_current_task_workflow(session_id)

    # ------------------------------------------------------------------
    # AgentLoop hooks
    # ------------------------------------------------------------------

    def step_program(self, task: Any):
        return self.workflow.step if self.workflow is not None else None

    def turn_context(self, task: Any, **turn_kwargs: Any) -> Dict[str, Any]:
        return {
            "query": self.query,
            "user_message": self.user_message,
            "session_id": self.session_id,
        }

    async def on_code_step(self, task: Any, step: Dict[str, Any]) -> Any:
        """A code step becomes validated decision payloads — returned, not
        executed (execution is agent_base's job). All-invalid → decline."""
        decisions = step_to_decisions(step) or []
        label = decisions[0].get("reasoning", "") if decisions else ""
        actionable = [d for d in decisions if d.get("action_name")]
        if not actionable:  # wait step — the no-op decision shape
            logger.info(f"[STEP] {self.session_id} wait: {label}")
            return decisions
        validated = self.router._validate_parallel_actions(actionable, self.GUI_mode)
        if validated:
            logger.info(
                f"[STEP] {self.session_id} code-decided turn "
                f"({step.get('kind')}): "
                f"{[a.get('action_name') for a in validated]} — {label}"
            )
            return validated
        logger.error(
            f"[STEP] {self.session_id} step actions all failed validation "
            f"({[d.get('action_name') for d in actionable]}) — falling "
            "back to LLM decide"
        )
        return FALLBACK

    async def llm_turn(
        self, task: Any, directive: Optional[str], step: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        router = self.router
        query = directive if directive else self.query
        allowed = (step.get("allowed_actions") or None) if step else None

        # Candidate actions from the task's compiled sets — filtered to an
        # "llm" step's allow-list so the model only sees what the step
        # permits. An UNSATISFIABLE allow-list (empty intersection with the
        # compiled set) drops the bound entirely — for the candidates AND
        # the post-parse filter — so both layers always agree; the old
        # split (show everything, then drop whatever the model picked)
        # produced silent empty turns.
        ignore_actions = ["ignore", "task_start"]
        compiled_actions = router._get_current_task_compiled_actions(
            session_id=self.session_id
        )
        action_candidates = router._build_candidates_from_compiled_list(
            compiled_actions, self.GUI_mode, ignore_actions
        )
        logger.info(
            f"ActionRouter using compiled action list: {len(action_candidates)} actions"
        )
        if allowed:
            allowed_set = set(allowed)
            bounded = [c for c in action_candidates if c.get("name") in allowed_set]
            if bounded:
                action_candidates = bounded
            else:
                logger.warning(
                    f"[STEP] {self.session_id} allow-list {sorted(allowed_set)} "
                    "matches none of the task's compiled actions — running "
                    "the turn unbounded"
                )
                allowed = None

        task_state = router.context_engine.get_task_state(session_id=self.session_id)
        event_stream_content = router.context_engine.get_event_stream(
            session_id=self.session_id
        )

        # Pull integration essentials the same way conversation-mode does
        # (see select_action). Match against both the current step's query
        # and the task state so the platform name from the original user
        # request still triggers a match even after the per-step query is
        # generic. Sub-workflow tasks opt out: their purpose-built prompt
        # carries everything relevant, and unrelated integration lore only
        # dilutes a focused (possibly weak) model.
        integration_essentials = ""
        if self.workflow is None or self.workflow.inject_essentials:
            integration_essentials = router._get_integration_essentials(
                f"{query}\n{task_state}", "task-mode"
            )

        # Sub-workflows may replace the generic 11.6KB task protocol with a
        # purpose-built one (same format variables + output contract). The
        # generic prompt's set_requirement/todo-phase/approval rules
        # actively fight a workflow whose next step is computed by the
        # platform — a weak model obeys the bigger prompt.
        decision_template = SELECT_ACTION_IN_TASK_PROMPT
        decision_prompt_name = "SELECT_ACTION_IN_TASK"
        if self.workflow is not None and self.workflow.select_action_prompt:
            decision_template = self.workflow.select_action_prompt
            decision_prompt_name = (
                f"SELECT_ACTION_WORKFLOW_{self.workflow.name.upper()}"
            )
        full_prompt = decision_template.format(
            event_stream=event_stream_content,
            task_state=task_state,
            query=query,
            action_candidates=router._format_candidates(action_candidates),
            integration_essentials=integration_essentials,
        )

        return await router._decide_actions_with_format_retry(
            full_prompt,
            mode_label="Task mode",
            prompt_name=decision_prompt_name,
            is_task=True,
            call_type=LLMCallType.ACTION_SELECTION,
            session_id=self.session_id,
            turn_directive=directive,
            GUI_mode=self.GUI_mode,
            allowed_actions=allowed,
        )


__all__ = ["TaskTurn"]
