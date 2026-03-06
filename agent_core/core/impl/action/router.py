# -*- coding: utf-8 -*-
"""
ActionRouter for action selection based on user queries and task context.

This module provides the ActionRouter class that selects actions
based on user queries using LLM reasoning.
"""

import json
import ast
from typing import Optional, List, Dict, Any, Tuple

from agent_core.core.state import get_state, get_session_or_none
from agent_core.decorators import profile, OperationCategory
from agent_core.core.protocols.action import ActionLibraryProtocol
from agent_core.core.protocols.context import ContextEngineProtocol
from agent_core.core.protocols.llm import LLMInterfaceProtocol
from agent_core.core.impl.llm import LLMCallType
from agent_core.core.prompts import (
    SELECT_ACTION_PROMPT,
    SELECT_ACTION_IN_TASK_PROMPT,
    SELECT_ACTION_IN_GUI_PROMPT,
    SELECT_ACTION_IN_SIMPLE_TASK_PROMPT,
    GUI_ACTION_SPACE_PROMPT,
)
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
    if mode == 'ALL':
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
    async def select_action(
        self,
        query: str,
        action_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Default action selection function when not in a task.
        Supports parallel action selection - returns a list of actions.
        For now, only choosing between chat, ignore or create and start task.

        Args:
            query: User's request that should be satisfied by an action.
            action_type: Optional type filter forwarded to the LLM.

        Returns:
            List[Dict[str, Any]]: List of decision payloads, each with ``action_name``,
            ``parameters``, and ``reasoning`` for execution.
        """
        # Base conversation mode actions
        base_actions = ["send_message", "task_start", "ignore"]

        # Dynamically add messaging actions for connected platforms
        try:
            from app.external_comms.integration_discovery import (
                get_connected_messaging_platforms,
                get_messaging_actions_for_platforms,
            )
            connected_platforms = get_connected_messaging_platforms()
            messaging_actions = get_messaging_actions_for_platforms(connected_platforms)
            conversation_mode_actions = base_actions + messaging_actions
        except Exception as e:
            logger.debug(f"[ACTION] Could not discover messaging actions: {e}")
            conversation_mode_actions = base_actions

        action_candidates = []

        for action in conversation_mode_actions:
            act = self.action_library.retrieve_action(action_name=action)
            if act:
                action_candidates.append({
                    "name": act.name,
                    "description": act.description,
                    "type": act.action_type,
                    "input_schema": act.input_schema,
                    "output_schema": act.output_schema
                })

        # Build the instruction prompt for the LLM
        prompt = SELECT_ACTION_PROMPT.format(
            event_stream=self.context_engine.get_event_stream(),
            memory_context=self.context_engine.get_memory_context(query),
            query=query,
            action_candidates=self._format_candidates(action_candidates),
        )

        max_retries = 3
        for attempt in range(max_retries):
            decision = await self._prompt_for_decision(prompt, is_task=False)

            # Parse parallel action decisions
            actions = self._parse_parallel_action_decisions(decision)

            if not actions:
                # Empty action list - return empty decision
                return [{"action_name": "", "parameters": {}, "reasoning": decision.get("reasoning", "")}]

            # Validate and filter parallel actions (GUI_mode=False for conversation)
            validated_actions = self._validate_parallel_actions(actions, GUI_mode=False)

            if validated_actions:
                action_names = [a.get("action_name") for a in validated_actions]
                logger.info(f"[PARALLEL] Conversation mode selected {len(validated_actions)} action(s): {action_names}")
                return validated_actions

            logger.warning(
                f"No valid actions found during conversation selection attempt {attempt + 1}"
            )

        raise ValueError("Invalid selected action returned by LLM after retries.")

    @profile("action_router_select_action_in_task", OperationCategory.ACTION_ROUTING)
    async def select_action_in_task(
        self,
        query: str,
        action_type: Optional[str] = None,
        GUI_mode=False,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        When a task is running, this action selection will be used.
        Supports parallel action selection - returns a list of actions.

        Args:
            query: Task-level instruction for the next step.
            action_type: Optional action type hint supplied to the LLM.
            GUI_mode: Whether the user is interacting through a GUI.
            session_id: Optional session ID for session-specific state lookup.

        Returns:
            List[Dict[str, Any]]: List of decision payloads, each with ``action_name``,
            ``parameters``, and ``reasoning`` for execution.
        """
        action_candidates = []

        # List of filtered actions
        ignore_actions = ["ignore", "task_start"]

        # Get compiled action list from task's action sets
        compiled_actions = self._get_current_task_compiled_actions(session_id=session_id)

        # Use static compiled list - NO RAG SEARCH
        action_candidates = self._build_candidates_from_compiled_list(
            compiled_actions, GUI_mode, ignore_actions
        )
        logger.info(f"ActionRouter using compiled action list: {len(action_candidates)} actions")

        # Build the instruction prompt for the LLM
        task_state = self.context_engine.get_task_state(session_id=session_id)
        memory_context = self.context_engine.get_memory_context(query, session_id=session_id)
        static_prompt = SELECT_ACTION_IN_TASK_PROMPT.format(
            agent_state=self.context_engine.get_agent_state(session_id=session_id),
            task_state=task_state,
            memory_context=memory_context,
            event_stream="",  # Empty for static prompt
            query=query,
            action_candidates=self._format_candidates(action_candidates),
        )
        full_prompt = SELECT_ACTION_IN_TASK_PROMPT.format(
            agent_state=self.context_engine.get_agent_state(session_id=session_id),
            task_state=task_state,
            memory_context=memory_context,
            event_stream=self.context_engine.get_event_stream(session_id=session_id),
            query=query,
            action_candidates=self._format_candidates(action_candidates),
        )

        max_retries = 3
        for attempt in range(max_retries):
            decision = await self._prompt_for_decision(
                full_prompt,
                is_task=True,
                static_prompt=static_prompt,
                call_type=LLMCallType.ACTION_SELECTION,
                session_id=session_id,
            )

            # Parse parallel action decisions (handles both old and new format)
            actions = self._parse_parallel_action_decisions(decision)

            if not actions:
                # Empty action list - return empty decision for backward compatibility
                return [{"action_name": "", "parameters": {}, "reasoning": decision.get("reasoning", "")}]

            # Validate and filter parallel actions
            validated_actions = self._validate_parallel_actions(actions, GUI_mode)

            if validated_actions:
                action_names = [a.get("action_name") for a in validated_actions]
                logger.info(f"[PARALLEL] Selected {len(validated_actions)} action(s): {action_names}")
                return validated_actions

            logger.warning(
                f"No valid actions found during selection attempt {attempt + 1}"
            )

        raise ValueError("Invalid selected action returned by LLM after retries.")

    @profile("action_router_select_action_in_simple_task", OperationCategory.ACTION_ROUTING)
    async def select_action_in_simple_task(
        self,
        query: str,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Action selection for simple task mode - streamlined without todo workflow.
        Supports parallel action selection - returns a list of actions.

        Args:
            query: Task-level instruction for the next step.
            session_id: Optional session ID for session-specific state lookup.

        Returns:
            List[Dict[str, Any]]: List of decision payloads, each with ``action_name``,
            ``parameters``, and ``reasoning`` for execution.
        """
        action_candidates = []

        # Exclude todo management, ignore, and task_start for simple tasks
        ignore_actions = ["ignore", "task_update_todos", "task_start"]

        # Get compiled action list from task's action sets
        compiled_actions = self._get_current_task_compiled_actions(session_id=session_id)

        # Use static compiled list - NO RAG SEARCH
        action_candidates = self._build_candidates_from_compiled_list(
            compiled_actions, GUI_mode=False, ignore_actions=ignore_actions
        )
        logger.info(f"ActionRouter (simple task) using compiled action list: {len(action_candidates)} actions")

        # Build the instruction prompt
        task_state = self.context_engine.get_task_state(session_id=session_id)
        memory_context = self.context_engine.get_memory_context(query, session_id=session_id)
        static_prompt = SELECT_ACTION_IN_SIMPLE_TASK_PROMPT.format(
            agent_state=self.context_engine.get_agent_state(session_id=session_id),
            task_state=task_state,
            memory_context=memory_context,
            event_stream="",  # Empty for static prompt
            query=query,
            action_candidates=self._format_candidates(action_candidates),
        )
        full_prompt = SELECT_ACTION_IN_SIMPLE_TASK_PROMPT.format(
            agent_state=self.context_engine.get_agent_state(session_id=session_id),
            task_state=task_state,
            memory_context=memory_context,
            event_stream=self.context_engine.get_event_stream(session_id=session_id),
            query=query,
            action_candidates=self._format_candidates(action_candidates),
        )

        max_retries = 3
        for attempt in range(max_retries):
            decision = await self._prompt_for_decision(
                full_prompt,
                is_task=True,
                static_prompt=static_prompt,
                call_type=LLMCallType.ACTION_SELECTION,
                session_id=session_id,
            )

            # Parse parallel action decisions (handles both old and new format)
            actions = self._parse_parallel_action_decisions(decision)

            if not actions:
                # Empty action list - return empty decision for backward compatibility
                return [{"action_name": "", "parameters": {}, "reasoning": decision.get("reasoning", "")}]

            # Validate and filter parallel actions
            validated_actions = self._validate_parallel_actions(actions, GUI_mode=False)

            if validated_actions:
                action_names = [a.get("action_name") for a in validated_actions]
                logger.info(f"[PARALLEL] Simple task selected {len(validated_actions)} action(s): {action_names}")
                return validated_actions

            logger.warning(
                f"No valid actions found during simple task selection attempt {attempt + 1}"
            )

        raise ValueError("Invalid selected action returned by LLM after retries.")

    @profile("action_router_select_action_in_GUI", OperationCategory.ACTION_ROUTING)
    async def select_action_in_GUI(
        self,
        query: str,
        action_type: Optional[str] = None,
        GUI_mode=False,
        reasoning: str = "",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        GUI-specific action selection when a task is running.

        Args:
            query: Task-level instruction for the next step.
            action_type: Optional action type hint supplied to the LLM.
            GUI_mode: Whether the user is interacting through a GUI.
            reasoning: Pre-computed reasoning from VLM/OmniParser about screen state.
            session_id: Optional session ID for session-specific state lookup.

        Returns:
            Dict[str, Any]: Decision payload with ``action_name``, ``parameters``,
            and ``element_to_find`` for execution.
        """
        compiled_actions = self._get_current_task_compiled_actions(session_id=session_id)
        logger.info(f"ActionRouter (GUI) using compact action space prompt with {len(compiled_actions)} actions")

        # Build the instruction prompt for the LLM
        task_state = self.context_engine.get_task_state(session_id=session_id)
        memory_context = self.context_engine.get_memory_context(query, session_id=session_id)
        static_prompt = SELECT_ACTION_IN_GUI_PROMPT.format(
            agent_state=self.context_engine.get_agent_state(session_id=session_id),
            task_state=task_state,
            event_stream="",  # Empty for static prompt
            memory_context=memory_context,
            gui_action_space=GUI_ACTION_SPACE_PROMPT,
        )
        full_prompt = SELECT_ACTION_IN_GUI_PROMPT.format(
            agent_state=self.context_engine.get_agent_state(session_id=session_id),
            task_state=task_state,
            event_stream=self.context_engine.get_event_stream(session_id=session_id),
            memory_context=memory_context,
            gui_action_space=GUI_ACTION_SPACE_PROMPT,
        )

        max_retries = 3
        for attempt in range(max_retries):
            decision = await self._prompt_for_decision(
                full_prompt,
                is_task=True,
                static_prompt=static_prompt,
                call_type=LLMCallType.GUI_ACTION_SELECTION,
                session_id=session_id,
            )

            selected_action_name = decision.get("action_name", "")
            if selected_action_name == "":
                return decision

            selected_action = self.action_library.retrieve_action(selected_action_name)
            if selected_action is not None and _is_visible_in_mode(selected_action, GUI_mode):
                decision["parameters"] = self._ensure_parameters(decision.get("parameters"))
                return decision

            logger.warning(
                f"Received invalid action name '{selected_action_name}' during selection attempt {attempt + 1}"
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
    ) -> Dict[str, Any]:
        """
        Prompt the LLM for an action decision with session caching support.

        Args:
            prompt: The full prompt to send to the LLM.
            is_task: Whether this is a task-related call.
            static_prompt: Optional static portion for caching.
            call_type: Type of LLM call for cache keying.
            session_id: Optional session ID for session-specific state lookup.
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
                system_flags={"agent_info": True, "policy": False},
            )

            raw_response = None

            # Use session cache if we're in a task context AND session is registered
            if current_task_id and is_task:
                has_session = self.llm_interface.has_session_cache(current_task_id, call_type)

                if has_session:
                    # Session is registered (complex task) - use session caching
                    # CRITICAL: Use session-specific stream to prevent event leakage
                    from agent_core import get_event_stream_manager
                    event_stream_manager = get_event_stream_manager()
                    # Use get_stream_by_id with session_id to get the correct task's stream
                    effective_session_id = session_id or current_task_id
                    stream = event_stream_manager.get_stream_by_id(effective_session_id) if event_stream_manager else None
                    has_synced_before = stream.has_session_sync(call_type) if stream else False

                    if has_synced_before:
                        # We've made calls before - send only delta events
                        # CRITICAL: Pass session_id to get delta from the correct stream
                        delta_events, has_delta = self.context_engine.get_event_stream_delta(call_type, session_id=effective_session_id)

                        if has_delta:
                            # Send only the new events
                            logger.info(f"[SESSION CACHE] Sending delta events for {call_type}")
                            raw_response = await self.llm_interface.generate_response_with_session_async(
                                task_id=current_task_id,
                                call_type=call_type,
                                user_prompt=delta_events,
                                system_prompt_for_new_session=system_prompt,
                            )
                            # Mark events as synced after successful call
                            self.context_engine.mark_event_stream_synced(call_type, session_id=effective_session_id)
                        else:
                            # No new events - this could mean summarization happened
                            logger.info(f"[SESSION CACHE] No delta events, resetting cache for {call_type}")
                            self.llm_interface.end_session_cache(current_task_id, call_type)
                            self.context_engine.reset_event_stream_sync(call_type, session_id=effective_session_id)
                            # Fall through to first-call path
                            has_synced_before = False

                    if not has_synced_before:
                        # First call with session - send full prompt to establish session
                        logger.info(f"[SESSION CACHE] Creating new session for {call_type} (first call)")
                        raw_response = await self.llm_interface.generate_response_with_session_async(
                            task_id=current_task_id,
                            call_type=call_type,
                            user_prompt=current_prompt,
                            system_prompt_for_new_session=system_prompt,
                        )
                        # Mark events as synced after successful session creation
                        self.context_engine.mark_event_stream_synced(call_type, session_id=effective_session_id)
                else:
                    # No session registered (simple task) - use prefix cache / regular response
                    raw_response = await self.llm_interface.generate_response_async(system_prompt, current_prompt)
            else:
                # Not in task context - use regular response
                raw_response = await self.llm_interface.generate_response_async(system_prompt, current_prompt)

            decision, parse_error = self._parse_action_decision(raw_response)
            if decision is not None:
                decision.setdefault("parameters", {})
                decision["parameters"] = self._ensure_parameters(decision.get("parameters"))
                return decision

            feedback_error = parse_error or "unknown parsing error"
            last_error = ValueError(f"Unable to parse action decision on attempt {attempt + 1}: {feedback_error}")
            logger.warning(
                f"Failed to parse LLM decision on attempt {attempt + 1}: "
                f"{raw_response} | error={feedback_error}"
            )
            current_prompt = self._augment_prompt_with_feedback(prompt, attempt + 1, raw_response, feedback_error)

        if last_error:
            raise last_error
        raise ValueError("Unable to parse LLM decision")

    def _parse_action_decision(self, raw: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as json_error:
            try:
                parsed = ast.literal_eval(raw)
            except Exception as eval_error:
                logger.error(f"Unable to parse action decision: {raw}")
                return None, f"json error: {json_error}; literal_eval error: {eval_error}"

        if not isinstance(parsed, dict):
            logger.error(f"Parsed action decision is not a dict: {raw}")
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

    def _format_candidates(self, candidates: List[Dict[str, Any]]) -> str:
        """Format action candidates with compact schema for reduced prompt size."""
        if not candidates:
            return "[]"

        compact: List[Dict[str, Any]] = []
        for c in candidates:
            input_schema = c.get("input_schema") or {}
            params = {}

            for param_name, param_def in input_schema.items():
                if isinstance(param_def, dict):
                    ptype = param_def.get("type", "any")
                    desc = param_def.get("description", "")
                    is_optional = "default" in desc.lower() or "optional" in desc.lower()
                    req = "optional" if is_optional else "required"
                    params[param_name] = f"{ptype}, {req} - {desc}"
                else:
                    params[param_name] = str(param_def)

            entry = {
                "name": c.get("name"),
                "description": c.get("description", ""),
                "params": params
            }
            compact.append(entry)

        return json.dumps(compact, indent=2, ensure_ascii=False)

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

    def _parse_parallel_action_decisions(self, decision: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse LLM response for parallel action format.

        Expected format: {"reasoning": "...", "actions": [{...}, {...}]}

        Returns:
            List of action decisions, each with action_name, parameters, and reasoning.
        """
        if decision is None:
            return []

        reasoning = decision.get("reasoning", "")

        # Parse "actions" array format
        if "actions" in decision and isinstance(decision["actions"], list):
            actions = []
            for action in decision["actions"]:
                if isinstance(action, dict) and action.get("action_name"):
                    action["reasoning"] = reasoning
                    action["parameters"] = self._ensure_parameters(action.get("parameters"))
                    actions.append(action)
            return actions

        return []

    def _validate_parallel_actions(
        self,
        actions: List[Dict[str, Any]],
        GUI_mode: bool
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

        # Check for non-parallelizable actions by looking up each action's parallelizable attribute
        has_non_parallel = False
        for action_dict in actions:
            action_name = action_dict.get("action_name", "")
            if action_name:
                act = self.action_library.retrieve_action(action_name)
                if act and not getattr(act, "parallelizable", True):
                    has_non_parallel = True
                    break

        if has_non_parallel and len(actions) > 1:
            logger.warning(
                f"[PARALLEL] Non-parallelizable action detected in batch of {len(actions)}. "
                f"Using only first action: {actions[0].get('action_name')}"
            )
            actions = [actions[0]]

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
                logger.warning(f"[PARALLEL] Action '{action_name}' not found or not visible, skipping")

        return validated

    def _build_candidates_from_compiled_list(
        self,
        compiled_actions: List[str],
        GUI_mode: bool,
        ignore_actions: Optional[List[str]] = None
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

            candidates.append({
                "name": act.name,
                "description": act.description,
                "type": act.action_type,
                "input_schema": act.input_schema,
                "output_schema": act.output_schema
            })

        return candidates

    def _get_current_task_compiled_actions(self, session_id: Optional[str] = None) -> List[str]:
        """
        Get the compiled action list from the current task.

        Args:
            session_id: Optional session ID for session-specific state lookup.
        """
        # Try session-specific state first
        session = get_session_or_none(session_id)
        if session and session.current_task:
            task = session.current_task
        else:
            # CRITICAL: Log warning when falling back to global state
            # This could indicate a race condition in concurrent task execution
            if session_id:
                logger.warning(f"[ACTION_ROUTER] Session not found for session_id={session_id!r}, "
                             f"falling back to global STATE. This may cause context leakage in concurrent tasks!")
            task = get_state().current_task

        if task and hasattr(task, 'compiled_actions') and task.compiled_actions:
            return task.compiled_actions
        return []
