"""TUI interface adapter implementation using Textual."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from asyncio import Queue
from typing import TYPE_CHECKING, List, Optional

from rich.text import Text

from app.ui_layer.adapters.base import InterfaceAdapter
from app.ui_layer.themes.base import ThemeAdapter, StyleType
from app.ui_layer.themes.theme import BaseTheme
from app.ui_layer.components.protocols import (
    ChatComponentProtocol,
    ActionPanelProtocol,
    StatusBarProtocol,
    FootageComponentProtocol,
)
from app.ui_layer.components.types import ChatMessage, ActionItem as UIActionItem
from app.ui_layer.events import UIEvent, UIEventType

# Import TUI-specific data types for CraftApp compatibility
from app.tui.data import (
    ActionItem as TUIActionItem,
    ActionPanelUpdate,
    FootageUpdate,
    TimelineEntry,
)

if TYPE_CHECKING:
    from app.ui_layer.controller.ui_controller import UIController
    from app.ui_layer.onboarding import OnboardingFlowController
    from app.tui.app import CraftApp


class TUIThemeAdapter(ThemeAdapter):
    """TUI-specific theme adapter using Rich formatting."""

    def format_text(self, text: str, style_type: StyleType) -> Text:
        """Format text with Rich styling."""
        style = self._theme.get_style(style_type)
        rich_style = style.to_rich()
        return Text(text, style=rich_style)

    def format_chat_message(
        self,
        label: str,
        message: str,
        style_type: StyleType,
    ) -> Text:
        """Format a chat message with Rich styling."""
        style = self._theme.get_style(style_type)
        rich_style = style.to_rich()

        result = Text()
        result.append(f"{label}: ", style=rich_style)
        result.append(message)
        return result

    def format_action_item(
        self,
        name: str,
        status: str,
        is_task: bool,
        indent: int = 0,
    ) -> Text:
        """Format an action panel item."""
        icon = self._theme.get_status_icon(status)
        style_type = self._theme.get_status_style(status)
        style = self._theme.get_style(style_type)
        rich_style = style.to_rich()

        prefix = "  " * indent
        result = Text()
        result.append(f"{prefix}[{icon}] ", style=rich_style)
        result.append(name)
        return result


class TUIChatComponent(ChatComponentProtocol):
    """TUI chat component wrapping queue-based communication."""

    def __init__(self, adapter: "TUIAdapter") -> None:
        self._adapter = adapter
        self._messages: List[ChatMessage] = []

    async def append_message(self, message: ChatMessage) -> None:
        """Queue message for display."""
        self._messages.append(message)
        # Put message in the queue for CraftApp to consume
        await self._adapter.chat_updates.put(
            (message.sender, message.content, message.style)
        )

    async def clear(self) -> None:
        """Clear messages."""
        self._messages.clear()
        # Reinitialize queue to clear pending messages
        self._adapter.chat_updates = Queue()

    def scroll_to_bottom(self) -> None:
        """Request scroll to bottom."""
        pass

    def get_messages(self) -> List[ChatMessage]:
        """Get all messages."""
        return self._messages.copy()


class TUIActionPanelComponent(ActionPanelProtocol):
    """TUI action panel component."""

    def __init__(self, adapter: "TUIAdapter") -> None:
        self._adapter = adapter
        self._items: dict[str, TUIActionItem] = {}
        self._order: list[str] = []

    async def add_item(self, item: UIActionItem) -> None:
        """Add an action item."""
        tui_item = TUIActionItem(
            id=item.id,
            display_name=item.name,
            item_type=item.item_type,
            status=item.status,
            task_id=item.parent_id,
            created_at=time.time(),
        )
        self._items[item.id] = tui_item
        self._order.append(item.id)
        await self._adapter.action_updates.put(ActionPanelUpdate("add", tui_item))

    async def update_item(self, item_id: str, status: str) -> None:
        """Update an item's status."""
        if item_id in self._items:
            self._items[item_id].status = status
            await self._adapter.action_updates.put(
                ActionPanelUpdate("update", self._items[item_id])
            )

    async def update_item_by_name(
        self,
        action_name: str,
        task_id: str,
        status: str,
        action_id: str = "",
        output: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update item status by matching name and task."""
        matched_item = None

        # First try exact ID match if provided
        if action_id and action_id in self._items:
            matched_item = self._items[action_id]

        # Try matching by name + task_id + running status
        if not matched_item and task_id:
            for item_id in reversed(self._order):
                item = self._items.get(item_id)
                if (
                    item
                    and item.item_type == "action"
                    and item.display_name == action_name
                    and item.task_id == task_id
                    and item.status == "running"
                ):
                    matched_item = item
                    break

        # Fallback: match by just name + running status (handles mismatched task_ids)
        if not matched_item:
            for item_id in reversed(self._order):
                item = self._items.get(item_id)
                if (
                    item
                    and item.item_type == "action"
                    and item.display_name == action_name
                    and item.status == "running"
                ):
                    matched_item = item
                    break

        if matched_item:
            matched_item.status = status
            # Note: TUI doesn't display output/error in panel, but params accepted for compatibility
            await self._adapter.action_updates.put(
                ActionPanelUpdate("update", matched_item)
            )

    async def remove_item(self, item_id: str) -> None:
        """Remove an item."""
        if item_id in self._items:
            del self._items[item_id]
            self._order = [i for i in self._order if i != item_id]
            await self._adapter.action_updates.put(
                ActionPanelUpdate("remove", TUIActionItem(id=item_id, display_name="", item_type="", status=""))
            )

    async def update_item_data(
        self,
        item_id: str,
        output: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update an item's output/error data. No-op for TUI."""
        # TUI doesn't display output/error in the panel
        pass

    async def clear(self) -> None:
        """Clear all items."""
        self._items.clear()
        self._order.clear()
        await self._adapter.action_updates.put(ActionPanelUpdate("clear", None))

    async def clear_terminal_tasks(self) -> int:
        """
        Remove tasks whose status is completed/error/cancelled, along with
        their child actions. Running/waiting tasks remain visible.

        Returns:
            Number of tasks removed (does not count child actions).
        """
        terminal_statuses = {"completed", "error", "cancelled"}

        terminal_task_ids = {
            item_id
            for item_id, item in self._items.items()
            if item.item_type == "task" and item.status in terminal_statuses
        }

        if not terminal_task_ids:
            return 0

        removed_ids = [
            item_id
            for item_id, item in list(self._items.items())
            if item_id in terminal_task_ids or item.task_id in terminal_task_ids
        ]

        for item_id in removed_ids:
            self._items.pop(item_id, None)
        self._order = [iid for iid in self._order if iid not in removed_ids]

        for item_id in removed_ids:
            await self._adapter.action_updates.put(
                ActionPanelUpdate(
                    "remove",
                    TUIActionItem(id=item_id, display_name="", item_type="", status=""),
                )
            )

        return len(terminal_task_ids)

    def select_task(self, task_id: Optional[str]) -> None:
        """Select a task for detail view."""
        self._adapter._selected_task_id = task_id

    def get_items(self) -> List[UIActionItem]:
        """Get all items as UIActionItem."""
        return [
            UIActionItem(
                id=self._items[item_id].id,
                name=self._items[item_id].display_name,
                status=self._items[item_id].status,
                item_type=self._items[item_id].item_type,
                parent_id=self._items[item_id].task_id,
            )
            for item_id in self._order
            if item_id in self._items
        ]

    def get_tui_items(self) -> dict[str, TUIActionItem]:
        """Get all items as TUIActionItem dict."""
        return self._items.copy()

    def get_task_items(self) -> List[TUIActionItem]:
        """Get only task items in display order."""
        return [
            self._items[item_id]
            for item_id in self._order
            if item_id in self._items and self._items[item_id].item_type == "task"
        ]

    def get_actions_for_task(self, task_id: str) -> List[TUIActionItem]:
        """Get all actions belonging to a specific task."""
        return [
            item for item in self._items.values()
            if item.item_type == "action" and item.task_id == task_id
        ]


class TUIStatusBarComponent(StatusBarProtocol):
    """TUI status bar component."""

    def __init__(self, adapter: "TUIAdapter") -> None:
        self._adapter = adapter
        self._status: str = "Agent is idle"
        self._loading: bool = False

    async def set_status(self, message: str) -> None:
        """Set the status message."""
        self._status = message
        await self._adapter.status_updates.put(message)

    async def set_loading(self, loading: bool) -> None:
        """Set loading state."""
        self._loading = loading

    def get_status(self) -> str:
        """Get current status."""
        return self._status


class TUIFootageComponent(FootageComponentProtocol):
    """TUI footage display component."""

    def __init__(self, adapter: "TUIAdapter") -> None:
        self._adapter = adapter
        self._image_bytes: Optional[bytes] = None
        self._visible: bool = False

    async def update(self, image_bytes: bytes) -> None:
        """Update the displayed image."""
        self._image_bytes = image_bytes
        await self._adapter.footage_updates.put(
            FootageUpdate(image_bytes=image_bytes, timestamp=time.time())
        )

    async def clear(self) -> None:
        """Clear the display."""
        self._image_bytes = None

    def set_visible(self, visible: bool) -> None:
        """Set visibility."""
        self._visible = visible


class TUIAdapter(InterfaceAdapter):
    """
    TUI interface adapter using Textual.

    This adapter integrates with the existing CraftApp Textual application,
    providing the UI layer interface while maintaining the queue-based
    communication that CraftApp expects.
    """

    # Hidden actions that should not be displayed
    HIDDEN_ACTIONS = {"task_start", "task_update_todos"}

    def __init__(self, controller: "UIController") -> None:
        super().__init__(controller, "tui")
        self._theme_adapter = TUIThemeAdapter(BaseTheme())
        self._chat = TUIChatComponent(self)
        self._action_panel = TUIActionPanelComponent(self)
        self._status_bar = TUIStatusBarComponent(self)
        self._footage = TUIFootageComponent(self)
        self._app: Optional["CraftApp"] = None

        # Queue-based communication for CraftApp compatibility
        self.chat_updates: Queue[TimelineEntry] = Queue()
        self.action_updates: Queue[ActionPanelUpdate] = Queue()
        self.status_updates: Queue[str] = Queue()
        self.footage_updates: Queue[FootageUpdate] = Queue()

        # State tracking
        self._agent_state: str = "idle"
        self._selected_task_id: Optional[str] = None
        self._loading_frame_index: int = 0
        self._gui_mode_ended_flag: bool = False
        self._last_gui_mode: bool = False

    # ─────────────────────────────────────────────────────────────────────
    # CraftApp compatibility properties
    # ─────────────────────────────────────────────────────────────────────

    @property
    def _agent(self):
        """Get the agent (for CraftApp compatibility)."""
        return self._controller.agent

    @property
    def _action_items(self) -> dict:
        """Get action items dict (for CraftApp compatibility)."""
        return self._action_panel._items

    @property
    def _action_order(self) -> list:
        """Get action order list (for CraftApp compatibility)."""
        return self._action_panel._order

    def _generate_status_message(self) -> str:
        """Generate status message (for CraftApp compatibility)."""
        from app.ui_layer.state.store import _generate_status_message
        return _generate_status_message(self._controller.state_store.state)

    @property
    def theme_adapter(self) -> ThemeAdapter:
        return self._theme_adapter

    @property
    def chat_component(self) -> ChatComponentProtocol:
        return self._chat

    @property
    def action_panel(self) -> ActionPanelProtocol:
        return self._action_panel

    @property
    def status_bar(self) -> StatusBarProtocol:
        return self._status_bar

    @property
    def footage_component(self) -> FootageComponentProtocol:
        return self._footage

    async def _on_start(self) -> None:
        """Start the TUI interface."""
        # Suppress console logging for Textual
        self._suppress_console_logging()

        # Check for onboarding (lazy import to avoid circular dependency)
        from app.ui_layer.onboarding import OnboardingFlowController
        onboarding = OnboardingFlowController(self._controller)
        if onboarding.needs_hard_onboarding:
            # Run onboarding before starting Textual app
            await self._run_hard_onboarding(onboarding)

        # Trigger soft onboarding if needed (after hard onboarding check)
        from app.onboarding import onboarding_manager
        if onboarding_manager.needs_soft_onboarding:
            import asyncio
            agent = self._controller.agent
            if agent:
                asyncio.create_task(agent.trigger_soft_onboarding())

        # Queue initial messages
        from app.config import get_app_version
        await self.chat_updates.put(
            ("System", f"CraftBot v{get_app_version()} ready. Type /help for more info and /exit to quit.", "system")
        )
        await self.status_updates.put("Agent is idle")

        # Set footage callback on agent for GUI mode
        from app.gui.handler import GUIHandler
        self._controller.agent._tui_footage_callback = self.push_footage
        if GUIHandler.gui_module:
            GUIHandler.gui_module.set_tui_footage_callback(self.push_footage)

        # Create and run the Textual app
        from app.tui.app import CraftApp

        default_provider = self._controller.config.default_provider
        default_api_key = self._controller.config.default_api_key
        self._app = CraftApp(self, default_provider, default_api_key)

        # Emit ready event
        self._controller.event_bus.emit(
            UIEvent(
                type=UIEventType.INTERFACE_READY,
                data={"adapter": "tui"},
                source_adapter=self._adapter_id,
            )
        )

        # Run the app (this blocks until the app exits)
        await self._app.run_async()

    async def _on_stop(self) -> None:
        """Stop the TUI interface."""
        if self._app and self._app.is_running:
            self._app.exit()

    def _suppress_console_logging(self) -> None:
        """Suppress console logging for Textual."""
        root_logger = logging.getLogger()
        handlers_to_remove = []
        for handler in root_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                if handler.stream in (sys.stdout, sys.stderr):
                    handlers_to_remove.append(handler)

        for handler in handlers_to_remove:
            root_logger.removeHandler(handler)

        # Also suppress named loggers
        for name in list(logging.Logger.manager.loggerDict.keys()):
            named_logger = logging.getLogger(name)
            handlers_to_remove = []
            for handler in named_logger.handlers:
                if isinstance(handler, logging.StreamHandler):
                    if handler.stream in (sys.stdout, sys.stderr):
                        handlers_to_remove.append(handler)
            for handler in handlers_to_remove:
                named_logger.removeHandler(handler)

        if not root_logger.handlers:
            root_logger.addHandler(logging.NullHandler())

    async def _run_hard_onboarding(
        self, onboarding: OnboardingFlowController
    ) -> None:
        """Run hard onboarding using Textual screens."""
        # For now, run simple CLI-style onboarding before Textual starts
        try:
            from app.tui.onboarding import run_tui_hard_onboarding
            await run_tui_hard_onboarding(onboarding)
        except ImportError:
            # Fall back to simple CLI onboarding
            await self._run_simple_onboarding(onboarding)

    async def _run_simple_onboarding(
        self, onboarding: OnboardingFlowController
    ) -> None:
        """Simple CLI-style onboarding fallback."""
        print("\nWelcome to CraftBot! Let's set up your agent.\n")

        while not onboarding.is_complete and not onboarding.is_cancelled:
            step_info = onboarding.get_step_info()

            print(f"\n{step_info['progress']}")
            print(f"{step_info['title']}")
            print(f"{step_info['description']}\n")

            options = step_info["options"]
            if options:
                for i, opt in enumerate(options, 1):
                    default_marker = " (default)" if opt.default else ""
                    print(f"  {i}. {opt.label}{default_marker}")

                selection = input("Enter choice: ").strip()
                try:
                    idx = int(selection) - 1
                    if 0 <= idx < len(options):
                        value = options[idx].value
                    else:
                        continue
                except ValueError:
                    value = selection
            else:
                default = step_info["default"]
                value = input(f"Enter value [{default}]: ").strip() or default

            if onboarding.submit_step_value(value):
                onboarding.next_step()

    # ─────────────────────────────────────────────────────────────────────
    # Public methods for CraftApp compatibility
    # ─────────────────────────────────────────────────────────────────────

    async def push_footage(self, image_bytes: bytes, container_id: str = "") -> None:
        """Push a new screenshot to the footage display."""
        await self.footage_updates.put(
            FootageUpdate(image_bytes=image_bytes, timestamp=time.time(), container_id=container_id)
        )

    def signal_gui_mode_end(self) -> None:
        """Signal that GUI mode has ended."""
        self._gui_mode_ended_flag = True

    def gui_mode_ended(self) -> bool:
        """Check if GUI mode has ended since last check."""
        if self._gui_mode_ended_flag:
            self._gui_mode_ended_flag = False
            return True
        return False

    def notify_provider(self, provider: str) -> None:
        """Notify about provider change."""
        self.chat_updates.put_nowait(
            ("System", f"Launching agent with provider: {provider}", "system")
        )

    def configure_provider(self, provider: str, api_key: str) -> None:
        """Configure provider settings (saves to settings.json and syncs to os.environ)."""
        from app.tui.settings import save_settings_to_json
        # save_settings_to_json handles both persistence and os.environ sync
        save_settings_to_json(provider, api_key)

    async def request_shutdown(self) -> None:
        """Stop the interface and close the Textual application."""
        await self.stop()
        self._controller.agent.is_running = False

    def submit_user_input(self, text: str) -> None:
        """Submit user input from the Textual app."""
        asyncio.create_task(self.submit_message(text))

    async def submit_user_message(self, message: str) -> None:
        """Submit user message (for CraftApp compatibility)."""
        await self.submit_message(message)

    # Delegate methods for CraftApp action panel access
    def get_actions_for_task(self, task_id: str) -> List[TUIActionItem]:
        """Get all actions belonging to a specific task."""
        return self._action_panel.get_actions_for_task(task_id)

    def get_task_items(self) -> List[TUIActionItem]:
        """Get only task items in display order."""
        return self._action_panel.get_task_items()

    def format_chat_entry(self, label: str, message: str, style: str):
        """Format a chat entry for display."""
        from rich.table import Table
        from rich.text import Text

        _STYLE_COLORS = {
            "user": "bold #ffffff",
            "agent": "bold #ff4f18",
            "action": "bold #a0a0a0",
            "task": "bold #ff4f18",
            "error": "bold #ff4f18",
            "info": "bold #666666",
            "system": "bold #a0a0a0",
        }

        colour = _STYLE_COLORS.get(style, _STYLE_COLORS["info"])
        label_text = f"{label}:"
        label_width = 7

        table = Table.grid(padding=(0, 1))
        table.expand = True
        table.add_column(
            "label",
            width=label_width,
            min_width=label_width,
            max_width=label_width,
            style=colour,
            no_wrap=True,
            justify="left",
        )
        table.add_column("message", ratio=1)

        label_cell = Text(label_text, style=colour, no_wrap=True)
        message_text = Text(str(message))
        message_text.no_wrap = False
        message_text.overflow = "fold"

        table.add_row(label_cell, message_text)
        return table

    def format_action_item(self, item: TUIActionItem):
        """Format an ActionItem for display in the action panel."""
        from rich.table import Table
        from rich.text import Text

        ICON_COMPLETED = "+"
        ICON_ERROR = "x"
        ICON_LOADING_FRAMES = ["●", "○"]

        if item.status == "completed":
            status_icon = ICON_COMPLETED
        elif item.status == "error":
            status_icon = ICON_ERROR
        else:
            status_icon = ICON_LOADING_FRAMES[self._loading_frame_index % len(ICON_LOADING_FRAMES)]

        if item.item_type == "task":
            label_text = f"[{status_icon}]"
            colour = "bold #ff4f18"
            message = item.display_name
        else:
            label_text = f"[{status_icon}]"
            colour = "bold #a0a0a0"
            message = f"    {item.display_name}" if item.task_id else item.display_name

        label_width = 5
        table = Table.grid(padding=(0, 1))
        table.expand = True
        table.add_column(
            "label",
            width=label_width,
            min_width=label_width,
            max_width=label_width,
            style=colour,
            no_wrap=True,
            justify="left",
        )
        table.add_column("message", ratio=1)

        label_cell = Text(label_text, style=colour, no_wrap=True)
        message_text = Text(str(message))
        message_text.no_wrap = False
        message_text.overflow = "fold"

        table.add_row(label_cell, message_text)
        return table

    def clear_logs(self) -> None:
        """Clear display logs via app."""
        if self._app:
            self._app.clear_logs()

    # ─────────────────────────────────────────────────────────────────────
    # Override event handlers for TUI-specific behavior
    # ─────────────────────────────────────────────────────────────────────

    def _handle_user_message(self, event: UIEvent) -> None:
        """Handle user message - display in chat."""
        message = event.data.get("message", "")
        asyncio.create_task(
            self.chat_updates.put(("You", message, "user"))
        )

    def _handle_agent_message(self, event: UIEvent) -> None:
        """Handle agent message - display in chat."""
        from app.onboarding import onboarding_manager
        agent_name = onboarding_manager.state.agent_name or "Agent"
        message = event.data.get("message", "")
        asyncio.create_task(
            self.chat_updates.put((agent_name, message, "agent"))
        )

    def _handle_system_message(self, event: UIEvent) -> None:
        """Handle system message - check for clear command."""
        if event.data.get("is_clear_command"):
            asyncio.create_task(self._chat.clear())
            asyncio.create_task(self._action_panel.clear())
        else:
            message = event.data.get("message", "")
            asyncio.create_task(
                self.chat_updates.put(("System", message, "system"))
            )

    def _handle_error_message(self, event: UIEvent) -> None:
        """Handle error message - display in chat."""
        message = event.data.get("message", "")
        asyncio.create_task(
            self.chat_updates.put(("Error", message, "error"))
        )

    def _handle_info_message(self, event: UIEvent) -> None:
        """Handle info message - display in chat."""
        message = event.data.get("message", "")
        asyncio.create_task(
            self.chat_updates.put(("Info", message, "info"))
        )

    def _handle_task_start(self, event: UIEvent) -> None:
        """Handle task start - add to action panel."""
        self._agent_state = "working"
        task_id = event.data.get("task_id", "")
        task_name = event.data.get("task_name", "Task")

        # Check if task already exists (placeholder)
        if task_id in self._action_panel._items:
            self._action_panel._items[task_id].display_name = task_name
            self._action_panel._items[task_id].status = "running"
            asyncio.create_task(
                self.action_updates.put(ActionPanelUpdate("update", self._action_panel._items[task_id]))
            )
        else:
            item = TUIActionItem(
                id=task_id,
                display_name=task_name,
                item_type="task",
                status="running",
                task_id=None,
                created_at=time.time(),
            )
            self._action_panel._items[task_id] = item
            self._action_panel._order.append(task_id)
            asyncio.create_task(self.action_updates.put(ActionPanelUpdate("add", item)))

        # Update status
        asyncio.create_task(self._update_status())

    def _handle_task_end(self, event: UIEvent) -> None:
        """Handle task end - update action panel."""
        task_id = event.data.get("task_id", "")
        status = event.data.get("status", "completed")

        # Find task by ID first
        if task_id in self._action_panel._items:
            self._action_panel._items[task_id].status = status
            asyncio.create_task(
                self.action_updates.put(ActionPanelUpdate("update", self._action_panel._items[task_id]))
            )
        else:
            # If task not found by ID, find any running task and mark as completed
            for item in self._action_panel._items.values():
                if item.item_type == "task" and item.status == "running":
                    item.status = status
                    asyncio.create_task(
                        self.action_updates.put(ActionPanelUpdate("update", item))
                    )
                    break

        # Also mark all running actions under this task as completed
        for item in self._action_panel._items.values():
            if item.item_type == "action" and item.status == "running":
                if not task_id or item.task_id == task_id:
                    item.status = status
                    asyncio.create_task(
                        self.action_updates.put(ActionPanelUpdate("update", item))
                    )

        if not self._has_running_work():
            self._agent_state = "idle"

        asyncio.create_task(self._update_status())

    def _handle_action_start(self, event: UIEvent) -> None:
        """Handle action start - add to action panel."""
        self._agent_state = "working"
        action_name = event.data.get("action_name", "Action")
        task_id = event.data.get("task_id", "")

        # Skip hidden actions
        base_name = action_name.split(" with ")[0].lower().replace(" ", "_")
        if base_name in self.HIDDEN_ACTIONS:
            return

        # Create placeholder task if needed
        if task_id and task_id not in self._action_panel._items:
            task_item = TUIActionItem(
                id=task_id,
                display_name="Starting task...",
                item_type="task",
                status="running",
                task_id=None,
                created_at=time.time(),
            )
            self._action_panel._items[task_id] = task_item
            self._action_panel._order.append(task_id)
            asyncio.create_task(self.action_updates.put(ActionPanelUpdate("add", task_item)))

        # Create action item
        action_id = event.data.get("action_id", f"{task_id or 'main'}:{action_name}:{time.time()}")
        item = TUIActionItem(
            id=action_id,
            display_name=action_name,
            item_type="action",
            status="running",
            task_id=task_id,
            created_at=time.time(),
        )
        self._action_panel._items[action_id] = item
        self._action_panel._order.append(action_id)
        asyncio.create_task(self.action_updates.put(ActionPanelUpdate("add", item)))

        asyncio.create_task(self._update_status())

    def _handle_action_end(self, event: UIEvent) -> None:
        """Handle action end - update action panel."""
        action_name = event.data.get("action_name", "Action")
        status = "error" if event.data.get("error") else "completed"

        # Find running action - try exact match first, then partial match
        found_item = None
        for item_id, item in self._action_panel._items.items():
            if item.item_type == "action" and item.status == "running":
                # Exact match
                if item.display_name == action_name:
                    found_item = item
                    break
                # Partial match (action name contained in display name or vice versa)
                if action_name in item.display_name or item.display_name in action_name:
                    found_item = item
                    break

        # If still not found, mark the oldest running action as completed
        if not found_item:
            running_actions = [
                item for item in self._action_panel._items.values()
                if item.item_type == "action" and item.status == "running"
            ]
            if running_actions:
                # Get the oldest running action
                found_item = min(running_actions, key=lambda x: x.created_at)

        if found_item:
            found_item.status = status
            asyncio.create_task(self.action_updates.put(ActionPanelUpdate("update", found_item)))

        if not self._has_running_work() and self._agent_state == "working":
            self._agent_state = "idle"

        asyncio.create_task(self._update_status())

    def _handle_show_menu(self, event: UIEvent) -> None:
        """Handle show menu - switch to menu view in CraftApp."""
        if self._app:
            self._app.show_menu = True

    def _handle_shutdown(self, event: UIEvent) -> None:
        """Handle shutdown - exit the Textual app."""
        if self._app and self._app.is_running:
            self._app.exit()

    def _has_running_work(self) -> bool:
        """Check if there are any running tasks or actions."""
        for item in self._action_panel._items.values():
            if item.status == "running":
                return True
        return False

    async def _update_status(self) -> None:
        """Update status message."""
        ICON_LOADING_FRAMES = ["●", "○"]
        loading_icon = ICON_LOADING_FRAMES[self._loading_frame_index % len(ICON_LOADING_FRAMES)]

        running_tasks = [
            item for item in self._action_panel._items.values()
            if item.item_type == "task" and item.status == "running"
        ]

        if running_tasks:
            if len(running_tasks) == 1:
                status = f"{loading_icon} Working on: {running_tasks[0].display_name}"
            else:
                task_names = ", ".join(t.display_name for t in running_tasks[:2])
                if len(running_tasks) > 2:
                    status = f"{loading_icon} Working on: {task_names} (+{len(running_tasks) - 2} more)"
                else:
                    status = f"{loading_icon} Working on: {task_names}"
        elif self._agent_state == "idle":
            status = "Agent is idle"
        elif self._agent_state == "working":
            status = f"{loading_icon} Agent is working..."
        elif self._agent_state == "waiting_for_user":
            status = "⏸ Waiting for your response"
        else:
            status = "Agent is idle"

        await self.status_updates.put(status)
