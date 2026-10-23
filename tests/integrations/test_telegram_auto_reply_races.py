"""Concurrency, revocation and merged-message regression tests."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from craftos_integrations.config import ConfigStore
from craftos_integrations.service import get_config, update_config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)


@pytest.mark.parametrize("sender_id", ["", None])
def test_external_message_without_sender_id_cannot_send_as_owner(sender_id):
    from agent_core.core.impl.action.context import current_message_origin
    from app.data.action.integrations.telegram._auto_reply import reply_permission_error

    token = current_message_origin.set(
        {
            "integration_type": "telegram_bot",
            "contact_id": sender_id,
            "is_self_message": False,
            "auto_reply_allowed": False,
        }
    )
    try:
        result = reply_permission_error({"chat_id": "2222", "account": "bot"})
        assert result["status"] == "error"
    finally:
        current_message_origin.reset(token)


@pytest.mark.parametrize("iteration", range(5))
def test_concurrent_contact_additions_do_not_lose_permissions(monkeypatch, iteration):
    import craftos_integrations.service as service
    from app.data.action.integrations.telegram.telegram_auto_reply_actions import (
        set_telegram_contact_auto_reply,
    )

    update_config("telegram_bot", {"self_messages_only": True})
    original = service.get_config

    def slow_read(integration):
        result = original(integration)
        time.sleep(0.005)
        return result

    monkeypatch.setattr(service, "get_config", slow_read)
    contact_ids = [str(1000 + n) for n in range(24)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(
            pool.map(
                lambda cid: set_telegram_contact_auto_reply(
                    {"contact_id": cid, "enabled": True}
                ),
                contact_ids,
            )
        )
    assert all(r["status"] == "success" for r in results), results
    config = get_config("telegram_bot")
    assert set(config["auto_reply_contact_ids"]) == set(contact_ids)
    assert config["self_messages_only"] is True


def test_permission_revoked_after_arrival_blocks_queued_reply(monkeypatch):
    from agent_core.core.impl.action.context import current_message_origin
    from app.data.action.integrations.telegram.telegram_actions import (
        send_telegram_bot_message,
    )
    import app.data.action.integrations._helpers as helpers

    update_config("telegram_bot", {"auto_reply_contact_ids": ["1111"]})
    origin = {
        "platform": "Telegram_bot",
        "integration_type": "telegram_bot",
        "contact_id": "1111",
        "channel_id": "1111",
        "account": "9002",
        "is_self_message": False,
        "auto_reply_allowed": True,
    }
    calls = []

    async def send(*args, **kwargs):
        calls.append(kwargs)
        return {"status": "success", "result": {"message_id": 1}}

    monkeypatch.setattr(helpers, "run_client", send)
    monkeypatch.setattr(helpers, "record_outgoing_message", lambda *args: None)
    update_config("telegram_bot", {"auto_reply_contact_ids": []})
    token = current_message_origin.set(origin)
    try:
        result = asyncio.run(
            send_telegram_bot_message(
                {"chat_id": "1111", "account": "9002", "text": "Hi"}
            )
        )
    finally:
        current_message_origin.reset(token)
    assert result["status"] == "error"
    assert calls == []


@pytest.mark.parametrize(
    "overrides", [{"chat_id": "2222"}, {"account": "9001"}, {"account": None}]
)
def test_auto_reply_cannot_target_another_chat_or_bot(monkeypatch, overrides):
    from agent_core.core.impl.action.context import current_message_origin
    from app.data.action.integrations.telegram.telegram_actions import (
        send_telegram_bot_message,
    )
    import app.data.action.integrations._helpers as helpers

    update_config("telegram_bot", {"auto_reply_contact_ids": ["1111"]})
    calls = []

    async def send(*args, **kwargs):
        calls.append(kwargs)
        return {"status": "success", "result": {"message_id": 1}}

    monkeypatch.setattr(helpers, "run_client", send)
    monkeypatch.setattr(helpers, "record_outgoing_message", lambda *args: None)
    token = current_message_origin.set(
        {
            "integration_type": "telegram_bot",
            "contact_id": "1111",
            "channel_id": "1111",
            "account": "9002",
            "is_self_message": False,
            "auto_reply_allowed": True,
        }
    )
    try:
        result = asyncio.run(
            send_telegram_bot_message(
                {"chat_id": "1111", "account": "9002", "text": "Hi", **overrides}
            )
        )
    finally:
        current_message_origin.reset(token)
    assert result["status"] == "error"
    assert calls == []


def message_trigger(contact_id, account, is_self):
    from agent_core.core.trigger import Trigger
    from app.triggers.sources import TriggerSource

    return Trigger(
        fire_at=time.time(),
        priority=3,
        next_action_description="Incoming Telegram message",
        session_id="main",
        source=TriggerSource.USER_MESSAGE.value,
        payload={
            "platform": "Telegram_bot",
            "integration_type": "telegram_bot",
            "contact_id": contact_id,
            "channel_id": contact_id,
            "account": account,
            "is_self_message": is_self,
            "auto_reply_allowed": not is_self,
            "user_message": "Hi",
        },
    )


def test_merging_messages_preserves_latest_bot_and_third_party_status():
    from app.triggers.runtime import _merge_triggers

    merged = _merge_triggers(
        message_trigger("1111", "9001", True), [message_trigger("2222", "9002", False)]
    )
    assert merged.payload["contact_id"] == "2222"
    assert merged.payload["account"] == "9002"
    assert merged.payload["is_self_message"] is False
    assert merged.payload["auto_reply_allowed"] is True


def test_corrupt_permission_list_does_not_turn_string_into_other_contacts():
    from craftos_integrations.credentials_store import save_config
    from craftos_integrations.providers.telegram_bot.client import TelegramBotConfig
    from app.data.action.integrations.telegram.telegram_auto_reply_actions import (
        set_telegram_contact_auto_reply,
    )

    save_config(
        "telegram_bot_config.json", TelegramBotConfig(auto_reply_contact_ids="1111")
    )
    result = set_telegram_contact_auto_reply({"contact_id": "2222", "enabled": True})
    assert result["status"] == "error"
    assert get_config("telegram_bot")["auto_reply_contact_ids"] == "1111"


def test_stale_settings_form_cannot_overwrite_new_permission():
    update_config("telegram_bot", {"auto_reply_contact_ids": ["1111"]})
    baseline = get_config("telegram_bot")
    update_config("telegram_bot", {"auto_reply_contact_ids": ["1111", "2222"]})
    ok, message = update_config(
        "telegram_bot",
        {"auto_reply_contact_ids": "1111, 3333"},
        expected_values={"auto_reply_contact_ids": baseline["auto_reply_contact_ids"]},
    )
    assert not ok
    assert "changed elsewhere" in message
    assert get_config("telegram_bot")["auto_reply_contact_ids"] == ["1111", "2222"]


def test_settings_edit_of_other_field_preserves_concurrent_contact_addition():
    update_config("telegram_bot", {"auto_reply_contact_ids": ["1111", "2222"]})
    ok, _ = update_config(
        "telegram_bot",
        {"self_messages_only": True},
        expected_values={"self_messages_only": False},
    )
    assert ok
    assert get_config("telegram_bot") == {
        "self_messages_only": True,
        "auto_reply_contact_ids": ["1111", "2222"],
        "self_user_ids": [],
    }


def test_atomic_saves_never_expose_partial_json(monkeypatch):
    import json
    import threading
    import craftos_integrations.credentials_store as storage
    from craftos_integrations.providers.telegram_bot.client import TelegramBotConfig

    update_config("telegram_bot", {"auto_reply_contact_ids": ["1111"]})
    original_dump = storage.json.dump
    errors = []
    stop = threading.Event()

    def slow_dump(obj, stream, **kwargs):
        # Extend the window in which a non-atomic writer would expose a cut.
        text = json.dumps(obj, **kwargs)
        middle = len(text) // 2
        stream.write(text[:middle])
        stream.flush()
        time.sleep(0.002)
        stream.write(text[middle:])

    def reader():
        while not stop.is_set():
            try:
                config = storage.load_config(
                    "telegram_bot_config.json", TelegramBotConfig
                )
                assert config is not None
                assert len(config.auto_reply_contact_ids) == 1
                assert config.auto_reply_contact_ids[0].isdecimal()
            except Exception as exc:
                errors.append(str(exc))

    monkeypatch.setattr(storage.json, "dump", slow_dump)
    worker = threading.Thread(target=reader)
    worker.start()
    try:
        for n in range(30):
            assert update_config(
                "telegram_bot", {"auto_reply_contact_ids": [str(1000 + n)]}
            )[0]
    finally:
        stop.set()
        worker.join(timeout=5)
        monkeypatch.setattr(storage.json, "dump", original_dump)
    assert not worker.is_alive()
    assert errors == []


@pytest.mark.parametrize(
    "contacts", ["Tham", "@tham", "-1111", "0", "01111", "١١١١", "1" * 5000, [True]]
)
def test_settings_reject_invalid_contact_ids_without_erasing_saved_permissions(
    contacts,
):
    update_config("telegram_bot", {"auto_reply_contact_ids": ["1111"]})
    ok, message = update_config("telegram_bot", {"auto_reply_contact_ids": contacts})
    assert not ok
    assert "numeric Telegram user IDs" in message
    assert get_config("telegram_bot")["auto_reply_contact_ids"] == ["1111"]


def test_duplicate_update_does_not_emit_or_regress_poll_offset():
    from craftos_integrations.providers.telegram_bot.provider import TelegramBotProvider

    messages = []
    client = TelegramBotProvider().build_client({}, lambda c: None)

    async def callback(msg):
        messages.append(msg)

    client._message_callback = callback
    update = {
        "update_id": 77,
        "message": {
            "text": "Hi",
            "from": {"id": 1111},
            "chat": {"id": 1111, "type": "private"},
        },
    }
    asyncio.run(client._process_update(update))
    asyncio.run(client._process_update(update))
    asyncio.run(client._process_update({**update, "update_id": 76}))
    assert len(messages) == 1
    assert client._poll_offset == 78


@pytest.mark.parametrize("stop_first", [True, False])
def test_end_turn_cannot_discard_a_telegram_reply(stop_first):
    from types import SimpleNamespace
    from agent_core.core.impl.action.router import ActionRouter

    definitions = {
        "end_turn": SimpleNamespace(parallelizable=False, mode="ALL"),
        "send_telegram_bot_message": SimpleNamespace(parallelizable=True, mode="ALL"),
    }
    router = SimpleNamespace(
        action_library=SimpleNamespace(
            retrieve_action=lambda name: definitions.get(name)
        )
    )
    send = {
        "action_name": "send_telegram_bot_message",
        "parameters": {"chat_id": "1111", "text": "Hi"},
    }
    stop = {"action_name": "end_turn", "parameters": {}}
    actions = [stop, send] if stop_first else [send, stop]
    validated = ActionRouter._validate_parallel_actions(router, actions, GUI_mode=False)
    assert validated == [send]


@pytest.mark.parametrize("success", [True, False])
def test_auto_reply_ends_run_only_after_successful_delivery(monkeypatch, success):
    from agent_core.core.impl.action.context import current_message_origin
    from app.data.action.integrations.telegram.telegram_actions import (
        send_telegram_bot_message,
    )
    import app.data.action.integrations._helpers as helpers

    update_config("telegram_bot", {"auto_reply_contact_ids": ["1111"]})

    async def send(*args, **kwargs):
        return (
            {"status": "success", "result": {"message_id": 1}}
            if success
            else {"status": "error", "message": "API unavailable"}
        )

    monkeypatch.setattr(helpers, "run_client", send)
    monkeypatch.setattr(helpers, "record_outgoing_message", lambda *args: None)
    token = current_message_origin.set(
        {
            "integration_type": "telegram_bot",
            "contact_id": "1111",
            "channel_id": "1111",
            "account": "9002",
            "is_self_message": False,
            "auto_reply_allowed": True,
        }
    )
    try:
        result = asyncio.run(
            send_telegram_bot_message(
                {"chat_id": "1111", "account": "9002", "text": "Hi"}
            )
        )
    finally:
        current_message_origin.reset(token)
    assert result.get("end_turn", False) is success


def test_pending_messages_from_other_contacts_bots_or_owner_stay_queued():
    from agent_core.core.impl.trigger.session_queue import SessionTriggerQueue
    from app.triggers.runtime import _compatible_message_origins

    async def scenario():
        queue = SessionTriggerQueue("main")
        base = message_trigger("1111", "9001", False)
        same = message_trigger("1111", "9001", False)
        other_contact = message_trigger("2222", "9001", False)
        other_bot = message_trigger("1111", "9002", False)
        owner = message_trigger("1111", "9001", True)
        for trigger in (same, other_contact, other_bot, owner):
            await queue.put(trigger)
        batch = await queue.pop_due_batch(
            predicate=lambda other: _compatible_message_origins(base, other)
        )
        assert batch == [same]
        assert [await queue.get(), await queue.get(), await queue.get()] == [
            other_contact,
            other_bot,
            owner,
        ]

    asyncio.run(scenario())


def test_config_ui_receipts_keep_request_identity(monkeypatch):
    from types import SimpleNamespace
    from app.ui_layer.adapters.browser_adapter import BrowserAdapter

    receipts = []

    async def broadcast(message):
        receipts.append(message)

    adapter = SimpleNamespace(_broadcast=broadcast)
    asyncio.run(
        BrowserAdapter._handle_integration_get_config(
            adapter, "telegram_bot", "tab-a-read"
        )
    )
    asyncio.run(
        BrowserAdapter._handle_integration_update_config(
            adapter,
            "telegram_bot",
            {"auto_reply_contact_ids": ["1111"]},
            {"auto_reply_contact_ids": []},
            "tab-a-save",
        )
    )
    assert [r["data"]["requestId"] for r in receipts] == ["tab-a-read", "tab-a-save"]
    assert all(r["data"]["success"] for r in receipts)


@pytest.mark.parametrize("text", ["4", "0", "https://example.com", "Hello there"])
def test_short_outgoing_reply_remains_visible_markdown(monkeypatch, text):
    from types import SimpleNamespace
    from app.internal_action_interface import InternalActionInterface
    from app.data.action.integrations._helpers import record_outgoing_message

    recorded = []
    monkeypatch.setattr(
        InternalActionInterface,
        "state_manager",
        SimpleNamespace(
            record_agent_message=lambda message, **kwargs: recorded.append(message)
        ),
    )
    record_outgoing_message("Telegram", "1111", text)
    assert recorded == [f"Sent via Telegram to 1111:\n\n{text}"]
    assert not recorded[0].startswith("[Sent via")
