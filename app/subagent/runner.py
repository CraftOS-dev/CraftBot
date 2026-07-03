# -*- coding: utf-8 -*-
"""
SubAgentRunner — minimal action loop for one sub-agent.

This is intentionally NOT a thin wrapper around the main agent's
``react()`` loop. Sub-agents don't need todo planning, memory pulls,
conversation routing, GUI workflows, or proactive handling. They need:

    while not terminal:
        prompt = type-specific system prompt + query + own event log
        decision = LLM(prompt) → {action_name, parameters}
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

import ast
import json
import time
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from agent_core.core.impl.llm import LLMCallType, LLMConsecutiveFailureError
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

# Sub-agents only ever do action selection — never GUI or reasoning calls —
# so a single call type covers their entire lifetime.
_SUBAGENT_CALL_TYPE = LLMCallType.ACTION_SELECTION


class SubAgentRunner:
    """Drives a single sub-agent to a terminal state."""

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
            try:
                self.subagent_manager.release(sub.id)
            except Exception as e:
                logger.warning(f"[SubAgentRunner] release({sub.id}) failed: {e}")

    # ------------------------------------------------------------------
    # Termination helpers (iteration cap / wall-clock cap)
    # ------------------------------------------------------------------

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
            await self._run_one_step(sub)
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
            self.subagent_manager.end(
                sub.id,
                status="failed",
                result=f"(sub-agent aborted — LLM unavailable: {cause})",
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

    async def _run_one_step(self, sub: SubAgent) -> None:
        decision, parse_error = await self._ask_llm_for_decision(sub)
        if decision is None:
            self._fail_unparseable(sub, parse_error)
            return
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
        parameters = self._extract_parameters(decision)

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

        # ActionManager handles action_start/action_end logging to the child
        # stream, error capture, and idempotency. We pass session_id=sub.id
        # so every log routes to the child's per-id stream.
        await self.action_manager.execute_action(
            action=action,
            context="",
            event_stream="",
            session_id=sub.id,
            is_running_task=True,
            is_gui_task=False,
            input_data=parameters,
        )

    @staticmethod
    def _extract_parameters(decision: Dict[str, Any]) -> Dict[str, Any]:
        """Return action inputs from the accepted decision parameter keys."""
        parameters = decision.get("parameters")
        if isinstance(parameters, dict):
            return parameters

        # The compact action list describes schemas under ``params``. Some
        # providers mirror that key in their decision even though the required
        # output shape says ``parameters``.
        params_alias = decision.get("params")
        if isinstance(params_alias, dict):
            return params_alias

        return {}

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
        self.llm_interface.create_session_cache(
            sub.id, _SUBAGENT_CALL_TYPE, system_prompt
        )

    def _reset_session(self, sub: SubAgent, stream) -> None:
        """
        Drop the session cache and the stream's sync point for this turn.

        Called when the stream signals the sync point is no longer usable
        (e.g. summarization has rolled events past it). The next call to
        ``_build_user_prompt`` will resend the full first-turn prompt and
        the LLM interface will lazily recreate the session.
        """
        self.llm_interface.end_session_cache(sub.id, _SUBAGENT_CALL_TYPE)
        stream.reset_session_sync(_SUBAGENT_CALL_TYPE)

    # ------------------------------------------------------------------
    # LLM call + JSON parsing — session-cache aware
    # ------------------------------------------------------------------

    async def _ask_llm_for_decision(
        self, sub: SubAgent
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Ask the LLM for the next action and return ``(decision, error)``.

        Builds the user prompt (full first-turn vs. delta), invokes the
        LLM, parses the JSON, and retries up to ``_MAX_PARSE_RETRIES``
        times if the response is unparseable. Returns ``(None, error)``
        if every attempt fails.

        Marks the stream's sync point on the first successful parse so
        the next turn only sees events appended since this one.
        """
        stream = self.event_stream_manager.get_stream_by_id(sub.id)
        base_user_prompt, is_first_turn = self._build_user_prompt(sub, stream)
        system_prompt = self.context_engine.make_system_prompt(sub)

        current_user_prompt = base_user_prompt
        last_error: Optional[str] = None
        last_raw: Optional[str] = None

        for attempt in range(1, _MAX_PARSE_RETRIES + 1):
            try:
                raw = await self._invoke_llm(sub, current_user_prompt, system_prompt)
            except LLMConsecutiveFailureError:
                # Fatal: the LLM is in a broken state (e.g. out-of-credits,
                # auth). Retrying within this turn can't help — let it
                # propagate so the runner ends the sub-agent with the real
                # cause instead of looping the parse retries.
                raise
            except Exception as e:
                logger.exception(
                    f"[SubAgentRunner] {sub.id} LLM call failed on attempt {attempt}: {e}"
                )
                last_error = f"LLM call failed: {e}"
                continue

            last_raw = raw or ""
            decision, parse_error = self._parse_decision(raw)
            if decision is not None:
                # Advance the sync point so the next turn's delta excludes
                # everything up to and including this turn's outcome.
                stream.mark_session_synced(_SUBAGENT_CALL_TYPE)
                return decision, None

            last_error = parse_error or "unknown parse error"
            logger.warning(
                f"[SubAgentRunner] {sub.id} parse error attempt {attempt}: "
                f"{last_error} | raw={raw!r}"
            )
            current_user_prompt = self._augment_with_retry_hint(
                base=base_user_prompt if is_first_turn else current_user_prompt,
                attempt=attempt,
                error=last_error,
            )

        return None, f"{last_error} (last raw response: {last_raw!r})"

    async def _invoke_llm(
        self, sub: SubAgent, user_prompt: str, system_prompt: str
    ) -> str:
        """
        One round-trip to the LLM via the session-cache path.

        ``system_prompt_for_new_session`` is passed every turn so the LLM
        interface can recreate the session if a context-overflow reset
        happened underneath us.
        """
        return await self.llm_interface.generate_response_with_session_async(
            task_id=sub.id,
            call_type=_SUBAGENT_CALL_TYPE,
            user_prompt=user_prompt,
            system_prompt_for_new_session=system_prompt,
            prompt_name=f"SUBAGENT_{sub.agent_type.upper()}",
        )

    @staticmethod
    def _augment_with_retry_hint(base: str, attempt: int, error: str) -> str:
        return (
            f"{base}\n\n"
            f"PREVIOUS ATTEMPT {attempt} FAILED TO PARSE.\n"
            f"Error: {error}\n"
            "Reply with ONLY the JSON object as specified. "
            "No prose, no fences."
        )

    # ------------------------------------------------------------------
    # User-prompt builder (first turn vs. delta)
    # ------------------------------------------------------------------

    def _build_user_prompt(self, sub: SubAgent, stream) -> Tuple[str, bool]:
        """Return ``(user_prompt, is_first_turn)``.

        First turn: send the full query + the initial event log.

        Delta turns: send only events added since the last sync point. If
        the stream reports no delta (e.g. summarization rolled events
        past the sync point), reset the session and fall back to a fresh
        first-turn prompt — that's the only path that re-grounds the
        model after the cached history vanishes.
        """
        if not stream.has_session_sync(_SUBAGENT_CALL_TYPE):
            return self.context_engine.make_first_turn_user_prompt(sub), True

        delta_str, has_delta = stream.get_delta_events(_SUBAGENT_CALL_TYPE)
        if not has_delta:
            logger.info(
                f"[SubAgentRunner] {sub.id} no delta events / summarization "
                "detected — resetting session and resending full prompt"
            )
            self._reset_session(sub, stream)
            return self.context_engine.make_first_turn_user_prompt(sub), True

        return self.context_engine.make_delta_user_prompt(delta_str), False

    # ------------------------------------------------------------------
    # JSON parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_decision(
        raw: Optional[str],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Robust JSON/dict parsing of an LLM decision."""
        if not raw or not raw.strip():
            return None, "empty LLM response"

        text = raw.strip()
        # Strip BOM, normalize line endings.
        if text.startswith("﻿"):
            text = text[1:]
        text = text.replace("\r\n", "\n").replace("\r", "").strip()

        # Strip markdown code fences if the LLM ignored instructions.
        if text.startswith("```"):
            first_nl = text.find("\n")
            if first_nl != -1:
                text = text[first_nl + 1 :]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            try:
                parsed = ast.literal_eval(text)
            except Exception as e2:
                return None, f"json: {e}; literal_eval: {e2}"

        if not isinstance(parsed, dict):
            return None, "parsed value is not a dict"
        if "action_name" not in parsed:
            return None, "missing 'action_name' field"
        return parsed, None


__all__ = ["SubAgentRunner"]
