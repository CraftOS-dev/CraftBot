"""Browser interface adapter using WebSocket."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from app.ui_layer.adapters.base import InterfaceAdapter
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
        """Add item and broadcast."""
        self._items.append(item)
        await self._adapter._broadcast({
            "type": "action_add",
            "data": {
                "id": item.id,
                "name": item.name,
                "status": item.status,
                "itemType": item.item_type,
                "parentId": item.parent_id,
            },
        })

    async def update_item(self, item_id: str, status: str) -> None:
        """Update item status and broadcast."""
        for item in self._items:
            if item.id == item_id:
                item.status = status
                break

        await self._adapter._broadcast({
            "type": "action_update",
            "data": {
                "id": item_id,
                "status": status,
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
        self._port = port
        self._theme_adapter = BrowserThemeAdapter(BaseTheme())
        self._chat = BrowserChatComponent(self)
        self._action_panel = BrowserActionPanelComponent(self)
        self._status_bar = BrowserStatusBarComponent(self)
        self._footage = BrowserFootageComponent(self)
        self._app: Optional["web.Application"] = None
        self._ws_clients: Set = set()

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
        """Start the browser interface."""
        from aiohttp import web

        self._app = web.Application()
        self._app.router.add_get("/ws", self._websocket_handler)
        self._app.router.add_get("/", self._index_handler)
        self._app.router.add_get("/api/state", self._state_handler)
        self._app.router.add_get("/api/theme.css", self._theme_css_handler)

        # Serve static files if they exist
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

        # Keep running
        while self._running and self._controller.agent.is_running:
            await asyncio.sleep(1)

    async def _on_stop(self) -> None:
        """Stop the browser interface."""
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

    def _get_initial_state(self) -> Dict[str, Any]:
        """Get initial state for new connections."""
        state = self._controller.state

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
                }
                for a in self._action_panel.get_items()
            ],
            "status": self._status_bar.get_status(),
        }

    async def _index_handler(self, request: "web.Request") -> "web.Response":
        """Serve the main HTML page."""
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
