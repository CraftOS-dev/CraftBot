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
    get_proactive_tasks,
    add_proactive_task,
    update_proactive_task,
    remove_proactive_task,
    reset_proactive_tasks,
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

    async def append_message(self, message: ChatMessage) -> None:
        """Append message and broadcast to clients."""
        self._messages.append(message)

        # Build message data with optional attachments
        message_data: Dict[str, Any] = {
            "sender": message.sender,
            "content": message.content,
            "style": message.style,
            "timestamp": message.timestamp,
            "messageId": message.message_id,
        }

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

        await self._adapter._broadcast({
            "type": "chat_message",
            "data": message_data,
        })

    async def clear(self) -> None:
        """Clear messages and notify clients."""
        self._messages.clear()
        await self._adapter._broadcast({
            "type": "chat_clear",
        })

    def scroll_to_bottom(self) -> None:
        """No-op - handled by frontend."""
        pass

    def get_messages(self) -> List[ChatMessage]:
        """Get all messages."""
        return self._messages.copy()


class BrowserActionPanelComponent(ActionPanelProtocol):
    """Browser action panel component."""

    def __init__(self, adapter: "BrowserAdapter") -> None:
        self._adapter = adapter
        self._items: List[ActionItem] = []

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
        await self._adapter._broadcast({
            "type": "action_remove",
            "data": {"id": item_id},
        })

    async def clear(self) -> None:
        """Clear all items and broadcast."""
        self._items.clear()
        await self._adapter._broadcast({
            "type": "action_clear",
        })

    def select_task(self, task_id: Optional[str]) -> None:
        """Select task - handled by frontend."""
        pass

    def get_items(self) -> List[ActionItem]:
        """Get all items."""
        return self._items.copy()


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
        port: int = 8080,
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
        self._runner: Optional["web.AppRunner"] = None

        # Dashboard metrics collector
        self._metrics_collector = MetricsCollector(controller.agent)
        self._metrics_task: Optional[asyncio.Task] = None

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

        self._app = web.Application()

        # API and WebSocket routes (must be registered first)
        self._app.router.add_get("/ws", self._websocket_handler)
        self._app.router.add_get("/api/state", self._state_handler)
        self._app.router.add_get("/api/theme.css", self._theme_css_handler)
        self._app.router.add_get("/api/workspace/{path:.*}", self._workspace_file_handler)

        # Serve Vite-built frontend (production)
        frontend_dist = Path(__file__).parent.parent / "browser" / "frontend" / "dist"
        if frontend_dist.exists():
            # Serve static assets from /assets/
            assets_path = frontend_dist / "assets"
            if assets_path.exists():
                self._app.router.add_static("/assets/", assets_path)

            # Serve favicon
            favicon_path = frontend_dist / "favicon.svg"
            if favicon_path.exists():
                self._app.router.add_get(
                    "/favicon.svg",
                    lambda _: web.FileResponse(favicon_path)
                )

            # Serve index.html for all non-API routes (SPA routing)
            self._app.router.add_get("/", self._spa_handler)
            self._app.router.add_get("/{path:.*}", self._spa_handler)
        else:
            # Fallback to inline HTML for development without build
            self._app.router.add_get("/", self._index_handler)
            self._app.router.add_get("/{path:.*}", self._index_handler)

        # Serve static files if they exist (legacy)
        static_path = Path(__file__).parent.parent / "browser" / "static"
        if static_path.exists():
            self._app.router.add_static("/static/", static_path)

        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, self._host, self._port)
        await site.start()

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
        # Cancel metrics broadcasting task
        if self._metrics_task:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass

        # Close all WebSocket connections
        for ws in self._ws_clients:
            await ws.close()
        self._ws_clients.clear()

    async def _websocket_handler(self, request: "web.Request") -> "web.WebSocketResponse":
        """Handle WebSocket connections."""
        from aiohttp import web, WSMsgType

        # Increase max message size to 100MB to allow multiple large attachments
        ws = web.WebSocketResponse(max_msg_size=100 * 1024 * 1024)
        await ws.prepare(request)
        self._ws_clients.add(ws)

        # Send initial state
        await ws.send_json({
            "type": "init",
            "data": self._get_initial_state(),
        })

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_ws_message(data)
                    except json.JSONDecodeError:
                        pass
                    except Exception as e:
                        # Log error but don't break the connection
                        import traceback
                        print(f"[BROWSER ADAPTER] Error handling WS message: {e}")
                        traceback.print_exc()
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            self._ws_clients.discard(ws)

        return ws

    async def _handle_ws_message(self, data: Dict[str, Any]) -> None:
        """Handle incoming WebSocket message."""
        msg_type = data.get("type")

        if msg_type == "message":
            # User sent a message (may include attachments)
            content = data.get("content", "")
            attachments = data.get("attachments", [])

            if attachments:
                # Message with attachments - use custom handler
                await self._handle_chat_message_with_attachments(content, attachments)
            elif content:
                # Regular message without attachments - use normal flow
                await self.submit_message(content)

        elif msg_type == "chat_attachment_upload":
            # Upload attachment for chat message
            await self._handle_chat_attachment_upload(data)

        elif msg_type == "command":
            # User sent a command
            command = data.get("command", "")
            if command:
                await self.submit_message(command)

        # File operations
        elif msg_type == "file_list":
            directory = data.get("directory", "")
            await self._handle_file_list(directory)

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

        elif msg_type == "reset":
            await self._handle_reset()

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
            await self._handle_model_connection_test(provider, api_key, base_url)

        elif msg_type == "model_validate_save":
            await self._handle_model_validate_save(data)

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

        elif msg_type == "integration_disconnect":
            integration_id = data.get("id", "")
            account_id = data.get("account_id")
            await self._handle_integration_disconnect(integration_id, account_id)

        # WhatsApp QR code flow handlers
        elif msg_type == "whatsapp_start_qr":
            await self._handle_whatsapp_start_qr()

        elif msg_type == "whatsapp_check_status":
            session_id = data.get("session_id", "")
            await self._handle_whatsapp_check_status(session_id)

        elif msg_type == "whatsapp_cancel":
            session_id = data.get("session_id", "")
            await self._handle_whatsapp_cancel(session_id)

        elif msg_type == "dashboard_metrics_filter":
            period = data.get("period", "total")
            await self._handle_dashboard_metrics_filter(period)

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
                    # Toggle schedules at runtime
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

        result = get_proactive_tasks(
            proactive_manager,
            frequency=frequency,
            enabled_only=False
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

        result = add_proactive_task(
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

        result = update_proactive_task(proactive_manager, task_id, update_dict)

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

        result = remove_proactive_task(proactive_manager, task_id)

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
        result = reset_proactive_tasks()

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
                task = await agent.create_process_memory_task()
                await self._broadcast({
                    "type": "memory_process_trigger",
                    "data": {
                        "success": True,
                        "taskId": task.id if task else None,
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
        """Update model settings."""
        try:
            result = update_model_settings(
                llm_provider=data.get("llmProvider"),
                vlm_provider=data.get("vlmProvider"),
                llm_model=data.get("llmModel"),
                vlm_model=data.get("vlmModel"),
                api_key=data.get("apiKey"),
                provider_for_key=data.get("providerForKey"),
                base_url=data.get("baseUrl"),
                provider_for_url=data.get("providerForUrl"),
            )
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
    ) -> None:
        """Test connection to a model provider."""
        try:
            result = test_connection(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
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
            # Refresh the list
            if success:
                await self._handle_skill_list()
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
            # Refresh the list
            if success:
                await self._handle_skill_list()
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
            # Refresh the list
            if success:
                await self._handle_skill_list()
        except Exception as e:
            await self._broadcast({
                "type": "skill_reload",
                "data": {
                    "success": False,
                    "error": str(e),
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
            # Refresh the list on success
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
        """Start OAuth flow for an integration."""
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
            # Refresh the list on success
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
            # If connected, refresh the integrations list
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

        for ws in self._ws_clients:
            try:
                await ws.send_str(json_msg)
            except Exception:
                disconnected.add(ws)

        # Clean up disconnected clients
        self._ws_clients -= disconnected

    async def _broadcast_metrics_loop(self) -> None:
        """Periodically broadcast dashboard metrics to connected clients."""
        while self._running:
            try:
                if self._ws_clients:
                    metrics = self._metrics_collector.get_metrics()
                    await self._broadcast({
                        "type": "dashboard_metrics",
                        "data": metrics.to_dict(),
                    })
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

    async def _handle_file_list(self, directory: str) -> None:
        """List files in a directory within the workspace."""
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

            files = []
            for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                files.append(self._get_file_info(item))

            await self._broadcast({
                "type": "file_list",
                "data": {
                    "directory": directory,
                    "files": files,
                    "success": True,
                },
            })
        except Exception as e:
            await self._broadcast({
                "type": "file_list",
                "data": {
                    "directory": directory,
                    "files": [],
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

    async def _handle_chat_message_with_attachments(self, content: str, attachments: List[Dict[str, Any]]) -> None:
        """Handle user chat message with attachments."""
        import uuid
        from app.ui_layer.state.ui_state import AgentStateType

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
            )
            await self._chat.append_message(user_message)

            # Combine content with attachment info for agent context
            # (This is what the agent sees in the event stream - includes file paths)
            agent_context = content + attachment_note

            if not agent_context.strip():
                return

            # Update state and route to agent directly
            # (Skip submit_message to avoid duplicate chat message)
            self._controller._state_store.dispatch("SET_AGENT_STATE", AgentStateType.WORKING.value)

            # Route directly to agent with full context
            payload = {
                "text": agent_context,
                "sender": {"id": self._adapter_id or "user", "type": "user"},
                "gui_mode": self._controller._state_store.state.gui_mode,
            }
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
        sender: str = "agent",
        style: str = "agent",
    ) -> Dict[str, Any]:
        """
        Send a chat message with a single attachment from the agent.

        Deprecated: Use send_message_with_attachments for new code.

        Args:
            message: The message content
            file_path: Absolute path or path relative to workspace
            sender: Message sender (default: "agent")
            style: Message style (default: "agent")

        Returns:
            Dict with 'success', 'files_sent', and optionally 'errors'
        """
        return await self.send_message_with_attachments(message, [file_path], sender, style)

    async def send_message_with_attachments(
        self,
        message: str,
        file_paths: list,
        sender: str = "agent",
        style: str = "agent",
    ) -> Dict[str, Any]:
        """
        Send a chat message with one or more attachments from the agent.

        This method is called by the agent to send files to the user.
        Supports both absolute paths and workspace-relative paths.

        Args:
            message: The message content
            file_paths: List of absolute paths or paths relative to workspace
            sender: Message sender (default: "agent")
            style: Message style (default: "agent")

        Returns:
            Dict with 'success' (bool), 'files_sent' (int), and optionally 'errors' (list of str)
        """
        try:
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
        state = self._controller.state
        metrics = self._metrics_collector.get_metrics()

        return {
            "agentState": state.agent_state.value,
            "guiMode": state.gui_mode,
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
