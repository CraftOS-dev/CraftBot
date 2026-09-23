"""Central UI Controller that coordinates all UI operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from agent_core.utils.logger import logger
from app.ui_layer.events.event_bus import EventBus
from app.ui_layer.events.event_types import UIEvent, UIEventType
from app.ui_layer.events.transformer import EventTransformer
from app.ui_layer.controller.event_cursor import (
    EventStreamCursors,
    event_dedup_key,
)
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
        # Per-stream read positions for the event pump. Owned here (not
        # local to the pump task) so a stream being torn down can be drained
        # through the same cursors before it disappears.
        self._cursors = EventStreamCursors()
        self._removal_listener_registered = False

        # Settle activity rows whose action_end never reached the UI.
        self._event_bus.subscribe(
            UIEventType.RUN_STATE_CHANGED, self._on_run_state_changed
        )

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

    async def stop_run(self, session_id: Optional[str] = None) -> bool:
        """Force-stop a session's in-flight run (chat stop button).

        Returns True when a run was actually stopped. Run-state broadcasts
        ("stopping" then "idle") come from the agent, not from here.
        """
        return await self._agent.request_run_stop(session_id or "main")

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

    async def submit_question_answer(
        self,
        value: str,
        question: str,
        session_id: Optional[str] = None,
        dismissed: bool = False,
        adapter_id: str = "",
        pending_questions: Optional[list] = None,
    ) -> None:
        """
        Handle the user's response to a pinned agent question (suggested
        responses UI).

        Paints the answer as a normal user bubble, then hands the agent a
        marker-prefixed copy that names the question being answered — the
        answer rides the regular user-message trigger, so it queues/merges
        like any other message when the agent is mid-run.

        Args:
            value: The chosen suggestion or typed free-text answer. Ignored
                when dismissed.
            question: The question message's text (for the agent-side marker).
            session_id: The session the question belongs to.
            dismissed: True when the user closed the question unanswered —
                no bubble is painted; the agent is told to proceed on its
                own judgment.
            adapter_id: ID of the adapter that sent the response.
            pending_questions: Contents of the session's OTHER still-
                unanswered questions. Appended as a reminder so the agent
                doesn't re-ask questions that are still pinned in the UI.
        """
        question_excerpt = " ".join(question.split())
        if len(question_excerpt) > 200:
            question_excerpt = question_excerpt[:200] + "..."

        if dismissed:
            agent_text = (
                f"[QUESTION DISMISSED] The user dismissed your question "
                f'("{question_excerpt}") without answering. Do NOT re-ask '
                f"it; proceed using your best judgment."
            )
        else:
            if not value.strip():
                return
            agent_text = f'[ANSWERING YOUR QUESTION "{question_excerpt}"] {value}'

            # Paint the answer as a user bubble (and persist it) — only the
            # answer text; the marker is agent-facing context.
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
            self._event_bus.emit(
                UIEvent(
                    type=UIEventType.USER_MESSAGE,
                    data={
                        "message": value,
                        "adapter_id": adapter_id,
                        "session_id": session_id,
                    },
                    source_adapter=adapter_id,
                )
            )

        if pending_questions:
            listed = " | ".join(
                f'"{" ".join(q.split())[:120]}"' for q in pending_questions
            )
            agent_text += (
                f"\n[Your other question(s) are STILL PINNED in the user's UI "
                f"awaiting their response — do NOT re-send them: {listed}]"
            )

        await self._agent._handle_chat_message(
            {
                "text": agent_text,
                "sender": {"id": adapter_id or "user", "type": "user"},
                "session_id": session_id,
            }
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

    def _process_event(self, task_id: str, event, *, emit: bool) -> None:
        """Deliver ONE event to the UI, isolating its failures.

        The cursor advances past a whole batch the moment it is read, so a
        raise anywhere in here used to abandon every remaining event of that
        tick — permanently, because those events were never marked seen and
        the cursor had already passed them. A parallel action batch puts all
        its ``action_end`` records in one tick, which is exactly when the loss
        showed up: the rows stayed "running" forever, with nothing in the log
        because the pump swallowed the exception. Failures are now contained
        to their own event, and always logged.

        Args:
            task_id: The owning stream's session id.
            event: The raw event-stream record's event.
            emit: False during the restore pass, which rebuilds UI state
                without re-announcing history to the interface.
        """
        key = event_dedup_key(task_id, event)
        if key in self._state_store.state.seen_event_keys:
            return
        self._state_store.dispatch("MARK_EVENT_SEEN", key)

        ui_event = EventTransformer.transform(event, task_id)
        if ui_event is None:
            return
        if emit:
            self._event_bus.emit(ui_event)
        self._update_state_from_event(ui_event)

    def _drain_stream(self, task_id: str, stream, cursors) -> None:
        """Read and deliver one stream's new events. Never raises."""
        try:
            events = cursors.new_events(task_id, stream)
        except Exception:
            logger.exception(f"[UI] Failed to read new events for stream {task_id}")
            return
        for event in events:
            try:
                self._process_event(task_id, event, emit=True)
            except Exception:
                logger.exception(
                    f"[UI] Failed to deliver event from stream {task_id} "
                    f"(kind={getattr(event, 'kind', '?')}, "
                    f"action_id={getattr(event, 'action_id', None)})"
                )

    def _on_stream_removed(self, task_id: str, stream) -> None:
        """Drain a stream that is about to be dropped.

        Registered with EventStreamManager.add_removal_listener and called
        synchronously by whatever tears the stream down — a sub-agent
        finishing, a session being deleted. Without it, everything logged
        since the last 50 ms poll dies with the stream.
        """
        if not self._running:
            return
        self._drain_stream(task_id, stream, self._cursors)

    async def _watch_agent_events(self) -> None:
        """Watch and transform agent events to UI events."""
        # Mark all pre-existing events as seen so restored events
        # from previous sessions are not emitted as new UI messages.
        # State-updating events (action_start/action_end) are still processed
        # to rebuild UI state (e.g., show a restored in-flight action).
        # Each tick reads only events added since the previous one; the
        # stream is never modified (event_cursor.py).
        cursors = self._cursors
        streams = self._agent.event_stream_manager.get_all_streams_with_ids()
        for task_id, stream in streams:
            for event in cursors.new_events(task_id, stream):
                try:
                    self._process_event(task_id, event, emit=False)
                except Exception:
                    logger.exception(
                        f"[UI] Failed to restore event from stream {task_id}"
                    )

        # A stream can disappear between two polls; drain it before it goes.
        # Registered once per controller, not once per start/stop cycle.
        if not self._removal_listener_registered:
            try:
                self._agent.event_stream_manager.add_removal_listener(
                    self._on_stream_removed
                )
                self._removal_listener_registered = True
            except AttributeError:
                # Event-stream manager without the hook: the polling loop
                # below is still the primary path.
                logger.debug("[UI] Event stream manager has no removal hook")

        while self._running and self._agent.is_running:
            try:
                # Get all event streams
                streams = self._agent.event_stream_manager.get_all_streams_with_ids()
                cursors.retain(task_id for task_id, _ in streams)

                for task_id, stream in streams:
                    self._drain_stream(task_id, stream, cursors)

                await asyncio.sleep(0.05)  # 50ms polling interval

            except Exception:
                logger.exception("[UI] Event pump tick failed")
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
                    "task_id": event.task_id or event.data.get("session_id"),
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

    # ──────────────────────────────────────────────────────────────────
    # End-of-run reconciliation
    # ──────────────────────────────────────────────────────────────────

    # Grace period after a run settles before reconciling, so the normal
    # delivery path gets to finish first (the pump polls every 50 ms, and
    # its handlers are scheduled as tasks).
    _RECONCILE_DELAY_SECONDS = 2.0

    def _on_run_state_changed(self, event: UIEvent) -> None:
        """When a session's run settles, schedule a reconciliation pass."""
        if (event.data.get("state") or "") != "idle":
            return
        session_id = event.data.get("session_id") or "main"
        try:
            asyncio.create_task(self._settle_stale_actions(session_id))
        except RuntimeError:
            # No running loop (emitted off the loop); nothing to reconcile.
            pass

    async def _settle_stale_actions(self, session_id: str) -> None:
        """Settle activity rows left "running" after the run finished.

        The UI mirrors action state by replaying event-stream records. Every
        delivery path has failure modes that end in the same place — a row
        spinning forever — and because the status is persisted, a reload
        brings it right back. ``ActionManager`` knows what is actually still
        executing, so once a run settles anything it does not hold is over.

        Recovery order: replay the real ``action_end`` from the session's
        event stream (keeps the true status and output), and only fall back
        to a flat "completed" for rows whose end event is no longer there.
        """
        await asyncio.sleep(self._RECONCILE_DELAY_SECONDS)

        panel = self._adapter.action_panel if self._adapter else None
        get_items = getattr(panel, "get_items", None)
        if panel is None or get_items is None:
            return

        try:
            live = self._agent.action_manager.inflight_ids(session_id)
        except Exception:
            logger.exception("[UI] Could not read in-flight actions")
            return

        stale = {
            item.id: item
            for item in get_items()
            if item.item_type == "action"
            and item.status == "running"
            and (item.session_id or "main") == session_id
            and item.id
            and item.id not in live
        }
        if not stale:
            return

        logger.warning(
            f"[UI] {len(stale)} action(s) still marked running after session "
            f"{session_id} went idle; reconciling: "
            f"{[item.name for item in stale.values()]}"
        )

        for event in self._recover_action_ends(session_id, set(stale)):
            action_id = event.action_id
            try:
                ui_event = EventTransformer.transform(event, session_id)
                if ui_event is None:
                    continue
                self._event_bus.emit(ui_event)
                self._update_state_from_event(ui_event)
                stale.pop(action_id, None)
            except Exception:
                logger.exception(
                    f"[UI] Failed to replay action_end for {action_id}"
                )

        # Whatever is left has lost its end event for good (folded out of the
        # stream, or never logged). The action is not running — say so.
        for item in stale.values():
            try:
                await panel.update_item_by_name(
                    action_name=item.name,
                    session_id=session_id,
                    status="completed",
                    action_id=item.id,
                )
                logger.warning(
                    f"[UI] Force-settled action {item.name} ({item.id}): its "
                    "action_end event is no longer in the event stream"
                )
            except Exception:
                logger.exception(f"[UI] Failed to settle action {item.id}")

    def _recover_action_ends(self, session_id: str, action_ids: set) -> list:
        """The session stream's ``action_end`` events for these run ids."""
        if not action_ids:
            return []
        try:
            manager = self._agent.event_stream_manager
            if not manager.has_stream(session_id):
                return []
            events = manager.get_stream_by_id(session_id).as_list()
        except Exception:
            logger.exception(
                f"[UI] Could not read the event stream for session {session_id}"
            )
            return []

        from agent_core.core.event_stream.event import EventType

        return [
            event
            for event in events
            if event.event_type == EventType.ACTION_END
            and event.action_id in action_ids
        ]

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
            TokensCommand,
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
        self._command_registry.register(TokensCommand(self))

        # Register integration commands
        self._register_integration_commands()

    def _register_integration_commands(self) -> None:
        """Register integration-specific commands.

        Enumerated from the provider registry, which is a static list built at
        import time — no boot ordering to respect (the handler registry
        this used to read had to be populated by ``manager.start()`` first).
        """
        from craftos_integrations import list_all
        from app.ui_layer.commands.builtin.integrations import IntegrationCommand

        for integration_name in list_all():
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
