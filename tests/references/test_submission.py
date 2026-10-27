"""Exercise the real browser submission path against disposable storage."""

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.ui_layer.adapters.browser_adapter import BrowserAdapter, BrowserChatComponent
from app.usage.chat_storage import ChatStorage, StoredChatMessage


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    import app.ui_layer.adapters.browser_adapter as module

    monkeypatch.setattr(module, "AGENT_WORKSPACE_ROOT", tmp_path)
    storage = ChatStorage(str(tmp_path / "chat.db"))
    storage.insert_message(
        StoredChatMessage(
            "source-message",
            "agent",
            "Use the blue theme",
            "agent",
            1,
            session_id="source",
        )
    )
    sessions = {key: SimpleNamespace(id=key, title=key) for key in ("dest", "source")}
    agent = SimpleNamespace(
        session_manager=SimpleNamespace(get=sessions.get),
        _handle_chat_message=AsyncMock(),
    )
    result = BrowserAdapter.__new__(BrowserAdapter)
    result._controller = SimpleNamespace(
        agent=agent, _agent=agent, _state_store=Mock(), _event_bus=Mock()
    )
    result._adapter_id = "browser"
    result._agent_app_manager = SimpleNamespace(get_project=lambda key: None)
    result._answer_shown_question = AsyncMock(return_value=None)
    result._send_to = AsyncMock()
    result._broadcast = AsyncMock()
    chat = BrowserChatComponent.__new__(BrowserChatComponent)
    chat._adapter, chat._storage, chat._messages, chat._trim_at = (
        result,
        storage,
        [],
        500,
    )
    chat._db = ThreadPoolExecutor(max_workers=1)
    result._chat = chat
    yield result, storage, agent
    chat._db.shutdown()


def test_reference_only_is_persisted_echoed_and_queued_once(adapter):
    browser, storage, agent = adapter
    asyncio.run(
        browser._handle_chat_message_with_attachments(
            "",
            [],
            "dest",
            "client-1",
            [{"kind": "session", "targetId": "source"}],
        )
    )
    assert agent._handle_chat_message.await_count == 1
    payload = agent._handle_chat_message.call_args.args[0]
    assert payload["session_id"] == "dest" and payload["strict_session"]
    assert "Use the blue theme" in payload["text"]
    message = storage.get_recent_messages("dest")[0]
    assert message.content == "Referenced: source"
    assert "Use the blue theme" not in message.content
    assert message.references[0]["targetId"] == "source"
    echo = browser._broadcast.call_args.args[0]["data"]
    assert echo["references"] == message.references and echo["clientId"] == "client-1"
    assert (
        BrowserChatComponent._stored_to_chat_message(message).to_dict()["references"]
        == message.references
    )


def test_attachment_and_reference_share_one_submission(adapter):
    browser, storage, agent = adapter
    asyncio.run(
        browser._handle_chat_message_with_attachments(
            "/compare this",
            [
                {
                    "name": "notes.txt",
                    "type": "text/plain",
                    "size": 5,
                    "content": base64.b64encode(b"hello").decode(),
                }
            ],
            "dest",
            "client-2",
            [{"kind": "session", "targetId": "source"}],
        )
    )
    message = storage.get_recent_messages("dest")[0]
    assert message.content == "/compare this"
    assert len(message.attachments) == len(message.references) == 1
    payload = agent._handle_chat_message.call_args.args[0]["text"]
    assert "ATTACHMENTS:" in payload and "REFERENCE CONTEXT" in payload
    assert agent._handle_chat_message.await_count == 1


@pytest.mark.parametrize(
    "destination,target", [("dest", "missing"), ("missing", "source")]
)
def test_missing_source_or_destination_rejects_before_acceptance(
    adapter, destination, target
):
    browser, storage, agent = adapter
    asyncio.run(
        browser._handle_chat_message_with_attachments(
            "Compare",
            [],
            destination,
            "client-3",
            [{"kind": "session", "targetId": target}],
        )
    )
    assert storage.get_recent_messages(destination) == []
    agent._handle_chat_message.assert_not_awaited()
    rejection = browser._send_to.call_args.args[1]
    assert rejection["type"] == "message_rejected"
    assert rejection["data"]["clientId"] == "client-3"


def test_storage_failure_does_not_accept_or_run_reference(adapter, monkeypatch):
    browser, _, agent = adapter
    monkeypatch.setattr(
        browser._chat._storage, "insert_message", Mock(side_effect=OSError("disk full"))
    )
    asyncio.run(
        browser._handle_chat_message_with_attachments(
            "Compare",
            [],
            "dest",
            "client-4",
            [{"kind": "session", "targetId": "source"}],
        )
    )
    agent._handle_chat_message.assert_not_awaited()
    assert browser._chat._messages == []
    assert browser._send_to.call_args.args[1]["type"] == "message_rejected"


def test_concurrent_retries_reuse_the_original_snapshot_and_queue_once(adapter):
    browser, storage, agent = adapter

    async def send_twice():
        args = (
            "Compare",
            [],
            "dest",
            "same-client",
            [{"kind": "session", "targetId": "source"}],
        )
        await asyncio.gather(
            browser._handle_chat_message_with_attachments(*args),
            browser._handle_chat_message_with_attachments(*args),
        )

    asyncio.run(send_twice())
    assert agent._handle_chat_message.await_count == 1
    assert len(storage.get_recent_messages("dest")) == 1
    assert browser._send_to.call_args.args[1]["type"] == "chat_message"
    assert browser._reference_submission_gate._entries == {}
