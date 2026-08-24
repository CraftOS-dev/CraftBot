"""Browser interface adapter using WebSocket."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from aiohttp.client_exceptions import ClientConnectionResetError

from agent_core.core.impl.memory.tuning import (
    PROCESSING_THRESHOLD_DEFAULT,
    SCHEDULE_HOUR_DEFAULT,
    SCHEDULE_MINUTE_DEFAULT,
)
from agent_core.utils.logger import logger
from app.config import AGENT_WORKSPACE_ROOT, APP_DATA_PATH
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
    reset_entity_registry,
    clear_unprocessed_events,
    get_memory_stats,
    get_memory_processing_threshold,
    get_memory_processing_threshold_max,
    set_memory_processing_threshold,
    get_unprocessed_event_count,
    memory_schedule_expression,
    set_memory_indexed_files,
    add_memory_indexed_file,
    remove_memory_indexed_file,
    list_indexable_candidates,
    # Model settings
    get_available_providers,
    get_model_settings,
    update_model_settings,
    test_connection,
    validate_can_save,
    get_ollama_models,
    # Subscription OAuth (ChatGPT Plus/Pro, SuperGrok)
    complete_subscription,
    connect_subscription_async,
    disconnect_subscription,
    get_subscription_status,
    prepare_subscription_async,
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
from app.ui_layer.components.types import (
    ChatMessage,
    ActionItem,
    Attachment,
    QUESTION_DISMISSED_VALUE,
)
from app.ui_layer.events import UIEvent, UIEventType
from app.ui_layer.onboarding import OnboardingFlowController
from app.ui_layer.metrics import MetricsCollector
from app.living_ui import (
    LivingUIManager,
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
            from app.usage.chat_storage import get_chat_storage

            self._storage = get_chat_storage()

            # Load recent messages from storage (initial page)
            stored_messages = self._storage.get_recent_messages(limit=50)
            for stored in stored_messages:
                self._messages.append(self._stored_to_chat_message(stored))
        except Exception:
            # Storage may not be available, continue without persistence
            pass

    @staticmethod
    def _stored_to_chat_message(stored) -> ChatMessage:
        """Rehydrate a StoredChatMessage row into the live ChatMessage shape."""
        from app.ui_layer.components.types import ChatMessageOption

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
            options = [
                ChatMessageOption(
                    label=o.get("label", ""),
                    value=o.get("value", ""),
                    style=o.get("style", "default"),
                )
                for o in stored.options
            ]
        return ChatMessage(
            sender=stored.sender,
            content=stored.content,
            style=stored.style,
            timestamp=stored.timestamp,
            message_id=stored.message_id,
            attachments=attachments,
            session_id=stored.session_id,
            options=options,
            option_selected=stored.option_selected,
            continue_work=stored.continue_work,
            is_question=stored.is_question,
            allow_free_text=stored.allow_free_text,
            requires_choice=not stored.is_question,
            details=stored.details,
        )

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
                    message_id=message.message_id
                    or f"{message.sender}:{message.timestamp}",
                    sender=message.sender,
                    content=message.content,
                    style=message.style,
                    timestamp=message.timestamp,
                    attachments=attachments_data,
                    session_id=message.session_id,
                    options=options_data,
                    continue_work=message.continue_work,
                    is_question=message.is_question,
                    allow_free_text=message.allow_free_text,
                    details=message.details,
                )
                self._storage.insert_message(stored)
            except Exception:
                pass

        # ChatMessage.to_dict() is the WS wire format (always emits sessionId).
        await self._adapter._broadcast(
            {
                "type": "chat_message",
                "data": message.to_dict(),
            }
        )

    async def clear(self, session_id: Optional[str] = None) -> None:
        """Clear messages (one session's, or all) and notify clients."""
        if session_id:
            self._messages = [m for m in self._messages if m.session_id != session_id]
        else:
            self._messages.clear()

        # Clear from storage
        if self._storage:
            try:
                self._storage.clear_messages(session_id)
            except Exception:
                pass

        await self._adapter._broadcast(
            {
                "type": "chat_clear",
                "data": {"sessionId": session_id},
            }
        )

    def drop_session_messages(self, session_id: str) -> None:
        """Drop a session's messages from memory only (storage already cleared
        by the caller — e.g. the /clear command or session_clear handler)."""
        self._messages = [m for m in self._messages if m.session_id != session_id]

    def scroll_to_bottom(self) -> None:
        """No-op - handled by frontend."""
        pass

    def get_messages(self) -> List[ChatMessage]:
        """Get all loaded messages."""
        return self._messages.copy()

    def get_messages_before(
        self,
        before_timestamp: float,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[ChatMessage]:
        """Get older messages from storage before a given timestamp."""
        if not self._storage:
            return []
        try:
            stored = self._storage.get_messages_before(
                before_timestamp, session_id=session_id, limit=limit
            )
            return [self._stored_to_chat_message(s) for s in stored]
        except Exception:
            return []

    def get_total_count(self, session_id: Optional[str] = None) -> int:
        """Get total message count from storage."""
        if not self._storage:
            return len(self._messages)
        try:
            return self._storage.get_message_count(session_id)
        except Exception:
            return len(self._messages)


class BrowserActionPanelComponent(ActionPanelProtocol):
    """Browser activity feed component.

    Holds the per-session activity items (actions and reasoning) rendered
    inline in each session's chat. Write-through persisted to ActionStorage
    (like chat messages), so the feed survives restarts and crashes
    independently of the session's event stream, which summarizes and
    prunes itself for LLM context.
    """

    # How many items per session to load back into memory at boot. Bounds
    # the init payload; the full history stays in storage.
    RESTORE_PER_SESSION_LIMIT = 100

    def __init__(self, adapter: "BrowserAdapter") -> None:
        self._adapter = adapter
        self._items: List[ActionItem] = []
        self._storage = None
        self._init_storage()

    def _init_storage(self) -> None:
        """Initialize storage and load each session's recent items."""
        try:
            from app.usage.action_storage import get_action_storage

            self._storage = get_action_storage()

            # Anything still 'running' in storage died with the previous
            # process — close it out before loading.
            self._storage.mark_running_interrupted()

            for stored in self._storage.get_recent_items_by_session(
                self.RESTORE_PER_SESSION_LIMIT
            ):
                self._items.append(
                    ActionItem(
                        id=stored.id,
                        name=stored.name,
                        status=stored.status,
                        item_type=stored.item_type,
                        session_id=stored.session_id,
                        created_at=stored.created_at,
                        completed_at=stored.completed_at,
                        input_data=stored.input_data,
                        output_data=stored.output_data,
                        error_message=stored.error_message,
                    )
                )
        except Exception:
            # Storage may not be available, continue without persistence
            logger.exception("[ActionStorage] Failed to initialize activity storage")

    def _persist_item(self, item: ActionItem) -> None:
        """Write-through an item's full current state to storage."""
        if not self._storage:
            return
        try:
            from app.usage.action_storage import StoredActionItem

            self._storage.save_item(
                StoredActionItem(
                    id=item.id,
                    name=item.name,
                    status=item.status,
                    item_type=item.item_type,
                    session_id=item.session_id,
                    created_at=item.created_at,
                    completed_at=item.completed_at,
                    input_data=item.input_data,
                    output_data=item.output_data,
                    error_message=item.error_message,
                )
            )
        except Exception as e:
            logger.warning(f"[ActionStorage] Failed to persist item {item.id}: {e}")

    @staticmethod
    def _item_payload(item: ActionItem) -> Dict[str, Any]:
        """Wire payload for an activity item (always carries sessionId)."""
        return {
            "id": item.id,
            "name": item.name,
            "status": item.status,
            "itemType": item.item_type,
            "sessionId": item.session_id,
            "createdAt": int(item.created_at * 1000),
            "completedAt": (
                int(item.completed_at * 1000) if item.completed_at else None
            ),
            "duration": item.duration,
            "input": item.input_data,
            "output": item.output_data,
            "error": item.error_message,
        }

    async def add_item(self, item: ActionItem) -> None:
        """Add item, persist it, and broadcast. Prevents duplicates by ID."""
        # Check if item with same ID already exists
        for existing in self._items:
            if existing.id == item.id:
                # Item already exists, just update its status if needed
                if existing.status != item.status:
                    await self.update_item(existing.id, item.status)
                return

        self._items.append(item)
        self._persist_item(item)

        await self._adapter._broadcast(
            {
                "type": "action_add",
                "data": self._item_payload(item),
            }
        )

    async def _broadcast_update(self, item: ActionItem) -> None:
        """Broadcast an action_update for an item's current state."""
        await self._adapter._broadcast(
            {
                "type": "action_update",
                "data": {
                    "id": item.id,
                    "status": item.status,
                    "sessionId": item.session_id,
                    "completedAt": (
                        int(item.completed_at * 1000) if item.completed_at else None
                    ),
                    "duration": item.duration,
                    "output": item.output_data,
                    "error": item.error_message,
                },
            }
        )

    async def update_item(self, item_id: str, status: str) -> None:
        """Update item status by ID, persist, and broadcast."""
        for item in self._items:
            if item.id == item_id:
                item.status = status
                # Record completion time for terminal statuses
                if status in ("completed", "error") and item.completed_at is None:
                    item.completed_at = time.time()
                self._persist_item(item)
                await self._broadcast_update(item)
                return

    async def update_item_by_name(
        self,
        action_name: str,
        session_id: str,
        status: str,
        action_id: str = "",
        output: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update item status by matching name and session."""
        matched_item = None

        # First try exact ID match if provided
        if action_id:
            for item in self._items:
                if item.id == action_id:
                    matched_item = item
                    break

        # Try matching by name + session + running status
        if not matched_item and session_id:
            for item in reversed(self._items):
                if (
                    item.item_type == "action"
                    and item.name == action_name
                    and item.session_id == session_id
                    and item.status == "running"
                ):
                    matched_item = item
                    break

        # Fallback: match by just name + running status
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
            # Record completion time for terminal statuses
            if status in ("completed", "error") and matched_item.completed_at is None:
                matched_item.completed_at = time.time()
            # Set output and error data
            if output is not None:
                matched_item.output_data = output
            if error is not None:
                matched_item.error_message = error

            self._persist_item(matched_item)
            await self._broadcast_update(matched_item)

    async def update_item_data(
        self,
        item_id: str,
        output: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update an item's output/error data."""
        for item in self._items:
            if item.id == item_id:
                if output is not None:
                    item.output_data = output
                if error is not None:
                    item.error_message = error
                self._persist_item(item)
                await self._broadcast_update(item)
                return

    async def remove_item(self, item_id: str) -> None:
        """Remove item and broadcast."""
        removed = next((i for i in self._items if i.id == item_id), None)
        self._items = [i for i in self._items if i.id != item_id]
        if self._storage:
            try:
                self._storage.delete_item(item_id)
            except Exception:
                pass

        await self._adapter._broadcast(
            {
                "type": "action_remove",
                "data": {
                    "id": item_id,
                    "sessionId": removed.session_id if removed else None,
                },
            }
        )

    async def clear(self) -> None:
        """Clear all items (memory + storage) and broadcast."""
        self._items.clear()
        if self._storage:
            try:
                self._storage.clear_items()
            except Exception:
                pass

        await self._adapter._broadcast(
            {
                "type": "action_clear",
            }
        )

    def drop_session_items(self, session_id: str) -> None:
        """Drop a session's items from memory only (storage rows are cleared
        by the owner of the operation — session deletion purges them via the
        session-delete hook, conversation clears purge them alongside the
        chat rows)."""
        self._items = [i for i in self._items if i.session_id != session_id]

    def get_items(self) -> List[ActionItem]:
        """Get all loaded items."""
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
        await self._adapter._broadcast(
            {
                "type": "status_update",
                "data": {
                    "message": message,
                    "loading": self._loading,
                },
            }
        )

    async def set_loading(self, loading: bool) -> None:
        """Set loading state and broadcast."""
        self._loading = loading
        await self._adapter._broadcast(
            {
                "type": "status_update",
                "data": {
                    "message": self._status,
                    "loading": loading,
                },
            }
        )

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
        await self._adapter._broadcast(
            {
                "type": "footage_update",
                "data": {
                    "image": f"data:image/png;base64,{b64}",
                },
            }
        )

    async def clear(self) -> None:
        """Clear footage."""
        await self._adapter._broadcast(
            {
                "type": "footage_clear",
            }
        )

    def set_visible(self, visible: bool) -> None:
        """Set visibility."""
        self._visible = visible
        asyncio.create_task(
            self._adapter._broadcast(
                {
                    "type": "footage_visibility",
                    "data": {"visible": visible},
                }
            )
        )


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

        # Staged bundle bytes keyed by short-lived token (inspect → import flow)
        self._staged_bundles: Dict[str, bytes] = {}

        # Living UI manager
        self._living_ui_manager = LivingUIManager(workspace_root=AGENT_WORKSPACE_ROOT)
        # Wizard: reference-image VLM notes cached between interview and
        # finalize (keyed by wizardId) so images are described only once.
        self._wizard_image_notes: Dict[str, List[str]] = {}
        # Bind session manager and trigger service for project sessions
        agent = self._controller.agent
        self._living_ui_manager.bind_session_manager(
            agent.session_manager, agent.trigger_service
        )

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
            broadcast_data_changed=self.broadcast_living_ui_data_changed,
            broadcast_created=self.broadcast_living_ui_created,
            broadcast_build_event=self.broadcast_living_ui_build_event,
            broadcast_wizard_open=self.broadcast_living_ui_wizard_open,
        )

        # Subscribe the Living UI module to SessionManager todo updates so
        # that the agent's build breakdown streams to the browser automatically.
        agent.session_manager.add_post_update_todos_hook(make_todo_broadcast_hook())

        # READ-ONLY build observer: derive construction-dock build events from
        # the actions the agent already performs (write_file / stream_edit /
        # living_ui_scaffold / living_ui_notify_ready). These hooks are
        # single-callback and currently unset; the executor wraps them in
        # try/except and the observer swallows all exceptions, so this can
        # never affect a build. It reads inputs/outputs only, mutates nothing.
        try:
            from app.living_ui import construction_events

            on_start, on_end = construction_events.make_action_hooks()
            agent.action_manager._on_action_start = on_start
            agent.action_manager._on_action_end = on_end
        except Exception as e:
            logger.warning(f"[LIVING_UI] build-event observer not attached: {e}")

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
        session_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> None:
        """
        Submit a message from the user.

        Args:
            message: The user's input message
            session_id: The session the message was typed in (main if omitted)
            client_id: Optional client-generated UUID for reconciling optimistic UI
        """
        await self._controller.submit_message(
            message,
            self._adapter_id,
            session_id=session_id,
            client_id=client_id,
        )

    async def _handle_enhance_prompt(self, content: str, ws) -> None:
        """Enhance a user's prompt using the LLM for clarity and precision."""
        try:
            enhanced: str = await self._controller.handle_prompt_enhance(
                user_message=content
            )
            await ws.send_json({"type": "prompt_enhanced", "content": enhanced.strip()})
            return
        except Exception as e:
            logger.warning(f"[BROWSER ADAPTER] enhance_prompt failed: {e}")

    def _handle_reasoning(self, event: UIEvent) -> None:
        """Handle reasoning event — add it to the session's activity feed."""
        session_id = event.data.get("session_id") or "main"
        reasoning_id = event.data.get("reasoning_id", "")
        content = event.data.get("content", "")

        asyncio.create_task(
            self._action_panel.add_item(
                ActionItem(
                    id=reasoning_id,
                    name="Reasoning",
                    status="completed",  # Reasoning is always complete
                    item_type="reasoning",
                    session_id=session_id,
                    output_data=content,  # Store reasoning content in output
                )
            )
        )

    def _handle_run_state_change(self, event: UIEvent) -> None:
        """Broadcast a session's run state (typing indicator + stop button).

        ``state`` is "running" | "stopping" | "idle"; ``busy`` is the
        derived boolean kept alongside it for older consumers.
        """
        session_id = event.data.get("session_id") or "main"
        busy = bool(event.data.get("busy", False))
        state = event.data.get("state") or ("running" if busy else "idle")
        asyncio.create_task(
            self._broadcast(
                {
                    "type": "session_busy",
                    "data": {"sessionId": session_id, "busy": busy, "state": state},
                }
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
        self._app.router.add_get(
            "/api/workspace/{path:.*}", self._workspace_file_handler
        )
        self._app.router.add_get(
            "/api/agent-profile-picture", self._agent_profile_picture_handler
        )

        # Living UI export/import routes
        self._app.router.add_get(
            "/api/living-ui/{project_id}/export", self._living_ui_export_handler
        )
        self._app.router.add_post(
            "/api/living-ui/import", self._living_ui_import_handler
        )
        self._app.router.add_post("/api/living-ui/stage", self._living_ui_stage_handler)
        self._app.router.add_get(
            "/api/living-ui/icon/{project_id}", self._living_ui_icon_handler
        )

        # Workspace and chat HTTP upload routes
        self._app.router.add_post(
            "/api/workspace/upload", self._workspace_upload_handler
        )
        self._app.router.add_post(
            "/api/chat-attachments/upload", self._chat_attachment_upload_handler
        )

        # Agent profile bundle import/export routes
        self._app.router.add_get("/api/profile/export", self._profile_export_handler)
        self._app.router.add_post("/api/profile/inspect", self._profile_inspect_handler)
        self._app.router.add_post("/api/profile/import", self._profile_import_handler)

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
            print(
                f"\nCraftBot Browser Interface running at http://{self._host}:{self._port}"
            )
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
        if hasattr(self, "_integration_bridge"):
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

    async def _websocket_handler(
        self, request: "web.Request"
    ) -> "web.WebSocketResponse":
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
                peer = (
                    request.transport.get_extra_info("peername")
                    if request.transport
                    else None
                )
            except Exception:
                peer = None
            user_agent = request.headers.get("User-Agent", "")
            attempt_id = request.query.get("attempt", "")
            uptime_s = (
                (time.monotonic() - self._started_at) if self._started_at else -1.0
            )
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
        # is ready to receive the onboarding messages.
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
            await ws.send_json(
                {
                    "type": "init",
                    "data": initial_state,
                }
            )
            await ws.send_json(
                {
                    "type": "skill_meta",
                    "data": self._get_skill_meta(),
                }
            )
            # Push the Living UI list on connect instead of relying on the
            # client to request it. The frontend's request is sent from an
            # onOpen handler registered after React mounts; when the socket
            # opens before that (middleware connects during store bootstrap),
            # the request was never sent and the side panel stayed empty
            # until the next reconnect.
            await ws.send_json(
                {
                    "type": "living_ui_list",
                    "data": {
                        "success": True,
                        "projects": [
                            p.to_dict() for p in self._living_ui_manager.list_projects()
                        ],
                    },
                }
            )
        except (ConnectionResetError, ClientConnectionResetError, RuntimeError):
            # Gracefully handle connection closing
            self._ws_clients.discard(ws)
            return ws
        except Exception:
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
            print(
                f"[BROWSER ADAPTER] WebSocket connection reset: {type(e).__name__}: {e}"
            )
        except Exception as e:
            import traceback

            print(
                f"[BROWSER ADAPTER] WebSocket loop error: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            )
        finally:
            self._ws_clients.discard(ws)
            self._metrics_subscribers.discard(ws)

        return ws

    async def _handle_ws_message(self, data: Dict[str, Any], ws=None) -> None:
        """Handle incoming WebSocket message."""
        msg_type = data.get("type")

        if msg_type == "message":
            # User sent a message (may include attachments)
            content = data.get("content", "")
            attachments = data.get("attachments", [])
            session_id = data.get("sessionId") or "main"
            client_id = data.get("clientId")

            # Reply-to-bubble: append the quoted agent message so both the
            # stored user message and the agent's event stream record which
            # message was replied to. No routing — the session is explicit.
            reply_context = data.get("replyContext") or {}
            original = (
                (reply_context.get("originalMessage") or "").strip()
                if isinstance(reply_context, dict)
                else ""
            )
            if original and content:
                content = (
                    f"{content}\n\n[REPLYING TO PREVIOUS AGENT MESSAGE]:\n{original}"
                )

            # Draft chat: the sidebar's "New Chat" only opens an empty view —
            # the session is created lazily here, on the FIRST message.
            # session_created is broadcast (with the sender's clientId) before
            # the message so the draft view can navigate to the real session.
            if session_id == "new":
                session = self._controller.agent.create_chat_session()
                session_id = session.id
                await self._broadcast(
                    {
                        "type": "session_created",
                        "data": {
                            "session": self._session_info(session),
                            "clientId": client_id,
                        },
                    }
                )

            # Dispatch chat submission as a background task so the WS message loop
            # can immediately read the next frame. Otherwise rapid-fire sends are
            # serialised behind each message's per-session processing, which
            # makes optimistic bubbles un-gray one-by-one instead of all at once.
            if attachments:
                asyncio.create_task(
                    self._handle_chat_message_with_attachments(
                        content, attachments, session_id, client_id
                    )
                )
            elif content:
                asyncio.create_task(
                    self.submit_message(
                        content, session_id=session_id, client_id=client_id
                    )
                )

        elif msg_type == "session_stop":
            # User force-stops the session's in-flight run (the chat input's
            # stop button). Runs as a background task: stopping awaits full
            # settlement (process kills) and must not block the WS read loop.
            session_id = data.get("sessionId") or "main"
            asyncio.create_task(self._controller.stop_run(session_id))

        elif msg_type == "chat_attachment_upload":
            # Upload attachment for chat message
            await self._handle_chat_attachment_upload(data)

        elif msg_type == "command":
            # User sent a slash command. Mirror the "message" branch's lazy
            # draft-session creation, but only for commands that operate on or
            # produce the conversation they were typed in (skills, /clear —
            # they declare requires_session). A draft must materialize a real
            # session before those run: otherwise a skill turn leaks into the
            # main session and session-scoped output orphans in the never-
            # committed draft. Global informational commands (/help, /mcp, …)
            # run in place — their output stays in the draft as immediate
            # feedback without spawning an empty session in the sidebar.
            command = data.get("command", "")
            session_id = data.get("sessionId") or "main"
            client_id = data.get("clientId")
            if command:
                if session_id == "new":
                    name = command.strip().split()[0].lower() if command.strip() else ""
                    cmd = self._controller.command_registry.get(name) if name else None
                    if cmd is not None and cmd.requires_session:
                        session = self._controller.agent.create_chat_session()
                        session_id = session.id
                        await self._broadcast(
                            {
                                "type": "session_created",
                                "data": {
                                    "session": self._session_info(session),
                                    "clientId": client_id,
                                    # Only skills launch a turn; a state command
                                    # like /clear commits a session but starts no
                                    # run, so the draft handoff must not show a
                                    # phantom typing indicator on it.
                                    "startsRun": cmd.starts_run,
                                },
                            }
                        )
                await self.submit_message(command, session_id=session_id)

        elif msg_type == "enhance_prompt":
            content = data.get("content", "")
            if content and ws:
                await self._handle_enhance_prompt(content, ws)

        elif msg_type == "chat_history":
            session_id = data.get("sessionId") or "main"
            before_timestamp = data.get("beforeTimestamp")
            limit = data.get("limit", 50)
            await self._handle_chat_history(session_id, before_timestamp, limit, ws)

        # Session management (creation is lazy — see the "message" branch)
        elif msg_type == "session_delete":
            await self._handle_session_delete(data)

        elif msg_type == "session_rename":
            await self._handle_session_rename(data)

        elif msg_type == "session_clear":
            await self._handle_session_clear(data)

        elif msg_type == "session_list":
            await self._handle_session_list(ws)

        # File operations
        elif msg_type == "file_list":
            directory = data.get("directory", "")
            offset = data.get("offset", 0)
            limit = data.get("limit", 50)
            search = data.get("search", "")
            await self._handle_file_list(
                directory, offset=offset, limit=limit, search=search
            )

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

        elif msg_type == "option_click":
            value = data.get("value", "")
            session_id = data.get("sessionId", "")
            message_id = data.get("messageId", "")
            await self._handle_option_click(value, session_id, message_id)

        elif msg_type == "question_response":
            value = data.get("value", "")
            session_id = data.get("sessionId", "")
            message_id = data.get("messageId", "")
            dismissed = bool(data.get("dismissed", False))
            await self._handle_question_response(
                value, session_id, message_id, dismissed
            )

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
            await self._handle_reset(data)

        elif msg_type == "create_skill_from_session":
            await self._handle_create_skill_from_session(data)

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
            superseded = data.get("superseded")
            await self._handle_memory_item_update(
                item_id, category, content, superseded
            )

        elif msg_type == "memory_item_remove":
            item_id = data.get("itemId", "")
            await self._handle_memory_item_remove(item_id)

        elif msg_type == "memory_reset":
            await self._handle_memory_reset()


        elif msg_type == "memory_stats_get":
            await self._handle_memory_stats_get()

        elif msg_type == "memory_process_trigger":
            await self._handle_memory_process_trigger()

        elif msg_type == "memory_schedule_get":
            await self._handle_memory_schedule_get()

        elif msg_type == "memory_schedule_set":
            await self._handle_memory_schedule_set(data)

        elif msg_type == "memory_graph_get":
            await self._handle_memory_graph_get()

        elif msg_type == "memory_indexed_files_get":
            await self._handle_memory_indexed_files_get()

        elif msg_type == "memory_indexed_files_set":
            paths = data.get("paths", [])
            await self._handle_memory_indexed_files_set(paths)

        elif msg_type == "memory_index_file_add":
            path = data.get("path", "")
            await self._handle_memory_index_file_mutate("add", path)

        elif msg_type == "memory_index_file_remove":
            path = data.get("path", "")
            await self._handle_memory_index_file_mutate("remove", path)

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
            aws_credentials = data.get("awsCredentials")
            await self._handle_model_connection_test(
                provider, api_key, base_url, model, aws_credentials
            )

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

        # Subscription OAuth (ChatGPT Plus/Pro, SuperGrok)
        elif msg_type == "model_subscription_connect":
            await self._handle_model_subscription_connect(data.get("provider", ""))

        elif msg_type == "model_subscription_disconnect":
            await self._handle_model_subscription_disconnect(data.get("provider", ""))

        elif msg_type == "model_subscription_status":
            await self._handle_model_subscription_status(data.get("provider", ""))

        elif msg_type == "model_subscription_prepare":
            await self._handle_model_subscription_prepare(data.get("provider", ""))

        elif msg_type == "model_subscription_complete":
            await self._handle_model_subscription_complete(
                data.get("provider", ""),
                data.get("code", ""),
                data.get("attemptId"),
            )

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

        # Slash command list (for autocomplete)
        elif msg_type == "command_list":
            await self._handle_command_list()

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
            session_id = data.get("sessionId") or "main"
            await self._handle_skill_run(name, args_text, session_id)

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
            request_id = data.get("request_id")
            await self._handle_integration_disconnect(
                integration_id, account_id, request_id
            )

        # Multi-account integration handlers
        elif msg_type == "integration_accounts_add":
            integration_id = data.get("integration_id", "")
            request_id = data.get("request_id")
            await self._handle_integration_accounts_add(integration_id, request_id)

        elif msg_type == "integration_apply_account_changes":
            integration_id = data.get("integration_id", "")
            request_id = data.get("request_id")
            changes = data.get("changes") or {}
            await self._handle_integration_apply_account_changes(
                integration_id, request_id, changes
            )

        # Generic per-integration config (replaces the old bespoke jira/github settings handlers)
        elif msg_type == "integration_get_config":
            integration_id = data.get("id")
            await self._handle_integration_get_config(integration_id)

        elif msg_type == "integration_update_config":
            integration_id = data.get("id")
            values = data.get("values") or {}
            await self._handle_integration_update_config(integration_id, values)

        # Living UI settings handlers
        elif msg_type == "living_ui_settings_get":
            await self._handle_living_ui_settings_get()

        elif msg_type == "living_ui_project_setting_update":
            project_id = data.get("projectId", "")
            setting = data.get("setting", "")
            value = data.get("value")
            await self._handle_living_ui_project_setting_update(
                project_id, setting, value
            )

        elif msg_type == "living_ui_backups_list":
            await self._handle_living_ui_backups_list(data.get("projectId", ""))

        elif msg_type == "living_ui_backup_now":
            await self._handle_living_ui_backup_now(data.get("projectId", ""))

        elif msg_type == "living_ui_backup_restore":
            await self._handle_living_ui_backup_restore(
                data.get("projectId", ""),
                data.get("filename", ""),
                data.get("sourceProjectId") or None,
            )

        elif msg_type == "living_ui_backup_delete":
            await self._handle_living_ui_backup_delete(
                data.get("projectId", ""),
                data.get("filename", ""),
                orphan=bool(data.get("orphan", False)),
            )

        elif msg_type == "living_ui_marketplace_list":
            await self._handle_marketplace_list()

        elif msg_type == "living_ui_marketplace_install":
            app_id = data.get("appId", "")
            app_name = data.get("appName", "")
            app_description = data.get("appDescription", "")
            custom_fields = data.get("customFields", {})
            # Run as background task so the WS loop stays unblocked for concurrent installs
            asyncio.create_task(
                self._handle_marketplace_install(
                    app_id, app_name, app_description, custom_fields
                )
            )

        elif msg_type == "living_ui_import":
            source = data.get("source", "")
            name = data.get("name", "External App")
            asyncio.create_task(self._handle_living_ui_import(source, name))

        # Playbook catalogue handlers
        elif msg_type == "playbook_list":
            await self._handle_playbook_list()

        # WhatsApp QR code flow handlers — session-scoped: QR/status results
        # go to the requesting connection only, never broadcast (a second
        # settings tab used to pick up the broadcast, run its own poll loop
        # and double-complete the link).
        elif msg_type == "whatsapp_start_qr":
            await self._handle_whatsapp_start_qr(
                ws, force=bool(data.get("force", False))
            )

        elif msg_type == "whatsapp_check_status":
            session_id = data.get("session_id", "")
            await self._handle_whatsapp_check_status(session_id, ws)

        elif msg_type == "whatsapp_cancel":
            session_id = data.get("session_id", "")
            await self._handle_whatsapp_cancel(session_id, ws)

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

        elif msg_type == "living_ui_wizard_interview":
            await self._handle_living_ui_wizard_interview(data)

        elif msg_type == "living_ui_wizard_finalize":
            await self._handle_living_ui_wizard_finalize(data)

        elif msg_type == "living_ui_theme_update":
            await self._handle_living_ui_theme_update(data)

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
            await self._handle_living_ui_delete(
                project_id, delete_backups=bool(data.get("deleteBackups", False))
            )

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
            await self._broadcast(
                {
                    "type": "update_check_result",
                    "data": {
                        "updateAvailable": update_available,
                        "currentVersion": current,
                        "latestVersion": latest,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "update_check_result",
                    "data": {
                        "updateAvailable": False,
                        "currentVersion": "",
                        "latestVersion": "",
                        "error": str(e),
                    },
                }
            )

    async def _handle_do_update(self) -> None:
        """Perform CraftBot update and restart."""
        from app.updater import perform_update

        async def progress(msg: str) -> None:
            await self._broadcast(
                {
                    "type": "update_progress",
                    "data": {"message": msg},
                }
            )

        try:
            await perform_update(progress_callback=progress)
        except Exception as e:
            await self._broadcast(
                {
                    "type": "update_progress",
                    "data": {"message": f"Update failed: {e}"},
                }
            )

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

            await self._broadcast(
                {
                    "type": "dashboard_filtered_metrics",
                    "data": filtered_metrics.to_dict(),
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "dashboard_filtered_metrics",
                    "data": {
                        "error": str(e),
                        "period": period,
                    },
                }
            )

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
                await self._broadcast(
                    {
                        "type": "onboarding_step",
                        "data": {
                            "success": True,
                            "completed": True,
                        },
                    }
                )
                return

            step = controller.get_current_step()
            options = controller.get_step_options()

            await self._broadcast(
                {
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
                            **self._step_subscription_meta(step),
                            "form_fields": self._get_step_form_fields(step),
                        },
                    },
                }
            )
        except Exception as e:
            logger.error(f"[ONBOARDING] Error getting step: {e}")
            await self._broadcast(
                {
                    "type": "onboarding_step",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    @staticmethod
    def _step_subscription_meta(step) -> Dict[str, Any]:
        """Subscription-OAuth hints for a step (empty for non-api_key steps).

        Lets the onboarding UI render a 'Sign in with ChatGPT/Grok' button next
        to the API-key field for providers that support subscription auth, the
        same capability the Settings model panel exposes.
        """
        supports = getattr(step, "supports_subscription_oauth", None)
        if callable(supports) and supports():
            return {
                "supports_subscription_oauth": True,
                "subscription_label": step.subscription_label(),
            }
        return {"supports_subscription_oauth": False, "subscription_label": ""}

    @staticmethod
    def _get_step_form_fields(step) -> Optional[list]:
        """Extract form field definitions from a step, if it supports them."""
        form_fields = getattr(step, "get_form_fields", lambda: [])()
        if not form_fields:
            return None
        return [
            {
                "name": f.name,
                "label": f.label,
                "field_type": f.field_type,
                "options": [
                    {
                        "value": o.value,
                        "label": o.label,
                        "description": o.description,
                        "default": o.default,
                    }
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
                await self._broadcast(
                    {
                        "type": "onboarding_submit",
                        "data": {
                            "success": False,
                            "error": error or "Invalid value",
                            "index": controller.current_step_index,
                        },
                    }
                )
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
                        await self._broadcast(
                            {
                                "type": "onboarding_submit",
                                "data": {
                                    "success": False,
                                    "error": f"Ollama connection failed: {err}",
                                    "index": controller.current_step_index,
                                },
                            }
                        )
                        return
                    # Normalise the value to the URL that actually worked
                    value = ollama_url
                elif value:
                    from app.models import MODEL_REGISTRY, InterfaceType
                    from app.onboarding.interfaces.steps import ApiKeyStep

                    # For proxied providers, value is a dict {api_key, via, or_model?}.
                    # via='direct' → test the provider's own endpoint.
                    # via='openrouter' → test via OpenRouter proxy.
                    if provider in ApiKeyStep.OPENROUTER_PROXIED:
                        if isinstance(value, dict):
                            actual_key = value.get("api_key", "")
                            via = value.get("via", "openrouter")
                            or_model = value.get("or_model", "")
                        else:
                            actual_key = value
                            via = "direct"
                            or_model = ""

                        if via == "openrouter":
                            if not or_model:
                                from agent_core.core.models.factory import (
                                    _OR_MODEL_MAP,
                                    _to_openrouter_slug,
                                )

                                native_model = MODEL_REGISTRY.get(provider, {}).get(
                                    InterfaceType.LLM, ""
                                )
                                or_model = _OR_MODEL_MAP.get(provider, {}).get(
                                    native_model
                                ) or _to_openrouter_slug(provider, native_model)
                            test_result = test_connection(
                                provider="openrouter",
                                api_key=actual_key,
                                model=or_model,
                            )
                        else:
                            # Direct API test
                            native_model = MODEL_REGISTRY.get(provider, {}).get(
                                InterfaceType.LLM
                            )
                            test_result = test_connection(
                                provider=provider,
                                api_key=actual_key,
                                model=native_model,
                            )
                        # Store via + resolved or_model so _complete() knows how to save
                        value = {
                            "api_key": actual_key,
                            "via": via,
                            "or_model": or_model,
                        }
                    else:
                        actual_key = (
                            value
                            if isinstance(value, str)
                            else value.get("api_key", "")
                        )
                        default_model = MODEL_REGISTRY.get(provider, {}).get(
                            InterfaceType.LLM
                        )
                        test_result = test_connection(
                            provider=provider,
                            api_key=actual_key,
                            model=default_model,
                        )
                    if not test_result.get("success"):
                        error_msg = (
                            test_result.get("error")
                            or test_result.get("message")
                            or "Connection test failed"
                        )
                        await self._broadcast(
                            {
                                "type": "onboarding_submit",
                                "data": {
                                    "success": False,
                                    "error": error_msg,
                                    "index": controller.current_step_index,
                                },
                            }
                        )
                        return

            # Submit the value
            controller.submit_step_value(value)

            # Move to next step
            has_more = controller.next_step()

            if not has_more:
                # Onboarding complete - controller._complete() already called
                from app.onboarding import onboarding_manager

                from app.ui_layer.settings.general_settings import (
                    get_agent_profile_picture_info,
                )

                picture_info = get_agent_profile_picture_info()
                await self._broadcast(
                    {
                        "type": "onboarding_complete",
                        "data": {
                            "success": True,
                            "agentName": onboarding_manager.state.agent_name or "Agent",
                            "agentProfilePictureUrl": picture_info["url"],
                            "agentProfilePictureHasCustom": picture_info["has_custom"],
                        },
                    }
                )
                # Clear cached controller for fresh state
                if hasattr(self, "_onboarding_controller"):
                    delattr(self, "_onboarding_controller")
            else:
                # Send next step info
                step = controller.get_current_step()
                options = controller.get_step_options()

                await self._broadcast(
                    {
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
                                **self._step_subscription_meta(step),
                                "form_fields": self._get_step_form_fields(step),
                            },
                        },
                    }
                )
        except Exception as e:
            logger.error(f"[ONBOARDING] Error submitting step: {e}")
            await self._broadcast(
                {
                    "type": "onboarding_submit",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_onboarding_skip(self) -> None:
        """Skip the current optional onboarding step."""
        try:
            controller = self._get_onboarding_controller()

            # Check if step is required before trying to skip
            step = controller.get_current_step()
            if step.required:
                await self._broadcast(
                    {
                        "type": "onboarding_skip",
                        "data": {
                            "success": False,
                            "error": "This step is required and cannot be skipped",
                        },
                    }
                )
                return

            # Skip the step (advances to next or completes)
            controller.skip_step()

            # Check if onboarding is complete after skip
            if controller.is_complete:
                from app.onboarding import onboarding_manager

                from app.ui_layer.settings.general_settings import (
                    get_agent_profile_picture_info,
                )

                picture_info = get_agent_profile_picture_info()
                await self._broadcast(
                    {
                        "type": "onboarding_complete",
                        "data": {
                            "success": True,
                            "agentName": onboarding_manager.state.agent_name or "Agent",
                            "agentProfilePictureUrl": picture_info["url"],
                            "agentProfilePictureHasCustom": picture_info["has_custom"],
                        },
                    }
                )
                if hasattr(self, "_onboarding_controller"):
                    delattr(self, "_onboarding_controller")
            else:
                # Send next step info
                step = controller.get_current_step()
                options = controller.get_step_options()

                await self._broadcast(
                    {
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
                                **self._step_subscription_meta(step),
                            },
                        },
                    }
                )
        except Exception as e:
            logger.error(f"[ONBOARDING] Error skipping step: {e}")
            await self._broadcast(
                {
                    "type": "onboarding_skip",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_onboarding_back(self) -> None:
        """Go back to the previous onboarding step."""
        try:
            controller = self._get_onboarding_controller()

            if not controller.previous_step():
                await self._broadcast(
                    {
                        "type": "onboarding_back",
                        "data": {
                            "success": False,
                            "error": "Already at the first step",
                        },
                    }
                )
                return

            # Send previous step info
            step = controller.get_current_step()
            options = controller.get_step_options()

            await self._broadcast(
                {
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
                            **self._step_subscription_meta(step),
                            "form_fields": self._get_step_form_fields(step),
                        },
                    },
                }
            )
        except Exception as e:
            logger.error(f"[ONBOARDING] Error going back: {e}")
            await self._broadcast(
                {
                    "type": "onboarding_back",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    # ── Local LLM (Ollama) handlers ──────────────────────────────────────────

    async def _handle_local_llm_check(self) -> None:
        """Return Ollama installation and runtime status."""
        try:
            from app.ui_layer.local_llm_setup import get_ollama_status

            status = get_ollama_status()
            await self._broadcast(
                {
                    "type": "local_llm_check",
                    "data": {"success": True, **status},
                }
            )
        except Exception as e:
            logger.error(f"[LOCAL_LLM] Error checking status: {e}")
            await self._broadcast(
                {
                    "type": "local_llm_check",
                    "data": {"success": False, "error": str(e)},
                }
            )

    async def _handle_local_llm_test(self, url: str) -> None:
        """Test an HTTP connection to a running Ollama instance."""
        try:
            from app.ui_layer.local_llm_setup import test_ollama_connection_sync

            result = test_ollama_connection_sync(url)
            await self._broadcast(
                {
                    "type": "local_llm_test",
                    "data": result,
                }
            )
        except Exception as e:
            logger.error(f"[LOCAL_LLM] Error testing connection: {e}")
            await self._broadcast(
                {
                    "type": "local_llm_test",
                    "data": {"success": False, "error": str(e)},
                }
            )

    async def _handle_local_llm_install(self) -> None:
        """Install Ollama, streaming progress back to the client."""

        async def progress_callback(msg: str) -> None:
            await self._broadcast(
                {
                    "type": "local_llm_install_progress",
                    "data": {"message": msg},
                }
            )

        try:
            from app.ui_layer.local_llm_setup import install_ollama

            result = await install_ollama(progress_callback)
            await self._broadcast(
                {
                    "type": "local_llm_install",
                    "data": result,
                }
            )
        except Exception as e:
            logger.error(f"[LOCAL_LLM] Error installing: {e}")
            await self._broadcast(
                {
                    "type": "local_llm_install",
                    "data": {"success": False, "error": str(e)},
                }
            )

    async def _handle_local_llm_start(self) -> None:
        """Start the Ollama server."""
        try:
            from app.ui_layer.local_llm_setup import start_ollama

            result = await start_ollama()
            await self._broadcast(
                {
                    "type": "local_llm_start",
                    "data": result,
                }
            )
        except Exception as e:
            logger.error(f"[LOCAL_LLM] Error starting Ollama: {e}")
            await self._broadcast(
                {
                    "type": "local_llm_start",
                    "data": {"success": False, "error": str(e)},
                }
            )

    async def _handle_local_llm_suggested_models(self) -> None:
        """Return the list of suggested Ollama models."""
        from app.ui_layer.local_llm_setup import SUGGESTED_MODELS

        await self._broadcast(
            {
                "type": "local_llm_suggested_models",
                "data": {"models": SUGGESTED_MODELS},
            }
        )

    async def _handle_local_llm_pull_model(
        self, model: str, base_url: str | None = None
    ) -> None:
        """Pull an Ollama model, streaming progress back to the client."""
        if not model:
            await self._broadcast(
                {
                    "type": "local_llm_pull_model",
                    "data": {"success": False, "error": "No model specified"},
                }
            )
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
            await self._broadcast(
                {
                    "type": "local_llm_pull_progress",
                    "data": data,
                }
            )

        try:
            from app.ui_layer.local_llm_setup import pull_ollama_model

            result = await pull_ollama_model(
                model, progress_callback, base_url=base_url
            )
            await self._broadcast(
                {
                    "type": "local_llm_pull_model",
                    "data": result,
                }
            )
        except Exception as e:
            logger.error(f"[LOCAL_LLM] Error pulling model {model}: {e}")
            await self._broadcast(
                {
                    "type": "local_llm_pull_model",
                    "data": {"success": False, "error": str(e)},
                }
            )

    # -------------------------------------------------------------------------
    # Living UI Handlers
    # -------------------------------------------------------------------------

    async def _handle_living_ui_wizard_interview(self, data: Dict[str, Any]) -> None:
        """Wizard step 2: generate interview questions from the Step-1
        configuration via a direct LLM call (no project/session exists yet)."""
        from app.living_ui import wizard

        wizard_id = str(data.get("wizardId", ""))
        try:
            config = data.get("config") or {}
            living_ui_dir = Path(self._living_ui_manager.living_ui_dir)
            wizard.sweep_stale_staging(living_ui_dir)

            # Reference images are described once and reused at finalize.
            image_notes = await wizard.describe_staged_images(living_ui_dir, wizard_id)
            self._wizard_image_notes[wizard_id] = image_notes

            questions = await wizard.generate_interview(config, image_notes)
            await self._broadcast(
                {
                    "type": "living_ui_wizard_interview",
                    "data": {
                        "success": True,
                        "wizardId": wizard_id,
                        "questions": questions,
                    },
                }
            )
        except Exception as e:
            logger.error(f"[LIVING_UI:WIZARD] interview failed: {e}")
            await self._broadcast(
                {
                    "type": "living_ui_wizard_interview",
                    "data": {
                        "success": False,
                        "wizardId": wizard_id,
                        "error": str(e),
                    },
                }
            )

    async def _handle_living_ui_wizard_finalize(self, data: Dict[str, Any]) -> None:
        """Wizard step 3: synthesize the requirements document, create the
        project, move staged attachments in, queue the build run in the
        project's session, and hand the frontend its projectId to navigate to."""
        from app.living_ui import wizard

        wizard_id = str(data.get("wizardId", ""))
        try:
            config = data.get("config") or {}
            answers = data.get("answers") or []
            name = str(config.get("name", "")).strip()
            description = str(config.get("description", "")).strip()
            if not name or not description:
                raise ValueError("Name and description are required")

            living_ui_dir = Path(self._living_ui_manager.living_ui_dir)
            image_notes = self._wizard_image_notes.pop(wizard_id, None)
            if image_notes is None:
                image_notes = await wizard.describe_staged_images(
                    living_ui_dir, wizard_id
                )

            # SECOND INTERVIEW ROUND (one, at most): with a marketplace
            # match, round 1 collapses to the marketplace question — correct
            # for the install path, but the other two answers need the real
            # questions asked NOW (both observed live 2026-08-05):
            #   adapt  → targeted "what should be different" follow-ups
            #            (else synthesis fabricates the adaptation list);
            #   fresh  → the standard requirement interview, catalogue
            #            withheld (else the build synthesizes from a
            #            one-line description with zero questions asked).
            # Fail-open: no follow-ups → synthesize as before.
            if not bool(data.get("followupDone")):
                followups = []
                try:
                    if wizard.adapt_chosen(answers):
                        followups = await wizard.generate_followup_questions(
                            config, answers, image_notes
                        )
                    elif wizard.fresh_build_chosen(answers) and len(answers) <= 1:
                        followups = await wizard.generate_interview(
                            config, image_notes, include_marketplace=False
                        )
                except Exception as e:
                    logger.warning(f"[LIVING_UI:WIZARD] round 2 skipped: {e}")
                    followups = []
                if followups:
                    # Re-id: a model reusing "q1" would collide with the
                    # marketplace question and overwrite its answer in the
                    # frontend's answers map.
                    for i, q in enumerate(followups):
                        q["id"] = f"r2-{i + 1}"
                    self._wizard_image_notes[wizard_id] = image_notes
                    await self._broadcast(
                        {
                            "type": "living_ui_wizard_finalize",
                            "data": {
                                "success": True,
                                "wizardId": wizard_id,
                                "followupQuestions": followups,
                            },
                        }
                    )
                    return

            requirements_doc = await wizard.synthesize_requirements(
                config, answers, image_notes
            )

            auth_mode = str(config.get("authMode") or "none")
            # stylePack is derived by the frontend from the theme catalog
            # (style-bearing theme id, or "" for pinned color themes).
            style_pack = str(config.get("stylePack") or "")
            project = await self._living_ui_manager.create_project(
                name=name,
                description=description,
                auth_mode=auth_mode,
                style_pack=style_pack,
            )

            # Staged files: uploaded icon → app favicon, references →
            # <project>/reference/. An uploaded icon wins over a lucide pick.
            moved = wizard.move_staging_into_project(
                living_ui_dir, wizard_id, Path(project.path)
            )
            if moved["icon"]:
                project.icon = moved["icon"]
                # Favicon injection edited the system-owned index.html —
                # re-canonize hashes so the validation gate stays green.
                try:
                    await self._living_ui_manager.runner.kit_sync(Path(project.path))
                except Exception as e:
                    logger.warning(f"[LIVING_UI:WIZARD] re-canon failed: {e}")
            elif str(config.get("icon", "")).startswith("lucide:"):
                project.icon = str(config.get("icon"))

            # The wizard's theme pick becomes the project's default display
            # theme — the Living UI page adopts it (absent a local override)
            # and pushes it to the app via the livingui-theme protocol.
            ui_theme = str(config.get("uiTheme") or "").strip()
            if ui_theme:
                project.ui_theme = {"themeId": ui_theme}
            self._living_ui_manager._save_projects()

            # The build's binding specification (walk-verify reads it too).
            reference_dir = Path(project.path) / "reference"
            reference_dir.mkdir(parents=True, exist_ok=True)
            (reference_dir / "requirements.md").write_text(
                requirements_doc, encoding="utf-8"
            )

            # Create the project's session BEFORE broadcasting so the project
            # snapshot carries sessionId — the Living UI page keys its chat
            # panel on project.sessionId, and nothing back-fills it later.
            # (start_development_run reuses this session; ensure is idempotent.)
            self._living_ui_manager.ensure_project_session(project)

            # Same broadcast the plain create path uses — the store's
            # living_ui_create handler adds the project tab.
            await self._broadcast(
                {
                    "type": "living_ui_create",
                    "data": {
                        "success": True,
                        "projectId": project.id,
                        "project": project.to_dict(),
                        "stylePack": style_pack,
                    },
                }
            )

            # Post the "what you asked for" summary as the first bubble in the
            # PROJECT'S session (never main) — it heads the Living UI chat the
            # user is auto-switched into, so the build has a visible cause.
            try:
                await self._display_chat_message(
                    "System",
                    f"**Living UI: {name}**\n\n{description}\n\n"
                    "Building your app now — follow the progress here.",
                    "system",
                    session_id=project.session_id,
                )
            except Exception as e:
                logger.debug(f"[LIVING_UI] create chat message failed: {e}")

            await self._broadcast(
                {
                    "type": "living_ui_status",
                    "data": {
                        "projectId": project.id,
                        "phase": "initializing",
                        "progress": 10,
                        "message": "Project created, starting development...",
                    },
                }
            )

            # Queue the build run in the project's dedicated session.
            session_id = await self._living_ui_manager.start_development_run(project.id)
            if not session_id:
                raise RuntimeError("Failed to start development run")

            # CHAT-PATH tail: tell the session that ran living_ui_scaffold
            # which project resulted. Without this the origin agent's last
            # knowledge is "no project created yet" — observed live
            # 2026-08-05: asked to "add data to it", it searched the
            # filesystem and then asked the user for the project id.
            origin_session = str(data.get("originSessionId") or "").strip()
            if origin_session:
                # Persist for the machine's ready/stuck announcements — the
                # created-trigger below only covers build START.
                try:
                    from app.factory.host_craftbot import get_factory_host

                    get_factory_host().set_origin_session(project.id, origin_session)
                except Exception as e:
                    logger.debug(f"[LIVING_UI:WIZARD] origin persist failed: {e}")
                try:
                    from app.triggers import TriggerSource, TriggerSpec

                    await self._living_ui_manager._trigger_service.emit(
                        TriggerSpec(
                            source=TriggerSource.LIVING_UI_CREATED,
                            description=(
                                f"FYI: the setup questions were answered — "
                                f"Living UI '{project.name}' (project_id "
                                f"{project.id}) has been created and its "
                                "build is running in its own session. No "
                                "action and no message needed: acknowledge "
                                "silently with end_turn unless the user has "
                                "asked for something. Remember the "
                                "project_id for future requests about this "
                                "app."
                            ),
                            priority=10,
                            session_id=origin_session,
                            payload={"project_id": project.id},
                        )
                    )
                except Exception as e:
                    logger.debug(
                        f"[LIVING_UI:WIZARD] origin-session notify failed: {e}"
                    )

            await self._broadcast(
                {
                    "type": "living_ui_wizard_finalize",
                    "data": {
                        "success": True,
                        "wizardId": wizard_id,
                        "projectId": project.id,
                    },
                }
            )
        except Exception as e:
            logger.error(f"[LIVING_UI:WIZARD] finalize failed: {e}")
            await self._broadcast(
                {
                    "type": "living_ui_wizard_finalize",
                    "data": {
                        "success": False,
                        "wizardId": wizard_id,
                        "error": str(e),
                    },
                }
            )

    async def _handle_living_ui_theme_update(self, data: Dict[str, Any]) -> None:
        """Persist a project's display theme so it follows the user across
        browsers ({"projectId", "theme": {"themeId", "customColors"}})."""
        try:
            project_id = str(data.get("projectId", ""))
            theme = data.get("theme")
            if project_id:
                self._living_ui_manager.set_project_ui_theme(project_id, theme)
        except Exception as e:
            logger.debug(f"[LIVING_UI] theme update failed: {e}")

    async def _handle_living_ui_create(self, data: Dict[str, Any]) -> None:
        """Create a new Living UI project."""
        try:
            name = data.get("name", "")
            description = data.get("description", "")
            features = data.get("features", [])
            data_source = data.get("dataSource")
            theme = data.get("theme", "system")

            if not name or not description:
                await self._broadcast(
                    {
                        "type": "living_ui_error",
                        "data": {
                            "projectId": "",
                            "error": "Name and description are required",
                        },
                    }
                )
                return

            # Create the project (directory/template)
            auth_mode = data.get("authMode", "none")
            layout = data.get("layout", "")
            style_pack = data.get("stylePack", "")
            ref_files = data.get("referenceFiles") or []

            # Fold wizard choices into the build description so they land in
            # the task instruction and reference/requirements.md.
            extras = []
            if layout and layout != "free":
                extras.append(f"Layout preference: {layout}")
            if style_pack:
                extras.append(f"Style pack (visual theme): {style_pack}")
            if ref_files:
                names = ", ".join(Path(f).name for f in ref_files[:10])
                extras.append(
                    f"Reference files (design sketches/docs) in reference/: {names} — "
                    "study them before designing the UI."
                )
            if extras:
                description = description + "\n\n" + "\n".join(extras)

            project = await self._living_ui_manager.create_project(
                name=name,
                description=description,
                features=features,
                data_source=data_source,
                theme=theme,
                auth_mode=auth_mode,
                style_pack=style_pack,
            )

            # Move staged reference files into the project.
            if ref_files:
                ref_dir = Path(project.path) / "reference"
                ref_dir.mkdir(parents=True, exist_ok=True)
                for f in ref_files[:10]:
                    src = Path(f)
                    staging_root = (
                        Path(self._living_ui_manager.living_ui_dir) / "_staging"
                    )
                    if src.exists() and staging_root in src.parents:
                        shutil.move(str(src), str(ref_dir / src.name))

            # Create the session BEFORE broadcasting so the project snapshot
            # carries sessionId (the Living UI page's chat panel keys on it;
            # nothing back-fills it later). start_development_run reuses it.
            self._living_ui_manager.ensure_project_session(project)

            # Broadcast project created
            await self._broadcast(
                {
                    "type": "living_ui_create",
                    "data": {
                        "success": True,
                        "projectId": project.id,
                        "project": project.to_dict(),
                        "stylePack": style_pack,
                    },
                }
            )

            # Post the "what you asked for" summary as the first bubble in the
            # PROJECT'S session (never main) — it heads the Living UI chat the
            # user is auto-switched into, so the build has a visible cause.
            try:
                await self._display_chat_message(
                    "System",
                    f"**Living UI: {name}**\n\n{description}\n\n"
                    "Building your app now — follow the progress here.",
                    "system",
                    session_id=project.session_id,
                )
            except Exception as e:
                logger.debug(f"[LIVING_UI] create chat message failed: {e}")

            # Broadcast initial status update
            await self._broadcast(
                {
                    "type": "living_ui_status",
                    "data": {
                        "projectId": project.id,
                        "phase": "initializing",
                        "progress": 10,
                        "message": "Project created, starting development...",
                    },
                }
            )

            # Queue the build run in the project's dedicated session.
            # The manager handles: session creation, status update, trigger firing.
            session_id = await self._living_ui_manager.start_development_run(project.id)

            if session_id:
                logger.info(
                    f"[LIVING_UI] Queued build run in session {session_id} "
                    f"for project {project.id}"
                )
            else:
                logger.error(
                    f"[LIVING_UI] Failed to start development run for project {project.id}"
                )
                await self._broadcast(
                    {
                        "type": "living_ui_error",
                        "data": {
                            "projectId": project.id,
                            "error": "Failed to start development run",
                        },
                    }
                )

        except Exception as e:
            logger.error(f"[LIVING_UI] Error creating project: {e}")
            await self._broadcast(
                {
                    "type": "living_ui_error",
                    "data": {
                        "projectId": "",
                        "error": str(e),
                    },
                }
            )

    async def _handle_living_ui_list(self) -> None:
        """Get list of all Living UI projects."""
        try:
            projects = self._living_ui_manager.list_projects()
            await self._broadcast(
                {
                    "type": "living_ui_list",
                    "data": {
                        "success": True,
                        "projects": [p.to_dict() for p in projects],
                    },
                }
            )
            # Replay buffered build events for any in-progress build so a
            # reconnecting client repopulates the construction dock feed.
            try:
                from app.living_ui import construction_events

                for p in projects:
                    if getattr(p, "status", None) not in ("creating", "error"):
                        continue
                    events = construction_events.get_buffered_events(p.id)
                    if events:
                        await self._broadcast(
                            {
                                "type": "living_ui_build_events_replay",
                                "data": {"projectId": p.id, "events": events},
                            }
                        )
            except Exception as e:
                logger.debug(f"[LIVING_UI] build-event replay skipped: {e}")
        except Exception as e:
            logger.error(f"[LIVING_UI] Error listing projects: {e}")
            await self._broadcast(
                {
                    "type": "living_ui_list",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_living_ui_launch(self, project_id: str) -> None:
        """Launch a Living UI project."""
        try:
            success = await self._living_ui_manager.launch_project(project_id)
            project = self._living_ui_manager.get_project(project_id)

            if success and project:
                await self._broadcast(
                    {
                        "type": "living_ui_launch",
                        "data": {
                            "success": True,
                            "projectId": project_id,
                            "url": project.url,
                            "port": project.port,
                        },
                    }
                )
            else:
                await self._broadcast(
                    {
                        "type": "living_ui_launch",
                        "data": {
                            "success": False,
                            "projectId": project_id,
                            "error": project.error if project else "Project not found",
                        },
                    }
                )
        except Exception as e:
            logger.error(f"[LIVING_UI] Error launching project: {e}")
            await self._broadcast(
                {
                    "type": "living_ui_launch",
                    "data": {
                        "success": False,
                        "projectId": project_id,
                        "error": str(e),
                    },
                }
            )

    async def _handle_living_ui_stop(self, project_id: str) -> None:
        """Stop a running Living UI project."""
        try:
            success = await self._living_ui_manager.stop_project(project_id)
            await self._broadcast(
                {
                    "type": "living_ui_stop",
                    "data": {
                        "success": success,
                        "projectId": project_id,
                    },
                }
            )
        except Exception as e:
            logger.error(f"[LIVING_UI] Error stopping project: {e}")
            await self._broadcast(
                {
                    "type": "living_ui_stop",
                    "data": {
                        "success": False,
                        "projectId": project_id,
                        "error": str(e),
                    },
                }
            )

    async def _handle_living_ui_delete(
        self, project_id: str, delete_backups: bool = False
    ) -> None:
        """Delete a Living UI project (and its dedicated session)."""
        try:
            project = self._living_ui_manager.get_project(project_id)
            session_id = project.session_id if project else None

            success = await self._living_ui_manager.delete_project(
                project_id, delete_backups=delete_backups
            )
            try:
                from app.living_ui import construction_events

                construction_events.clear_buffer(project_id)
            except Exception:
                pass
            await self._broadcast(
                {
                    "type": "living_ui_delete",
                    "data": {
                        "success": success,
                        "projectId": project_id,
                    },
                }
            )
            # The manager deletes the project's session as part of
            # delete_project — tell the sidebar to drop it too.
            if success and session_id:
                await self._broadcast(
                    {
                        "type": "session_deleted",
                        "data": {"sessionId": session_id},
                    }
                )
        except Exception as e:
            logger.error(f"[LIVING_UI] Error deleting project: {e}")
            await self._broadcast(
                {
                    "type": "living_ui_delete",
                    "data": {
                        "success": False,
                        "projectId": project_id,
                        "error": str(e),
                    },
                }
            )

    async def _living_ui_export_handler(self, request: "web.Request") -> "web.Response":
        """HTTP handler: download a Living UI project as a ZIP file."""
        from aiohttp import web

        project_id = request.match_info["project_id"]
        try:
            zip_path = self._living_ui_manager.export_project_zip(project_id)
            project = self._living_ui_manager.get_project(project_id)
            filename = (
                f"{project.name.replace(' ', '_')}.zip"
                if project
                else f"{project_id}.zip"
            )

            response = web.FileResponse(
                zip_path,
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Content-Type": "application/zip",
                },
            )
            # Schedule cleanup after response is sent
            response._zip_cleanup_path = zip_path
            return response
        except (ValueError, FileNotFoundError) as e:
            from agent_core.core.errors import ErrorCategory, ErrorInfo, redact
            from app.errors.web import error_json_response

            return error_json_response(
                ErrorInfo(
                    category=ErrorCategory.NOT_FOUND,
                    code="LIVING_UI_EXPORT_NOT_FOUND",
                    title="Export not found",
                    message=redact(str(e)),
                ),
                status=404,
            )
        except Exception as e:
            logger.error(f"[LIVING_UI] Export error: {e}")
            from agent_core.core.errors import ErrorCategory, ErrorInfo, redact
            from app.errors.web import error_json_response

            return error_json_response(
                ErrorInfo(
                    category=ErrorCategory.INTERNAL,
                    code="LIVING_UI_EXPORT_FAILED",
                    title="Export failed",
                    message=redact(str(e)),
                ),
                status=500,
            )

    async def _living_ui_stage_handler(self, request: "web.Request") -> "web.Response":
        """Stage a reference file (sketch/screenshot/doc) for a NEW Living UI.

        Saves under living_ui/_staging/refs/ and returns {"path": ...}. The
        create flow moves staged files into the project's reference/ dir.

        Wizard mode: with ?wizardId=<id> (and optional &kind=icon) the file
        stages under living_ui/_staging/wizard/<id>/ instead; icons are
        normalized to icon.<ext> so finalize can find them.
        """
        from aiohttp import web

        from app.living_ui import wizard

        wizard_id = request.query.get("wizardId", "")
        kind = request.query.get("kind", "reference")
        try:
            reader = await request.multipart()
            saved = None
            async for part in reader:
                if part.name == "file":
                    filename = Path(part.filename or "reference.bin").name
                    if wizard_id:
                        staging = wizard.staging_dir(
                            Path(self._living_ui_manager.living_ui_dir), wizard_id
                        )
                        if kind == "icon":
                            filename = f"icon{Path(filename).suffix.lower() or '.png'}"
                    else:
                        staging = (
                            Path(self._living_ui_manager.living_ui_dir)
                            / "_staging"
                            / "refs"
                        )
                    staging.mkdir(parents=True, exist_ok=True)
                    target = staging / filename
                    if wizard_id and kind == "icon":
                        # Re-picking the icon replaces it (finalize looks
                        # for exactly icon.<ext>); clear stale extensions.
                        for old in staging.glob("icon.*"):
                            old.unlink(missing_ok=True)
                    else:
                        i = 1
                        while target.exists():
                            target = (
                                staging
                                / f"{target.stem.split('__')[0]}__{i}{target.suffix}"
                            )
                            i += 1
                    with open(target, "wb") as f:
                        while True:
                            chunk = await part.read_chunk()
                            if not chunk:
                                break
                            f.write(chunk)
                    saved = str(target)
            if saved is None:
                return web.json_response({"error": "no file"}, status=400)
            return web.json_response({"path": saved})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _living_ui_icon_handler(
        self, request: "web.Request"
    ) -> "web.StreamResponse":
        """Serve a project's uploaded icon (project.icon == "file:<relpath>")."""
        from aiohttp import web

        project = self._living_ui_manager.get_project(
            request.match_info.get("project_id", "")
        )
        if project and (project.icon or "").startswith("file:"):
            icon_path = (Path(project.path) / project.icon[5:]).resolve()
            # The relpath is server-written, but never serve outside the project.
            if icon_path.is_file() and str(icon_path).startswith(
                str(Path(project.path).resolve())
            ):
                return web.FileResponse(icon_path)
        return web.json_response({"error": "no icon"}, status=404)

    async def _living_ui_import_handler(self, request: "web.Request") -> "web.Response":
        """HTTP handler: stage a ZIP file upload and return the temp path.

        The frontend then sends a living_ui_import WebSocket message with
        the path so the agent handles extraction via the importer skill.
        """
        from aiohttp import web

        try:
            import tempfile

            reader = await request.multipart()
            zip_path = None
            name = ""

            async for part in reader:
                if part.name == "name":
                    name = (await part.read()).decode("utf-8")
                elif part.name == "file":
                    # Save uploaded file to a staging location
                    staging_dir = (
                        Path(self._living_ui_manager.living_ui_dir) / "_staging"
                    )
                    staging_dir.mkdir(parents=True, exist_ok=True)
                    tmp = tempfile.NamedTemporaryFile(
                        suffix=".zip",
                        prefix="import_",
                        dir=str(staging_dir),
                        delete=False,
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

            return web.json_response(
                {
                    "success": True,
                    "path": zip_path,
                    "name": name,
                }
            )
        except Exception as e:
            logger.error(f"[LIVING_UI] Upload staging error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def _workspace_upload_handler(self, request: "web.Request") -> "web.Response":
        """HTTP handler: stream-upload a file directly into the workspace.

        Accepts multipart/form-data with a single 'file' field.
        The target path is passed as the 'path' query parameter.
        """
        from aiohttp import web

        try:
            file_path = request.rel_url.query.get("path", "").strip()
            if not file_path:
                return web.json_response(
                    {"success": False, "error": "Missing 'path' query parameter"},
                    status=400,
                )

            target = self._validate_path(file_path)
            target.parent.mkdir(parents=True, exist_ok=True)

            reader = await request.multipart()
            written = False
            async for part in reader:
                if part.name == "file":
                    with open(target, "wb") as f:
                        while True:
                            chunk = await part.read_chunk()
                            if not chunk:
                                break
                            f.write(chunk)
                    written = True
                    break

            if not written:
                return web.json_response(
                    {"success": False, "error": "No file field in request"},
                    status=400,
                )

            file_info = self._get_file_info(target)

            await self._broadcast(
                {
                    "type": "file_upload",
                    "data": {
                        "path": file_path,
                        "fileInfo": file_info,
                        "success": True,
                    },
                }
            )

            return web.json_response(
                {"success": True, "path": file_path, "fileInfo": file_info}
            )
        except ValueError as e:
            return web.json_response({"success": False, "error": str(e)}, status=400)
        except Exception as e:
            logger.error(f"[WORKSPACE] Upload error: {e}")
            return web.json_response({"success": False, "error": str(e)}, status=500)

    async def _chat_attachment_upload_handler(
        self, request: "web.Request"
    ) -> "web.Response":
        """HTTP handler: stream-upload a chat attachment into workspace/download/.

        Accepts multipart/form-data with a single 'file' field.
        Pass 'name' and 'type' as query parameters.
        """
        import uuid
        from aiohttp import web

        try:
            name = (
                request.rel_url.query.get("name", "attachment").strip() or "attachment"
            )
            file_type = (
                request.rel_url.query.get("type", "application/octet-stream").strip()
                or "application/octet-stream"
            )

            download_dir = Path(AGENT_WORKSPACE_ROOT) / "download"
            download_dir.mkdir(parents=True, exist_ok=True)

            unique_name = f"{uuid.uuid4().hex[:8]}_{name}"
            file_path = download_dir / unique_name
            relative_path = f"download/{unique_name}"

            reader = await request.multipart()
            size = 0
            written = False
            async for part in reader:
                if part.name == "file":
                    with open(file_path, "wb") as f:
                        while True:
                            chunk = await part.read_chunk()
                            if not chunk:
                                break
                            f.write(chunk)
                            size += len(chunk)
                    written = True
                    break

            if not written:
                return web.json_response(
                    {"success": False, "error": "No file field in request"},
                    status=400,
                )

            return web.json_response(
                {
                    "success": True,
                    "serverPath": relative_path,
                    "url": f"/api/workspace/{relative_path}",
                    "name": name,
                    "size": size,
                    "type": file_type,
                }
            )
        except Exception as e:
            logger.error(f"[CHAT ATTACHMENT] Upload error: {e}")
            return web.json_response({"success": False, "error": str(e)}, status=500)

    # ─────────────────────────────────────────────────────────────────────
    # Agent profile bundle (.craftbot) — export / inspect / import
    # ─────────────────────────────────────────────────────────────────────

    async def _profile_export_handler(self, request: "web.Request") -> "web.Response":
        """Build a .craftbot bundle of the current agent and return it."""
        from aiohttp import web
        from app.ui_layer.settings.profile_bundle import export_profile
        import shutil

        description = request.query.get("description", "")
        try:
            result = export_profile(description=description)
        except Exception as exc:
            logger.error(f"[PROFILE_BUNDLE] Export failed: {exc}", exc_info=True)
            return web.json_response({"error": str(exc)}, status=500)

        if not result.get("success"):
            return web.json_response(
                {"error": result.get("error", "Export failed")}, status=500
            )

        bundle_path = Path(result["path"])
        filename = result["filename"]
        try:
            payload = bundle_path.read_bytes()
        finally:
            # Clean up the temp file + its parent dir immediately. Bundles are
            # small enough (no node_modules) to hold in memory briefly.
            shutil.rmtree(bundle_path.parent, ignore_errors=True)

        return web.Response(
            body=payload,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(payload)),
            },
        )

    async def _stage_uploaded_bundle(self, request: "web.Request") -> Optional[str]:
        """Read the multipart upload and save the bundle to a temp file."""
        import tempfile

        reader = await request.multipart()
        bundle_path: Optional[str] = None
        async for part in reader:
            if part.name == "file":
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".craftbot",
                    prefix="craftbot_profile_in_",
                    delete=False,
                )
                while True:
                    chunk = await part.read_chunk()
                    if not chunk:
                        break
                    tmp.write(chunk)
                tmp.close()
                bundle_path = tmp.name
        return bundle_path

    async def _profile_inspect_handler(self, request: "web.Request") -> "web.Response":
        """Read a bundle's manifest so the frontend can render a preview modal."""
        from aiohttp import web
        from app.ui_layer.settings.profile_bundle import inspect_bundle

        bundle_path = None
        try:
            bundle_path = await self._stage_uploaded_bundle(request)
            if not bundle_path:
                return web.json_response(
                    {"error": "No bundle file uploaded"}, status=400
                )
            result = inspect_bundle(bundle_path)
            # Read bytes into memory and delete the temp file immediately so a
            # cancelled import (user closes modal) never leaks a file to %TEMP%.
            bundle_bytes = Path(bundle_path).read_bytes()
            token = str(uuid.uuid4())
            self._staged_bundles[token] = bundle_bytes
            result["bundle_token"] = token
            return web.json_response(result)
        except Exception as exc:
            logger.error(f"[PROFILE_BUNDLE] Inspect failed: {exc}", exc_info=True)
            return web.json_response({"error": str(exc)}, status=500)
        finally:
            if bundle_path:
                try:
                    Path(bundle_path).unlink(missing_ok=True)
                except Exception:
                    pass

    async def _profile_import_handler(self, request: "web.Request") -> "web.Response":
        """Apply a previously-inspected bundle to the agent."""
        from aiohttp import web
        from app.ui_layer.settings.profile_bundle import import_profile

        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON body"}, status=400)

        token = payload.get("bundle_token") or ""
        mode = payload.get("mode", "replace")
        if not token:
            return web.json_response({"error": "bundle_token is required"}, status=400)

        bundle_bytes = self._staged_bundles.get(token)
        if bundle_bytes is None:
            return web.json_response(
                {"error": "bundle_token not found or already used"}, status=400
            )

        import tempfile

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".craftbot",
                prefix="craftbot_profile_in_",
                delete=False,
            ) as tmp:
                tmp.write(bundle_bytes)
                tmp_path = tmp.name

            # Pass the live LivingUIManager so imported projects land in its
            # in-memory state. Without this, the manager's stale state will
            # overwrite our file on the next status update / watchdog tick.
            result = import_profile(
                tmp_path,
                mode=mode,
                living_ui_manager=self._living_ui_manager,
            )
        except Exception as exc:
            logger.error(f"[PROFILE_BUNDLE] Import failed: {exc}", exc_info=True)
            return web.json_response({"error": str(exc)}, status=500)
        finally:
            self._staged_bundles.pop(token, None)
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

        return web.json_response(result)

    async def _handle_living_ui_state_update(self, data: Dict[str, Any]) -> None:
        """Handle state update from a Living UI for agent awareness."""
        try:
            project_id = data.get("projectId", "")
            state = data.get("state", {})

            # Store the state for agent context
            from app.state import STATE

            if hasattr(STATE, "update_living_ui_state"):
                STATE.update_living_ui_state(project_id, state)

            # Also forward to any listening clients (for debugging/monitoring)
            await self._broadcast(
                {
                    "type": "living_ui_state_update",
                    "data": {
                        "projectId": project_id,
                        "state": state,
                    },
                }
            )
        except Exception as e:
            logger.error(f"[LIVING_UI] Error handling state update: {e}")

    async def _handle_living_ui_sharing_info(self, project_id: str) -> None:
        """Return sharing info (LAN URL, tunnel URL)."""
        lan_url = self._living_ui_manager.get_lan_url(project_id)
        project = self._living_ui_manager.get_project(project_id)
        await self._broadcast(
            {
                "type": "living_ui_sharing_info",
                "data": {
                    "projectId": project_id,
                    "lanUrl": lan_url,
                    "tunnelUrl": project.tunnel_url if project else None,
                },
            }
        )

    async def _handle_living_ui_tunnel_start(
        self, project_id: str, provider: str
    ) -> None:
        """Start a tunnel for a Living UI project."""
        logger.info(
            f"[LIVING_UI] Tunnel start requested: project={project_id}, provider={provider}"
        )
        try:
            url = await self._living_ui_manager.start_tunnel(project_id, provider)
            await self._broadcast(
                {
                    "type": "living_ui_tunnel_status",
                    "data": {
                        "projectId": project_id,
                        "tunnelUrl": url,
                        "success": url is not None,
                        "error": None if url else f"Failed to start {provider} tunnel",
                    },
                }
            )
        except Exception as e:
            logger.error(f"[LIVING_UI] Tunnel start error: {e}", exc_info=True)
            await self._broadcast(
                {
                    "type": "living_ui_tunnel_status",
                    "data": {
                        "projectId": project_id,
                        "tunnelUrl": None,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_living_ui_tunnel_stop(self, project_id: str) -> None:
        """Stop a tunnel for a Living UI project."""
        await self._living_ui_manager.stop_tunnel(project_id)
        await self._broadcast(
            {
                "type": "living_ui_tunnel_status",
                "data": {
                    "projectId": project_id,
                    "tunnelUrl": None,
                    "success": True,
                },
            }
        )

    async def broadcast_living_ui_ready(
        self, project_id: str, url: str, port: int
    ) -> bool:
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
            logger.error(
                f"[LIVING_UI] Project not found for ready notification: {project_id}"
            )
            # Broadcast error to browser so it can display the error state
            await self._broadcast(
                {
                    "type": "living_ui_error",
                    "data": {
                        "projectId": project_id,
                        "error": f"Project '{project_id}' not found. Check that the project_id matches the one from the build instruction.",
                    },
                }
            )
            return False

        # The delivery/deploy paths (finalize_first_delivery, finalize_modify)
        # hand this method an app that is ALREADY running and healthy — the
        # unconditional status-flip + launch_project below then killed the
        # just-delivered app and re-ran the full pipeline a second time
        # (observed 2026-08-04, kanban_board_1bb64990: every delivery and
        # every modify-flip restarted the app twice, ~9 s of extra downtime
        # right after the user was told "ready"). Launch only when the app
        # is not actually up.
        if (
            project.status == "running"
            and project.port
            and self._living_ui_manager._is_port_in_use(project.port)
        ):
            success = True
        else:
            # Update project status to "ready" (build complete, about to launch)
            self._living_ui_manager.update_project_status(project_id, "ready")

            # Launch the project server via manager (centralizes process management)
            success = await self._living_ui_manager.launch_project(project_id)

        if success:
            # Get updated project info with URL
            project = self._living_ui_manager.get_project(project_id)
            await self._broadcast(
                {
                    "type": "living_ui_ready",
                    "data": {
                        "projectId": project_id,
                        "url": project.url if project else url,
                        "port": project.port if project else port,
                        "sessionId": project.session_id if project else None,
                    },
                }
            )
            logger.info(f"[LIVING_UI] Project {project_id} launched and ready")
            # Build finished — drop the buffered construction-dock feed so a
            # later rebuild of the same project starts from a clean slate.
            try:
                from app.living_ui import construction_events

                construction_events.clear_buffer(project_id)
            except Exception:
                pass
            return True
        else:
            # Launch failed
            await self._broadcast(
                {
                    "type": "living_ui_error",
                    "data": {
                        "projectId": project_id,
                        "error": "Failed to launch Living UI server",
                    },
                }
            )
            logger.error(f"[LIVING_UI] Failed to launch project {project_id}")
            return False

    async def broadcast_living_ui_wizard_open(self, payload: Dict[str, Any]) -> None:
        """Open the Create Custom wizard at the interview step (chat-path
        requirements phase: living_ui_scaffold has questions for the user)."""
        await self._broadcast({"type": "living_ui_wizard_open", "data": payload})

    async def broadcast_living_ui_created(self, project: Dict[str, Any]) -> None:
        """Broadcast that a Living UI project was created (called from agent action).

        Mirrors the modal create flow's broadcast so a chat-created Living UI is
        registered in the browser's project list and shows its build progress.
        """
        await self._broadcast(
            {
                "type": "living_ui_create",
                "data": {
                    "success": True,
                    "projectId": project.get("id", ""),
                    "project": project,
                },
            }
        )

    async def broadcast_living_ui_progress(
        self, project_id: str, phase: str, progress: int, message: str
    ) -> None:
        """Broadcast Living UI creation progress (called from agent action)."""
        await self._broadcast(
            {
                "type": "living_ui_status",
                "data": {
                    "projectId": project_id,
                    "phase": phase,
                    "progress": progress,
                    "message": message,
                },
            }
        )

    async def broadcast_living_ui_todos(
        self,
        project_id: str,
        todos: list,
    ) -> None:
        """Broadcast the agent's current todo list for a Living UI build.

        Fired from the SessionManager's post-update-todos hook whenever the
        agent updates its todos during a Living UI build run.
        """
        await self._broadcast(
            {
                "type": "living_ui_todos",
                "data": {
                    "projectId": project_id,
                    "todos": todos,
                },
            }
        )

    async def broadcast_living_ui_build_event(
        self, project_id: str, event: dict
    ) -> None:
        """Broadcast one construction-dock build event (from the read-only
        observer in construction_events). Fire-and-forget UI observation."""
        await self._broadcast(
            {
                "type": "living_ui_build_event",
                "data": {
                    "projectId": project_id,
                    "event": event,
                },
            }
        )

    async def broadcast_living_ui_data_changed(self, project_id: str) -> None:
        """Tell the browser that a Living UI's backend data was just modified
        by the agent, so it should refresh the iframe to display new state."""
        await self._broadcast(
            {
                "type": "living_ui_data_changed",
                "data": {"projectId": project_id},
            }
        )

    async def _handle_option_click(
        self, value: str, session_id: str, message_id: str
    ) -> None:
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
            logger.error(
                f"[OPTION_CLICK] Error handling option click: {e}", exc_info=True
            )

    async def _handle_question_response(
        self, value: str, session_id: str, message_id: str, dismissed: bool
    ) -> None:
        """Handle the user answering (or dismissing) a pinned agent question.

        Marks the question message answered (which un-pins it everywhere),
        then feeds the answer back into the agent as a regular user message
        so the normal trigger queue/merge behavior applies.
        """
        try:
            question_text = ""
            recorded = QUESTION_DISMISSED_VALUE if dismissed else value
            pending_questions: list = []
            if self._chat and message_id:
                for m in self._chat._messages:
                    if m.message_id == message_id:
                        question_text = m.content
                        m.option_selected = recorded
                        break
                if self._chat._storage:
                    try:
                        self._chat._storage.update_option_selected(
                            message_id, recorded
                        )
                        # After marking this one, whatever question messages
                        # remain unanswered are still pinned in the user's UI.
                        pending_questions = self._chat._storage.get_pending_questions(
                            session_id
                        )
                    except Exception:
                        pass

            # Un-pin on every connected client (the answering client already
            # marked the selection optimistically).
            await self._broadcast(
                {
                    "type": "question_answered",
                    "data": {
                        "sessionId": session_id,
                        "messageId": message_id,
                        "value": recorded,
                    },
                }
            )

            await self._controller.submit_question_answer(
                value,
                question_text,
                session_id,
                dismissed,
                adapter_id=self._adapter_id,
                pending_questions=pending_questions,
            )
        except Exception as e:
            logger.error(
                f"[QUESTION_RESPONSE] Error handling question response: {e}",
                exc_info=True,
            )

    # ─────────────────────────────────────────────────────────────────────
    # Session Handlers (sidebar surface)
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _session_info(session) -> Dict[str, Any]:
        """SessionInfo wire shape for a Session."""
        return {
            "id": session.id,
            "type": session.type,
            "title": session.title,
            "createdAt": session.created_at,
            "lastActiveAt": session.last_active_at,
            "livingUiProjectId": session.living_ui_project_id,
        }

    async def _handle_session_delete(self, data: Dict[str, Any]) -> None:
        """Delete a session and its chat history. The main session is permanent."""
        from agent_core.core.session import MAIN_SESSION_ID

        session_id = (data.get("sessionId") or "").strip()
        if not session_id or session_id == MAIN_SESSION_ID:
            logger.warning(f"[SESSION] Refusing to delete session {session_id!r}")
            return
        try:
            # Durable rows (session, event stream, chat, activity) are purged
            # by the session-delete hook; here we drop the in-memory feeds
            # and notify clients.
            if not await self._controller.agent.delete_session(session_id):
                logger.warning(f"[SESSION] Delete refused for {session_id}")
                return
            self._chat.drop_session_messages(session_id)
            self._action_panel.drop_session_items(session_id)
            await self._broadcast(
                {
                    "type": "session_deleted",
                    "data": {"sessionId": session_id},
                }
            )
        except Exception as e:
            logger.error(f"[SESSION] Delete failed for {session_id}: {e}")

    async def _handle_session_rename(self, data: Dict[str, Any]) -> None:
        """Rename a session's sidebar title."""
        session_id = (data.get("sessionId") or "").strip()
        title = (data.get("title") or "").strip()
        if not session_id or not title:
            return
        try:
            self._controller.agent.rename_session(session_id, title)
            await self.broadcast_session_updated(session_id)
        except Exception as e:
            logger.error(f"[SESSION] Rename failed for {session_id}: {e}")

    async def _handle_session_clear(self, data: Dict[str, Any]) -> None:
        """Clear a session's conversation (chat + activity rows and
        agent-side state)."""
        session_id = (data.get("sessionId") or "").strip() or "main"
        try:
            from app.usage import get_action_storage, get_chat_storage

            try:
                get_chat_storage().clear_messages(session_id)
            except Exception:
                pass
            try:
                get_action_storage().clear_items(session_id)
            except Exception:
                pass
            await self._controller.agent.clear_session(session_id)
            await self.broadcast_session_cleared(session_id)
        except Exception as e:
            logger.error(f"[SESSION] Clear failed for {session_id}: {e}")

    async def _handle_session_list(self, ws=None) -> None:
        """Send the current session list."""
        message = {
            "type": "session_list",
            "data": {
                "sessions": [
                    self._session_info(s)
                    for s in self._controller.agent.session_manager.list_sessions()
                ]
            },
        }
        if ws is not None:
            await ws.send_json(message)
        else:
            await self._broadcast(message)

    async def broadcast_session_updated(self, session_id: str) -> None:
        """Broadcast a session's refreshed metadata (title, last-active, ...).

        Called by ui_controller.notify_session_updated and the rename handler.
        """
        session = self._controller.agent.session_manager.get(session_id)
        if session is None:
            return
        await self._broadcast(
            {
                "type": "session_updated",
                "data": {"session": self._session_info(session)},
            }
        )

    async def broadcast_session_cleared(self, session_id: str) -> None:
        """Drop a session's rendered conversation on every client.

        Called by the /clear command (which has already cleared storage and
        agent-side state) and by the session_clear handler. The activity
        feed is part of the conversation, so its items go with it.
        """
        self._chat.drop_session_messages(session_id)
        self._action_panel.drop_session_items(session_id)
        await self._broadcast(
            {
                "type": "session_cleared",
                "data": {"sessionId": session_id},
            }
        )

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

            await self._broadcast(
                {
                    "type": "settings_get",
                    "data": {
                        "settings": settings,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "settings_get",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_settings_update(self, settings: Dict[str, Any]) -> None:
        """Update settings."""
        try:
            # Convert frontend camelCase to snake_case
            update_data = {}
            if "agentName" in settings:
                update_data["agent_name"] = settings["agentName"]

            result = update_general_settings(update_data)

            if result.get("success"):
                await self._broadcast(
                    {
                        "type": "settings_update",
                        "data": {
                            "settings": settings,
                            "success": True,
                        },
                    }
                )
            else:
                await self._broadcast(
                    {
                        "type": "settings_update",
                        "data": {
                            "success": False,
                            "error": result.get("error", "Unknown error"),
                        },
                    }
                )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "settings_update",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_agent_file_read(self, filename: str) -> None:
        """Read an agent file system file (USER.md or AGENT.md)."""
        result = read_agent_file(filename)

        if result.get("success"):
            await self._broadcast(
                {
                    "type": "agent_file_read",
                    "data": {
                        "filename": filename,
                        "content": result.get("content"),
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "agent_file_read",
                    "data": {
                        "filename": filename,
                        "content": None,
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_agent_file_write(self, filename: str, content: str) -> None:
        """Write to an agent file system file (USER.md or AGENT.md)."""
        result = write_agent_file(filename, content)

        if result.get("success"):
            # Update memory index after file change
            agent = self._controller.agent
            if hasattr(agent, "memory_manager"):
                agent.memory_manager.update()

            await self._broadcast(
                {
                    "type": "agent_file_write",
                    "data": {
                        "filename": filename,
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "agent_file_write",
                    "data": {
                        "filename": filename,
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_agent_file_restore(self, filename: str) -> None:
        """Restore an agent file from template."""
        result = restore_agent_file(filename)

        if result.get("success"):
            # Update memory index after file change
            agent = self._controller.agent
            if hasattr(agent, "memory_manager"):
                agent.memory_manager.update()

            await self._broadcast(
                {
                    "type": "agent_file_restore",
                    "data": {
                        "filename": filename,
                        "content": result.get("content"),
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "agent_file_restore",
                    "data": {
                        "filename": filename,
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_reset(self, data: dict | None = None) -> None:
        """Reset agent state.

        If ``data`` carries a ``components`` list (from the settings checklist),
        only those parts are reset. With no components it's a full reset
        (equivalent to /reset).
        """
        components = None
        if isinstance(data, dict):
            raw = data.get("components")
            if isinstance(raw, list):
                components = [str(c) for c in raw]

        # Snapshot session ids before the reset: sessions deleted inside
        # reset_agent_state bypass _handle_session_delete, so no
        # session_deleted broadcasts happen — we diff and emit them below.
        sessions_before = {
            s.id
            for s in self._controller.agent.session_manager.list_sessions(
                include_archived=True
            )
        }

        result = await reset_agent_state(self._controller, components=components)

        if result.get("success"):
            # Chats (id "sessions", plus the legacy "conversation" alias):
            # clear transcripts, the action panel, and push the session list
            # so extra chats drop from the sidebar without a refresh.
            chats_reset = (
                components is None
                or "sessions" in components
                or "conversation" in components
            )
            if chats_reset:
                await self._chat.clear()
                await self._action_panel.clear()
                await self._handle_session_list()

            # Tell clients which sessions the reset deleted so the sidebar
            # (and each session's messages/activity/draft state) updates
            # without a page refresh — the frontend session list is
            # server-owned and only reacts to session_* events.
            sessions_after = {
                s.id
                for s in self._controller.agent.session_manager.list_sessions(
                    include_archived=True
                )
            }
            for sid in sessions_before - sessions_after:
                await self._broadcast(
                    {
                        "type": "session_deleted",
                        "data": {"sessionId": sid},
                    }
                )

            # If LivingUI apps were deleted, push refreshed (now-empty) lists so
            # the frontend reflects the deletion. Both the main LivingUI page
            # (living_ui_list) and the Settings > LivingUI page
            # (living_ui_settings_get) cache their own project lists and won't
            # refetch on their own, so we must push to both.
            if components is not None and "livingui" in components:
                await self._handle_living_ui_list()
                await self._handle_living_ui_settings_get()

            await self._broadcast(
                {
                    "type": "reset",
                    "data": {
                        "success": True,
                        "message": result.get("message", "Agent state has been reset."),
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "reset",
                    "data": {
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    # ─────────────────────────────────────────────────────────────────────
    # Skill creation from a session
    # ─────────────────────────────────────────────────────────────────────

    # Workflow ids of CraftBot's internal skill/memory infrastructure runs.
    # Exposed to the frontend via skill_meta so it can hide "Create Skill"
    # affordances on internal workflow activity.
    _INTERNAL_WORKFLOW_IDS = frozenset(
        {
            "skill_creation",
            "skill_improvement",
            "memory_processing",
        }
    )

    # The union of every skill in the repo with `user-invocable: false`.
    # A run whose loaded skills intersect this set is system-spawned;
    # exposed to the frontend via skill_meta.
    _INTERNAL_SKILL_NAMES = frozenset(
        {
            "craftbot-skill-creator",
            "craftbot-skill-improve",
            "memory-processor",
            "heartbeat-processor",
            "user-profile-interview",
            "day-planner",
            "week-planner",
            "month-planner",
        }
    )

    # Names the user may not type into the SkillCreatorModal (validated in
    # _handle_create_skill_from_session). Kept separate from
    # _INTERNAL_SKILL_NAMES because the two answer different questions:
    #   _INTERNAL_SKILL_NAMES → "is this run a system workflow?" (hides the
    #     Create Skill affordance)
    #   _RESERVED_SKILL_NAMES → "is this *name* one the user can claim?"
    #     (modal input validation)
    # The contents happen to coincide today, but a future user-invocable
    # skill that we still don't want overwritten would belong only here,
    # and an internal skill we'd let users replace would belong only in
    # _INTERNAL_SKILL_NAMES — keeping them split avoids a re-split later.
    _RESERVED_SKILL_NAMES = frozenset(
        {
            "craftbot-skill-creator",
            "craftbot-skill-improve",
            "memory-processor",
            "user-profile-interview",
            "heartbeat-processor",
            "day-planner",
            "week-planner",
            "month-planner",
        }
    )

    _SKILL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,63}$")

    def _get_skill_meta(self) -> Dict[str, Any]:
        return {
            "internalWorkflowIds": sorted(self._INTERNAL_WORKFLOW_IDS),
            "internalSkillNames": sorted(self._INTERNAL_SKILL_NAMES),
            "reservedSkillNames": sorted(self._RESERVED_SKILL_NAMES),
        }

    async def _handle_create_skill_from_session(self, data: Dict[str, Any]) -> None:
        """
        Queue a skill-creation/improvement workflow run in the main session,
        using a chat session's transcript as evidence. Writes a per-session
        SKILL_SOURCE markdown file before emitting the trigger.
        """
        response_type = "create_skill_from_session"

        async def _err(msg: str) -> None:
            await self._broadcast(
                {
                    "type": response_type,
                    "data": {"success": False, "error": msg},
                }
            )

        # ---- Validate request shape ----------------------------------
        source_session_id = (data.get("sessionId") or "").strip()
        mode = data.get("mode")
        skill_name_raw = (data.get("skillName") or "").strip()
        target_skill_raw = (data.get("targetSkill") or "").strip()

        if mode == "create":
            workflow_id = "skill_creation"
            workflow_skill = "craftbot-skill-creator"
            target = skill_name_raw
            verb = "Create"
        elif mode == "improve":
            workflow_id = "skill_improvement"
            workflow_skill = "craftbot-skill-improve"
            target = target_skill_raw or skill_name_raw
            verb = "Improve"
        else:
            await _err("invalid_mode")
            return

        if not source_session_id:
            await _err("missing_session_id")
            return
        if not target:
            await _err("missing_skill_name")
            return
        if not self._SKILL_NAME_PATTERN.fullmatch(target):
            await _err("invalid_skill_name")
            return
        if target in self._RESERVED_SKILL_NAMES:
            await _err("reserved_skill_name")
            return

        # ---- Look up source transcript -------------------------------
        # The session's event stream is the durable record of what
        # happened. Prefer the live stream; fall back to the persisted
        # copy in session storage.
        agent = self._controller.agent
        session = agent.session_manager.get(source_session_id)

        head_summary: Optional[str] = None
        records: List[Any] = []
        if agent.event_stream_manager.has_stream(source_session_id):
            stream = agent.event_stream_manager.get_stream_by_id(source_session_id)
            head_summary = stream.head_summary
            records = list(stream.tail_events)
        else:
            try:
                from app.usage.session_storage import get_session_storage

                head_summary, records = get_session_storage().get_event_stream(
                    source_session_id
                )
            except Exception:
                head_summary, records = None, []

        if session is None and not records and not head_summary:
            await _err("source_session_not_found")
            return

        # ---- Skill existence checks ----------------------------------
        skills_dir = Path(__file__).resolve().parents[3] / "skills"
        target_dir = skills_dir / target
        target_skill_md = target_dir / "SKILL.md"

        if mode == "create":
            if target_skill_md.exists():
                await _err("skill_already_exists")
                return
            try:
                from app.ui_layer.settings.skill_settings import get_skill_info

                if get_skill_info(target):
                    await _err("skill_already_exists")
                    return
            except Exception:
                pass
        else:  # improve
            if not target_skill_md.exists():
                await _err("skill_not_found")
                return

        source_md_path: Optional[Path] = None
        try:
            # ---- Build SKILL_SOURCE_<session_id>.md ------------------
            from app.config import AGENT_FILE_SYSTEM_PATH

            source_md_path = (
                Path(AGENT_FILE_SYSTEM_PATH) / f"SKILL_SOURCE_{source_session_id}.md"
            )
            source_md_path.parent.mkdir(parents=True, exist_ok=True)
            existing_skill_md = target_skill_md if mode == "improve" else None
            source_md_path.write_text(
                self._build_skill_source_md(
                    mode=mode,
                    target_skill=target,
                    session_id=source_session_id,
                    session_title=session.title if session else "",
                    head_summary=head_summary,
                    records=records,
                    existing_skill_md=existing_skill_md,
                ),
                encoding="utf-8",
            )

            # ---- Queue the workflow run ------------------------------
            # Use absolute paths in the instruction so the agent can pass
            # them verbatim to read_file / stream_edit. With relative
            # paths the agent has been observed mistakenly prepending the
            # source-file's prefix (`agent_file_system/`), landing the new
            # SKILL.md inside the agent file system instead of `skills/`.
            absolute_source_path = source_md_path.resolve()
            absolute_target_path = target_skill_md.resolve()
            instruction = (
                f"SILENT BACKGROUND TASK — do not message the user.\n"
                f"{verb} skill '{target}'.\n"
                f"Source file (read this — absolute path, use verbatim): {absolute_source_path}\n"
                f"Target file (write the new SKILL.md here — absolute path, use verbatim): {absolute_target_path}\n"
                f"Mode: {mode}\n"
                f"Skill name: {target}\n"
                f"Read the source file, follow the {workflow_skill} skill instructions, "
                f"and write the new skill to the target file (use the absolute target "
                f"path verbatim)."
            )

            from agent_core.core.session import MAIN_SESSION_ID
            from app.triggers import TriggerSource, TriggerSpec

            await agent.trigger_service.emit(
                TriggerSpec(
                    source=TriggerSource.SKILL_WORKFLOW,
                    description=instruction,
                    priority=60,
                    session_id=MAIN_SESSION_ID,
                    payload={
                        "workflow_skills": [workflow_skill],
                        "workflow_action_sets": ["file_operations"],
                        "skill_workflow": {
                            "workflow": workflow_id,
                            "skill_name": target,
                        },
                    },
                )
            )

            # Acknowledge in the chat immediately so the user sees the
            # work being picked up. The agent follows up when the workflow
            # completes (see craftbot-skill-* SKILL.md).
            ack_text = (
                f"Creating skill `{target}` from this session."
                if mode == "create"
                else f"Improving skill `{target}` based on this session."
            )
            try:
                await self._display_chat_message("System", ack_text, "system")
            except Exception as e:
                logger.debug(f"[SKILL_CREATOR] ack chat message failed: {e}")

            await self._broadcast(
                {
                    "type": response_type,
                    "data": {
                        "success": True,
                        "sessionId": source_session_id,
                        "skillName": target,
                        "mode": mode,
                    },
                }
            )
            return

        except Exception as e:
            logger.warning(f"[SKILL_CREATOR] handler failed: {e}", exc_info=True)
            # Best-effort cleanup of the source file we wrote.
            if source_md_path is not None:
                try:
                    source_md_path.unlink()
                except Exception:
                    pass
            await _err(str(e) or "internal_error")
            return

    def _build_skill_source_md(
        self,
        *,
        mode: str,
        target_skill: str,
        session_id: str,
        session_title: str,
        head_summary: Optional[str],
        records: List[Any],
        existing_skill_md: Optional[Path],
    ) -> str:
        """Compose the per-session SKILL_SOURCE markdown file from the
        session's event stream (live or persisted).

        Sections:
          frontmatter (mode, target_skill, source_session_id, generated_at)
          ## Session             — sidebar title
          ## Earlier history     — head_summary, when the stream was rolled up
          ## Event transcript    — every tail event (kind, timestamp, message)
          ## Existing SKILL.md   — verbatim, improve mode only
        """
        FIELD_CAP = 2048
        SUMMARY_CAP = 8192

        def truncate(value: Optional[str], cap: int = FIELD_CAP) -> str:
            if value is None:
                return "(none)"
            text = str(value)
            if len(text) <= cap:
                return text
            return text[:cap] + f"\n…[truncated {len(text) - cap} chars]"

        lines: List[str] = [
            "---",
            f"mode: {mode}",
            f"target_skill: {target_skill}",
            f"source_session_id: {session_id}",
            f"generated_at: {datetime.utcnow().isoformat()}Z",
            "---",
            "",
            "# Source Session Context",
            "",
            "## Session",
            session_title or "(untitled)",
            "",
        ]

        if head_summary:
            lines.extend(
                [
                    "## Earlier history (summarized)",
                    "",
                    truncate(head_summary, SUMMARY_CAP),
                    "",
                ]
            )

        lines.extend(["## Event transcript", ""])

        if not records:
            lines.append("(no recorded events)")
        else:
            for idx, record in enumerate(records, 1):
                ev = record.event
                lines.append(f"### [{idx}] {ev.kind} — {ev.iso_ts}")
                lines.append(truncate(ev.message))
                lines.append("")

        if existing_skill_md is not None:
            lines.append("## Existing SKILL.md")
            lines.append("")
            try:
                existing = existing_skill_md.read_text(encoding="utf-8")
            except Exception as e:
                existing = f"(failed to read: {e})"
            lines.append("```")
            lines.append(existing)
            lines.append("```")

        return "\n".join(lines)

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
            if hasattr(agent, "scheduler") and agent.scheduler:
                scheduler_status = agent.scheduler.get_status()

            await self._broadcast(
                {
                    "type": "scheduler_config_get",
                    "data": {
                        "config": result.get("config"),
                        "status": scheduler_status,
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "scheduler_config_get",
                    "data": {
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

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
                if hasattr(agent, "scheduler") and agent.scheduler:
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
                                    schedule_update["enabled"],
                                )

                # Re-read config for response
                config_result = get_scheduler_config()

                await self._broadcast(
                    {
                        "type": "scheduler_config_update",
                        "data": {
                            "config": config_result.get("config", {}),
                            "success": True,
                        },
                    }
                )
            else:
                await self._broadcast(
                    {
                        "type": "scheduler_config_update",
                        "data": {
                            "success": False,
                            "error": result.get("error", "Unknown error"),
                        },
                    }
                )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "scheduler_config_update",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_proactive_tasks_get(self, frequency: str = None) -> None:
        """Get proactive tasks from PROACTIVE.md."""
        agent = self._controller.agent
        proactive_manager = getattr(agent, "proactive_manager", None)

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

            await self._broadcast(
                {
                    "type": "proactive_tasks_get",
                    "data": {
                        "tasks": tasks_data,
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "proactive_tasks_get",
                    "data": {
                        "tasks": [],
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_proactive_task_add(self, task_data: Dict[str, Any]) -> None:
        """Add a new proactive task."""
        agent = self._controller.agent
        proactive_manager = getattr(agent, "proactive_manager", None)

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
            await self._broadcast(
                {
                    "type": "proactive_task_add",
                    "data": {
                        "taskId": result.get("task", {}).get("id"),
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "proactive_task_add",
                    "data": {
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_proactive_task_update(
        self, task_id: str, updates: Dict[str, Any]
    ) -> None:
        """Update a proactive task."""
        agent = self._controller.agent
        proactive_manager = getattr(agent, "proactive_manager", None)

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
            await self._broadcast(
                {
                    "type": "proactive_task_update",
                    "data": {
                        "taskId": task_id,
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "proactive_task_update",
                    "data": {
                        "taskId": task_id,
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_proactive_task_remove(self, task_id: str) -> None:
        """Remove a proactive task."""
        agent = self._controller.agent
        proactive_manager = getattr(agent, "proactive_manager", None)

        result = remove_recurring_task(proactive_manager, task_id)

        if result.get("success"):
            await self._broadcast(
                {
                    "type": "proactive_task_remove",
                    "data": {
                        "taskId": task_id,
                        "removed": True,
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "proactive_task_remove",
                    "data": {
                        "taskId": task_id,
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_proactive_tasks_reset(self) -> None:
        """Reset all proactive tasks (restore from template)."""
        result = reset_recurring_tasks()

        if result.get("success"):
            # Reload proactive manager
            agent = self._controller.agent
            proactive_manager = getattr(agent, "proactive_manager", None)
            if proactive_manager:
                reload_proactive_manager(proactive_manager)

            await self._broadcast(
                {
                    "type": "proactive_tasks_reset",
                    "data": {
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "proactive_tasks_reset",
                    "data": {
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_proactive_file_read(self) -> None:
        """Read the raw PROACTIVE.md file content."""
        result = read_agent_file("PROACTIVE.md")

        if result.get("success"):
            await self._broadcast(
                {
                    "type": "proactive_file_read",
                    "data": {
                        "content": result.get("content"),
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "proactive_file_read",
                    "data": {
                        "content": None,
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_proactive_mode_get(self) -> None:
        """Get the current proactive mode status."""
        result = get_proactive_mode()

        await self._broadcast(
            {
                "type": "proactive_mode_get",
                "data": {
                    "enabled": result.get("enabled", True),
                    "success": result.get("success", False),
                    "error": result.get("error"),
                },
            }
        )

    async def _handle_proactive_mode_set(self, enabled: bool) -> None:
        """Set the proactive mode on or off."""
        result = set_proactive_mode(enabled)

        await self._broadcast(
            {
                "type": "proactive_mode_set",
                "data": {
                    "enabled": result.get("enabled", enabled),
                    "success": result.get("success", False),
                    "error": result.get("error"),
                },
            }
        )

    # ─────────────────────────────────────────────────────────────────────
    # Memory Operation Handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_memory_mode_get(self) -> None:
        """Get the current memory mode status."""
        result = get_memory_mode()

        await self._broadcast(
            {
                "type": "memory_mode_get",
                "data": {
                    "enabled": result.get("enabled", True),
                    "success": result.get("success", False),
                    "error": result.get("error"),
                },
            }
        )

    async def _handle_memory_mode_set(self, enabled: bool) -> None:
        """Set the memory mode on or off."""
        result = set_memory_mode(enabled)

        await self._broadcast(
            {
                "type": "memory_mode_set",
                "data": {
                    "enabled": result.get("enabled", enabled),
                    "success": result.get("success", False),
                    "error": result.get("error"),
                },
            }
        )

    async def _handle_memory_items_get(self) -> None:
        """Get all memory items from MEMORY.md."""
        result = get_memory_items()

        if result.get("success"):
            await self._broadcast(
                {
                    "type": "memory_items_get",
                    "data": {
                        "items": result.get("items", []),
                        "categories": result.get("categories", []),
                        "count": result.get("count", 0),
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "memory_items_get",
                    "data": {
                        "items": [],
                        "categories": [],
                        "count": 0,
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_memory_item_add(self, category: str, content: str) -> None:
        """Add a new memory item."""
        result = add_memory_item(category=category, content=content)

        if result.get("success"):
            # Update memory index after adding
            agent = self._controller.agent
            if hasattr(agent, "memory_manager"):
                agent.memory_manager.update()

            await self._broadcast(
                {
                    "type": "memory_item_add",
                    "data": {
                        "item": result.get("item"),
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "memory_item_add",
                    "data": {
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_memory_item_update(
        self,
        item_id: str,
        category: str = None,
        content: str = None,
        superseded: bool = None,
    ) -> None:
        """Update an existing memory item."""
        result = update_memory_item(
            item_id=item_id,
            category=category,
            content=content,
            superseded=superseded,
        )

        if result.get("success"):
            # Update memory index after updating
            agent = self._controller.agent
            if hasattr(agent, "memory_manager"):
                agent.memory_manager.update()

            await self._broadcast(
                {
                    "type": "memory_item_update",
                    "data": {
                        "item": result.get("item"),
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "memory_item_update",
                    "data": {
                        "itemId": item_id,
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_memory_item_remove(self, item_id: str) -> None:
        """Remove a memory item."""
        result = remove_memory_item(item_id=item_id)

        if result.get("success"):
            # Update memory index after removing
            agent = self._controller.agent
            if hasattr(agent, "memory_manager"):
                agent.memory_manager.update()

            await self._broadcast(
                {
                    "type": "memory_item_remove",
                    "data": {
                        "itemId": item_id,
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "memory_item_remove",
                    "data": {
                        "itemId": item_id,
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_memory_reset(self) -> None:
        """Reset memory: restore MEMORY.md + ENTITIES.md from template, clear
        unprocessed events, then FORCE-rebuild the index.

        Force rebuild (not incremental update) so every derived cache — the
        ChromaDB chunks, the graph, and the entity embedding collection — is
        reseeded from the reset markdown. An incremental update() would leave
        stale chunks and entity vectors behind.
        """
        result = reset_memory()

        if result.get("success"):
            clear_unprocessed_events()
            reset_entity_registry()

            agent = self._controller.agent
            if hasattr(agent, "memory_manager"):
                agent.memory_manager.index_all(force=True)

            await self._broadcast(
                {
                    "type": "memory_reset",
                    "data": {
                        "success": True,
                    },
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "memory_reset",
                    "data": {
                        "success": False,
                        "error": result.get("error", "Unknown error"),
                    },
                }
            )

    async def _handle_memory_stats_get(self) -> None:
        """Get memory statistics."""
        result = get_memory_stats()

        await self._broadcast(
            {
                "type": "memory_stats_get",
                "data": {
                    "stats": result if result.get("success") else {},
                    "success": result.get("success", False),
                    "error": result.get("error"),
                },
            }
        )

    async def _handle_memory_process_trigger(self) -> None:
        """Manually trigger memory processing."""
        try:
            agent = self._controller.agent

            # Check if memory is enabled
            mode_result = get_memory_mode()
            if not mode_result.get("enabled", True):
                await self._broadcast(
                    {
                        "type": "memory_process_trigger",
                        "data": {
                            "success": False,
                            "error": "Memory is disabled. Enable memory mode first.",
                        },
                    }
                )
                return

            # Same emptiness condition as the MEMORY run pre-check
            # (_prepare_memory_run): with nothing to process the trigger
            # would be silently dropped there — surface that here instead.
            from app.ui_layer.settings.memory_settings import memory_needs_pruning

            if get_unprocessed_event_count() == 0 and not memory_needs_pruning():
                await self._broadcast(
                    {
                        "type": "memory_process_trigger",
                        "data": {
                            "success": False,
                            "error": "No unprocessed events to process.",
                        },
                    }
                )
                return

            # Queue a memory-processing run in the main session. The agent's
            # MEMORY pre-check decides whether there is actually work to do.
            from app.triggers import TriggerSource, TriggerSpec

            await agent.trigger_service.emit(
                TriggerSpec(
                    source=TriggerSource.MEMORY,
                    description="Process unprocessed events into long-term memory",
                    priority=60,
                )
            )

            await self._broadcast(
                {
                    "type": "memory_process_trigger",
                    "data": {
                        "success": True,
                        "message": "Memory processing run queued",
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "memory_process_trigger",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_memory_schedule_get(self) -> None:
        """Send the auto-processing schedule + threshold to the panel."""
        try:
            agent = self._controller.agent
            task = agent.scheduler.get_schedule("memory-processing")
            if task is None:
                await self._broadcast(
                    {
                        "type": "memory_schedule_get",
                        "data": {"success": False, "error": "Schedule not found"},
                    }
                )
                return

            sched = task.schedule
            await self._broadcast(
                {
                    "type": "memory_schedule_get",
                    "data": {
                        "success": True,
                        "schedule": {
                            "hour": (
                                sched.hour
                                if sched.hour is not None
                                else SCHEDULE_HOUR_DEFAULT
                            ),
                            "minute": sched.minute or SCHEDULE_MINUTE_DEFAULT,
                        },
                        "threshold": get_memory_processing_threshold(),
                        "threshold_max": get_memory_processing_threshold_max(),
                        "unprocessed": get_unprocessed_event_count(),
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "memory_schedule_get",
                    "data": {"success": False, "error": str(e)},
                }
            )

    async def _handle_memory_schedule_set(self, data: dict) -> None:
        """Apply the daily auto-processing time + threshold from the panel.

        Auto-processing is daily by design; only the time of day and the
        threshold are configurable. Applied live via update_schedule
        (persists + reschedules next run).
        """
        try:
            agent = self._controller.agent
            set_memory_processing_threshold(
                int(data.get("threshold", PROCESSING_THRESHOLD_DEFAULT))
            )
            expr = memory_schedule_expression(
                hour=int(data.get("hour", SCHEDULE_HOUR_DEFAULT)),
                minute=int(data.get("minute", SCHEDULE_MINUTE_DEFAULT)),
            )
            agent.scheduler.update_schedule(
                "memory-processing", schedule=expr, enabled=True
            )
            await self._broadcast(
                {"type": "memory_schedule_set", "data": {"success": True}}
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "memory_schedule_set",
                    "data": {"success": False, "error": str(e)},
                }
            )

    async def _memory_graph_snapshot(self) -> dict:
        """Graph snapshot (nodes/edges) with the panel's pipeline stats folded in.

        Shared by _handle_memory_graph_get and the per-file index mutations so
        both push an identically shaped graph payload.
        """
        agent = self._controller.agent
        snapshot = await asyncio.to_thread(agent.memory_manager.graph_snapshot)
        stats = snapshot.get("stats", {})
        memory_stats = get_memory_stats()
        if memory_stats.get("success"):
            stats["unprocessed_events"] = memory_stats.get("unprocessed_events", 0)
            stats["memory_item_count"] = memory_stats.get("total_items", 0)
        snapshot["stats"] = stats
        return snapshot

    async def _handle_memory_graph_get(self) -> None:
        """Send the memory graph snapshot (nodes/edges/stats) to the panel."""
        try:
            snapshot = await self._memory_graph_snapshot()

            await self._broadcast(
                {
                    "type": "memory_graph_get",
                    "data": {"success": True, "graph": snapshot},
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "memory_graph_get",
                    "data": {"success": False, "error": str(e)},
                }
            )

    async def _handle_memory_indexed_files_get(self) -> None:
        """Send the indexed-files list and addable candidates."""
        try:
            agent = self._controller.agent
            files = agent.memory_manager.get_index_files_info()
            candidates_result = list_indexable_candidates()
            await self._broadcast(
                {
                    "type": "memory_indexed_files_get",
                    "data": {
                        "success": True,
                        "files": files,
                        "candidates": candidates_result.get("candidates", []),
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "memory_indexed_files_get",
                    "data": {"success": False, "error": str(e)},
                }
            )

    async def _handle_memory_indexed_files_set(self, paths: list) -> None:
        """Replace the extra indexed-files list and re-index."""
        try:
            result = set_memory_indexed_files(paths)
            if not result.get("success"):
                await self._broadcast(
                    {
                        "type": "memory_indexed_files_set",
                        "data": {
                            "success": False,
                            "error": result.get("error", "Unknown error"),
                        },
                    }
                )
                return

            # Re-index so added files appear (and removed files drop out)
            # immediately rather than waiting for the file watcher.
            agent = self._controller.agent
            await asyncio.to_thread(agent.memory_manager.update)

            await self._broadcast(
                {
                    "type": "memory_indexed_files_set",
                    "data": {
                        "success": True,
                        "files": agent.memory_manager.get_index_files_info(),
                        "rejected": result.get("rejected", []),
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "memory_indexed_files_set",
                    "data": {"success": False, "error": str(e)},
                }
            )

    async def _handle_memory_index_file_mutate(self, op: str, path: str) -> None:
        """Add or remove a single indexed file and re-index.

        Additive per-file counterpart to _handle_memory_indexed_files_set.
        Each mutation reads the persisted list fresh, so simultaneous "+"
        clicks (processed serially by the WS loop) each add their own file
        instead of overwriting one another. The response echoes the path so
        the frontend clears only that file's spinner.
        """
        msg_type = f"memory_index_file_{op}"
        try:
            if op == "add":
                result = add_memory_indexed_file(path)
            else:
                result = remove_memory_indexed_file(path)

            if not result.get("success"):
                await self._broadcast(
                    {
                        "type": msg_type,
                        "data": {
                            "success": False,
                            "path": path,
                            "error": result.get("error", "Unknown error"),
                        },
                    }
                )
                return

            # Re-index so the added file appears (or removed file drops out)
            # immediately rather than waiting for the file watcher.
            agent = self._controller.agent
            await asyncio.to_thread(agent.memory_manager.update)

            # Push the fresh graph + file list INSIDE this completion broadcast.
            # The WS loop is serial, so if the panel replied by sending its own
            # memory_graph_get it would queue behind the other still-pending
            # index jobs and only refresh once they all finished. Piggy-backing
            # the snapshot here lets each file appear the moment it's indexed.
            candidates_result = list_indexable_candidates()
            await self._broadcast(
                {
                    "type": msg_type,
                    "data": {
                        "success": True,
                        "path": path,
                        "files": agent.memory_manager.get_index_files_info(),
                        "candidates": candidates_result.get("candidates", []),
                        "graph": await self._memory_graph_snapshot(),
                        "rejected": result.get("rejected", []),
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": msg_type,
                    "data": {"success": False, "path": path, "error": str(e)},
                }
            )

    # ─────────────────────────────────────────────────────────────────────
    # Model Settings Handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_model_providers_get(self) -> None:
        """Get available model providers."""
        try:
            result = get_available_providers()
            await self._broadcast(
                {
                    "type": "model_providers_get",
                    "data": result,
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "model_providers_get",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_model_settings_get(self) -> None:
        """Get current model settings."""
        try:
            result = get_model_settings()
            await self._broadcast(
                {
                    "type": "model_settings_get",
                    "data": result,
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "model_settings_get",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

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
            image_gen_provider = data.get("imageGenProvider")
            video_gen_provider = data.get("videoGenProvider")
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
                    await self._broadcast(
                        {
                            "type": "model_settings_update",
                            "data": {
                                "success": False,
                                "error": "; ".join(errors),
                            },
                        }
                    )
                    return

            # Step 2: Test connection before saving — only when credentials are changing.
            # Mirror the frontend logic: skip the test when only model/provider name
            # changes so that saving works even if the service (e.g. Ollama) is offline.
            # Also skip when the user has a connected subscription for this provider:
            # the OAuth token has its own auth flow, and the connection-test path uses
            # a stored API key shape that wouldn't apply.
            aws_credentials_in = data.get("awsCredentials")
            credentials_changing = bool(api_key or base_url or aws_credentials_in)
            has_active_subscription = False
            if new_provider:
                try:
                    from craftos_integrations.integrations.llm_oauth.tokens import (
                        has_credential as _sub_has,
                    )

                    has_active_subscription = _sub_has(new_provider)
                except Exception:
                    pass
            if new_provider and credentials_changing and not has_active_subscription:
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
                    aws_credentials=aws_credentials_in,
                )
                if not test_result.get("success"):
                    error_msg = test_result.get("error", "Connection test failed")
                    await self._broadcast(
                        {
                            "type": "model_settings_update",
                            "data": {
                                "success": False,
                                "error": f"Connection test failed: {error_msg}",
                            },
                        }
                    )
                    return

            # Capture the current image-gen provider/model BEFORE saving, so a
            # failed reinitialize below can roll the persisted values back and
            # keep settings.json consistent with the still-live interface.
            prev_image_gen_provider = None
            prev_image_gen_model = None
            if image_gen_provider:
                from app.config import (
                    get_image_gen_provider as _get_ig_provider,
                    get_image_gen_model as _get_ig_model,
                )

                prev_image_gen_provider = _get_ig_provider()
                prev_image_gen_model = _get_ig_model()

            prev_video_gen_provider = None
            prev_video_gen_model = None
            if video_gen_provider:
                from app.config import (
                    get_video_gen_provider as _get_vg_provider,
                    get_video_gen_model as _get_vg_model,
                )

                prev_video_gen_provider = _get_vg_provider()
                prev_video_gen_model = _get_vg_model()

            # Step 3: Now save settings (validation and connection test passed)
            result = update_model_settings(
                llm_provider=new_provider,
                vlm_provider=vlm_provider,
                image_gen_provider=image_gen_provider,
                video_gen_provider=video_gen_provider,
                llm_model=data.get("llmModel"),
                vlm_model=data.get("vlmModel"),
                image_gen_model=data.get("imageGenModel"),
                video_gen_model=data.get("videoGenModel"),
                api_key=api_key,
                provider_for_key=provider_for_key,
                base_url=base_url,
                provider_for_url=data.get("providerForUrl"),
                aws_credentials=data.get("awsCredentials"),
            )

            # Reinitialize LLM/VLM with new provider settings
            if result.get("success") and new_provider:
                try:
                    agent = self._controller.agent
                    agent.reinitialize_llm(new_provider)
                    logger.info(
                        f"[BROWSER] LLM reinitialized with provider: {new_provider}"
                    )
                except Exception as e:
                    logger.warning(f"[BROWSER] Failed to reinitialize LLM: {e}")
                    result["warning"] = (
                        f"Settings saved but LLM reinitialization failed: {e}"
                    )

            # Reinitialize image gen interface when its provider changes.
            # Settings are already persisted above, and reinitialize_image_gen
            # only swaps the live interface on success — so if it fails (e.g.
            # the new provider has no API key) we must roll the saved image-gen
            # provider/model back to match the still-live interface. Otherwise
            # settings.json would advertise a provider the running interface
            # can't serve.
            if result.get("success") and image_gen_provider:
                reinit_ok = False
                try:
                    agent = self._controller.agent
                    reinit_ok = agent.reinitialize_image_gen(image_gen_provider)
                except Exception as e:
                    logger.warning(f"[BROWSER] Failed to reinitialize image gen: {e}")

                if reinit_ok:
                    logger.info(
                        f"[BROWSER] Image gen reinitialized with provider: {image_gen_provider}"
                    )
                else:
                    # Roll persisted image-gen settings back to the previous
                    # (still-live) values to avoid a settings/interface mismatch.
                    update_model_settings(
                        image_gen_provider=prev_image_gen_provider,
                        image_gen_model=prev_image_gen_model,
                    )
                    msg = (
                        f"Image generation provider '{image_gen_provider}' could not be "
                        f"initialized — check its API key. Kept '{prev_image_gen_provider}'."
                    )
                    logger.warning(f"[BROWSER] {msg}")
                    result["warning"] = result.get("warning") or msg

            # Reinitialize video gen interface when its provider changes.
            # Mirrors the image gen pattern: roll back on reinit failure.
            if result.get("success") and video_gen_provider:
                reinit_vid_ok = False
                try:
                    agent = self._controller.agent
                    reinit_vid_ok = agent.reinitialize_video_gen(video_gen_provider)
                except Exception as e:
                    logger.warning(f"[BROWSER] Failed to reinitialize video gen: {e}")

                if reinit_vid_ok:
                    logger.info(
                        f"[BROWSER] Video gen reinitialized with provider: {video_gen_provider}"
                    )
                else:
                    update_model_settings(
                        video_gen_provider=prev_video_gen_provider,
                        video_gen_model=prev_video_gen_model,
                    )
                    msg = (
                        f"Video generation provider '{video_gen_provider}' could not be "
                        f"initialized — check its API key. Kept '{prev_video_gen_provider}'."
                    )
                    logger.warning(f"[BROWSER] {msg}")
                    result["warning"] = result.get("warning") or msg

            await self._broadcast(
                {
                    "type": "model_settings_update",
                    "data": result,
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "model_settings_update",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_model_connection_test(
        self,
        provider: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        aws_credentials: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Test connection to a model provider."""
        try:
            result = test_connection(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                aws_credentials=aws_credentials,
            )
            await self._broadcast(
                {
                    "type": "model_connection_test",
                    "data": result,
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "model_connection_test",
                    "data": {
                        "success": False,
                        "message": "Test failed",
                        "provider": provider,
                        "error": str(e),
                    },
                }
            )

    async def _handle_model_validate_save(self, data: Dict[str, Any]) -> None:
        """Validate if model settings can be saved."""
        try:
            result = validate_can_save(
                llm_provider=data.get("llmProvider", "anthropic"),
                vlm_provider=data.get("vlmProvider"),
                api_key=data.get("apiKey"),
                provider_for_key=data.get("providerForKey"),
            )
            await self._broadcast(
                {
                    "type": "model_validate_save",
                    "data": result,
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "model_validate_save",
                    "data": {
                        "success": False,
                        "can_save": False,
                        "errors": [str(e)],
                    },
                }
            )

    async def _handle_ollama_models_get(self, base_url: Optional[str] = None) -> None:
        """Fetch available models from Ollama and broadcast to frontend."""
        try:
            if not base_url:
                settings_data = get_model_settings()
                base_url = settings_data.get("base_urls", {}).get("remote")
            result = get_ollama_models(base_url=base_url)
            await self._broadcast({"type": "ollama_models_get", "data": result})
        except Exception as e:
            await self._broadcast(
                {
                    "type": "ollama_models_get",
                    "data": {"success": False, "models": [], "error": str(e)},
                }
            )

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
            await self._broadcast(
                {
                    "type": "openrouter_models_get",
                    "data": {"success": False, "models": [], "error": str(e)},
                }
            )

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
            await self._broadcast(
                {
                    "type": "openrouter_credits_get",
                    "data": {"success": False, "error": str(e)},
                }
            )

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
            await self._broadcast(
                {
                    "type": "slow_mode_get",
                    "data": {"success": False, "error": str(e)},
                }
            )

    async def _handle_slow_mode_set(self, data: Dict[str, Any]) -> None:
        """Set slow mode on or off."""
        try:
            from app.ui_layer.settings.model_settings import set_slow_mode

            enabled = data.get("enabled", False)
            tpm_limit = data.get("tpmLimit")
            result = set_slow_mode(enabled, tpm_limit)
            await self._broadcast({"type": "slow_mode_set", "data": result})
        except Exception as e:
            await self._broadcast(
                {
                    "type": "slow_mode_set",
                    "data": {"success": False, "error": str(e)},
                }
            )

    # ─────────────────────────────────────────────────────────────────────
    # Subscription OAuth Handlers (ChatGPT Plus/Pro, SuperGrok)
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_model_subscription_connect(self, provider: str) -> None:
        """Launch the OAuth flow for the given provider — opens the user's
        browser, waits for the loopback callback, saves the credential.

        We call ``connect_subscription_async`` directly rather than the sync
        wrapper because we're already inside the adapter's event loop —
        spinning a new loop with ``run_until_complete`` from inside a running
        loop raises ``RuntimeError``. Long-running because the user has to
        complete the browser sign-in; the frontend should show a spinner.

        On success, this handler also makes ``provider`` the active LLM
        provider using the same ``update_model_settings`` + ``reinitialize_llm``
        path that the manual Save flow uses — so "Sign in with X"
        implicitly = "use X" without a separate Save click. The newly-active
        provider is echoed back in ``active_provider`` so the frontend
        dropdown updates immediately.
        """
        try:
            success, message = await connect_subscription_async(provider)
            active_provider = self._activate_provider_via_settings(success, provider)
            status_payload = get_subscription_status(provider)
            await self._broadcast(
                {
                    "type": "model_subscription_connect",
                    "data": {
                        "success": success,
                        "provider": provider,
                        "message": message,
                        "status": status_payload,
                        "active_provider": active_provider,
                    },
                }
            )
        except Exception as e:
            logger.error(f"[BROWSER] subscription connect failed: {e}")
            await self._broadcast(
                {
                    "type": "model_subscription_connect",
                    "data": {
                        "success": False,
                        "provider": provider,
                        "error": str(e),
                    },
                }
            )

    def _activate_provider_via_settings(
        self, connect_success: bool, provider: str
    ) -> Optional[str]:
        """Reuse the manual-Save path to make ``provider`` the active LLM.

        Wraps the exact same two calls the model_settings_update handler
        makes — ``update_model_settings(llm_provider=provider)`` persists
        the switch to settings.json and clears model overrides, then
        ``agent.reinitialize_llm(provider)`` rebuilds the live LLM
        interface. Returns the provider name that was successfully
        activated so the caller can echo it to the frontend, or ``None``
        if either the connect itself failed or reinit raised.
        """
        if not connect_success:
            return None
        try:
            update_model_settings(llm_provider=provider)
            self._controller.agent.reinitialize_llm(provider)
            logger.info(f"[BROWSER] LLM reinitialized with provider: {provider}")
            return provider
        except Exception as e:
            logger.warning(
                f"[BROWSER] Failed to activate provider {provider} after "
                f"subscription connect: {e}"
            )
            return None

    async def _handle_model_subscription_disconnect(self, provider: str) -> None:
        """Remove stored OAuth credentials for the given provider.

        If the disconnected provider is the active LLM, the live interface
        still holds a client authenticated with the (now deleted) OAuth
        bearer, so every call would keep failing with "The OAuth2 access
        token could not be validated" until an app restart. Reinitialize so
        the factory rebuilds the client — falling back to the stored API key
        now that the subscription credential is gone.
        """
        try:
            success, message = disconnect_subscription(provider)
            warning = None
            if success:
                try:
                    from app.ui_layer.settings.provider_settings import (
                        get_current_provider,
                    )

                    if get_current_provider() == provider:
                        self._controller.agent.reinitialize_llm(provider)
                        logger.info(
                            f"[BROWSER] LLM reinitialized with provider {provider} "
                            "after subscription disconnect (API-key mode)"
                        )
                except Exception as e:
                    logger.warning(
                        f"[BROWSER] LLM reinit after {provider} subscription "
                        f"disconnect failed: {e}"
                    )
                    warning = (
                        "Subscription disconnected, but the model could not be "
                        f"reinitialized: {e}"
                    )
            await self._broadcast(
                {
                    "type": "model_subscription_disconnect",
                    "data": {
                        "success": success,
                        "provider": provider,
                        "message": message,
                        "warning": warning,
                        "status": get_subscription_status(provider),
                    },
                }
            )
        except Exception as e:
            logger.error(f"[BROWSER] subscription disconnect failed: {e}")
            await self._broadcast(
                {
                    "type": "model_subscription_disconnect",
                    "data": {
                        "success": False,
                        "provider": provider,
                        "error": str(e),
                    },
                }
            )

    async def _handle_model_subscription_status(self, provider: str) -> None:
        """Return current connection status for a given provider."""
        try:
            status_payload = get_subscription_status(provider)
            await self._broadcast(
                {
                    "type": "model_subscription_status",
                    "data": {
                        "success": True,
                        "provider": provider,
                        "status": status_payload,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "model_subscription_status",
                    "data": {
                        "success": False,
                        "provider": provider,
                        "error": str(e),
                    },
                }
            )

    async def _handle_model_subscription_prepare(self, provider: str) -> None:
        """Open the OAuth browser for paste-back flow. Returns auth URL +
        attempt_id without waiting for loopback — the user will paste the
        code shown on the provider's page into a textbox to finalize."""
        try:
            success, info = await prepare_subscription_async(provider)
            payload = {
                "success": success,
                "provider": provider,
            }
            if success:
                payload["auth_url"] = info.get("auth_url", "")
                payload["attempt_id"] = info.get("attempt_id", "")
            else:
                payload["error"] = info.get("error", "Unknown error")
            await self._broadcast(
                {"type": "model_subscription_prepare", "data": payload}
            )
        except Exception as e:
            logger.error(f"[BROWSER] subscription prepare failed: {e}")
            await self._broadcast(
                {
                    "type": "model_subscription_prepare",
                    "data": {
                        "success": False,
                        "provider": provider,
                        "error": str(e),
                    },
                }
            )

    async def _handle_model_subscription_complete(
        self, provider: str, code: str, attempt_id: Optional[str]
    ) -> None:
        """Finalize the paste-back flow: exchange the user-pasted code for tokens.

        On success, activates ``provider`` as the current LLM the same way
        ``_handle_model_subscription_connect`` does — see
        ``_activate_provider_via_settings``.
        """
        try:
            success, message = complete_subscription(provider, code, attempt_id)
            active_provider = self._activate_provider_via_settings(success, provider)
            await self._broadcast(
                {
                    "type": "model_subscription_complete",
                    "data": {
                        "success": success,
                        "provider": provider,
                        "message": message,
                        "status": get_subscription_status(provider),
                        "active_provider": active_provider,
                    },
                }
            )
        except Exception as e:
            logger.error(f"[BROWSER] subscription complete failed: {e}")
            await self._broadcast(
                {
                    "type": "model_subscription_complete",
                    "data": {
                        "success": False,
                        "provider": provider,
                        "error": str(e),
                    },
                }
            )

    # ─────────────────────────────────────────────────────────────────────
    # MCP Settings Handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_mcp_list(self) -> None:
        """Get list of configured MCP servers."""
        try:
            servers = list_mcp_servers()
            await self._broadcast(
                {
                    "type": "mcp_list",
                    "data": {
                        "success": True,
                        "servers": servers,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "mcp_list",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_mcp_enable(self, name: str) -> None:
        """Enable an MCP server."""
        try:
            success, message = enable_mcp_server(name)
            await self._broadcast(
                {
                    "type": "mcp_enable",
                    "data": {
                        "success": success,
                        "message": message,
                        "name": name,
                    },
                }
            )
            # Refresh the list
            if success:
                await self._handle_mcp_list()
        except Exception as e:
            await self._broadcast(
                {
                    "type": "mcp_enable",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "name": name,
                    },
                }
            )

    async def _handle_mcp_disable(self, name: str) -> None:
        """Disable an MCP server."""
        try:
            success, message = disable_mcp_server(name)
            await self._broadcast(
                {
                    "type": "mcp_disable",
                    "data": {
                        "success": success,
                        "message": message,
                        "name": name,
                    },
                }
            )
            # Refresh the list
            if success:
                await self._handle_mcp_list()
        except Exception as e:
            await self._broadcast(
                {
                    "type": "mcp_disable",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "name": name,
                    },
                }
            )

    async def _handle_mcp_remove(self, name: str) -> None:
        """Remove an MCP server."""
        try:
            success, message = remove_mcp_server(name)
            await self._broadcast(
                {
                    "type": "mcp_remove",
                    "data": {
                        "success": success,
                        "message": message,
                        "name": name,
                    },
                }
            )
            # Refresh the list
            if success:
                await self._handle_mcp_list()
        except Exception as e:
            await self._broadcast(
                {
                    "type": "mcp_remove",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "name": name,
                    },
                }
            )

    async def _handle_mcp_add_json(self, name: str, config: str) -> None:
        """Add an MCP server from JSON configuration."""
        try:
            success, message = add_mcp_server_from_json(name, config)
            await self._broadcast(
                {
                    "type": "mcp_add_json",
                    "data": {
                        "success": success,
                        "message": message,
                        "name": name,
                    },
                }
            )
            # Refresh the list
            if success:
                await self._handle_mcp_list()
        except Exception as e:
            await self._broadcast(
                {
                    "type": "mcp_add_json",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "name": name,
                    },
                }
            )

    async def _handle_mcp_get_env(self, name: str) -> None:
        """Get environment variables for an MCP server."""
        try:
            env_vars = get_server_env_vars(name)
            await self._broadcast(
                {
                    "type": "mcp_get_env",
                    "data": {
                        "success": True,
                        "name": name,
                        "env": env_vars,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "mcp_get_env",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "name": name,
                    },
                }
            )

    async def _handle_mcp_update_env(
        self, name: str, env_key: str, env_value: str
    ) -> None:
        """Update an environment variable for an MCP server."""
        try:
            success, message = update_mcp_server_env(name, env_key, env_value)
            await self._broadcast(
                {
                    "type": "mcp_update_env",
                    "data": {
                        "success": success,
                        "message": message,
                        "name": name,
                        "key": env_key,
                    },
                }
            )
            # Refresh the list to show updated env status
            if success:
                await self._handle_mcp_list()
        except Exception as e:
            await self._broadcast(
                {
                    "type": "mcp_update_env",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "name": name,
                        "key": env_key,
                    },
                }
            )

    # ─────────────────────────────────────────────────────────────────────
    # Skill Settings Handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_command_list(self) -> None:
        """Get list of registered non-skill slash commands for autocomplete."""
        try:
            from app.ui_layer.commands.builtin.skill_invoke import SkillInvokeCommand

            cmds = self._controller.command_registry.list_commands(include_hidden=False)
            commands = [
                {"name": c.name.lstrip("/"), "description": c.description}
                for c in cmds
                if not isinstance(c, SkillInvokeCommand)
            ]
            await self._broadcast(
                {
                    "type": "command_list",
                    "data": {
                        "success": True,
                        "commands": commands,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "command_list",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "commands": [],
                    },
                }
            )

    async def _handle_skill_list(self) -> None:
        """Get list of all skills."""
        try:
            skills = list_skills()
            # Calculate stats
            total = len(skills)
            enabled = sum(1 for s in skills if s.get("enabled", True))

            await self._broadcast(
                {
                    "type": "skill_list",
                    "data": {
                        "success": True,
                        "skills": skills,
                        "total": total,
                        "enabled": enabled,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "skill_list",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "skills": [],
                        "total": 0,
                        "enabled": 0,
                    },
                }
            )

    async def _handle_skill_info(self, name: str) -> None:
        """Get detailed info about a skill."""
        try:
            info = get_skill_info(name)
            if info:
                await self._broadcast(
                    {
                        "type": "skill_info",
                        "data": {
                            "success": True,
                            "name": name,
                            "skill": info,
                        },
                    }
                )
            else:
                await self._broadcast(
                    {
                        "type": "skill_info",
                        "data": {
                            "success": False,
                            "error": f"Skill '{name}' not found",
                            "name": name,
                        },
                    }
                )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "skill_info",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "name": name,
                    },
                }
            )

    async def _handle_skill_enable(self, name: str) -> None:
        """Enable a skill."""
        try:
            success, message = enable_skill(name)
            await self._broadcast(
                {
                    "type": "skill_enable",
                    "data": {
                        "success": success,
                        "message": message,
                        "name": name,
                    },
                }
            )
            # Refresh the list and sync skill commands
            if success:
                await self._handle_skill_list()
                self._controller.sync_skill_commands()
        except Exception as e:
            await self._broadcast(
                {
                    "type": "skill_enable",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "name": name,
                    },
                }
            )

    async def _handle_skill_disable(self, name: str) -> None:
        """Disable a skill."""
        try:
            success, message = disable_skill(name)
            await self._broadcast(
                {
                    "type": "skill_disable",
                    "data": {
                        "success": success,
                        "message": message,
                        "name": name,
                    },
                }
            )
            # Refresh the list and sync skill commands
            if success:
                await self._handle_skill_list()
                self._controller.sync_skill_commands()
        except Exception as e:
            await self._broadcast(
                {
                    "type": "skill_disable",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "name": name,
                    },
                }
            )

    async def _handle_skill_reload(self) -> None:
        """Reload skills from disk."""
        try:
            success, message = reload_skills()
            await self._broadcast(
                {
                    "type": "skill_reload",
                    "data": {
                        "success": success,
                        "message": message,
                    },
                }
            )
            # Refresh the list and sync skill commands
            if success:
                await self._handle_skill_list()
                self._controller.sync_skill_commands()
        except Exception as e:
            await self._broadcast(
                {
                    "type": "skill_reload",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_skill_run(
        self, name: str, args_text: str = "", session_id: str = "main"
    ) -> None:
        """Run a skill by invoking it through the controller."""
        try:
            await self._controller.invoke_skill(
                name, args_text, self._adapter_id, session_id=session_id
            )
            await self._broadcast(
                {
                    "type": "skill_run",
                    "data": {
                        "success": True,
                        "name": name,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "skill_run",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "name": name,
                    },
                }
            )

    async def _handle_skill_install(self, source: str) -> None:
        """Install a skill from path or git URL."""
        try:
            # Check if it's a git URL
            if source.startswith("http") or source.startswith("git@"):
                success, message = install_skill_from_git(source)
            else:
                success, message = install_skill_from_path(source)

            await self._broadcast(
                {
                    "type": "skill_install",
                    "data": {
                        "success": success,
                        "message": message,
                        "source": source,
                    },
                }
            )
            # Refresh the list
            if success:
                await self._handle_skill_list()
        except Exception as e:
            await self._broadcast(
                {
                    "type": "skill_install",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "source": source,
                    },
                }
            )

    async def _handle_skill_create(
        self, name: str, description: str, content: str = ""
    ) -> None:
        """Create a new skill scaffold."""
        try:
            success, message = create_skill_scaffold(
                name, description, content if content else None
            )
            await self._broadcast(
                {
                    "type": "skill_create",
                    "data": {
                        "success": success,
                        "message": message,
                        "name": name,
                    },
                }
            )
            # Refresh the list
            if success:
                await self._handle_skill_list()
        except Exception as e:
            await self._broadcast(
                {
                    "type": "skill_create",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "name": name,
                    },
                }
            )

    async def _handle_skill_template(self, name: str, description: str) -> None:
        """Get a skill template for the given name and description."""
        try:
            template = get_skill_template(name or "my-skill", description)
            await self._broadcast(
                {
                    "type": "skill_template",
                    "data": {
                        "success": True,
                        "template": template,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "skill_template",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_skill_remove(self, name: str) -> None:
        """Remove a skill."""
        try:
            success, message = remove_skill(name)
            await self._broadcast(
                {
                    "type": "skill_remove",
                    "data": {
                        "success": success,
                        "message": message,
                        "name": name,
                    },
                }
            )
            # Refresh the list
            if success:
                await self._handle_skill_list()
        except Exception as e:
            await self._broadcast(
                {
                    "type": "skill_remove",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "name": name,
                    },
                }
            )

    async def _handle_skill_dirs(self) -> None:
        """Get skill search directories."""
        try:
            dirs = get_skill_search_directories()
            await self._broadcast(
                {
                    "type": "skill_dirs",
                    "data": {
                        "success": True,
                        "directories": dirs,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "skill_dirs",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "directories": [],
                    },
                }
            )

    # =====================
    # Integration Handlers
    # =====================

    async def _handle_integration_list(self) -> None:
        """Get list of all integrations with status.

        Uses the v2-merged list: multi-account providers source ``connected``
        and ``accounts`` from the IntegrationSystem (the legacy credential
        file is never written by v2 connects, so the legacy status path
        reports them as disconnected — issue seen with youtube/notion).
        """
        try:
            from app.data.action.integrations._helpers import (
                list_integrations_merged_async,
            )

            integrations = await list_integrations_merged_async()
            # Calculate stats
            total = len(integrations)
            connected = sum(1 for i in integrations if i.get("connected", False))

            await self._broadcast(
                {
                    "type": "integration_list",
                    "data": {
                        "success": True,
                        "integrations": integrations,
                        "total": total,
                        "connected": connected,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "integration_list",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "integrations": [],
                        "total": 0,
                        "connected": 0,
                    },
                }
            )

    # ── multi-account integration helpers ──────────────────────

    @staticmethod
    def _system_for(integration_id: str):
        """Return the IntegrationSystem when it knows this provider id.

        Returns None for legacy integrations (or if bootstrap fails), so
        callers fall back to the legacy path unchanged.
        """
        try:
            from app.integrations import get_system

            system = get_system()
            if system.registry.get(integration_id) is not None:
                return system
        except Exception as e:
            # Loud on purpose: this degrade silently reroutes v2 providers to
            # the LEGACY single-account UI (no Add account, status-parsed
            # rows), which looks like a frontend bug. Never let it hide.
            logger.error(
                f"[INTEGRATIONS] integration-system bootstrap/lookup failed for "
                f"{integration_id}; degrading to legacy path: {e!r}"
            )
        return None

    @staticmethod
    def _accounts_payload(accounts, integration_id: str = "") -> List[Dict[str, Any]]:
        """Serialize AccountInfo objects into the wire shape. whatsapp_web
        rows gain ``sessionState`` (relink CTA / reconnect notice)."""
        try:
            from app.data.action.integrations._helpers import accounts_payload

            return accounts_payload(accounts, integration_id)
        except Exception:
            return [
                {
                    "identity": a.identity,
                    "alias": a.alias,
                    "isPrimary": a.is_primary,
                    "listen": a.listen,
                }
                for a in accounts
            ]

    def _current_accounts(self, integration_id: str) -> Optional[List[Dict[str, Any]]]:
        """Best-effort current account list for error payloads.

        Returns None (NOT []) when the list can't be fetched: the frontend
        treats a present ``accounts`` array as the authoritative state and
        prunes its staged edits against it, so a fabricated empty list would
        blank the Manage modal and silently discard the user's unsaved
        edits. Callers must OMIT the ``accounts`` key when this is None.
        """
        try:
            system = self._system_for(integration_id)
            if system is not None:
                return self._accounts_payload(
                    system.list_accounts(integration_id), integration_id
                )
        except Exception:
            pass
        return None

    @staticmethod
    def _with_accounts(
        data: Dict[str, Any], accounts: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """Attach ``accounts`` only when a real list is available."""
        if accounts is not None:
            data["accounts"] = accounts
        return data

    async def _handle_integration_info(self, integration_id: str) -> None:
        """Get detailed info about an integration.

        Metadata comes from the legacy handler (still the metadata source);
        connection state and accounts come from the IntegrationSystem —
        every integration is multi-account now, so the old
        ``handler.status()`` text-scraping path is gone. A missing
        top-level ``accounts`` key tells the frontend the account list
        couldn't be loaded (it renders a reload hint, never fake rows).
        """
        try:
            from craftos_integrations import get_metadata

            info = get_metadata(integration_id)
            if info:
                managed_accounts: Optional[List[Dict[str, Any]]] = None
                try:
                    system = self._system_for(integration_id)
                    if system is not None:
                        managed_accounts = self._accounts_payload(
                            system.list_accounts(integration_id), integration_id
                        )
                except Exception as e:
                    logger.error(
                        f"[INTEGRATIONS] v2 accounts for {integration_id} "
                        f"unavailable, Manage modal shows reload hint: {e!r}"
                    )
                info["connected"] = bool(managed_accounts)
                info["accounts"] = managed_accounts or []
                data: Dict[str, Any] = {
                    "success": True,
                    "id": integration_id,
                    "integration": info,
                }
                if managed_accounts is not None:
                    data["accounts"] = managed_accounts
                await self._broadcast(
                    {
                        "type": "integration_info",
                        "data": data,
                    }
                )
            else:
                await self._broadcast(
                    {
                        "type": "integration_info",
                        "data": {
                            "success": False,
                            "error": f"Integration '{integration_id}' not found",
                            "id": integration_id,
                        },
                    }
                )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "integration_info",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "id": integration_id,
                    },
                }
            )

    def _notify_agent_integration_event(self, message: str) -> None:
        """Record a UI-initiated integration change in the agent's event stream.

        Connect/disconnect from the settings page happens outside any agent
        run, so without this the agent keeps answering from stale connection
        state until an action fails.
        """
        try:
            from agent_core.core.event_stream.event import EventType

            agent = self._controller.agent
            if agent and agent.event_stream_manager:
                agent.event_stream_manager.log(
                    "system",
                    message,
                    event_type=EventType.SYSTEM,
                    display_message=message,
                    task_id="main",
                )
                agent.state_manager.bump_event_stream()
        except Exception as e:
            logger.debug(f"integration event-stream notify failed: {e}")

    async def _handle_integration_connect_token(
        self, integration_id: str, credentials: Dict[str, str]
    ) -> None:
        """Connect an integration using token/credentials.

        multi-account providers (notion/hubspot/slack manual tokens) validate the token
        the same way the legacy handler login does, then store through the
        IntegrationSystem — never the legacy single-account save. Legacy
        integrations keep the legacy handler path unchanged.
        """
        try:
            v2_system = self._system_for(integration_id)
            if v2_system is not None:
                from app.data.action.integrations._helpers import system_connect_token

                success, message = await asyncio.to_thread(
                    system_connect_token, v2_system, integration_id, credentials
                )
            else:
                success, message = await connect_integration_token(
                    integration_id, credentials
                )
            await self._broadcast(
                {
                    "type": "integration_connect_result",
                    "data": {
                        "success": success,
                        "message": message,
                        "id": integration_id,
                    },
                }
            )
            # Refresh the list on success (listener is started by connect_integration_token)
            if success:
                self._notify_agent_integration_event(
                    f"User connected integration '{integration_id}' from the "
                    f"settings page. {message}"
                )
                await self._handle_integration_list()
        except Exception as e:
            await self._broadcast(
                {
                    "type": "integration_connect_result",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "id": integration_id,
                    },
                }
            )

    async def _handle_integration_connect_oauth(self, integration_id: str) -> None:
        """Start OAuth flow for an integration (non-blocking)."""
        # Cancel any existing OAuth task for this integration
        if integration_id in self._oauth_tasks:
            self._oauth_tasks[integration_id].cancel()

        # Run OAuth in background task so WebSocket message loop stays responsive
        task = asyncio.create_task(self._run_oauth_flow(integration_id))
        self._oauth_tasks[integration_id] = task

    async def _run_oauth_flow(self, integration_id: str) -> None:
        """Execute OAuth flow and broadcast result (runs as background task).

        multi-account providers route through ``IntegrationSystem.add_account`` (the
        multi-account OAuth flow); the broadcast keeps the legacy
        ``integration_connect_result`` shape so the frontend needs no
        changes. Legacy integrations keep the legacy handler login.
        """
        try:
            v2_system = self._system_for(integration_id)
            if v2_system is not None:
                success, message, _accounts = await v2_system.add_account(
                    integration_id
                )
            else:
                success, message = await connect_integration_oauth(integration_id)
            await self._broadcast(
                {
                    "type": "integration_connect_result",
                    "data": {
                        "success": success,
                        "message": message,
                        "id": integration_id,
                    },
                }
            )
            # Refresh the list on success (listener is started by connect_integration_oauth)
            if success:
                self._notify_agent_integration_event(
                    f"User connected integration '{integration_id}' from the "
                    f"settings page. {message}"
                )
                await self._handle_integration_list()
        except asyncio.CancelledError:
            # OAuth was cancelled by user closing the modal
            await self._broadcast(
                {
                    "type": "integration_connect_result",
                    "data": {
                        "success": False,
                        "message": "OAuth cancelled",
                        "id": integration_id,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "integration_connect_result",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "id": integration_id,
                    },
                }
            )
        finally:
            self._oauth_tasks.pop(integration_id, None)

    async def _handle_integration_connect_interactive(
        self, integration_id: str
    ) -> None:
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
            await self._broadcast(
                {
                    "type": "integration_connect_result",
                    "data": {
                        "success": success,
                        "message": message,
                        "id": integration_id,
                    },
                }
            )
            # Refresh the list on success (listener is started by connect_integration_interactive)
            if success:
                self._notify_agent_integration_event(
                    f"User connected integration '{integration_id}' from the "
                    f"settings page. {message}"
                )
                await self._handle_integration_list()
        except asyncio.CancelledError:
            # Interactive flow was cancelled by user closing the modal
            await self._broadcast(
                {
                    "type": "integration_connect_result",
                    "data": {
                        "success": False,
                        "message": "Connection cancelled",
                        "id": integration_id,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "integration_connect_result",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "id": integration_id,
                    },
                }
            )
        finally:
            self._oauth_tasks.pop(integration_id, None)

    async def _handle_integration_connect_cancel(self, integration_id: str) -> None:
        """Cancel an in-progress OAuth/interactive flow."""
        if integration_id in self._oauth_tasks:
            self._oauth_tasks[integration_id].cancel()
            # Result will be broadcast by the cancelled task's CancelledError handler

    async def _handle_integration_disconnect(
        self,
        integration_id: str,
        account_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """Disconnect an integration account.

        Heavy teardown (e.g. WhatsApp bridge ``client.destroy()``) can take
        20+ seconds. We don't want the WS message handler blocked on it —
        the frontend would show stale "connected" state until the teardown
        finishes. So we run the disconnect in a background task and let
        this handler return immediately.

        For providers known to the integrations system:
        - with ``account_id``: remove just that account via the integration system
          (no legacy call — legacy has no notion of a specific account).
        - without ``account_id``: remove ALL accounts, then fall through
          to the legacy disconnect so old cred/config files are cleaned too.
        Legacy integrations take the legacy path unchanged.
        """

        async def _do_disconnect() -> None:
            try:
                system = self._system_for(integration_id)

                if system is not None and account_id:
                    # Targeted removal — handled entirely by the integration
                    # system. Platform teardown (whatsapp_web: server-side
                    # logout + bridge stop + session-dir delete) runs FIRST,
                    # while the account still exists — record removal
                    # triggers a listener reconcile that would race a
                    # trailing teardown on the same bridge.
                    try:
                        from app.data.action.integrations._helpers import (
                            platform_teardown_accounts_async,
                        )

                        identity = await asyncio.to_thread(
                            system.resolve, integration_id, account_id
                        )
                        await platform_teardown_accounts_async(
                            integration_id, [identity]
                        )
                        await asyncio.to_thread(
                            system.remove_account, integration_id, identity
                        )
                        success, message = (
                            True,
                            f"Removed account '{identity}' from {integration_id}",
                        )
                    except Exception as e:
                        success, message = False, str(e)
                    await self._broadcast(
                        {
                            "type": "integration_disconnect_result",
                            "data": self._with_accounts(
                                {
                                    "success": success,
                                    "message": message,
                                    "id": integration_id,
                                    "requestId": request_id,
                                },
                                self._current_accounts(integration_id),
                            ),
                        }
                    )
                    if success:
                        self._notify_agent_integration_event(
                            f"User disconnected account '{account_id}' of "
                            f"integration '{integration_id}' from the settings page."
                        )
                        await self._handle_integration_list()
                    return

                removed: list[str] = []
                if system is not None:
                    # Disconnect-all: drop every account, then fall through
                    # to the legacy disconnect below for file cleanup.
                    # Platform teardown before each record removal — same
                    # ordering rationale as the targeted path above.
                    try:
                        from app.data.action.integrations._helpers import (
                            platform_teardown_accounts_async,
                        )

                        for account in await asyncio.to_thread(
                            system.list_accounts, integration_id
                        ):
                            try:
                                await platform_teardown_accounts_async(
                                    integration_id, [account.identity]
                                )
                                await asyncio.to_thread(
                                    system.remove_account,
                                    integration_id,
                                    account.identity,
                                )
                                removed.append(account.identity)
                            except Exception as e:
                                logger.warning(
                                    f"remove_account {integration_id}/"
                                    f"{account.identity} failed: {e}"
                                )
                    except Exception as e:
                        logger.warning(
                            f"disconnect-all for {integration_id} failed: {e}"
                        )

                success, message = await disconnect_integration(
                    integration_id, account_id
                )
                # Removing the last account also deletes the legacy credential
                # file, so the legacy logout above reports "no credentials
                # found" — a legacy failure must never mask a successful
                # account removal (mirrors _helpers.system_disconnect).
                if removed:
                    success = True
                    message = (
                        f"Disconnected {integration_id}: removed "
                        f"{len(removed)} account(s) ({', '.join(removed)})"
                    )
                await self._broadcast(
                    {
                        "type": "integration_disconnect_result",
                        "data": {
                            "success": success,
                            "message": message,
                            "error": None if success else message,
                            "id": integration_id,
                            "requestId": request_id,
                        },
                    }
                )
                if success:
                    self._notify_agent_integration_event(
                        f"User disconnected integration '{integration_id}' "
                        f"(all accounts) from the settings page."
                    )
                # Always reconcile the list — the frontend flipped the row
                # optimistically and needs the authoritative state either way.
                await self._handle_integration_list()
            except Exception as e:
                await self._broadcast(
                    {
                        "type": "integration_disconnect_result",
                        "data": {
                            "success": False,
                            "error": str(e),
                            "id": integration_id,
                            "requestId": request_id,
                        },
                    }
                )

        asyncio.create_task(_do_disconnect())

    async def _handle_integration_accounts_add(
        self, integration_id: str, request_id: Optional[str] = None
    ) -> None:
        """Add another account to a multi-account integration (real OAuth — the browser
        opens and the flow may take minutes). Runs as a background task so
        the WS message loop stays responsive, mirroring the legacy OAuth
        connect handlers. Result is broadcast as
        ``integration_accounts_add_result``; the frontend correlates via
        ``requestId``.
        """
        # Cancel any in-flight connect/add flow for this integration.
        if integration_id in self._oauth_tasks:
            self._oauth_tasks[integration_id].cancel()

        task = asyncio.create_task(
            self._run_accounts_add(integration_id, request_id)
        )
        self._oauth_tasks[integration_id] = task

    async def _run_accounts_add(
        self, integration_id: str, request_id: Optional[str]
    ) -> None:
        """Execute the add-account OAuth flow and broadcast the result."""
        try:
            from app.integrations import get_system

            system = get_system()
            if system.registry.get(integration_id) is None:
                raise LookupError(f"Unknown integration '{integration_id}'")
            ok, message, accounts = await system.add_account(integration_id)
            await self._broadcast(
                {
                    "type": "integration_accounts_add_result",
                    "data": {
                        "id": integration_id,
                        "requestId": request_id,
                        "ok": bool(ok),
                        "message": message,
                        "accounts": self._accounts_payload(
                            accounts or [], integration_id
                        ),
                    },
                }
            )
            if ok:
                await self._handle_integration_list()
        except asyncio.CancelledError:
            await self._broadcast(
                {
                    "type": "integration_accounts_add_result",
                    "data": self._with_accounts(
                        {
                            "id": integration_id,
                            "requestId": request_id,
                            "ok": False,
                            "message": "Add account cancelled",
                        },
                        self._current_accounts(integration_id),
                    ),
                }
            )
        except Exception as e:
            # Contract note: the add-result failure text travels in "message"
            # (Settings/types.ts IntegrationAccountsAddResult has no "error"
            # field), unlike apply_account_changes_result which uses "error".
            await self._broadcast(
                {
                    "type": "integration_accounts_add_result",
                    "data": self._with_accounts(
                        {
                            "id": integration_id,
                            "requestId": request_id,
                            "ok": False,
                            "message": str(e),
                        },
                        self._current_accounts(integration_id),
                    ),
                }
            )
        finally:
            self._oauth_tasks.pop(integration_id, None)

    async def _handle_integration_apply_account_changes(
        self,
        integration_id: str,
        request_id: Optional[str] = None,
        changes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Apply one batched set of account edits from the Manage modal.

        ``changes`` = {"disconnect": [identity...], "primary": identity|None,
        "aliases": {identity: alias|None}, "listen": {identity: bool}}.
        The integration system applies disconnects → primary → aliases → listen flags
        inside its storage lock. Sync file I/O, so it runs in a thread. On
        failure the frontend keeps its staged edits, so the error payload
        carries the *current* (unchanged) account list.
        """
        try:
            from craftos_integrations.contracts import AccountResolutionError
            from app.integrations import get_system

            system = get_system()
            if system.registry.get(integration_id) is None:
                raise LookupError(f"Unknown integration '{integration_id}'")
            try:
                accounts = await asyncio.to_thread(
                    system.apply_account_changes, integration_id, changes or {}
                )
                # Batched disconnects need the platform-specific teardown too
                # (whatsapp_web: stop the account's bridge, delete its
                # session dir) — core removal only edits the AccountSet.
                try:
                    from app.data.action.integrations._helpers import (
                        platform_teardown_accounts_async,
                    )

                    # Awaited (we're already off the WS handler in a task):
                    # the result broadcast below must reflect completed
                    # teardown, not a fire-and-forget race.
                    await platform_teardown_accounts_async(
                        integration_id, (changes or {}).get("disconnect") or []
                    )
                except Exception as e:
                    logger.warning(
                        f"[INTEGRATIONS] platform teardown after batched "
                        f"disconnect failed for {integration_id}: {e!r}"
                    )
                await self._broadcast(
                    {
                        "type": "integration_apply_account_changes_result",
                        "data": {
                            "id": integration_id,
                            "requestId": request_id,
                            "ok": True,
                            "accounts": self._accounts_payload(
                                accounts, integration_id
                            ),
                        },
                    }
                )
                await self._handle_integration_list()
            except (ValueError, AccountResolutionError) as e:
                await self._broadcast(
                    {
                        "type": "integration_apply_account_changes_result",
                        "data": self._with_accounts(
                            {
                                "id": integration_id,
                                "requestId": request_id,
                                "ok": False,
                                "error": str(e),
                            },
                            self._current_accounts(integration_id),
                        ),
                    }
                )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "integration_apply_account_changes_result",
                    "data": self._with_accounts(
                        {
                            "id": integration_id,
                            "requestId": request_id,
                            "ok": False,
                            "error": str(e),
                        },
                        self._current_accounts(integration_id),
                    ),
                }
            )

    # ==========================
    # Generic per-integration config
    # ==========================
    # Schema-driven: each integration declares ``config_class`` +
    # ``config_fields`` on its handler. These two handlers work for
    # every integration with no per-id branching.

    async def _handle_integration_get_config(self, integration_id: str) -> None:
        """Send the integration's config schema + current values to the frontend."""
        try:
            from craftos_integrations import get_config, get_config_schema, get_metadata

            meta = get_metadata(integration_id)
            if meta is None:
                await self._broadcast(
                    {
                        "type": "integration_config",
                        "data": {
                            "id": integration_id,
                            "success": False,
                            "error": "Unknown integration",
                        },
                    }
                )
                return
            await self._broadcast(
                {
                    "type": "integration_config",
                    "data": {
                        "id": integration_id,
                        "success": True,
                        "schema": get_config_schema(integration_id) or [],
                        "values": get_config(integration_id) or {},
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "integration_config",
                    "data": {
                        "id": integration_id,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_integration_update_config(
        self, integration_id: str, values: dict
    ) -> None:
        """Persist new config values; return the post-write state so the UI can refresh."""
        try:
            from craftos_integrations import get_config, update_config

            ok, message = update_config(integration_id, values or {})
            await self._broadcast(
                {
                    "type": "integration_config_updated",
                    "data": {
                        "id": integration_id,
                        "success": ok,
                        "message": message,
                        "values": get_config(integration_id) if ok else None,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "integration_config_updated",
                    "data": {
                        "id": integration_id,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    # ==========================
    # Living UI Settings Handlers
    # ==========================

    async def _handle_living_ui_settings_get(self) -> None:
        """Get all Living UI projects with their settings."""
        from app.ui_layer.settings.living_ui_settings import get_living_ui_projects

        result = get_living_ui_projects()
        await self._broadcast({"type": "living_ui_settings_get", "data": result})

    async def _handle_living_ui_project_setting_update(
        self, project_id: str, setting: str, value
    ) -> None:
        """Update a per-project setting."""
        from app.ui_layer.settings.living_ui_settings import update_project_setting

        result = update_project_setting(project_id, setting, value)
        await self._broadcast(
            {"type": "living_ui_project_setting_update", "data": result}
        )

    # Backups (spec docs/plans/living-ui-backups-plan.md Phase 4). Thin
    # handlers: all policy lives in the manager/BackupStore. Restore and
    # backup-now run as background tasks (stop+relaunch can take a minute)
    # so the WS loop stays responsive; results broadcast with *_result types.

    async def _handle_living_ui_backups_list(self, project_id: str) -> None:
        from app.living_ui import get_living_ui_manager

        payload = {"projectId": project_id, "backups": [], "totalSize": 0}
        try:
            manager = get_living_ui_manager()
            entries = manager.backups.store.list_backups(project_id)
            payload["backups"] = [
                {
                    "filename": e.filename,
                    "ts": int(e.ts * 1000),
                    "trigger": e.trigger,
                    "size": e.size,
                }
                for e in entries
            ]
            payload["totalSize"] = sum(e.size for e in entries)
        except Exception as e:
            payload["error"] = str(e)
        await self._broadcast({"type": "living_ui_backups_list", "data": payload})

    async def _handle_living_ui_backup_now(self, project_id: str) -> None:
        from app.living_ui import get_living_ui_manager

        async def _run() -> None:
            try:
                result = await get_living_ui_manager().backup_now(project_id)
            except Exception as e:
                result = {"status": "error", "errors": [str(e)]}
            await self._broadcast(
                {
                    "type": "living_ui_backup_now_result",
                    "data": {"projectId": project_id, **result},
                }
            )
            await self._handle_living_ui_backups_list(project_id)

        asyncio.create_task(_run())

    async def _handle_living_ui_backup_restore(
        self, project_id: str, filename: str, source_project_id: str | None = None
    ) -> None:
        """source_project_id: restore an archive from ANOTHER project's
        backup dir (a deleted app's leftovers) into project_id."""
        from app.living_ui import get_living_ui_manager

        async def _run() -> None:
            try:
                result = await get_living_ui_manager().restore_backup(
                    project_id, filename, source_project_id=source_project_id
                )
            except Exception as e:
                result = {"status": "error", "errors": [str(e)]}
            await self._broadcast(
                {
                    "type": "living_ui_backup_restore_result",
                    "data": {"projectId": project_id, "filename": filename, **result},
                }
            )
            await self._handle_living_ui_backups_list(project_id)

        asyncio.create_task(_run())

    async def _handle_living_ui_backup_delete(
        self, project_id: str, filename: str, orphan: bool = False
    ) -> None:
        from app.living_ui import get_living_ui_manager

        data = {"projectId": project_id, "filename": filename, "success": True}
        orphan_reaped = False
        try:
            manager = get_living_ui_manager()
            if orphan:
                # Whole-dir cleanup of a deleted project's leftovers (D5) —
                # refuse if the id is (again) a registered project.
                if project_id in manager.projects:
                    raise ValueError("not an orphan — project exists")
                manager.backups.store.delete_project_backups(project_id)
            else:
                manager.backups.store.delete(project_id, filename)
                # An unregistered (deleted-app) dir whose last archive just
                # went is pure residue (meta.json only) — reap it so the
                # orphan row disappears instead of lingering empty.
                if project_id not in manager.projects and not (
                    manager.backups.store.list_backups(project_id)
                ):
                    manager.backups.store.delete_project_backups(project_id)
                    orphan_reaped = True
        except Exception as e:
            data = {**data, "success": False, "error": str(e)}
        await self._broadcast({"type": "living_ui_backup_delete", "data": data})
        if not orphan:
            await self._handle_living_ui_backups_list(project_id)
        if orphan or orphan_reaped:
            await self._handle_living_ui_settings_get()

    # =====================
    # Playbook Handlers
    # =====================

    async def _handle_playbook_list(self) -> None:
        """Read the bundled playbook catalogue and broadcast it to the client.

        Lookup order mirrors `get_default_picture_path` for read-only bundled
        assets: APP_DATA_PATH first (source mode + writable per-user dir),
        then `_MEIPASS/app/data/playbooks` so packaged builds resolve too.
        """
        candidates = [APP_DATA_PATH / "playbooks" / "catalogue.json"]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(
                Path(meipass) / "app" / "data" / "playbooks" / "catalogue.json"
            )

        catalogue_path: Optional[Path] = next(
            (p for p in candidates if p.exists()), None
        )

        if catalogue_path is None:
            await self._broadcast(
                {
                    "type": "playbook_list",
                    "data": {
                        "success": False,
                        "error": "Playbook catalogue not found.",
                        "playbooks": [],
                    },
                }
            )
            return

        try:
            with open(catalogue_path, "r", encoding="utf-8") as f:
                catalogue = json.load(f)
            await self._broadcast(
                {
                    "type": "playbook_list",
                    "data": {
                        "success": True,
                        "playbooks": catalogue.get("playbooks", []),
                    },
                }
            )
        except Exception as e:
            logger.error(f"[PLAYBOOK] Failed to read catalogue: {e}")
            await self._broadcast(
                {
                    "type": "playbook_list",
                    "data": {
                        "success": False,
                        "error": str(e),
                        "playbooks": [],
                    },
                }
            )

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
            import ssl
            import certifi

            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            req = urllib.request.Request(
                CATALOGUE_URL, headers={"User-Agent": "CraftBot"}
            )
            response = urllib.request.urlopen(req, timeout=15, context=ssl_ctx)
            raw = response.read().decode()
            # Strip trailing commas before ] or } (tolerant of hand-edited JSON)
            raw = _re.sub(r",\s*([}\]])", r"\1", raw)
            catalogue = _json.loads(raw)
            await self._broadcast(
                {
                    "type": "living_ui_marketplace_list",
                    "data": {"success": True, "apps": catalogue.get("apps", [])},
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "living_ui_marketplace_list",
                    "data": {"success": False, "error": str(e), "apps": []},
                }
            )

    async def _handle_marketplace_install(
        self,
        app_id: str,
        app_name: str,
        app_description: str,
        custom_fields: dict = None,
    ) -> None:
        """Install a marketplace app."""
        if not app_id or not app_name:
            await self._broadcast(
                {
                    "type": "living_ui_marketplace_install",
                    "data": {
                        "success": False,
                        "error": "App ID and name are required",
                        "appId": app_id,
                    },
                }
            )
            return

        # Spawn a placeholder tab immediately so the user sees the install is
        # underway (the install itself is synchronous and can take a while).
        # install_from_marketplace adopts this id so the same tab becomes the
        # running app.
        placeholder = self._living_ui_manager.create_placeholder_project(
            app_name, app_description
        )
        project_id = placeholder.id
        await self.broadcast_living_ui_created(placeholder.to_dict())
        await self._broadcast(
            {
                "type": "living_ui_status",
                "data": {
                    "projectId": project_id,
                    "phase": "initializing",
                    "progress": 10,
                    "message": "Installing from marketplace...",
                },
            }
        )

        result = await self._living_ui_manager.install_from_marketplace(
            app_id=app_id,
            app_name=app_name,
            app_description=app_description,
            custom_fields=custom_fields,
            project_id=project_id,
        )

        if result.get("status") == "success":
            # The project already exists as a tab (placeholder adopted) — flip
            # it to running so the iframe loads.
            await self._broadcast(
                {
                    "type": "living_ui_ready",
                    "data": {
                        "projectId": project_id,
                        "url": result.get("url"),
                        "port": result["project"].get("port"),
                        "sessionId": result["project"].get("sessionId"),
                    },
                }
            )

            # Mirror the install into chat as a system message so the request
            # is visible in the conversation (not just the new tab).
            body = f"{app_description}\n\n" if app_description else ""
            try:
                await self._display_chat_message(
                    "System",
                    f"**Living UI: {app_name}**\n\n{body}"
                    "Installed from the marketplace — open it in the new tab.",
                    "system",
                )
            except Exception as e:
                logger.debug(f"[LIVING_UI] marketplace chat message failed: {e}")
        else:
            # Install failed — surface the error on the spawned tab.
            await self._broadcast(
                {
                    "type": "living_ui_error",
                    "data": {
                        "projectId": project_id,
                        "error": result.get("error", "Marketplace install failed"),
                    },
                }
            )

        await self._broadcast(
            {
                "type": "living_ui_marketplace_install",
                "data": {**result, "projectId": project_id, "appId": app_id},
            }
        )

    async def _handle_living_ui_import(self, source: str, name: str) -> None:
        """Import a Living UI from a ZIP, a local folder path, or a git URL
        (one door — LIFECYCLE-PLAN Phase 4). After registering, a
        launch-and-verify run is queued in the project's session so the
        import finishes as a running, verified app without further clicks."""
        if not source:
            return
        # Every outcome is LOGGED and answered with living_ui_import_result:
        # the first live test failed with no server log line and no UI
        # feedback at all (2026-08-05 — "I paste the path and nothing
        # happens"), because failures only broadcast a generic error the
        # already-closed modal never saw.
        logger.info(f"[LIVING_UI] import requested: {source!r} (name={name!r})")
        try:
            project = await self._living_ui_manager.import_project_source(
                source, name or None
            )
            await self.broadcast_living_ui_created(project.to_dict())
            await self._broadcast(
                {
                    "type": "living_ui_import_result",
                    "data": {"success": True, "projectId": project.id},
                }
            )
            try:
                from app.triggers import TriggerSource

                is_ext = getattr(project, "project_type", "native") == "external"
                await self._living_ui_manager.start_development_run(
                    project.id,
                    brief=self._living_ui_manager.post_import_brief(project),
                    trigger_source=TriggerSource.LIVING_UI_IMPORT,
                    workflow_skill=(
                        "living-ui-importer" if is_ext else "living-ui-modify"
                    ),
                    # External adoption is a build-like run: "creating" shows
                    # the construction dock while the agent writes the
                    # pipeline verbs + operations map. Native imports stay
                    # untouched (verify-only).
                    status=("creating" if is_ext else None),
                )
            except Exception as e:
                logger.warning(f"[LIVING_UI] import verify dispatch failed: {e}")
        except Exception as e:
            logger.error(f"[LIVING_UI] import failed for {source!r}: {e}")
            await self._broadcast(
                {
                    "type": "living_ui_import_result",
                    "data": {"success": False, "error": f"Import failed: {e}"},
                }
            )
            await self._broadcast(
                {
                    "type": "living_ui_error",
                    "data": {"projectId": "", "error": f"Import failed: {e}"},
                }
            )
        return

    async def _send_to(self, ws, message: Dict[str, Any]) -> None:
        """Send to one connection (session-scoped flows); falls back to a
        broadcast when the requesting socket is unknown/closed."""
        if ws is not None:
            try:
                await ws.send_json(message)
                return
            except Exception:
                pass
        await self._broadcast(message)

    async def _handle_whatsapp_start_qr(self, ws=None, force: bool = False) -> None:
        """Start a WhatsApp link flow and return the QR to the requesting
        connection only. ``force`` (explicit user click) bypasses the
        just-connected ghost-flow guard."""
        try:
            result = await start_whatsapp_qr_session(force=force)
            await self._send_to(ws, {"type": "whatsapp_qr_result", "data": result})
        except Exception as e:
            await self._send_to(
                ws,
                {
                    "type": "whatsapp_qr_result",
                    "data": {
                        "success": False,
                        "status": "error",
                        "message": str(e),
                    },
                },
            )

    async def _handle_whatsapp_check_status(self, session_id: str, ws=None) -> None:
        """Poll a WhatsApp link flow (states: qr_ready / scanned / promoting /
        connected / timeout / cancelled / error). Idempotent completion —
        a second poller gets the same connected result, and the account
        upsert below is an idempotent write."""
        try:
            result = await check_whatsapp_session_status(session_id)
            # On connect, store the account into the AccountSet — the QR flow
            # itself can't (craftos_integrations never imports the host); the
            # v2 ListenerManager then picks the account up via reconcile.
            if result.get("connected") and result.get("credential"):
                try:
                    from app.integrations import get_system

                    system = get_system()
                    identity = system.store_credential(
                        "whatsapp_web",
                        result.get("identity"),
                        result["credential"],
                    )
                    system.reconcile_listeners()
                    logger.info(
                        f"[INTEGRATIONS] whatsapp_web account '{identity}' "
                        f"stored via QR session {session_id}"
                    )
                except Exception as e:
                    logger.error(
                        f"[INTEGRATIONS] storing whatsapp_web QR account "
                        f"failed (session {session_id}): {e!r}"
                    )
            await self._send_to(ws, {"type": "whatsapp_status_result", "data": result})
            if result.get("connected"):
                # The integrations *list* refresh stays a broadcast — every
                # tab should see the new account.
                await self._handle_integration_list()
        except Exception as e:
            await self._send_to(
                ws,
                {
                    "type": "whatsapp_status_result",
                    "data": {
                        "success": False,
                        "status": "error",
                        "connected": False,
                        "message": str(e),
                    },
                },
            )

    async def _handle_whatsapp_cancel(self, session_id: str, ws=None) -> None:
        """Cancel a WhatsApp link flow."""
        try:
            result = cancel_whatsapp_session(session_id)
            await self._send_to(ws, {"type": "whatsapp_cancel_result", "data": result})
        except Exception as e:
            await self._send_to(
                ws,
                {
                    "type": "whatsapp_cancel_result",
                    "data": {
                        "success": False,
                        "message": str(e),
                    },
                },
            )

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
            await self._broadcast(
                {
                    "type": "chat_message",
                    "data": {
                        "sender": "System",
                        "content": f"[DEBUG ERROR] {error_message}",
                        "style": "error",
                        "timestamp": time.time(),
                        "messageId": f"error:{time.time()}",
                        "sessionId": "main",
                    },
                }
            )
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
            all_files = sorted(
                target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())
            )

            # Apply search filter
            if search:
                search_lower = search.lower()
                all_files = [f for f in all_files if search_lower in f.name.lower()]

            total = len(all_files)

            # Apply pagination
            paginated = all_files[offset : offset + limit]
            files = [self._get_file_info(item) for item in paginated]

            await self._broadcast(
                {
                    "type": "file_list",
                    "data": {
                        "directory": directory,
                        "files": files,
                        "total": total,
                        "hasMore": offset + limit < total,
                        "offset": offset,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
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
                }
            )

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

            await self._broadcast(
                {
                    "type": "file_read",
                    "data": {
                        "path": file_path,
                        "content": content,
                        "isBinary": is_binary,
                        "fileInfo": file_info,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "file_read",
                    "data": {
                        "path": file_path,
                        "content": None,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_file_write(self, file_path: str, content: str) -> None:
        """Write content to a file."""
        try:
            target = self._validate_path(file_path)

            # Ensure parent directory exists
            target.parent.mkdir(parents=True, exist_ok=True)

            target.write_text(content, encoding="utf-8")

            file_info = self._get_file_info(target)

            await self._broadcast(
                {
                    "type": "file_write",
                    "data": {
                        "path": file_path,
                        "fileInfo": file_info,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "file_write",
                    "data": {
                        "path": file_path,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

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

            await self._broadcast(
                {
                    "type": "file_create",
                    "data": {
                        "path": file_path,
                        "fileType": file_type,
                        "fileInfo": file_info,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "file_create",
                    "data": {
                        "path": file_path,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

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

            await self._broadcast(
                {
                    "type": "file_delete",
                    "data": {
                        "path": file_path,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "file_delete",
                    "data": {
                        "path": file_path,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_file_rename(self, old_path: str, new_name: str) -> None:
        """Rename a file or directory."""
        try:
            target = self._validate_path(old_path)

            if not target.exists():
                raise FileNotFoundError(f"Path not found: {old_path}")

            # New path is in the same directory with new name
            new_target = target.parent / new_name

            # Validate new path is still within workspace
            self._validate_path(
                str(new_target.relative_to(Path(AGENT_WORKSPACE_ROOT).resolve()))
            )

            if new_target.exists():
                raise ValueError(f"Target already exists: {new_name}")

            target.rename(new_target)

            file_info = self._get_file_info(new_target)

            await self._broadcast(
                {
                    "type": "file_rename",
                    "data": {
                        "oldPath": old_path,
                        "newPath": str(
                            new_target.relative_to(Path(AGENT_WORKSPACE_ROOT).resolve())
                        ).replace("\\", "/"),
                        "fileInfo": file_info,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "file_rename",
                    "data": {
                        "oldPath": old_path,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_file_batch_delete(self, paths: List[str]) -> None:
        """Delete multiple files/directories."""
        results = []
        for file_path in paths:
            try:
                target = self._validate_path(file_path)

                if not target.exists():
                    results.append(
                        {"path": file_path, "success": False, "error": "Not found"}
                    )
                    continue

                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()

                results.append({"path": file_path, "success": True})
            except Exception as e:
                results.append({"path": file_path, "success": False, "error": str(e)})

        await self._broadcast(
            {
                "type": "file_batch_delete",
                "data": {
                    "results": results,
                    "success": all(r["success"] for r in results),
                },
            }
        )

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

            await self._broadcast(
                {
                    "type": "file_move",
                    "data": {
                        "srcPath": src_path,
                        "destPath": str(
                            dest.relative_to(Path(AGENT_WORKSPACE_ROOT).resolve())
                        ).replace("\\", "/"),
                        "fileInfo": file_info,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "file_move",
                    "data": {
                        "srcPath": src_path,
                        "destPath": dest_path,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

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

            await self._broadcast(
                {
                    "type": "file_copy",
                    "data": {
                        "srcPath": src_path,
                        "destPath": str(
                            dest.relative_to(Path(AGENT_WORKSPACE_ROOT).resolve())
                        ).replace("\\", "/"),
                        "fileInfo": file_info,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "file_copy",
                    "data": {
                        "srcPath": src_path,
                        "destPath": dest_path,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

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

            await self._broadcast(
                {
                    "type": "file_upload",
                    "data": {
                        "path": file_path,
                        "fileInfo": file_info,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "file_upload",
                    "data": {
                        "path": file_path,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

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

            await self._broadcast(
                {
                    "type": "file_download",
                    "data": {
                        "path": file_path,
                        "content": content_b64,
                        "fileInfo": file_info,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "file_download",
                    "data": {
                        "path": file_path,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_chat_history(
        self,
        session_id: str,
        before_timestamp: Optional[float] = None,
        limit: int = 50,
        ws=None,
    ) -> None:
        """Load a session's chat messages (paged) for infinite scroll."""

        async def _reply(payload: Dict[str, Any]) -> None:
            message = {"type": "chat_history", "data": payload}
            if ws is not None:
                await ws.send_json(message)
            else:
                await self._broadcast(message)

        try:
            if before_timestamp is not None:
                messages = self._chat.get_messages_before(
                    before_timestamp, session_id=session_id, limit=limit
                )
            else:
                # Initial page: most recent messages for the session.
                storage = self._chat._storage
                stored = (
                    storage.get_recent_messages(session_id=session_id, limit=limit)
                    if storage
                    else []
                )
                messages = [
                    BrowserChatComponent._stored_to_chat_message(s) for s in stored
                ]

            await _reply(
                {
                    "sessionId": session_id,
                    "messages": [m.to_dict() for m in messages],
                    "hasMore": len(messages) == limit,
                }
            )
        except Exception as e:
            await _reply(
                {
                    "sessionId": session_id,
                    "messages": [],
                    "hasMore": False,
                    "error": str(e),
                }
            )

    async def _handle_chat_message_with_attachments(
        self,
        content: str,
        attachments: List[Dict[str, Any]],
        session_id: str = "main",
        client_id: Optional[str] = None,
    ) -> None:
        """Handle user chat message with attachments."""
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
                    server_path = att.get("serverPath", "")

                    # Save file to workspace (base64 inline) or reference a
                    # file that was already uploaded via HTTP pre-upload.
                    if content_b64:
                        try:
                            file_content = base64.b64decode(content_b64)
                            file_path.write_bytes(file_content)
                            size = len(file_content)
                        except Exception as e:
                            print(
                                f"[BROWSER ADAPTER] Error saving attachment {name}: {e}"
                            )
                            continue
                    elif server_path:
                        # File was pre-uploaded via HTTP; it already lives in
                        # workspace/download/ — use its existing path directly.
                        pre_uploaded = Path(AGENT_WORKSPACE_ROOT) / server_path
                        if not pre_uploaded.exists():
                            print(
                                f"[BROWSER ADAPTER] Pre-uploaded file missing: {server_path}"
                            )
                            continue
                        relative_path = server_path
                        file_path = pre_uploaded
                        size = file_path.stat().st_size
                    else:
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
                    parts.append(
                        f"{name} ({file_type}, {size} B), saved to workspace/{relative_path}"
                    )

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
                session_id=session_id,
                client_id=client_id,
            )
            await self._chat.append_message(user_message)

            # Combine content with attachment info for agent context
            # (This is what the agent sees in the event stream - includes file paths)
            agent_context = content + attachment_note

            if not agent_context.strip():
                return

            # Update state and route to agent directly
            # (Skip submit_message to avoid duplicate chat message)
            self._controller._state_store.dispatch(
                "SET_AGENT_STATE", AgentStateType.WORKING.value
            )

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
                "session_id": session_id,
            }

            await self._controller._agent._handle_chat_message(payload)

        except Exception as e:
            import traceback

            print(
                f"[BROWSER ADAPTER] Error in _handle_chat_message_with_attachments: {e}"
            )
            traceback.print_exc()
            # Still try to display an error message to the user
            error_message = ChatMessage(
                sender="System",
                content=f"Error processing attachment: {str(e)}",
                style="error",
                timestamp=time.time(),
                session_id=session_id,
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
            await self._broadcast(
                {
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
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "chat_attachment_upload",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

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

            await self._broadcast(
                {
                    "type": "agent_profile_picture_upload",
                    "data": result,
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "agent_profile_picture_upload",
                    "data": {
                        "success": False,
                        "error": str(e),
                    },
                }
            )

    async def _handle_agent_profile_picture_remove(self) -> None:
        """Handle removing the custom agent profile picture."""
        from app.ui_layer.settings.general_settings import remove_agent_profile_picture

        try:
            result = remove_agent_profile_picture()
        except Exception as e:
            result = {"success": False, "error": str(e)}

        await self._broadcast(
            {
                "type": "agent_profile_picture_remove",
                "data": result,
            }
        )

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

            await self._broadcast(
                {
                    "type": "open_file",
                    "data": {
                        "path": file_path,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "open_file",
                    "data": {
                        "path": file_path,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

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

            await self._broadcast(
                {
                    "type": "open_folder",
                    "data": {
                        "path": file_path,
                        "success": True,
                    },
                }
            )
        except Exception as e:
            await self._broadcast(
                {
                    "type": "open_folder",
                    "data": {
                        "path": file_path,
                        "success": False,
                        "error": str(e),
                    },
                }
            )

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
        return await self.send_message_with_attachments(
            message, [file_path], sender, style
        )

    async def send_message_with_attachments(
        self,
        message: str,
        file_paths: list,
        sender: Optional[str] = None,
        style: str = "agent",
        session_id: Optional[str] = None,
        continue_work: bool = False,
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
            session_id: The chat session the message belongs to (main default).

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
                    session_id=session_id or "main",
                    continue_work=continue_work,
                )
                await self._chat.append_message(chat_message)

            # If there were errors, send an error message listing them
            if errors:
                error_content = "Failed to attach some files:\n" + "\n".join(
                    f"- {e}" for e in errors
                )
                error_message = ChatMessage(
                    sender="system",
                    content=error_content,
                    style="error",
                    session_id=session_id or "main",
                )
                await self._chat.append_message(error_message)

            # If no attachments succeeded at all, send a general error
            if not attachments and not errors:
                error_message = ChatMessage(
                    sender="system",
                    content="No files provided to attach.",
                    style="error",
                    session_id=session_id or "main",
                )
                await self._chat.append_message(error_message)
                return {
                    "success": False,
                    "files_sent": 0,
                    "errors": ["No files provided to attach."],
                }

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
                session_id=session_id or "main",
            )
            await self._chat.append_message(error_message)
            return {"success": False, "files_sent": 0, "errors": [str(e)]}

    def _get_initial_state(self) -> Dict[str, Any]:
        """Get initial state for new connections."""
        from app.onboarding import onboarding_manager
        from app.ui_layer.settings.general_settings import (
            get_agent_profile_picture_info,
        )

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
            "sessions": [
                self._session_info(s)
                for s in self._controller.agent.session_manager.list_sessions()
            ],
            # Sessions with a run currently in flight — seeds the per-session
            # typing indicator on connect/reload.
            "busySessions": sorted(self._controller.agent.busy_sessions),
            # ChatMessage.to_dict() always carries sessionId.
            "messages": [m.to_dict() for m in self._chat.get_messages()],
            # Recent activity items (per-session inline feed); each carries sessionId.
            "actions": [
                BrowserActionPanelComponent._item_payload(a)
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
            return web.Response(text=self._get_index_html(), content_type="text/html")

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

    async def _agent_profile_picture_handler(
        self, request: "web.Request"
    ) -> "web.Response":
        """Serve the current agent profile picture (user upload or bundled default)."""
        from aiohttp import web

        from app.ui_layer.settings.general_settings import (
            EXT_TO_MIME,
            _user_profile_picture_path,
            get_default_picture_path,
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
            # Falls back to the bundled default (sys._MEIPASS) when the per-user
            # data dir lacks it — e.g. the packaged macOS app (issue #254).
            target = get_default_picture_path()
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
        """Serve files from the workspace directory.

        Pass ?download=1 to force Content-Disposition: attachment (triggers a
        browser Save-As dialog).  Omitting the param keeps 'inline' so chat
        attachment previews continue to work as before.

        Uses web.FileResponse for true streaming — no full-file read into RAM —
        which supports arbitrarily large files and HTTP Range requests.
        """
        from aiohttp import web

        try:
            file_path = request.match_info.get("path", "")

            if not file_path:
                raise web.HTTPNotFound()

            target = self._validate_path(file_path)

            if not target.exists():
                raise web.HTTPNotFound()

            if target.is_dir():
                raise web.HTTPBadRequest(reason="Cannot serve directory")

            disposition = (
                "attachment" if request.rel_url.query.get("download") else "inline"
            )

            return web.FileResponse(
                target,
                headers={
                    "Content-Disposition": f'{disposition}; filename="{target.name}"',
                    "Cache-Control": "no-cache",
                },
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
