# -*- coding: utf-8 -*-
"""
ActionRouter for action selection based on user queries and task context.

This module provides the ActionRouter class that selects actions
based on user queries using LLM reasoning.
"""

from __future__ import annotations

import json
import ast
from typing import Optional, List, Dict, Any, Tuple

from agent_core.core.state import get_state, get_session_or_none
from agent_core.decorators import profile, OperationCategory
from agent_core.core.protocols.action import ActionLibraryProtocol
from agent_core.core.protocols.context import ContextEngineProtocol
from agent_core.core.protocols.llm import LLMInterfaceProtocol
from agent_core.core.impl.llm import LLMCallType
from agent_core.core.impl.llm.errors import LLMConsecutiveFailureError
from agent_core.core.errors import ClassifiedError, ErrorCategory, ErrorInfo
from agent_core.core.prompts import SELECT_ACTION_PROMPT
from agent_core.utils.logger import logger


def _is_visible_in_mode(action, GUI_mode: bool) -> bool:
    """
    Returns True if the action should be visible under the given GUI_mode.
    - Empty/missing mode is visible in both modes.
    - 'GUI' is visible only when GUI_mode=True.
    - 'CLI' is visible only when GUI_mode=False.
    - 'ALL' is visible when GUI_mode=False and GUI_mode=True.
    """
    mode = getattr(action, "mode", None)
    if not mode:  # None, "", or falsy -> visible in both
        return True
    if mode == "ALL":
        return True
    m = str(mode).strip().upper()
    if GUI_mode:
        return m == "GUI"
    else:
        return m == "CLI"


class ActionRouter:
    """
    Selects actions based on user queries, with an LLM verifying correctness
    or creating new actions on the fly.
    """

    def __init__(
        self,
        action_library: ActionLibraryProtocol,
        llm_interface: LLMInterfaceProtocol,
        context_engine: ContextEngineProtocol,
    ):
        """
        Initialize the router responsible for selecting or creating actions.

        Args:
            action_library: Repository for storing and retrieving action definitions.
            llm_interface: LLM client used to reason about which action to run.
            context_engine: Provider of system prompts and context formatting.
        """
        self.action_library = action_library
        self.llm_interface = llm_interface
        self.context_engine = context_engine

    @profile("action_router_select_action", OperationCategory.ACTION_ROUTING)
    async def select_action_in_session(
        self,
        query: str,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        The one action-selection call for a session turn.
        Supports parallel action selection - returns a list of actions.

        Args:
            query: The turn's instruction (the trigger description).
            session_id: Session ID for session-specific state lookup.

        Returns:
            List[Dict[str, Any]]: List of decision payloads, each with
            ``action_name``, ``parameters``, and ``reasoning`` for execution.

        Raises:
            ValueError: If LLM returns invalid format 3 times consecutively.
        """
        # Get compiled action list from the session's loaded action sets
        compiled_actions = self._get_session_compiled_actions(session_id=session_id)

        # Use static compiled list - NO RAG SEARCH
        action_candidates = self._build_candidates_from_compiled_list(
            compiled_actions, GUI_mode=False, ignore_actions=None
        )
        logger.info(
            f"ActionRouter using compiled action list: {len(action_candidates)} actions"
        )

        # Build the instruction prompt for the LLM
        session_state = self.context_engine.get_session_state(session_id=session_id)
        event_stream_content = self.context_engine.get_event_stream(
            session_id=session_id
        )

        # Pull just-in-time guidance for any integrations the user named.
        # Match against both the current turn's query and the session state so
        # the platform name from the original user request still triggers a
        # match even after the per-turn query is generic ("Perform the next
        # best action...").
        try:
            from app.data.action.integrations._integration_essentials import (
                get_essentials_for_message,
            )

            integration_essentials = get_essentials_for_message(
                f"{query}\n{session_state}"
            )
            logger.info(
                f"[ACTION] integration essentials: "
                f"{len(integration_essentials)} chars injected"
            )
        except Exception as e:
            logger.debug(f"[ACTION] integration essentials lookup failed: {e}")
            integration_essentials = ""

        decision_prompt_name = "SELECT_ACTION"
        static_prompt = SELECT_ACTION_PROMPT.format(
            session_state=session_state,
            event_stream="",  # Empty for static prompt
            query=query,
            action_candidates=self._format_candidates(action_candidates),
            integration_essentials=integration_essentials,
        )
        full_prompt = SELECT_ACTION_PROMPT.format(
            session_state=session_state,
            event_stream=event_stream_content,
            query=query,
            action_candidates=self._format_candidates(action_candidates),
            integration_essentials=integration_essentials,
        )

        max_format_retries = 3
        current_prompt = full_prompt

        for attempt in range(max_format_retries):
            decision = await self._prompt_for_decision(
                current_prompt,
                is_task=True,
                static_prompt=static_prompt,
                call_type=LLMCallType.ACTION_SELECTION,
                session_id=session_id,
                prompt_name=decision_prompt_name,
            )

            # Parse parallel action decisions with format error detection
            actions, format_error = self._parse_parallel_action_decisions(decision)

            if format_error:
                # LLM returned wrong format - retry with feedback
                logger.warning(
                    f"[FORMAT ERROR] Attempt {attempt + 1}/{max_format_retries}: {format_error}"
                )

                if attempt < max_format_retries - 1:
                    current_prompt = self._augment_prompt_with_format_error(
                        full_prompt, attempt + 1, decision, format_error
                    )
                    continue
                else:
                    raise ValueError(
                        f"LLM output format error after {max_format_retries} attempts. "
                        f"Last error: {format_error}. Run aborted to prevent token waste."
                    )

            if not actions:
                # Empty action list (no format error) - return empty decision for backward compatibility
                return [
                    {
                        "action_name": "",
                        "parameters": {},
                        "reasoning": decision.get("reasoning", ""),
                    }
                ]

            # Validate and filter parallel actions
            validated_actions = self._validate_parallel_actions(actions, GUI_mode=False)

            if validated_actions:
                action_names = [a.get("action_name") for a in validated_actions]
                logger.info(
                    f"[PARALLEL] Selected {len(validated_actions)} action(s): {action_names}"
                )
                return validated_actions

            logger.warning(
                f"No valid actions found during selection attempt {attempt + 1}"
            )

        raise ValueError("Invalid selected action returned by LLM after retries.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _prompt_for_decision(
        self,
        prompt: str,
        is_task: bool = False,
        static_prompt: Optional[str] = None,
        call_type: str = LLMCallType.ACTION_SELECTION,
        session_id: Optional[str] = None,
        prompt_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Prompt the LLM for an action decision with session caching support.

        Args:
            prompt: The full prompt to send to the LLM.
            is_task: Whether this is a task-related call.
            static_prompt: Optional static portion for caching.
            call_type: Type of LLM call for cache keying.
            session_id: Optional session ID for session-specific state lookup.
            prompt_name: Identity of the named prompt, tagged onto the captured
                LLM call for per-prompt profiling.
        """
        max_retries = 3
        last_error: Optional[Exception] = None
        current_prompt = prompt

        # Get current task_id for session cache (if running in a task)
        # Use session_id if provided, otherwise fall back to global state
        if session_id:
            current_task_id = session_id
        elif is_task:
            session = get_session_or_none(session_id)
            if session:
                current_task_id = session.session_id
            else:
                current_task_id = get_state().get_agent_property("current_task_id", "")
        else:
            current_task_id = ""

        for attempt in range(max_retries):
            # KV CACHING: System prompt is STATIC only (no dynamic content)
            # agent_info is included for all modes to provide consistent agent context
            system_prompt, _ = self.context_engine.make_prompt(
                user_flags={"query": False, "expected_output": False},
                system_flags={"agent_info": True},
            )

            raw_response = None

            try:
                # Use session cache if we're in a task context AND session is registered
                if current_task_id and is_task:
                    has_session = self.llm_interface.has_session_cache(
                        current_task_id, call_type
                    )

                    if has_session:
                        # Session is registered (complex task) - use session caching
                        # CRITICAL: Use session-specific stream to prevent event leakage
                        from agent_core import get_event_stream_manager

                        event_stream_manager = get_event_stream_manager()
                        # Use get_stream_by_id with session_id to get the correct task's stream
                        effective_session_id = session_id or current_task_id
                        stream = (
                            event_stream_manager.get_stream_by_id(effective_session_id)
                            if event_stream_manager
                            else None
                        )
                        has_synced_before = (
                            stream.has_session_sync(call_type) if stream else False
                        )

                        if has_synced_before:
                            # We've made calls before - send only delta events
                            # CRITICAL: Pass session_id to get delta from the correct stream
                            delta_events, has_delta = (
                                self.context_engine.get_event_stream_delta(
                                    call_type, session_id=effective_session_id
                                )
                            )

                            if has_delta:
                                # Send only the new events
                                logger.info(
                                    f"[SESSION CACHE] Sending delta events for {call_type}"
                                )
                                raw_response = await self.llm_interface.generate_response_with_session_async(
                                    task_id=current_task_id,
                                    call_type=call_type,
                                    user_prompt=delta_events,
                                    system_prompt_for_new_session=system_prompt,
                                    prompt_name=prompt_name,
                                )
                                # Mark events as synced after successful call
                                self.context_engine.mark_event_stream_synced(
                                    call_type, session_id=effective_session_id
                                )
                            else:
                                # No new events - this could mean summarization happened
                                logger.info(
                                    f"[SESSION CACHE] No delta events, resetting cache for {call_type}"
                                )
                                self.llm_interface.end_session_cache(
                                    current_task_id, call_type
                                )
                                self.context_engine.reset_event_stream_sync(
                                    call_type, session_id=effective_session_id
                                )
                                # Fall through to first-call path
                                has_synced_before = False

                        if not has_synced_before:
                            # First call with session - send full prompt to establish session
                            logger.info(
                                f"[SESSION CACHE] Creating new session for {call_type} (first call)"
                            )
                            raw_response = await self.llm_interface.generate_response_with_session_async(
                                task_id=current_task_id,
                                call_type=call_type,
                                user_prompt=current_prompt,
                                system_prompt_for_new_session=system_prompt,
                                prompt_name=prompt_name,
                            )
                            # Mark events as synced after successful session creation
                            self.context_engine.mark_event_stream_synced(
                                call_type, session_id=effective_session_id
                            )
                    else:
                        # No session registered (simple task) - use prefix cache / regular response
                        raw_response = await self.llm_interface.generate_response_async(
                            system_prompt, current_prompt, prompt_name=prompt_name
                        )
                else:
                    # Not in task context - use regular response
                    raw_response = await self.llm_interface.generate_response_async(
                        system_prompt, current_prompt, prompt_name=prompt_name
                    )

                # Validate response before parsing
                if not raw_response or (
                    isinstance(raw_response, str) and not raw_response.strip()
                ):
                    logger.error(
                        f"[ACTION ROUTER] LLM returned empty response on attempt {attempt + 1}. "
                        f"System prompt length: {len(system_prompt)}, User prompt length: {len(current_prompt)}"
                    )

                decision, parse_error = self._parse_action_decision(raw_response)
                if decision is not None:
                    decision.setdefault("parameters", {})
                    decision["parameters"] = self._ensure_parameters(
                        decision.get("parameters")
                    )
                    return decision

                feedback_error = parse_error or "unknown parsing error"
                last_error = ValueError(
                    f"Unable to parse action decision on attempt {attempt + 1}: {feedback_error}"
                )
                logger.warning(
                    f"Failed to parse LLM decision on attempt {attempt + 1}: "
                    f"{raw_response} | error={feedback_error}"
                )
                current_prompt = self._augment_prompt_with_feedback(
                    prompt, attempt + 1, raw_response, feedback_error
                )
            except LLMConsecutiveFailureError:
                # Fatal: LLM is in a broken state - re-raise immediately, do not retry
                raise
            except RuntimeError as e:
                # LLM provider error (empty response, API error, auth failure, etc.)
                # — a recognized, user-actionable failure, not a code bug. The
                # attempt-number bookkeeping stays in the log only; the
                # user-facing message (ClassifiedError.info.message) stays
                # short and skips it.
                error_msg = str(e)
                logger.error(
                    f"[ACTION ROUTER] LLM provider error on attempt {attempt + 1}: {error_msg}"
                )
                last_error = ClassifiedError(
                    ErrorInfo(
                        category=ErrorCategory.UNKNOWN,
                        code="ACTION_DECISION_FAILED",
                        title="Action decision failed",
                        message=(
                            f"{error_msg.rstrip('.')}. Check LLM configuration, "
                            f"API credentials, and service availability."
                        ),
                    )
                )
                # After 3 attempts, give up
                if attempt >= max_retries - 1:
                    raise last_error
                # Otherwise, retry with more context in the prompt
                current_prompt = self._augment_prompt_with_feedback(
                    prompt,
                    attempt + 1,
                    f"[LLM ERROR] {error_msg}",
                    "LLM provider failed - retrying",
                )
            except Exception as e:
                # Unexpected error
                logger.error(
                    f"[ACTION ROUTER] Unexpected error on attempt {attempt + 1}: {e}",
                    exc_info=True,
                )
                last_error = RuntimeError(
                    f"Unexpected error in action selection on attempt {attempt + 1}: {e}"
                )
                if attempt >= max_retries - 1:
                    raise last_error
                current_prompt = self._augment_prompt_with_feedback(
                    prompt,
                    attempt + 1,
                    f"[ERROR] {str(e)}",
                    "An unexpected error occurred - retrying",
                )

        if last_error:
            raise last_error
        raise ValueError("Unable to parse LLM decision")

    def _parse_action_decision(
        self, raw: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        # Check for empty or None response from LLM
        if not raw or (isinstance(raw, str) and not raw.strip()):
            logger.error("LLM returned empty response")
            return (
                None,
                "LLM returned an empty response. This may indicate an API error or the model failed to generate output.",
            )

        # Normalize Windows/encoding artifacts (BOM, CRLF, etc.)
        # This handles Windows CRLF line endings and encoding issues
        normalized = raw

        # Remove BOM if present (Windows encoding artifact)
        if normalized.startswith("\ufeff"):
            normalized = normalized[1:]

        # Normalize line endings to LF (convert CRLF to LF)
        normalized = normalized.replace("\r\n", "\n")

        # Remove any remaining carriage returns
        normalized = normalized.replace("\r", "")

        # Strip all leading/trailing whitespace
        normalized = normalized.strip()

        if not normalized:
            logger.error(
                f"Response was empty after normalization. Original: {repr(raw)}"
            )
            return (
                None,
                "LLM response was empty or only contained whitespace after normalization.",
            )

        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError as json_error:
            try:
                parsed = ast.literal_eval(normalized)
            except Exception as eval_error:
                logger.error(f"Unable to parse action decision: {repr(normalized)}")
                return (
                    None,
                    f"json error: {json_error}; literal_eval error: {eval_error}",
                )

        if not isinstance(parsed, dict):
            logger.error(f"Parsed action decision is not a dict: {repr(normalized)}")
            return None, "parsed value is not a dictionary"

        return parsed, None

    def _augment_prompt_with_feedback(
        self,
        base_prompt: str,
        attempt: int,
        raw_response: str,
        error_message: str,
    ) -> str:
        feedback_block = (
            f"\n\nPrevious attempt {attempt} failed to parse because: {error_message}. "
            "Review your last reply above (shown in the RAW RESPONSE section) and return a corrected response. "
            "You must return ONLY a JSON object with action_name and parameters fields. "
            "Do not include any additional commentary, code fences, or explanatory text.\n\n"
            "RAW RESPONSE:\n"
            f"{raw_response}\n"
            "--- End of RAW RESPONSE ---\n"
            "Respond now with the corrected JSON object."
        )
        return base_prompt + feedback_block

    def _augment_prompt_with_format_error(
        self,
        base_prompt: str,
        attempt: int,
        decision: Dict[str, Any],
        format_error: str,
    ) -> str:
        """
        Augment prompt with format error feedback to help LLM correct its output.

        Args:
            base_prompt: Original prompt.
            attempt: Current attempt number.
            decision: The parsed decision that had format issues.
            format_error: Detailed error message explaining what was wrong.

        Returns:
            Augmented prompt with error feedback.
        """
        try:
            raw_response = json.dumps(decision, indent=2, ensure_ascii=False)
        except Exception:
            raw_response = str(decision)

        feedback_block = (
            f"\n\n{'=' * 60}\n"
            f"⚠️ OUTPUT FORMAT ERROR (Attempt {attempt}/3)\n"
            f"{'=' * 60}\n\n"
            f"{format_error}\n\n"
            f"YOUR INCORRECT RESPONSE:\n"
            f"```json\n{raw_response}\n```\n\n"
            f"CORRECT FORMAT REQUIRED:\n"
            f"```json\n"
            f"{{\n"
            f'  "reasoning": "<your reasoning here>",\n'
            f'  "actions": [\n'
            f"    {{\n"
            f'      "action_name": "<action from available actions>",\n'
            f'      "parameters": {{\n'
            f'        "<param_name>": <value>\n'
            f"      }}\n"
            f"    }}\n"
            f"  ]\n"
            f"}}\n"
            f"```\n\n"
            f"⚠️ This is attempt {attempt} of 3. If you fail again, the task will be ABORTED.\n"
            f"Return ONLY the corrected JSON object with the exact format shown above.\n"
            f"{'=' * 60}\n"
        )
        return base_prompt + feedback_block

    def _format_candidates(self, candidates: List[Dict[str, Any]]) -> str:
        """Format action candidates with compact schema for reduced prompt size.

        Delegates to ``agent_core.core.action_framework.format_action_candidates``
        so the format stays in sync with the sub-agent prompt builder.
        """
        from agent_core.core.action_framework import format_action_candidates

        return format_action_candidates(candidates)

    def _format_action_names(self, names: List[str]) -> str:
        if not names:
            return "[]"
        return json.dumps(names, indent=2, ensure_ascii=False)

    def _format_event_stream(self, event_stream: str | list | dict | None) -> str:
        if not event_stream:
            return "No prior events available."
        if isinstance(event_stream, (list, dict)):
            return json.dumps(event_stream, indent=2, ensure_ascii=False)
        return str(event_stream)

    def _ensure_parameters(self, parameters: Any) -> Dict[str, Any]:
        if isinstance(parameters, dict):
            return parameters
        return {}

    def _parse_parallel_action_decisions(
        self, decision: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Parse LLM response for parallel action format.

        Expected format: {"reasoning": "...", "actions": [{"action_name": "...", "parameters": {...}}, ...]}

        Returns:
            Tuple of (actions_list, format_error_message).
            If format_error_message is not None, the LLM response was in wrong format.
        """
        if decision is None:
            return [], "Response is empty or null"

        reasoning = decision.get("reasoning", "")

        # Detect common format errors and provide helpful feedback
        format_error = self._detect_format_error(decision)
        if format_error:
            return [], format_error

        # Parse "actions" array format
        if "actions" in decision and isinstance(decision["actions"], list):
            actions = []
            for idx, action in enumerate(decision["actions"]):
                if isinstance(action, dict):
                    # Check for wrong key names within action items
                    action_error = self._detect_action_item_error(action, idx)
                    if action_error:
                        return [], action_error

                    if action.get("action_name"):
                        action["reasoning"] = reasoning
                        action["parameters"] = self._ensure_parameters(
                            action.get("parameters")
                        )
                        actions.append(action)

            if not actions:
                return [], (
                    "The 'actions' array is empty or contains no valid action items. "
                    "Each action item must have an 'action_name' field."
                )
            return actions, None

        return [], "Response is missing the required 'actions' array"

    def _detect_format_error(self, decision: Dict[str, Any]) -> Optional[str]:
        """
        Detect common LLM output format errors and return a helpful error message.

        Returns:
            Error message if format is wrong, None if format looks correct.
        """
        # Check for "response" key - LLM trying to respond conversationally
        if "response" in decision and "actions" not in decision:
            return (
                "WRONG FORMAT: You returned a 'response' key instead of the required format. "
                "Do NOT respond conversationally. You MUST return a JSON with 'reasoning' and 'actions' fields. "
                'Example: {"reasoning": "...", "actions": [{"action_name": "send_message", "parameters": {"message": "..."}}]}'
            )

        # Check for "action" key instead of "actions" array
        if "action" in decision and "actions" not in decision:
            action_value = decision.get("action", "")
            args_value = decision.get("args", decision.get("parameters", {}))
            return (
                f"WRONG FORMAT: You used 'action' key instead of 'actions' array. "
                f"The correct format uses 'actions' (plural) as an array. "
                f'Correct your response to: {{"reasoning": "...", "actions": [{{"action_name": "{action_value}", "parameters": {args_value}}}]}}'
            )

        # Check for "args" at top level (wrong structure)
        if "args" in decision and "actions" not in decision:
            return (
                "WRONG FORMAT: You used 'args' at the top level. "
                'The correct format is: {"reasoning": "...", "actions": [{"action_name": "...", "parameters": {...}}]}. '
                "'parameters' should be inside each action item, not at the top level."
            )

        # Check for "message" at top level (trying to send message without proper format)
        if "message" in decision and "actions" not in decision:
            msg = decision.get("message", "")
            return (
                f"WRONG FORMAT: You tried to send a message directly. "
                f'Use the proper action format: {{"reasoning": "...", "actions": [{{"action_name": "send_message", "parameters": {{"message": "{msg[:50]}..."}}}}]}}'
            )

        # Check if actions exists but is not a list
        if "actions" in decision and not isinstance(decision["actions"], list):
            return (
                "WRONG FORMAT: 'actions' must be an array/list, not a single object. "
                'Even for a single action, wrap it in an array: {"reasoning": "...", "actions": [{...}]}'
            )

        return None

    def _detect_action_item_error(
        self, action: Dict[str, Any], idx: int
    ) -> Optional[str]:
        """
        Detect format errors within an action item.

        Returns:
            Error message if format is wrong, None if format looks correct.
        """
        # Check for "action" instead of "action_name"
        if "action" in action and "action_name" not in action:
            action_value = action.get("action", "")
            return (
                f"WRONG FORMAT in action item {idx}: You used 'action' instead of 'action_name'. "
                f'The correct key is \'action_name\'. Example: {{"action_name": "{action_value}", "parameters": {{...}}}}'
            )

        # Check for "args" instead of "parameters"
        if "args" in action and "parameters" not in action:
            return (
                f"WRONG FORMAT in action item {idx}: You used 'args' instead of 'parameters'. "
                f'The correct key is \'parameters\'. Example: {{"action_name": "...", "parameters": {{...}}}}'
            )

        # Check for "name" instead of "action_name"
        if "name" in action and "action_name" not in action:
            name_value = action.get("name", "")
            return (
                f"WRONG FORMAT in action item {idx}: You used 'name' instead of 'action_name'. "
                f'The correct key is \'action_name\'. Example: {{"action_name": "{name_value}", "parameters": {{...}}}}'
            )

        return None

    def _validate_parallel_actions(
        self, actions: List[Dict[str, Any]], GUI_mode: bool
    ) -> List[Dict[str, Any]]:
        """
        Validate and filter parallel actions.

        Rules:
        - Max 10 actions per batch
        - If any action is non-parallelizable (action.parallelizable=False), return only first action
        - Validate each action exists and is visible in current mode

        Args:
            actions: List of parsed action decisions.
            GUI_mode: Whether in GUI mode.

        Returns:
            Validated list of actions (may be reduced to 1 if non-parallelizable detected).
        """
        if not actions:
            return []

        # Cap at 10 actions
        actions = actions[:10]

        dropped_actions = []

        # Check for non-parallelizable actions by looking up each action's parallelizable attribute
        # If found, we need to keep the non-parallelizable action (not just the first action)
        non_parallel_action = None
        for action_dict in actions:
            action_name = action_dict.get("action_name", "")
            if action_name:
                act = self.action_library.retrieve_action(action_name)
                if act and not getattr(act, "parallelizable", True):
                    non_parallel_action = action_dict
                    break

        if non_parallel_action and len(actions) > 1:
            non_parallel_name = non_parallel_action.get("action_name")
            logger.warning(
                f"[PARALLEL] Non-parallelizable action detected in batch of {len(actions)}. "
                f"Using non-parallelizable action: {non_parallel_name}"
            )
            # Mark other actions as dropped with error
            kept = 0
            for action_dict in actions:
                if action_dict is not non_parallel_action:
                    kept += 1
            for action_dict in actions:
                if action_dict is not non_parallel_action:
                    dropped_action = action_dict.copy()
                    dropped_action["_error"] = (
                        f"Action dropped: '{non_parallel_name}' cannot run in "
                        f"parallel, so it ran ALONE and the other {kept} "
                        "action(s) in this batch did not run. Nothing about "
                        "them failed — re-issue them, ONE non-parallelizable "
                        "action per turn, after re-reading any state the "
                        f"'{non_parallel_name}' call just changed. Do not "
                        "re-send the same multi-action batch: it will be cut "
                        "the same way."
                    )
                    dropped_actions.append(dropped_action)
            actions = [non_parallel_action]

        # Validate each action exists and is visible
        validated = []
        for action in actions:
            action_name = action.get("action_name", "")
            if not action_name:
                continue
            act = self.action_library.retrieve_action(action_name)
            if act and _is_visible_in_mode(act, GUI_mode):
                validated.append(action)
            else:
                # Mark as error instead of silently dropping
                dropped_action = action.copy()
                dropped_action["_error"] = (
                    f"Action '{action_name}' not found or not visible in current mode"
                )
                dropped_actions.append(dropped_action)
                logger.warning(
                    f"[PARALLEL] Action '{action_name}' not found or not visible, marking as error"
                )

        # Append dropped actions with error status so they get logged
        validated.extend(dropped_actions)

        return validated

    def _build_candidates_from_compiled_list(
        self,
        compiled_actions: List[str],
        GUI_mode: bool,
        ignore_actions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Build action candidate list from pre-compiled action names.
        """
        ignore_actions = ignore_actions or []
        candidates = []

        for name in compiled_actions:
            if name in ignore_actions:
                continue

            act = self.action_library.retrieve_action(name)
            if not act:
                continue

            if not _is_visible_in_mode(act, GUI_mode):
                continue

            candidates.append(
                {
                    "name": act.name,
                    "description": act.description,
                    "type": act.action_type,
                    "input_schema": act.input_schema,
                    "output_schema": act.output_schema,
                }
            )

        return candidates

    def _get_session_compiled_actions(
        self, session_id: Optional[str] = None
    ) -> List[str]:
        """
        Get the compiled action list from a session.

        Args:
            session_id: Optional session ID for session-specific state lookup.
        """
        # Try session-specific state first
        state_session = get_session_or_none(session_id)
        if state_session and state_session.current_session:
            session = state_session.current_session
        else:
            # CRITICAL: Log warning when falling back to global state
            # This could indicate a race condition in concurrent execution
            if session_id:
                logger.warning(
                    f"[ACTION_ROUTER] Session not found for session_id={session_id!r}, "
                    f"falling back to global STATE. This may cause context leakage "
                    f"across concurrent sessions!"
                )
            session = get_state().current_session

        if (
            session
            and hasattr(session, "compiled_actions")
            and session.compiled_actions
        ):
            return session.compiled_actions
        return []
