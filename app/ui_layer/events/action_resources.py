"""Which UI resources an agent action changes.

When an action finishes (``ACTION_END``), views showing what it changed are
refreshed right away (docs/plans/ui-data-freshness-plan.md, WS-3.11). File
watchers catch most of these too; this covers state that isn't file-backed
and avoids waiting for a watcher's debounce. File tools (``write_file``,
``stream_edit``, ``run_shell``) aren't listed: they can touch anything, so
the watchers decide what changed.
"""

from __future__ import annotations

from typing import Dict, Optional

from app.ui_layer.events.resource_changes import Resource

RESOURCE_BY_ACTION: Dict[str, Resource] = {
    # Recurring (proactive) tasks
    "recurring_add": Resource.PROACTIVE,
    "recurring_update_task": Resource.PROACTIVE,
    "recurring_remove": Resource.PROACTIVE,
    # Scheduled tasks
    "schedule_task": Resource.SCHEDULER,
    "schedule_task_toggle": Resource.SCHEDULER,
    "remove_scheduled_task": Resource.SCHEDULER,
    # Integrations
    "connect_integration": Resource.INTEGRATIONS,
    "disconnect_integration": Resource.INTEGRATIONS,
    "manage_integration_account": Resource.INTEGRATIONS,
    # Agent Apps
    "agent_app_scaffold": Resource.AGENT_APPS,
    "agent_app_notify_ready": Resource.AGENT_APPS,
    "agent_app_restart": Resource.AGENT_APPS,
    "agent_app_approve_triggers": Resource.AGENT_APPS,
    "agent_app_marketplace_install": Resource.AGENT_APPS,
    "agent_app_import_zip": Resource.AGENT_APPS,
    "agent_app_import": Resource.AGENT_APPS,
    "agent_app_convert": Resource.AGENT_APPS,
}


def resource_for_action(action_name: Optional[str]) -> Optional[Resource]:
    """The resource a finished action changed, if it's one the UI caches."""
    return RESOURCE_BY_ACTION.get(action_name or "")
