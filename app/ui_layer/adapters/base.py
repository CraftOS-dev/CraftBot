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
from app.ui_layer.components.types import ChatMessage, ActionItem

if TYPE_CHECKING:
    from app.ui_layer.controller.ui_controller import UIController


class InterfaceAdapter(ABC):
    """
    Base class for interface adapters.

    Each interface (CLI, TUI, Browser) extends this to implement
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
            bus.subscribe(UIEventType.INFO_MESSAGE, self._handle_info_message)
        )

        # Task/action events
        self._unsubscribers.append(
            bus.subscribe(UIEventType.TASK_START, self._handle_task_start)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.TASK_END, self._handle_task_end)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.ACTION_START, self._handle_action_start)
        )
        self._unsubscribers.append(
            bus.subscribe(UIEventType.ACTION_END, self._handle_action_end)
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
            self._display_chat_message("You", event.data.get("message", ""), "user")
        )

    def _handle_agent_message(self, event: UIEvent) -> None:
        """Handle agent message event."""
        from app.onboarding import onboarding_manager

        agent_name = onboarding_manager.state.agent_name or "Agent"
        asyncio.create_task(
            self._display_chat_message(
                agent_name, event.data.get("message", ""), "agent"
            )
        )

    def _handle_system_message(self, event: UIEvent) -> None:
        """Handle system message event."""
        asyncio.create_task(
            self._display_chat_message(
                "System", event.data.get("message", ""), "system"
            )
        )

    def _handle_error_message(self, event: UIEvent) -> None:
        """Handle error message event."""
        asyncio.create_task(
            self._display_chat_message("Error", event.data.get("message", ""), "error")
        )

    def _handle_info_message(self, event: UIEvent) -> None:
        """Handle info message event."""
        asyncio.create_task(
            self._display_chat_message("Info", event.data.get("message", ""), "info")
        )

    def _handle_task_start(self, event: UIEvent) -> None:
        """Handle task start event."""
        # Skip task events from main stream (empty task_id).
        # Main stream's task_started events are for conversation history,
        # not for UI task panels.
        task_id = event.data.get("task_id", "")
        if not task_id:
            return

        if self.action_panel:
            asyncio.create_task(
                self.action_panel.add_item(
                    ActionItem(
                        id=task_id,
                        name=event.data.get("task_name", "Task"),
                        status="running",
                        item_type="task",
                    )
                )
            )

    def _handle_task_end(self, event: UIEvent) -> None:
        """Handle task end event."""
        # Skip task events from main stream (empty task_id).
        task_id = event.data.get("task_id", "")
        if not task_id:
            return

        if self.action_panel:
            status = event.data.get("status", "completed")
            asyncio.create_task(
                self.action_panel.update_item(task_id, status)
            )

    def _handle_action_start(self, event: UIEvent) -> None:
        """Handle action start event."""
        if self.action_panel:
            # Use event's task_id if available, otherwise fall back to current task
            # This handles cases where action events go to main stream (task_id="")
            # but should still be associated with the running task
            task_id = event.data.get("task_id") or self._controller.state.current_task_id
            asyncio.create_task(
                self.action_panel.add_item(
                    ActionItem(
                        id=event.data.get("action_id", ""),
                        name=event.data.get("action_name", "Action"),
                        status="running",
                        item_type="action",
                        parent_id=task_id,
                        input_data=event.data.get("input"),
                    )
                )
            )

    def _handle_action_end(self, event: UIEvent) -> None:
        """Handle action end event."""
        if self.action_panel:
            status = "error" if event.data.get("error") else "completed"
            # Try to match by action_id first, then fall back to action_name + task_id
            action_id = event.data.get("action_id", "")
            action_name = event.data.get("action_name", "")
            # Use event's task_id if available, otherwise fall back to current task
            task_id = event.data.get("task_id") or self._controller.state.current_task_id or ""
            # Get output and error data
            output = event.data.get("output")
            error_message = event.data.get("error_message")
            asyncio.create_task(
                self.action_panel.update_item_by_name(
                    action_name=action_name,
                    task_id=task_id,
                    status=status,
                    action_id=action_id,
                    output=output,
                    error=error_message,
                )
            )

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
        """Handle show menu event. Override in TUI/Browser adapters."""
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
    ) -> None:
        """
        Display a chat message.

        Args:
            label: Message sender label
            message: Message content
            style: Style identifier
        """
        import time

        await self.chat_component.append_message(
            ChatMessage(
                sender=label,
                content=message,
                style=style,
                timestamp=time.time(),
            )
        )

    async def submit_message(self, message: str) -> None:
        """
        Submit a message from the user.

        Routes through the controller for command handling and agent processing.

        Args:
            message: The user's input message
        """
        await self._controller.submit_message(message, self._adapter_id)
