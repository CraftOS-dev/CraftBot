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

        # Register built-in commands
        self._register_builtin_commands()

        # Register agent-provided commands
        self._register_agent_commands()

        # Register enabled skills as slash commands
        self._register_skill_commands()

        # Expose the event bus on global STATE so module-level hooks
        # (e.g. _report_usage in app/llm/interface.py) can emit UI events
        # without needing a controller handle.
        try:
            from app.state.agent_state import STATE

            STATE.event_bus = self._event_bus
        except Exception:
            pass

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
        """Start the UI controller and begin processing events.

        The agent loops themselves are owned by the per-session runtime
        (SessionRuntimeManager) — this controller only watches event streams
        and routes user input.
        """
        if self._running:
            return

        self._running = True

        # Start event watching task
        self._event_task = asyncio.create_task(self._watch_agent_events())

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
        session_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> None:
        """
        Handle user input from any interface.

        Routes through command handling first, then to agent if not a command.

        Args:
            message: The user's input message
            adapter_id: ID of the adapter that sent the message
            session_id: The session the message was typed in (main if omitted)
            client_id: Optional originating client id (echo suppression)
        """
        if not message.strip():
            return

        # Try command execution first
        if await self._command_executor.try_execute(
            message, adapter_id, session_id=session_id
        ):
            return

        # Emit state change event so adapters can update status immediately
        self._event_bus.emit(
            UIEvent(
                type=UIEventType.AGENT_STATE_CHANGED,
                data={
                    "state": AgentStateType.WORKING.value,
                    "status_message": "Agent is working...",
                    "session_id": session_id,
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
                    "session_id": session_id,
                },
                source_adapter=adapter_id,
            )
        )

        # Route to agent — the destination session is explicit; no routing.
        payload = {
            "text": message,
            "sender": {"id": adapter_id or "user", "type": "user"},
            "session_id": session_id,
        }

        await self._agent._handle_chat_message(payload)

    async def notify_session_updated(self, session_id: str) -> None:
        """Tell the active adapter a session's metadata changed (e.g. title)."""
        adapter = self._adapter
        broadcast = getattr(adapter, "broadcast_session_updated", None)
        if broadcast is not None:
            try:
                await broadcast(session_id)
            except Exception:
                logger.debug(
                    f"[UI] Failed to broadcast session update for {session_id}",
                    exc_info=True,
                )

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

    async def handle_prompt_enhance(self, user_message: str) -> str:
        return await self._agent._handle_prompt_enhance(user_message=user_message)

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
                key = (task_id, event.iso_ts, event.kind, event.message)
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
                        # Create deduplication key. task_id must be part of
                        # the key: iso_ts is seconds-precision and task_end
                        # messages are generic, so two tasks ending in the
                        # same second would otherwise collide and the second
                        # TASK_END would be dropped — leaving that task stuck
                        # "running" in every UI until restart.
                        key = (task_id, event.iso_ts, event.kind, event.message)

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
        if event.type == UIEventType.ACTION_START:
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
            UpdateCommand,
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
        self._command_registry.register(UpdateCommand(self))

        # Register integration commands
        self._register_integration_commands()

    def _register_integration_commands(self) -> None:
        """Register integration-specific commands.

        ``manager.start()`` (called during agent step 6) has already populated
        the registry by the time the UI controller boots, so we just iterate
        the registered handler names.
        """
        from craftos_integrations import get_registered_handler_names
        from app.ui_layer.commands.builtin.integrations import IntegrationCommand

        for integration_name in get_registered_handler_names():
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
        except Exception:
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
        session_id: Optional[str] = None,
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
                task_id=session_id,
            )
        )

        # Emit state change
        self._event_bus.emit(
            UIEvent(
                type=UIEventType.AGENT_STATE_CHANGED,
                data={
                    "state": AgentStateType.WORKING.value,
                    "status_message": "Agent is working...",
                    "session_id": session_id,
                },
                source_adapter=adapter_id,
                task_id=session_id,
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
            "session_id": session_id,
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
