"""Base interface adapter class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, List, Optional
import asyncio

from app.ui_layer.events import UIEvent, UIEventType
from app.ui_layer.themes.base import ThemeAdapter
from app.ui_layer.components.protocols import (
    ChatComponentProtocol,
    ActionPanelProtocol,
    StatusBarProtocol,
    InputComponentProtocol,
    FootageComponentProtocol,
)
from app.ui_layer.components.types import ChatMessage, ChatMessageOption, ActionItem

if TYPE_CHECKING:
    from app.ui_layer.controller.ui_controller import UIController


class InterfaceAdapter(ABC):
    """
    Base class for interface adapters.

    Each interface (CLI, Browser) extends this to implement
    the UI components and connect to the controller. Only one adapter
    can be active at a time.

    Adapters:
    - Subscribe to UI events via the EventBus
    - Implement component protocols for their specific UI technology
    - Handle input and route to the controller
    - Render output based on events

    Example:
        class MyAdapter(InterfaceAdapter):
            @property
            def theme_adapter(self) -> ThemeAdapter:
                return MyThemeAdapter(BaseTheme())

            @property
            def chat_component(self) -> ChatComponentProtocol:
                return self._chat

            async def _on_start(self) -> None:
                # Initialize UI
                pass

            async def _on_stop(self) -> None:
                # Cleanup UI
                pass
    """

    def __init__(
        self,
        controller: "UIController",
        adapter_id: str,
    ) -> None:
        """
        Initialize the adapter.

        Args:
            controller: The UI controller instance
            adapter_id: Unique identifier for this adapter
        """
        self._controller = controller
        self._adapter_id = adapter_id
        self._running = False
        self._unsubscribers: List[Callable[[], None]] = []

    @property
    def adapter_id(self) -> str:
        """Get the adapter ID."""
        return self._adapter_id

    @property
    def controller(self) -> "UIController":
        """Get the UI controller."""
        return self._controller

    @property
    def is_running(self) -> bool:
        """Check if the adapter is running."""
        return self._running

    # ─────────────────────────────────────────────────────────────────────
    # Abstract properties - must be implemented by subclasses
    # ─────────────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def theme_adapter(self) -> ThemeAdapter:
        """Get the theme adapter for this interface."""
        pass

    @property
    @abstractmethod
    def chat_component(self) -> ChatComponentProtocol:
        """Get the chat display component."""
        pass

    # ─────────────────────────────────────────────────────────────────────
    # Optional components - override if your interface supports them
    # ─────────────────────────────────────────────────────────────────────

    @property
    def action_panel(self) -> Optional[ActionPanelProtocol]:
        """Get the action panel component (optional)."""
        return None

    @property
    def status_bar(self) -> Optional[StatusBarProtocol]:
        """Get the status bar component (optional)."""
        return None

    @property
    def input_component(self) -> Optional[InputComponentProtocol]:
        """Get the input component (optional)."""
        return None

    @property
    def footage_component(self) -> Optional[FootageComponentProtocol]:
        """Get the footage component (optional)."""
        return None

    # ─────────────────────────────────────────────────────────────────────
    # Lifecycle methods
    # ─────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the interface adapter."""
        if self._running:
            return

        self._running = True
        self._controller.register_adapter(self)

        # Capture the main event loop so worker threads (LLM calls invoked
        # via asyncio.to_thread) can schedule coroutines back onto it.
        try:
            from app.state.agent_state import STATE

            STATE.main_loop = asyncio.get_running_loop()
        except Exception:
            pass

        # Subscribe to events
        self._subscribe_events()

        # Run interface-specific startup
        await self._on_start()

    async def stop(self) -> None:
        """Stop the interface adapter."""
        if not self._running:
            return

        self._running = False

        # Unsubscribe from events
        for unsub in self._unsubscribers:
            unsub()
        self._unsubscribers.clear()

        self._controller.unregister_adapter()

        await self._on_stop()

    # ─────────────────────────────────────────────────────────────────────
    # Abstract methods - must be implemented by subclasses
    # ─────────────────────────────────────────────────────────────────────

    @abstractmethod
    async def _on_start(self) -> None:
        """
        Interface-specific startup logic.

        Called after the adapter is registered and events are subscribed.
        Use this to initialize your UI, show welcome messages, etc.
        """
        pass

    @abstractmethod
    async def _on_stop(self) -> None:
        """
        Interface-specific shutdown logic.

        Called before the adapter is unregistered.
        Use this to clean up your UI, save state, etc.
        """
        pass

    # ─────────────────────────────────────────────────────────────────────
    # Event handling
    # ─────────────────────────────────────────────────────────────────────

    def _subscribe_events(self) -> None:
        """Subscribe to relevant events from the event bus."""
        bus = self._controller.event_bus

        # Chat events
        self._unsubscribers.append(
            bus.subscribe(UIEventType.USER_MESSAGE, self._handle_user_message)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.AGENT_MESSAGE, self._handle_agent_message)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.SYSTEM_MESSAGE, self._handle_system_message)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.ERROR_MESSAGE, self._handle_error_message)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.LLM_FATAL_ERROR, self._handle_llm_fatal_error)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.INFO_MESSAGE, self._handle_info_message)
        )

        # Action events (per-session activity feed)
        self._unsubscribers.append(
            bus.subscribe(UIEventType.ACTION_START, self._handle_action_start)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.ACTION_END, self._handle_action_end)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.REASONING, self._handle_reasoning)
        )

        # State events
        self._unsubscribers.append(
            bus.subscribe(UIEventType.AGENT_STATE_CHANGED, self._handle_state_change)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.GUI_MODE_CHANGED, self._handle_gui_mode_change)
        )

        # Footage events
        self._unsubscribers.append(
            bus.subscribe(UIEventType.FOOTAGE_UPDATE, self._handle_footage_update)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.FOOTAGE_CLEAR, self._handle_footage_clear)
        )

        # Navigation events
        self._unsubscribers.append(
            bus.subscribe(UIEventType.SHOW_MENU, self._handle_show_menu)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.INTERFACE_SHUTDOWN, self._handle_shutdown)
        )

    # ─────────────────────────────────────────────────────────────────────
    # Default event handlers - subclasses can override for custom behavior
    # ─────────────────────────────────────────────────────────────────────

    def _handle_user_message(self, event: UIEvent) -> None:
        """Handle user message event."""
        asyncio.create_task(
            self._display_chat_message(
                "You",
                event.data.get("message", ""),
                "user",
                session_id=event.data.get("session_id"),
                client_id=event.data.get("client_id"),
            )
        )

    def _handle_agent_message(self, event: UIEvent) -> None:
        """Handle agent message event."""
        from app.onboarding import onboarding_manager

        agent_name = onboarding_manager.state.agent_name or "Agent"
        # Extract options from event data if present
        raw_options = event.data.get("options")
        options = None
        if raw_options and isinstance(raw_options, list):
            options = [
                ChatMessageOption(
                    label=o.get("label", ""),
                    value=o.get("value", ""),
                    style=o.get("style", "default"),
                )
                for o in raw_options
            ]
        asyncio.create_task(
            self._display_chat_message(
                agent_name,
                event.data.get("message", ""),
                "agent",
                session_id=event.task_id,
                options=options,
            )
        )

    def _handle_system_message(self, event: UIEvent) -> None:
        """Handle system message event."""
        asyncio.create_task(
            self._display_chat_message(
                "System",
                event.data.get("message", ""),
                "system",
                session_id=event.task_id,
            )
        )

    def _handle_error_message(self, event: UIEvent) -> None:
        """Handle error message event."""
        asyncio.create_task(
            self._display_chat_message(
                "Error",
                event.data.get("message", ""),
                "error",
                session_id=event.task_id,
            )
        )

    def _handle_llm_fatal_error(self, event: UIEvent) -> None:
        """Handle fatal LLM consecutive failure — show retry/change-model options."""
        from app.ui_layer.components.types import ChatMessageOption

        session_id = event.data.get("session_id")
        options = [
            ChatMessageOption(label="Retry", value="llm_retry", style="primary"),
            ChatMessageOption(
                label="Change Model", value="llm_change_model", style="default"
            ),
        ]
        asyncio.create_task(
            self._display_chat_message(
                "System",
                "What would you like to do?",
                "system",
                session_id=session_id,
                options=options,
            )
        )

    def _handle_info_message(self, event: UIEvent) -> None:
        """Handle info message event."""
        asyncio.create_task(
            self._display_chat_message(
                "Info",
                event.data.get("message", ""),
                "info",
                session_id=event.task_id,
            )
        )

    def _handle_action_start(self, event: UIEvent) -> None:
        """Handle action start event."""
        if self.action_panel:
            session_id = event.data.get("session_id") or "main"
            asyncio.create_task(
                self.action_panel.add_item(
                    ActionItem(
                        id=event.data.get("action_id", ""),
                        name=event.data.get("action_name", "Action"),
                        status="running",
                        item_type="action",
                        session_id=session_id,
                        input_data=event.data.get("input"),
                    )
                )
            )

    def _handle_action_end(self, event: UIEvent) -> None:
        """Handle action end event."""
        if self.action_panel:
            status = "error" if event.data.get("error") else "completed"
            # Try to match by action_id first, then fall back to name + session
            action_id = event.data.get("action_id", "")
            action_name = event.data.get("action_name", "")
            session_id = event.data.get("session_id") or "main"
            # Get output and error data
            output = event.data.get("output")
            error_message = event.data.get("error_message")
            asyncio.create_task(
                self.action_panel.update_item_by_name(
                    action_name=action_name,
                    session_id=session_id,
                    status=status,
                    action_id=action_id,
                    output=output,
                    error=error_message,
                )
            )

    def _handle_reasoning(self, event: UIEvent) -> None:
        """Handle reasoning event. Override in browser adapter to broadcast
        it into the session's inline activity feed."""
        pass

    def _handle_state_change(self, event: UIEvent) -> None:
        """Handle agent state change event."""
        if self.status_bar:
            asyncio.create_task(
                self.status_bar.set_status(event.data.get("status_message", ""))
            )

    def _handle_gui_mode_change(self, event: UIEvent) -> None:
        """Handle GUI mode change event."""
        if self.footage_component:
            self.footage_component.set_visible(event.data.get("gui_mode", False))

    def _handle_footage_update(self, event: UIEvent) -> None:
        """Handle footage update event."""
        if self.footage_component:
            asyncio.create_task(
                self.footage_component.update(event.data.get("image_bytes", b""))
            )

    def _handle_footage_clear(self, event: UIEvent) -> None:
        """Handle footage clear event."""
        if self.footage_component:
            asyncio.create_task(self.footage_component.clear())

    def _handle_show_menu(self, event: UIEvent) -> None:
        """Handle show menu event. Override in Browser adapter."""
        pass

    def _handle_shutdown(self, event: UIEvent) -> None:
        """Handle shutdown event. Override in adapters for specific cleanup."""
        asyncio.create_task(self.stop())

    # ─────────────────────────────────────────────────────────────────────
    # Helper methods
    # ─────────────────────────────────────────────────────────────────────

    async def _display_chat_message(
        self,
        label: str,
        message: str,
        style: str,
        session_id: Optional[str] = None,
        options: Optional[List[ChatMessageOption]] = None,
        client_id: Optional[str] = None,
    ) -> None:
        """
        Display a chat message.

        Args:
            label: Message sender label
            message: Message content
            style: Style identifier
            session_id: The chat session the message belongs to (main default)
            options: Optional list of interactive options/buttons
            client_id: Optional client-generated UUID for reconciling with optimistic UI
        """
        import time

        await self.chat_component.append_message(
            ChatMessage(
                sender=label,
                content=message,
                style=style,
                timestamp=time.time(),
                session_id=session_id or "main",
                options=options,
                client_id=client_id,
            )
        )

    async def submit_message(
        self, message: str, session_id: Optional[str] = None
    ) -> None:
        """
        Submit a message from the user.

        Routes through the controller for command handling and agent processing.

        Args:
            message: The user's input message
            session_id: The session the message was typed in (main if omitted)
        """
        await self._controller.submit_message(
            message, self._adapter_id, session_id=session_id
        )
