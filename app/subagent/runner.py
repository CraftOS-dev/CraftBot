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
  action_start / action_end to the sub-agent's stream (because we pass
  ``session_id=sub.id`` and ``is_running_task=True``).
- ``sub_task_end`` is the action that marks the sub-agent terminal —
  the runner detects that by checking ``sub.is_terminal()`` after every
  step.

Session caching:
- Sub-agents use the same provider-agnostic session-cache plumbing as
  ``ActionRouter._prompt_for_decision``. On the first turn we register a
  session via :meth:`LLMInterface.create_session_cache` (so the system
  prompt is stored for overflow recovery), then call
  ``generate_response_with_session_async`` with the full first-turn user
  prompt. On every subsequent turn we send only the events that have
  been appended to the child's event stream since the last call —
  drastically reducing tokens for multi-turn sub-agents.
- For providers that don't support session caching (e.g. ollama), the
  LLM interface transparently falls back to ``_generate_response_sync``.
  The delta-only path becomes equivalent to a no-cache call, which is
  the same behavior the main agent has on those providers.

Resource cleanup:
- ``SubAgentManager.end()`` only flips status and writes a breadcrumb;
  it deliberately leaves the stream alive so the ``sub_task_end`` action
  can finish logging ``action_end`` to the child stream.
- After the loop exits, the runner calls ``SubAgentManager.release()`` to
  drop the stream and release session caches.
"""

from __future__ import annotations

import ast
import json
import time
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from agent_core.core.impl.llm import LLMCallType
from app.logger import logger
from app.subagent.context_engine import SubAgentContextEngine
from app.subagent.types import SubAgent, get_subagent_config

if TYPE_CHECKING:
    from agent_core.core.impl.action.library import ActionLibrary
    from agent_core.core.impl.action.manager import ActionManager
    from app.event_stream import EventStreamManager
    from app.llm import LLMInterface
    from app.subagent.manager import SubAgentManager


# Max LLM format-error retries per turn before we abort the sub-agent.
_MAX_PARSE_RETRIES = 3

# Sub-agents only ever do action selection — never GUI or reasoning calls
# — so a single call type covers their entire lifetime.
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
        cfg = get_subagent_config(sub.agent_type)
        max_iter = cfg["max_iterations"]
        max_wall = cfg["max_wall_seconds"]
        deadline = time.monotonic() + max_wall

        logger.info(
            f"[SubAgentRunner] starting {sub.id} type={sub.agent_type} "
            f"max_iter={max_iter} max_wall={max_wall}s"
        )

        try:
            while not sub.is_terminal():
                # Increment at the TOP of the loop so `sub.iterations`
                # reflects the turn currently being executed. This makes
                # the manager's "Ended iterations=N" and the runner's
                # "loop done iterations=N" agree.
                sub.iterations += 1

                if sub.iterations > max_iter:
                    logger.warning(
                        f"[SubAgentRunner] {sub.id} hit iteration cap "
                        f"({max_iter}); ending as failed"
                    )
                    # Roll the count back to the cap so it doesn't appear
                    # we ran an extra turn we never actually executed.
                    sub.iterations = max_iter
                    self.subagent_manager.end(
                        sub.id,
                        status="failed",
                        result=(
                            f"(sub-agent exhausted iteration cap of {max_iter} "
                            "without calling sub_task_end)"
                        ),
                    )
                    break

                if time.monotonic() > deadline:
                    logger.warning(
                        f"[SubAgentRunner] {sub.id} hit wall-clock cap "
                        f"({max_wall}s); ending as timeout"
                    )
                    sub.iterations -= 1  # un-count the turn we never ran
                    self.subagent_manager.end(
                        sub.id,
                        status="timeout",
                        result=(
                            f"(sub-agent ran past wall-clock cap of {max_wall}s "
                            "without calling sub_task_end)"
                        ),
                    )
                    break

                try:
                    await self._run_one_step(sub)
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
                    # Don't immediately fail — let the next step observe
                    # the error and self-correct, up to the iteration cap.

            logger.info(
                f"[SubAgentRunner] {sub.id} loop done. status={sub.status} "
                f"iterations={sub.iterations}"
            )
            return sub
        finally:
            # CRITICAL: release stream + session caches AFTER the loop has
            # exited, not inside SubAgentManager.end(). ActionManager logs
            # ``action_end`` for ``sub_task_end`` after our action call
            # returns; that log must still find the child's stream.
            try:
                self.subagent_manager.release(sub.id)
            except Exception as e:
                logger.warning(
                    f"[SubAgentRunner] release({sub.id}) failed: {e}"
                )

    # ------------------------------------------------------------------
    # One step: prompt → decision → execute
    # ------------------------------------------------------------------

    async def _run_one_step(self, sub: SubAgent) -> None:
        decision, parse_error = await self._ask_llm_for_decision(sub)
        if parse_error or decision is None:
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
            return

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

    # ------------------------------------------------------------------
    # LLM call + JSON parsing — session-cache aware
    # ------------------------------------------------------------------

    async def _ask_llm_for_decision(
        self, sub: SubAgent
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Get a parsed decision dict from the LLM.

        On the first turn we register a session cache with the sub-agent's
        system prompt and send the full first-turn user prompt (query +
        initial event log + decision nudge). On every subsequent turn we
        send only the events that have been appended to the child stream
        since the last call.

        The LLM interface transparently falls back to standard generation
        for providers that don't support session caching.

        Retries up to ``_MAX_PARSE_RETRIES`` times on unparseable responses.
        """
        system_prompt = self.context_engine.make_system_prompt(sub)
        stream = self.event_stream_manager.get_stream_by_id(sub.id)

        # Ensure the session is registered. ``create_session_cache`` stores
        # the system prompt for lazy session creation on the first actual
        # call AND for context-overflow recovery on later calls. It's
        # idempotent — re-registering just overwrites the stored prompt
        # (which is stable for a given sub-agent anyway).
        try:
            self.llm_interface.create_session_cache(
                sub.id, _SUBAGENT_CALL_TYPE, system_prompt
            )
        except Exception as e:
            # Non-fatal — the call below will still work via the
            # ``system_prompt_for_new_session`` argument.
            logger.warning(
                f"[SubAgentRunner] create_session_cache failed for {sub.id}: {e}"
            )

        # Decide first-turn vs delta-turn.
        user_prompt, is_first_turn = self._build_user_prompt(sub, stream)

        last_error: Optional[str] = None
        last_raw: Optional[str] = None
        current_user_prompt = user_prompt

        for attempt in range(1, _MAX_PARSE_RETRIES + 1):
            try:
                raw = await self.llm_interface.generate_response_with_session_async(
                    task_id=sub.id,
                    call_type=_SUBAGENT_CALL_TYPE,
                    user_prompt=current_user_prompt,
                    system_prompt_for_new_session=system_prompt,
                    prompt_name=f"SUBAGENT_{sub.agent_type.upper()}",
                )
            except Exception as e:
                logger.exception(
                    f"[SubAgentRunner] {sub.id} LLM call failed on attempt {attempt}: {e}"
                )
                last_error = f"LLM call failed: {e}"
                continue

            last_raw = raw or ""
            decision, parse_error = self._parse_decision(raw)
            if decision is not None:
                # Mark this turn's events as synced. For the FIRST turn we
                # also mark synced — so the next turn's get_delta_events
                # only returns events added AFTER this point. For DELTA
                # turns we mark again, advancing the sync point past the
                # action_start/action_end events the upcoming action will
                # produce.
                try:
                    stream.mark_session_synced(_SUBAGENT_CALL_TYPE)
                except Exception as e:
                    logger.warning(
                        f"[SubAgentRunner] {sub.id} mark_session_synced failed: {e}"
                    )
                return decision, None

            last_error = parse_error or "unknown parse error"
            logger.warning(
                f"[SubAgentRunner] {sub.id} parse error attempt {attempt}: "
                f"{last_error} | raw={raw!r}"
            )
            # On retry, append a corrective nudge. We deliberately do NOT
            # rebuild the full first-turn prompt — once the session is
            # established, only the retry hint needs to be sent.
            current_user_prompt = (
                user_prompt if is_first_turn else current_user_prompt
            ) + (
                f"\n\nPREVIOUS ATTEMPT {attempt} FAILED TO PARSE.\n"
                f"Error: {last_error}\n"
                "Reply with ONLY the JSON object as specified. "
                "No prose, no fences."
            )

        return None, f"{last_error} (last raw response: {last_raw!r})"

    # ------------------------------------------------------------------
    # User-prompt builder (first turn vs delta)
    # ------------------------------------------------------------------

    def _build_user_prompt(self, sub: SubAgent, stream) -> Tuple[str, bool]:
        """Return ``(user_prompt, is_first_turn)``."""
        if not stream.has_session_sync(_SUBAGENT_CALL_TYPE):
            # First turn: send query + initial event log.
            return self.context_engine.make_first_turn_user_prompt(sub), True

        # Delta turn: pull only events added since last sync. If
        # summarization happened (or no new events), ``has_delta`` is False;
        # we treat that as cache invalidation and fall back to a full
        # first-turn prompt with a fresh session.
        delta_str, has_delta = stream.get_delta_events(_SUBAGENT_CALL_TYPE)
        if not has_delta:
            logger.info(
                f"[SubAgentRunner] {sub.id} no delta events / summarization "
                "detected — resetting session and resending full prompt"
            )
            try:
                self.llm_interface.end_session_cache(
                    sub.id, _SUBAGENT_CALL_TYPE
                )
            except Exception as e:
                logger.warning(
                    f"[SubAgentRunner] end_session_cache failed for {sub.id}: {e}"
                )
            try:
                stream.reset_session_sync(_SUBAGENT_CALL_TYPE)
            except Exception as e:
                logger.warning(
                    f"[SubAgentRunner] reset_session_sync failed for {sub.id}: {e}"
                )
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
