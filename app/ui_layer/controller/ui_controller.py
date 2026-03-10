"""Central UI Controller that coordinates all UI operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

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

    async def submit_message(self, message: str, adapter_id: str = "") -> None:
        """
        Handle user input from any interface.

        Routes through command handling first, then to agent if not a command.

        Args:
            message: The user's input message
            adapter_id: ID of the adapter that sent the message
        """
        if not message.strip():
            return

        # Try command execution first
        if await self._command_executor.try_execute(message, adapter_id):
            return

        # Not a command - send to agent
        # Update state
        self._state_store.dispatch("SET_AGENT_STATE", AgentStateType.WORKING.value)

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
                data={"message": message, "adapter_id": adapter_id},
                source_adapter=adapter_id,
            )
        )

        # Route to agent
        payload = {
            "text": message,
            "sender": {"id": adapter_id or "user", "type": "user"},
            "gui_mode": self._state_store.state.gui_mode,
        }
        await self._agent._handle_chat_message(payload)

    # ─────────────────────────────────────────────────────────────────────
    # Event Processing
    # ─────────────────────────────────────────────────────────────────────

    async def _watch_agent_events(self) -> None:
        """Watch and transform agent events to UI events."""
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

    async def _consume_triggers(self) -> None:
        """Consume triggers and run agent reactions."""
        while self._running and self._agent.is_running:
            try:
                trigger = await asyncio.wait_for(
                    self._agent.triggers.get(), timeout=0.5
                )
                # Run react in a thread to avoid blocking
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._run_react_in_thread,
                    trigger,
                )
            except asyncio.TimeoutError:
                # No trigger available, continue
                pass
            except Exception:
                # Log but don't crash
                await asyncio.sleep(0.1)

    def _run_react_in_thread(self, trigger) -> None:
        """Run agent.react() in an isolated thread with its own event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._agent.react(trigger))
        finally:
            loop.close()

    # ─────────────────────────────────────────────────────────────────────
    # Command Registration
    # ─────────────────────────────────────────────────────────────────────

    def _register_builtin_commands(self) -> None:
        """Register all built-in commands."""
        from app.ui_layer.commands.builtin import (
            HelpCommand,
            ClearCommand,
            ResetCommand,
            ExitCommand,
            MenuCommand,
            ProviderCommand,
            MCPCommand,
            SkillCommand,
            CredCommand,
        )

        self._command_registry.register(HelpCommand(self))
        self._command_registry.register(ClearCommand(self))
        self._command_registry.register(ResetCommand(self))
        self._command_registry.register(ExitCommand(self))
        self._command_registry.register(MenuCommand(self))
        self._command_registry.register(ProviderCommand(self))
        self._command_registry.register(MCPCommand(self))
        self._command_registry.register(SkillCommand(self))
        self._command_registry.register(CredCommand(self))

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
