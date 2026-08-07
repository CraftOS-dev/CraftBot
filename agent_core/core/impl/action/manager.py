# -*- coding: utf-8 -*-
"""
ActionManager for executing actions with full lifecycle management.

This module provides the ActionManager class that handles both atomic and
hierarchical action execution, with optional hooks for external integrations
like chatserver reporting.
"""

from datetime import datetime
import platform
import time
import json
import asyncio
import nest_asyncio
from typing import Optional, List, Dict, Any, Callable, Tuple
import io
import sys
import re
import uuid

from agent_core.core.action import Action
from agent_core.core.state import get_state_or_none
from agent_core.decorators import profile, OperationCategory
from agent_core.core.protocols.action import ActionLibraryProtocol
from agent_core.core.protocols.database import DatabaseInterfaceProtocol
from agent_core.core.protocols.event_stream import EventStreamManagerProtocol
from agent_core.core.protocols.context import ContextEngineProtocol
from agent_core.core.protocols.state import StateManagerProtocol
from agent_core.core.impl.action.executor import ActionExecutor
from agent_core.core.impl.action.idempotency import IdempotencyGuard
from agent_core.core.event_stream.event import EventType
from agent_core.utils.logger import logger

# ============================================================================
# Python 3.14 + nest_asyncio 1.6.0 compatibility shim for asyncio.wait_for.
# On 3.11+, asyncio.wait_for uses `async with asyncio.timeout(...)`, which
# calls asyncio.current_task() in __aenter__. nest_asyncio.apply() (below)
# patches the event loop's _run_once but does not propagate the task context
# variable when re-entering the loop, so current_task() returns None and
# wait_for raises "RuntimeError: Timeout should be used inside a task".
# Replace wait_for with an asyncio.wait-based equivalent that doesn't depend
# on current_task(). Installed just before nest_asyncio.apply() so every
# subsequent asyncio.wait_for caller (MCP stdio, action executor, etc.) picks
# it up. Safe to remove once nest_asyncio ships a 3.14-compatible release.
try:
    import sys as _compat_sys

    if _compat_sys.version_info >= (3, 11):
        import asyncio.tasks as _compat_asyncio_tasks

        async def _compat_wait_for(fut, timeout):
            if timeout is None:
                return await fut
            task = asyncio.ensure_future(fut)
            try:
                _done, pending = await asyncio.wait({task}, timeout=timeout)
            except asyncio.CancelledError:
                # Real wait_for GUARANTEES the wrapped future is cancelled
                # when the outer await is cancelled; asyncio.wait does NOT
                # cancel its input tasks, so without this branch a user
                # force-stop unwound the turn while the executing ACTION
                # kept running as an orphaned task — its message/file output
                # landed seconds after "Run stopped." (PR #410). Cancel the
                # inner task and AWAIT its unwind before re-raising: that
                # wait is what keeps the stop spinner honest — an action
                # whose sync body is mid-flight in a worker thread only
                # unwinds when the thread finishes, so settlement (and the
                # "Run stopped." bubble) waits for the last real work.
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
                raise
            if task in pending:
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
                raise asyncio.TimeoutError()
            return task.result()

        asyncio.wait_for = _compat_wait_for
        _compat_asyncio_tasks.wait_for = _compat_wait_for
        try:
            _compat_sys.stderr.write(
                "[compat-shim] asyncio.wait_for replaced (action/manager)\n"
            )
            _compat_sys.stderr.flush()
        except Exception:
            pass
except Exception as _compat_exc:
    logger.warning(
        f"[compat-shim] failed to install asyncio.wait_for replacement: {_compat_exc!r}"
    )
# ============================================================================

nest_asyncio.apply()


def _to_pretty_json(value: Any) -> str:
    """Serialize a value to pretty-printed JSON for readable logs and event streams."""
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


# Type aliases for hooks
OnActionStartHook = Callable[
    [str, Any, Dict, str, str], Any
]  # (run_id, action, inputs, parent_id, started_at) -> awaitable
OnActionEndHook = Callable[
    [str, Any, Dict, str, str, str], Any
]  # (run_id, action, outputs, status, parent_id, ended_at) -> awaitable
GetParentIdHook = Callable[[], Optional[str]]  # () -> parent_id or None


class ActionManager:
    """
    Executes actions, handling both atomic and hierarchical tasks.
    Persists every run into *action_history* (one document per run).

    Supports optional hooks for external integrations:
    - on_action_start: Called when an action starts (e.g., POST to chatserver)
    - on_action_end: Called when an action ends (e.g., PUT to chatserver)
    - get_parent_id: Called to resolve parent_id from current task context
    """

    def __init__(
        self,
        action_library: ActionLibraryProtocol,
        llm_interface,
        db_interface: DatabaseInterfaceProtocol,
        event_stream_manager: EventStreamManagerProtocol,
        context_engine: ContextEngineProtocol,
        state_manager: StateManagerProtocol,
        *,
        on_action_start: Optional[OnActionStartHook] = None,
        on_action_end: Optional[OnActionEndHook] = None,
        get_parent_id: Optional[GetParentIdHook] = None,
        idempotency_guard: Optional["IdempotencyGuard"] = None,
    ):
        """
        Build an ActionManager that can execute and track actions.

        Args:
            action_library: Source of action definitions and metadata.
            llm_interface: LLM client used for input resolution and routing.
            db_interface: Persistence layer for action history records.
            event_stream_manager: Publisher for execution events.
            context_engine: Provider for system prompts.
            state_manager: State controller for task progress updates.
            on_action_start: Optional hook called when action starts.
            on_action_end: Optional hook called when action ends.
            get_parent_id: Optional hook to resolve parent_id from task context.
            idempotency_guard: Optional guard consulted before/after actions
                flagged ``irreversible=True``: records intent
                before the side effect and prevents a completed run from
                being silently re-executed after a crash.
        """
        self.action_library = action_library
        self.llm_interface = llm_interface
        self.db_interface = db_interface
        self.event_stream_manager = event_stream_manager
        self.context_engine = context_engine
        self.state_manager = state_manager
        self.executor = ActionExecutor()

        # Track in-flight actions
        self._inflight: Dict[str, Dict] = {}

        # Optional hooks for external integrations
        self._on_action_start = on_action_start
        self._on_action_end = on_action_end
        self._get_parent_id = get_parent_id
        self._idempotency_guard = idempotency_guard

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @profile("action_manager_execute_action", OperationCategory.ACTION_EXECUTION)
    async def execute_action(
        self,
        action: Action,
        context: str,
        event_stream: str,
        parent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        is_running_task: bool = False,
        is_gui_task: bool = False,
        *,
        input_data: Optional[Dict] = None,
    ) -> Dict:
        """
        Execute an action and persist the full run lifecycle.

        Args:
            action: Action definition to run.
            context: Textual context for the current conversation or task.
            event_stream: Serialized event stream for the prompt.
            parent_id: Optional run identifier when executing as a sub-action.
            session_id: Session identifier for logging.
            is_running_task: Whether part of an active task workflow.
            is_gui_task: Whether this is a GUI task.
            input_data: Pre-resolved action inputs.

        Returns:
            dict: Final output payload of the action execution.
        """
        # ───────────────────────────────────────────────────────────────
        # 1. Resolve inputs and setup
        # ───────────────────────────────────────────────────────────────

        current_platform = platform.system().lower()
        platform_code = action.platform_overrides.get(current_platform, {}).get(
            "code", action.code
        )
        action.code = platform_code

        if not isinstance(input_data, dict):
            logger.error(f"Provided action input is not a dict. action={action.name}")

        # Inject session_id into input_data so actions can access it
        # (used for per-session stream isolation and outbound routing)
        if input_data is None:
            input_data = {}
        if session_id:
            input_data["_session_id"] = session_id

        logger.debug(f"[INPUT DATA] {input_data}")

        # Generate the run_id up front so it is available to every
        # event-stream log call for this execution — including the
        # idempotency-skipped path below, which emits action_end without
        # any matching action_start. Sharing the same run_id across all
        # events of one execution is how the UI pairs start/end correctly
        # when multiple parallel calls of the same action fire within the
        # same wall-clock second.
        run_id = str(uuid.uuid4())

        # ── Idempotency guard for irreversible actions ──
        # BEFORE the side effect: record intent durably, and refuse to
        # re-execute work the ledger shows as already completed (or as
        # interrupted mid-flight, where the effect may have happened).
        idem_key = None
        # if getattr(action, "irreversible", False) and self._idempotency_guard:

        # TODO: Temporary turning idempotency guard off.
        if 1 == 0:
            try:
                decision = self._idempotency_guard.begin(
                    action.name, input_data, session_id
                )
            except Exception as exc:
                logger.warning(f"Idempotency guard begin() failed: {exc}")
                decision = None
            if decision is not None:
                idem_key = decision.idem_key
                if not decision.proceed:
                    if decision.stored_output is not None:
                        skip_outputs = decision.stored_output
                        skip_message = (
                            f"Action {action.name} skipped — an identical run "
                            f"already completed; returning its stored output."
                        )
                    else:
                        skip_outputs = {
                            "status": "error",
                            "error": decision.note,
                            "error_code": "irreversible_uncertain",
                        }
                        skip_message = (
                            f"Action {action.name} blocked — a previous "
                            f"attempt was interrupted and its side effect may "
                            f"already have happened. See the action output."
                        )
                    self._log_event_stream(
                        is_gui_task=is_gui_task,
                        event_kind="action_end",
                        event_type=EventType.ACTION_END,
                        event=skip_message,
                        display_message=f"{action.display_name} → skipped (idempotent)",
                        action_name=action.name,
                        action_display_name=action.display_name,
                        action_id=run_id,
                        action_output=skip_outputs,
                        session_id=session_id,
                    )
                    return skip_outputs

        started_at = datetime.utcnow().isoformat()

        # Resolve parent_id using hook if available
        if not parent_id and self._get_parent_id:
            parent_id = self._get_parent_id()

        # Call on_action_start hook if provided
        if self._on_action_start:
            try:
                result = self._on_action_start(
                    run_id, action, input_data, parent_id, started_at
                )
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning(f"on_action_start hook failed: {exc}")

        logger.debug(f"Executing action {action.name} (run_id={run_id})...")

        # Track in-flight
        self._inflight[run_id] = {
            "action": action,
            "inputs": input_data,
            "parent_id": parent_id,
            "session_id": session_id,
            "started_at": started_at,
        }

        logger.info(f"Action {action.name} marked as in-flight.")

        # Log to event stream
        # Only pass session_id when is_running_task=True (task stream exists)
        # When no task exists, use global stream by not passing task_id
        pretty_input = _to_pretty_json(input_data)
        self._log_event_stream(
            is_gui_task=is_gui_task,
            event_kind="action_start",
            event_type=EventType.ACTION_START,
            event=f"Running action {action.name} with input: {pretty_input}.",
            display_message=f"Running {action.display_name}",
            action_name=action.name,
            action_display_name=action.display_name,
            action_id=run_id,
            action_input=input_data,
            # Always pass session_id when present so the event_stream_manager can route
            # to the correct task stream OR fall back to main_stream for transient
            # sessions (e.g. third-party email notification). Previously this gated on
            # is_running_task, which meant conversation-mode actions logged with
            # task_id=None and got attributed to whatever task_stream get_stream()
            # returned via STATE.current_task_id — leaking events into unrelated tasks.
            session_id=session_id,
        )

        logger.debug(f"Starting execution of action {action.name}...")

        was_cancelled = False
        try:
            # ────────────────────────────────────────────────────────────
            # 2. Execute
            # ────────────────────────────────────────────────────────────

            status = ""
            outputs = {}

            logger.debug(f"Action type: {action.action_type}")

            if action.action_type == "atomic":
                try:
                    outputs = await self.execute_atomic_action(action, input_data)
                except Exception as e:
                    logger.error(
                        f"[ERROR] Failed to execute atomic action {action.name}: {e}",
                        exc_info=True,
                    )
                    raise e

                logger.debug(
                    f"[OUTPUT DATA] Completed execute_atomic_action: {outputs}"
                )

                # Observation step
                if action.observer:
                    obs_result = await self.run_observe_step(action, outputs)
                    if not obs_result["success"]:
                        status = "error"
                        outputs["observation"] = {
                            "success": False,
                            "message": obs_result.get("message"),
                        }
                    else:
                        outputs["observation"] = {
                            "success": True,
                            "message": obs_result.get("message"),
                        }

            else:
                logger.debug(f"Executing divisible action: {action.name}")
                try:
                    outputs = await self.execute_divisible_action(
                        action, input_data, run_id
                    )
                except Exception as e:
                    logger.error(
                        f"[ERROR] Failed to execute divisible action {action.name}: {e}",
                        exc_info=True,
                    )
                    raise e

            # Auto-save large base64 strings in action output to temp files
            # This prevents LLMs from truncating binary data when it appears in context
            outputs = self._extract_base64_to_files(outputs, action.name)

            logger.debug(
                f"[OUTPUT DATA] Final outputs for action {action.name}: {outputs}"
            )

            if status != "error":
                # If the action returned an error dict (either via exception path in
                # execute_atomic_action or an explicit failure from the action body),
                # treat the run as an error so on_action_end and runtime logs reflect it.
                if outputs and outputs.get("status") == "error":
                    status = "error"
                else:
                    status = "success"

        except asyncio.CancelledError:
            # A user force-stop cancelled the turn mid-action. Record the
            # outcome (the event stream and idempotency ledger must show the
            # action was cancelled), but DO NOT swallow the cancellation:
            # catching CancelledError without re-raising un-cancels the task,
            # and the react loop then treated "Action cancelled" as an
            # ordinary failed action and started the NEXT LLM call — a zombie
            # turn the stop's settlement wait could never catch, surfacing as
            # "Stop settlement timed out" + forceful finalize (observed live
            # 2026-08-07, PR #410). The re-raise happens AFTER persistence,
            # at the end of this method.
            status = "error"
            outputs = {"error": "Action cancelled", "error_code": "cancelled"}
            was_cancelled = True
        except Exception as e:
            status = "error"
            outputs = {"error": str(e)}
            logger.exception(f"[ERROR] Exception while executing action {action.name}")

        ended_at = datetime.utcnow().isoformat()

        # ── Idempotency guard: record the outcome durably ──
        # AFTER the side effect, BEFORE anything that could fail below — a
        # crash between the side effect and this line is the §4.2 window the
        # ledger exists to shrink.
        if idem_key and self._idempotency_guard:
            try:
                self._idempotency_guard.complete(idem_key, status, outputs)
            except Exception as exc:
                logger.warning(f"Idempotency guard complete() failed: {exc}")

        # Re-resolve parent_id after execution if hook provided
        if not parent_id and self._get_parent_id:
            parent_id = self._get_parent_id()

        # ────────────────────────────────────────────────────────────────
        # 3. Persist final state
        # ────────────────────────────────────────────────────────────────

        logger.info(f"Action {action.name} completed with status: {status}.")

        # Log to event stream
        # Only pass session_id when is_running_task=True (task stream exists)
        output_has_error = outputs and outputs.get("status") == "error"
        display_status = (
            "failed" if (status == "error" or output_has_error) else "completed"
        )
        pretty_output = _to_pretty_json(outputs)
        self._log_event_stream(
            is_gui_task=is_gui_task,
            event_kind="action_end",
            event_type=EventType.ACTION_END,
            event=f"Action {action.name} completed with output: {pretty_output}.",
            display_message=f"{action.display_name} → {display_status}",
            action_name=action.name,
            action_display_name=action.display_name,
            action_id=run_id,
            action_output=outputs,
            # Always pass session_id when present so the event_stream_manager can route
            # to the correct task stream OR fall back to main_stream for transient
            # sessions (e.g. third-party email notification). Previously this gated on
            # is_running_task, which meant conversation-mode actions logged with
            # task_id=None and got attributed to whatever task_stream get_stream()
            # returned via STATE.current_task_id — leaking events into unrelated tasks.
            session_id=session_id,
        )

        # Emit waiting_for_user event when the action ends the run and the
        # session goes back to waiting for the user's next input.
        if outputs and outputs.get("end_turn", False):
            self._log_event_stream(
                is_gui_task=is_gui_task,
                event_kind="waiting_for_user",
                event_type=EventType.WAITING_FOR_USER,
                event="Agent is waiting for user response.",
                display_message=None,
                action_name=action.name,
                action_id=run_id,
                session_id=session_id,
            )

        logger.debug(f"Persisting final state for action {action.name}...")

        # Update action count on the per-task StateSession (per-task counter).
        # Falls back to the global state provider when no session is registered
        # (e.g. transient/conversation-mode actions before any task is created).
        from agent_core.core.state.session import StateSession

        session = StateSession.get_or_none(session_id) if session_id else None
        if session is not None:
            session.agent_properties.set_property(
                "action_count",
                session.agent_properties.get_property("action_count", 0) + 1,
            )
        else:
            state = get_state_or_none()
            if state:
                state.set_agent_property(
                    "action_count", state.get_agent_property("action_count", 0) + 1
                )

        # Call on_action_end hook if provided
        if self._on_action_end:
            try:
                result = self._on_action_end(
                    run_id, action, outputs, status, parent_id, ended_at
                )
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning(f"on_action_end hook failed: {exc}")

        logger.debug(f"Final state for action {action.name} persisted.")
        self._inflight.pop(run_id, None)

        logger.debug(f"Action {action.name} removed from in-flight tracking.")

        if was_cancelled:
            # Bookkeeping is done (event stream + ledger show the cancelled
            # outcome); now let the stop actually stop the turn.
            raise asyncio.CancelledError()

        return outputs

    @profile(
        "action_manager_execute_actions_parallel", OperationCategory.ACTION_EXECUTION
    )
    async def execute_actions_parallel(
        self,
        actions: List[Tuple[Action, Dict]],
        context: str,
        event_stream: str,
        parent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        is_running_task: bool = False,
        is_gui_task: bool = False,
    ) -> List[Dict]:
        """
        Execute multiple actions in parallel using asyncio.gather.

        Each action logs its own results to the event stream via execute_action().

        Args:
            actions: List of (Action, input_data) tuples to execute.
            context: Textual context for the current conversation or task.
            event_stream: Serialized event stream for the prompt.
            parent_id: Optional run identifier when executing as a sub-action.
            session_id: Session identifier for logging.
            is_running_task: Whether part of an active task workflow.
            is_gui_task: Whether this is a GUI task.

        Returns:
            List[Dict]: List of output payloads from each action execution.
        """
        if not actions:
            return []

        if len(actions) == 1:
            # Single action - use existing method
            action, input_data = actions[0]
            result = await self.execute_action(
                action=action,
                context=context,
                event_stream=event_stream,
                parent_id=parent_id,
                session_id=session_id,
                is_running_task=is_running_task,
                is_gui_task=is_gui_task,
                input_data=input_data,
            )
            return [result]

        # Log parallel execution start (internal logging only, no display message)
        action_names = [a[0].name for a in actions]
        logger.info(
            f"[PARALLEL] Executing {len(actions)} actions in parallel: {action_names}"
        )

        # Create coroutines for parallel execution
        async def execute_single(
            action: Action, input_data: Dict, action_session_id: str
        ) -> Dict:
            return await self.execute_action(
                action=action,
                context=context,
                event_stream=event_stream,
                parent_id=parent_id,
                session_id=action_session_id,
                is_running_task=is_running_task,
                is_gui_task=is_gui_task,
                input_data=input_data,
            )

        # All parallel actions run under the parent session_id. Real tasks
        # (not bare coroutines) so a cancelled batch can be awaited below.
        parallel_tasks = [
            asyncio.ensure_future(execute_single(action, input_data, session_id))
            for action, input_data in actions
        ]

        # Execute all actions in parallel
        try:
            results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
        except asyncio.CancelledError:
            # User force-stop: gather cancels the children but raises without
            # waiting for their unwind — which includes each action's
            # cancelled-outcome bookkeeping and the wait for uninterruptible
            # thread bodies. Settling here keeps the stop contract (spinner
            # until the last in-flight action finalizes) for parallel batches
            # exactly as execute_action keeps it for single ones (PR #410).
            await asyncio.wait(parallel_tasks)
            raise

        # Process results, converting exceptions to error dicts.
        # BaseException, not Exception: a child's CancelledError would
        # otherwise pass isinstance() and leak an exception OBJECT into the
        # results list, crashing the status tally below.
        processed = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.error(f"[PARALLEL] Action {actions[i][0].name} failed: {result}")
                processed.append(
                    {
                        "status": "error",
                        "error": str(result),
                        "action_name": actions[i][0].name,
                    }
                )
            else:
                processed.append(result)

        # Log completion (internal logging only, no display message)
        success_count = sum(1 for r in processed if r.get("status") != "error")
        logger.info(
            f"[PARALLEL] Execution complete: {success_count}/{len(actions)} succeeded"
        )

        return processed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _log_event_stream(
        self,
        is_gui_task: bool,
        event_kind: str,
        event_type: EventType,
        event: str,
        display_message: Optional[str],
        action_name: str,
        session_id: Optional[str] = None,
        action_display_name: Optional[str] = None,
        action_id: Optional[str] = None,
        action_input: Optional[Dict] = None,
        action_output: Optional[Dict] = None,
    ) -> None:
        """Log action events to the unified event stream.

        Args:
            is_gui_task: Whether this is a GUI task (affects event kind labeling)
            event_kind: Free-text label used in the prompt-facing snapshot
                (e.g., ``"action_start"`` / ``"GUI action start"``).
            event_type: Closed-set category for UI routing.
            event: Full event message
            display_message: Short display message for UI
            action_name: Name of the action
            session_id: Task/session ID to ensure event goes to correct stream.
                       CRITICAL for concurrent task execution - without this,
                       events may go to the wrong task's stream.
            action_id: Stable identifier paired across an action's
                start and end events. Generated by ``ActionManager`` (as
                ``run_id`` locally) so the UI can pair start↔end across
                parallel calls of the same action.
            action_input: Structured input dict for action_start events.
            action_output: Structured output dict for action_end events.
        """
        if not self.event_stream_manager:
            logger.warning(
                f"No event stream manager to log to for event kind: {event_kind}"
            )
            return

        if is_gui_task:
            gui_event_labels = {
                "action_start": "GUI action start",
                "action_end": "GUI action end",
            }
            kind = gui_event_labels.get(event_kind, f"GUI {event_kind}")
        else:
            kind = event_kind

        self.event_stream_manager.log(
            kind,
            event,
            event_type=event_type,
            display_message=display_message,
            action_name=action_name,
            action_display_name=action_display_name,
            action_id=action_id,
            action_input=action_input,
            action_output=action_output,
            task_id=session_id,
        )

    # ------------------------------------------------------------------
    # Action execution primitives
    # ------------------------------------------------------------------

    @profile("action_manager_execute_atomic_action", OperationCategory.ACTION_EXECUTION)
    async def execute_atomic_action(self, action: Action, input_data: Dict) -> Dict:
        try:
            output = await self.executor.execute_action(action, input_data)

            logger.debug(f"The action output is:\n{output}")

            if "error" in output:
                logger.error(f"Action execution error: {output['error']}")
                return output

            logger.debug(f"[ACTION] Parsed action output: {output}")
            return output

        except Exception as e:
            logger.exception("Error occurred while executing atomic action")
            # Mark status=error so the caller (execute_action) propagates "error" to
            # the action_end event, the UI display_status, and the on_action_end hook.
            # Without this, the action is reported as "completed/success" despite raising.
            return {"status": "error", "error": f"Execution failed: {str(e)}"}

    @staticmethod
    def _parse_action_output(raw_output: str) -> Any:
        """Attempt to decode a JSON object from captured stdout."""
        if not raw_output:
            return {}

        ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
        cleaned = ansi_escape.sub("", raw_output).strip()

        if not cleaned:
            return {}

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.debug(
                "Raw action output was not pure JSON; attempting to extract payload."
            )
            json_start_candidates = [
                idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx != -1
            ]
            if not json_start_candidates:
                raise

            start = min(json_start_candidates)
            end_brace = cleaned.rfind("}")
            end_bracket = cleaned.rfind("]")
            end_candidates = [idx for idx in (end_brace, end_bracket) if idx != -1]
            if not end_candidates:
                raise

            end = max(end_candidates)
            candidate = cleaned[start : end + 1]
            parsed = json.loads(candidate)
            logger.debug("Recovered JSON payload from action output.")
            return parsed

    @profile(
        "action_manager_execute_divisible_action", OperationCategory.ACTION_EXECUTION
    )
    async def execute_divisible_action(self, action, input_data, parent_id) -> Dict:
        results = {}
        for sub in action.sub_actions:
            results[sub.name] = await self.execute_action(
                sub,
                context=str(input_data),
                event_stream="",
                parent_id=parent_id,
                input_data=input_data if isinstance(input_data, dict) else None,
            )
        return results

    @profile("action_manager_run_observe_step", OperationCategory.ACTION_EXECUTION)
    async def run_observe_step(
        self, action: Action, action_output: Dict
    ) -> Dict[str, Any]:
        """
        Executes the observation code with retries, to confirm action outcome.
        """
        observe = action.observer
        if not observe or not observe.code:
            return {"success": True, "message": "No observation step."}

        input_json = json.dumps(action_output)
        python_script = f"""import json;output = {input_json};{observe.code}"""

        attempt = 0
        start_time = time.time()
        while (
            attempt < observe.max_retries
            and (time.time() - start_time) < observe.max_total_time_sec
        ):
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()

            sys.stdout = stdout_buf
            sys.stderr = stderr_buf
            local_env = {}

            try:
                exec(python_script, {}, local_env)
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__

                success = local_env.get("success", None)
                message = local_env.get("message", "")

                if success is True:
                    return {"success": True, "message": message}
                elif success is False:
                    return {"success": False, "message": message}

            except Exception as e:
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__
                logger.warning(f"[OBSERVE] Error during observation: {e}")

            await asyncio.sleep(observe.retry_interval_sec)
            attempt += 1

        return {"success": False, "message": "Observation failed or timed out."}

    @staticmethod
    def _extract_base64_to_files(data: dict, action_name: str) -> dict:
        """
        Scan action output for large base64 data URLs and save them to temp files.
        Replaces the base64 string with the file path so LLMs don't truncate it.
        """
        import tempfile
        import base64
        import re

        if not isinstance(data, dict):
            return data

        MIN_BASE64_LENGTH = 500  # Only process strings longer than this

        def process_value(key: str, value):
            if not isinstance(value, str) or len(value) < MIN_BASE64_LENGTH:
                return value

            # Check for data URL format: data:image/png;base64,iVBOR...
            match = re.match(r"^data:([\w/+.-]+);base64,(.+)$", value, re.DOTALL)
            if match:
                mime_type = match.group(1)
                b64_data = match.group(2)
                ext = {
                    "image/png": ".png",
                    "image/jpeg": ".jpg",
                    "image/gif": ".gif",
                    "image/webp": ".webp",
                    "application/pdf": ".pdf",
                }.get(mime_type, ".bin")

                try:
                    decoded = base64.b64decode(b64_data)
                    tmp = tempfile.NamedTemporaryFile(
                        delete=False,
                        suffix=ext,
                        prefix=f"{action_name}_{key}_",
                    )
                    tmp.write(decoded)
                    tmp.close()
                    logger.info(
                        f"[ACTION] Saved base64 {key} ({len(b64_data)} chars) to {tmp.name}"
                    )
                    return tmp.name
                except Exception as e:
                    logger.warning(f"[ACTION] Failed to extract base64 from {key}: {e}")

            return value

        result = {}
        for k, v in data.items():
            if isinstance(v, dict):
                result[k] = ActionManager._extract_base64_to_files(v, action_name)
            elif isinstance(v, list):
                result[k] = [
                    ActionManager._extract_base64_to_files(item, action_name)
                    if isinstance(item, dict)
                    else process_value(k, item)
                    if isinstance(item, str)
                    else item
                    for item in v
                ]
            else:
                result[k] = process_value(k, v)
        return result
