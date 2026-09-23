"""Detect changes made outside UI handlers and tell browsers what to refetch.

Three read-only sources, all inside the UI layer
(docs/plans/ui-data-freshness-plan.md, WS-3):

- file watchers on files the agent and background jobs write;
- finished agent actions (``ACTION_END`` → ``action_resources.py``);
- a session run ending (``RUN_STATE_CHANGED`` to idle), which moves the
  session to the top of the sidebar.

Everything goes through ``notify_resource_changed``, which coalesces bursts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, List, Optional

from app.ui_layer.events.action_resources import resource_for_action
from app.ui_layer.events.change_watchers import ChangeWatcher, WatchTarget
from app.ui_layer.events.event_types import UIEvent, UIEventType
from app.ui_layer.events.resource_changes import Resource, notify_resource_changed

Notify = Callable[[Resource, Iterable[str]], None]

# Workspace folders that churn constantly or aren't shown as user files.
WORKSPACE_IGNORE = (
    "sessions",  # per-session EVENT.md logs, rewritten every turn
    ".memory_staging",
    "agent_app",  # Agent App code, pb_data, backups, logs
    "node_modules",
    ".git",
    "__pycache__",
    "pb_data",
)


def workspace_dir_id(root: Path, changed: Path) -> Optional[str]:
    """The workspace-relative folder (posix, "" for the root) a change is in."""
    if changed == root:
        # The OS also reports the root folder itself as modified when a child
        # changes; that's a change to the root listing.
        return ""
    try:
        relative = changed.parent.relative_to(root)
    except ValueError:
        return None
    text = relative.as_posix()
    return "" if text == "." else text


def default_watch_targets() -> List[WatchTarget]:
    """The files and folders the UI caches data from."""
    from app.config import (
        AGENT_FILE_SYSTEM_PATH,
        AGENT_WORKSPACE_ROOT,
        APP_CONFIG_PATH,
        PROJECT_ROOT,
    )

    workspace = Path(AGENT_WORKSPACE_ROOT)
    agent_fs = Path(AGENT_FILE_SYSTEM_PATH)
    config = Path(APP_CONFIG_PATH)
    return [
        WatchTarget(Resource.AGENT_APPS.value, workspace / "agent_app_projects.json"),
        WatchTarget(Resource.AGENT_APPS.value, workspace / "agent_app_instances.json"),
        WatchTarget(Resource.MCP_SERVERS.value, config / "mcp_config.json"),
        WatchTarget(Resource.SKILLS.value, config / "skills_config.json"),
        WatchTarget(Resource.SCHEDULER.value, config / "scheduler_config.json"),
        WatchTarget(Resource.GENERAL_SETTINGS.value, config / "settings.json"),
        WatchTarget(Resource.MODEL_SETTINGS.value, config / "settings.json"),
        WatchTarget(Resource.PROACTIVE.value, agent_fs / "PROACTIVE.md"),
        WatchTarget(Resource.MEMORY.value, agent_fs / "MEMORY.md"),
        WatchTarget(Resource.MEMORY.value, agent_fs / "ENTITIES.md"),
        *(
            WatchTarget(
                Resource.AGENT_FILES.value, agent_fs / name, id_for=lambda p: p.name
            )
            for name in ("USER.md", "AGENT.md", "SOUL.md")
        ),
        WatchTarget(
            Resource.INTEGRATIONS.value,
            Path(PROJECT_ROOT) / ".credentials",
            pattern="*.accounts.json",
        ),
        WatchTarget(
            Resource.WORKSPACE_FILES.value,
            workspace,
            recursive=True,
            debounce=0.5,
            id_for=lambda p: workspace_dir_id(workspace, p),
            ignore=WORKSPACE_IGNORE,
        ),
    ]


class ChangeDetection:
    """Runs the detectors for as long as the browser adapter runs."""

    def __init__(
        self,
        event_bus,
        targets: Optional[List[WatchTarget]] = None,
        notify: Notify = notify_resource_changed,
    ) -> None:
        self._bus = event_bus
        self._targets = targets
        self._notify = notify
        self._watcher: Optional[ChangeWatcher] = None
        self._unsubscribers: List[Callable[[], None]] = []

    def start(self) -> None:
        targets = (
            self._targets if self._targets is not None else default_watch_targets()
        )
        self._watcher = ChangeWatcher(targets, self._on_file_change)
        self._watcher.start()
        self._unsubscribers = [
            self._bus.subscribe(UIEventType.ACTION_END, self._on_action_end),
            self._bus.subscribe(UIEventType.RUN_STATE_CHANGED, self._on_run_state),
        ]

    def stop(self) -> None:
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers = []
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None

    def _on_file_change(self, name: str, ids) -> None:
        self._notify(Resource(name), ids)

    def _on_action_end(self, event: UIEvent) -> None:
        resource = resource_for_action((event.data or {}).get("action_canonical_name"))
        if resource is not None:
            self._notify(resource, ())

    def _on_run_state(self, event: UIEvent) -> None:
        # A finished turn bumps the session's last-active time (sidebar order).
        if (event.data or {}).get("state") == "idle":
            self._notify(Resource.SESSIONS, ())
