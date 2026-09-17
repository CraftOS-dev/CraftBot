"""Tests for the UI resource change notifier (app/ui_layer/events/resource_changes.py)."""

import asyncio
import threading
from pathlib import Path

from app.ui_layer.events.resource_changes import (
    _ALSO_CHANGED_BY_MESSAGE_TYPE,
    _RESOURCE_BY_MESSAGE_TYPE,
    Resource,
    ResourceChangeNotifier,
    resource_change_for_message,
    resource_changes_for_message,
)

ADAPTER_SOURCE = (
    Path(__file__).resolve().parents[1] / "app" / "ui_layer" / "adapters" / "browser_adapter.py"
).read_text(encoding="utf-8")


def _collect(delay=0.05):
    sent = []

    async def broadcast(message):
        sent.append(message)

    return ResourceChangeNotifier(delay=delay), broadcast, sent


def test_unbound_notify_is_a_no_op():
    notifier, _, sent = _collect()
    notifier.notify(Resource.AGENT_APPS, ["a"])
    assert sent == []


def test_burst_is_coalesced_with_ids_unioned():
    async def run():
        notifier, broadcast, sent = _collect()
        notifier.bind(asyncio.get_running_loop(), broadcast)
        notifier.notify(Resource.AGENT_APPS, ["b"])
        notifier.notify(Resource.AGENT_APPS, ["a", "b"])
        await asyncio.sleep(0.15)
        return sent

    sent = asyncio.run(run())
    assert sent == [{"type": "resource_changed", "data": {"resource": "agent_apps", "ids": ["a", "b"]}}]


def test_change_without_ids_means_everything():
    async def run():
        notifier, broadcast, sent = _collect()
        notifier.bind(asyncio.get_running_loop(), broadcast)
        notifier.notify(Resource.AGENT_APPS, ["a"])
        notifier.notify(Resource.AGENT_APPS)
        notifier.notify(Resource.AGENT_APPS, ["b"])
        await asyncio.sleep(0.15)
        return sent

    sent = asyncio.run(run())
    assert [m["data"]["ids"] for m in sent] == [[]]


def test_notify_from_another_thread():
    async def run():
        notifier, broadcast, sent = _collect()
        notifier.bind(asyncio.get_running_loop(), broadcast)
        thread = threading.Thread(target=notifier.notify, args=(Resource.AGENT_APPS, ["x"]))
        thread.start()
        thread.join()
        await asyncio.sleep(0.15)
        return sent

    sent = asyncio.run(run())
    assert sent[0]["data"]["ids"] == ["x"]


def test_separate_bursts_send_separately():
    async def run():
        notifier, broadcast, sent = _collect()
        notifier.bind(asyncio.get_running_loop(), broadcast)
        notifier.notify(Resource.AGENT_APPS, ["a"])
        await asyncio.sleep(0.15)
        notifier.notify(Resource.AGENT_APPS, ["b"])
        await asyncio.sleep(0.15)
        return sent

    assert [m["data"]["ids"] for m in asyncio.run(run())] == [["a"], ["b"]]


def test_unbind_drops_pending():
    async def run():
        notifier, broadcast, sent = _collect()
        notifier.bind(asyncio.get_running_loop(), broadcast)
        notifier.notify(Resource.AGENT_APPS, ["a"])
        notifier.unbind()
        await asyncio.sleep(0.15)
        return sent

    assert asyncio.run(run()) == []


def test_message_mapping():
    assert resource_change_for_message(
        {"type": "agent_app_delete", "data": {"success": True, "projectId": "p1"}}
    ) == (Resource.AGENT_APPS, ["p1"])
    assert resource_change_for_message(
        {"type": "agent_app_create", "data": {"project": {"id": "p2"}}}
    ) == (Resource.AGENT_APPS, ["p2"])
    # Build/launch progress changes nothing in the saved list; refetching on it
    # overwrote the in-flight status an import's page was showing.
    assert resource_change_for_message({"type": "agent_app_status", "data": {}}) is None
    # Data-only replies must not report changes, or refetches would loop.
    assert resource_change_for_message({"type": "agent_app_settings_get", "data": {}}) is None
    assert resource_change_for_message({"type": "agent_app_list", "data": {}}) is None


def test_mutation_replies_map_to_their_resource_with_ids():
    cases = [
        ({"type": "session_updated", "data": {"session": {"id": "s1"}}}, Resource.SESSIONS, ["s1"]),
        ({"type": "proactive_task_remove", "data": {"taskId": "t1", "success": True}}, Resource.PROACTIVE, ["t1"]),
        ({"type": "proactive_mode_set", "data": {"enabled": False}}, Resource.PROACTIVE, []),
        ({"type": "memory_schedule_set", "data": {"success": True}}, Resource.SCHEDULER, []),
        ({"type": "memory_item_add", "data": {"item": {"id": "m1"}}}, Resource.MEMORY, ["m1"]),
        ({"type": "memory_item_remove", "data": {"itemId": "m2"}}, Resource.MEMORY, ["m2"]),
        ({"type": "skill_enable", "data": {"name": "pdf"}}, Resource.SKILLS, ["pdf"]),
        ({"type": "skill_reload", "data": {"success": True}}, Resource.SKILLS, []),
        ({"type": "mcp_remove", "data": {"name": "github"}}, Resource.MCP_SERVERS, ["github"]),
        ({"type": "integration_config_updated", "data": {"id": "slack"}}, Resource.INTEGRATIONS, ["slack"]),
        ({"type": "slow_mode_set", "data": {"success": True}}, Resource.MODEL_SETTINGS, []),
        ({"type": "settings_update", "data": {"settings": {"agentName": "x"}}}, Resource.GENERAL_SETTINGS, []),
        ({"type": "agent_file_write", "data": {"filename": "USER.md"}}, Resource.AGENT_FILES, ["USER.md"]),
    ]
    for message, resource, ids in cases:
        assert resource_change_for_message(message) == (resource, ids), message["type"]


def test_failed_mutations_still_report_a_change():
    # The refetch reconciles optimistic UI after a failure.
    assert resource_change_for_message(
        {"type": "mcp_enable", "data": {"success": False, "error": "x", "name": "a"}}
    ) == (Resource.MCP_SERVERS, ["a"])


def test_reset_reports_every_resource_it_rewrites():
    changes = resource_changes_for_message({"type": "reset", "data": {"success": True}})
    assert changes == [(Resource.AGENT_FILES, []), (Resource.MEMORY, []), (Resource.PROACTIVE, [])]
    assert resource_change_for_message({"type": "reset", "data": {}}) == (Resource.AGENT_FILES, [])
    assert resource_changes_for_message({"type": "skill_list", "data": {}}) == []


def test_no_data_only_reply_is_mapped():
    # *_get / *_list replies answer refetches; mapping one would loop.
    for message_type in _RESOURCE_BY_MESSAGE_TYPE:
        assert not message_type.endswith(("_get", "_list")), message_type


def test_mapped_types_are_broadcast_by_the_adapter():
    for message_type in [*_RESOURCE_BY_MESSAGE_TYPE, *_ALSO_CHANGED_BY_MESSAGE_TYPE]:
        assert f'"type": "{message_type}"' in ADAPTER_SOURCE, message_type
