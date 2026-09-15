"""Resource change notifications for the browser UI.

When something a view displays may have changed, the UI layer calls
``notify_resource_changed``. Connected browsers receive
``{"type": "resource_changed", "data": {"resource", "ids"}}`` and refetch what
they show (docs/plans/ui-data-freshness-plan.md, §A4.2). Changes are detected
inside the UI layer only; agent code never calls this.

Notifications are thread-safe and coalesced per resource over a short window,
so a burst of status events becomes one refetch.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set, Tuple

COALESCE_SECONDS = 0.2

Broadcast = Callable[[Dict[str, Any]], Awaitable[None]]


class Resource(str, Enum):
    """Server data that browser views cache. Mirrored by the frontend
    ``store/resources`` catalog; extended as views are migrated."""

    AGENT_APPS = "agent_apps"
    SESSIONS = "sessions"
    WORKSPACE_FILES = "workspace_files"  # ids = directory paths
    SKILLS = "skills"  # skill list, skill meta and slash commands
    MCP_SERVERS = "mcp_servers"
    INTEGRATIONS = "integrations"
    PROACTIVE = "proactive"  # recurring tasks and proactive mode
    SCHEDULER = "scheduler"  # scheduler config and the memory-processing schedule
    MEMORY = "memory"  # items, graph, indexed files and memory mode
    AGENT_FILES = "agent_files"  # ids = USER.md / AGENT.md / SOUL.md
    GENERAL_SETTINGS = "general_settings"
    MODEL_SETTINGS = "model_settings"


class ResourceChangeNotifier:
    """Coalesces change notifications and broadcasts them on the event loop."""

    def __init__(self, delay: float = COALESCE_SECONDS) -> None:
        self._delay = delay
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._broadcast: Optional[Broadcast] = None
        # Changed ids per resource; None means "everything".
        self._pending: Dict[Resource, Optional[Set[str]]] = {}
        self._flush_handle: Optional[asyncio.TimerHandle] = None
        self._tasks: Set[asyncio.Task] = set()

    def bind(self, loop: asyncio.AbstractEventLoop, broadcast: Broadcast) -> None:
        """Start delivering notifications through ``broadcast`` on ``loop``."""
        self._loop = loop
        self._broadcast = broadcast

    def unbind(self) -> None:
        """Stop delivering; pending and later notifications are dropped."""
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None
        self._pending.clear()
        self._loop = None
        self._broadcast = None

    def notify(self, resource: Resource, ids: Iterable[str] = ()) -> None:
        """Record that ``resource`` changed (only ``ids`` when given).

        Safe to call from any thread; a no-op until bound.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        # "" is a real id (the workspace root folder); only None is dropped.
        changed = frozenset(str(i) for i in ids if i is not None)
        try:
            on_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            on_loop = False
        if on_loop:
            self._add(resource, changed)
        else:
            loop.call_soon_threadsafe(self._add, resource, changed)

    def _add(self, resource: Resource, ids: frozenset) -> None:
        if self._loop is None:
            return
        if not ids:
            self._pending[resource] = None
        elif resource not in self._pending:
            self._pending[resource] = set(ids)
        elif self._pending[resource] is not None:
            self._pending[resource] |= ids
        if self._flush_handle is None:
            self._flush_handle = self._loop.call_later(self._delay, self._flush)

    def _flush(self) -> None:
        self._flush_handle = None
        pending, self._pending = self._pending, {}
        if self._loop is None or self._broadcast is None:
            return
        for resource, ids in pending.items():
            message = {
                "type": "resource_changed",
                "data": {"resource": resource.value, "ids": sorted(ids) if ids else []},
            }
            task = self._loop.create_task(self._broadcast(message))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)


# Existing broadcasts that mean a resource changed: replies to UI mutations
# and status events (§A4.2 sources 1 and 4). Data-only replies such as
# agent_app_list and *_get / *_list are deliberately absent, since the
# refetch they answer would otherwise trigger another change. Failed
# mutations are mapped too: the refetch reconciles optimistic UI.
_RESOURCE_BY_MESSAGE_TYPE: Dict[str, Resource] = {
    **dict.fromkeys(
        (
            "agent_app_create",
            "agent_app_status",
            "agent_app_ready",
            "agent_app_error",
            "agent_app_launch",
            "agent_app_stop",
            "agent_app_delete",
            "agent_app_project_setting_update",
        ),
        Resource.AGENT_APPS,
    ),
    "session_updated": Resource.SESSIONS,
    **dict.fromkeys(
        (
            "proactive_task_add",
            "proactive_task_update",
            "proactive_task_remove",
            "proactive_tasks_reset",
            "proactive_mode_set",
        ),
        Resource.PROACTIVE,
    ),
    **dict.fromkeys(("scheduler_config_update", "memory_schedule_set"), Resource.SCHEDULER),
    **dict.fromkeys(
        (
            "memory_mode_set",
            "memory_item_add",
            "memory_item_update",
            "memory_item_remove",
            "memory_reset",
            "memory_process_trigger",
        ),
        Resource.MEMORY,
    ),
    **dict.fromkeys(
        (
            "skill_enable",
            "skill_disable",
            "skill_install",
            "skill_create",
            "skill_remove",
            "skill_reload",
        ),
        Resource.SKILLS,
    ),
    **dict.fromkeys(
        ("mcp_enable", "mcp_disable", "mcp_remove", "mcp_add_json", "mcp_update_env"),
        Resource.MCP_SERVERS,
    ),
    **dict.fromkeys(
        (
            "integration_connect_result",
            "integration_disconnect_result",
            "integration_accounts_add_result",
            "integration_apply_account_changes_result",
            "integration_config_updated",
        ),
        Resource.INTEGRATIONS,
    ),
    **dict.fromkeys(
        (
            "model_settings_update",
            "slow_mode_set",
            # Subscription sign-in/out also switches the active provider.
            "model_subscription_connect",
            "model_subscription_disconnect",
            "model_subscription_complete",
        ),
        Resource.MODEL_SETTINGS,
    ),
    "settings_update": Resource.GENERAL_SETTINGS,
    **dict.fromkeys(("agent_file_write", "agent_file_restore", "reset"), Resource.AGENT_FILES),
}

# Messages that change more than their primary resource. A reset restores
# every agent markdown file from templates (the full reset and the "memory"
# component both do), so memory and proactive tasks change with it.
_ALSO_CHANGED_BY_MESSAGE_TYPE: Dict[str, Tuple[Resource, ...]] = {
    "reset": (Resource.MEMORY, Resource.PROACTIVE),
}

# Where a message's payload names the changed item, per resource. Dotted
# paths reach into nested objects; the first non-empty value wins.
_ID_FIELDS: Dict[Resource, Tuple[str, ...]] = {
    Resource.AGENT_APPS: ("projectId", "project.id"),
    Resource.SESSIONS: ("sessionId", "session.id"),
    Resource.PROACTIVE: ("taskId",),
    Resource.MEMORY: ("itemId", "item.id"),
    Resource.SKILLS: ("name",),
    Resource.MCP_SERVERS: ("name",),
    Resource.INTEGRATIONS: ("id",),
    Resource.AGENT_FILES: ("filename",),
}


def _changed_ids(resource: Resource, data: Any) -> List[str]:
    for path in _ID_FIELDS.get(resource, ()):
        value = data
        for key in path.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, str) and value:
            return [value]
    return []


def resource_changes_for_message(message: Dict[str, Any]) -> List[Tuple[Resource, List[str]]]:
    """Every resource (with ids, when known) an outgoing message reports as changed."""
    message_type = message.get("type", "")
    resource = _RESOURCE_BY_MESSAGE_TYPE.get(message_type)
    if resource is None:
        return []
    data = message.get("data")
    resources = (resource, *_ALSO_CHANGED_BY_MESSAGE_TYPE.get(message_type, ()))
    return [(r, _changed_ids(r, data)) for r in resources]


def resource_change_for_message(message: Dict[str, Any]) -> Optional[Tuple[Resource, List[str]]]:
    """The primary resource (and ids, when known) an outgoing message reports as changed.

    Prefer ``resource_changes_for_message``, which also covers messages
    that change several resources (``reset``).
    """
    changes = resource_changes_for_message(message)
    return changes[0] if changes else None


_notifier = ResourceChangeNotifier()


def get_notifier() -> ResourceChangeNotifier:
    """The process-wide notifier the browser adapter binds on start."""
    return _notifier


def notify_resource_changed(resource: Resource, ids: Iterable[str] = ()) -> None:
    """Tell connected browsers that ``resource`` changed. Thread-safe."""
    _notifier.notify(resource, ids)
