# -*- coding: utf-8 -*-
"""
app.agent_base

Generic, extensible agent that serves every role-specific AI worker.
This is a vanilla "base agent", can be launched by instantiating **AgentBase**
with default arguments; specialised agents simply subclass and override
or extend the protected hooks.

CraftBot is an open-source, light version of AI agent developed by CraftOS.
Here are the core features:
- Todo-based task tracking
- Can switch between CLI/GUI mode

Main agent cycle:
- Receive query from user
- Reply or create task
- Task cycle:
    - Action selection and execution
    - Update todos
    - Repeat until completion
"""

from __future__ import annotations

import asyncio
import os
import shutil
import traceback
import time
import uuid
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core import Action

from agent_core import ActionLibrary, ActionManager, ActionRouter

from app.config import (
    AGENT_WORKSPACE_ROOT,
    AGENT_FILE_SYSTEM_PATH,
    AGENT_FILE_SYSTEM_TEMPLATE_PATH,
    AGENT_MEMORY_CHROMA_PATH,
    PROCESS_MEMORY_AT_STARTUP,
)

from app.internal_action_interface import InternalActionInterface
from app.llm import LLMInterface, LLMCallType
from app.vlm_interface import VLMInterface
from app.database_interface import DatabaseInterface
from app.logger import logger
from agent_core import MemoryManager, MemoryPointer, MemoryFileWatcher, create_memory_processing_task
from app.context_engine import ContextEngine
from app.state.state_manager import StateManager
from app.state.agent_state import STATE
from app.trigger import Trigger, TriggerQueue
from app.prompt import ROUTE_TO_SESSION_PROMPT
from app.state.types import ReasoningResult
from app.task.task_manager import TaskManager
from app.event_stream import EventStreamManager
from app.gui.gui_module import GUIModule
from app.gui.handler import GUIHandler
from app.scheduler import SchedulerManager
from app.proactive import initialize_proactive_manager, get_proactive_manager
from agent_core import profile, profile_loop, OperationCategory
from agent_core import (
    # Registries for dependency injection
    DatabaseRegistry,
    LLMInterfaceRegistry,
    EventStreamManagerRegistry,
    StateManagerRegistry,
    ContextEngineRegistry,
    ActionExecutorRegistry,
    ActionManagerRegistry,
    TaskManagerRegistry,
    MemoryRegistry,
)
from pathlib import Path


@dataclass
class AgentCommand:
    name: str
    description: str
    handler: Callable[[], Awaitable[str | None]]


@dataclass
class TriggerData:
    """Structured data extracted from a Trigger."""
    query: str
    gui_mode: bool | None
    parent_id: str | None
    session_id: str | None = None
    user_message: str | None = None  # Original user message without routing prefix
    platform: str | None = None  # Source platform (e.g., "CraftBot TUI", "Telegram", "Whatsapp")
    is_self_message: bool = False  # True when the user sent themselves a message
    contact_id: str | None = None  # Sender/chat ID from external platform
    channel_id: str | None = None  # Channel/group ID from external platform

class AgentBase:
    """
    Foundation class for all agents.

    Sub-classes typically override **one or more** of the following:

    * `_load_extra_system_prompt`     → inject role-specific prompt fragment
    * `_register_extra_actions`       → register additional tools
    * `_build_db_interface`           → point to another Mongo/Chroma DB
    """

    def __init__(
        self,
        *,
        data_dir: str = "app/data",
        chroma_path: str = "./chroma_db",
        llm_provider: str = "anthropic",
        deferred_init: bool = False,
    ) -> None:
        """
        This constructor that initializes all agent components.

        Args:
            data_dir: Filesystem path where persistent agent data (plans,
                history, etc.) is stored.
            chroma_path: Directory for the local Chroma vector store used by the
                RAG components.
            llm_provider: Provider name passed to :class:`LLMInterface` and
                :class:`VLMInterface`.
            deferred_init: If True, allow LLM/VLM initialization to be deferred
                until API key is configured (useful for first-time setup).
        """

        # persistence & memory
        self.db_interface = self._build_db_interface(
            data_dir = data_dir, chroma_path=chroma_path
        )

        # LLM + prompt plumbing (may be deferred if API key not yet configured)
        self.llm = LLMInterface(
            provider=llm_provider,
            db_interface=self.db_interface,
            deferred=deferred_init,
        )
        self.vlm = VLMInterface(provider=llm_provider, deferred=deferred_init)

        self.event_stream_manager = EventStreamManager(
            self.llm,
            agent_file_system_path=AGENT_FILE_SYSTEM_PATH
        )
        
        # action & task layers
        self.action_library = ActionLibrary(self.llm, db_interface=self.db_interface)

        self.triggers = TriggerQueue(
            llm=self.llm,
            route_to_session_prompt=ROUTE_TO_SESSION_PROMPT,
        )

        # global state
        self.state_manager = StateManager(
            self.event_stream_manager
        )
        self.context_engine = ContextEngine(state_manager=self.state_manager)
        self.context_engine.set_role_info_hook(self._generate_role_info_prompt)

        self.action_manager = ActionManager(
            self.action_library, self.llm, self.db_interface, self.event_stream_manager, self.context_engine, self.state_manager
        )
        self.action_router = ActionRouter(self.action_library, self.llm, self.context_engine)

        self.task_manager = TaskManager(
            db_interface=self.db_interface,
            event_stream_manager=self.event_stream_manager,
            state_manager=self.state_manager,
            llm_interface=self.llm,
            context_engine=self.context_engine,
            on_task_end_callback=self._cleanup_session_triggers,
        )

        # Bind task_manager so state_manager can look up tasks by session_id
        self.state_manager.bind_task_manager(self.task_manager)
        # Bind task_manager and event_stream_manager to trigger queue for rich routing context
        self.triggers.set_task_manager(self.task_manager)
        self.triggers.set_event_stream_manager(self.event_stream_manager)

        # Clean up any leftover temp directories from previous runs
        self.task_manager.cleanup_all_temp_dirs()

        # ── memory manager for proactive agent ──
        self.memory_manager = MemoryManager(
            agent_file_system_path=str(AGENT_FILE_SYSTEM_PATH),
            chroma_path=str(AGENT_MEMORY_CHROMA_PATH),
        )
        # Connect memory manager to context engine for memory-aware prompts
        self.context_engine.set_memory_manager(self.memory_manager)

        # ── Register components with shared registries ──
        # This enables shared code to access components via get_*() functions
        DatabaseRegistry.register(lambda: self.db_interface)
        LLMInterfaceRegistry.register(lambda: self.llm)
        EventStreamManagerRegistry.register(lambda: self.event_stream_manager)
        StateManagerRegistry.register(lambda: self.state_manager)
        ContextEngineRegistry.register(lambda: self.context_engine)
        TaskManagerRegistry.register(lambda: self.task_manager)
        ActionManagerRegistry.register(lambda: self.action_manager)
        MemoryRegistry.register(lambda: self.memory_manager)

        # Index the agent file system on startup (incremental)
        try:
            self.memory_manager.update()
        except Exception as e:
            logger.warning(f"[MEMORY] Failed to update memory index on startup: {e}")

        # Start file watcher to auto-index on changes
        self.memory_file_watcher = MemoryFileWatcher(
            memory_manager=self.memory_manager,
            debounce_seconds=30.0,
        )
        self.memory_file_watcher.start()


        InternalActionInterface.initialize(
            self.llm,
            self.task_manager,
            self.state_manager,
            vlm_interface=self.vlm,
            memory_manager=self.memory_manager,
            context_engine=self.context_engine,
        )

        # Initialize footage callback (will be set by TUI interface later)
        self._tui_footage_callback = None

        # Only initialize GUIModule if GUI mode is globally enabled
        gui_globally_enabled = os.getenv("GUI_MODE_ENABLED", "True") == "True"
        if gui_globally_enabled:
            GUIHandler.gui_module: GUIModule = GUIModule(
                provider=llm_provider,
                action_library=self.action_library,
                action_router=self.action_router,
                context_engine=self.context_engine,
                action_manager=self.action_manager,
                event_stream_manager=self.event_stream_manager,
                tui_footage_callback=self._tui_footage_callback,
            )
            # Set gui_module reference in InternalActionInterface for GUI event stream integration
            InternalActionInterface.gui_module = GUIHandler.gui_module
        else:
            GUIHandler.gui_module = None
            InternalActionInterface.gui_module = None
            logger.info("[AGENT] GUI mode disabled - skipping GUIModule initialization")

        # ── misc ──
        self.is_running: bool = True
        self._extra_system_prompt: str = self._load_extra_system_prompt()

        # Scheduler for periodic tasks (memory processing, proactive checks, etc.)
        self.scheduler = SchedulerManager()
        InternalActionInterface.scheduler = self.scheduler

        # Proactive task manager
        proactive_file = AGENT_FILE_SYSTEM_PATH / "PROACTIVE.md"
        self.proactive_manager = initialize_proactive_manager(proactive_file)
        InternalActionInterface.proactive_manager = self.proactive_manager

        self._command_registry: Dict[str, AgentCommand] = {}
        self._register_builtin_commands()

    # =====================================
    # Commands
    # =====================================

    def _register_builtin_commands(self) -> None:
        self.register_command(
            "/reset",
            "Reset the agent state, clearing tasks, triggers, and session data.",
            self.reset_agent_state,
        )
        self.register_command(
            "/onboarding",
            "Re-run the user profile interview to update your preferences.",
            self._handle_onboarding_command,
        )

    def register_command(
        self,
        name: str,
        description: str,
        handler: Callable[[], Awaitable[str | None]],
    ) -> None:
        """
        Register an in-band command that users can invoke from chat.

        Commands are simple hooks (e.g. ``/reset``) that map to coroutine
        handlers. They are surfaced in the UI and routed via
        :meth:`get_commands`.

        Args:
            name: Command string the user types; case-insensitive.
            description: Human-readable description used in help menus.
            handler: Awaitable callable that performs the command action and
                returns an optional message to display.
        """

        self._command_registry[name.lower()] = AgentCommand(
            name=name.lower(), description=description, handler=handler
        )

    def get_commands(self) -> Dict[str, AgentCommand]:
        """Return all registered commands."""

        return self._command_registry

    # =====================================
    # Main Agent Cycle
    # =====================================
    @profile_loop
    async def react(self, trigger: Trigger) -> None:
        """
        Main agent cycle - routes to appropriate workflow handler.

        This method handles 4 distinct workflows:
        1. MEMORY: Background memory processing tasks
        2. GUI TASK: Visual interaction with screen elements
        3. COMPLEX TASK: Multi-step tasks with todo management
        4. SIMPLE TASK: Quick tasks that auto-complete
        5. CONVERSATION: No active task, handle user messages

        Args:
            trigger: The Trigger that wakes the agent up and describes
                when and why the agent should act.
        """
        session_id = trigger.session_id

        try:
            logger.debug("[REACT] starting...")

            # ----- WORKFLOW 1A: Memory Processing -----
            if self._is_memory_trigger(trigger):
                task_created = await self._handle_memory_workflow(trigger)
                if not task_created:
                    return  # No events to process
                # Task was created - return to avoid falling through to conversation mode
                # which would cause the LLM to create a duplicate task
                return

            # ----- WORKFLOW 1B: Proactive Processing (heartbeats, planners) -----
            if self._is_proactive_trigger(trigger):
                task_created = await self._handle_proactive_workflow(trigger)
                if not task_created:
                    return  # No tasks to process
                # Task was created - return to avoid falling through to conversation mode
                return

            # Initialize session for all other workflows
            trigger_data: TriggerData = self._extract_trigger_data(trigger)
            await self._initialize_session(trigger_data.gui_mode, session_id)

            # Record user message if routed from existing session via triggers.fire()
            # This ensures the LLM sees the user message in the event stream
            user_message = self._extract_user_message_from_trigger(trigger)
            if user_message:
                logger.info(f"[REACT] Recording routed user message: {user_message[:50]}...")
                # Use platform from trigger_data (already formatted by _extract_trigger_data)
                self.state_manager.record_user_message(user_message, platform=trigger_data.platform)

            # Debug: Log state after session initialization
            logger.debug(
                f"[STATE] session_id={session_id} | "
                f"current_task_id={STATE.get_agent_property('current_task_id')} | "
                f"current_task={STATE.current_task.id if STATE.current_task else None}"
            )

            # ----- WORKFLOW 2: GUI Task Mode -----
            if self._is_gui_task_mode(session_id):
                await self._handle_gui_task_workflow(trigger_data, session_id)
                return

            # ----- WORKFLOW 3: Complex Task Mode -----
            if self._is_complex_task_mode(session_id):
                await self._handle_complex_task_workflow(trigger_data, session_id)
                return

            # ----- WORKFLOW 4: Simple Task Mode -----
            if self._is_simple_task_mode(session_id):
                await self._handle_simple_task_workflow(trigger_data, session_id)
                return

            # ----- WORKFLOW 5: Conversation Mode (default) -----
            await self._handle_conversation_workflow(trigger_data, session_id)

        except Exception as e:
            await self._handle_react_error(e, None, session_id, {})
        finally:
            self._cleanup_session()

    # =====================================
    # Memory Processing
    # =====================================

    def create_process_memory_task(self) -> str:
        """
        Create a task to process unprocessed events and move them to memory.

        This creates a task that uses the 'memory-processor' skill to guide
        the agent through:
        1. Read EVENT_UNPROCESSED.md for unprocessed events
        2. Evaluate event importance for long-term memory
        3. Check for duplicate memories using memory_search
        4. Write important, unique events to MEMORY.md
        5. Clear processed events from EVENT_UNPROCESSED.md

        Returns:
            The task ID of the created task.
        """
        logger.info("[MEMORY] Creating process memory task")

        # Enable skip_unprocessed_logging to prevent infinite loops
        # (events generated during memory processing won't be added to EVENT_UNPROCESSED.md)
        # This flag is automatically reset when the task ends (in task_manager._end_task)
        self.event_stream_manager.set_skip_unprocessed_logging(True)

        # Create task using the memory-processor skill
        task_id = create_memory_processing_task(self.task_manager)
        logger.info(f"[MEMORY] Process memory task created: {task_id}")

        return task_id

    async def _process_memory_at_startup(self) -> None:
        """
        Process unprocessed events into memory at startup.

        This checks if there are unprocessed events and fires a memory
        processing trigger if needed. The trigger goes through normal
        processing flow which creates the task and executes it.
        """
        import time

        try:
            unprocessed_file = AGENT_FILE_SYSTEM_PATH / "EVENT_UNPROCESSED.md"
            if not unprocessed_file.exists():
                logger.debug("[MEMORY] EVENT_UNPROCESSED.md not found, skipping startup processing")
                return

            # Check if there are events to process (more than just headers)
            content = unprocessed_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            # Filter out empty lines and header lines (starting with # or empty)
            event_lines = [l for l in lines if l.strip() and l.strip().startswith("[")]

            if not event_lines:
                logger.info("[MEMORY] No unprocessed events found at startup")
                return

            logger.info(f"[MEMORY] Found {len(event_lines)} unprocessed events at startup, firing processing trigger")

            # Fire a memory_processing trigger (not scheduled, so won't reschedule)
            trigger = Trigger(
                fire_at=time.time(),
                priority=50,
                next_action_description="Process unprocessed events into long-term memory (startup)",
                payload={
                    "type": "memory_processing",
                    "scheduled": False,  # Don't reschedule after this
                },
                session_id="memory_processing_startup",
            )
            await self.triggers.put(trigger)

        except Exception as e:
            logger.warning(f"[MEMORY] Failed to process memory at startup: {e}")

    # Note: Daily memory processing is now handled by the SchedulerManager.
    # See app/config/scheduler_config.json for schedule configuration.

    async def _handle_memory_processing_trigger(self) -> bool:
        """
        Handle the memory processing trigger.

        This is called when a memory processing trigger fires (startup or scheduled).
        It creates a task to process unprocessed events.

        Note: Rescheduling is handled automatically by the SchedulerManager.

        Returns:
            True if a task was created and processing should continue,
            False if no task was created and react() should return.
        """
        logger.info("[MEMORY] Memory processing trigger fired")
        task_created = False

        try:
            # Check if there are events to process
            unprocessed_file = AGENT_FILE_SYSTEM_PATH / "EVENT_UNPROCESSED.md"
            if unprocessed_file.exists():
                content = unprocessed_file.read_text(encoding="utf-8")
                lines = content.strip().split("\n")
                event_lines = [l for l in lines if l.strip() and l.strip().startswith("[")]

                if event_lines:
                    logger.info(f"[MEMORY] Processing {len(event_lines)} unprocessed events")
                    self.create_process_memory_task()
                    task_created = True
                else:
                    logger.info("[MEMORY] No unprocessed events to process")
            else:
                logger.debug("[MEMORY] EVENT_UNPROCESSED.md not found")

        except Exception as e:
            logger.warning(f"[MEMORY] Failed to process memory: {e}")

        return task_created

    # =====================================
    # Workflow Routing
    # =====================================

    def _extract_trigger_data(self, trigger: Trigger) -> TriggerData:
        """Extract and structure data from trigger."""
        # Extract platform from payload (already formatted by _handle_chat_message)
        # Default to "CraftBot TUI" for local messages without platform info
        payload = trigger.payload or {}
        raw_platform = payload.get("platform", "")
        platform = raw_platform if raw_platform else "CraftBot TUI"

        return TriggerData(
            query=trigger.next_action_description,
            gui_mode=payload.get("gui_mode"),
            parent_id=payload.get("parent_action_id"),
            session_id=trigger.session_id,
            user_message=payload.get("user_message"),
            platform=platform,
            is_self_message=payload.get("is_self_message", False),
            contact_id=payload.get("contact_id", ""),
            channel_id=payload.get("channel_id", ""),
        )

    def _extract_user_message_from_trigger(self, trigger: Trigger) -> Optional[str]:
        """Extract user message that was appended by triggers.fire().

        When a message is routed to an existing session, the fire() method
        appends it as '[NEW USER MESSAGE]: {message}' to next_action_description.
        This message needs to be recorded to the event stream so the LLM can see it.

        Returns:
            The user message if found, None otherwise.
        """
        marker = "[NEW USER MESSAGE]:"
        desc = trigger.next_action_description
        if marker in desc:
            idx = desc.index(marker) + len(marker)
            return desc[idx:].strip()
        return None

    async def _initialize_session(self, gui_mode: bool | None, session_id: str) -> None:
        """Initialize the agent session and set current task ID.

        Note: Only sets current_task_id if no task is running for THIS session,
        since create_task() already sets the task_id which must be used for
        session cache lookups.
        """
        if not self.state_manager.is_running_task(session_id):
            STATE.set_agent_property("current_task_id", session_id)
        await self.state_manager.start_session(gui_mode, session_id=session_id)

    # ----- Mode Checks -----

    def _is_memory_trigger(self, trigger: Trigger) -> bool:
        """Check if trigger is for memory processing."""
        return trigger.payload.get("type") == "memory_processing"

    def _is_proactive_trigger(self, trigger: Trigger) -> bool:
        """Check if trigger is for proactive processing (heartbeat or planner)."""
        trigger_type = trigger.payload.get("type", "")
        return trigger_type in ("proactive_heartbeat", "proactive_planner")

    def _is_gui_task_mode(self, session_id: str | None = None) -> bool:
        """Check if in GUI task execution mode."""
        return self.state_manager.is_running_task(session_id=session_id) and STATE.gui_mode

    def _is_complex_task_mode(self, session_id: str | None = None) -> bool:
        """Check if running a complex task."""
        return self.state_manager.is_running_task(session_id=session_id) and not self.task_manager.is_simple_task()

    def _is_simple_task_mode(self, session_id: str | None = None) -> bool:
        """Check if running a simple task."""
        return self.state_manager.is_running_task(session_id=session_id) and self.task_manager.is_simple_task()

    # ----- Workflow Handlers -----

    async def _handle_memory_workflow(self, trigger: Trigger) -> bool:
        """
        Handle memory processing workflow.

        Args:
            trigger: The memory processing trigger.

        Returns:
            True if a task was created and processing should continue,
            False if no task was created.
        """
        return await self._handle_memory_processing_trigger()

    async def _handle_proactive_workflow(self, trigger: Trigger) -> bool:
        """
        Handle proactive heartbeat and planner triggers.

        Creates a task to process proactive tasks based on the trigger type
        (heartbeat or planner) and frequency/scope.

        Args:
            trigger: The proactive trigger

        Returns:
            True if a task was created and processing should continue,
            False if no task was created.
        """
        trigger_type = trigger.payload.get("type")
        frequency = trigger.payload.get("frequency", "")
        scope = trigger.payload.get("scope", "")

        logger.info(f"[PROACTIVE] Trigger fired: type={trigger_type}, frequency={frequency}, scope={scope}")

        try:
            if trigger_type == "proactive_heartbeat":
                return await self._handle_proactive_heartbeat(frequency)
            elif trigger_type == "proactive_planner":
                return await self._handle_proactive_planner(scope)
        except Exception as e:
            logger.warning(f"[PROACTIVE] Failed to handle proactive trigger: {e}")

        return False

    async def _handle_proactive_heartbeat(self, frequency: str) -> bool:
        """Create heartbeat processing task for the given frequency."""
        import time

        # Check if there are any tasks for this frequency
        tasks = self.proactive_manager.get_tasks(frequency=frequency, enabled_only=True)
        if not tasks:
            logger.info(f"[PROACTIVE] No {frequency} tasks enabled, skipping heartbeat")
            return False

        # Create task using heartbeat-processor skill
        task_id = self.task_manager.create_task(
            task_name=f"{frequency.title()} Heartbeat",
            task_instruction=f"Execute {frequency} proactive tasks from PROACTIVE.md. "
                           f"There are {len(tasks)} task(s) to process.",
            mode="complex",
            action_sets=["file_operations", "proactive"],
            selected_skills=["heartbeat-processor"],
        )
        logger.info(f"[PROACTIVE] Created heartbeat task: {task_id} for {frequency}")

        # Queue trigger to start the task (matching user-profile-interview pattern)
        trigger = Trigger(
            fire_at=time.time(),
            priority=50,
            next_action_description=f"Execute {frequency} proactive tasks",
            session_id=task_id,
            payload={"type": "proactive_heartbeat", "frequency": frequency},
        )
        await self.triggers.put(trigger)
        logger.info(f"[PROACTIVE] Queued trigger for heartbeat task: {task_id}")

        return True

    async def _handle_proactive_planner(self, scope: str) -> bool:
        """Create planner task for the given scope (day, week, month)."""
        import time

        skill_name = f"{scope}-planner"

        task_id = self.task_manager.create_task(
            task_name=f"{scope.title()} Planner",
            task_instruction=f"Review recent interactions and plan {scope}ly proactive activities. "
                           f"Update PROACTIVE.md planner section with findings.",
            mode="complex",
            action_sets=["file_operations", "proactive"],
            selected_skills=[skill_name],
        )
        logger.info(f"[PROACTIVE] Created planner task: {task_id} for {scope}")

        # Queue trigger to start the task (matching user-profile-interview pattern)
        trigger = Trigger(
            fire_at=time.time(),
            priority=50,
            next_action_description=f"Execute {scope} planner task",
            session_id=task_id,
            payload={"type": "proactive_planner", "scope": scope},
        )
        await self.triggers.put(trigger)
        logger.info(f"[PROACTIVE] Queued trigger for planner task: {task_id}")

        return True

    async def _handle_conversation_workflow(self, trigger_data: TriggerData, session_id: str) -> None:
        """
        Handle conversation mode - no active task.
        Routes user queries to appropriate actions (send_message, task_start, etc.)
        Uses prefix caching only (no session caching for conversation mode).
        Supports parallel task_start for starting multiple tasks at once.
        """
        logger.debug(f"[WORKFLOW: CONVERSATION] Query: {trigger_data.query}")

        # Use _select_action to maintain proper call chain
        action_decisions, reasoning = await self._select_action(trigger_data)

        prepared_actions = await self._retrieve_and_prepare_actions(
            action_decisions, trigger_data.parent_id
        )

        action_output = await self._execute_actions(
            prepared_actions, trigger_data, reasoning, session_id
        )

        new_session_id = action_output.get("task_id") or session_id
        await self._finalize_action_execution(new_session_id, action_output, session_id)

    async def _handle_simple_task_workflow(self, trigger_data: TriggerData, session_id: str) -> None:
        """
        Handle simple task mode - streamlined execution without todos.
        Quick tasks that auto-complete after delivering results.
        Uses session caching for efficient multi-turn execution.
        Supports parallel action execution for efficiency.
        """
        logger.debug(f"[WORKFLOW: SIMPLE TASK] Query: {trigger_data.query}")

        # Use _select_action to maintain proper call chain with session caching
        action_decisions, reasoning = await self._select_action(trigger_data)

        prepared_actions = await self._retrieve_and_prepare_actions(
            action_decisions, trigger_data.parent_id
        )

        action_output = await self._execute_actions(
            prepared_actions, trigger_data, reasoning, session_id
        )

        new_session_id = action_output.get("task_id") or session_id
        await self._finalize_action_execution(new_session_id, action_output, session_id)

    async def _handle_complex_task_workflow(self, trigger_data: TriggerData, session_id: str) -> None:
        """
        Handle complex task mode - full todo workflow with planning.
        Multi-step tasks with todo management and user verification.
        Uses session caching for efficient multi-turn execution.
        Supports parallel action execution for efficiency.
        """
        logger.debug(f"[WORKFLOW: COMPLEX TASK] Query: {trigger_data.query}")

        # Use _select_action to maintain proper call chain with session caching
        action_decisions, reasoning = await self._select_action(trigger_data)

        prepared_actions = await self._retrieve_and_prepare_actions(
            action_decisions, trigger_data.parent_id
        )

        action_output = await self._execute_actions(
            prepared_actions, trigger_data, reasoning, session_id
        )

        new_session_id = action_output.get("task_id") or session_id
        await self._finalize_action_execution(new_session_id, action_output, session_id)

    async def _handle_gui_task_workflow(self, trigger_data: TriggerData, session_id: str) -> None:
        """
        Handle GUI task mode - visual interaction workflow.
        Tasks requiring screen interaction via mouse/keyboard.
        """
        logger.debug("[WORKFLOW: GUI TASK] Entered GUI mode.")

        gui_response = await self._handle_gui_task_execution(trigger_data, session_id)

        await self._finalize_action_execution(
            gui_response.get("new_session_id"), gui_response.get("action_output"), session_id
        )

    # ----- GUI Task Helpers -----

    async def _handle_gui_task_execution(
        self, trigger_data: TriggerData, session_id: str
    ) -> dict:
        """
        Handle GUI mode task execution.

        Returns:
            Dictionary with action_output and new_session_id.
            Note: GUI events are now logged to main event stream directly.
        """
        current_todo = self.state_manager.get_current_todo()

        logger.debug("[GUI MODE] Entered GUI mode.")

        gui_response = await GUIHandler.gui_module.perform_gui_task_step(
            step=current_todo,
            session_id=session_id,
            next_action_description=trigger_data.query,
            parent_action_id=trigger_data.parent_id,
        )

        if gui_response.get("status") != "ok":
            raise ValueError(gui_response.get("message", "GUI task step failed"))

        action_output = gui_response.get("action_output", {})
        new_session_id = action_output.get("task_id") or session_id

        return {
            "action_output": action_output,
            "new_session_id": new_session_id,
        }

    # ----- Action Selection -----

    @profile("agent_select_action", OperationCategory.AGENT_LOOP)
    async def _select_action(self, trigger_data: TriggerData) -> tuple[list, str]:
        """
        Select action(s) based on current task state.
        Always returns a list for consistency with parallel action support.

        Routes to appropriate action selection method:
        - Complex task: _select_action_in_task (with session caching)
        - Simple task: _select_action_in_simple_task (with session caching)
        - Conversation: action_router.select_action (prefix caching only)

        Returns:
            Tuple of (action_decisions_list, reasoning) where reasoning is empty string
            for non-task contexts.
        """
        # CRITICAL: Use session_id to check THIS specific session's task state
        # Without session_id, checks global state which could be wrong in concurrent tasks
        is_running_task = self.state_manager.is_running_task(session_id=trigger_data.session_id)

        if is_running_task:
            # Check task mode - simple tasks use streamlined action selection
            if self.task_manager.is_simple_task():
                return await self._select_action_in_simple_task(trigger_data.query, trigger_data.session_id)
            else:
                return await self._select_action_in_task(trigger_data.query, trigger_data.session_id)
        else:
            logger.debug(f"[AGENT QUERY] {trigger_data.query}")
            action_decisions = await self.action_router.select_action(query=trigger_data.query)
            if not action_decisions:
                raise ValueError("Action router returned no decision.")
            # Extract reasoning from first action (shared across all)
            reasoning = action_decisions[0].get("reasoning", "") if action_decisions else ""
            return action_decisions, reasoning

    @profile("agent_select_action_in_task", OperationCategory.AGENT_LOOP)
    async def _select_action_in_task(self, query: str, session_id: str | None = None) -> tuple[list, str]:
        """
        Select action(s) when running within a task context.
        Supports parallel action selection - returns a list of actions.

        Reasoning is now integrated into the action selection prompt,
        so this method directly calls the action router without a separate
        reasoning step.

        Args:
            query: The query/instruction for action selection.
            session_id: Session ID for session-specific state lookup.

        Returns:
            Tuple of (action_decisions_list, reasoning)
        """
        # Single LLM call - reasoning is integrated into action selection
        # Returns List[Dict] for parallel action support
        action_decisions = await self.action_router.select_action_in_task(
            query=query,
            GUI_mode=STATE.gui_mode,
            session_id=session_id,
        )

        if not action_decisions:
            raise ValueError("Action router returned no decision.")

        # Extract reasoning from the first action decision (shared across all)
        reasoning = action_decisions[0].get("reasoning", "") if action_decisions else ""
        logger.debug(f"[AGENT REASONING] {reasoning}")

        # Log reasoning to event stream (pass task_id for multi-task isolation)
        if self.event_stream_manager and reasoning:
            self.event_stream_manager.log(
                "agent reasoning",
                reasoning,
                severity="DEBUG",
                display_message=None,
                task_id=session_id,
            )
            self.state_manager.bump_event_stream()

        return action_decisions, reasoning

    @profile("agent_select_action_in_simple_task", OperationCategory.AGENT_LOOP)
    async def _select_action_in_simple_task(self, query: str, session_id: str | None = None) -> tuple[list, str]:
        """
        Select action(s) for simple task mode - lighter weight than complex task.
        Supports parallel action selection - returns a list of actions.

        Reasoning is now integrated into the action selection prompt.
        Simple tasks use streamlined prompts and no todo workflow.
        They auto-end after delivering results.

        Args:
            query: The query/instruction for action selection.
            session_id: Session ID for session-specific state lookup.

        Returns:
            Tuple of (action_decisions_list, reasoning)
        """
        # Single LLM call - reasoning is integrated into action selection
        # Returns List[Dict] for parallel action support
        action_decisions = await self.action_router.select_action_in_simple_task(
            query=query,
            session_id=session_id,
        )

        if not action_decisions:
            raise ValueError("Action router returned no decision.")

        # Extract reasoning from the first action decision (shared across all)
        reasoning = action_decisions[0].get("reasoning", "") if action_decisions else ""
        logger.debug(f"[AGENT REASONING - SIMPLE TASK] {reasoning}")

        # Log reasoning to event stream (pass task_id for multi-task isolation)
        if self.event_stream_manager and reasoning:
            self.event_stream_manager.log(
                "agent reasoning",
                reasoning,
                severity="DEBUG",
                display_message=None,
                task_id=session_id,
            )
            self.state_manager.bump_event_stream()

        return action_decisions, reasoning

    # ----- Action Execution -----

    async def _retrieve_and_prepare_actions(
        self, action_decisions: list, initial_parent_id: str | None
    ) -> list:
        """
        Retrieve actions from library for a list of action decisions.

        Args:
            action_decisions: List of action decision dicts from router.
            initial_parent_id: Parent action ID for tracking.

        Returns:
            List of Tuple (action, action_params, parent_id)
        """
        prepared = []
        for decision in action_decisions:
            action_name = decision.get("action_name")
            action_params = decision.get("parameters", {})

            if not action_name:
                continue

            action = self.action_library.retrieve_action(action_name)
            if action is None:
                logger.warning(f"Action '{action_name}' not found, skipping")
                continue

            prepared.append((action, action_params, initial_parent_id))

        return prepared

    @profile("agent_execute_actions", OperationCategory.AGENT_LOOP)
    async def _execute_actions(
        self,
        prepared_actions: list,
        trigger_data: TriggerData,
        reasoning: str,
        session_id: str,
    ) -> dict:
        """
        Execute prepared actions (parallel if multiple).

        Each action logs its own results to event stream via execute_action().
        Returns merged output for agent loop control.
        """
        if not prepared_actions:
            raise ValueError("No valid actions to execute")

        is_running_task = self.state_manager.is_running_task(session_id=session_id)
        context = reasoning if reasoning else trigger_data.query
        parent_id = prepared_actions[0][2] if prepared_actions else None

        # Build list of (action, input_data) tuples
        actions_with_input = [(action, params) for action, params, _ in prepared_actions]

        # Inject original user message and platform for task_start actions
        # Use user_message from payload (original message) if available,
        # otherwise fall back to query (may include routing prefix)
        for action, params in actions_with_input:
            if action.name == "task_start":
                params["_original_query"] = trigger_data.user_message or trigger_data.query
                params["_original_platform"] = trigger_data.platform

        action_names = [a[0].name for a in actions_with_input]
        logger.info(f"[ACTION] Ready to run {len(actions_with_input)} action(s): {action_names}")

        # Execute actions (parallel if multiple)
        results = await self.action_manager.execute_actions_parallel(
            actions=actions_with_input,
            context=context,
            event_stream=STATE.event_stream,
            parent_id=parent_id,
            session_id=session_id,
            is_running_task=is_running_task,
        )

        return self._merge_action_outputs(results)

    def _merge_action_outputs(self, outputs: list) -> dict:
        """
        Merge outputs from parallel actions into single response.

        Preserves all individual results and extracts key fields for loop control.
        """
        if not outputs:
            return {}
        if len(outputs) == 1:
            return outputs[0]

        merged = {
            "parallel_results": outputs,
            "task_id": None,
            "fire_at_delay": 0.0,
        }

        # Extract task_id if any action created one
        for output in outputs:
            if output.get("task_id"):
                merged["task_id"] = output["task_id"]
                break

        # Use max fire_at_delay
        merged["fire_at_delay"] = max(
            (output.get("fire_at_delay", 0.0) for output in outputs), default=0.0
        )

        # Check for errors
        errors = [o for o in outputs if o.get("status") == "error"]
        if errors:
            merged["has_errors"] = True
            merged["error_count"] = len(errors)

        return merged

    async def _finalize_action_execution(
        self, new_session_id: str, action_output: dict, session_id: str
    ) -> None:
        """Handle post-action cleanup and trigger scheduling."""
        self.state_manager.bump_event_stream()
        if not await self._check_agent_limits():
            return

        # Check if parallel actions created multiple tasks
        parallel_results = action_output.get("parallel_results")
        if parallel_results:
            # Collect all task_ids from parallel task_start results
            new_task_ids = [
                r.get("task_id") for r in parallel_results
                if r.get("task_id") and r.get("status") == "success"
            ]
            # Create a trigger for each newly created task
            for task_id in new_task_ids:
                await self._create_new_trigger(task_id, action_output, STATE)

            # Always create trigger for the original session to continue current task
            # This ensures the task keeps running regardless of what parallel actions did
            await self._create_new_trigger(session_id, action_output, STATE)
        else:
            # Single action - use existing logic
            await self._create_new_trigger(new_session_id, action_output, STATE)

    # ----- Error Handling -----

    async def _handle_react_error(
        self,
        error: Exception,
        new_session_id: str | None,
        session_id: str,
        action_output: dict,
    ) -> None:
        """Handle errors during react execution."""
        tb = traceback.format_exc()
        logger.error(f"[REACT ERROR] {error}\n{tb}")

        session_to_use = new_session_id or session_id
        if not session_to_use or not self.event_stream_manager:
            return

        try:
            logger.debug("[REACT ERROR] Logging to event stream")
            self.event_stream_manager.log(
                "error",
                f"[REACT] {type(error).__name__}: {error}\n{tb}",
                display_message=None,
                task_id=session_to_use,
            )
            self.state_manager.bump_event_stream()
            await self._create_new_trigger(session_to_use, action_output, STATE)
        except Exception as e:
            logger.error(
                "[REACT ERROR] Failed to log to event stream or create trigger",
                exc_info=True,
            )

    # ----- Session Management -----

    def _cleanup_session(self) -> None:
        """Safely cleanup session state."""
        try:
            self.state_manager.clean_state()
        except Exception as e:
            logger.warning(f"[REACT] Failed to end session safely: {e}")

    # ----- Agent Limits -----

    async def _check_agent_limits(self) -> bool:
        agent_properties = STATE.get_agent_properties()
        action_count: int = agent_properties.get("action_count", 0)
        max_actions: int = agent_properties.get("max_actions_per_task", 0)
        token_count: int = agent_properties.get("token_count", 0)
        max_tokens: int = agent_properties.get("max_tokens_per_task", 0)
        current_task_id: str = agent_properties.get("current_task_id", "")

        # Check action limits
        if (action_count / max_actions) >= 1.0:
            # Log warning BEFORE cancelling task (stream is removed during cancel)
            if self.event_stream_manager:
                self.event_stream_manager.log(
                    "warning",
                    f"Action limit reached: 100% of the maximum actions ({max_actions} actions) has been used. Aborting task.",
                    display_message=f"Action limit reached: 100% of the maximum ({max_actions} actions) has been used. Aborting task.",
                    task_id=current_task_id,
                )
                self.state_manager.bump_event_stream()
            response = await self.task_manager.mark_task_cancel(reason=f"Task reached the maximum actions allowed limit: {max_actions}")
            task_cancelled: bool = response
            return not task_cancelled
        elif (action_count / max_actions) >= 0.8:
            if self.event_stream_manager:
                self.event_stream_manager.log(
                    "warning",
                    f"Action limit nearing: 80% of the maximum actions ({max_actions} actions) has been used. "
                    "Consider wrapping up the task or informing the user that the task may be too complex. "
                    "If necessary, mark the task as aborted to prevent premature termination.",
                    display_message=None,
                    task_id=current_task_id,
                )
                self.state_manager.bump_event_stream()
                return True

        # Check token limits
        if (token_count / max_tokens) >= 1.0:
            # Log warning BEFORE cancelling task (stream is removed during cancel)
            if self.event_stream_manager:
                self.event_stream_manager.log(
                    "warning",
                    f"Token limit reached: 100% of the maximum tokens ({max_tokens} tokens) has been used. Aborting task.",
                    display_message=f"Token limit reached: 100% of the maximum ({max_tokens} tokens) has been used. Aborting task.",
                    task_id=current_task_id,
                )
                self.state_manager.bump_event_stream()
            response = await self.task_manager.mark_task_cancel(reason=f"Task reached the maximum tokens allowed limit: {max_tokens}")
            task_cancelled: bool = response
            return not task_cancelled
        elif (token_count / max_tokens) >= 0.8:
            if self.event_stream_manager:
                self.event_stream_manager.log(
                    "warning",
                    f"Token limit nearing: 80% of the maximum tokens ({max_tokens} tokens) has been used. "
                    "Consider wrapping up the task or informing the user that the task may be too complex. "
                    "If necessary, mark the task as aborted to prevent premature termination.",
                    display_message=None,
                    task_id=current_task_id,
                )
                self.state_manager.bump_event_stream()
                return True

        # No limits close or reached
        return True

    # ----- Trigger Management -----

    async def _cleanup_session_triggers(self, session_id: str) -> None:
        """
        Remove all triggers associated with a session when its task ends.

        This callback is invoked by TaskManager when a task completes, errors,
        or is cancelled, ensuring that stale triggers no longer appear as
        "ACTIVE" in the routing prompt.

        Args:
            session_id: The task/session ID whose triggers should be removed.
        """
        try:
            await self.triggers.remove_sessions([session_id])
            logger.debug(f"[TRIGGER] Cleaned up triggers for session={session_id}")
        except Exception as e:
            logger.warning(f"[TRIGGER] Failed to cleanup triggers for session={session_id}: {e}")

    @profile("agent_create_new_trigger", OperationCategory.TRIGGER)
    async def _create_new_trigger(self, new_session_id, action_output, STATE):
        """
        Schedule a follow-up trigger when a task is ongoing.

        This helper inspects the current task state and enqueues a new trigger
        so the agent can continue multi-step executions. It is defensive by
        design so failures do not interrupt the main ``react`` loop.

        Args:
            new_session_id: Session identifier to continue.
            action_output: Result dictionary returned by the previous action
                execution; may contain timing metadata.
            state_session: The current :class:`StateSession` object, used to
                propagate session context and payload.
        """
        try:
            # CRITICAL: Pass session_id to is_running_task() to check THIS specific task
            # Without session_id, it checks global state which could be wrong in concurrent tasks
            if not self.state_manager.is_running_task(session_id=new_session_id):
                # Nothing to schedule if no task is running for THIS session
                logger.debug(f"[TRIGGER] No task running for session {new_session_id}, skipping trigger creation")
                return

            # Delay logic
            fire_at_delay = 0.0
            try:
                fire_at_delay = float(action_output.get("fire_at_delay", 0.0))
            except Exception:
                logger.error("[TRIGGER] Invalid fire_at_delay in action_output. Using 0.0", exc_info=True)

            fire_at = time.time() + fire_at_delay

            logger.debug(f"[TRIGGER] Creating new trigger for session: {new_session_id}")

            # Build and enqueue trigger safely
            try:
                await self.triggers.put(
                    Trigger(
                        fire_at=fire_at,
                        priority=5,
                        next_action_description="Perform the next best action for the task based on the todos and event stream",
                        session_id=new_session_id,
                        payload={
                            "gui_mode": STATE.gui_mode,
                        },
                    ),
                    skip_merge=True,  # Session is already explicitly set, no LLM merge check needed
                )
            except Exception as e:
                logger.error(f"[TRIGGER] Failed to enqueue trigger for session {new_session_id}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"[TRIGGER] Unexpected error in create_new_trigger: {e}", exc_info=True)

    # ----- Chat Handling -----

    def _format_sessions_for_routing(
        self,
        active_task_ids: List[str],
        triggers: Optional[List[Trigger]] = None
    ) -> str:
        """Format active sessions with rich context for routing prompt.

        Uses active task IDs from state_manager (not just triggers in queue) to ensure
        all running tasks are visible for routing decisions.

        Args:
            active_task_ids: List of task IDs from state_manager.main_state.active_task_ids
            triggers: Optional list of triggers (used to check waiting_for_reply status)

        Returns:
            Formatted string with session context for routing decisions.
        """
        if not active_task_ids:
            return "No existing sessions."

        # Build a lookup of triggers by session_id for waiting_for_reply status
        trigger_map = {}
        if triggers:
            for tr in triggers:
                if tr.session_id:
                    trigger_map[tr.session_id] = tr

        sections = []
        for i, task_id in enumerate(active_task_ids, 1):
            task = self.task_manager.tasks.get(task_id) if self.task_manager else None
            trigger = trigger_map.get(task_id)

            # Check waiting_for_reply from trigger OR from task state
            is_waiting = False
            if trigger and trigger.waiting_for_reply:
                is_waiting = True
            if task and hasattr(task, 'waiting_for_user_reply') and task.waiting_for_user_reply:
                is_waiting = True

            status = "WAITING FOR REPLY" if is_waiting else "ACTIVE"
            platform = trigger.payload.get("platform", "default") if trigger else "default"

            lines = [
                f"--- Session {i} ---",
                f"Session ID: {task_id}",
                f"Status: {status}",
            ]

            if task:
                lines.extend([
                    f"Task Name: \"{task.name}\"",
                    f"Original Request: \"{task.instruction}\"",
                    f"Mode: {task.mode}",
                    f"Created: {task.created_at}",
                ])

                # Todo progress
                if task.todos:
                    completed = sum(1 for t in task.todos if t.status == "completed")
                    in_progress_todo = next(
                        (t for t in task.todos if t.status == "in_progress"), None
                    )
                    lines.append(f"Progress: {completed}/{len(task.todos)} todos completed")
                    if in_progress_todo:
                        lines.append(f"Currently working on: \"{in_progress_todo.content}\"")

                # Get recent events from event stream for this task
                if self.event_stream_manager and task_id:
                    stream = self.event_stream_manager.get_stream_by_id(task_id)
                    if stream and stream.tail_events:
                        # Get last 10 events for better routing context
                        # (5 was insufficient - file creation events were missed)
                        recent_events = stream.tail_events[-10:]
                        lines.append("Recent Activity:")
                        for rec in recent_events:
                            # Only truncate very long event messages (500+ chars)
                            # Short truncation caused loss of important context like file paths
                            event_line = rec.compact_line()
                            if len(event_line) > 500:
                                event_line = event_line[:497] + "..."
                            lines.append(f"  - {event_line}")
            else:
                # Fallback to trigger description if no task found
                desc = trigger.next_action_description if trigger else "Unknown task"
                lines.append(f"Description: \"{desc}\"")

            lines.append(f"Platform: {platform}")

            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    async def _route_to_session(
        self,
        item_type: str,
        item_content: str,
        existing_sessions: str,
        source_platform: str = "default",
    ) -> Dict[str, Any]:
        """Route incoming item to appropriate session using unified prompt.

        Args:
            item_type: Type of incoming item ("message" or "trigger")
            item_content: The content of the message or trigger description
            existing_sessions: Formatted string of existing sessions
            source_platform: The platform the message came from (e.g., "cli", "gui")

        Returns:
            Dict with routing decision containing:
            - action: "route" | "new"
            - session_id: The session to route to (or "new")
            - reason: Explanation of the routing decision
        """
        prompt = ROUTE_TO_SESSION_PROMPT.format(
            item_type=item_type,
            item_content=item_content,
            source_platform=source_platform,
            existing_sessions=existing_sessions,
        )

        logger.debug(f"[UNIFIED ROUTING PROMPT]:\n{prompt}")
        response = await self.llm.generate_response_async(
            system_prompt="You are a session routing system.",
            user_prompt=prompt,
        )
        logger.debug(f"[UNIFIED ROUTING RESPONSE]: {response}")

        try:
            result = json.loads(response)
            # Ensure action field exists for backward compatibility
            if "action" not in result:
                result["action"] = "route" if result.get("session_id", "new") != "new" else "new"
            return result
        except json.JSONDecodeError:
            logger.error("[ROUTING] Failed to parse routing response JSON")
            return {"action": "new", "session_id": "new", "reason": "Failed to parse routing response"}

    async def _handle_chat_message(self, payload: Dict):
        try:
            user_input: str = payload.get("text", "")
            if not user_input:
                logger.warning("Received empty message.")
                return

            chat_content = user_input
            logger.info(f"[CHAT RECEIVED] {chat_content}")
            gui_mode = payload.get("gui_mode")

            # Determine platform - use payload's platform if available, otherwise default
            # External messages (WhatsApp, Telegram, etc.) have platform set by _handle_external_event
            # TUI/CLI messages don't have platform in payload, so use "CraftBot TUI"
            if payload.get("platform"):
                # External message - capitalize for display (e.g., "whatsapp" -> "Whatsapp")
                platform = payload["platform"].capitalize()
            else:
                # Local TUI/CLI message
                platform = "CraftBot TUI"

            # Check active tasks — route message to matching session if possible
            # Use active_task_ids from state_manager (not just triggers in queue) to ensure
            # all running tasks are visible for routing, not just those waiting in queue
            active_task_ids = self.state_manager.get_main_state().active_task_ids
            triggers = await self.triggers.list_triggers()  # Still get triggers for waiting_for_reply status

            if active_task_ids:
                # Use unified routing prompt with rich task context
                existing_sessions = self._format_sessions_for_routing(active_task_ids, triggers)
                routing_result = await self._route_to_session(
                    item_type="message",
                    item_content=chat_content,
                    existing_sessions=existing_sessions,
                    source_platform=platform,
                )

                action = routing_result.get("action", "new")

                if action == "route":
                    matched_session_id = routing_result.get("session_id", "new")
                    if matched_session_id != "new":
                        # Fire the matched trigger so it gets priority,
                        # and attach the new user message so react() sees it.
                        if not await self.triggers.fire(
                            matched_session_id, message=chat_content
                        ):
                            logger.warning(
                                f"[CHAT] Trigger for session_id {matched_session_id} not found, creating new."
                            )
                        else:
                            logger.info(
                                f"[CHAT] Routed message to existing session {matched_session_id} "
                                f"(reason: {routing_result.get('reason', 'N/A')})"
                            )
                            return

            # No existing triggers matched or action == "new" — create a fresh session
            await self.state_manager.start_session(gui_mode)
            self.state_manager.record_user_message(chat_content, platform=platform)

            # skip_merge=True because we already did routing above
            trigger_payload = {
                "gui_mode": gui_mode,
                "platform": platform,
                "user_message": chat_content,  # Original user message for task event stream
            }
            # Carry external message context for platform-aware routing
            if payload.get("external_event"):
                trigger_payload["is_self_message"] = payload.get("is_self_message", False)
                trigger_payload["contact_id"] = payload.get("contact_id", "")
                trigger_payload["channel_id"] = payload.get("channel_id", "")

            # Include platform in the action description so the LLM picks
            # the correct platform-specific send action for replies.
            # Must be directive (not just informational) for weaker LLMs.
            platform_hint = ""
            if platform and platform.lower() != "craftbot tui":
                platform_hint = f" from {platform} (reply on {platform}, NOT send_message)"

            await self.triggers.put(
                Trigger(
                    fire_at=time.time(),
                    priority=1,
                    next_action_description=(
                        "Please perform action that best suit this user chat "
                        f"you just received{platform_hint}: {chat_content}"
                    ),
                    session_id=str(uuid.uuid4()),  # Generate unique session ID
                    payload=trigger_payload,
                ),
                skip_merge=True,
            )

        except Exception as e:
            logger.error(f"Error handling incoming message: {e}", exc_info=True)

    async def _handle_external_event(self, payload: Dict) -> None:
        """
        Handle an incoming external tool event (WhatsApp, Telegram, etc.).

        Self-messages (user messaging themselves) are treated as direct user
        input to the agent.  Messages from other people are wrapped as
        notifications so the agent asks the user what to do.

        Args:
            payload: Event payload with standardized fields:
                - source: Platform name (e.g., "Telegram", "WhatsApp Web")
                - integrationType: Integration type (e.g., "telegram_bot", "whatsapp_web")
                - contactId: Contact/chat ID
                - contactName: Contact name
                - messageBody: Message text
                - is_self_message: True when the user sent themselves a message
        """
        try:
            source = payload.get("source", "Unknown")
            contact_id = payload.get("contactId", "unknown")
            contact_name = payload.get("contactName") or contact_id
            message_body = payload.get("messageBody", "")
            integration_type = payload.get("integrationType", "").lower()
            is_self_message = payload.get("is_self_message", False)

            if not message_body:
                logger.warning(f"[EXTERNAL] Empty message body from {source}, ignoring.")
                return

            channel_id = payload.get("channelId", "")
            channel_name = payload.get("channelName", "")

            logger.info(
                f"[EXTERNAL] Received from {source} ({integration_type}): "
                f"{contact_name}: {message_body[:100]}... "
                f"(channel={channel_name or channel_id}, self={is_self_message})"
            )

            # Map integration type to platform for routing
            platform_map = {
                "whatsapp_web": "whatsapp",
                "whatsapp_business": "whatsapp",
                "telegram_bot": "telegram",
                "telegram_user": "telegram",
                "telegram_mtproto": "telegram",
                "slack": "slack",
                "discord": "discord",
                "linkedin": "linkedin",
                "notion": "notion",
                "outlook": "outlook",
                "google_workspace": "google",
                "gmail": "google",
            }
            source_platform = platform_map.get(integration_type, source.lower())

            # Build message context for payload (useful for downstream processing)
            message_context = {
                "platform": source_platform,
                "integration_type": integration_type,
                "contact_id": contact_id,
                "contact_name": contact_name,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "is_self_message": is_self_message,
            }

            # Build a location string (channel/server context)
            location_parts = []
            if channel_name:
                location_parts.append(channel_name)
            elif channel_id:
                location_parts.append(f"channel {channel_id}")
            location_str = f" in {' / '.join(location_parts)}" if location_parts else ""

            if is_self_message:
                # Self-message = user is directly talking to the agent.
                # Pass message body as-is (like a normal chat input).
                event_content = message_body
            else:
                # Someone else sent a message — notify the agent so it can
                # ask the user what to do about it.
                event_content = (
                    f"[Incoming {source} message from {contact_name} ({contact_id}){location_str}]: "
                    f"\"{message_body}\"\n\n"
                    f"A new message was received on {source} from {contact_name}{location_str}. "
                    f"Ask the user what they would like to do about this message. "
                    f"Present the message content and wait for instructions."
                )

            # Route through the existing chat message handler
            await self._handle_chat_message({
                "text": event_content,
                "gui_mode": False,
                "platform": source_platform,
                "external_event": True,
                "is_self_message": is_self_message,
                "contact_id": contact_id,
                "contact_name": contact_name,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "message_context": message_context,
            })

        except Exception as e:
            logger.error(f"Error handling external event: {e}", exc_info=True)

    # =====================================
    # Hooks
    # =====================================

    def _load_extra_system_prompt(self) -> str:
        """
        Sub-classes may override to return a *role-specific* system-prompt
        fragment that is **prepended** to the standard one.
        """
        return ""
    
    def _generate_role_info_prompt(self) -> str:
        """
        Subclasses override this to return role-specific system instructions
        (responsibilities, behaviour constraints, expected domain tasks, etc).
        """
        return "You are a general computer-use AI agent that can switch between CLI/GUI mode."

    def _build_db_interface(self, *, data_dir: str, chroma_path: str):
        """A tiny wrapper so a subclass can point to another DB/collection."""
        return DatabaseInterface(
            data_dir = data_dir, chroma_path=chroma_path
        )

    # =====================================
    # State Management
    # =====================================

    async def reset_agent_state(self) -> str:
        """
        Reset runtime state so the agent behaves like a fresh instance.

        Clears triggers, resets task and state managers, purges event
        streams, and reinitializes the agent file system from templates.

        Returns:
            Confirmation message summarizing the reset.
        """
        # 1. Clear runtime state
        await self.triggers.clear()
        self.task_manager.reset()
        self.state_manager.reset()
        self.event_stream_manager.clear_all()

        # 2. Stop file watcher to prevent interference during reset
        if hasattr(self, 'memory_file_watcher') and self.memory_file_watcher.is_running:
            self.memory_file_watcher.stop()

        # 3. Reinitialize agent file system from templates
        await self._reset_agent_file_system()

        # 4. Clear and rebuild memory index
        if hasattr(self, 'memory_manager'):
            self.memory_manager.clear()
            self.memory_manager.update()

        # 5. Restart file watcher
        if hasattr(self, 'memory_file_watcher'):
            self.memory_file_watcher.start()

        return "Agent state reset. Agent file system reinitialized."

    async def _reset_agent_file_system(self) -> None:
        """
        Reset agent file system by copying fresh templates.
        Clears all markdown files and workspace contents, then copies
        fresh templates from the template directory.
        """
        # Run blocking file operations in a thread to avoid freezing the UI
        await asyncio.to_thread(self._reset_agent_file_system_sync)

    def _reset_agent_file_system_sync(self) -> None:
        """
        Synchronous helper for file system reset operations.
        Called via asyncio.to_thread() to avoid blocking the event loop.
        """
        template_path = AGENT_FILE_SYSTEM_TEMPLATE_PATH
        target_path = AGENT_FILE_SYSTEM_PATH

        if not template_path.exists():
            logger.error(f"[RESET] Template path does not exist: {template_path}")
            raise FileNotFoundError(f"Template path not found: {template_path}")

        # Clear existing markdown files
        for md_file in target_path.glob("*.md"):
            try:
                md_file.unlink()
                logger.debug(f"[RESET] Removed {md_file.name}")
            except Exception as e:
                logger.warning(f"[RESET] Failed to remove {md_file}: {e}")

        # Clear workspace directory contents
        workspace_path = target_path / "workspace"
        if workspace_path.exists():
            for item in workspace_path.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                except Exception as e:
                    logger.warning(f"[RESET] Failed to remove workspace item {item}: {e}")
        else:
            workspace_path.mkdir(parents=True, exist_ok=True)

        # Copy fresh templates
        for template_file in template_path.glob("*.md"):
            dest = target_path / template_file.name
            shutil.copy2(template_file, dest)
            logger.debug(f"[RESET] Copied template {template_file.name}")

        # Ensure workspace directory exists
        if not workspace_path.exists():
            workspace_path.mkdir(parents=True, exist_ok=True)

        logger.info("[RESET] Agent file system reinitialized from templates")

    async def trigger_soft_onboarding(self, reset: bool = False) -> Optional[str]:
        """
        Trigger soft onboarding interview task.

        This method centralizes soft onboarding logic so interfaces don't need
        to contain agent logic.

        Args:
            reset: If True, reset soft onboarding state first (for /onboarding command)

        Returns:
            Task ID if created, None if not needed or already in progress
        """
        from app.onboarding import onboarding_manager
        from app.onboarding.soft.task_creator import create_soft_onboarding_task
        from app.trigger import Trigger
        import time

        if reset:
            onboarding_manager.reset_soft_onboarding()

        # Create interview task
        task_id = create_soft_onboarding_task(self.task_manager)

        # Fire trigger to start the task
        trigger = Trigger(
            fire_at=time.time(),
            priority=1,
            next_action_description="Begin user profile interview",
            session_id=task_id,
            payload={"onboarding": True},
        )
        await self.triggers.put(trigger)

        logger.info(f"[ONBOARDING] Triggered soft onboarding task: {task_id}")
        return task_id

    async def _handle_onboarding_command(self) -> str:
        """
        Handle the /onboarding command to re-run soft onboarding.

        Returns:
            Message indicating the interview is starting.
        """
        await self.trigger_soft_onboarding(reset=True)
        return "Starting user profile interview. I'll ask you some questions to personalize your experience."

    def _parse_reasoning_response(self, response: str) -> ReasoningResult:
        """
        Parse and validate the structured JSON response from the reasoning LLM call.
        """
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned invalid JSON: {response}") from e

        if not isinstance(parsed, dict):
            raise ValueError(f"LLM response is not a JSON object: {parsed}")

        reasoning = parsed.get("reasoning")
        action_query = parsed.get("action_query")

        if not isinstance(reasoning, str) or not isinstance(action_query, str):
            raise ValueError(f"Invalid reasoning schema: {parsed}")

        return ReasoningResult(
            reasoning=reasoning,
            action_query=action_query,
        )

    # =====================================
    # Initialization
    # =====================================

    def reinitialize_llm(self, provider: str | None = None) -> bool:
        """Reinitialize LLM and VLM interfaces with updated configuration.

        Call this after updating environment variables with new API keys.

        Args:
            provider: Optional provider to switch to. If None, uses current provider.

        Returns:
            True if both LLM and VLM were initialized successfully.
        """
        llm_ok = self.llm.reinitialize(provider)
        vlm_ok = self.vlm.reinitialize(provider)

        if llm_ok and vlm_ok:
            logger.info(f"[AGENT] LLM and VLM reinitialized with provider: {self.llm.provider}")
            # Update GUI module provider if needed (only if GUI mode is enabled)
            gui_globally_enabled = os.getenv("GUI_MODE_ENABLED", "True") == "True"
            if gui_globally_enabled and hasattr(self, 'action_library') and hasattr(GUIHandler, 'gui_module'):
                GUIHandler.gui_module = GUIModule(
                    provider=self.llm.provider,
                    action_library=self.action_library,
                    action_router=self.action_router,
                    context_engine=self.context_engine,
                    action_manager=self.action_manager,
                    event_stream_manager=self.event_stream_manager,
                    tui_footage_callback=self._tui_footage_callback,
                )
        return llm_ok and vlm_ok

    @property
    def is_llm_initialized(self) -> bool:
        """Check if the LLM interface is properly initialized."""
        return self.llm.is_initialized

    # =====================================
    # MCP Integration
    # =====================================

    async def _initialize_mcp(self) -> None:
        """
        Initialize MCP (Model Context Protocol) client and register tools as actions.

        This method:
        1. Loads MCP configuration from app/config/mcp_config.json
        2. Connects to enabled MCP servers
        3. Discovers tools from each connected server
        4. Registers tools as actions in the ActionRegistry

        MCP tools become available as action sets (e.g., mcp_filesystem) that
        can be selected during task creation.
        """
        try:
            from app.mcp import mcp_client
            from app.config import PROJECT_ROOT

            config_path = PROJECT_ROOT / "app" / "config" / "mcp_config.json"

            if not config_path.exists():
                logger.info(f"[MCP] No MCP config found at {config_path}, skipping MCP initialization")
                return

            logger.info(f"[MCP] Loading config from {config_path}")

            # Initialize MCP client (loads config and connects to servers)
            await mcp_client.initialize(config_path)

            # Log connection status before registering
            status = mcp_client.get_status()
            connected_count = sum(1 for s in status.get("servers", {}).values() if s.get("connected"))
            total_servers = len(status.get("servers", {}))
            logger.info(f"[MCP] Connected to {connected_count}/{total_servers} servers")

            for server_name, server_info in status.get("servers", {}).items():
                if server_info.get("connected"):
                    logger.info(
                        f"[MCP] Server '{server_name}': {server_info['tool_count']} tools available"
                    )

            # Register MCP tools as actions
            tool_count = mcp_client.register_tools_as_actions()

            if tool_count > 0:
                logger.info(
                    f"[MCP] Successfully registered {tool_count} MCP tools as actions"
                )
            else:
                # Provide more detailed diagnostics
                if not mcp_client.servers:
                    logger.warning("[MCP] No MCP servers connected - check if Node.js/npx is installed")
                else:
                    for name, server in mcp_client.servers.items():
                        if not server.is_connected:
                            logger.warning(f"[MCP] Server '{name}' failed to connect")
                        elif not server.tools:
                            logger.warning(f"[MCP] Server '{name}' connected but has no tools")

        except ImportError as e:
            logger.warning(f"[MCP] MCP module not available: {e}")
        except Exception as e:
            import traceback
            logger.warning(f"[MCP] Failed to initialize MCP: {e}")
            logger.debug(f"[MCP] Traceback: {traceback.format_exc()}")

    async def _shutdown_mcp(self) -> None:
        """Gracefully disconnect from all MCP servers."""
        try:
            from app.mcp import mcp_client
            await mcp_client.disconnect_all()
            logger.info("[MCP] Disconnected from all MCP servers")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"[MCP] Error during MCP shutdown: {e}")

    # =====================================
    # Skills Integration
    # =====================================

    async def _initialize_skills(self) -> None:
        """
        Initialize the skills system and discover available skills.

        This method:
        1. Loads skills configuration from app/config/skills_config.json
        2. Discovers skills from global (~/.whitecollar/skills/) and project directories
        3. Makes skills available for automatic selection during task creation

        Skills provide specialized instructions that are injected into context
        when selected for a task.
        """
        try:
            from app.skill import skill_manager
            from app.config import PROJECT_ROOT

            config_path = PROJECT_ROOT / "app" / "config" / "skills_config.json"

            logger.info(f"[SKILLS] Loading config from {config_path}")

            # Initialize skill manager (loads config and discovers skills)
            await skill_manager.initialize(config_path)

            # Log discovered skills
            status = skill_manager.get_status()
            total_skills = status.get("total_skills", 0)
            enabled_skills = status.get("enabled_skills", 0)

            if total_skills > 0:
                logger.info(f"[SKILLS] Discovered {total_skills} skills ({enabled_skills} enabled)")
                for skill_name, skill_info in status.get("skills", {}).items():
                    if skill_info.get("enabled"):
                        logger.debug(f"[SKILLS] - {skill_name}: {skill_info.get('description', 'No description')}")
            else:
                logger.info("[SKILLS] No skills discovered. Create skills in ~/.whitecollar/skills/ or .whitecollar/skills/")

        except ImportError as e:
            logger.warning(f"[SKILLS] Skill module not available: {e}")
        except Exception as e:
            import traceback
            logger.warning(f"[SKILLS] Failed to initialize skills: {e}")
            logger.debug(f"[SKILLS] Traceback: {traceback.format_exc()}")

    # =====================================
    # External Libraries
    # =====================================

    async def _initialize_external_libraries(self) -> None:
        """Import all platform modules so their @register_client decorators fire."""
        try:
            from app.external_comms.manager import _import_all_platforms
            _import_all_platforms()
            logger.info("[EXT LIBS] External platform modules loaded")
        except Exception as e:
            logger.warning(f"[EXT LIBS] Failed to load platform modules: {e}")

    # =====================================
    # Lifecycle
    # =====================================

    async def run(
        self,
        *,
        provider: str | None = None,
        api_key: str = "",
        interface_mode: str = "tui",
    ) -> None:
        """
        Launch the interactive loop for the agent.

        Args:
            provider: Optional provider override passed to the interface before
                chat starts; defaults to the provider configured during
                initialization.
            api_key: Optional API key presented in the interface for convenience.
            interface_mode: "tui" for Textual interface, "cli" for command line.
        """
        # Startup progress messages
        print("[3/8] Initializing agent...")

        # Initialize MCP client and register tools
        print("[4/8] Connecting to MCP servers...")
        await self._initialize_mcp()

        # Initialize skills system
        print("[5/8] Loading skills...")
        await self._initialize_skills()

        # Start usage reporter background flush
        from app.usage import get_usage_reporter
        self._usage_reporter = get_usage_reporter()
        self._usage_reporter.start_background_flush()

        # Initialize external app libraries
        print("[6/8] Loading libraries...")
        await self._initialize_external_libraries()

        # Process unprocessed events into memory at startup (if enabled)
        if PROCESS_MEMORY_AT_STARTUP:
            await self._process_memory_at_startup()

        # Initialize and start the scheduler (handles memory processing and other periodic tasks)
        print("[7/8] Starting scheduler...")
        from app.config import PROJECT_ROOT
        scheduler_config_path = PROJECT_ROOT / "app" / "config" / "scheduler_config.json"
        await self.scheduler.initialize(
            config_path=scheduler_config_path,
            trigger_queue=self.triggers,
        )
        await self.scheduler.start()

        # Trigger soft onboarding if needed (BEFORE starting interface)
        # This ensures agent handles onboarding logic, not the interfaces
        from app.onboarding import onboarding_manager
        if onboarding_manager.needs_soft_onboarding:
            logger.info("[ONBOARDING] Soft onboarding needed, triggering from agent")
            await self.trigger_soft_onboarding()

        # Initialize external communications (WhatsApp, Telegram)
        print("[8/8] Starting communications...")
        from app.external_comms import ExternalCommsManager
        from app.external_comms.manager import initialize_manager
        self._external_comms = initialize_manager(self)
        await self._external_comms.start()

        # Startup complete
        print("\n[OK] Ready!\n", flush=True)

        # Flush stdout/stderr to ensure clean output before TUI starts
        import sys
        sys.stdout.flush()
        sys.stderr.flush()

        try:
            # Select interface based on mode
            if interface_mode == "cli":
                from app.cli import CLIInterface
                interface = CLIInterface(
                    self,
                    default_provider=provider or self.llm.provider,
                    default_api_key=api_key,
                )
            else:
                # Import TUI lazily to avoid terminal capability queries at startup
                from app.tui import TUIInterface
                interface = TUIInterface(
                    self,
                    default_provider=provider or self.llm.provider,
                    default_api_key=api_key,
                )

            await interface.start()
        finally:
            # Shutdown scheduler (handles all periodic tasks including memory processing)
            self.is_running = False
            await self.scheduler.shutdown()
            # Gracefully shutdown MCP connections
            await self._shutdown_mcp()
            # Stop external communications
            if hasattr(self, '_external_comms'):
                await self._external_comms.stop()
            # Flush remaining usage events
            if hasattr(self, '_usage_reporter'):
                await self._usage_reporter.shutdown()