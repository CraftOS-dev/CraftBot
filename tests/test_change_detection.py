"""Tests for UI-layer change detection (app/ui_layer/events/change_detection.py)."""

import time
from pathlib import Path

from app.ui_layer.events.action_resources import RESOURCE_BY_ACTION
from app.ui_layer.events.change_detection import (
    ChangeDetection,
    default_watch_targets,
    workspace_dir_id,
)
from app.ui_layer.events.change_watchers import WatchTarget
from app.ui_layer.events.event_bus import EventBus
from app.ui_layer.events.event_types import UIEvent, UIEventType
from app.ui_layer.events.resource_changes import Resource


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, resource, ids):
        self.calls.append((resource, set(ids)))


def test_action_end_maps_to_resource():
    bus, rec = EventBus(), Recorder()
    detection = ChangeDetection(bus, targets=[], notify=rec)
    detection.start()
    try:
        bus.emit(UIEvent(type=UIEventType.ACTION_END, data={"action_canonical_name": "recurring_add"}))
        bus.emit(UIEvent(type=UIEventType.ACTION_END, data={"action_canonical_name": "write_file"}))
    finally:
        detection.stop()
    assert rec.calls == [(Resource.PROACTIVE, set())]


def test_run_ending_refreshes_sessions_and_stop_unsubscribes():
    bus, rec = EventBus(), Recorder()
    detection = ChangeDetection(bus, targets=[], notify=rec)
    detection.start()
    bus.emit(UIEvent(type=UIEventType.RUN_STATE_CHANGED, data={"session_id": "s", "state": "running"}))
    bus.emit(UIEvent(type=UIEventType.RUN_STATE_CHANGED, data={"session_id": "s", "state": "idle"}))
    detection.stop()
    bus.emit(UIEvent(type=UIEventType.RUN_STATE_CHANGED, data={"session_id": "s", "state": "idle"}))
    assert rec.calls == [(Resource.SESSIONS, set())]


def test_file_change_notifies_named_resource(tmp_path: Path):
    config = tmp_path / "mcp_config.json"
    config.write_text("{}")
    bus, rec = EventBus(), Recorder()
    detection = ChangeDetection(bus, targets=[WatchTarget("mcp_servers", config, debounce=0.2)], notify=rec)
    detection.start()
    try:
        time.sleep(0.3)
        config.write_text('{"a": 1}')
        end = time.monotonic() + 5
        while not rec.calls and time.monotonic() < end:
            time.sleep(0.05)
    finally:
        detection.stop()
    assert rec.calls == [(Resource.MCP_SERVERS, set())]


def test_workspace_dir_id(tmp_path: Path):
    assert workspace_dir_id(tmp_path, tmp_path) == ""
    assert workspace_dir_id(tmp_path, tmp_path / "a.txt") == ""
    assert workspace_dir_id(tmp_path, tmp_path / "docs" / "x" / "a.txt") == "docs/x"
    assert workspace_dir_id(tmp_path, Path("C:/elsewhere/a.txt")) is None


def test_default_targets_use_known_resources():
    names = {t.name for t in default_watch_targets()}
    for name in names:
        Resource(name)  # raises if a target names an unknown resource


def test_mapped_actions_exist_in_registry():
    from agent_core.core.action_framework.loader import load_actions_from_directories
    from agent_core.core.action_framework.registry import registry_instance
    from app.config import PROJECT_ROOT

    load_actions_from_directories(base_dir=str(PROJECT_ROOT), paths_to_scan=["app/data/action"])
    registered = set(registry_instance.list_all_actions().keys())
    missing = sorted(set(RESOURCE_BY_ACTION) - registered)
    assert missing == [], f"mapped actions not in the registry: {missing}"
