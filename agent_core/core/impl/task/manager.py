# -*- coding: utf-8 -*-
"""
Shared TaskManager for agent_core.

This module provides the TaskManager class that handles task lifecycle,
todo management, and action set compilation. It uses hooks for runtime-specific
behavior:

State hooks:
- get_gui_mode: Returns current GUI/CLI mode
- get_agent_property: Gets agent property from state
- set_agent_property: Sets agent property in state
- get_conversation_id: Gets current conversation ID (WCA only)
- get_active_task_id: Gets current task ID from session state

Event stream hooks:
- on_stream_create: Called when task is created to set up event stream
- on_stream_remove: Called when task ends to clean up event stream

Chatserver hooks (WCA only):
- on_task_created_chatserver: POST task to chatserver
- on_todo_transition: POST/PUT todo transitions to chatserver
- on_task_ended_chatserver: PUT final task status to chatserver
- finalize_todos_chatserver: PUT remaining todos on task end
"""

import asyncio
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, List, Dict, Any, Optional, TYPE_CHECKING

from agent_core.core.task import Task, TodoItem
from agent_core.core.state import get_state, StateSession
from agent_core.core.impl.llm import LLMCallType

if TYPE_CHECKING:
    from agent_core.core.state.base import StateManagerBase

# Set up logger - use shared agent_core logger for consistency
from agent_core.utils.logger import logger


# =============================================================================
# Hook Type Definitions
# =============================================================================

# State hooks
GetGuiModeHook = Callable[[], bool]
GetAgentPropertyHook = Callable[[str, Any], Any]
SetAgentPropertyHook = Callable[[str, Any], None]
GetConversationIdHook = Callable[[], Optional[str]]
GetActiveTaskIdHook = Callable[[], Optional[str]]

# Event stream hooks
OnStreamCreateHook = Callable[[str, Path], None]  # (task_id, temp_dir)
OnStreamRemoveHook = Callable[[str], None]  # (task_id)

# Chatserver hooks (WCA only)
OnTaskCreatedChatserverHook = Callable[[Task], None]
OnTodoTransitionHook = Callable[[List[tuple]], None]  # List of (todo, old_status, new_status)
OnTaskEndedChatserverHook = Callable[[Task, str, Optional[str]], Awaitable[None]]
FinalizeTodosChatserverHook = Callable[[Task, str], Awaitable[None]]


class TaskManager:
    """
    Task manager using todo-based tracking with hook-based customization.

    Coordinates task lifecycle without complex step planning. The agent
    directly manages the todo list via update_todos(). Runtime-specific
    behavior (state access, chatserver reporting) is handled via hooks.
    """

    def __init__(
        self,
        db_interface,
        event_stream_manager,
        state_manager: "StateManagerBase",
        llm_interface=None,
        context_engine=None,
        on_task_end_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        workspace_root: Optional[Path] = None,
        agent_file_system_path: Optional[Path] = None,
        *,
        # State hooks
        get_gui_mode: Optional[GetGuiModeHook] = None,
        get_agent_property: Optional[GetAgentPropertyHook] = None,
        set_agent_property: Optional[SetAgentPropertyHook] = None,
        get_conversation_id: Optional[GetConversationIdHook] = None,
        get_active_task_id: Optional[GetActiveTaskIdHook] = None,
        # Event stream hooks
        on_stream_create: Optional[OnStreamCreateHook] = None,
        on_stream_remove: Optional[OnStreamRemoveHook] = None,
        # Chatserver hooks (WCA only)
        on_task_created_chatserver: Optional[OnTaskCreatedChatserverHook] = None,
        on_todo_transition: Optional[OnTodoTransitionHook] = None,
        on_task_ended_chatserver: Optional[OnTaskEndedChatserverHook] = None,
        finalize_todos_chatserver: Optional[FinalizeTodosChatserverHook] = None,
    ):
        """
        Initialize the task manager.

        Args:
            db_interface: Persistence layer for task logging.
            event_stream_manager: Event stream for user-visible progress.
            state_manager: State tracker for sharing task context.
            llm_interface: LLM interface for creating session caches (optional).
            context_engine: Context engine for generating system prompts (optional).
            on_task_end_callback: Optional async callback invoked when a task ends.
            workspace_root: Root directory for task temp dirs.
            agent_file_system_path: Path to agent file system (for TASK_HISTORY.md).

            State hooks:
            get_gui_mode: Returns True if GUI mode, False for CLI mode.
            get_agent_property: Gets property from state (name, default) -> value.
            set_agent_property: Sets property in state (name, value) -> None.
            get_conversation_id: Gets current conversation ID (WCA) or None.
            get_active_task_id: Gets active task ID from session state.

            Event stream hooks:
            on_stream_create: Called to set up event stream for task.
            on_stream_remove: Called to clean up event stream on task end.

            Chatserver hooks (WCA only):
            on_task_created_chatserver: POST task to chatserver.
            on_todo_transition: Report todo transitions to chatserver.
            on_task_ended_chatserver: PUT final task status to chatserver.
            finalize_todos_chatserver: Finalize remaining todos on task end.
        """
        self.db_interface = db_interface
        self.event_stream_manager = event_stream_manager
        self.state_manager = state_manager
        self.llm_interface = llm_interface
        self.context_engine = context_engine
        self._on_task_end = on_task_end_callback
        self.tasks: Dict[str, Task] = {}
        self._current_session_id: Optional[str] = None  # For CraftBot compatibility
        self.workspace_root = workspace_root or Path(".")
        self.agent_file_system_path = agent_file_system_path

        # State hooks (with defaults for CraftBot compatibility)
        self._get_gui_mode = get_gui_mode or (lambda: get_state().gui_mode)
        self._get_agent_property = get_agent_property or (
            lambda name, default: get_state().get_agent_property(name, default)
        )
        self._set_agent_property = set_agent_property or (
            lambda name, value: get_state().set_agent_property(name, value)
        )
        self._get_conversation_id = get_conversation_id or (lambda: None)
        self._get_active_task_id = get_active_task_id

        # Event stream hooks
        self._on_stream_create = on_stream_create
        self._on_stream_remove = on_stream_remove

        # Chatserver hooks (WCA only, default to None/no-op)
        self._on_task_created_chatserver = on_task_created_chatserver
        self._on_todo_transition = on_todo_transition
        self._on_task_ended_chatserver = on_task_ended_chatserver
        self._finalize_todos_chatserver = finalize_todos_chatserver

    @property
    def active(self) -> Optional[Task]:
        """Current session's task.

        Resolution strategy:
        1. If get_active_task_id hook is set, use it (WCA/session-based).
        2. Otherwise, use _current_session_id (CraftBot/singleton-based).
        3. Fall back to the only task if there's just one.
        """
        if self._get_active_task_id:
            task_id = self._get_active_task_id()
            if task_id:
                return self.tasks.get(task_id)
            return None

        # CraftBot fallback: use _current_session_id or only task
        if self._current_session_id:
            return self.tasks.get(self._current_session_id)
        if len(self.tasks) == 1:
            return next(iter(self.tasks.values()))
        return None

    def get_task_by_id(self, task_id: str) -> Optional[Task]:
        """Look up a task by its ID (without needing a session)."""
        return self.tasks.get(task_id)

    def has_any_running_task(self) -> bool:
        """Check if any task is currently running."""
        return any(t.status == "running" for t in self.tasks.values())

    def set_current_session(self, session_id: str) -> None:
        """Set the current session ID for the active property (CraftBot)."""
        self._current_session_id = session_id

    def reset(self) -> None:
        """Clear all task state."""
        self.tasks.clear()
        self._current_session_id = None

    # ─────────────────────── Task Creation ───────────────────────────────────

    def create_task(
        self,
        task_name: str,
        task_instruction: str,
        mode: str = "complex",
        action_sets: Optional[List[str]] = None,
        selected_skills: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        original_query: Optional[str] = None,
        original_platform: Optional[str] = None,
    ) -> str:
        """
        Create a new task without LLM planning.

        Args:
            task_name: Human-readable identifier for the task.
            task_instruction: Description of the work to be done.
            mode: Task execution mode - "simple" or "complex".
            action_sets: List of action set names to enable for this task.
            selected_skills: List of skill names selected for this task.
            session_id: Optional session ID to use as task_id. If provided,
                       this ID will be used instead of generating a new one.
                       This ensures session_id and task_id are the same,
                       which is critical for event stream isolation.
            original_query: Optional original user message to log to the task's
                           event stream. If provided, logs as "user message"
                           before the task_start event.
            original_platform: Optional platform where the original message came from
                              (e.g., "CraftBot TUI", "Telegram", "Whatsapp").

        Returns:
            The unique task identifier.
        """
        # Use session_id as task_id if provided (ensures session_id == task_id)
        # Otherwise generate a new ID for backwards compatibility
        if session_id:
            task_id = session_id
        else:
            task_id = self._sanitize_task_id(f"{task_name}_{uuid.uuid4().hex[:6]}")
        temp_dir = self._prepare_task_temp_dir(task_id)

        # Compile action list from selected sets
        # Note: compile_action_list always includes "core" set automatically
        selected_sets = action_sets or []
        from app.action.action_set import action_set_manager
        visibility_mode = "GUI" if self._get_gui_mode() else "CLI"
        compiled_actions = action_set_manager.compile_action_list(
            selected_sets, mode=visibility_mode
        )
        logger.debug(f"[TaskManager] Compiled {len(compiled_actions)} actions from sets: {selected_sets}")

        # Get conversation_id via hook (WCA) or None (CraftBot)
        conversation_id = self._get_conversation_id()

        task = Task(
            id=task_id,
            name=task_name,
            instruction=task_instruction,
            mode=mode,
            temp_dir=str(temp_dir),
            action_sets=selected_sets,
            compiled_actions=compiled_actions,
            selected_skills=selected_skills or [],
            conversation_id=conversation_id,
        )

        self.tasks[task_id] = task
        self._current_session_id = task_id  # CraftBot compatibility
        self.db_interface.log_task(task)
        self._sync_state_manager(task)

        # Notify state manager for two-tier state tracking
        if self.state_manager:
            self.state_manager.on_task_created(task)

        # Set up event stream via hook
        if self._on_stream_create:
            self._on_stream_create(task_id, temp_dir)
        else:
            # CraftBot default: assign temp_dir to single event stream
            self.event_stream_manager.event_stream.temp_dir = temp_dir

        # Log original user query to the new task's stream (if provided)
        # This ensures the task's event stream contains the original user message
        # before the task_start event, providing full context for the task.
        if original_query:
            # Format event label with platform info (matches state_manager.record_user_message format)
            if original_platform:
                event_label = f"user message from platform: {original_platform}"
            else:
                event_label = "user message"
            self.event_stream_manager.log(
                event_label,
                original_query,
                display_message=original_query,
                task_id=task_id,
            )

        # CRITICAL: Pass task_id explicitly to ensure event goes to the NEW task's stream,
        # not the previous task's stream. The global STATE.current_task_id hasn't been
        # updated yet, so without explicit task_id, log() would use the old task's stream.
        self.event_stream_manager.log(
            "task_start",
            f"Created task: '{task_name}'",
            display_message=task_name,
            task_id=task_id,
        )

        self._set_agent_property("current_task_id", task_id)

        # Call chatserver hook if provided (WCA)
        if self._on_task_created_chatserver:
            self._on_task_created_chatserver(task)

        # Create session caches for all tasks
        if self.llm_interface and self.context_engine:
            self._create_session_caches(task_id)

        logger.debug(f"[TaskManager] Task {task_id} created")
        return task_id

    def _create_session_caches(self, task_id: str) -> None:
        """Create session caches for a task."""
        try:
            system_prompt, _ = self.context_engine.make_prompt(
                user_flags={"query": False, "expected_output": False},
                system_flags={"policy": False},
            )
            for call_type in [
                LLMCallType.REASONING,
                LLMCallType.ACTION_SELECTION,
                LLMCallType.GUI_REASONING,
                LLMCallType.GUI_ACTION_SELECTION,
            ]:
                cache_id = self.llm_interface.create_session_cache(task_id, call_type, system_prompt)
                if cache_id:
                    logger.debug(f"[TaskManager] Created session cache {cache_id} for task {task_id}:{call_type}")
        except Exception as e:
            logger.warning(f"[TaskManager] Failed to create session caches for task {task_id}: {e}")

    # ─────────────────────── Todo Management ─────────────────────────────────

    def update_todos(self, todos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Update the todo list for the active task.

        Called by the agent to add, update, or complete todos.
        Detects status transitions and reports them via hook if provided.

        Args:
            todos: List of todo dictionaries with content, status, and
                   optional active_form.

        Returns:
            The updated todo list as dictionaries.
        """
        if not self.active:
            logger.warning("[TaskManager] No active task to update todos")
            return []

        # Strip status suffixes that LLMs sometimes append to content
        def _clean_content(s: str) -> str:
            return re.sub(
                r"\s*-\s*(completed|in_progress|in progress|pending|done)\s*$",
                "", s, flags=re.IGNORECASE
            ).strip()

        # Build lookup of existing todos by cleaned content to preserve IDs
        existing_by_content: Dict[str, TodoItem] = {
            _clean_content(t.content): t for t in self.active.todos
        }

        new_todos: List[TodoItem] = []
        transitions: List[tuple] = []  # (todo, old_status, new_status)

        for t_dict in todos:
            raw_content = t_dict.get("content", "")
            content = _clean_content(raw_content)
            new_status = t_dict.get("status", "pending")

            existing = existing_by_content.get(content)
            if existing:
                old_status = existing.status
                existing.status = new_status
                existing.content = content
                existing.active_form = t_dict.get("active_form", existing.active_form)
                new_todos.append(existing)
                if old_status != new_status:
                    transitions.append((existing, old_status, new_status))
            else:
                t_dict_clean = {**t_dict, "content": content}
                item = TodoItem.from_dict(t_dict_clean)
                new_todos.append(item)
                if new_status == "in_progress":
                    transitions.append((item, "pending", "in_progress"))

        self.active.todos = new_todos
        self.db_interface.log_task(self.active)
        self._sync_state_manager(self.active)

        # Report transitions via hook if provided (WCA)
        if transitions and self._on_todo_transition:
            self._on_todo_transition(transitions)

        # Track the current in-progress todo's ID for parent_action_id
        in_progress_todo = next(
            (t for t in self.active.todos if t.status == "in_progress"),
            None,
        )
        self._set_agent_property(
            "current_todo_action_id",
            in_progress_todo.id if in_progress_todo else None,
        )

        logger.debug(f"[TaskManager] Updated {len(self.active.todos)} todos, {len(transitions)} transitions")
        return [t.to_dict() for t in self.active.todos]

    def get_todos(self) -> List[Dict[str, Any]]:
        """Get the current todo list as dictionaries."""
        if not self.active:
            return []
        return [t.to_dict() for t in self.active.todos]

    # ─────────────────────── Task Completion ─────────────────────────────────

    async def mark_task_completed(
        self,
        message: Optional[str] = None,
        summary: Optional[str] = None,
        errors: Optional[List[str]] = None,
        task_id: Optional[str] = None,
    ) -> bool:
        """Mark a specific task as completed.

        Args:
            message: Completion message.
            summary: Summary of what was accomplished.
            errors: List of errors encountered.
            task_id: Specific task ID to complete. If None, uses active task (legacy).
        """
        task = self.tasks.get(task_id) if task_id else self.active
        if not task:
            return False
        await self._end_task(task, "completed", message, summary, errors)
        return True

    async def mark_task_error(
        self,
        message: Optional[str] = None,
        summary: Optional[str] = None,
        errors: Optional[List[str]] = None,
        task_id: Optional[str] = None,
    ) -> bool:
        """Mark a specific task as failed with an error.

        Args:
            message: Error message.
            summary: Summary of what was done before error.
            errors: List of errors encountered.
            task_id: Specific task ID to mark as error. If None, uses active task (legacy).
        """
        task = self.tasks.get(task_id) if task_id else self.active
        if not task:
            return False
        await self._end_task(task, "error", message, summary, errors)
        return True

    async def mark_task_cancel(
        self,
        reason: Optional[str] = None,
        summary: Optional[str] = None,
        errors: Optional[List[str]] = None,
        task_id: Optional[str] = None,
    ) -> bool:
        """Cancel a specific task.

        Args:
            reason: Reason for cancellation.
            summary: Summary of what was done before cancellation.
            errors: List of errors encountered.
            task_id: Specific task ID to cancel. If None, uses active task (legacy).
        """
        task = self.tasks.get(task_id) if task_id else self.active
        if not task:
            return False
        await self._end_task(task, "cancelled", reason, summary, errors)
        return True

    def get_task(self) -> Optional[Task]:
        """Get the currently active task."""
        return self.active

    def is_simple_task(self) -> bool:
        """Check if current task is in simple mode."""
        return self.active is not None and self.active.mode == "simple"

    # ─────────────────────── Action Set Management ───────────────────────────

    def add_action_sets(self, sets_to_add: List[str]) -> Dict[str, Any]:
        """Add action sets to the current task and recompile the action list."""
        if not self.active:
            return {"success": False, "error": "No active task"}

        from app.action.action_set import action_set_manager

        current_sets = set(self.active.action_sets)
        new_sets = set(sets_to_add) - current_sets
        self.active.action_sets = list(current_sets | new_sets)

        visibility_mode = "GUI" if self._get_gui_mode() else "CLI"
        old_actions = set(self.active.compiled_actions)
        self.active.compiled_actions = action_set_manager.compile_action_list(
            self.active.action_sets, mode=visibility_mode
        )
        new_actions = set(self.active.compiled_actions) - old_actions

        self._sync_state_manager(self.active)

        logger.debug(f"[TaskManager] Added action sets {sets_to_add}, now have {len(self.active.compiled_actions)} actions")
        return {
            "success": True,
            "current_sets": self.active.action_sets,
            "added_actions": list(new_actions),
            "total_actions": len(self.active.compiled_actions),
        }

    def remove_action_sets(self, sets_to_remove: List[str]) -> Dict[str, Any]:
        """Remove action sets from the current task and recompile."""
        if not self.active:
            return {"success": False, "error": "No active task"}

        from app.action.action_set import action_set_manager

        sets_to_remove_filtered = [s for s in sets_to_remove if s != "core"]
        current_sets = set(self.active.action_sets)
        self.active.action_sets = list(current_sets - set(sets_to_remove_filtered))

        visibility_mode = "GUI" if self._get_gui_mode() else "CLI"
        old_actions = set(self.active.compiled_actions)
        self.active.compiled_actions = action_set_manager.compile_action_list(
            self.active.action_sets, mode=visibility_mode
        )
        removed_actions = old_actions - set(self.active.compiled_actions)

        self._sync_state_manager(self.active)

        logger.debug(f"[TaskManager] Removed action sets {sets_to_remove_filtered}, now have {len(self.active.compiled_actions)} actions")
        return {
            "success": True,
            "current_sets": self.active.action_sets,
            "removed_actions": list(removed_actions),
            "total_actions": len(self.active.compiled_actions),
        }

    def get_action_sets(self) -> List[str]:
        """Get the current action sets for the active task."""
        if not self.active:
            return []
        return self.active.action_sets.copy()

    def get_compiled_actions(self) -> List[str]:
        """Get the compiled action list for the active task."""
        if not self.active:
            return []
        return self.active.compiled_actions.copy()

    # ─────────────────────── Internal Helpers ────────────────────────────────

    async def _end_task(
        self,
        task: Task,
        status: str,
        note: Optional[str],
        summary: Optional[str] = None,
        errors: Optional[List[str]] = None
    ) -> None:
        """Finalize a task with the given status."""
        task.status = status
        task.ended_at = datetime.utcnow().isoformat()
        task.final_summary = summary
        task.errors = errors or []

        self.db_interface.log_task(task)
        self._sync_state_manager(task)

        self.event_stream_manager.log(
            "task_end",
            f"Task ended with status '{status}'. {note or ''}",
            display_message=task.name,
            task_id=task.id,
        )

        # Log to TASK_HISTORY.md
        self._log_to_task_history(task, note)

        # Reset skip_unprocessed_logging flag
        if hasattr(self.event_stream_manager, 'set_skip_unprocessed_logging'):
            self.event_stream_manager.set_skip_unprocessed_logging(False)

        # Finalize remaining todos via chatserver hook (WCA)
        if self._finalize_todos_chatserver:
            await self._finalize_todos_chatserver(task, status)

        # Finalize task via chatserver hook (WCA)
        if self._on_task_ended_chatserver:
            await self._on_task_ended_chatserver(task, status, summary)

        # Notify state manager BEFORE removing task
        if self.state_manager:
            self.state_manager.on_task_ended(task, status, summary)

        # Remove task from dict and clean up event stream
        self.tasks.pop(task.id, None)
        if self._current_session_id == task.id:
            self._current_session_id = None

        # Clean up session-specific state (multi-task isolation)
        StateSession.end(task.id)

        # Small delay to allow UI to poll task_end event before stream removal.
        # The UI polls every 50ms, so 100ms gives at least one poll opportunity.
        await asyncio.sleep(0.1)

        # Remove event stream via hook (WCA) or no-op (CraftBot)
        if self._on_stream_remove:
            self._on_stream_remove(task.id)

        # Only reset global agent state if NO other tasks are running
        # This prevents ending one parallel task from corrupting state for others
        has_other_running_tasks = any(t.status == "running" for t in self.tasks.values())
        if not has_other_running_tasks:
            self._set_agent_property("current_task_id", "")
            self._set_agent_property("action_count", 0)
            self._set_agent_property("token_count", 0)
            self._set_agent_property("current_todo_action_id", None)
            if self.state_manager:
                self.state_manager.remove_active_task()

        # Invoke callback to clean up session triggers
        if self._on_task_end:
            try:
                await self._on_task_end(task.id)
            except Exception as e:
                logger.warning(f"[TaskManager] on_task_end callback failed: {e}")

        # Cleanup temp directory
        self._cleanup_task_temp_dir(task)

        # Check if this was a soft onboarding task that completed successfully
        if status == "completed" and "user-profile-interview" in (task.selected_skills or []):
            try:
                from app.onboarding import onboarding_manager
                onboarding_manager.mark_soft_complete()
                logger.info("[ONBOARDING] Soft onboarding task completed, marked as complete")
            except Exception as e:
                logger.warning(f"[ONBOARDING] Failed to mark soft onboarding complete: {e}")

    def _sync_state_manager(self, task: Optional[Task]) -> None:
        """Sync task state to the state manager."""
        if self.state_manager:
            self.state_manager.add_to_active_task(task=task)

    def _log_to_task_history(self, task: Task, note: Optional[str] = None) -> None:
        """Log completed task to TASK_HISTORY.md."""
        if not self.agent_file_system_path:
            return

        try:
            task_history_path = self.agent_file_system_path / "TASK_HISTORY.md"

            if not task_history_path.exists():
                logger.warning(f"[TaskManager] TASK_HISTORY.md not found at {task_history_path}")
                return

            entry_lines = [
                f"### Task: {task.name}",
                f"- **Task ID:** `{task.id}`",
                f"- **Status:** {task.status}",
                f"- **Created:** {task.created_at}",
                f"- **Ended:** {task.ended_at}",
            ]

            if task.errors:
                entry_lines.append("- **Errors:**")
                for error in task.errors:
                    entry_lines.append(f"  - {error}")

            if task.final_summary:
                entry_lines.append(f"- **Summary:** {task.final_summary}")
            elif note:
                entry_lines.append(f"- **Summary:** {note}")

            if task.instruction:
                entry_lines.append(f"- **Instruction:** {task.instruction}")

            if task.selected_skills:
                entry_lines.append(f"- **Skills:** {', '.join(task.selected_skills)}")

            if task.action_sets:
                entry_lines.append(f"- **Action Sets:** {', '.join(task.action_sets)}")

            entry_lines.append("")

            with open(task_history_path, "a", encoding="utf-8") as f:
                f.write("\n".join(entry_lines) + "\n")

            logger.debug(f"[TaskManager] Logged task {task.id} to TASK_HISTORY.md")

        except Exception as e:
            logger.warning(f"[TaskManager] Failed to log task to TASK_HISTORY.md: {e}")

    def _prepare_task_temp_dir(self, task_id: str) -> Path:
        """Create a temporary directory for the task."""
        temp_root = self.workspace_root / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        task_temp_dir = temp_root / task_id
        task_temp_dir.mkdir(parents=True, exist_ok=True)
        return task_temp_dir

    def _cleanup_task_temp_dir(self, task: Task) -> None:
        """Remove the task's temporary directory."""
        if not task.temp_dir:
            return
        try:
            shutil.rmtree(task.temp_dir, ignore_errors=True)
            logger.debug(f"[TaskManager] Cleaned up temp dir for task {task.id}")
        except Exception:
            logger.warning(f"[TaskManager] Failed to clean temp dir for {task.id}", exc_info=True)

    def cleanup_all_temp_dirs(self) -> int:
        """Remove all temporary directories in workspace/tmp/."""
        temp_root = self.workspace_root / "tmp"
        if not temp_root.exists():
            return 0

        cleaned_count = 0
        try:
            for item in temp_root.iterdir():
                if item.is_dir():
                    try:
                        shutil.rmtree(item, ignore_errors=True)
                        cleaned_count += 1
                        logger.debug(f"[TaskManager] Cleaned up leftover temp dir: {item.name}")
                    except Exception:
                        logger.warning(f"[TaskManager] Failed to clean leftover temp dir: {item.name}", exc_info=True)

            if cleaned_count > 0:
                logger.info(f"[TaskManager] Cleaned up {cleaned_count} leftover temp directories on startup")
        except Exception:
            logger.warning("[TaskManager] Failed to enumerate temp directories", exc_info=True)

        return cleaned_count

    def _sanitize_task_id(self, s: str) -> str:
        """Sanitize a string for use as a task ID."""
        s = s.strip()
        s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
        s = re.sub(r"_+", "_", s)
        return s.strip("._-") or "task"
