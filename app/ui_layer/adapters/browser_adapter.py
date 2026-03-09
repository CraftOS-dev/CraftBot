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
)
from app.ui_layer.themes.base import ThemeAdapter, StyleType
from app.ui_layer.themes.theme import BaseTheme
from app.ui_layer.components.protocols import (
    ChatComponentProtocol,
    ActionPanelProtocol,
    StatusBarProtocol,
    FootageComponentProtocol,
)
from app.ui_layer.components.types import ChatMessage, ActionItem
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
        await self._adapter._broadcast({
            "type": "chat_message",
            "data": {
                "sender": message.sender,
                "content": message.content,
                "style": message.style,
                "timestamp": message.timestamp,
                "messageId": message.message_id,
            },
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

        ws = web.WebSocketResponse()
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
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            self._ws_clients.discard(ws)

        return ws

    async def _handle_ws_message(self, data: Dict[str, Any]) -> None:
        """Handle incoming WebSocket message."""
        msg_type = data.get("type")

        if msg_type == "message":
            # User sent a message
            content = data.get("content", "")
            if content:
                await self.submit_message(content)

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
