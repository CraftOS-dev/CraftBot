# -*- coding: utf-8 -*-
"""
SubAgentRunner — the sub-agent DRIVER on the shared agentic loop.

The runner IS the same loop as the main agent's task turns: it subclasses
:class:`app.agentic.loop.AgentLoop` (the one turn skeleton — step-program
consult → code step | directive → LLM turn) and its LLM turn delegates the
decide phase to the shared TurnEngine (:mod:`app.agentic.engine`). What
lives HERE is only sub-agent policy — no memory pulls, conversation
routing, GUI workflows, or proactive handling; instead: the blocking
outer loop, iteration/wall caps, capped ordered batch dispatch, and exit
gates on ``sub_task_end``. The shape:

    while not terminal:                       # this driver
        run_turn(sub):                        # AgentLoop skeleton
            step = type's step program?       # code may decide the turn
            decision = engine.decide(...)     # shared decide phase
            for each action (max 4, ordered):
                if action_name not in compiled_actions: skip with warning
                action_manager.execute_action(action, ..., session_id=sub.id)

The runner relies on existing primitives for execution and logging:

- ``ActionManager.execute_action`` runs the action and logs
  ``action_start`` / ``action_end`` to the sub-agent's stream (because we
  pass ``session_id=sub.id`` and ``is_running_task=True``).
- ``sub_task_end`` is the action that marks the sub-agent terminal — the
  runner detects that by checking ``sub.is_terminal()`` after every step.

Session caching:

- A single session cache is registered with the LLM interface up front
  (once per sub-agent lifetime) using the sub-agent's system prompt.
- The first turn sends the full ``query + initial event log`` user
  prompt; subsequent turns send only the events appended to the child
  stream since the previous call, drastically reducing tokens.
- The LLM interface transparently handles providers without session
  caching (e.g. ollama) — the call shape is the same.

Resource cleanup:

- ``SubAgentManager.end()`` only flips status and writes a breadcrumb;
  it deliberately leaves the stream alive so the ``sub_task_end`` action
  can finish logging ``action_end`` to the child stream.
- After the loop exits, the runner calls ``SubAgentManager.release()``
  in a ``finally`` to drop the stream and release session caches.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agent_core.core.impl.llm import LLMCallType, LLMConsecutiveFailureError
from app.agentic.loop import AgentLoop
from app.logger import logger
from app.subagent.context_engine import SubAgentContextEngine
from app.subagent.registry import get_subagent_definition
from app.subagent.types import SubAgent

if TYPE_CHECKING:
    from agent_core.core.impl.action.library import ActionLibrary
    from agent_core.core.impl.action.manager import ActionManager
    from app.event_stream import EventStreamManager
    from app.llm import LLMInterface
    from app.subagent.manager import SubAgentManager


# Max LLM format-error retries per turn before the runner aborts the sub-agent.
_MAX_PARSE_RETRIES = 3

# Max actions executed from a single decision turn. Mirrors the main agent's
# decision batches: independent steps (reads, todo update + write) run in one
# turn instead of one LLM round-trip each. Anything past the cap is dropped
# with a stream note so the model re-plans instead of silently losing work.
_MAX_ACTIONS_PER_TURN = 4

# Sub-agents only ever do action selection — never GUI or reasoning calls —
# so a single call type covers their entire lifetime.
_SUBAGENT_CALL_TYPE = LLMCallType.ACTION_SELECTION


class SubAgentRunner(AgentLoop):
    """Drives a single sub-agent to a terminal state.

    The turn skeleton (step-program consult → code step | directive →
    LLM turn) is inherited from :class:`app.agentic.loop.AgentLoop`;
    this class contributes the sub-agent POLICY: the blocking outer
    loop, iteration/wall caps, capped ordered batch dispatch, exit
    gates (via sub_task_end), and fatal-LLM handling."""

    def __init__(
        self,
        subagent_manager: "SubAgentManager",
        action_manager: "ActionManager",
        action_library: "ActionLibrary",
        event_stream_manager: "EventStreamManager",
        llm_interface: "LLMInterface",
    ):
        self.subagent_manager = subagent_manager
        self.action_manager = action_manager
        self.action_library = action_library
        self.event_stream_manager = event_stream_manager
        self.llm_interface = llm_interface
        self.context_engine = SubAgentContextEngine(
            action_library=action_library,
            event_stream_manager=event_stream_manager,
        )
        # System prompts are stable for a sub-agent's whole lifetime; built
        # once in _register_session, reused every turn, dropped on release.
        self._system_prompt_cache: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    async def run_to_completion(self, sub: SubAgent) -> SubAgent:
        """
        Loop until the sub-agent reaches a terminal status, hits the
        iteration cap, or hits the wall-clock cap. Always returns the
        same ``SubAgent`` (mutated in place).

        Always calls ``SubAgentManager.release(sub.id)`` before returning,
        even on exception, so the per-sub-agent event stream and session
        caches don't leak.
        """
        defn = get_subagent_definition(sub.agent_type)
        max_iter = defn.max_iterations
        max_wall = defn.max_wall_seconds
        deadline = time.monotonic() + max_wall

        logger.info(
            f"[SubAgentRunner] starting {sub.id} type={sub.agent_type} "
            f"max_iter={max_iter} max_wall={max_wall}s"
        )

        # Register the session cache once for this sub-agent's whole
        # lifetime. The system prompt is stable across turns, so this
        # only needs to happen here, not on every step.
        self._register_session(sub)

        try:
            while not sub.is_terminal():
                # Increment at the TOP of the loop so ``sub.iterations``
                # reflects the turn currently being executed. This makes
                # the manager's "Ended iterations=N" log and the runner's
                # "loop done iterations=N" log agree.
                sub.iterations += 1

                if sub.iterations > max_iter:
                    # GRACE TURN before the guillotine: one final forced
                    # wrap-up so the run's observations become a report
                    # instead of being discarded (a walk that burned 50
                    # turns used to die with a generic epitaph and the
                    # check learned NOTHING).
                    await self._final_wrapup_turn(sub)
                    if not sub.is_terminal():
                        self._terminate_at_iteration_cap(sub, max_iter)
                    break
                if time.monotonic() > deadline:
                    self._terminate_at_wall_clock(sub, max_wall)
                    break

                await self._run_one_step_safely(sub)

            logger.info(
                f"[SubAgentRunner] {sub.id} loop done. status={sub.status} "
                f"iterations={sub.iterations}"
            )
            return sub
        finally:
            # Release runs AFTER the loop, not inside ``end()``. ActionManager
            # logs ``action_end`` for ``sub_task_end`` after the action body
            # returns; that log must still find the child's stream. We swallow
            # release errors so a cleanup crash doesn't mask the original
            # exception (if any) propagating out of the try block.
            self._system_prompt_cache.pop(sub.id, None)
            try:
                self.subagent_manager.release(sub.id)
            except Exception as e:
                logger.warning(f"[SubAgentRunner] release({sub.id}) failed: {e}")

    # ------------------------------------------------------------------
    # Termination helpers (iteration cap / wall-clock cap)
    # ------------------------------------------------------------------

    _WRAPUP_DIRECTIVE = (
        "YOUR TURN BUDGET IS EXHAUSTED. This is your FINAL turn: call "
        "sub_task_end NOW (alone, no other action) with an HONEST report of "
        "what you actually did and observed. Verification agents: report "
        "your VERDICT with per-feature results for everything you actually "
        "checked, and list features you did not get to as 'NOT REACHED: "
        "<feature>' — never report an unvisited feature as FAIL. Builders: "
        "report exactly what is BUILT/working vs REMAINING. If your work is "
        'incomplete, use status="failed" — an honest partial report is '
        "valuable; silence is not."
    )

    async def _final_wrapup_turn(self, sub: SubAgent) -> None:
        """One forced report-and-end turn at the iteration cap. Fail-open:
        any error (including a dead LLM) falls through to the normal cap
        termination."""
        try:
            logger.info(
                f"[SubAgentRunner] {sub.id} at iteration cap — forcing a "
                "final wrap-up turn"
            )
            actions, parse_error = await self._ask_llm_for_decision(
                sub, turn_directive=self._WRAPUP_DIRECTIVE
            )
            if actions:
                # Only honor the terminal action — the budget is spent.
                terminal = [
                    a for a in actions if a.get("action_name") == "sub_task_end"
                ]
                if terminal:
                    await self._dispatch_batch(sub, terminal[:1])
                else:
                    logger.warning(
                        f"[SubAgentRunner] {sub.id} wrap-up turn chose "
                        "non-terminal actions — ignoring"
                    )
            elif parse_error:
                logger.warning(
                    f"[SubAgentRunner] {sub.id} wrap-up turn unparseable: "
                    f"{parse_error}"
                )
        except Exception as e:
            logger.warning(f"[SubAgentRunner] {sub.id} wrap-up turn failed: {e}")

    def _terminate_at_iteration_cap(self, sub: SubAgent, cap: int) -> None:
        logger.warning(
            f"[SubAgentRunner] {sub.id} hit iteration cap ({cap}); ending as failed"
        )
        # Roll the count back to the cap so it doesn't appear we ran an
        # extra turn we never actually executed.
        sub.iterations = cap
        self.subagent_manager.end(
            sub.id,
            status="failed",
            result=(
                f"(sub-agent exhausted iteration cap of {cap} "
                "without calling sub_task_end)"
            ),
        )

    def _terminate_at_wall_clock(self, sub: SubAgent, cap_seconds: int) -> None:
        logger.warning(
            f"[SubAgentRunner] {sub.id} hit wall-clock cap "
            f"({cap_seconds}s); ending as timeout"
        )
        # The increment at the top of the loop was speculative — we never
        # actually ran this turn. Undo it so the count stays honest.
        sub.iterations -= 1
        self.subagent_manager.end(
            sub.id,
            status="timeout",
            result=(
                f"(sub-agent ran past wall-clock cap of {cap_seconds}s "
                "without calling sub_task_end)"
            ),
        )

    # ------------------------------------------------------------------
    # Per-step: ask LLM → dispatch action
    # ------------------------------------------------------------------

    async def _run_one_step_safely(self, sub: SubAgent) -> None:
        """Run one step, surfacing crashes as a stream event without aborting.

        The sub-agent gets another chance on the next turn to observe the
        error and self-correct. If failures continue, the iteration cap
        catches it.
        """
        try:
            await self.run_turn(sub)
        except LLMConsecutiveFailureError as e:
            # Fatal LLM failure (out-of-credits, auth, repeated provider
            # errors). Retrying can't help, so end the sub-agent now with the
            # real cause instead of spinning until the iteration cap. Ending
            # makes ``sub.is_terminal()`` true, so the run loop exits cleanly.
            cause = (
                e.last_error_info.message if e.last_error_info is not None else str(e)
            )
            logger.error(
                f"[SubAgentRunner] {sub.id} aborting after consecutive LLM "
                f"failures: {cause}"
            )
            self.event_stream_manager.log(
                kind="subagent_error",
                message=f"LLM unavailable: {cause}",
                severity="ERROR",
                task_id=sub.id,
            )
            from app.agentic.engine import INFRA_LLM_MARKER

            self.subagent_manager.end(
                sub.id,
                status="failed",
                result=(
                    f"{INFRA_LLM_MARKER} sub-agent aborted — LLM "
                    f"unavailable: {cause}"
                ),
            )
        except Exception as e:
            logger.exception(
                f"[SubAgentRunner] {sub.id} step {sub.iterations} crashed: {e}"
            )
            self.event_stream_manager.log(
                kind="subagent_error",
                message=f"Step crashed: {e}",
                severity="ERROR",
                task_id=sub.id,
            )

    # ------------------------------------------------------------------
    # AgentLoop hooks — the turn skeleton itself lives in the base class
    # (app/agentic/loop.py); this driver contributes only its policy.
    # Sub-agents are data-only (no step program): every turn is an LLM turn.
    # ------------------------------------------------------------------

    async def llm_turn(
        self, sub: SubAgent, directive: Optional[str], step: Optional[Dict[str, Any]]
    ) -> None:
        actions, parse_error = await self._ask_llm_for_decision(
            sub, turn_directive=directive
        )
        if actions is None:
            self._fail_unparseable(sub, parse_error)
            return
        await self._dispatch_batch(sub, actions)

    async def _dispatch_batch(
        self, sub: SubAgent, actions: List[Dict[str, Any]]
    ) -> None:
        """Cap the batch, then execute strictly in order — same semantics
        as the main agent's decision batches. Stop as soon as the
        sub-agent turns terminal (sub_task_end accepted); the model sees
        each action's result in its event log next turn."""
        if len(actions) > _MAX_ACTIONS_PER_TURN:
            dropped = [
                a.get("action_name", "?") for a in actions[_MAX_ACTIONS_PER_TURN:]
            ]
            self.event_stream_manager.log(
                kind="action_blocked",
                message=(
                    f"Turn batch too large: only the first "
                    f"{_MAX_ACTIONS_PER_TURN} actions ran; dropped {dropped}. "
                    "Re-issue the dropped actions next turn."
                ),
                task_id=sub.id,
            )
            actions = actions[:_MAX_ACTIONS_PER_TURN]

        for decision in actions:
            if sub.is_terminal():
                break
            await self._dispatch_action(sub, decision)

    def _fail_unparseable(self, sub: SubAgent, parse_error: Optional[str]) -> None:
        self.event_stream_manager.log(
            kind="subagent_error",
            message=(
                f"LLM produced unparseable decision after "
                f"{_MAX_PARSE_RETRIES} attempts. Last error: {parse_error}"
            ),
            severity="ERROR",
            task_id=sub.id,
        )
        self.subagent_manager.end(
            sub.id,
            status="failed",
            result=(
                "(sub-agent could not produce a parseable action decision; "
                f"last error: {parse_error})"
            ),
        )

    async def _dispatch_action(self, sub: SubAgent, decision: Dict[str, Any]) -> None:
        action_name = decision.get("action_name") or ""
        parameters = decision.get("parameters") or {}
        if not isinstance(parameters, dict):
            parameters = {}

        # Enforce the frozen action list — refuse anything else.
        if action_name not in sub.compiled_actions:
            msg = (
                f"Disallowed action {action_name!r}. "
                f"You can only use: {sub.compiled_actions}."
            )
            logger.warning(f"[SubAgentRunner] {sub.id} {msg}")
            self.event_stream_manager.log(
                kind="action_blocked",
                message=msg,
                display_message=f"blocked: {action_name}",
                task_id=sub.id,
            )
            return

        action = self.action_library.retrieve_action(action_name)
        if action is None:
            msg = (
                f"Action {action_name!r} is in the type's allow list but is "
                "not registered in the library. Configuration bug."
            )
            logger.error(f"[SubAgentRunner] {sub.id} {msg}")
            self.event_stream_manager.log(
                kind="action_blocked",
                message=msg,
                task_id=sub.id,
            )
            return

        # Track files this agent writes — exit checks (build_passes) locate
        # the project to verify from exactly these.
        if action_name in ("write_file", "stream_edit"):
            file_path = str(parameters.get("file_path", "") or "")
            if file_path and file_path not in sub.written_files:
                sub.written_files.append(file_path)
        # Track every action name — exit checks can require real work (e.g. a
        # coding agent must have actually driven the browser before "done").
        sub.actions_run.append(action_name)

        # Definition-pinned parameters win over whatever the model asked for
        # (see SubAgentDefinition.param_overrides).
        forced = get_subagent_definition(sub.agent_type).overrides_for(action_name)
        if forced:
            parameters = {**parameters, **forced}

        # ActionManager handles action_start/action_end logging to the child
        # stream, error capture, and idempotency. We pass session_id=sub.id
        # so every log routes to the child's per-id stream.
        outputs = await self.action_manager.execute_action(
            action=action,
            context="",
            event_stream="",
            session_id=sub.id,
            is_running_task=True,
            is_gui_task=False,
            input_data=parameters,
        )
        # Record failures alongside attempts: an exit check can then tell a
        # tool that is DEAD (attempted, never once succeeded → fail open) from
        # an agent that never tried (→ refuse). Never let this bookkeeping
        # break the action itself.
        try:
            if isinstance(outputs, dict) and outputs.get("status") == "error":
                sub.actions_failed.append(action_name)
        except Exception:  # pragma: no cover — bookkeeping must never throw
            pass

    # ------------------------------------------------------------------
    # Session-cache management
    # ------------------------------------------------------------------

    def _register_session(self, sub: SubAgent) -> None:
        """
        Register a session cache for this sub-agent's full lifetime.

        Stores the system prompt with the LLM interface so:
        - the first ``generate_response_with_session_async`` call can
          create the actual provider-side session lazily, and
        - context-overflow recovery (provider-specific) can rebuild a
          fresh session from the stored prompt.

        Called once before the loop starts. Re-registration would be
        harmless (just overwrites the stored prompt) but wasteful.
        """
        system_prompt = self.context_engine.make_system_prompt(sub)
        self._system_prompt_cache[sub.id] = system_prompt
        self.llm_interface.create_session_cache(
            sub.id, _SUBAGENT_CALL_TYPE, system_prompt
        )

    # (Session reset on summarization is handled inside the shared engine's
    # decide phase — see app/agentic/engine._build_turn_prompt.)

    # ------------------------------------------------------------------
    # Decide phase — delegated to the shared TurnEngine
    # ------------------------------------------------------------------

    async def _ask_llm_for_decision(
        self, sub: SubAgent, turn_directive: Optional[str] = None
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """
        Ask the LLM for the next action batch and return ``(actions, error)``.

        Delegates the whole decide phase — session-delta orchestration,
        LLM call, parse, retry-with-feedback — to the shared TurnEngine
        (:mod:`app.agentic.engine`); this runner keeps only sub-agent
        policy (the blocking loop, caps, exit gates, dispatch).

        ``turn_directive`` (a step program's "llm" prompt) is appended to
        the delta prompt so it reaches the model THIS turn, not just at
        session establishment.
        """
        from app.agentic.engine import DecideConfig, append_step_directive, decide

        stream = self.event_stream_manager.get_stream_by_id(sub.id)
        return await decide(
            self.llm_interface,
            stream,
            DecideConfig(
                session_key=sub.id,
                call_type=_SUBAGENT_CALL_TYPE,
                system_prompt=(
                    self._system_prompt_cache.get(sub.id)
                    or self.context_engine.make_system_prompt(sub)
                ),
                # Lazy: only establish/re-establish turns consume it — delta
                # turns must not pay for building query + full initial log.
                first_prompt=lambda: append_step_directive(
                    self.context_engine.make_first_turn_user_prompt(sub),
                    turn_directive,
                ),
                delta_prompt_builder=lambda delta: append_step_directive(
                    self.context_engine.make_delta_user_prompt(sub, delta),
                    turn_directive,
                ),
                parse=self._parse_decision,
                # augment_retry: the engine's default (raw-echoing feedback).
                prompt_name=f"SUBAGENT_{sub.agent_type.upper()}",
                max_retries=_MAX_PARSE_RETRIES,
                on_exhaust="none",
            ),
        )


    # ------------------------------------------------------------------
    # JSON parsing — delegates to the shared parser (app/agentic/parsing)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_decision(
        raw: Optional[str],
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """Raw LLM text → normalized, ordered action list.

        Accepts the batch shape ``{"actions": [...]}`` and the legacy
        single-action shape. One shared implementation for every loop."""
        from app.agentic.parsing import extract_actions_strict, parse_decision_dict

        decision, err = parse_decision_dict(raw)
        if decision is None:
            return None, err
        return extract_actions_strict(decision)


__all__ = ["SubAgentRunner"]
