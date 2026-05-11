"""Central UI Controller that coordinates all UI operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from agent_core.utils.logger import logger
from app.ui_layer.events.event_bus import EventBus
from app.ui_layer.events.event_types import UIEvent, UIEventType
from app.ui_layer.events.transformer import EventTransformer
from app.ui_layer.state.store import UIStateStore
from app.ui_layer.state.ui_state import AgentStateType
from app.ui_layer.commands.registry import CommandRegistry
from app.ui_layer.commands.executor import CommandExecutor

if TYPE_CHECKING:
    from app.agent_base import AgentBase
    from app.ui_layer.adapters.base import InterfaceAdapter


@dataclass
class UIControllerConfig:
    """
    Configuration for the UI Controller.

    Attributes:
        default_provider: Default LLM provider
        default_api_key: Default API key (if any)
        enable_footage: Whether to enable footage display
        enable_action_panel: Whether to enable action panel
        max_event_history: Maximum events to keep in history
    """

    default_provider: str = "openai"
    default_api_key: str = ""
    enable_footage: bool = True
    enable_action_panel: bool = True
    max_event_history: int = 1000


class UIController:
    """
    Central controller for all UI operations.

    Coordinates between:
    - Agent runtime (via AgentBase)
    - Event system (EventBus)
    - State management (UIStateStore)
    - Command handling (CommandRegistry)
    - Active interface adapter

    Only one adapter can be active at a time. The controller manages
    the lifecycle of the active adapter and routes events to it.

    Example:
        controller = UIController(agent)
        await controller.start()

        # Register an adapter
        adapter = CLIAdapter(controller, "cli")
        await adapter.start()

        # Submit a message
        await controller.submit_message("Hello!", "cli")

        # Stop
        await adapter.stop()
        await controller.stop()
    """

    def __init__(
        self,
        agent: "AgentBase",
        config: Optional[UIControllerConfig] = None,
    ) -> None:
        """
        Initialize the UI controller.

        Args:
            agent: The agent runtime instance
            config: Optional configuration
        """
        self._agent = agent
        self._config = config or UIControllerConfig()

        # Core subsystems
        self._event_bus = EventBus(max_history=self._config.max_event_history)
        self._state_store = UIStateStore()
        self._command_registry = CommandRegistry()
        self._command_executor = CommandExecutor(
            registry=self._command_registry,
            controller=self,
        )

        # Runtime state
        self._running = False
        self._adapter: Optional["InterfaceAdapter"] = None
        self._event_task: Optional[asyncio.Task] = None
        self._trigger_task: Optional[asyncio.Task] = None

        # Register built-in commands
        self._register_builtin_commands()

        # Register agent-provided commands
        self._register_agent_commands()

        # Register enabled skills as slash commands
        self._register_skill_commands()

    # ─────────────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────────────

    @property
    def agent(self) -> "AgentBase":
        """Get the agent runtime."""
        return self._agent

    @property
    def event_bus(self) -> EventBus:
        """Get the event bus."""
        return self._event_bus

    @property
    def state_store(self) -> UIStateStore:
        """Get the state store."""
        return self._state_store

    @property
    def state(self):
        """Get the current UI state."""
        return self._state_store.state

    @property
    def command_registry(self) -> CommandRegistry:
        """Get the command registry."""
        return self._command_registry

    @property
    def config(self) -> UIControllerConfig:
        """Get the configuration."""
        return self._config

    @property
    def is_running(self) -> bool:
        """Check if the controller is running."""
        return self._running

    @property
    def active_adapter(self) -> Optional["InterfaceAdapter"]:
        """Get the currently active adapter."""
        return self._adapter

    # ─────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the UI controller and begin processing events."""
        if self._running:
            return

        self._running = True

        # Start event watching task
        self._event_task = asyncio.create_task(self._watch_agent_events())

        # Start trigger consuming task
        self._trigger_task = asyncio.create_task(self._consume_triggers())

    async def stop(self) -> None:
        """Stop the UI controller."""
        if not self._running:
            return

        self._running = False

        # Cancel tasks
        if self._event_task:
            self._event_task.cancel()
            try:
                await self._event_task
            except asyncio.CancelledError:
                pass

        if self._trigger_task:
            self._trigger_task.cancel()
            try:
                await self._trigger_task
            except asyncio.CancelledError:
                pass

    # ─────────────────────────────────────────────────────────────────────
    # Adapter Management
    # ─────────────────────────────────────────────────────────────────────

    def register_adapter(self, adapter: "InterfaceAdapter") -> None:
        """
        Register an interface adapter.

        Only one adapter can be active at a time.

        Args:
            adapter: The adapter to register

        Raises:
            RuntimeError: If an adapter is already registered
        """
        if self._adapter is not None:
            raise RuntimeError(
                f"An adapter is already registered: {self._adapter.adapter_id}. "
                "Only one adapter can be active at a time."
            )
        self._adapter = adapter

    def unregister_adapter(self) -> None:
        """Unregister the current adapter."""
        self._adapter = None

    # ─────────────────────────────────────────────────────────────────────
    # Message Handling
    # ─────────────────────────────────────────────────────────────────────

    async def submit_message(
        self,
        message: str,
        adapter_id: str = "",
        target_session_id: Optional[str] = None,
        living_ui_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> None:
        """
        Handle user input from any interface.

        Routes through command handling first, then to agent if not a command.

        Args:
            message: The user's input message
            adapter_id: ID of the adapter that sent the message
            target_session_id: Optional session ID for direct reply (bypasses routing)
            living_ui_id: Optional Living UI project ID if user is on a Living UI page
        """
        if not message.strip():
            return

        # Try command execution first
        if await self._command_executor.try_execute(message, adapter_id):
            return

        # Not a command - send to agent
        # Note: Task status updates (waiting -> running) are handled in _handle_chat_message
        # after routing determines the correct session. We don't update here to avoid
        # incorrectly changing status of unrelated tasks.

        # Emit state change event so adapters can update status immediately
        self._event_bus.emit(
            UIEvent(
                type=UIEventType.AGENT_STATE_CHANGED,
                data={
                    "state": AgentStateType.WORKING.value,
                    "status_message": "Agent is working...",
                },
                source_adapter=adapter_id,
            )
        )

        # Emit user message event
        self._event_bus.emit(
            UIEvent(
                type=UIEventType.USER_MESSAGE,
                data={
                    "message": message,
                    "adapter_id": adapter_id,
                    "client_id": client_id,
                },
                source_adapter=adapter_id,
            )
        )

        # Route to agent
        payload = {
            "text": message,
            "sender": {"id": adapter_id or "user", "type": "user"},
            "gui_mode": self._state_store.state.gui_mode,
        }
        # Include target session ID for direct reply (bypasses routing LLM)
        if target_session_id:
            payload["target_session_id"] = target_session_id
        if living_ui_id:
            payload["living_ui_id"] = living_ui_id

        await self._agent._handle_chat_message(payload)

    async def handle_option_click(self, value: str, session_id: str) -> None:
        """
        Handle a user clicking an option button in a chat message.

        Routes limit-choice options to the appropriate agent handler.

        Args:
            value: The option value (e.g. "continue_limit", "abort_limit")
            session_id: The task session ID associated with the option
        """
        if value == "continue_limit":
            await self._agent.handle_limit_continue(session_id)
        elif value == "abort_limit":
            await self._agent.handle_limit_abort(session_id)
        elif value == "llm_retry":
            await self._agent.handle_llm_retry(session_id)

    # ─────────────────────────────────────────────────────────────────────
    # Event Processing
    # ─────────────────────────────────────────────────────────────────────

    async def _watch_agent_events(self) -> None:
        """Watch and transform agent events to UI events."""
        # Mark all pre-existing events as seen so restored events
        # from previous sessions are not emitted as new UI messages.
        # State-updating events (task_start, task_end) are still processed
        # to rebuild UI state (e.g., show restored tasks as running).
        streams = self._agent.event_stream_manager.get_all_streams_with_ids()
        for task_id, stream in streams:
            for event in stream.as_list():
                key = (event.iso_ts, event.kind, event.message)
                self._state_store.dispatch("MARK_EVENT_SEEN", key)
                # Rebuild UI state from restored events without emitting to UI
                ui_event = EventTransformer.transform(event, task_id)
                if ui_event:
                    self._update_state_from_event(ui_event)

        while self._running and self._agent.is_running:
            try:
                # Get all event streams
                streams = self._agent.event_stream_manager.get_all_streams_with_ids()

                for task_id, stream in streams:
                    for event in stream.as_list():
                        # Create deduplication key
                        key = (event.iso_ts, event.kind, event.message)

                        # Skip if already seen
                        if key in self._state_store.state.seen_event_keys:
                            continue

                        # Mark as seen
                        self._state_store.dispatch("MARK_EVENT_SEEN", key)

                        # Transform and emit
                        ui_event = EventTransformer.transform(event, task_id)
                        if ui_event:
                            self._event_bus.emit(ui_event)
                            self._update_state_from_event(ui_event)

                await asyncio.sleep(0.05)  # 50ms polling interval

            except Exception:
                # Log but don't crash
                await asyncio.sleep(0.1)

    def _update_state_from_event(self, event: UIEvent) -> None:
        """Update state store based on UI events."""
        if event.type == UIEventType.TASK_START:
            # Skip task events from main stream (empty task_id).
            # Main stream's task_started events are for conversation history tracking,
            # not for UI task panels. Task stream has the actual task_start events.
            task_id = event.data.get("task_id", "")
            if not task_id:
                return

            self._state_store.dispatch(
                "ADD_ACTION_ITEM",
                {
                    "id": task_id,
                    "display_name": event.data.get("task_name", "Task"),
                    "item_type": "task",
                    "status": "running",
                },
            )
            self._state_store.dispatch(
                "SET_CURRENT_TASK",
                {
                    "task_id": task_id,
                    "task_name": event.data.get("task_name"),
                },
            )
            self._state_store.dispatch("SET_AGENT_STATE", AgentStateType.WORKING.value)
            # Emit state change event so adapters can update status
            task_name = event.data.get("task_name", "task")
            self._event_bus.emit(
                UIEvent(
                    type=UIEventType.AGENT_STATE_CHANGED,
                    data={
                        "state": AgentStateType.WORKING.value,
                        "status_message": f"Working on {task_name}...",
                    },
                )
            )

        elif event.type == UIEventType.TASK_END:
            # Skip task events from main stream (empty task_id).
            # Main stream's task_ended events are for conversation history tracking.
            task_id = event.data.get("task_id", "")
            if not task_id:
                return

            self._state_store.dispatch(
                "UPDATE_ACTION_ITEM",
                {
                    "id": task_id,
                    "status": event.data.get("status", "completed"),
                },
            )
            self._state_store.dispatch("SET_CURRENT_TASK", None)
            self._state_store.dispatch("SET_AGENT_STATE", AgentStateType.IDLE.value)
            # Emit state change event so adapters can update status
            self._event_bus.emit(
                UIEvent(
                    type=UIEventType.AGENT_STATE_CHANGED,
                    data={
                        "state": AgentStateType.IDLE.value,
                        "status_message": "Agent is idle",
                    },
                )
            )

        elif event.type == UIEventType.ACTION_START:
            self._state_store.dispatch(
                "ADD_ACTION_ITEM",
                {
                    "id": event.data.get("action_id", ""),
                    "display_name": event.data.get("action_name", "Action"),
                    "item_type": "action",
                    "status": "running",
                    "task_id": event.data.get("task_id"),
                },
            )

        elif event.type == UIEventType.ACTION_END:
            self._state_store.dispatch(
                "UPDATE_ACTION_ITEM",
                {
                    "id": event.data.get("action_id", ""),
                    "status": event.data.get("status", "completed"),
                },
            )
            # Check if there are no more running items and emit IDLE state
            if not self._state_store.state.has_running_items():
                self._state_store.dispatch("SET_AGENT_STATE", AgentStateType.IDLE.value)
                self._event_bus.emit(
                    UIEvent(
                        type=UIEventType.AGENT_STATE_CHANGED,
                        data={
                            "state": AgentStateType.IDLE.value,
                            "status_message": "Agent is idle",
                        },
                    )
                )

        elif event.type == UIEventType.GUI_MODE_CHANGED:
            self._state_store.dispatch(
                "SET_GUI_MODE", event.data.get("gui_mode", False)
            )

        elif event.type == UIEventType.WAITING_FOR_USER:
            task_id = event.data.get("task_id", "")
            if task_id:
                # Update specific task status to "waiting"
                self._state_store.dispatch(
                    "UPDATE_ACTION_ITEM",
                    {
                        "id": task_id,
                        "status": "waiting",
                    },
                )
            # Update global agent state
            self._state_store.dispatch(
                "SET_AGENT_STATE", AgentStateType.WAITING_FOR_USER.value
            )
            # Emit state change event for status bar
            self._event_bus.emit(
                UIEvent(
                    type=UIEventType.AGENT_STATE_CHANGED,
                    data={
                        "state": AgentStateType.WAITING_FOR_USER.value,
                        "status_message": "Waiting for your response",
                    },
                )
            )

        elif event.type == UIEventType.TASK_UPDATE:
            task_id = event.data.get("task_id", "")
            if task_id:
                self._state_store.dispatch(
                    "UPDATE_ACTION_ITEM",
                    {
                        "id": task_id,
                        "status": event.data.get("status", "running"),
                    },
                )

    async def _consume_triggers(self) -> None:
        """Consume triggers and run agent reactions."""
        logger.info("[CONSUMER] Trigger consumer started")
        try:
            while self._running and self._agent.is_running:
                try:
                    trigger = await self._agent.triggers.get()
                    await self._agent.react(trigger)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(
                        f"[CONSUMER] Exception during trigger processing: {e!r}",
                        exc_info=True,
                    )
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("[CONSUMER] Trigger consumer cancelled")
            raise
        except BaseException as e:
            logger.error(
                f"[CONSUMER] Trigger consumer died with unhandled {type(e).__name__}: {e!r}",
                exc_info=True,
            )
            raise
        finally:
            logger.info(
                f"[CONSUMER] Trigger consumer exiting "
                f"(running={self._running}, agent_running={self._agent.is_running})"
            )

    # ─────────────────────────────────────────────────────────────────────
    # Command Registration
    # ─────────────────────────────────────────────────────────────────────

    def _register_builtin_commands(self) -> None:
        """Register all built-in commands."""
        from app.ui_layer.commands.builtin import (
            HelpCommand,
            ClearCommand,
            ClearTasksCommand,
            ResetCommand,
            ExitCommand,
            MenuCommand,
            ProviderCommand,
            MCPCommand,
            SkillCommand,
            CredCommand,
            UpdateCommand,
        )

        self._command_registry.register(HelpCommand(self))
        self._command_registry.register(ClearCommand(self))
        self._command_registry.register(ClearTasksCommand(self))
        self._command_registry.register(ResetCommand(self))
        self._command_registry.register(ExitCommand(self))
        self._command_registry.register(MenuCommand(self))
        self._command_registry.register(ProviderCommand(self))
        self._command_registry.register(MCPCommand(self))
        self._command_registry.register(SkillCommand(self))
        self._command_registry.register(CredCommand(self))
        self._command_registry.register(UpdateCommand(self))

        # Register integration commands
        self._register_integration_commands()

    def _register_integration_commands(self) -> None:
        """Register integration-specific commands."""
        from app.credentials.handlers import INTEGRATION_HANDLERS
        from app.ui_layer.commands.builtin.integrations import IntegrationCommand

        for integration_name in INTEGRATION_HANDLERS:
            cmd = IntegrationCommand(self, integration_name)
            self._command_registry.register(cmd)

    def _register_agent_commands(self) -> None:
        """Register agent-provided commands."""
        from app.ui_layer.commands.builtin.agent_command import AgentCommandWrapper

        for name, cmd_info in self._agent.get_commands().items():
            wrapped = AgentCommandWrapper(self, name, cmd_info)
            self._command_registry.register(wrapped)

    def _register_skill_commands(self) -> None:
        """Register enabled skills as slash commands."""
        from app.ui_layer.commands.builtin.skill_invoke import SkillInvokeCommand

        try:
            from agent_core.core.impl.skill.manager import skill_manager

            for skill in skill_manager.get_enabled_skills():
                cmd_name = f"/{skill.name}"
                if self._command_registry.has(cmd_name):
                    logger.warning(
                        f"[SKILLS] Cannot register {cmd_name} as command — "
                        f"name conflicts with existing command"
                    )
                    continue
                cmd = SkillInvokeCommand(
                    self,
                    skill.name,
                    skill.description,
                    argument_hint=skill.metadata.argument_hint,
                )
                self._command_registry.register(cmd)

            logger.info(
                f"[SKILLS] Registered {len(skill_manager.get_enabled_skills())} "
                f"skill commands"
            )
        except Exception as e:
            # Skill system may not be initialized yet at startup
            pass

    def sync_skill_commands(self) -> None:
        """Re-synchronize skill slash commands with current enabled skills."""
        from app.ui_layer.commands.builtin.skill_invoke import SkillInvokeCommand

        # Remove all existing skill-invoke commands
        for cmd_name in list(self._command_registry.get_command_names()):
            cmd = self._command_registry.get(cmd_name)
            if isinstance(cmd, SkillInvokeCommand):
                self._command_registry.unregister(cmd_name)

        # Re-register from current skill state
        self._register_skill_commands()

    async def invoke_skill(
        self,
        skill_name: str,
        args_text: str,
        adapter_id: str = "",
    ) -> None:
        """
        Invoke a skill by routing through the agent's message handler.

        Emits appropriate UI events and sends the message to the agent
        with a skill hint so the LLM selects the correct skill.

        Args:
            skill_name: Name of the skill to invoke
            args_text: User-provided arguments (may be empty)
            adapter_id: ID of the adapter that initiated the invocation
        """
        # Emit system message
        if args_text:
            sys_msg = f"Invoking skill '{skill_name}': {args_text}"
        else:
            sys_msg = f"Invoking skill '{skill_name}'..."

        self._event_bus.emit(
            UIEvent(
                type=UIEventType.SYSTEM_MESSAGE,
                data={"message": sys_msg},
                source_adapter=adapter_id,
            )
        )

        # Emit state change
        self._event_bus.emit(
            UIEvent(
                type=UIEventType.AGENT_STATE_CHANGED,
                data={
                    "state": AgentStateType.WORKING.value,
                    "status_message": "Agent is working...",
                },
                source_adapter=adapter_id,
            )
        )

        # Build task text for the agent
        if args_text:
            task_text = args_text
        else:
            task_text = (
                f"User invoked the {skill_name} skill. "
                f"Ask user for further requirement if the skill requires context."
            )

        # Route to agent with pre_selected_skills in payload
        payload = {
            "text": task_text,
            "sender": {"id": adapter_id or "user", "type": "user"},
            "gui_mode": self._state_store.state.gui_mode,
            "pre_selected_skills": [skill_name],
        }
        await self._agent._handle_chat_message(payload)

    # ─────────────────────────────────────────────────────────────────────
    # Utility Methods
    # ─────────────────────────────────────────────────────────────────────

    def emit_system_message(self, message: str) -> None:
        """
        Emit a system message to the UI.

        Args:
            message: The message to display
        """
        self._event_bus.emit(
            UIEvent(
                type=UIEventType.SYSTEM_MESSAGE,
                data={"message": message},
            )
        )

    def emit_error_message(self, message: str) -> None:
        """
        Emit an error message to the UI.

        Args:
            message: The error message to display
        """
        self._event_bus.emit(
            UIEvent(
                type=UIEventType.ERROR_MESSAGE,
                data={"message": message},
            )
        )

    def emit_info_message(self, message: str) -> None:
        """
        Emit an info message to the UI.

        Args:
            message: The info message to display
        """
        self._event_bus.emit(
            UIEvent(
                type=UIEventType.INFO_MESSAGE,
                data={"message": message},
            )
        )
