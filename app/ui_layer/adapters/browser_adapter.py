"""Browser interface adapter using WebSocket."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from aiohttp.client_exceptions import ClientConnectionResetError

from agent_core.utils.logger import logger
from app.config import AGENT_WORKSPACE_ROOT
from app.ui_layer.adapters.base import InterfaceAdapter
from app.ui_layer.settings import (
    # General settings
    read_agent_file,
    write_agent_file,
    restore_agent_file,
    reset_agent_state,
    get_general_settings,
    update_general_settings,
    # Proactive mode control
    get_proactive_mode,
    set_proactive_mode,
    # Proactive/scheduler settings
    get_scheduler_config,
    update_scheduler_config,
    toggle_schedule_runtime,
    get_recurring_tasks,
    add_recurring_task,
    update_recurring_task,
    remove_recurring_task,
    reset_recurring_tasks,
    reload_proactive_manager,
    # Memory settings
    get_memory_mode,
    set_memory_mode,
    get_memory_items,
    add_memory_item,
    update_memory_item,
    remove_memory_item,
    reset_memory,
    clear_unprocessed_events,
    get_memory_stats,
    # Model settings
    get_available_providers,
    get_model_settings,
    update_model_settings,
    test_connection,
    validate_can_save,
    get_ollama_models,
    # MCP settings
    list_mcp_servers,
    add_mcp_server_from_json,
    remove_mcp_server,
    enable_mcp_server,
    disable_mcp_server,
    get_server_env_vars,
    update_mcp_server_env,
    # Skill settings
    list_skills,
    get_skill_info,
    enable_skill,
    disable_skill,
    reload_skills,
    get_skill_search_directories,
    install_skill_from_path,
    install_skill_from_git,
    create_skill_scaffold,
    get_skill_template,
    remove_skill,
    # Integration settings
    list_integrations,
    get_integration_info,
    connect_integration_token,
    connect_integration_oauth,
    connect_integration_interactive,
    disconnect_integration,
    # WhatsApp QR code flow
    start_whatsapp_qr_session,
    check_whatsapp_session_status,
    cancel_whatsapp_session,
)
from app.ui_layer.themes.base import ThemeAdapter, StyleType
from app.ui_layer.themes.theme import BaseTheme
from app.ui_layer.components.protocols import (
    ChatComponentProtocol,
    ActionPanelProtocol,
    StatusBarProtocol,
    FootageComponentProtocol,
)
from app.ui_layer.components.types import ChatMessage, ActionItem, Attachment
from app.ui_layer.events import UIEvent, UIEventType
from app.ui_layer.onboarding import OnboardingFlowController
from app.ui_layer.metrics import MetricsCollector
from app.living_ui import (
    LivingUIManager,
    LivingUIProject,
    set_living_ui_manager,
    register_broadcast_callbacks,
    make_todo_broadcast_hook,
)

if TYPE_CHECKING:
    from app.ui_layer.controller.ui_controller import UIController
    from aiohttp import web


class BrowserThemeAdapter(ThemeAdapter):
    """Browser-specific theme adapter outputting CSS-compatible styles."""

    def format_text(self, text: str, style_type: StyleType) -> Dict[str, Any]:
        """Format text with CSS styling info."""
        style = self._theme.get_style(style_type)
        return {
            "text": text,
            "style": style.to_css(),
            "styleType": style_type.value,
        }

    def format_chat_message(
        self,
        label: str,
        message: str,
        style_type: StyleType,
    ) -> Dict[str, Any]:
        """Format a chat message for browser."""
        style = self._theme.get_style(style_type)
        return {
            "label": label,
            "message": message,
            "style": style.to_css(),
            "styleType": style_type.value,
        }

    def format_action_item(
        self,
        name: str,
        status: str,
        is_task: bool,
        indent: int = 0,
    ) -> Dict[str, Any]:
        """Format an action panel item for browser."""
        icon = self._theme.get_status_icon(status)
        style_type = self._theme.get_status_style(status)
        style = self._theme.get_style(style_type)

        return {
            "name": name,
            "status": status,
            "icon": icon,
            "isTask": is_task,
            "indent": indent,
            "style": style.to_css(),
        }

    def get_theme_css(self) -> str:
        """Get CSS variables for the theme."""
        theme = self._theme
        return f"""
:root {{
    --color-primary: {theme.COLOR_PRIMARY};
    --color-white: {theme.COLOR_WHITE};
    --color-gray: {theme.COLOR_GRAY};
    --color-dark-gray: {theme.COLOR_DARK_GRAY};
    --color-black: {theme.COLOR_BLACK};
    --color-red: {theme.COLOR_RED};
    --color-green: {theme.COLOR_GREEN};
    --color-blue: {theme.COLOR_BLUE};
    --color-yellow: {theme.COLOR_YELLOW};
}}
"""


class BrowserChatComponent(ChatComponentProtocol):
    """Browser chat component sending messages via WebSocket."""

    def __init__(self, adapter: "BrowserAdapter") -> None:
        self._adapter = adapter
        self._messages: List[ChatMessage] = []
        self._storage = None
        self._init_storage()

    def _init_storage(self) -> None:
        """Initialize storage and load persisted messages."""
        try:
            from app.usage.chat_storage import get_chat_storage, StoredChatMessage
            self._storage = get_chat_storage()

            # Load recent messages from storage (initial page)
            stored_messages = self._storage.get_recent_messages(limit=50)
            for stored in stored_messages:
                attachments = None
                if stored.attachments:
                    attachments = [
                        Attachment(
                            name=att.get("name", ""),
                            path=att.get("path", ""),
                            type=att.get("type", ""),
                            size=att.get("size", 0),
                            url=att.get("url", ""),
                        )
                        for att in stored.attachments
                    ]
                options = None
                if stored.options:
                    from app.ui_layer.components.types import ChatMessageOption
                    options = [
                        ChatMessageOption(
                            label=o.get("label", ""),
                            value=o.get("value", ""),
                            style=o.get("style", "default"),
                        )
                        for o in stored.options
                    ]
                self._messages.append(ChatMessage(
                    sender=stored.sender,
                    content=stored.content,
                    style=stored.style,
                    timestamp=stored.timestamp,
                    message_id=stored.message_id,
                    attachments=attachments,
                    task_session_id=stored.task_session_id,
                    options=options,
                    option_selected=stored.option_selected,
                ))
        except Exception:
            # Storage may not be available, continue without persistence
            pass

    async def append_message(self, message: ChatMessage) -> None:
        """Append message and broadcast to clients."""
        self._messages.append(message)

        # Persist to storage
        if self._storage:
            try:
                from app.usage.chat_storage import StoredChatMessage
                attachments_data = None
                if message.attachments:
                    attachments_data = [
                        {
                            "name": att.name,
                            "path": att.path,
                            "type": att.type,
                            "size": att.size,
                            "url": att.url,
                        }
                        for att in message.attachments
                    ]
                options_data = None
                if message.options:
                    options_data = [
                        {"label": o.label, "value": o.value, "style": o.style}
                        for o in message.options
                    ]
                stored = StoredChatMessage(
                    message_id=message.message_id or f"{message.sender}:{message.timestamp}",
                    sender=message.sender,
                    content=message.content,
                    style=message.style,
                    timestamp=message.timestamp,
                    attachments=attachments_data,
                    task_session_id=message.task_session_id,
                    options=options_data,
                )
                self._storage.insert_message(stored)
            except Exception:
                pass

        # Build message data with optional attachments
        message_data: Dict[str, Any] = {
            "sender": message.sender,
            "content": message.content,
            "style": message.style,
            "timestamp": message.timestamp,
            "messageId": message.message_id,
        }

        # Include client_id so the browser can reconcile its optimistic pending bubble
        if message.client_id:
            message_data["clientId"] = message.client_id

        # Include attachments if present
        if message.attachments:
            message_data["attachments"] = [
                {
                    "name": att.name,
                    "path": att.path,
                    "type": att.type,
                    "size": att.size,
                    "url": att.url,
                }
                for att in message.attachments
            ]

        # Include task session ID for reply feature
        if message.task_session_id:
            message_data["taskSessionId"] = message.task_session_id

        # Include options/buttons if present
        if message.options:
            message_data["options"] = [
                {"label": o.label, "value": o.value, "style": o.style}
                for o in message.options
            ]
        if message.option_selected:
            message_data["optionSelected"] = message.option_selected

        await self._adapter._broadcast({
            "type": "chat_message",
            "data": message_data,
        })

    async def clear(self) -> None:
        """Clear messages and notify clients."""
        self._messages.clear()

        # Clear from storage
        if self._storage:
            try:
                self._storage.clear_messages()
            except Exception:
                pass

        await self._adapter._broadcast({
            "type": "chat_clear",
        })

    def scroll_to_bottom(self) -> None:
        """No-op - handled by frontend."""
        pass

    def get_messages(self) -> List[ChatMessage]:
        """Get all loaded messages."""
        return self._messages.copy()

    def get_messages_before(self, before_timestamp: float, limit: int = 50) -> List[ChatMessage]:
        """Get older messages from storage before a given timestamp."""
        if not self._storage:
            return []
        try:
            stored = self._storage.get_messages_before(before_timestamp, limit=limit)
            messages = []
            for s in stored:
                attachments = None
                if s.attachments:
                    attachments = [
                        Attachment(
                            name=att.get("name", ""),
                            path=att.get("path", ""),
                            type=att.get("type", ""),
                            size=att.get("size", 0),
                            url=att.get("url", ""),
                        )
                        for att in s.attachments
                    ]
                options = None
                if s.options:
                    from app.ui_layer.components.types import ChatMessageOption
                    options = [
                        ChatMessageOption(
                            label=o.get("label", ""),
                            value=o.get("value", ""),
                            style=o.get("style", "default"),
                        )
                        for o in s.options
                    ]
                messages.append(ChatMessage(
                    sender=s.sender,
                    content=s.content,
                    style=s.style,
                    timestamp=s.timestamp,
                    message_id=s.message_id,
                    attachments=attachments,
                    options=options,
                    option_selected=s.option_selected,
                ))
            return messages
        except Exception:
            return []

    def get_total_count(self) -> int:
        """Get total message count from storage."""
        if not self._storage:
            return len(self._messages)
        try:
            return self._storage.get_message_count()
        except Exception:
            return len(self._messages)


class BrowserActionPanelComponent(ActionPanelProtocol):
    """Browser action panel component."""

    def __init__(self, adapter: "BrowserAdapter") -> None:
        self._adapter = adapter
        self._items: List[ActionItem] = []
        self._storage = None
        self._init_storage()

    def _init_storage(self) -> None:
        """Initialize storage and load persisted actions."""
        try:
            from app.usage.action_storage import get_action_storage, StoredActionItem
            self._storage = get_action_storage()

            # Mark stale running items as cancelled, but exclude restored tasks
            restored_ids = getattr(
                self._adapter._controller.agent, '_restored_task_ids', set()
            )
            self._storage.mark_running_as_cancelled(exclude=restored_ids)

            # Load recent tasks (and their child actions) from storage
            stored_items = self._storage.get_recent_tasks_with_actions(task_limit=15)
            for stored in stored_items:
                self._items.append(ActionItem(
                    id=stored.id,
                    name=stored.name,
                    status=stored.status,
                    item_type=stored.item_type,
                    parent_id=stored.parent_id,
                    created_at=stored.created_at,
                    completed_at=stored.completed_at,
                    input_data=stored.input_data,
                    output_data=stored.output_data,
                    error_message=stored.error_message,
                ))
        except Exception:
            # Storage may not be available, continue without persistence
            pass

    def _persist_item(self, item: ActionItem) -> None:
        """Persist an action item to storage."""
        if self._storage:
            try:
                from app.usage.action_storage import StoredActionItem
                stored = StoredActionItem(
                    id=item.id,
                    name=item.name,
                    status=item.status,
                    item_type=item.item_type,
                    parent_id=item.parent_id,
                    created_at=item.created_at,
                    completed_at=item.completed_at,
                    input_data=item.input_data,
                    output_data=item.output_data,
                    error_message=item.error_message,
                )
                self._storage.insert_item(stored)
            except Exception:
                pass

    async def add_item(self, item: ActionItem) -> None:
        """Add item and broadcast. Prevents duplicates by ID."""
        # Check if item with same ID already exists
        for existing in self._items:
            if existing.id == item.id:
                # Item already exists, just update its status if needed
                if existing.status != item.status:
                    await self.update_item(existing.id, item.status)
                return

        self._items.append(item)

        # Persist to storage
        self._persist_item(item)

        await self._adapter._broadcast({
            "type": "action_add",
            "data": {
                "id": item.id,
                "name": item.name,
                "status": item.status,
                "itemType": item.item_type,
                "parentId": item.parent_id,
                "createdAt": int(item.created_at * 1000),
                "duration": item.duration,
                "input": item.input_data,
                "output": item.output_data,
                "error": item.error_message,
            },
        })

    async def update_item(self, item_id: str, status: str) -> None:
        """Update item status by ID and broadcast."""
        matched_item = None
        for item in self._items:
            if item.id == item_id:
                item.status = status
                # Record completion time for completed/error/cancelled status
                if status in ("completed", "error", "cancelled") and item.completed_at is None:
                    item.completed_at = time.time()
                matched_item = item
                break

        if matched_item:
            # Persist update to storage
            self._persist_item(matched_item)

            await self._adapter._broadcast({
                "type": "action_update",
                "data": {
                    "id": item_id,
                    "status": status,
                    "duration": matched_item.duration,
                    "output": matched_item.output_data,
                    "error": matched_item.error_message,
                },
            })

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
        if action_id:
            for item in self._items:
                if item.id == action_id:
                    matched_item = item
                    break

        # Try matching by name + parent_id + running status
        if not matched_item and task_id:
            for item in reversed(self._items):
                if (
                    item.item_type == "action"
                    and item.name == action_name
                    and item.parent_id == task_id
                    and item.status == "running"
                ):
                    matched_item = item
                    break

        # Fallback: match by just name + running status (handles mismatched task_ids)
        if not matched_item:
            for item in reversed(self._items):
                if (
                    item.item_type == "action"
                    and item.name == action_name
                    and item.status == "running"
                ):
                    matched_item = item
                    break

        if matched_item:
            matched_item.status = status
            # Record completion time for completed/error/cancelled status
            if status in ("completed", "error", "cancelled") and matched_item.completed_at is None:
                matched_item.completed_at = time.time()
            # Set output and error data
            if output is not None:
                matched_item.output_data = output
            if error is not None:
                matched_item.error_message = error

            # Persist update to storage
            self._persist_item(matched_item)

            await self._adapter._broadcast({
                "type": "action_update",
                "data": {
                    "id": matched_item.id,
                    "status": status,
                    "duration": matched_item.duration,
                    "output": matched_item.output_data,
                    "error": matched_item.error_message,
                },
            })

    async def update_item_data(
        self,
        item_id: str,
        output: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update an item's output/error data."""
        matched_item = None
        for item in self._items:
            if item.id == item_id:
                if output is not None:
                    item.output_data = output
                if error is not None:
                    item.error_message = error
                matched_item = item
                break

        if matched_item:
            # Persist update to storage
            self._persist_item(matched_item)

            await self._adapter._broadcast({
                "type": "action_update",
                "data": {
                    "id": item_id,
                    "status": matched_item.status,
                    "duration": matched_item.duration,
                    "output": matched_item.output_data,
                    "error": matched_item.error_message,
                },
            })

    async def remove_item(self, item_id: str) -> None:
        """Remove item and broadcast."""
        self._items = [i for i in self._items if i.id != item_id]

        # Remove from storage
        if self._storage:
            try:
                self._storage.delete_item(item_id)
            except Exception:
                pass

        await self._adapter._broadcast({
            "type": "action_remove",
            "data": {"id": item_id},
        })

    async def clear(self) -> None:
        """Clear all items and broadcast."""
        self._items.clear()

        # Clear from storage
        if self._storage:
            try:
                self._storage.clear_items()
            except Exception:
                pass

        await self._adapter._broadcast({
            "type": "action_clear",
        })

    async def clear_terminal_tasks(self) -> int:
        """
        Remove tasks whose status is completed/error/cancelled, along with
        their child actions. Running/waiting tasks remain visible.

        Returns:
            Number of tasks removed (does not count child actions).
        """
        terminal_statuses = {"completed", "error", "cancelled"}

        # Find terminal task IDs in the in-memory list
        terminal_task_ids = {
            item.id
            for item in self._items
            if item.item_type == "task" and item.status in terminal_statuses
        }

        if not terminal_task_ids:
            return 0

        # Remove the tasks themselves and any actions that belong to them
        removed_ids = [
            item.id
            for item in self._items
            if item.id in terminal_task_ids or item.parent_id in terminal_task_ids
        ]
        self._items = [
            item
            for item in self._items
            if item.id not in terminal_task_ids and item.parent_id not in terminal_task_ids
        ]

        # Mirror in storage so a refresh doesn't bring them back. We let
        # storage compute its own ID set rather than pass our list, since
        # storage may carry tasks not currently loaded in memory.
        if self._storage:
            try:
                self._storage.clear_terminal_tasks()
            except Exception:
                pass

        # Tell each connected client to drop the removed items individually,
        # so any other (running) tasks they're watching stay in place.
        for item_id in removed_ids:
            await self._adapter._broadcast({
                "type": "action_remove",
                "data": {"id": item_id},
            })

        return len(terminal_task_ids)

    def select_task(self, task_id: Optional[str]) -> None:
        """Select task - handled by frontend."""
        pass

    def get_items(self) -> List[ActionItem]:
        """Get all loaded items."""
        return self._items.copy()

    def get_tasks_before(self, before_timestamp: float, task_limit: int = 15) -> List[ActionItem]:
        """Get older tasks (and their child actions) from storage."""
        if not self._storage:
            return []
        try:
            stored = self._storage.get_tasks_before(before_timestamp, task_limit=task_limit)
            return [
                ActionItem(
                    id=s.id,
                    name=s.name,
                    status=s.status,
                    item_type=s.item_type,
                    parent_id=s.parent_id,
                    created_at=s.created_at,
                    completed_at=s.completed_at,
                    input_data=s.input_data,
                    output_data=s.output_data,
                    error_message=s.error_message,
                )
                for s in stored
            ]
        except Exception:
            return []

    def get_task_count(self) -> int:
        """Get total task count (not actions) from storage."""
        if not self._storage:
            return len([i for i in self._items if i.item_type == 'task'])
        try:
            return self._storage.get_task_count()
        except Exception:
            return len([i for i in self._items if i.item_type == 'task'])


class BrowserStatusBarComponent(StatusBarProtocol):
    """Browser status bar component."""

    def __init__(self, adapter: "BrowserAdapter") -> None:
        self._adapter = adapter
        self._status: str = "Agent is idle"
        self._loading: bool = False

    async def set_status(self, message: str) -> None:
        """Set status and broadcast."""
        self._status = message
        await self._adapter._broadcast({
            "type": "status_update",
            "data": {
                "message": message,
                "loading": self._loading,
            },
        })

    async def set_loading(self, loading: bool) -> None:
        """Set loading state and broadcast."""
        self._loading = loading
        await self._adapter._broadcast({
            "type": "status_update",
            "data": {
                "message": self._status,
                "loading": loading,
            },
        })

    def get_status(self) -> str:
        """Get current status."""
        return self._status


class BrowserFootageComponent(FootageComponentProtocol):
    """Browser footage component."""

    def __init__(self, adapter: "BrowserAdapter") -> None:
        self._adapter = adapter
        self._visible: bool = False

    async def update(self, image_bytes: bytes) -> None:
        """Update footage - send as base64."""
        import base64

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        await self._adapter._broadcast({
            "type": "footage_update",
            "data": {
                "image": f"data:image/png;base64,{b64}",
            },
        })

    async def clear(self) -> None:
        """Clear footage."""
        await self._adapter._broadcast({
            "type": "footage_clear",
        })

    def set_visible(self, visible: bool) -> None:
        """Set visibility."""
        self._visible = visible
        asyncio.create_task(self._adapter._broadcast({
            "type": "footage_visibility",
            "data": {"visible": visible},
        }))


class BrowserAdapter(InterfaceAdapter):
    """
    Browser interface adapter using WebSocket.

    Provides a web-based interface for CraftBot accessible via browser.
    Communicates with the React frontend via WebSocket.
    """

    def __init__(
        self,
        controller: "UIController",
        host: str = "localhost",
        port: int = 7926,
    ) -> None:
        super().__init__(controller, "browser")
        self._host = host
        self._port = int(os.environ.get("BROWSER_PORT", port))
        self._theme_adapter = BrowserThemeAdapter(BaseTheme())
        self._chat = BrowserChatComponent(self)
        self._action_panel = BrowserActionPanelComponent(self)
        self._status_bar = BrowserStatusBarComponent(self)
        self._footage = BrowserFootageComponent(self)
        self._app: Optional["web.Application"] = None
        self._ws_clients: Set = set()
        self._metrics_subscribers: Set = set()
        self._runner: Optional["web.AppRunner"] = None
        self._started_at: float = 0.0
        self._ws_prepare_failures: int = 0

        # Dashboard metrics collector
        self._metrics_collector = MetricsCollector(controller.agent)
        self._metrics_task: Optional[asyncio.Task] = None

        # Track active OAuth tasks for cancellation support
        self._oauth_tasks: Dict[str, asyncio.Task] = {}

        # Living UI manager
        template_path = Path(__file__).parent.parent.parent / "data" / "living_ui_template"
        self._living_ui_manager = LivingUIManager(
            workspace_root=AGENT_WORKSPACE_ROOT,
            template_path=template_path
        )
        # Bind task_manager and trigger_queue for task creation
        agent = self._controller.agent
        self._living_ui_manager.bind_task_manager(agent.task_manager, agent.triggers)

        # Clean up orphan processes and folders from previous sessions
        self._living_ui_manager.cleanup_on_startup()

        # Start watchdog to monitor running Living UI processes
        self._living_ui_manager.start_watchdog()

        # Auto-launch projects that have auto_launch enabled
        asyncio.create_task(self._living_ui_manager.auto_launch_projects())

        # Register global accessor and callbacks for Living UI actions
        set_living_ui_manager(self._living_ui_manager)
        register_broadcast_callbacks(
            broadcast_ready=self.broadcast_living_ui_ready,
            broadcast_progress=self.broadcast_living_ui_progress,
            broadcast_todos=self.broadcast_living_ui_todos,
        )

        # Subscribe the Living UI module to TaskManager todo updates so that
        # the agent's task breakdown streams to the browser automatically.
        agent.task_manager.add_post_update_todos_hook(make_todo_broadcast_hook())

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

    @property
    def metrics_collector(self) -> MetricsCollector:
        """Get the metrics collector for dashboard data."""
        return self._metrics_collector

    async def submit_message(
        self,
        message: str,
        reply_context: Optional[Dict[str, Any]] = None,
        living_ui_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> None:
        """
        Submit a message from the user with optional reply context.

        Overrides base class to handle reply-to-chat/task feature.
        Appends reply context to the message before routing to the agent.

        Args:
            message: The user's input message
            reply_context: Optional dict with {sessionId?: str, originalMessage: str}
            living_ui_id: Optional Living UI project ID if user is on a Living UI page
            client_id: Optional client-generated UUID for reconciling optimistic UI
        """
        agent_context = message

        # Add reply context note (similar to attachment_note pattern)
        if reply_context and reply_context.get("originalMessage"):
            reply_note = f"\n\n[REPLYING TO PREVIOUS AGENT MESSAGE]:\n{reply_context['originalMessage']}"
            agent_context = message + reply_note

        # Pass to controller with target session ID if replying
        target_session_id = reply_context.get("sessionId") if reply_context else None
        await self._controller.submit_message(
            agent_context,
            self._adapter_id,
            target_session_id=target_session_id,
            client_id=client_id,
            living_ui_id=living_ui_id
        )

    def _handle_task_start(self, event: UIEvent) -> None:
        """Handle task start event with metrics tracking."""
        # Call parent implementation
        super()._handle_task_start(event)

        # Track in metrics collector
        task_id = event.data.get("task_id", "")
        task_name = event.data.get("task_name", "Task")
        if task_id:
            self._metrics_collector.record_task_start(task_id, task_name)

    def _handle_task_end(self, event: UIEvent) -> None:
        """Handle task end event with metrics tracking."""
        # Call parent implementation
        super()._handle_task_end(event)

        # Track in metrics collector
        task_id = event.data.get("task_id", "")
        task_name = event.data.get("task_name", "Task")
        status = event.data.get("status", "completed")
        if task_id:
            self._metrics_collector.record_task_end(task_id, task_name, status)

    def _handle_reasoning(self, event: UIEvent) -> None:
        """Handle reasoning event - display in Tasks page only."""
        # Add reasoning as an action item with item_type="reasoning"
        # This will be displayed in the Tasks page but filtered out of
        # the Chat page's action panel
        task_id = event.data.get("task_id") or self._controller.state.current_task_id
        reasoning_id = event.data.get("reasoning_id", "")
        content = event.data.get("content", "")

        asyncio.create_task(
            self._action_panel.add_item(
                ActionItem(
                    id=reasoning_id,
                    name="Reasoning",
                    status="completed",  # Reasoning is always complete
                    item_type="reasoning",
                    parent_id=task_id,
                    output_data=content,  # Store reasoning content in output
                )
            )
        )

    async def _on_start(self) -> None:
        """Start the browser interface."""
        from aiohttp import web
        from app.onboarding import onboarding_manager
        import uuid

        # Display welcome system message if soft onboarding is pending
        if onboarding_manager.needs_soft_onboarding:
            welcome_message = ChatMessage(
                sender="System",
                content="""**Welcome to CraftBot**

CraftBot can perform virtually any computer-based task by configuring the right MCP servers, skills, or connecting to apps.

If you need help setting up MCP servers or skills, just ask the agent.

A quick Q&A will now begin to understand your objectives to serve you better:""",
                style="system",
                timestamp=time.time(),
                message_id=f"welcome-{uuid.uuid4().hex[:8]}",
            )
            self._chat._messages.insert(0, welcome_message)

        self._app = web.Application()

        # API and WebSocket routes (must be registered first)
        self._app.router.add_get("/ws", self._websocket_handler)
        self._app.router.add_get("/api/state", self._state_handler)
        self._app.router.add_get("/api/theme.css", self._theme_css_handler)
        self._app.router.add_get("/api/workspace/{path:.*}", self._workspace_file_handler)
        self._app.router.add_get("/api/agent-profile-picture", self._agent_profile_picture_handler)

        # Living UI export/import routes
        self._app.router.add_get("/api/living-ui/{project_id}/export", self._living_ui_export_handler)
        self._app.router.add_post("/api/living-ui/import", self._living_ui_import_handler)

        # Integration bridge routes (Living UI → external APIs)
        from app.living_ui.integration_bridge import IntegrationBridge
        self._integration_bridge = IntegrationBridge(self._living_ui_manager)
        self._integration_bridge.register_routes(self._app)

        # Serve Vite-built frontend (production)
        frontend_dist = Path(__file__).parent.parent / "browser" / "frontend" / "dist"
        if frontend_dist.exists():
            # Serve static assets from /assets/
            assets_path = frontend_dist / "assets"
            if assets_path.exists():
                self._app.router.add_static("/assets/", assets_path)

            # Serve static files from dist/ (public/ files copied by Vite build)
            # This must come before the SPA catch-all so images, fonts, etc. are served directly
            _dist = frontend_dist  # capture for closure

            async def _static_or_spa(request: web.Request) -> web.StreamResponse:
                """Serve static file from dist/ if it exists, otherwise index.html for SPA routing."""
                req_path = request.match_info.get("path", "")
                if req_path:
                    file_path = _dist / req_path
                    if file_path.is_file():
                        return web.FileResponse(file_path)
                return web.FileResponse(_dist / "index.html")

            self._app.router.add_get("/", self._spa_handler)
            self._app.router.add_get("/{path:.*}", _static_or_spa)
        else:
            # Fallback to inline HTML for development without build
            self._app.router.add_get("/", self._index_handler)
            self._app.router.add_get("/{path:.*}", self._index_handler)

        # Serve static files if they exist (legacy)
        static_path = Path(__file__).parent.parent / "browser" / "static"
        if static_path.exists():
            self._app.router.add_static("/static/", static_path)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        self._started_at = time.monotonic()

        # Only print URL info if not using browser startup UI (run.py handles it)
        import os
        if os.getenv("BROWSER_STARTUP_UI", "0") != "1":
            print(f"\nCraftBot Browser Interface running at http://{self._host}:{self._port}")
            print("Open this URL in your browser to interact with CraftBot.\n")

        # Emit ready event
        self._controller.event_bus.emit(
            UIEvent(
                type=UIEventType.INTERFACE_READY,
                data={
                    "adapter": "browser",
                    "url": f"http://{self._host}:{self._port}",
                },
                source_adapter=self._adapter_id,
            )
        )

        # Start metrics broadcasting task
        self._metrics_task = asyncio.create_task(self._broadcast_metrics_loop())

        # Keep running
        while self._running and self._controller.agent.is_running:
            await asyncio.sleep(1)

    async def _on_stop(self) -> None:
        """Stop the browser interface."""
        # Stop all running Living UI projects
        if self._living_ui_manager:
            await self._living_ui_manager.stop_all_projects()

        # Close integration bridge HTTP client
        if hasattr(self, '_integration_bridge'):
            await self._integration_bridge.cleanup()

        # Cancel metrics broadcasting task
        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass

        # Close all WebSocket connections
        for ws in self._ws_clients.copy():
            await ws.close()
        self._ws_clients.clear()

        # Shut down the aiohttp server and release the port
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def _websocket_handler(self, request: "web.Request") -> "web.WebSocketResponse":
        """Handle WebSocket connections."""
        from aiohttp import web, WSMsgType
        import asyncio

        ws = web.WebSocketResponse(
            max_msg_size=100 * 1024 * 1024,
            heartbeat=30.0,  # Send ping every 30s to keep connection alive
        )
        
        try:
            await ws.prepare(request)
        except ClientConnectionResetError:
            # Benign: the client (browser) aborted the TCP connection before the WebSocket
            # handshake could complete. Happens routinely in dev with React.StrictMode /
            # Vite HMR double-mounting WS providers, and on page navigations. Nothing to do.
            self._ws_prepare_failures += 1
            return ws
        except Exception as e:
            import traceback as _tb
            self._ws_prepare_failures += 1
            try:
                peer = request.transport.get_extra_info("peername") if request.transport else None
            except Exception:
                peer = None
            user_agent = request.headers.get("User-Agent", "")
            attempt_id = request.query.get("attempt", "")
            uptime_s = (time.monotonic() - self._started_at) if self._started_at else -1.0
            print(
                "[BROWSER ADAPTER] Failed to prepare WebSocket: "
                f"err={type(e).__name__}: {e} | peer={peer} | attempt_id={attempt_id} "
                f"| clients={len(self._ws_clients)} | uptime_s={uptime_s:.1f} "
                f"| failures={self._ws_prepare_failures} | ua={user_agent!r}\n"
                f"{_tb.format_exc()}"
            )
            return ws
        
        is_first_client = len(self._ws_clients) == 0
        self._ws_clients.add(ws)

        # Trigger soft onboarding on first client connection so the UI
        # is ready to receive the task creation event.
        if is_first_client:
            from app.onboarding import onboarding_manager
            if onboarding_manager.needs_soft_onboarding:
                agent = self._controller.agent
                if agent:
                    import asyncio
                    asyncio.create_task(agent.trigger_soft_onboarding())

        # Send initial state
        try:
            initial_state = self._get_initial_state()
            await ws.send_json({
                "type": "init",
                "data": initial_state,
            })
        except (ConnectionResetError, ClientConnectionResetError, RuntimeError) as e:
            # Gracefully handle connection closing
            self._ws_clients.discard(ws)
            return ws
        except Exception as e:
            self._ws_clients.discard(ws)
            return ws

        # Message loop
        try:
            async for msg in ws:
                try:
                    if msg.type == WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        await self._handle_ws_message(data, ws)
                    elif msg.type == WSMsgType.ERROR:
                        break
                    elif msg.type == WSMsgType.CLOSE:
                        break
                except json.JSONDecodeError as e:
                    # Continue on JSON errors, don't close connection
                    import traceback
                    error_detail = f"JSON decode error: {e}"
                    print(f"[BROWSER ADAPTER] {error_detail}")
                    await self._broadcast_error_to_chat(error_detail)
                except Exception as e:
                    # Continue on message errors, don't close connection
                    import traceback
                    error_detail = f"WebSocket message error: {type(e).__name__}: {e}\n{traceback.format_exc()}"
                    print(f"[BROWSER ADAPTER] {error_detail}")
                    await self._broadcast_error_to_chat(error_detail)
        except asyncio.CancelledError:
            print("[BROWSER ADAPTER] WebSocket cancelled")
        except (ClientConnectionResetError, ConnectionResetError) as e:
            print(f"[BROWSER ADAPTER] WebSocket connection reset: {type(e).__name__}: {e}")
        except Exception as e:
            import traceback
            print(f"[BROWSER ADAPTER] WebSocket loop error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        finally:
            self._ws_clients.discard(ws)
            self._metrics_subscribers.discard(ws)

        return ws

    async def _handle_ws_message(self, data: Dict[str, Any], ws=None) -> None:
        """Handle incoming WebSocket message."""
        msg_type = data.get("type")

        if msg_type == "message":
            # User sent a message (may include attachments and/or reply context)
            content = data.get("content", "")
            attachments = data.get("attachments", [])
            reply_context = data.get("replyContext")  # {sessionId?: str, originalMessage: str}
            living_ui_id = data.get("livingUIId")  # Set when user is on a Living UI page
            client_id = data.get("clientId")
            if living_ui_id:
                logger.info(f"[BROWSER ADAPTER] Message from Living UI page: {living_ui_id}")

            # Dispatch chat submission as a background task so the WS message loop
            # can immediately read the next frame. Otherwise rapid-fire sends are
            # serialised behind each message's routing-LLM call (~1s each), which
            # makes optimistic bubbles un-gray one-by-one instead of all at once.
            if attachments:
                asyncio.create_task(
                    self._handle_chat_message_with_attachments(
                        content, attachments, reply_context, living_ui_id, client_id
                    )
                )
            elif content:
                asyncio.create_task(
                    self.submit_message(content, reply_context, living_ui_id, client_id)
                )

        elif msg_type == "chat_attachment_upload":
            # Upload attachment for chat message
            await self._handle_chat_attachment_upload(data)

        elif msg_type == "command":
            # User sent a command
            command = data.get("command", "")
            if command:
                await self.submit_message(command)

        elif msg_type == "chat_history":
            before_timestamp = data.get("beforeTimestamp")
            limit = data.get("limit", 50)
            await self._handle_chat_history(before_timestamp, limit)

        elif msg_type == "action_history":
            before_timestamp = data.get("beforeTimestamp")
            limit = data.get("limit", 15)
            await self._handle_action_history(before_timestamp, limit)

        # File operations
        elif msg_type == "file_list":
            directory = data.get("directory", "")
            offset = data.get("offset", 0)
            limit = data.get("limit", 50)
            search = data.get("search", "")
            await self._handle_file_list(directory, offset=offset, limit=limit, search=search)

        elif msg_type == "file_read":
            file_path = data.get("path", "")
            await self._handle_file_read(file_path)

        elif msg_type == "file_write":
            file_path = data.get("path", "")
            content = data.get("content", "")
            await self._handle_file_write(file_path, content)

        elif msg_type == "file_create":
            file_path = data.get("path", "")
            file_type = data.get("fileType", "file")  # "file" or "directory"
            await self._handle_file_create(file_path, file_type)

        elif msg_type == "file_delete":
            file_path = data.get("path", "")
            await self._handle_file_delete(file_path)

        elif msg_type == "file_rename":
            old_path = data.get("oldPath", "")
            new_name = data.get("newName", "")
            await self._handle_file_rename(old_path, new_name)

        elif msg_type == "file_batch_delete":
            paths = data.get("paths", [])
            await self._handle_file_batch_delete(paths)

        elif msg_type == "file_move":
            src_path = data.get("srcPath", "")
            dest_path = data.get("destPath", "")
            await self._handle_file_move(src_path, dest_path)

        elif msg_type == "file_copy":
            src_path = data.get("srcPath", "")
            dest_path = data.get("destPath", "")
            await self._handle_file_copy(src_path, dest_path)

        elif msg_type == "file_upload":
            file_path = data.get("path", "")
            content_b64 = data.get("content", "")
            await self._handle_file_upload(file_path, content_b64)

        elif msg_type == "file_download":
            file_path = data.get("path", "")
            await self._handle_file_download(file_path)

        elif msg_type == "open_file":
            file_path = data.get("path", "")
            await self._handle_open_file(file_path)

        elif msg_type == "open_folder":
            file_path = data.get("path", "")
            await self._handle_open_folder(file_path)

        # Task control
        elif msg_type == "task_cancel":
            task_id = data.get("taskId", "")
            await self._handle_task_cancel(task_id)

        elif msg_type == "option_click":
            value = data.get("value", "")
            session_id = data.get("sessionId", "")
            message_id = data.get("messageId", "")
            await self._handle_option_click(value, session_id, message_id)

        # Settings operations
        elif msg_type == "settings_get":
            await self._handle_settings_get()

        elif msg_type == "settings_update":
            settings = data.get("settings", {})
            await self._handle_settings_update(settings)

        elif msg_type == "agent_file_read":
            filename = data.get("filename", "")
            await self._handle_agent_file_read(filename)

        elif msg_type == "agent_file_write":
            filename = data.get("filename", "")
            content = data.get("content", "")
            await self._handle_agent_file_write(filename, content)

        elif msg_type == "agent_file_restore":
            filename = data.get("filename", "")
            await self._handle_agent_file_restore(filename)

        elif msg_type == "agent_profile_picture_upload":
            await self._handle_agent_profile_picture_upload(data)

        elif msg_type == "agent_profile_picture_remove":
            await self._handle_agent_profile_picture_remove()

        elif msg_type == "reset":
            await self._handle_reset()

        elif msg_type == "clear_conversation":
            await self._handle_clear_conversation()

        elif msg_type == "clear_tasks":
            await self._handle_clear_tasks()

        # Scheduler/Proactive operations
        elif msg_type == "scheduler_config_get":
            await self._handle_scheduler_config_get()

        elif msg_type == "scheduler_config_update":
            updates = data.get("updates", {})
            await self._handle_scheduler_config_update(updates)

        elif msg_type == "proactive_tasks_get":
            frequency = data.get("frequency")
            await self._handle_proactive_tasks_get(frequency)

        elif msg_type == "proactive_task_add":
            task_data = data.get("task", {})
            await self._handle_proactive_task_add(task_data)

        elif msg_type == "proactive_task_update":
            task_id = data.get("taskId", "")
            updates = data.get("updates", {})
            await self._handle_proactive_task_update(task_id, updates)

        elif msg_type == "proactive_task_remove":
            task_id = data.get("taskId", "")
            await self._handle_proactive_task_remove(task_id)

        elif msg_type == "proactive_tasks_reset":
            await self._handle_proactive_tasks_reset()

        elif msg_type == "proactive_file_read":
            await self._handle_proactive_file_read()

        elif msg_type == "proactive_mode_get":
            await self._handle_proactive_mode_get()

        elif msg_type == "proactive_mode_set":
            enabled = data.get("enabled", True)
            await self._handle_proactive_mode_set(enabled)

        # Memory operations
        elif msg_type == "memory_mode_get":
            await self._handle_memory_mode_get()

        elif msg_type == "memory_mode_set":
            enabled = data.get("enabled", True)
            await self._handle_memory_mode_set(enabled)

        elif msg_type == "memory_items_get":
            await self._handle_memory_items_get()

        elif msg_type == "memory_item_add":
            category = data.get("category", "")
            content = data.get("content", "")
            await self._handle_memory_item_add(category, content)

        elif msg_type == "memory_item_update":
            item_id = data.get("itemId", "")
            category = data.get("category")
            content = data.get("content")
            await self._handle_memory_item_update(item_id, category, content)

        elif msg_type == "memory_item_remove":
            item_id = data.get("itemId", "")
            await self._handle_memory_item_remove(item_id)

        elif msg_type == "memory_reset":
            await self._handle_memory_reset()

        elif msg_type == "memory_stats_get":
            await self._handle_memory_stats_get()

        elif msg_type == "memory_process_trigger":
            await self._handle_memory_process_trigger()

        # Model settings operations
        elif msg_type == "model_providers_get":
            await self._handle_model_providers_get()

        elif msg_type == "model_settings_get":
            await self._handle_model_settings_get()

        elif msg_type == "model_settings_update":
            await self._handle_model_settings_update(data)

        elif msg_type == "model_connection_test":
            provider = data.get("provider", "")
            api_key = data.get("apiKey")
            base_url = data.get("baseUrl")
            model = data.get("model")
            await self._handle_model_connection_test(provider, api_key, base_url, model)

        elif msg_type == "model_validate_save":
            await self._handle_model_validate_save(data)

        elif msg_type == "ollama_models_get":
            base_url = data.get("baseUrl")
            await self._handle_ollama_models_get(base_url)

        elif msg_type == "openrouter_models_get":
            await self._handle_openrouter_models_get(
                base_url=data.get("baseUrl"),
                force_refresh=bool(data.get("forceRefresh", False)),
            )

        elif msg_type == "openrouter_credits_get":
            await self._handle_openrouter_credits_get(
                api_key=data.get("apiKey"),
                base_url=data.get("baseUrl"),
            )

        elif msg_type == "slow_mode_get":
            await self._handle_slow_mode_get()

        elif msg_type == "slow_mode_set":
            await self._handle_slow_mode_set(data)

        # MCP settings operations
        elif msg_type == "mcp_list":
            await self._handle_mcp_list()

        elif msg_type == "mcp_enable":
            name = data.get("name", "")
            await self._handle_mcp_enable(name)

        elif msg_type == "mcp_disable":
            name = data.get("name", "")
            await self._handle_mcp_disable(name)

        elif msg_type == "mcp_remove":
            name = data.get("name", "")
            await self._handle_mcp_remove(name)

        elif msg_type == "mcp_add_json":
            name = data.get("name", "")
            config = data.get("config", "{}")
            await self._handle_mcp_add_json(name, config)

        elif msg_type == "mcp_get_env":
            name = data.get("name", "")
            await self._handle_mcp_get_env(name)

        elif msg_type == "mcp_update_env":
            name = data.get("name", "")
            env_key = data.get("key", "")
            env_value = data.get("value", "")
            await self._handle_mcp_update_env(name, env_key, env_value)

        # Skill settings operations
        elif msg_type == "skill_list":
            await self._handle_skill_list()

        elif msg_type == "skill_info":
            name = data.get("name", "")
            await self._handle_skill_info(name)

        elif msg_type == "skill_enable":
            name = data.get("name", "")
            await self._handle_skill_enable(name)

        elif msg_type == "skill_disable":
            name = data.get("name", "")
            await self._handle_skill_disable(name)

        elif msg_type == "skill_reload":
            await self._handle_skill_reload()

        elif msg_type == "skill_install":
            source = data.get("source", "")
            await self._handle_skill_install(source)

        elif msg_type == "skill_create":
            name = data.get("name", "")
            description = data.get("description", "")
            content = data.get("content", "")
            await self._handle_skill_create(name, description, content)

        elif msg_type == "skill_remove":
            name = data.get("name", "")
            await self._handle_skill_remove(name)

        elif msg_type == "skill_dirs":
            await self._handle_skill_dirs()

        elif msg_type == "skill_template":
            name = data.get("name", "")
            description = data.get("description", "")
            await self._handle_skill_template(name, description)

        elif msg_type == "skill_run":
            name = data.get("name", "")
            args_text = data.get("args", "")
            await self._handle_skill_run(name, args_text)

        # Integration handlers
        elif msg_type == "integration_list":
            await self._handle_integration_list()

        elif msg_type == "integration_info":
            integration_id = data.get("id", "")
            await self._handle_integration_info(integration_id)

        elif msg_type == "integration_connect_token":
            integration_id = data.get("id", "")
            credentials = data.get("credentials", {})
            await self._handle_integration_connect_token(integration_id, credentials)

        elif msg_type == "integration_connect_oauth":
            integration_id = data.get("id", "")
            await self._handle_integration_connect_oauth(integration_id)

        elif msg_type == "integration_connect_interactive":
            integration_id = data.get("id", "")
            await self._handle_integration_connect_interactive(integration_id)

        elif msg_type == "integration_connect_cancel":
            integration_id = data.get("id", "")
            await self._handle_integration_connect_cancel(integration_id)

        elif msg_type == "integration_disconnect":
            integration_id = data.get("id", "")
            account_id = data.get("account_id")
            await self._handle_integration_disconnect(integration_id, account_id)

        # Jira settings handlers
        elif msg_type == "jira_get_settings":
            await self._handle_jira_get_settings()

        elif msg_type == "jira_update_settings":
            watch_tag = data.get("watch_tag")
            watch_labels = data.get("watch_labels")
            await self._handle_jira_update_settings(watch_tag=watch_tag, watch_labels=watch_labels)

        # GitHub settings handlers
        elif msg_type == "github_get_settings":
            await self._handle_github_get_settings()

        elif msg_type == "github_update_settings":
            watch_tag = data.get("watch_tag")
            watch_repos = data.get("watch_repos")
            await self._handle_github_update_settings(watch_tag=watch_tag, watch_repos=watch_repos)

        # Living UI settings handlers
        elif msg_type == "living_ui_settings_get":
            await self._handle_living_ui_settings_get()

        elif msg_type == "living_ui_project_action":
            project_id = data.get("projectId", "")
            action = data.get("action", "")
            await self._handle_living_ui_project_action(project_id, action)

        elif msg_type == "living_ui_project_setting_update":
            project_id = data.get("projectId", "")
            setting = data.get("setting", "")
            value = data.get("value")
            await self._handle_living_ui_project_setting_update(project_id, setting, value)

        elif msg_type == "living_ui_marketplace_list":
            await self._handle_marketplace_list()

        elif msg_type == "living_ui_marketplace_install":
            app_id = data.get("appId", "")
            app_name = data.get("appName", "")
            app_description = data.get("appDescription", "")
            custom_fields = data.get("customFields", {})
            # Run as background task so the WS loop stays unblocked for concurrent installs
            asyncio.create_task(self._handle_marketplace_install(app_id, app_name, app_description, custom_fields))

        elif msg_type == "living_ui_import":
            source = data.get("source", "")
            name = data.get("name", "External App")
            asyncio.create_task(self._handle_living_ui_import(source, name))

        # WhatsApp QR code flow handlers
        elif msg_type == "whatsapp_start_qr":
            await self._handle_whatsapp_start_qr()

        elif msg_type == "whatsapp_check_status":
            session_id = data.get("session_id", "")
            await self._handle_whatsapp_check_status(session_id)

        elif msg_type == "whatsapp_cancel":
            session_id = data.get("session_id", "")
            await self._handle_whatsapp_cancel(session_id)

        elif msg_type == "subscribe_dashboard_metrics":
            if ws is not None:
                self._metrics_subscribers.add(ws)

        elif msg_type == "unsubscribe_dashboard_metrics":
            if ws is not None:
                self._metrics_subscribers.discard(ws)

        elif msg_type == "dashboard_metrics_filter":
            period = data.get("period", "total")
            await self._handle_dashboard_metrics_filter(period)

        # Onboarding handlers
        elif msg_type == "onboarding_step_get":
            await self._handle_onboarding_step_get()

        elif msg_type == "onboarding_step_submit":
            value = data.get("value")
            await self._handle_onboarding_step_submit(value)

        elif msg_type == "onboarding_skip":
            await self._handle_onboarding_skip()

        elif msg_type == "onboarding_back":
            await self._handle_onboarding_back()

        # Local LLM (Ollama) helpers
        elif msg_type == "local_llm_check":
            await self._handle_local_llm_check()
        elif msg_type == "local_llm_test":
            url = data.get("url", "http://localhost:11434")
            await self._handle_local_llm_test(url)
        elif msg_type == "local_llm_install":
            await self._handle_local_llm_install()
        elif msg_type == "local_llm_start":
            await self._handle_local_llm_start()
        elif msg_type == "local_llm_suggested_models":
            await self._handle_local_llm_suggested_models()
        elif msg_type == "local_llm_pull_model":
            model = data.get("model", "")
            base_url = data.get("baseUrl")
            await self._handle_local_llm_pull_model(model, base_url)
        # Living UI handlers
        elif msg_type == "living_ui_create":
            await self._handle_living_ui_create(data)

        elif msg_type == "living_ui_list":
            await self._handle_living_ui_list()

        elif msg_type == "living_ui_launch":
            project_id = data.get("projectId", "")
            await self._handle_living_ui_launch(project_id)

        elif msg_type == "living_ui_stop":
            project_id = data.get("projectId", "")
            await self._handle_living_ui_stop(project_id)

        elif msg_type == "living_ui_delete":
            project_id = data.get("projectId", "")
            await self._handle_living_ui_delete(project_id)

        elif msg_type == "living_ui_state_update":
            await self._handle_living_ui_state_update(data)

        elif msg_type == "living_ui_tunnel_start":
            project_id = data.get("projectId", "")
            provider = data.get("provider", "cloudflared")
            await self._handle_living_ui_tunnel_start(project_id, provider)

        elif msg_type == "living_ui_tunnel_stop":
            project_id = data.get("projectId", "")
            await self._handle_living_ui_tunnel_stop(project_id)

        elif msg_type == "living_ui_sharing_info":
            project_id = data.get("projectId", "")
            await self._handle_living_ui_sharing_info(project_id)

        # Update operations
        elif msg_type == "check_update":
            await self._handle_check_update()

        elif msg_type == "do_update":
            await self._handle_do_update()

    async def _handle_check_update(self) -> None:
        """Check if a CraftBot update is available."""
        from app.updater import check_for_update

        try:
            update_available, current, latest = await check_for_update()
            await self._broadcast({
                "type": "update_check_result",
                "data": {
                    "updateAvailable": update_available,
                    "currentVersion": current,
                    "latestVersion": latest,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "update_check_result",
                "data": {
                    "updateAvailable": False,
                    "currentVersion": "",
                    "latestVersion": "",
                    "error": str(e),
                },
            })

    async def _handle_do_update(self) -> None:
        """Perform CraftBot update and restart."""
        from app.updater import perform_update

        async def progress(msg: str) -> None:
            await self._broadcast({
                "type": "update_progress",
                "data": {"message": msg},
            })

        try:
            await perform_update(progress_callback=progress)
        except Exception as e:
            await self._broadcast({
                "type": "update_progress",
                "data": {"message": f"Update failed: {e}"},
            })

    async def _handle_dashboard_metrics_filter(self, period: str) -> None:
        """Handle filtered metrics request for specific time period."""
        try:
            from app.ui_layer.metrics.collector import TimePeriod

            # Parse period string to enum
            try:
                period_enum = TimePeriod(period)
            except ValueError:
                period_enum = TimePeriod.TOTAL

            filtered_metrics = self._metrics_collector.get_filtered_metrics(period_enum)

            await self._broadcast({
                "type": "dashboard_filtered_metrics",
                "data": filtered_metrics.to_dict(),
            })
        except Exception as e:
            await self._broadcast({
                "type": "dashboard_filtered_metrics",
                "data": {
                    "error": str(e),
                    "period": period,
                },
            })

    # -------------------------------------------------------------------------
    # Onboarding Handlers
    # -------------------------------------------------------------------------

    def _get_onboarding_controller(self) -> "OnboardingFlowController":
        """Get or create the onboarding flow controller."""
        if not hasattr(self, "_onboarding_controller"):
            self._onboarding_controller = OnboardingFlowController(self._controller)
        return self._onboarding_controller

    async def _handle_onboarding_step_get(self) -> None:
        """Get current onboarding step info."""
        try:
            controller = self._get_onboarding_controller()

            if not controller.needs_hard_onboarding:
                await self._broadcast({
                    "type": "onboarding_step",
                    "data": {
                        "success": True,
                        "completed": True,
                    },
                })
                return

            step = controller.get_current_step()
            options = controller.get_step_options()

            await self._broadcast({
                "type": "onboarding_step",
                "data": {
                    "success": True,
                    "completed": False,
                    "step": {
                        "name": step.name,
                        "title": step.title,
                        "description": step.description,
                        "required": step.required,
                        "index": controller.current_step_index,
                        "total": controller.total_steps,
                        "options": [
                            {
                                "value": opt.value,
                                "label": opt.label,
                                "description": opt.description,
                                "default": opt.default,
                                "icon": opt.icon,
                                "requires_setup": opt.requires_setup,
                            }
                            for opt in options
                        ],
                        "default": controller.get_step_default(),
                        "provider": getattr(step, "provider", None),
                        "form_fields": self._get_step_form_fields(step),
                    },
                },
            })
        except Exception as e:
            logger.error(f"[ONBOARDING] Error getting step: {e}")
            await self._broadcast({
                "type": "onboarding_step",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    @staticmethod
    def _get_step_form_fields(step) -> Optional[list]:
        """Extract form field definitions from a step, if it supports them."""
        form_fields = getattr(step, 'get_form_fields', lambda: [])()
        if not form_fields:
            return None
        return [
            {
                "name": f.name,
                "label": f.label,
                "field_type": f.field_type,
                "options": [
                    {"value": o.value, "label": o.label, "description": o.description, "default": o.default}
                    for o in f.options
                ],
                "default": f.default,
                "placeholder": f.placeholder,
            }
            for f in form_fields
        ]

    async def _handle_onboarding_step_submit(self, value: Any) -> None:
        """Submit a value for the current onboarding step."""
        try:
            controller = self._get_onboarding_controller()

            # Validate the value
            is_valid, error = controller.validate_step_value(value)

            if not is_valid:
                await self._broadcast({
                    "type": "onboarding_submit",
                    "data": {
                        "success": False,
                        "error": error or "Invalid value",
                        "index": controller.current_step_index,
                    },
                })
                return

            # For API key step, test the connection before proceeding
            step = controller.get_current_step()
            if step.name == "api_key":
                provider = controller.get_collected_data().get("provider", "openai")
                if provider == "remote":
                    # Test Ollama connection with the submitted URL
                    ollama_url = (value or "http://localhost:11434").strip()
                    from app.ui_layer.local_llm_setup import test_ollama_connection_sync
                    test_result = test_ollama_connection_sync(ollama_url)
                    if not test_result.get("success"):
                        err = test_result.get("error", "Cannot reach Ollama")
                        await self._broadcast({
                            "type": "onboarding_submit",
                            "data": {
                                "success": False,
                                "error": f"Ollama connection failed: {err}",
                                "index": controller.current_step_index,
                            },
                        })
                        return
                    # Normalise the value to the URL that actually worked
                    value = ollama_url
                elif value:
                    test_result = test_connection(
                        provider=provider,
                        api_key=value,
                    )
                    if not test_result.get("success"):
                        error_msg = test_result.get("error") or test_result.get("message") or "Connection test failed"
                        await self._broadcast({
                            "type": "onboarding_submit",
                            "data": {
                                "success": False,
                                "error": f"Invalid API key: {error_msg}",
                                "index": controller.current_step_index,
                            },
                        })
                        return

            # Submit the value
            controller.submit_step_value(value)

            # Move to next step
            has_more = controller.next_step()

            if not has_more:
                # Onboarding complete - controller._complete() already called
                from app.onboarding import onboarding_manager

                from app.ui_layer.settings.general_settings import get_agent_profile_picture_info
                picture_info = get_agent_profile_picture_info()
                await self._broadcast({
                    "type": "onboarding_complete",
                    "data": {
                        "success": True,
                        "agentName": onboarding_manager.state.agent_name or "Agent",
                        "agentProfilePictureUrl": picture_info["url"],
                        "agentProfilePictureHasCustom": picture_info["has_custom"],
                    },
                })
                # Clear cached controller for fresh state
                if hasattr(self, "_onboarding_controller"):
                    delattr(self, "_onboarding_controller")
            else:
                # Send next step info
                step = controller.get_current_step()
                options = controller.get_step_options()

                await self._broadcast({
                    "type": "onboarding_submit",
                    "data": {
                        "success": True,
                        "nextStep": {
                            "name": step.name,
                            "title": step.title,
                            "description": step.description,
                            "required": step.required,
                            "index": controller.current_step_index,
                            "total": controller.total_steps,
                            "options": [
                                {
                                    "value": opt.value,
                                    "label": opt.label,
                                    "description": opt.description,
                                    "default": opt.default,
                                    "icon": opt.icon,
                                    "requires_setup": opt.requires_setup,
                                }
                                for opt in options
                            ],
                            "default": controller.get_step_default(),
                            "provider": getattr(step, "provider", None),
                            "form_fields": self._get_step_form_fields(step),
                        },
                    },
                })
        except Exception as e:
            logger.error(f"[ONBOARDING] Error submitting step: {e}")
            await self._broadcast({
                "type": "onboarding_submit",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_onboarding_skip(self) -> None:
        """Skip the current optional onboarding step."""
        try:
            controller = self._get_onboarding_controller()

            # Check if step is required before trying to skip
            step = controller.get_current_step()
            if step.required:
                await self._broadcast({
                    "type": "onboarding_skip",
                    "data": {
                        "success": False,
                        "error": "This step is required and cannot be skipped",
                    },
                })
                return

            # Skip the step (advances to next or completes)
            controller.skip_step()

            # Check if onboarding is complete after skip
            if controller.is_complete:
                from app.onboarding import onboarding_manager

                from app.ui_layer.settings.general_settings import get_agent_profile_picture_info
                picture_info = get_agent_profile_picture_info()
                await self._broadcast({
                    "type": "onboarding_complete",
                    "data": {
                        "success": True,
                        "agentName": onboarding_manager.state.agent_name or "Agent",
                        "agentProfilePictureUrl": picture_info["url"],
                        "agentProfilePictureHasCustom": picture_info["has_custom"],
                    },
                })
                if hasattr(self, "_onboarding_controller"):
                    delattr(self, "_onboarding_controller")
            else:
                # Send next step info
                step = controller.get_current_step()
                options = controller.get_step_options()

                await self._broadcast({
                    "type": "onboarding_skip",
                    "data": {
                        "success": True,
                        "nextStep": {
                            "name": step.name,
                            "title": step.title,
                            "description": step.description,
                            "required": step.required,
                            "index": controller.current_step_index,
                            "total": controller.total_steps,
                            "options": [
                                {
                                    "value": opt.value,
                                    "label": opt.label,
                                    "description": opt.description,
                                    "default": opt.default,
                                    "icon": opt.icon,
                                    "requires_setup": opt.requires_setup,
                                }
                                for opt in options
                            ],
                            "default": controller.get_step_default(),
                            "provider": getattr(step, "provider", None),
                        },
                    },
                })
        except Exception as e:
            logger.error(f"[ONBOARDING] Error skipping step: {e}")
            await self._broadcast({
                "type": "onboarding_skip",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_onboarding_back(self) -> None:
        """Go back to the previous onboarding step."""
        try:
            controller = self._get_onboarding_controller()

            if not controller.previous_step():
                await self._broadcast({
                    "type": "onboarding_back",
                    "data": {
                        "success": False,
                        "error": "Already at the first step",
                    },
                })
                return

            # Send previous step info
            step = controller.get_current_step()
            options = controller.get_step_options()

            await self._broadcast({
                "type": "onboarding_back",
                "data": {
                    "success": True,
                    "step": {
                        "name": step.name,
                        "title": step.title,
                        "description": step.description,
                        "required": step.required,
                        "index": controller.current_step_index,
                        "total": controller.total_steps,
                        "options": [
                            {
                                "value": opt.value,
                                "label": opt.label,
                                "description": opt.description,
                                "default": opt.default,
                                "icon": opt.icon,
                                "requires_setup": opt.requires_setup,
                            }
                            for opt in options
                        ],
                        "default": controller.get_step_default(),
                        "provider": getattr(step, "provider", None),
                        "form_fields": self._get_step_form_fields(step),
                    },
                },
            })
        except Exception as e:
            logger.error(f"[ONBOARDING] Error going back: {e}")
            await self._broadcast({
                "type": "onboarding_back",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    # ── Local LLM (Ollama) handlers ──────────────────────────────────────────

    async def _handle_local_llm_check(self) -> None:
        """Return Ollama installation and runtime status."""
        try:
            from app.ui_layer.local_llm_setup import get_ollama_status
            status = get_ollama_status()
            await self._broadcast({
                "type": "local_llm_check",
                "data": {"success": True, **status},
            })
        except Exception as e:
            logger.error(f"[LOCAL_LLM] Error checking status: {e}")
            await self._broadcast({
                "type": "local_llm_check",
                "data": {"success": False, "error": str(e)},
            })

    async def _handle_local_llm_test(self, url: str) -> None:
        """Test an HTTP connection to a running Ollama instance."""
        try:
            from app.ui_layer.local_llm_setup import test_ollama_connection_sync
            result = test_ollama_connection_sync(url)
            await self._broadcast({
                "type": "local_llm_test",
                "data": result,
            })
        except Exception as e:
            logger.error(f"[LOCAL_LLM] Error testing connection: {e}")
            await self._broadcast({
                "type": "local_llm_test",
                "data": {"success": False, "error": str(e)},
            })

    async def _handle_local_llm_install(self) -> None:
        """Install Ollama, streaming progress back to the client."""
        async def progress_callback(msg: str) -> None:
            await self._broadcast({
                "type": "local_llm_install_progress",
                "data": {"message": msg},
            })

        try:
            from app.ui_layer.local_llm_setup import install_ollama
            result = await install_ollama(progress_callback)
            await self._broadcast({
                "type": "local_llm_install",
                "data": result,
            })
        except Exception as e:
            logger.error(f"[LOCAL_LLM] Error installing: {e}")
            await self._broadcast({
                "type": "local_llm_install",
                "data": {"success": False, "error": str(e)},
            })

    async def _handle_local_llm_start(self) -> None:
        """Start the Ollama server."""
        try:
            from app.ui_layer.local_llm_setup import start_ollama
            result = await start_ollama()
            await self._broadcast({
                "type": "local_llm_start",
                "data": result,
            })
        except Exception as e:
            logger.error(f"[LOCAL_LLM] Error starting Ollama: {e}")
            await self._broadcast({
                "type": "local_llm_start",
                "data": {"success": False, "error": str(e)},
            })

    async def _handle_local_llm_suggested_models(self) -> None:
        """Return the list of suggested Ollama models."""
        from app.ui_layer.local_llm_setup import SUGGESTED_MODELS
        await self._broadcast({
            "type": "local_llm_suggested_models",
            "data": {"models": SUGGESTED_MODELS},
        })

    async def _handle_local_llm_pull_model(self, model: str, base_url: str | None = None) -> None:
        """Pull an Ollama model, streaming progress back to the client."""
        if not model:
            await self._broadcast({
                "type": "local_llm_pull_model",
                "data": {"success": False, "error": "No model specified"},
            })
            return

        # Resolve base URL: explicit param > stored settings > default
        if not base_url:
            try:
                from app.ui_layer.settings.model_settings import get_model_settings
                settings_data = get_model_settings()
                base_url = settings_data.get("base_urls", {}).get("remote")
            except Exception:
                pass

        async def progress_callback(data: dict) -> None:
            await self._broadcast({
                "type": "local_llm_pull_progress",
                "data": data,
            })

        try:
            from app.ui_layer.local_llm_setup import pull_ollama_model
            result = await pull_ollama_model(model, progress_callback, base_url=base_url)
            await self._broadcast({
                "type": "local_llm_pull_model",
                "data": result,
            })
        except Exception as e:
            logger.error(f"[LOCAL_LLM] Error pulling model {model}: {e}")
            await self._broadcast({
                "type": "local_llm_pull_model",
                "data": {"success": False, "error": str(e)},
            })
    # -------------------------------------------------------------------------
    # Living UI Handlers
    # -------------------------------------------------------------------------

    async def _handle_living_ui_create(self, data: Dict[str, Any]) -> None:
        """Create a new Living UI project."""
        try:
            name = data.get("name", "")
            description = data.get("description", "")
            features = data.get("features", [])
            data_source = data.get("dataSource")
            theme = data.get("theme", "system")

            if not name or not description:
                await self._broadcast({
                    "type": "living_ui_error",
                    "data": {
                        "projectId": "",
                        "error": "Name and description are required",
                    },
                })
                return

            # Create the project (directory/template)
            project = await self._living_ui_manager.create_project(
                name=name,
                description=description,
                features=features,
                data_source=data_source,
                theme=theme,
            )

            # Broadcast project created
            await self._broadcast({
                "type": "living_ui_create",
                "data": {
                    "success": True,
                    "projectId": project.id,
                    "project": project.to_dict(),
                },
            })

            # Broadcast initial status update
            await self._broadcast({
                "type": "living_ui_status",
                "data": {
                    "projectId": project.id,
                    "phase": "initializing",
                    "progress": 10,
                    "message": "Project created, starting development...",
                },
            })

            # Create task and fire trigger via manager
            # The manager handles: task creation, status update, trigger firing
            task_id = await self._living_ui_manager.create_development_task(project.id)

            if task_id:
                logger.info(f"[LIVING_UI] Created and triggered task {task_id} for project {project.id}")
            else:
                logger.error(f"[LIVING_UI] Failed to create task for project {project.id}")
                await self._broadcast({
                    "type": "living_ui_error",
                    "data": {
                        "projectId": project.id,
                        "error": "Failed to create development task",
                    },
                })

        except Exception as e:
            logger.error(f"[LIVING_UI] Error creating project: {e}")
            await self._broadcast({
                "type": "living_ui_error",
                "data": {
                    "projectId": "",
                    "error": str(e),
                },
            })

    async def _handle_living_ui_list(self) -> None:
        """Get list of all Living UI projects."""
        try:
            projects = self._living_ui_manager.list_projects()
            await self._broadcast({
                "type": "living_ui_list",
                "data": {
                    "success": True,
                    "projects": [p.to_dict() for p in projects],
                },
            })
        except Exception as e:
            logger.error(f"[LIVING_UI] Error listing projects: {e}")
            await self._broadcast({
                "type": "living_ui_list",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_living_ui_launch(self, project_id: str) -> None:
        """Launch a Living UI project."""
        try:
            success = await self._living_ui_manager.launch_project(project_id)
            project = self._living_ui_manager.get_project(project_id)

            if success and project:
                await self._broadcast({
                    "type": "living_ui_launch",
                    "data": {
                        "success": True,
                        "projectId": project_id,
                        "url": project.url,
                        "port": project.port,
                    },
                })
            else:
                await self._broadcast({
                    "type": "living_ui_launch",
                    "data": {
                        "success": False,
                        "projectId": project_id,
                        "error": project.error if project else "Project not found",
                    },
                })
        except Exception as e:
            logger.error(f"[LIVING_UI] Error launching project: {e}")
            await self._broadcast({
                "type": "living_ui_launch",
                "data": {
                    "success": False,
                    "projectId": project_id,
                    "error": str(e),
                },
            })

    async def _handle_living_ui_stop(self, project_id: str) -> None:
        """Stop a running Living UI project."""
        try:
            success = await self._living_ui_manager.stop_project(project_id)
            await self._broadcast({
                "type": "living_ui_stop",
                "data": {
                    "success": success,
                    "projectId": project_id,
                },
            })
        except Exception as e:
            logger.error(f"[LIVING_UI] Error stopping project: {e}")
            await self._broadcast({
                "type": "living_ui_stop",
                "data": {
                    "success": False,
                    "projectId": project_id,
                    "error": str(e),
                },
            })

    async def _handle_living_ui_delete(self, project_id: str) -> None:
        """Delete a Living UI project."""
        try:
            success = await self._living_ui_manager.delete_project(project_id)
            await self._broadcast({
                "type": "living_ui_delete",
                "data": {
                    "success": success,
                    "projectId": project_id,
                },
            })
        except Exception as e:
            logger.error(f"[LIVING_UI] Error deleting project: {e}")
            await self._broadcast({
                "type": "living_ui_delete",
                "data": {
                    "success": False,
                    "projectId": project_id,
                    "error": str(e),
                },
            })

    async def _living_ui_export_handler(self, request: 'web.Request') -> 'web.Response':
        """HTTP handler: download a Living UI project as a ZIP file."""
        from aiohttp import web
        project_id = request.match_info['project_id']
        try:
            zip_path = self._living_ui_manager.export_project_zip(project_id)
            project = self._living_ui_manager.get_project(project_id)
            filename = f"{project.name.replace(' ', '_')}.zip" if project else f"{project_id}.zip"

            response = web.FileResponse(
                zip_path,
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Content-Type': 'application/zip',
                },
            )
            # Schedule cleanup after response is sent
            response._zip_cleanup_path = zip_path
            return response
        except (ValueError, FileNotFoundError) as e:
            return web.json_response({"error": str(e)}, status=404)
        except Exception as e:
            logger.error(f"[LIVING_UI] Export error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def _living_ui_import_handler(self, request: 'web.Request') -> 'web.Response':
        """HTTP handler: stage a ZIP file upload and return the temp path.

        The frontend then sends a living_ui_import WebSocket message with
        the path so the agent handles extraction via the importer skill.
        """
        from aiohttp import web
        try:
            import tempfile
            reader = await request.multipart()
            zip_path = None
            name = ''

            async for part in reader:
                if part.name == 'name':
                    name = (await part.read()).decode('utf-8')
                elif part.name == 'file':
                    # Save uploaded file to a staging location
                    staging_dir = Path(self._living_ui_manager.living_ui_dir) / '_staging'
                    staging_dir.mkdir(parents=True, exist_ok=True)
                    tmp = tempfile.NamedTemporaryFile(
                        suffix='.zip', prefix='import_', dir=str(staging_dir), delete=False
                    )
                    while True:
                        chunk = await part.read_chunk()
                        if not chunk:
                            break
                        tmp.write(chunk)
                    tmp.close()
                    zip_path = tmp.name

            if not zip_path:
                return web.json_response({"error": "No ZIP file uploaded"}, status=400)

            return web.json_response({
                "success": True,
                "path": zip_path,
                "name": name,
            })
        except Exception as e:
            logger.error(f"[LIVING_UI] Upload staging error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_living_ui_state_update(self, data: Dict[str, Any]) -> None:
        """Handle state update from a Living UI for agent awareness."""
        try:
            project_id = data.get("projectId", "")
            state = data.get("state", {})

            # Store the state for agent context
            from app.state import STATE
            if hasattr(STATE, 'update_living_ui_state'):
                STATE.update_living_ui_state(project_id, state)

            # Also forward to any listening clients (for debugging/monitoring)
            await self._broadcast({
                "type": "living_ui_state_update",
                "data": {
                    "projectId": project_id,
                    "state": state,
                },
            })
        except Exception as e:
            logger.error(f"[LIVING_UI] Error handling state update: {e}")

    async def _handle_living_ui_sharing_info(self, project_id: str) -> None:
        """Return sharing info (LAN URL, tunnel URL)."""
        lan_url = self._living_ui_manager.get_lan_url(project_id)
        project = self._living_ui_manager.get_project(project_id)
        await self._broadcast({
            "type": "living_ui_sharing_info",
            "data": {
                "projectId": project_id,
                "lanUrl": lan_url,
                "tunnelUrl": project.tunnel_url if project else None,
            },
        })

    async def _handle_living_ui_tunnel_start(self, project_id: str, provider: str) -> None:
        """Start a tunnel for a Living UI project."""
        logger.info(f"[LIVING_UI] Tunnel start requested: project={project_id}, provider={provider}")
        try:
            url = await self._living_ui_manager.start_tunnel(project_id, provider)
            await self._broadcast({
                "type": "living_ui_tunnel_status",
                "data": {
                    "projectId": project_id,
                    "tunnelUrl": url,
                    "success": url is not None,
                    "error": None if url else f"Failed to start {provider} tunnel",
                },
            })
        except Exception as e:
            logger.error(f"[LIVING_UI] Tunnel start error: {e}", exc_info=True)
            await self._broadcast({
                "type": "living_ui_tunnel_status",
                "data": {
                    "projectId": project_id,
                    "tunnelUrl": None,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_living_ui_tunnel_stop(self, project_id: str) -> None:
        """Stop a tunnel for a Living UI project."""
        await self._living_ui_manager.stop_tunnel(project_id)
        await self._broadcast({
            "type": "living_ui_tunnel_status",
            "data": {
                "projectId": project_id,
                "tunnelUrl": None,
                "success": True,
            },
        })

    async def broadcast_living_ui_ready(self, project_id: str, url: str, port: int) -> bool:
        """
        Broadcast that a Living UI is ready (called from agent action).

        This method launches the Living UI server via the manager and notifies
        the browser. The agent should NOT start the server itself - just build
        and call this action.

        Returns:
            True if project was found and launched successfully, False otherwise
        """
        project = self._living_ui_manager.get_project(project_id)
        if not project:
            logger.error(f"[LIVING_UI] Project not found for ready notification: {project_id}")
            # Broadcast error to browser so it can display the error state
            await self._broadcast({
                "type": "living_ui_error",
                "data": {
                    "projectId": project_id,
                    "error": f"Project '{project_id}' not found. Check that the project_id matches the one from the task instruction.",
                },
            })
            return False

        # Update project status to "ready" (build complete, about to launch)
        self._living_ui_manager.update_project_status(project_id, "ready")

        # Launch the project server via manager (centralizes process management)
        success = await self._living_ui_manager.launch_project(project_id)

        if success:
            # Get updated project info with URL
            project = self._living_ui_manager.get_project(project_id)
            await self._broadcast({
                "type": "living_ui_ready",
                "data": {
                    "projectId": project_id,
                    "url": project.url if project else url,
                    "port": project.port if project else port,
                },
            })
            logger.info(f"[LIVING_UI] Project {project_id} launched and ready")
            return True
        else:
            # Launch failed
            await self._broadcast({
                "type": "living_ui_error",
                "data": {
                    "projectId": project_id,
                    "error": "Failed to launch Living UI server",
                },
            })
            logger.error(f"[LIVING_UI] Failed to launch project {project_id}")
            return False

    async def broadcast_living_ui_progress(
        self,
        project_id: str,
        phase: str,
        progress: int,
        message: str
    ) -> None:
        """Broadcast Living UI creation progress (called from agent action)."""
        await self._broadcast({
            "type": "living_ui_status",
            "data": {
                "projectId": project_id,
                "phase": phase,
                "progress": progress,
                "message": message,
            },
        })

    async def broadcast_living_ui_todos(
        self,
        project_id: str,
        todos: list,
    ) -> None:
        """Broadcast the agent's current todo list for a Living UI task.

        Fired from the task manager's on_todo_transition hook whenever the
        agent updates its todos during a Living UI creation task.
        """
        await self._broadcast({
            "type": "living_ui_todos",
            "data": {
                "projectId": project_id,
                "todos": todos,
            },
        })

    async def _handle_task_cancel(self, task_id: str) -> None:
        """Cancel a running task."""
        try:
            agent = self._controller.agent
            task_manager = agent.task_manager

            # Find the task
            task = task_manager.get_task_by_id(task_id) if task_id else task_manager.active
            if not task:
                await self._broadcast({
                    "type": "task_cancel_response",
                    "data": {
                        "taskId": task_id,
                        "success": False,
                        "error": "Task not found",
                    },
                })
                return

            # Cancel the task
            await task_manager.mark_task_cancel(
                reason="Aborted by user",
                task_id=task.id,
            )

            await self._broadcast({
                "type": "task_cancel_response",
                "data": {
                    "taskId": task.id,
                    "success": True,
                    "status": "cancelled",
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "task_cancel_response",
                "data": {
                    "taskId": task_id,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_option_click(self, value: str, session_id: str, message_id: str) -> None:
        """Handle a user clicking an option button in a chat message."""
        try:
            # Mark the option as selected in storage and in-memory
            if self._chat and message_id:
                if self._chat._storage:
                    try:
                        self._chat._storage.update_option_selected(message_id, value)
                    except Exception:
                        pass
                # Update in-memory message so refreshes reflect the selection
                for m in self._chat._messages:
                    if m.message_id == message_id:
                        m.option_selected = value
                        break

            # Route to the controller
            await self._controller.handle_option_click(value, session_id)
        except Exception as e:
            logger.error(f"[OPTION_CLICK] Error handling option click: {e}", exc_info=True)

    # ─────────────────────────────────────────────────────────────────────
    # Settings Operation Handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_settings_get(self) -> None:
        """Get current settings."""
        try:
            result = get_general_settings()
            settings = {
                "agentName": result.get("agent_name", "CraftBot"),
                "theme": "dark",  # Theme is managed client-side
                "agentProfilePictureUrl": result.get(
                    "agent_profile_picture_url", "/api/agent-profile-picture"
                ),
                "agentProfilePictureHasCustom": result.get(
                    "agent_profile_picture_has_custom", False
                ),
            }

            await self._broadcast({
                "type": "settings_get",
                "data": {
                    "settings": settings,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "settings_get",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_settings_update(self, settings: Dict[str, Any]) -> None:
        """Update settings."""
        try:
            # Convert frontend camelCase to snake_case
            update_data = {}
            if "agentName" in settings:
                update_data["agent_name"] = settings["agentName"]

            result = update_general_settings(update_data)

            if result.get("success"):
                await self._broadcast({
                    "type": "settings_update",
                    "data": {
                        "settings": settings,
                        "success": True,
                    },
                })
            else:
                await self._broadcast({
                    "type": "settings_update",
                    "data": {
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                })
        except Exception as e:
            await self._broadcast({
                "type": "settings_update",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_agent_file_read(self, filename: str) -> None:
        """Read an agent file system file (USER.md or AGENT.md)."""
        result = read_agent_file(filename)

        if result.get("success"):
            await self._broadcast({
                "type": "agent_file_read",
                "data": {
                    "filename": filename,
                    "content": result.get("content"),
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "agent_file_read",
                "data": {
                    "filename": filename,
                    "content": None,
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_agent_file_write(self, filename: str, content: str) -> None:
        """Write to an agent file system file (USER.md or AGENT.md)."""
        result = write_agent_file(filename, content)

        if result.get("success"):
            # Update memory index after file change
            agent = self._controller.agent
            if hasattr(agent, 'memory_manager'):
                agent.memory_manager.update()

            await self._broadcast({
                "type": "agent_file_write",
                "data": {
                    "filename": filename,
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "agent_file_write",
                "data": {
                    "filename": filename,
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_agent_file_restore(self, filename: str) -> None:
        """Restore an agent file from template."""
        result = restore_agent_file(filename)

        if result.get("success"):
            # Update memory index after file change
            agent = self._controller.agent
            if hasattr(agent, 'memory_manager'):
                agent.memory_manager.update()

            await self._broadcast({
                "type": "agent_file_restore",
                "data": {
                    "filename": filename,
                    "content": result.get("content"),
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "agent_file_restore",
                "data": {
                    "filename": filename,
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_reset(self) -> None:
        """Reset agent state (equivalent to /reset command)."""
        result = await reset_agent_state(self._controller)

        if result.get("success"):
            # Clear chat messages and actions in UI
            await self._chat.clear()
            await self._action_panel.clear()

            await self._broadcast({
                "type": "reset",
                "data": {
                    "success": True,
                    "message": result.get("message", "Agent state has been reset."),
                },
            })
        else:
            await self._broadcast({
                "type": "reset",
                "data": {
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_clear_conversation(self) -> None:
        """
        Clear the chat conversation log only.

        Drops chat messages from the panel and from chat_storage. The
        action panel (tasks/actions) is left alone so running tasks are
        not disrupted. Dashboard usage/task metrics live in a separate
        database and are not touched.
        """
        try:
            await self._chat.clear()
            await self._broadcast({
                "type": "clear_conversation",
                "data": {"success": True},
            })
        except Exception as e:
            await self._broadcast({
                "type": "clear_conversation",
                "data": {"success": False, "error": str(e)},
            })

    async def _handle_clear_tasks(self) -> None:
        """
        Clear only finished tasks (completed/error/cancelled) and their
        child actions from the panel. Running/waiting tasks are preserved.

        Dashboard usage/task metrics are persisted in a separate database
        and are not affected.
        """
        try:
            removed = await self._action_panel.clear_terminal_tasks()
            await self._broadcast({
                "type": "clear_tasks",
                "data": {"success": True, "removed": removed},
            })
        except Exception as e:
            await self._broadcast({
                "type": "clear_tasks",
                "data": {"success": False, "error": str(e)},
            })

    # ─────────────────────────────────────────────────────────────────────
    # Scheduler/Proactive Operation Handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_scheduler_config_get(self) -> None:
        """Get scheduler configuration."""
        result = get_scheduler_config()

        if result.get("success"):
            # Get current status from scheduler if available
            agent = self._controller.agent
            scheduler_status = {}
            if hasattr(agent, 'scheduler') and agent.scheduler:
                scheduler_status = agent.scheduler.get_status()

            await self._broadcast({
                "type": "scheduler_config_get",
                "data": {
                    "config": result.get("config"),
                    "status": scheduler_status,
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "scheduler_config_get",
                "data": {
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_scheduler_config_update(self, updates: Dict[str, Any]) -> None:
        """Update scheduler configuration."""
        try:
            # Convert frontend format to UI layer format
            config_updates = {}

            if "enabled" in updates:
                config_updates["enabled"] = updates["enabled"]

            if "schedules" in updates:
                # Convert schedule array to dict format for UI layer
                schedule_updates = {}
                for schedule_update in updates["schedules"]:
                    schedule_id = schedule_update.get("id")
                    if schedule_id:
                        schedule_updates[schedule_id] = {
                            k: v for k, v in schedule_update.items() if k != "id"
                        }
                config_updates["schedule_updates"] = schedule_updates

            result = update_scheduler_config(config_updates)

            if result.get("success"):
                # Update runtime scheduler if available
                agent = self._controller.agent
                if hasattr(agent, 'scheduler') and agent.scheduler:
                    # Toggle individual schedules at runtime
                    # Note: Master proactive toggle is handled separately via proactive_mode_set
                    # which updates settings.json, not scheduler_config.json
                    if "schedules" in updates:
                        for schedule_update in updates["schedules"]:
                            schedule_id = schedule_update.get("id")
                            if schedule_id and "enabled" in schedule_update:
                                await toggle_schedule_runtime(
                                    agent.scheduler,
                                    schedule_id,
                                    schedule_update["enabled"]
                                )

                # Re-read config for response
                config_result = get_scheduler_config()

                await self._broadcast({
                    "type": "scheduler_config_update",
                    "data": {
                        "config": config_result.get("config", {}),
                        "success": True,
                    },
                })
            else:
                await self._broadcast({
                    "type": "scheduler_config_update",
                    "data": {
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                })
        except Exception as e:
            await self._broadcast({
                "type": "scheduler_config_update",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_proactive_tasks_get(self, frequency: str = None) -> None:
        """Get proactive tasks from PROACTIVE.md."""
        agent = self._controller.agent
        proactive_manager = getattr(agent, 'proactive_manager', None)

        # Reload from file before getting tasks
        if proactive_manager:
            reload_proactive_manager(proactive_manager)

        result = get_recurring_tasks(
            proactive_manager,
            frequency=frequency,
            enabled_only=False,
        )

        if result.get("success"):
            # Convert to frontend format (camelCase)
            tasks_data = []
            for task in result.get("tasks", []):
                task_dict = {
                    "id": task.get("id"),
                    "name": task.get("name"),
                    "frequency": task.get("frequency"),
                    "instruction": task.get("instruction"),
                    "enabled": task.get("enabled"),
                    "priority": task.get("priority"),
                    "permissionTier": task.get("permission_tier"),
                    "time": task.get("time"),
                    "day": task.get("day"),
                    "runCount": task.get("run_count", 0),
                    "lastRun": task.get("last_executed"),
                    "nextRun": task.get("next_run"),
                    "outcomeHistory": task.get("outcome_history", []),
                }
                tasks_data.append(task_dict)

            await self._broadcast({
                "type": "proactive_tasks_get",
                "data": {
                    "tasks": tasks_data,
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "proactive_tasks_get",
                "data": {
                    "tasks": [],
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_proactive_task_add(self, task_data: Dict[str, Any]) -> None:
        """Add a new proactive task."""
        agent = self._controller.agent
        proactive_manager = getattr(agent, 'proactive_manager', None)

        result = add_recurring_task(
            proactive_manager,
            name=task_data.get("name", "New Task"),
            frequency=task_data.get("frequency", "daily"),
            instruction=task_data.get("instruction", ""),
            enabled=task_data.get("enabled", True),
            priority=task_data.get("priority", 50),
            permission_tier=task_data.get("permissionTier", 1),
            time=task_data.get("time"),
            day=task_data.get("day"),
        )

        if result.get("success"):
            await self._broadcast({
                "type": "proactive_task_add",
                "data": {
                    "taskId": result.get("task", {}).get("id"),
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "proactive_task_add",
                "data": {
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_proactive_task_update(self, task_id: str, updates: Dict[str, Any]) -> None:
        """Update a proactive task."""
        agent = self._controller.agent
        proactive_manager = getattr(agent, 'proactive_manager', None)

        # Convert camelCase to snake_case for the UI layer
        update_dict = {}
        if "name" in updates:
            update_dict["name"] = updates["name"]
        if "instruction" in updates:
            update_dict["instruction"] = updates["instruction"]
        if "enabled" in updates:
            update_dict["enabled"] = updates["enabled"]
        if "priority" in updates:
            update_dict["priority"] = updates["priority"]
        if "permissionTier" in updates:
            update_dict["permission_tier"] = updates["permissionTier"]
        if "time" in updates:
            update_dict["time"] = updates["time"]
        if "day" in updates:
            update_dict["day"] = updates["day"]
        if "frequency" in updates:
            update_dict["frequency"] = updates["frequency"]

        result = update_recurring_task(proactive_manager, task_id, update_dict)

        if result.get("success"):
            await self._broadcast({
                "type": "proactive_task_update",
                "data": {
                    "taskId": task_id,
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "proactive_task_update",
                "data": {
                    "taskId": task_id,
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_proactive_task_remove(self, task_id: str) -> None:
        """Remove a proactive task."""
        agent = self._controller.agent
        proactive_manager = getattr(agent, 'proactive_manager', None)

        result = remove_recurring_task(proactive_manager, task_id)

        if result.get("success"):
            await self._broadcast({
                "type": "proactive_task_remove",
                "data": {
                    "taskId": task_id,
                    "removed": True,
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "proactive_task_remove",
                "data": {
                    "taskId": task_id,
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_proactive_tasks_reset(self) -> None:
        """Reset all proactive tasks (restore from template)."""
        result = reset_recurring_tasks()

        if result.get("success"):
            # Reload proactive manager
            agent = self._controller.agent
            proactive_manager = getattr(agent, 'proactive_manager', None)
            if proactive_manager:
                reload_proactive_manager(proactive_manager)

            await self._broadcast({
                "type": "proactive_tasks_reset",
                "data": {
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "proactive_tasks_reset",
                "data": {
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_proactive_file_read(self) -> None:
        """Read the raw PROACTIVE.md file content."""
        result = read_agent_file("PROACTIVE.md")

        if result.get("success"):
            await self._broadcast({
                "type": "proactive_file_read",
                "data": {
                    "content": result.get("content"),
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "proactive_file_read",
                "data": {
                    "content": None,
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_proactive_mode_get(self) -> None:
        """Get the current proactive mode status."""
        result = get_proactive_mode()

        await self._broadcast({
            "type": "proactive_mode_get",
            "data": {
                "enabled": result.get("enabled", True),
                "success": result.get("success", False),
                "error": result.get("error"),
            },
        })

    async def _handle_proactive_mode_set(self, enabled: bool) -> None:
        """Set the proactive mode on or off."""
        result = set_proactive_mode(enabled)

        await self._broadcast({
            "type": "proactive_mode_set",
            "data": {
                "enabled": result.get("enabled", enabled),
                "success": result.get("success", False),
                "error": result.get("error"),
            },
        })

    # ─────────────────────────────────────────────────────────────────────
    # Memory Operation Handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_memory_mode_get(self) -> None:
        """Get the current memory mode status."""
        result = get_memory_mode()

        await self._broadcast({
            "type": "memory_mode_get",
            "data": {
                "enabled": result.get("enabled", True),
                "success": result.get("success", False),
                "error": result.get("error"),
            },
        })

    async def _handle_memory_mode_set(self, enabled: bool) -> None:
        """Set the memory mode on or off."""
        result = set_memory_mode(enabled)

        await self._broadcast({
            "type": "memory_mode_set",
            "data": {
                "enabled": result.get("enabled", enabled),
                "success": result.get("success", False),
                "error": result.get("error"),
            },
        })

    async def _handle_memory_items_get(self) -> None:
        """Get all memory items from MEMORY.md."""
        result = get_memory_items()

        if result.get("success"):
            await self._broadcast({
                "type": "memory_items_get",
                "data": {
                    "items": result.get("items", []),
                    "categories": result.get("categories", []),
                    "count": result.get("count", 0),
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "memory_items_get",
                "data": {
                    "items": [],
                    "categories": [],
                    "count": 0,
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_memory_item_add(self, category: str, content: str) -> None:
        """Add a new memory item."""
        result = add_memory_item(category=category, content=content)

        if result.get("success"):
            # Update memory index after adding
            agent = self._controller.agent
            if hasattr(agent, 'memory_manager'):
                agent.memory_manager.update()

            await self._broadcast({
                "type": "memory_item_add",
                "data": {
                    "item": result.get("item"),
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "memory_item_add",
                "data": {
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_memory_item_update(
        self,
        item_id: str,
        category: str = None,
        content: str = None
    ) -> None:
        """Update an existing memory item."""
        result = update_memory_item(item_id=item_id, category=category, content=content)

        if result.get("success"):
            # Update memory index after updating
            agent = self._controller.agent
            if hasattr(agent, 'memory_manager'):
                agent.memory_manager.update()

            await self._broadcast({
                "type": "memory_item_update",
                "data": {
                    "item": result.get("item"),
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "memory_item_update",
                "data": {
                    "itemId": item_id,
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_memory_item_remove(self, item_id: str) -> None:
        """Remove a memory item."""
        result = remove_memory_item(item_id=item_id)

        if result.get("success"):
            # Update memory index after removing
            agent = self._controller.agent
            if hasattr(agent, 'memory_manager'):
                agent.memory_manager.update()

            await self._broadcast({
                "type": "memory_item_remove",
                "data": {
                    "itemId": item_id,
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "memory_item_remove",
                "data": {
                    "itemId": item_id,
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_memory_reset(self) -> None:
        """Reset memory by restoring MEMORY.md from template."""
        result = reset_memory()

        if result.get("success"):
            # Also clear unprocessed events
            clear_unprocessed_events()

            # Update memory index after reset
            agent = self._controller.agent
            if hasattr(agent, 'memory_manager'):
                agent.memory_manager.update()

            await self._broadcast({
                "type": "memory_reset",
                "data": {
                    "success": True,
                },
            })
        else:
            await self._broadcast({
                "type": "memory_reset",
                "data": {
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                },
            })

    async def _handle_memory_stats_get(self) -> None:
        """Get memory statistics."""
        result = get_memory_stats()

        await self._broadcast({
            "type": "memory_stats_get",
            "data": {
                "stats": result if result.get("success") else {},
                "success": result.get("success", False),
                "error": result.get("error"),
            },
        })

    async def _handle_memory_process_trigger(self) -> None:
        """Manually trigger memory processing."""
        try:
            agent = self._controller.agent

            # Check if memory is enabled
            mode_result = get_memory_mode()
            if not mode_result.get("enabled", True):
                await self._broadcast({
                    "type": "memory_process_trigger",
                    "data": {
                        "success": False,
                        "error": "Memory is disabled. Enable memory mode first.",
                    },
                })
                return

            # Check if there's a create_process_memory_task method
            if hasattr(agent, 'create_process_memory_task'):
                task_id = agent.create_process_memory_task()

                if task_id:
                    # Queue trigger to start the task (same as _handle_memory_processing_trigger)
                    import time
                    from app.trigger import Trigger
                    trigger = Trigger(
                        fire_at=time.time(),
                        priority=60,
                        next_action_description="Process unprocessed events into long-term memory",
                        session_id=task_id,
                        payload={},
                    )
                    await agent.triggers.put(trigger)

                await self._broadcast({
                    "type": "memory_process_trigger",
                    "data": {
                        "success": True,
                        "taskId": task_id,
                        "message": "Memory processing task created",
                    },
                })
            else:
                await self._broadcast({
                    "type": "memory_process_trigger",
                    "data": {
                        "success": False,
                        "error": "Memory processing not available",
                    },
                })
        except Exception as e:
            await self._broadcast({
                "type": "memory_process_trigger",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    # ─────────────────────────────────────────────────────────────────────
    # Model Settings Handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_model_providers_get(self) -> None:
        """Get available model providers."""
        try:
            result = get_available_providers()
            await self._broadcast({
                "type": "model_providers_get",
                "data": result,
            })
        except Exception as e:
            await self._broadcast({
                "type": "model_providers_get",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_model_settings_get(self) -> None:
        """Get current model settings."""
        try:
            result = get_model_settings()
            await self._broadcast({
                "type": "model_settings_get",
                "data": result,
            })
        except Exception as e:
            await self._broadcast({
                "type": "model_settings_get",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_model_settings_update(self, data: Dict[str, Any]) -> None:
        """Update model settings.

        Validates API key presence before saving. Connection is tested only when
        credentials (API key or base URL) are actually changing, so that saving
        a model name or switching providers works even when the service is offline
        (e.g. Ollama not running).
        """
        try:
            new_provider = data.get("llmProvider")
            vlm_provider = data.get("vlmProvider")
            api_key = data.get("apiKey")
            provider_for_key = data.get("providerForKey")
            base_url = data.get("baseUrl")

            # Step 1: Validate API key presence before saving
            if new_provider:
                validation = validate_can_save(
                    llm_provider=new_provider,
                    vlm_provider=vlm_provider,
                    api_key=api_key,
                    provider_for_key=provider_for_key,
                )
                if not validation.get("can_save"):
                    errors = validation.get("errors", ["API key required"])
                    await self._broadcast({
                        "type": "model_settings_update",
                        "data": {
                            "success": False,
                            "error": "; ".join(errors),
                        },
                    })
                    return

            # Step 2: Test connection before saving — only when credentials are changing.
            # Mirror the frontend logic: skip the test when only model/provider name
            # changes so that saving works even if the service (e.g. Ollama) is offline.
            credentials_changing = bool(api_key or base_url)
            if new_provider and credentials_changing:
                # Determine the API key to test with
                test_api_key = api_key
                if not test_api_key and provider_for_key != new_provider:
                    # Use existing key from settings if not providing a new one
                    from app.config import get_api_key
                    test_api_key = get_api_key(new_provider)

                test_result = test_connection(
                    provider=new_provider,
                    api_key=test_api_key,
                    base_url=base_url,
                )
                if not test_result.get("success"):
                    error_msg = test_result.get("error", "Connection test failed")
                    await self._broadcast({
                        "type": "model_settings_update",
                        "data": {
                            "success": False,
                            "error": f"Connection test failed: {error_msg}",
                        },
                    })
                    return

            # Step 3: Now save settings (validation and connection test passed)
            result = update_model_settings(
                llm_provider=new_provider,
                vlm_provider=vlm_provider,
                llm_model=data.get("llmModel"),
                vlm_model=data.get("vlmModel"),
                api_key=api_key,
                provider_for_key=provider_for_key,
                base_url=base_url,
                provider_for_url=data.get("providerForUrl"),
            )

            # Reinitialize LLM/VLM with new provider settings
            if result.get("success") and new_provider:
                try:
                    agent = self._controller.agent
                    agent.reinitialize_llm(new_provider)
                    logger.info(f"[BROWSER] LLM reinitialized with provider: {new_provider}")
                except Exception as e:
                    logger.warning(f"[BROWSER] Failed to reinitialize LLM: {e}")
                    result["warning"] = f"Settings saved but LLM reinitialization failed: {e}"

            await self._broadcast({
                "type": "model_settings_update",
                "data": result,
            })
        except Exception as e:
            await self._broadcast({
                "type": "model_settings_update",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_model_connection_test(
        self,
        provider: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """Test connection to a model provider."""
        try:
            result = test_connection(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
            await self._broadcast({
                "type": "model_connection_test",
                "data": result,
            })
        except Exception as e:
            await self._broadcast({
                "type": "model_connection_test",
                "data": {
                    "success": False,
                    "message": "Test failed",
                    "provider": provider,
                    "error": str(e),
                },
            })

    async def _handle_model_validate_save(self, data: Dict[str, Any]) -> None:
        """Validate if model settings can be saved."""
        try:
            result = validate_can_save(
                llm_provider=data.get("llmProvider", "anthropic"),
                vlm_provider=data.get("vlmProvider"),
                api_key=data.get("apiKey"),
                provider_for_key=data.get("providerForKey"),
            )
            await self._broadcast({
                "type": "model_validate_save",
                "data": result,
            })
        except Exception as e:
            await self._broadcast({
                "type": "model_validate_save",
                "data": {
                    "success": False,
                    "can_save": False,
                    "errors": [str(e)],
                },
            })

    async def _handle_ollama_models_get(self, base_url: Optional[str] = None) -> None:
        """Fetch available models from Ollama and broadcast to frontend."""
        try:
            if not base_url:
                settings_data = get_model_settings()
                base_url = settings_data.get("base_urls", {}).get("remote")
            result = get_ollama_models(base_url=base_url)
            await self._broadcast({"type": "ollama_models_get", "data": result})
        except Exception as e:
            await self._broadcast({
                "type": "ollama_models_get",
                "data": {"success": False, "models": [], "error": str(e)},
            })

    async def _handle_openrouter_models_get(
        self,
        base_url: Optional[str] = None,
        force_refresh: bool = False,
    ) -> None:
        """Fetch the OpenRouter model catalog and broadcast it.

        The catalog is public (no auth) and large (~300 entries). The helper
        caches it in-process for 5 min; pass forceRefresh=True from the UI
        to bypass the cache.
        """
        try:
            from app.ui_layer.settings.openrouter_catalog import fetch_models
            result = await asyncio.to_thread(
                fetch_models, base_url, force_refresh=force_refresh
            )
            await self._broadcast({"type": "openrouter_models_get", "data": result})
        except Exception as e:
            await self._broadcast({
                "type": "openrouter_models_get",
                "data": {"success": False, "models": [], "error": str(e)},
            })

    async def _handle_openrouter_credits_get(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        """Fetch the OpenRouter account credit balance for the configured key."""
        try:
            from app.ui_layer.settings.openrouter_catalog import fetch_credits
            result = await asyncio.to_thread(fetch_credits, api_key, base_url)
            await self._broadcast({"type": "openrouter_credits_get", "data": result})
        except Exception as e:
            await self._broadcast({
                "type": "openrouter_credits_get",
                "data": {"success": False, "error": str(e)},
            })

    # ─────────────────────────────────────────────────────────────────────
    # Slow Mode Handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_slow_mode_get(self) -> None:
        """Get slow mode settings."""
        try:
            from app.ui_layer.settings.model_settings import get_slow_mode_settings
            result = get_slow_mode_settings()
            await self._broadcast({"type": "slow_mode_get", "data": result})
        except Exception as e:
            await self._broadcast({
                "type": "slow_mode_get",
                "data": {"success": False, "error": str(e)},
            })

    async def _handle_slow_mode_set(self, data: Dict[str, Any]) -> None:
        """Set slow mode on or off."""
        try:
            from app.ui_layer.settings.model_settings import set_slow_mode
            enabled = data.get("enabled", False)
            tpm_limit = data.get("tpmLimit")
            result = set_slow_mode(enabled, tpm_limit)
            await self._broadcast({"type": "slow_mode_set", "data": result})
        except Exception as e:
            await self._broadcast({
                "type": "slow_mode_set",
                "data": {"success": False, "error": str(e)},
            })

    # ─────────────────────────────────────────────────────────────────────
    # MCP Settings Handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_mcp_list(self) -> None:
        """Get list of configured MCP servers."""
        try:
            servers = list_mcp_servers()
            await self._broadcast({
                "type": "mcp_list",
                "data": {
                    "success": True,
                    "servers": servers,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "mcp_list",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_mcp_enable(self, name: str) -> None:
        """Enable an MCP server."""
        try:
            success, message = enable_mcp_server(name)
            await self._broadcast({
                "type": "mcp_enable",
                "data": {
                    "success": success,
                    "message": message,
                    "name": name,
                },
            })
            # Refresh the list
            if success:
                await self._handle_mcp_list()
        except Exception as e:
            await self._broadcast({
                "type": "mcp_enable",
                "data": {
                    "success": False,
                    "error": str(e),
                    "name": name,
                },
            })

    async def _handle_mcp_disable(self, name: str) -> None:
        """Disable an MCP server."""
        try:
            success, message = disable_mcp_server(name)
            await self._broadcast({
                "type": "mcp_disable",
                "data": {
                    "success": success,
                    "message": message,
                    "name": name,
                },
            })
            # Refresh the list
            if success:
                await self._handle_mcp_list()
        except Exception as e:
            await self._broadcast({
                "type": "mcp_disable",
                "data": {
                    "success": False,
                    "error": str(e),
                    "name": name,
                },
            })

    async def _handle_mcp_remove(self, name: str) -> None:
        """Remove an MCP server."""
        try:
            success, message = remove_mcp_server(name)
            await self._broadcast({
                "type": "mcp_remove",
                "data": {
                    "success": success,
                    "message": message,
                    "name": name,
                },
            })
            # Refresh the list
            if success:
                await self._handle_mcp_list()
        except Exception as e:
            await self._broadcast({
                "type": "mcp_remove",
                "data": {
                    "success": False,
                    "error": str(e),
                    "name": name,
                },
            })

    async def _handle_mcp_add_json(self, name: str, config: str) -> None:
        """Add an MCP server from JSON configuration."""
        try:
            success, message = add_mcp_server_from_json(name, config)
            await self._broadcast({
                "type": "mcp_add_json",
                "data": {
                    "success": success,
                    "message": message,
                    "name": name,
                },
            })
            # Refresh the list
            if success:
                await self._handle_mcp_list()
        except Exception as e:
            await self._broadcast({
                "type": "mcp_add_json",
                "data": {
                    "success": False,
                    "error": str(e),
                    "name": name,
                },
            })

    async def _handle_mcp_get_env(self, name: str) -> None:
        """Get environment variables for an MCP server."""
        try:
            env_vars = get_server_env_vars(name)
            await self._broadcast({
                "type": "mcp_get_env",
                "data": {
                    "success": True,
                    "name": name,
                    "env": env_vars,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "mcp_get_env",
                "data": {
                    "success": False,
                    "error": str(e),
                    "name": name,
                },
            })

    async def _handle_mcp_update_env(self, name: str, env_key: str, env_value: str) -> None:
        """Update an environment variable for an MCP server."""
        try:
            success, message = update_mcp_server_env(name, env_key, env_value)
            await self._broadcast({
                "type": "mcp_update_env",
                "data": {
                    "success": success,
                    "message": message,
                    "name": name,
                    "key": env_key,
                },
            })
            # Refresh the list to show updated env status
            if success:
                await self._handle_mcp_list()
        except Exception as e:
            await self._broadcast({
                "type": "mcp_update_env",
                "data": {
                    "success": False,
                    "error": str(e),
                    "name": name,
                    "key": env_key,
                },
            })

    # ─────────────────────────────────────────────────────────────────────
    # Skill Settings Handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_skill_list(self) -> None:
        """Get list of all skills."""
        try:
            skills = list_skills()
            # Calculate stats
            total = len(skills)
            enabled = sum(1 for s in skills if s.get("enabled", True))

            await self._broadcast({
                "type": "skill_list",
                "data": {
                    "success": True,
                    "skills": skills,
                    "total": total,
                    "enabled": enabled,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "skill_list",
                "data": {
                    "success": False,
                    "error": str(e),
                    "skills": [],
                    "total": 0,
                    "enabled": 0,
                },
            })

    async def _handle_skill_info(self, name: str) -> None:
        """Get detailed info about a skill."""
        try:
            info = get_skill_info(name)
            if info:
                await self._broadcast({
                    "type": "skill_info",
                    "data": {
                        "success": True,
                        "name": name,
                        "skill": info,
                    },
                })
            else:
                await self._broadcast({
                    "type": "skill_info",
                    "data": {
                        "success": False,
                        "error": f"Skill '{name}' not found",
                        "name": name,
                    },
                })
        except Exception as e:
            await self._broadcast({
                "type": "skill_info",
                "data": {
                    "success": False,
                    "error": str(e),
                    "name": name,
                },
            })

    async def _handle_skill_enable(self, name: str) -> None:
        """Enable a skill."""
        try:
            success, message = enable_skill(name)
            await self._broadcast({
                "type": "skill_enable",
                "data": {
                    "success": success,
                    "message": message,
                    "name": name,
                },
            })
            # Refresh the list and sync skill commands
            if success:
                await self._handle_skill_list()
                self._controller.sync_skill_commands()
        except Exception as e:
            await self._broadcast({
                "type": "skill_enable",
                "data": {
                    "success": False,
                    "error": str(e),
                    "name": name,
                },
            })

    async def _handle_skill_disable(self, name: str) -> None:
        """Disable a skill."""
        try:
            success, message = disable_skill(name)
            await self._broadcast({
                "type": "skill_disable",
                "data": {
                    "success": success,
                    "message": message,
                    "name": name,
                },
            })
            # Refresh the list and sync skill commands
            if success:
                await self._handle_skill_list()
                self._controller.sync_skill_commands()
        except Exception as e:
            await self._broadcast({
                "type": "skill_disable",
                "data": {
                    "success": False,
                    "error": str(e),
                    "name": name,
                },
            })

    async def _handle_skill_reload(self) -> None:
        """Reload skills from disk."""
        try:
            success, message = reload_skills()
            await self._broadcast({
                "type": "skill_reload",
                "data": {
                    "success": success,
                    "message": message,
                },
            })
            # Refresh the list and sync skill commands
            if success:
                await self._handle_skill_list()
                self._controller.sync_skill_commands()
        except Exception as e:
            await self._broadcast({
                "type": "skill_reload",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_skill_run(self, name: str, args_text: str = "") -> None:
        """Run a skill by invoking it through the controller."""
        try:
            await self._controller.invoke_skill(name, args_text, self._adapter_id)
            await self._broadcast({
                "type": "skill_run",
                "data": {
                    "success": True,
                    "name": name,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "skill_run",
                "data": {
                    "success": False,
                    "error": str(e),
                    "name": name,
                },
            })

    async def _handle_skill_install(self, source: str) -> None:
        """Install a skill from path or git URL."""
        try:
            # Check if it's a git URL
            if source.startswith("http") or source.startswith("git@"):
                success, message = install_skill_from_git(source)
            else:
                success, message = install_skill_from_path(source)

            await self._broadcast({
                "type": "skill_install",
                "data": {
                    "success": success,
                    "message": message,
                    "source": source,
                },
            })
            # Refresh the list
            if success:
                await self._handle_skill_list()
        except Exception as e:
            await self._broadcast({
                "type": "skill_install",
                "data": {
                    "success": False,
                    "error": str(e),
                    "source": source,
                },
            })

    async def _handle_skill_create(
        self, name: str, description: str, content: str = ""
    ) -> None:
        """Create a new skill scaffold."""
        try:
            success, message = create_skill_scaffold(
                name, description, content if content else None
            )
            await self._broadcast({
                "type": "skill_create",
                "data": {
                    "success": success,
                    "message": message,
                    "name": name,
                },
            })
            # Refresh the list
            if success:
                await self._handle_skill_list()
        except Exception as e:
            await self._broadcast({
                "type": "skill_create",
                "data": {
                    "success": False,
                    "error": str(e),
                    "name": name,
                },
            })

    async def _handle_skill_template(self, name: str, description: str) -> None:
        """Get a skill template for the given name and description."""
        try:
            template = get_skill_template(name or "my-skill", description)
            await self._broadcast({
                "type": "skill_template",
                "data": {
                    "success": True,
                    "template": template,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "skill_template",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_skill_remove(self, name: str) -> None:
        """Remove a skill."""
        try:
            success, message = remove_skill(name)
            await self._broadcast({
                "type": "skill_remove",
                "data": {
                    "success": success,
                    "message": message,
                    "name": name,
                },
            })
            # Refresh the list
            if success:
                await self._handle_skill_list()
        except Exception as e:
            await self._broadcast({
                "type": "skill_remove",
                "data": {
                    "success": False,
                    "error": str(e),
                    "name": name,
                },
            })

    async def _handle_skill_dirs(self) -> None:
        """Get skill search directories."""
        try:
            dirs = get_skill_search_directories()
            await self._broadcast({
                "type": "skill_dirs",
                "data": {
                    "success": True,
                    "directories": dirs,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "skill_dirs",
                "data": {
                    "success": False,
                    "error": str(e),
                    "directories": [],
                },
            })

    # =====================
    # Integration Handlers
    # =====================

    async def _handle_integration_list(self) -> None:
        """Get list of all integrations with status."""
        try:
            integrations = list_integrations()
            # Calculate stats
            total = len(integrations)
            connected = sum(1 for i in integrations if i.get("connected", False))

            await self._broadcast({
                "type": "integration_list",
                "data": {
                    "success": True,
                    "integrations": integrations,
                    "total": total,
                    "connected": connected,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "integration_list",
                "data": {
                    "success": False,
                    "error": str(e),
                    "integrations": [],
                    "total": 0,
                    "connected": 0,
                },
            })

    async def _handle_integration_info(self, integration_id: str) -> None:
        """Get detailed info about an integration."""
        try:
            info = get_integration_info(integration_id)
            if info:
                await self._broadcast({
                    "type": "integration_info",
                    "data": {
                        "success": True,
                        "id": integration_id,
                        "integration": info,
                    },
                })
            else:
                await self._broadcast({
                    "type": "integration_info",
                    "data": {
                        "success": False,
                        "error": f"Integration '{integration_id}' not found",
                        "id": integration_id,
                    },
                })
        except Exception as e:
            await self._broadcast({
                "type": "integration_info",
                "data": {
                    "success": False,
                    "error": str(e),
                    "id": integration_id,
                },
            })

    async def _handle_integration_connect_token(
        self, integration_id: str, credentials: Dict[str, str]
    ) -> None:
        """Connect an integration using token/credentials."""
        try:
            success, message = await connect_integration_token(integration_id, credentials)
            await self._broadcast({
                "type": "integration_connect_result",
                "data": {
                    "success": success,
                    "message": message,
                    "id": integration_id,
                },
            })
            # Refresh the list on success (listener is started by connect_integration_token)
            if success:
                await self._handle_integration_list()
        except Exception as e:
            await self._broadcast({
                "type": "integration_connect_result",
                "data": {
                    "success": False,
                    "error": str(e),
                    "id": integration_id,
                },
            })

    async def _handle_integration_connect_oauth(self, integration_id: str) -> None:
        """Start OAuth flow for an integration (non-blocking)."""
        # Cancel any existing OAuth task for this integration
        if integration_id in self._oauth_tasks:
            self._oauth_tasks[integration_id].cancel()

        # Run OAuth in background task so WebSocket message loop stays responsive
        task = asyncio.create_task(self._run_oauth_flow(integration_id))
        self._oauth_tasks[integration_id] = task

    async def _run_oauth_flow(self, integration_id: str) -> None:
        """Execute OAuth flow and broadcast result (runs as background task)."""
        try:
            success, message = await connect_integration_oauth(integration_id)
            await self._broadcast({
                "type": "integration_connect_result",
                "data": {
                    "success": success,
                    "message": message,
                    "id": integration_id,
                },
            })
            # Refresh the list on success (listener is started by connect_integration_oauth)
            if success:
                await self._handle_integration_list()
        except asyncio.CancelledError:
            # OAuth was cancelled by user closing the modal
            await self._broadcast({
                "type": "integration_connect_result",
                "data": {
                    "success": False,
                    "message": "OAuth cancelled",
                    "id": integration_id,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "integration_connect_result",
                "data": {
                    "success": False,
                    "error": str(e),
                    "id": integration_id,
                },
            })
        finally:
            self._oauth_tasks.pop(integration_id, None)

    async def _handle_integration_connect_interactive(self, integration_id: str) -> None:
        """Connect an integration using interactive flow (non-blocking)."""
        # Cancel any existing interactive task for this integration
        if integration_id in self._oauth_tasks:
            self._oauth_tasks[integration_id].cancel()

        # Run interactive flow in background task so WebSocket message loop stays responsive
        task = asyncio.create_task(self._run_interactive_flow(integration_id))
        self._oauth_tasks[integration_id] = task

    async def _run_interactive_flow(self, integration_id: str) -> None:
        """Execute interactive flow and broadcast result (runs as background task)."""
        try:
            success, message = await connect_integration_interactive(integration_id)
            await self._broadcast({
                "type": "integration_connect_result",
                "data": {
                    "success": success,
                    "message": message,
                    "id": integration_id,
                },
            })
            # Refresh the list on success (listener is started by connect_integration_interactive)
            if success:
                await self._handle_integration_list()
        except asyncio.CancelledError:
            # Interactive flow was cancelled by user closing the modal
            await self._broadcast({
                "type": "integration_connect_result",
                "data": {
                    "success": False,
                    "message": "Connection cancelled",
                    "id": integration_id,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "integration_connect_result",
                "data": {
                    "success": False,
                    "error": str(e),
                    "id": integration_id,
                },
            })
        finally:
            self._oauth_tasks.pop(integration_id, None)

    async def _handle_integration_connect_cancel(self, integration_id: str) -> None:
        """Cancel an in-progress OAuth/interactive flow."""
        if integration_id in self._oauth_tasks:
            self._oauth_tasks[integration_id].cancel()
            # Result will be broadcast by the cancelled task's CancelledError handler

    async def _handle_integration_disconnect(
        self, integration_id: str, account_id: Optional[str] = None
    ) -> None:
        """Disconnect an integration account."""
        try:
            success, message = await disconnect_integration(integration_id, account_id)
            await self._broadcast({
                "type": "integration_disconnect_result",
                "data": {
                    "success": success,
                    "message": message,
                    "id": integration_id,
                },
            })
            # Refresh the list on success
            if success:
                await self._handle_integration_list()
        except Exception as e:
            await self._broadcast({
                "type": "integration_disconnect_result",
                "data": {
                    "success": False,
                    "error": str(e),
                    "id": integration_id,
                },
            })

    # =====================
    # Jira Settings
    # =====================

    async def _handle_jira_get_settings(self) -> None:
        """Get current Jira watch tag and labels."""
        try:
            from app.external_comms.credentials import has_credential, load_credential
            from app.external_comms.platforms.jira import JiraCredential
            if not has_credential("jira.json"):
                await self._broadcast({"type": "jira_settings", "data": {"success": False, "error": "Not connected"}})
                return
            cred = load_credential("jira.json", JiraCredential)
            await self._broadcast({
                "type": "jira_settings",
                "data": {
                    "success": True,
                    "watch_tag": cred.watch_tag if cred else "",
                    "watch_labels": cred.watch_labels if cred else [],
                },
            })
        except Exception as e:
            await self._broadcast({"type": "jira_settings", "data": {"success": False, "error": str(e)}})

    async def _handle_jira_update_settings(self, watch_tag=None, watch_labels=None) -> None:
        """Update Jira watch tag and/or labels."""
        try:
            from app.external_comms.platforms.jira import JiraClient
            client = JiraClient()
            if not client.has_credentials():
                await self._broadcast({"type": "jira_settings_result", "data": {"success": False, "error": "Not connected"}})
                return
            if watch_tag is not None:
                client.set_watch_tag(watch_tag)
            if watch_labels is not None:
                if isinstance(watch_labels, str):
                    watch_labels = [l.strip() for l in watch_labels.split(",") if l.strip()]
                client.set_watch_labels(watch_labels)
            # Return updated settings
            cred = client._load()
            await self._broadcast({
                "type": "jira_settings_result",
                "data": {
                    "success": True,
                    "watch_tag": cred.watch_tag,
                    "watch_labels": cred.watch_labels,
                    "message": "Jira settings updated",
                },
            })
        except Exception as e:
            await self._broadcast({"type": "jira_settings_result", "data": {"success": False, "error": str(e)}})

    # =====================
    # GitHub Settings
    # =====================

    async def _handle_github_get_settings(self) -> None:
        """Get current GitHub watch tag and repos."""
        try:
            from app.external_comms.credentials import has_credential, load_credential
            from app.external_comms.platforms.github import GitHubCredential
            if not has_credential("github.json"):
                await self._broadcast({"type": "github_settings", "data": {"success": False, "error": "Not connected"}})
                return
            cred = load_credential("github.json", GitHubCredential)
            await self._broadcast({
                "type": "github_settings",
                "data": {
                    "success": True,
                    "watch_tag": cred.watch_tag if cred else "",
                    "watch_repos": cred.watch_repos if cred else [],
                },
            })
        except Exception as e:
            await self._broadcast({"type": "github_settings", "data": {"success": False, "error": str(e)}})

    async def _handle_github_update_settings(self, watch_tag=None, watch_repos=None) -> None:
        """Update GitHub watch tag and/or repos."""
        try:
            from app.external_comms.platforms.github import GitHubClient
            client = GitHubClient()
            if not client.has_credentials():
                await self._broadcast({"type": "github_settings_result", "data": {"success": False, "error": "Not connected"}})
                return
            if watch_tag is not None:
                client.set_watch_tag(watch_tag)
            if watch_repos is not None:
                if isinstance(watch_repos, str):
                    watch_repos = [r.strip() for r in watch_repos.split(",") if r.strip()]
                client.set_watch_repos(watch_repos)
            cred = client._load()
            await self._broadcast({
                "type": "github_settings_result",
                "data": {
                    "success": True,
                    "watch_tag": cred.watch_tag,
                    "watch_repos": cred.watch_repos,
                    "message": "GitHub settings updated",
                },
            })
        except Exception as e:
            await self._broadcast({"type": "github_settings_result", "data": {"success": False, "error": str(e)}})

    # ==========================
    # Living UI Settings Handlers
    # ==========================

    async def _handle_living_ui_settings_get(self) -> None:
        """Get all Living UI projects with their settings."""
        from app.ui_layer.settings.living_ui_settings import get_living_ui_projects
        result = get_living_ui_projects()
        await self._broadcast({"type": "living_ui_settings_get", "data": result})

    async def _handle_living_ui_project_action(self, project_id: str, action: str) -> None:
        """Execute a project action (launch/stop/delete)."""
        from app.ui_layer.settings.living_ui_settings import living_ui_project_action
        result = await living_ui_project_action(project_id, action)
        await self._broadcast({"type": "living_ui_project_action", "data": result})

    async def _handle_living_ui_project_setting_update(self, project_id: str, setting: str, value) -> None:
        """Update a per-project setting."""
        from app.ui_layer.settings.living_ui_settings import update_project_setting
        result = update_project_setting(project_id, setting, value)
        await self._broadcast({"type": "living_ui_project_setting_update", "data": result})

    # =====================
    # Marketplace Handlers
    # =====================

    async def _handle_marketplace_list(self) -> None:
        """Fetch marketplace catalogue from GitHub."""
        import urllib.request
        import json as _json
        import re as _re

        CATALOGUE_URL = "https://raw.githubusercontent.com/CraftOS-dev/living-ui-marketplace/main/catalogue.json"

        try:
            import ssl, certifi
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            req = urllib.request.Request(CATALOGUE_URL, headers={'User-Agent': 'CraftBot'})
            response = urllib.request.urlopen(req, timeout=15, context=ssl_ctx)
            raw = response.read().decode()
            # Strip trailing commas before ] or } (tolerant of hand-edited JSON)
            raw = _re.sub(r',\s*([}\]])', r'\1', raw)
            catalogue = _json.loads(raw)
            await self._broadcast({
                "type": "living_ui_marketplace_list",
                "data": {"success": True, "apps": catalogue.get("apps", [])},
            })
        except Exception as e:
            await self._broadcast({
                "type": "living_ui_marketplace_list",
                "data": {"success": False, "error": str(e), "apps": []},
            })

    async def _handle_marketplace_install(self, app_id: str, app_name: str, app_description: str, custom_fields: dict = None) -> None:
        """Install a marketplace app."""
        if not app_id or not app_name:
            await self._broadcast({
                "type": "living_ui_marketplace_install",
                "data": {"success": False, "error": "App ID and name are required", "appId": app_id},
            })
            return

        result = await self._living_ui_manager.install_from_marketplace(
            app_id=app_id,
            app_name=app_name,
            app_description=app_description,
            custom_fields=custom_fields,
        )

        if result.get("status") == "success":
            # Also broadcast as living_ui_create so the sidebar updates
            await self._broadcast({
                "type": "living_ui_create",
                "data": {
                    "success": True,
                    "projectId": result["project"]["id"],
                    "project": result["project"],
                },
            })

        await self._broadcast({
            "type": "living_ui_marketplace_install",
            "data": {**result, "appId": app_id},
        })

    async def _handle_living_ui_import(self, source: str, name: str) -> None:
        """Handle import of an external app or ZIP — creates a task with the importer skill."""
        if not source:
            return

        is_zip = source.lower().endswith('.zip')

        if is_zip:
            task_instruction = (
                f"Import this Living UI project from a ZIP file:\n"
                f"ZIP path: {source}\n"
                f"Name: {name}\n\n"
                f"Steps:\n"
                f"1. Call living_ui_import_zip to extract and register the project\n"
                f"2. Review the project structure and manifest\n"
                f"3. Install dependencies if needed\n"
                f"4. Launch the app and verify it works\n"
                f"5. Clean up the ZIP file after successful import"
            )
        else:
            task_instruction = (
                f"Import this external app as a Living UI:\n"
                f"Source: {source}\n"
                f"Name: {name}\n\n"
                f"Follow the living-ui-importer skill instructions:\n"
                f"1. Clone/copy the source code\n"
                f"2. Detect the app type (Go, Node, Python, etc.) — NEVER use Docker if native build is possible\n"
                f"3. Determine build/install command, start command, port config, and health check\n"
                f"4. Call living_ui_import_external with the detected configuration\n"
                f"5. Launch the app and verify it works\n"
                f"6. Create LIVING_UI.md documenting the app"
            )

        task_id = self._controller.agent.task_manager.create_task(
            task_name=f"Import Living UI: {name}",
            task_instruction=task_instruction,
            mode="complex",
            action_sets=["file_operations", "code_execution", "living_ui", "core"],
            selected_skills=["living-ui-importer"],
        )

        if task_id:
            from app.trigger import Trigger
            import time
            trigger = Trigger(
                fire_at=time.time(),
                priority=50,
                next_action_description=f"[Living UI] Import: {name}",
                session_id=task_id,
                payload={"type": "living_ui_import", "source": source},
            )
            await self._controller.agent.triggers.put(trigger)

        await self._broadcast({
            "type": "living_ui_import",
            "data": {"status": "started", "name": name, "source": source},
        })

    # =====================
    # WhatsApp QR Code Flow
    # =====================

    async def _handle_whatsapp_start_qr(self) -> None:
        """Start WhatsApp Web session and return QR code."""
        try:
            result = await start_whatsapp_qr_session()
            await self._broadcast({
                "type": "whatsapp_qr_result",
                "data": result,
            })
        except Exception as e:
            await self._broadcast({
                "type": "whatsapp_qr_result",
                "data": {
                    "success": False,
                    "status": "error",
                    "message": str(e),
                },
            })

    async def _handle_whatsapp_check_status(self, session_id: str) -> None:
        """Check WhatsApp session status."""
        try:
            result = await check_whatsapp_session_status(session_id)
            await self._broadcast({
                "type": "whatsapp_status_result",
                "data": result,
            })
            # If connected, refresh the integrations list (listener is started by check_whatsapp_session_status)
            if result.get("connected"):
                await self._handle_integration_list()
        except Exception as e:
            await self._broadcast({
                "type": "whatsapp_status_result",
                "data": {
                    "success": False,
                    "status": "error",
                    "connected": False,
                    "message": str(e),
                },
            })

    async def _handle_whatsapp_cancel(self, session_id: str) -> None:
        """Cancel WhatsApp session."""
        try:
            result = cancel_whatsapp_session(session_id)
            await self._broadcast({
                "type": "whatsapp_cancel_result",
                "data": result,
            })
        except Exception as e:
            await self._broadcast({
                "type": "whatsapp_cancel_result",
                "data": {
                    "success": False,
                    "message": str(e),
                },
            })

    async def _broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast message to all connected clients."""
        if not self._ws_clients:
            return

        json_msg = json.dumps(message)
        disconnected = set()

        for ws in self._ws_clients.copy():
            try:
                await ws.send_str(json_msg)
            except (ClientConnectionResetError, ConnectionResetError, RuntimeError):
                # Silently handle expected connection errors
                disconnected.add(ws)
            except Exception:
                # Log unexpected errors
                disconnected.add(ws)

        # Clean up disconnected clients
        self._ws_clients -= disconnected

    async def _broadcast_error_to_chat(self, error_message: str) -> None:
        """Broadcast an error message to the chat panel for debugging."""
        import time
        try:
            await self._broadcast({
                "type": "chat_message",
                "data": {
                    "sender": "System",
                    "content": f"[DEBUG ERROR] {error_message}",
                    "style": "error",
                    "timestamp": time.time(),
                    "messageId": f"error:{time.time()}",
                },
            })
        except Exception:
            # If broadcast fails, at least print to console
            print(f"[BROWSER ADAPTER] Failed to broadcast error: {error_message}")

    async def _broadcast_metrics_loop(self) -> None:
        """Periodically broadcast dashboard metrics to subscribed clients only."""
        while self._running:
            try:
                if self._metrics_subscribers:
                    metrics = self._metrics_collector.get_metrics()
                    payload = {"type": "dashboard_metrics", "data": metrics.to_dict()}
                    disconnected: Set = set()
                    for ws in self._metrics_subscribers.copy():
                        try:
                            await ws.send_json(payload)
                        except Exception:
                            disconnected.add(ws)
                    self._metrics_subscribers -= disconnected
                await asyncio.sleep(2)  # Update every 2 seconds
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)  # Back off on error

    # ─────────────────────────────────────────────────────────────────────
    # File Operation Handlers
    # ─────────────────────────────────────────────────────────────────────

    def _validate_path(self, file_path: str) -> Path:
        """Validate that the path is within the workspace. Returns absolute path."""
        workspace = Path(AGENT_WORKSPACE_ROOT).resolve()
        # Normalize the path - handle both relative and absolute paths
        if file_path.startswith("/") or file_path.startswith("\\"):
            # Treat as relative to workspace
            target = workspace / file_path.lstrip("/\\")
        else:
            target = workspace / file_path
        target = target.resolve()

        # Security check - ensure path is within workspace
        if not str(target).startswith(str(workspace)):
            raise ValueError(f"Path '{file_path}' is outside workspace")

        return target

    def _get_file_info(self, path: Path) -> Dict[str, Any]:
        """Get file/directory information."""
        workspace = Path(AGENT_WORKSPACE_ROOT).resolve()
        stat = path.stat()
        rel_path = str(path.relative_to(workspace)).replace("\\", "/")

        return {
            "name": path.name,
            "path": rel_path,
            "type": "directory" if path.is_dir() else "file",
            "size": stat.st_size if path.is_file() else None,
            "modified": int(stat.st_mtime * 1000),  # milliseconds for JS
        }

    async def _handle_file_list(
        self, directory: str, offset: int = 0, limit: int = 50, search: str = ""
    ) -> None:
        """List files in a directory within the workspace with pagination and search."""
        try:
            workspace = Path(AGENT_WORKSPACE_ROOT).resolve()

            # Ensure workspace exists
            if not workspace.exists():
                workspace.mkdir(parents=True, exist_ok=True)

            if directory:
                target = self._validate_path(directory)
            else:
                target = workspace

            if not target.exists():
                raise FileNotFoundError(f"Directory not found: {directory}")

            if not target.is_dir():
                raise ValueError(f"Path is not a directory: {directory}")

            # Collect and sort all files
            all_files = sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))

            # Apply search filter
            if search:
                search_lower = search.lower()
                all_files = [f for f in all_files if search_lower in f.name.lower()]

            total = len(all_files)

            # Apply pagination
            paginated = all_files[offset:offset + limit]
            files = [self._get_file_info(item) for item in paginated]

            await self._broadcast({
                "type": "file_list",
                "data": {
                    "directory": directory,
                    "files": files,
                    "total": total,
                    "hasMore": offset + limit < total,
                    "offset": offset,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "file_list",
                "data": {
                    "directory": directory,
                    "files": [],
                    "total": 0,
                    "hasMore": False,
                    "offset": 0,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_file_read(self, file_path: str) -> None:
        """Read file content."""
        try:
            target = self._validate_path(file_path)

            if not target.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            if target.is_dir():
                raise ValueError(f"Cannot read directory as file: {file_path}")

            # Check file size (limit to 10MB for text preview)
            if target.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("File too large to preview (max 10MB)")

            # Try to read as text, fallback to binary info
            try:
                content = target.read_text(encoding="utf-8")
                is_binary = False
            except UnicodeDecodeError:
                content = None
                is_binary = True

            file_info = self._get_file_info(target)

            await self._broadcast({
                "type": "file_read",
                "data": {
                    "path": file_path,
                    "content": content,
                    "isBinary": is_binary,
                    "fileInfo": file_info,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "file_read",
                "data": {
                    "path": file_path,
                    "content": None,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_file_write(self, file_path: str, content: str) -> None:
        """Write content to a file."""
        try:
            target = self._validate_path(file_path)

            # Ensure parent directory exists
            target.parent.mkdir(parents=True, exist_ok=True)

            target.write_text(content, encoding="utf-8")

            file_info = self._get_file_info(target)

            await self._broadcast({
                "type": "file_write",
                "data": {
                    "path": file_path,
                    "fileInfo": file_info,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "file_write",
                "data": {
                    "path": file_path,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_file_create(self, file_path: str, file_type: str) -> None:
        """Create a new file or directory."""
        try:
            target = self._validate_path(file_path)

            if target.exists():
                raise ValueError(f"Path already exists: {file_path}")

            if file_type == "directory":
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()

            file_info = self._get_file_info(target)

            await self._broadcast({
                "type": "file_create",
                "data": {
                    "path": file_path,
                    "fileType": file_type,
                    "fileInfo": file_info,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "file_create",
                "data": {
                    "path": file_path,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_file_delete(self, file_path: str) -> None:
        """Delete a file or directory."""
        try:
            target = self._validate_path(file_path)

            if not target.exists():
                raise FileNotFoundError(f"Path not found: {file_path}")

            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

            await self._broadcast({
                "type": "file_delete",
                "data": {
                    "path": file_path,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "file_delete",
                "data": {
                    "path": file_path,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_file_rename(self, old_path: str, new_name: str) -> None:
        """Rename a file or directory."""
        try:
            target = self._validate_path(old_path)

            if not target.exists():
                raise FileNotFoundError(f"Path not found: {old_path}")

            # New path is in the same directory with new name
            new_target = target.parent / new_name

            # Validate new path is still within workspace
            self._validate_path(str(new_target.relative_to(Path(AGENT_WORKSPACE_ROOT).resolve())))

            if new_target.exists():
                raise ValueError(f"Target already exists: {new_name}")

            target.rename(new_target)

            file_info = self._get_file_info(new_target)

            await self._broadcast({
                "type": "file_rename",
                "data": {
                    "oldPath": old_path,
                    "newPath": str(new_target.relative_to(Path(AGENT_WORKSPACE_ROOT).resolve())).replace("\\", "/"),
                    "fileInfo": file_info,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "file_rename",
                "data": {
                    "oldPath": old_path,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_file_batch_delete(self, paths: List[str]) -> None:
        """Delete multiple files/directories."""
        results = []
        for file_path in paths:
            try:
                target = self._validate_path(file_path)

                if not target.exists():
                    results.append({"path": file_path, "success": False, "error": "Not found"})
                    continue

                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()

                results.append({"path": file_path, "success": True})
            except Exception as e:
                results.append({"path": file_path, "success": False, "error": str(e)})

        await self._broadcast({
            "type": "file_batch_delete",
            "data": {
                "results": results,
                "success": all(r["success"] for r in results),
            },
        })

    async def _handle_file_move(self, src_path: str, dest_path: str) -> None:
        """Move a file or directory."""
        try:
            src = self._validate_path(src_path)
            dest = self._validate_path(dest_path)

            if not src.exists():
                raise FileNotFoundError(f"Source not found: {src_path}")

            # If dest is a directory, move into it
            if dest.exists() and dest.is_dir():
                dest = dest / src.name

            if dest.exists():
                raise ValueError(f"Destination already exists: {dest_path}")

            shutil.move(str(src), str(dest))

            file_info = self._get_file_info(dest)

            await self._broadcast({
                "type": "file_move",
                "data": {
                    "srcPath": src_path,
                    "destPath": str(dest.relative_to(Path(AGENT_WORKSPACE_ROOT).resolve())).replace("\\", "/"),
                    "fileInfo": file_info,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "file_move",
                "data": {
                    "srcPath": src_path,
                    "destPath": dest_path,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_file_copy(self, src_path: str, dest_path: str) -> None:
        """Copy a file or directory."""
        try:
            src = self._validate_path(src_path)
            dest = self._validate_path(dest_path)

            if not src.exists():
                raise FileNotFoundError(f"Source not found: {src_path}")

            # If dest is a directory, copy into it
            if dest.exists() and dest.is_dir():
                dest = dest / src.name

            if dest.exists():
                raise ValueError(f"Destination already exists: {dest_path}")

            if src.is_dir():
                shutil.copytree(str(src), str(dest))
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dest))

            file_info = self._get_file_info(dest)

            await self._broadcast({
                "type": "file_copy",
                "data": {
                    "srcPath": src_path,
                    "destPath": str(dest.relative_to(Path(AGENT_WORKSPACE_ROOT).resolve())).replace("\\", "/"),
                    "fileInfo": file_info,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "file_copy",
                "data": {
                    "srcPath": src_path,
                    "destPath": dest_path,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_file_upload(self, file_path: str, content_b64: str) -> None:
        """Upload a file (content is base64 encoded)."""
        try:
            target = self._validate_path(file_path)

            # Decode base64 content
            content = base64.b64decode(content_b64)

            # Ensure parent directory exists
            target.parent.mkdir(parents=True, exist_ok=True)

            target.write_bytes(content)

            file_info = self._get_file_info(target)

            await self._broadcast({
                "type": "file_upload",
                "data": {
                    "path": file_path,
                    "fileInfo": file_info,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "file_upload",
                "data": {
                    "path": file_path,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_file_download(self, file_path: str) -> None:
        """Download a file (returns base64 encoded content)."""
        try:
            target = self._validate_path(file_path)

            if not target.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            if target.is_dir():
                raise ValueError(f"Cannot download directory: {file_path}")

            # Read and encode as base64
            content = target.read_bytes()
            content_b64 = base64.b64encode(content).decode("utf-8")

            file_info = self._get_file_info(target)

            await self._broadcast({
                "type": "file_download",
                "data": {
                    "path": file_path,
                    "content": content_b64,
                    "fileInfo": file_info,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "file_download",
                "data": {
                    "path": file_path,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_chat_history(self, before_timestamp: float, limit: int = 50) -> None:
        """Load older chat messages for infinite scroll."""
        try:
            older_messages = self._chat.get_messages_before(before_timestamp, limit=limit)
            total = self._chat.get_total_count()

            messages_data = []
            for m in older_messages:
                msg_data = {
                    "sender": m.sender,
                    "content": m.content,
                    "style": m.style,
                    "timestamp": m.timestamp,
                    "messageId": m.message_id,
                }
                if m.attachments:
                    msg_data["attachments"] = [
                        {
                            "name": att.name,
                            "path": att.path,
                            "type": att.type,
                            "size": att.size,
                            "url": att.url,
                        }
                        for att in m.attachments
                    ]
                if m.task_session_id:
                    msg_data["taskSessionId"] = m.task_session_id
                if m.options:
                    msg_data["options"] = [
                        {"label": o.label, "value": o.value, "style": o.style}
                        for o in m.options
                    ]
                if m.option_selected:
                    msg_data["optionSelected"] = m.option_selected
                messages_data.append(msg_data)

            await self._broadcast({
                "type": "chat_history",
                "data": {
                    "messages": messages_data,
                    "hasMore": len(older_messages) == limit,
                    "total": total,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "chat_history",
                "data": {
                    "messages": [],
                    "hasMore": False,
                    "total": 0,
                    "error": str(e),
                },
            })

    async def _handle_action_history(self, before_timestamp: float, limit: int = 15) -> None:
        """Load older tasks (and their actions) for pagination."""
        try:
            # before_timestamp is in milliseconds from frontend, convert to seconds
            before_ts_seconds = before_timestamp / 1000.0
            older_items = self._action_panel.get_tasks_before(before_ts_seconds, task_limit=limit)

            # Count how many tasks were returned to determine hasMore
            task_count = sum(1 for a in older_items if a.item_type == 'task')

            actions_data = [
                {
                    "id": a.id,
                    "name": a.name,
                    "status": a.status,
                    "itemType": a.item_type,
                    "parentId": a.parent_id,
                    "createdAt": int(a.created_at * 1000),
                    "duration": a.duration,
                    "input": a.input_data,
                    "output": a.output_data,
                    "error": a.error_message,
                }
                for a in older_items
            ]

            await self._broadcast({
                "type": "action_history",
                "data": {
                    "actions": actions_data,
                    "hasMore": task_count == limit,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "action_history",
                "data": {
                    "actions": [],
                    "hasMore": False,
                    "error": str(e),
                },
            })

    async def _handle_chat_message_with_attachments(
        self,
        content: str,
        attachments: List[Dict[str, Any]],
        reply_context: Optional[Dict[str, Any]] = None,
        living_ui_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> None:
        """Handle user chat message with attachments and optional reply context."""
        import uuid
        from app.ui_layer.state.ui_state import AgentStateType
        from app.ui_layer.events import UIEvent, UIEventType

        try:
            processed_attachments: List[Attachment] = []
            attachment_note = ""

            if attachments:
                # Process each attachment - save to workspace/download/
                download_dir = Path(AGENT_WORKSPACE_ROOT) / "download"
                download_dir.mkdir(parents=True, exist_ok=True)

                parts = []
                for att in attachments:
                    name = att.get("name", "unknown")
                    file_type = att.get("type", "application/octet-stream")
                    size = att.get("size", 0)
                    content_b64 = att.get("content", "")

                    # Generate unique filename to avoid conflicts
                    unique_name = f"{uuid.uuid4().hex[:8]}_{name}"
                    file_path = download_dir / unique_name
                    relative_path = f"download/{unique_name}"

                    # Save file to workspace
                    if content_b64:
                        try:
                            file_content = base64.b64decode(content_b64)
                            file_path.write_bytes(file_content)
                            size = len(file_content)
                        except Exception as e:
                            print(f"[BROWSER ADAPTER] Error saving attachment {name}: {e}")
                            continue

                    # Create attachment object
                    attachment = Attachment(
                        name=name,
                        path=relative_path,
                        type=file_type,
                        size=size,
                        url=f"/api/workspace/{relative_path}",
                    )
                    processed_attachments.append(attachment)
                    parts.append(f"{name} ({file_type}, {size} B), saved to workspace/{relative_path}")

                if parts:
                    attachment_note = "\n\nATTACHMENTS:\n" + "\n".join(parts)

            # Display user message in chat with clean content and visual attachments
            # (This is what the user sees in the chat bubble - no attachment metadata text)
            user_message = ChatMessage(
                sender="You",
                content=content,
                style="user",
                timestamp=time.time(),
                attachments=processed_attachments if processed_attachments else None,
                client_id=client_id,
            )
            await self._chat.append_message(user_message)

            # Combine content with attachment info for agent context
            # (This is what the agent sees in the event stream - includes file paths)
            agent_context = content + attachment_note

            # Add reply context note (similar to attachment_note pattern)
            if reply_context and reply_context.get("originalMessage"):
                reply_note = f"\n\n[REPLYING TO PREVIOUS AGENT MESSAGE]:\n{reply_context['originalMessage']}"
                agent_context = agent_context + reply_note

            if not agent_context.strip():
                return

            # Update state and route to agent directly
            # (Skip submit_message to avoid duplicate chat message)
            self._controller._state_store.dispatch("SET_AGENT_STATE", AgentStateType.WORKING.value)

            # Emit state change event so adapters can update status immediately
            self._controller._event_bus.emit(
                UIEvent(
                    type=UIEventType.AGENT_STATE_CHANGED,
                    data={
                        "state": AgentStateType.WORKING.value,
                        "status_message": "Agent is working...",
                    },
                    source_adapter=self._adapter_id,
                )
            )

            # Route directly to agent with full context
            payload = {
                "text": agent_context,
                "sender": {"id": self._adapter_id or "user", "type": "user"},
                "gui_mode": self._controller._state_store.state.gui_mode,
            }
            # Include target session ID if replying to a specific session
            if reply_context and reply_context.get("sessionId"):
                payload["target_session_id"] = reply_context["sessionId"]
            if living_ui_id:
                payload["living_ui_id"] = living_ui_id

            await self._controller._agent._handle_chat_message(payload)

        except Exception as e:
            import traceback
            print(f"[BROWSER ADAPTER] Error in _handle_chat_message_with_attachments: {e}")
            traceback.print_exc()
            # Still try to display an error message to the user
            error_message = ChatMessage(
                sender="System",
                content=f"Error processing attachment: {str(e)}",
                style="error",
                timestamp=time.time(),
            )
            await self._chat.append_message(error_message)

    async def _handle_chat_attachment_upload(self, data: Dict[str, Any]) -> None:
        """Handle uploading a single attachment for chat."""
        import uuid

        try:
            name = data.get("name", "unknown")
            file_type = data.get("type", "application/octet-stream")
            content_b64 = data.get("content", "")

            if not content_b64:
                raise ValueError("No content provided")

            # Create download directory if needed
            download_dir = Path(AGENT_WORKSPACE_ROOT) / "download"
            download_dir.mkdir(parents=True, exist_ok=True)

            # Generate unique filename
            unique_name = f"{uuid.uuid4().hex[:8]}_{name}"
            file_path = download_dir / unique_name
            relative_path = f"download/{unique_name}"

            # Decode and save file
            file_content = base64.b64decode(content_b64)
            file_path.write_bytes(file_content)

            # Build response
            await self._broadcast({
                "type": "chat_attachment_upload",
                "data": {
                    "success": True,
                    "attachment": {
                        "name": name,
                        "path": relative_path,
                        "type": file_type,
                        "size": len(file_content),
                        "url": f"/api/workspace/{relative_path}",
                    },
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "chat_attachment_upload",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_agent_profile_picture_upload(self, data: Dict[str, Any]) -> None:
        """Handle uploading a new agent profile picture."""
        from app.ui_layer.settings.general_settings import (
            PROFILE_MIME_TO_EXT,
            ALLOWED_PROFILE_EXTS,
            MAX_PROFILE_PICTURE_BYTES,
            save_agent_profile_picture,
        )

        try:
            name = data.get("name", "")
            # Accept "mimeType" (preferred — avoids collision with the envelope "type" key)
            # and fall back to legacy "type" for compatibility.
            mime_type = (data.get("mimeType") or data.get("type") or "").lower()
            content_b64 = data.get("content", "")

            if not content_b64:
                raise ValueError("No content provided")

            # Resolve extension from MIME first, then fall back to filename.
            ext: Optional[str] = PROFILE_MIME_TO_EXT.get(mime_type)
            if not ext and name:
                guess = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if guess in ALLOWED_PROFILE_EXTS:
                    ext = guess
            if not ext:
                raise ValueError(
                    f"Unsupported image type. Allowed: {', '.join(sorted(ALLOWED_PROFILE_EXTS))}"
                )

            raw_bytes = base64.b64decode(content_b64)
            if len(raw_bytes) > MAX_PROFILE_PICTURE_BYTES:
                raise ValueError(
                    f"Image too large (max {MAX_PROFILE_PICTURE_BYTES // (1024 * 1024)} MB)"
                )

            result = save_agent_profile_picture(ext, raw_bytes)

            await self._broadcast({
                "type": "agent_profile_picture_upload",
                "data": result,
            })
        except Exception as e:
            await self._broadcast({
                "type": "agent_profile_picture_upload",
                "data": {
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_agent_profile_picture_remove(self) -> None:
        """Handle removing the custom agent profile picture."""
        from app.ui_layer.settings.general_settings import remove_agent_profile_picture

        try:
            result = remove_agent_profile_picture()
        except Exception as e:
            result = {"success": False, "error": str(e)}

        await self._broadcast({
            "type": "agent_profile_picture_remove",
            "data": result,
        })

    async def _handle_open_file(self, file_path: str) -> None:
        """Open a file with the system default application."""
        import subprocess
        import platform

        try:
            target = self._validate_path(file_path)

            if not target.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            # Open file with default application based on OS
            system = platform.system()
            if system == "Windows":
                os.startfile(str(target))
            elif system == "Darwin":  # macOS
                subprocess.run(["open", str(target)], check=True)
            else:  # Linux and others
                subprocess.run(["xdg-open", str(target)], check=True)

            await self._broadcast({
                "type": "open_file",
                "data": {
                    "path": file_path,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "open_file",
                "data": {
                    "path": file_path,
                    "success": False,
                    "error": str(e),
                },
            })

    async def _handle_open_folder(self, file_path: str) -> None:
        """Open the folder containing a file in the system file explorer."""
        import subprocess
        import platform

        try:
            target = self._validate_path(file_path)

            if not target.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            # Get parent folder
            folder = target.parent if target.is_file() else target

            # Open folder with file explorer based on OS
            system = platform.system()
            if system == "Windows":
                # Use explorer with /select to highlight the file
                if target.is_file():
                    subprocess.run(["explorer", "/select,", str(target)], check=True)
                else:
                    subprocess.run(["explorer", str(folder)], check=True)
            elif system == "Darwin":  # macOS
                if target.is_file():
                    subprocess.run(["open", "-R", str(target)], check=True)
                else:
                    subprocess.run(["open", str(folder)], check=True)
            else:  # Linux and others
                subprocess.run(["xdg-open", str(folder)], check=True)

            await self._broadcast({
                "type": "open_folder",
                "data": {
                    "path": file_path,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "open_folder",
                "data": {
                    "path": file_path,
                    "success": False,
                    "error": str(e),
                },
            })

    def _prepare_attachment(self, file_path: str) -> Attachment:
        """
        Prepare a file for attachment by validating and copying if needed.

        Args:
            file_path: Absolute path or path relative to workspace

        Returns:
            Attachment object ready to be sent

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If path points to a directory
        """
        import uuid
        import shutil
        import mimetypes

        # Handle both absolute and relative paths
        source_path = Path(file_path)

        # Check if it's an absolute path
        if source_path.is_absolute():
            target = source_path
        else:
            # Treat as relative to workspace
            target = self._validate_path(file_path)

        if not target.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if target.is_dir():
            raise ValueError(f"Cannot attach directory: {file_path}")

        file_name = target.name
        file_size = target.stat().st_size

        # If file is outside workspace, copy it to workspace/download/
        workspace = Path(AGENT_WORKSPACE_ROOT).resolve()
        if not str(target.resolve()).startswith(str(workspace)):
            # Copy file to workspace download folder
            download_dir = workspace / "download"
            download_dir.mkdir(parents=True, exist_ok=True)

            # Generate unique filename to avoid conflicts
            unique_name = f"{uuid.uuid4().hex[:8]}_{file_name}"
            dest_path = download_dir / unique_name
            shutil.copy2(target, dest_path)

            # Update paths for the attachment
            relative_path = f"download/{unique_name}"
        else:
            # File is already in workspace, get relative path
            relative_path = str(target.relative_to(workspace)).replace("\\", "/")

        # Determine MIME type
        mime_type, _ = mimetypes.guess_type(file_name)
        if mime_type is None:
            mime_type = "application/octet-stream"

        return Attachment(
            name=file_name,
            path=relative_path,
            type=mime_type,
            size=file_size,
            url=f"/api/workspace/{relative_path}",
        )

    async def send_message_with_attachment(
        self,
        message: str,
        file_path: str,
        sender: Optional[str] = None,
        style: str = "agent",
    ) -> Dict[str, Any]:
        """
        Send a chat message with a single attachment from the agent.

        Deprecated: Use send_message_with_attachments for new code.

        Args:
            message: The message content
            file_path: Absolute path or path relative to workspace
            sender: Message sender (default: uses agent name from onboarding)
            style: Message style (default: "agent")

        Returns:
            Dict with 'success', 'files_sent', and optionally 'errors'
        """
        return await self.send_message_with_attachments(message, [file_path], sender, style)

    async def send_message_with_attachments(
        self,
        message: str,
        file_paths: list,
        sender: Optional[str] = None,
        style: str = "agent",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a chat message with one or more attachments from the agent.

        This method is called by the agent to send files to the user.
        Supports both absolute paths and workspace-relative paths.

        Args:
            message: The message content
            file_paths: List of absolute paths or paths relative to workspace
            sender: Message sender (default: uses agent name from onboarding)
            style: Message style (default: "agent")
            session_id: Optional task/session ID for multi-task isolation.

        Returns:
            Dict with 'success' (bool), 'files_sent' (int), and optionally 'errors' (list of str)
        """
        try:
            # Get agent name from onboarding state if sender not provided
            # (same as _handle_agent_message in base adapter)
            if sender is None:
                from app.onboarding import onboarding_manager
                sender = onboarding_manager.state.agent_name or "Agent"

            attachments = []
            errors = []

            for file_path in file_paths:
                try:
                    attachment = self._prepare_attachment(file_path)
                    attachments.append(attachment)
                except Exception as e:
                    errors.append(f"{file_path}: {str(e)}")

            # If we have at least one successful attachment, send the message
            if attachments:
                chat_message = ChatMessage(
                    sender=sender,
                    content=message,
                    style=style,
                    attachments=attachments,
                    task_session_id=session_id,
                )
                await self._chat.append_message(chat_message)

            # If there were errors, send an error message listing them
            if errors:
                error_content = "Failed to attach some files:\n" + "\n".join(f"- {e}" for e in errors)
                error_message = ChatMessage(
                    sender="system",
                    content=error_content,
                    style="error",
                )
                await self._chat.append_message(error_message)

            # If no attachments succeeded at all, send a general error
            if not attachments and not errors:
                error_message = ChatMessage(
                    sender="system",
                    content="No files provided to attach.",
                    style="error",
                )
                await self._chat.append_message(error_message)
                return {"success": False, "files_sent": 0, "errors": ["No files provided to attach."]}

            # Return status
            return {
                "success": len(attachments) > 0 and len(errors) == 0,
                "files_sent": len(attachments),
                "errors": errors if errors else None,
            }

        except Exception as e:
            # Send error message if attachment fails
            error_message = ChatMessage(
                sender="system",
                content=f"Failed to send attachments: {str(e)}",
                style="error",
            )
            await self._chat.append_message(error_message)
            return {"success": False, "files_sent": 0, "errors": [str(e)]}

    def _get_initial_state(self) -> Dict[str, Any]:
        """Get initial state for new connections."""
        from app.onboarding import onboarding_manager
        from app.ui_layer.settings.general_settings import get_agent_profile_picture_info

        state = self._controller.state
        metrics = self._metrics_collector.get_metrics()

        from app.config import get_app_version

        picture_info = get_agent_profile_picture_info()

        return {
            "version": get_app_version(),
            "agentState": state.agent_state.value,
            "guiMode": state.gui_mode,
            "needsHardOnboarding": onboarding_manager.needs_hard_onboarding,
            "agentName": onboarding_manager.state.agent_name or "Agent",
            "agentProfilePictureUrl": picture_info["url"],
            "agentProfilePictureHasCustom": picture_info["has_custom"],
            "currentTask": {
                "id": state.current_task_id,
                "name": state.current_task_name,
            } if state.current_task_id else None,
            "messages": [
                {
                    "sender": m.sender,
                    "content": m.content,
                    "style": m.style,
                    "timestamp": m.timestamp,
                    "messageId": m.message_id,
                    **({"attachments": [
                        {
                            "name": att.name,
                            "path": att.path,
                            "type": att.type,
                            "size": att.size,
                            "url": att.url,
                        }
                        for att in m.attachments
                    ]} if m.attachments else {}),
                    **({"taskSessionId": m.task_session_id} if m.task_session_id else {}),
                    **({"options": [
                        {"label": o.label, "value": o.value, "style": o.style}
                        for o in m.options
                    ]} if m.options else {}),
                    **({"optionSelected": m.option_selected} if m.option_selected else {}),
                }
                for m in self._chat.get_messages()
            ],
            "actions": [
                {
                    "id": a.id,
                    "name": a.name,
                    "status": a.status,
                    "itemType": a.item_type,
                    "parentId": a.parent_id,
                    "createdAt": int(a.created_at * 1000),
                    "duration": a.duration,
                    "input": a.input_data,
                    "output": a.output_data,
                    "error": a.error_message,
                }
                for a in self._action_panel.get_items()
            ],
            "status": self._status_bar.get_status(),
            "dashboardMetrics": metrics.to_dict(),
        }

    async def _spa_handler(self, request: "web.Request") -> "web.Response":
        """Serve index.html for SPA routing."""
        from aiohttp import web

        # Skip API and WebSocket routes
        path = request.path
        if path.startswith("/api/") or path.startswith("/ws"):
            raise web.HTTPNotFound()

        # Serve the built index.html
        frontend_dist = Path(__file__).parent.parent / "browser" / "frontend" / "dist"
        index_path = frontend_dist / "index.html"

        if index_path.exists():
            return web.FileResponse(index_path)
        else:
            # Fallback to inline HTML
            return web.Response(
                text=self._get_index_html(),
                content_type="text/html"
            )

    async def _index_handler(self, request: "web.Request") -> "web.Response":
        """Serve the main HTML page (fallback when no build exists)."""
        from aiohttp import web

        html = self._get_index_html()
        return web.Response(text=html, content_type="text/html")

    async def _state_handler(self, request: "web.Request") -> "web.Response":
        """API endpoint for current state."""
        from aiohttp import web

        return web.json_response(self._get_initial_state())

    async def _theme_css_handler(self, request: "web.Request") -> "web.Response":
        """Serve theme CSS variables."""
        from aiohttp import web

        css = self._theme_adapter.get_theme_css()
        return web.Response(text=css, content_type="text/css")

    async def _agent_profile_picture_handler(self, request: "web.Request") -> "web.Response":
        """Serve the current agent profile picture (user upload or bundled default)."""
        from aiohttp import web

        from app.ui_layer.settings.general_settings import (
            AGENT_PROFILE_DIR,
            AGENT_PROFILE_DEFAULT_FILENAME,
            EXT_TO_MIME,
            _user_profile_picture_path,
        )
        from app.onboarding import onboarding_manager

        ext = onboarding_manager.state.agent_profile_picture
        target: Optional[Path] = None
        mime_type = "image/png"

        if ext:
            candidate = _user_profile_picture_path(ext)
            if candidate.exists():
                target = candidate
                mime_type = EXT_TO_MIME.get(ext.lower(), "application/octet-stream")

        if target is None:
            default_path = AGENT_PROFILE_DIR / AGENT_PROFILE_DEFAULT_FILENAME
            if default_path.exists():
                target = default_path
                mime_type = "image/png"

        if target is None:
            raise web.HTTPNotFound(reason="Avatar not available")

        try:
            content = target.read_bytes()
            return web.Response(
                body=content,
                content_type=mime_type,
                headers={
                    "Cache-Control": "no-cache, max-age=0",
                },
            )
        except Exception as e:
            raise web.HTTPInternalServerError(reason=str(e))

    async def _workspace_file_handler(self, request: "web.Request") -> "web.Response":
        """Serve files from the workspace directory."""
        from aiohttp import web
        import mimetypes

        try:
            file_path = request.match_info.get("path", "")

            if not file_path:
                raise web.HTTPNotFound()

            # Validate and get absolute path
            target = self._validate_path(file_path)

            if not target.exists():
                raise web.HTTPNotFound()

            if target.is_dir():
                raise web.HTTPBadRequest(reason="Cannot serve directory")

            # Determine content type
            mime_type, _ = mimetypes.guess_type(target.name)
            if mime_type is None:
                mime_type = "application/octet-stream"

            # Read and serve file
            content = target.read_bytes()

            return web.Response(
                body=content,
                content_type=mime_type,
                headers={
                    "Content-Disposition": f'inline; filename="{target.name}"',
                    "Cache-Control": "no-cache",
                }
            )
        except ValueError as e:
            raise web.HTTPForbidden(reason=str(e))
        except FileNotFoundError:
            raise web.HTTPNotFound()
        except Exception as e:
            raise web.HTTPInternalServerError(reason=str(e))

    def _get_index_html(self) -> str:
        """Get the index HTML for the browser interface."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CraftBot</title>
    <link rel="stylesheet" href="/api/theme.css">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: var(--color-black);
            color: var(--color-white);
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header {
            padding: 1rem;
            border-bottom: 1px solid var(--color-dark-gray);
        }
        .header h1 {
            color: var(--color-primary);
            font-size: 1.5rem;
        }
        .main {
            flex: 1;
            display: flex;
            overflow: hidden;
        }
        .chat-panel {
            flex: 2;
            display: flex;
            flex-direction: column;
            border-right: 1px solid var(--color-dark-gray);
        }
        .chat-messages {
            flex: 1;
            overflow-y: auto;
            padding: 1rem;
        }
        .message {
            margin-bottom: 0.5rem;
            padding: 0.5rem;
            border-radius: 4px;
        }
        .message.user { background: rgba(255,255,255,0.1); }
        .message.agent { background: rgba(255,79,24,0.1); }
        .message.system { background: rgba(160,160,160,0.1); }
        .message.error { background: rgba(255,51,51,0.1); }
        .message-label {
            font-weight: bold;
            margin-right: 0.5rem;
        }
        .message-label.user { color: var(--color-white); }
        .message-label.agent { color: var(--color-primary); }
        .message-label.system { color: var(--color-gray); }
        .message-label.error { color: var(--color-red); }
        .input-area {
            padding: 1rem;
            border-top: 1px solid var(--color-dark-gray);
        }
        .input-area input {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid var(--color-dark-gray);
            border-radius: 4px;
            background: var(--color-black);
            color: var(--color-white);
            font-size: 1rem;
        }
        .input-area input:focus {
            outline: none;
            border-color: var(--color-primary);
        }
        .action-panel {
            flex: 1;
            padding: 1rem;
            overflow-y: auto;
        }
        .action-panel h2 {
            color: var(--color-primary);
            font-size: 1rem;
            margin-bottom: 1rem;
        }
        .action-item {
            padding: 0.5rem;
            margin-bottom: 0.25rem;
            border-radius: 4px;
            background: rgba(255,255,255,0.05);
        }
        .action-item.task { font-weight: bold; }
        .action-item .icon {
            margin-right: 0.5rem;
        }
        .action-item.running .icon { color: var(--color-primary); }
        .action-item.completed .icon { color: var(--color-green); }
        .action-item.error .icon { color: var(--color-red); }
        .status-bar {
            padding: 0.5rem 1rem;
            background: rgba(255,255,255,0.05);
            border-top: 1px solid var(--color-dark-gray);
            font-size: 0.875rem;
            color: var(--color-gray);
        }
        .connecting {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            text-align: center;
        }
        .connecting h2 { color: var(--color-primary); }
    </style>
</head>
<body>
    <div id="app">
        <div class="connecting">
            <h2>CraftBot</h2>
            <p>Connecting...</p>
        </div>
    </div>
    <script>
        const app = document.getElementById('app');
        let ws;
        let state = { messages: [], actions: [], status: 'Connecting...' };

        function connect() {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${location.host}/ws`);

            ws.onopen = () => {
                console.log('Connected to CraftBot');
            };

            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                handleMessage(msg);
            };

            ws.onclose = () => {
                console.log('Disconnected, reconnecting...');
                setTimeout(connect, 2000);
            };

            ws.onerror = (err) => {
                console.error('WebSocket error:', err);
            };
        }

        function handleMessage(msg) {
            switch (msg.type) {
                case 'init':
                    state = msg.data;
                    render();
                    break;
                case 'chat_message':
                    state.messages.push(msg.data);
                    renderMessages();
                    break;
                case 'chat_clear':
                    state.messages = [];
                    renderMessages();
                    break;
                case 'action_add':
                    state.actions.push(msg.data);
                    renderActions();
                    break;
                case 'action_update':
                    const action = state.actions.find(a => a.id === msg.data.id);
                    if (action) action.status = msg.data.status;
                    renderActions();
                    break;
                case 'action_clear':
                    state.actions = [];
                    renderActions();
                    break;
                case 'status_update':
                    state.status = msg.data.message;
                    renderStatus();
                    break;
            }
        }

        function render() {
            app.innerHTML = `
                <div class="header">
                    <h1>CraftBot</h1>
                </div>
                <div class="main">
                    <div class="chat-panel">
                        <div class="chat-messages" id="messages"></div>
                        <div class="input-area">
                            <input type="text" id="input" placeholder="Type a message..." />
                        </div>
                    </div>
                    <div class="action-panel">
                        <h2>Actions</h2>
                        <div id="actions"></div>
                    </div>
                </div>
                <div class="status-bar" id="status"></div>
            `;

            document.getElementById('input').addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && e.target.value.trim()) {
                    ws.send(JSON.stringify({ type: 'message', content: e.target.value }));
                    e.target.value = '';
                }
            });

            renderMessages();
            renderActions();
            renderStatus();
        }

        function renderMessages() {
            const container = document.getElementById('messages');
            if (!container) return;

            container.innerHTML = state.messages.map(m => `
                <div class="message ${m.style}">
                    <span class="message-label ${m.style}">${m.sender}:</span>
                    ${m.content}
                </div>
            `).join('');

            container.scrollTop = container.scrollHeight;
        }

        function renderActions() {
            const container = document.getElementById('actions');
            if (!container) return;

            const icons = { running: '*', completed: '+', error: 'x' };
            container.innerHTML = state.actions.map(a => `
                <div class="action-item ${a.itemType} ${a.status}">
                    <span class="icon">[${icons[a.status] || 'o'}]</span>
                    ${a.name}
                </div>
            `).join('');
        }

        function renderStatus() {
            const container = document.getElementById('status');
            if (container) container.textContent = state.status;
        }

        connect();
    </script>
</body>
</html>"""
