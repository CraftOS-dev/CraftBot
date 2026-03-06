from typing import Dict, List, Optional, Any, TYPE_CHECKING
from datetime import datetime
from pathlib import Path
from agent_core.core.state.types import MainState
from agent_core.core.state.session import StateSession
from app.state.types import AgentProperties
from app.state.agent_state import STATE
from app.event_stream import EventStreamManager
from app.task import Task, TodoItem
from app.logger import logger
from app.config import AGENT_FILE_SYSTEM_PATH

if TYPE_CHECKING:
    from app.task.task_manager import TaskManager


class StateManager:
    """Manages task state and runtime session data."""

    def __init__(
        self,
        event_stream_manager: EventStreamManager,
    ):
        # Two-tier state architecture:
        # 1. Main state: Conversation-level context (not task-specific)
        #    - Records what tasks have been started (summaries)
        #    - Stores main event stream for conversation history
        # 2. Task state: Task-specific execution context
        #    - Task event stream, todos, action counts, etc.
        self._main_state: MainState = MainState()
        self.task: Optional[Task] = None
        self.event_stream_manager = event_stream_manager
        self._task_manager: Optional["TaskManager"] = None

    def bind_task_manager(self, task_manager: "TaskManager") -> None:
        """Bind a task manager for session-aware task lookups."""
        self._task_manager = task_manager

    # ─────────────────────────────────────────────────────────────────────────
    # Main State Methods (Two-Tier Architecture)
    # ─────────────────────────────────────────────────────────────────────────

    def get_main_state(self) -> MainState:
        """Get main state for conversation mode context."""
        return self._main_state

    def refresh_main_state(self, gui_mode: bool = False) -> None:
        """Refresh main state with current data."""
        self._main_state.gui_mode = gui_mode
        self._main_state.main_event_stream = self.event_stream_manager.snapshot_main()

    def log_to_main_stream(self, kind: str, message: str, **kwargs) -> None:
        """Log event to main stream (for conversation mode / task summaries)."""
        main_stream = self.event_stream_manager.get_main_stream()
        main_stream.log(kind, message, **kwargs)

    def on_task_created(self, task: Task) -> None:
        """Called when a new task is created.

        Tracks task in main state and logs to main stream.
        Note: Per-task event stream is created via TaskManager's on_stream_create hook,
        not here, to avoid duplicate stream creation.
        """
        # Track in main state
        self._main_state.add_task_started(task.id, task.name, task.created_at)

        # Log to main stream
        self.log_to_main_stream(
            "task_started",
            f"Started task: {task.name}",
            display_message=f"Task started: {task.name}"
        )
        logger.debug(f"[STATE] Task created and tracked in main state: {task.id}")

    def on_task_ended(self, task: Task, status: str, summary: Optional[str] = None) -> None:
        """Called when a task ends.

        Updates main state, logs to main stream, removes per-task stream.
        """
        # Update main state
        self._main_state.mark_task_ended(
            task.id, status, task.ended_at or "", summary
        )

        # Log to main stream
        self.log_to_main_stream(
            "task_ended",
            f"Task {status}: {task.name}. {summary or ''}",
            display_message=f"Task {status}: {task.name}"
        )

        # Remove per-task stream
        self.event_stream_manager.remove_stream(task.id)
        logger.debug(f"[STATE] Task ended and removed from tracking: {task.id}")

    # ─────────────────────────────────────────────────────────────────────────
    # Session Management
    # ─────────────────────────────────────────────────────────────────────────

    async def start_session(self, gui_mode: bool = False, session_id: Optional[str] = None):
        """
        Initialize a session, optionally for a specific task/session.

        Two-tier state handling:
        - Always refresh main state (conversation history, task summaries)
        - If task found: use task-specific event stream
        - If no task: use main state event stream (conversation mode)

        Args:
            gui_mode: Whether the session is in GUI mode.
            session_id: Optional task/session ID to look up and set as current.
        """
        # Always refresh main state first
        self.refresh_main_state(gui_mode)

        current_task: Optional[Task] = None
        event_stream: str

        # If session_id provided and we have a task manager, look up the task
        if session_id and self._task_manager:
            current_task = self._task_manager.get_task_by_id(session_id)
            if current_task:
                self._task_manager.set_current_session(session_id)
                self.task = current_task  # Update state manager's task reference
                # Use task-specific event stream
                event_stream = self.event_stream_manager.snapshot_by_id(session_id)
                logger.debug(f"[STATE] Loaded task for session={session_id}")
            else:
                # No task for this session - conversation mode
                self._task_manager.set_current_session(session_id)
                self.task = None
                # Use main state event stream (conversation history)
                event_stream = self._main_state.main_event_stream
                logger.debug(f"[STATE] No task found for session={session_id}, using main state (conversation mode)")
        elif not session_id:
            # No session_id provided - use existing task if any
            current_task = self.get_current_task_state()
            event_stream = self.get_event_stream_snapshot()
        else:
            event_stream = self.get_event_stream_snapshot()

        logger.debug(f"[CURRENT TASK]: this is the current_task: {current_task}")

        # Create/update session-specific state for multi-task isolation
        # This allows concurrent tasks to have independent state
        if session_id:
            StateSession.start(
                session_id=session_id,
                current_task=current_task,
                event_stream=event_stream,
                gui_mode=gui_mode,
            )
            logger.debug(f"[STATE] StateSession created for session_id={session_id}")

        STATE.refresh(
            current_task=current_task,
            event_stream=event_stream,
            gui_mode=gui_mode
        )

        # CRITICAL: Sync agent_properties.current_task_id with the session being processed
        # This ensures consistency when multiple tasks run concurrently.
        # Without this, task A's trigger could use task B's session cache.
        task_id = current_task.id if current_task else (session_id or "")
        STATE.set_agent_property("current_task_id", task_id)

    def clean_state(self):
        """
        End the session, clearing session context so the next user input starts fresh.
        """
        STATE.refresh()

    def reset(self) -> None:
        """Fully reset runtime state, including tasks and session context."""
        self.task = None
        STATE.agent_properties: AgentProperties = AgentProperties(
            current_task_id="", action_count=0
        )
        if self.event_stream_manager:
            self.event_stream_manager.clear_all()
        self.clean_state()

    def _append_to_conversation_history(self, sender: str, content: str) -> None:
        """
        Append a message to CONVERSATION_HISTORY.md with timestamp.

        Format: [YYYY/MM/DD HH:MM:SS] [sender]: message

        Args:
            sender: Either "user" or "agent"
            content: The message content
        """
        try:
            conversation_file = Path(AGENT_FILE_SYSTEM_PATH) / "CONVERSATION_HISTORY.md"
            timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            entry = f"[{timestamp}] [{sender}]: {content}\n"

            with open(conversation_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            logger.warning(f"[STATE] Failed to append to conversation history: {e}")

    def record_user_message(
        self,
        content: str,
        session_id: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> None:
        """Record a user message to the event stream and conversation history.

        Args:
            content: The message content.
            session_id: Optional task/session ID for multi-task isolation.
                       If not provided, falls back to current task's ID.
            platform: Optional platform identifier (e.g., "Telegram", "WhatsApp", "CraftBot TUI").
                     If provided, the event label becomes "user message from platform: X".
        """
        # Get task_id for proper event stream isolation in multi-task scenarios
        task_id = session_id or (self.task.id if self.task else None)

        # Include platform info in the event label if provided
        if platform:
            event_label = f"user message from platform: {platform}"
        else:
            event_label = "user message"

        self.event_stream_manager.log(
            event_label,
            content,
            display_message=content,
            task_id=task_id,
        )

        # Record to conversation history for context injection into future tasks
        self.event_stream_manager.record_conversation_message(
            event_label,
            content,
            display_message=content,
        )

        self.bump_event_stream()
        self._append_to_conversation_history("user", content)

    def record_agent_message(
        self,
        content: str,
        session_id: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> None:
        """Record an agent message to the event stream and conversation history.

        Args:
            content: The message content.
            session_id: Optional task/session ID for multi-task isolation.
                       If not provided, falls back to current task's ID.
            platform: Optional platform identifier (e.g., "Telegram", "WhatsApp", "CraftBot TUI").
                     If provided, the event label becomes "agent message to platform: X".
        """
        # Get task_id for proper event stream isolation in multi-task scenarios
        task_id = session_id or (self.task.id if self.task else None)

        # Include platform info in the event label if provided
        if platform:
            event_label = f"agent message to platform: {platform}"
        else:
            event_label = "agent message"

        # Log to task-specific stream if within a task
        if task_id:
            self.event_stream_manager.log(
                event_label,
                content,
                display_message=content,
                task_id=task_id,
            )

        # Also log to main event stream (for conversation-level context)
        # This ensures agent messages appear in the main event stream alongside user messages
        main_stream = self.event_stream_manager.get_main_stream()
        main_stream.log(
            event_label,
            content,
            display_message=content,
        )

        # Record to conversation history for context injection into future tasks
        self.event_stream_manager.record_conversation_message(
            event_label,
            content,
            display_message=content,
        )

        self.bump_event_stream()
        self._append_to_conversation_history("agent", content)

    def get_current_todo(self) -> Optional[TodoItem]:
        """Get the current todo item from the active task."""
        task: Optional[Task] = self.task
        if not task:
            return None
        return task.get_current_todo()

    def get_event_stream_snapshot(self) -> str:
        return self.event_stream_manager.snapshot()

    def get_current_task_state(self) -> Optional[Task]:
        """Get the current task state for context."""
        task: Optional[Task] = self.task

        logger.debug(f"[TASK] task in StateManager: {task}")

        if not task:
            logger.debug("[TASK] task not found in StateManager")
            return None

        return task

    def bump_task_state(self) -> None:
        STATE.update_current_task(self.get_current_task_state())

    def bump_event_stream(self) -> None:
        STATE.update_event_stream(self.get_event_stream_snapshot())

    def is_running_task(self, session_id: Optional[str] = None) -> bool:
        """Check if a task is running for session_id, or for the current session.

        Args:
            session_id: Optional session ID to check for a running task.
                       If provided, checks if this specific session has a task.
                       If not provided, falls back to checking self.task.
        """
        if session_id and self._task_manager:
            result = session_id in self._task_manager.tasks
            logger.debug(f"[is_running_task] session_id={session_id!r}, in_tasks={result}")
            return result
        # Fallback: check current task reference
        return self.task is not None

    def add_to_active_task(self, task: Optional[Task]) -> None:
        if task is None:
            self.task = None
            STATE.update_current_task(None)
        else:
            self.task = task
            self.bump_task_state()

    def remove_active_task(self) -> None:
        self.task = None
        STATE.update_current_task(None)
