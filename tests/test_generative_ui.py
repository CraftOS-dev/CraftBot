"""Artifact validation, delivery, history migrations and session-safe revisions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent_core.core.event_stream.event import Event, EventType
from agent_core.core.action_framework.registry import ActionRegistry
from agent_core.core.impl.action.executor import ActionExecutor
from agent_core.core.impl.event_stream.manager import EventStreamManager
from app.data.action.render_ui import render_ui
from app.generative_ui import MAX_HTML_BYTES, make_artifact
from app.internal_action_interface import InternalActionInterface
from app.state.state_manager import StateManager
from app.ui_layer.adapters.base import InterfaceAdapter
from app.ui_layer.adapters.browser_adapter import BrowserChatComponent
from app.ui_layer.components.types import ChatMessage
from app.ui_layer.events.transformer import EventTransformer
from app.usage.chat_storage import ChatStorage, StoredChatMessage


def artifact():
    return make_artifact(
        {"title": "Interactive steps", "html": "<button>Next</button>"}
    )


@pytest.mark.parametrize(
    "change",
    [
        {"title": " "},
        {"title": "a" * 121},
        {"html": ""},
        {"html": 123},
        {"html": "é" * (MAX_HTML_BYTES // 2 + 1)},
        {"artifact_id": "../other"},
        {"connect_origins": "https://api.example.com"},
        {"connect_origins": [{}]},
        {"connect_origins": ["https://api.example.com"] * 9},
    ],
)
def test_rejects_invalid_artifacts(change):
    with pytest.raises(ValueError):
        make_artifact({"title": "Example", "html": "<p>Hello</p>", **change})


@pytest.mark.parametrize(
    "origin",
    [
        "http://api.example.com",
        "https://api.example.com/path",
        "https://api.example.com?secret=value",
        "https://user:pass@api.example.com",
        "https://*.example.com",
        "https://api.example.com; connect-src *",
        "https://api.example.com\n",
        "https://127.0.0.1",
        "https://[::1]",
        "https://localhost",
        "https://app.localhost",
        "https://app.local",
        "https://app.internal",
        "https://api.example.com:7946",
        "https://-bad.example.com",
        "https://api..example.com",
    ],
)
def test_rejects_unsafe_connect_origins(origin):
    with pytest.raises(ValueError):
        make_artifact(
            {"title": "API output", "html": "<p>Data</p>", "connect_origins": [origin]}
        )


def test_connect_origins_are_explicit_normalized_and_persisted(tmp_path):
    data = make_artifact(
        {
            "title": "API output",
            "html": "<p>Data</p>",
            "connect_origins": [
                "https://API.Example.com:443/",
                "https://api.example.com",
                "https://data.example.org",
            ],
        }
    )
    assert data["connect_origins"] == [
        "https://api.example.com",
        "https://data.example.org",
    ]
    storage = ChatStorage(str(tmp_path / "api-output.db"))
    storage.insert_message(
        StoredChatMessage(
            message_id="api-output",
            sender="Agent",
            content="API output",
            style="agent",
            timestamp=1,
            session_id="api-test",
            ui_artifact=data,
        )
    )
    assert (
        storage.get_messages(session_id="api-test")[0].ui_artifact["connect_origins"]
        == data["connect_origins"]
    )


def test_artifact_delivery_and_history_round_trip(tmp_path, monkeypatch):
    """Exercise the production state → event → adapter → SQLite → wire path."""
    streams = EventStreamManager(llm=SimpleNamespace())
    stream = streams.create_stream("cooking")
    manager = StateManager(streams)
    monkeypatch.setattr(manager, "bump_event_stream", lambda: None)
    monkeypatch.setattr(InternalActionInterface, "state_manager", manager)
    result = asyncio.run(
        ActionExecutor().execute_atomic_action(
            SimpleNamespace(**ActionRegistry().find_action_by_name("render_ui")),
            {
                "title": "Steps",
                "html": "<button>Next</button>",
                "_session_id": "cooking",
            },
        )
    )
    event = Event.from_dict(stream.as_list()[-1].to_dict())
    assert event.ui_artifact["id"] == result["artifact_id"]
    ui_event = EventTransformer.transform(event, session_id="cooking")
    component = SimpleNamespace(append_message=AsyncMock())
    # InterfaceAdapter is abstract: exercise its method on a minimal receiver.
    receiver = SimpleNamespace(chat_component=component)
    asyncio.run(
        InterfaceAdapter._display_chat_message(
            receiver,
            "CraftBot",
            "Steps",
            "agent",
            session_id="cooking",
            ui_artifact=ui_event.data["ui_artifact"],
        )
    )
    message = component.append_message.call_args.args[0]
    storage = ChatStorage(str(tmp_path / "chat.db"))
    storage.insert_message(
        StoredChatMessage(
            message_id=message.message_id,
            sender=message.sender,
            content=message.content,
            style=message.style,
            timestamp=message.timestamp,
            session_id=message.session_id,
            ui_artifact=message.ui_artifact,
        )
    )
    restored = BrowserChatComponent._stored_to_chat_message(
        storage.get_recent_messages(session_id="cooking")[0]
    )
    assert restored.to_dict()["uiArtifact"] == message.to_dict()["uiArtifact"]
    assert restored.session_id == "cooking"
    assert storage.get_recent_messages(session_id="other") == []
    assert (
        storage.get_latest_ui_artifact("cooking", message.ui_artifact["id"])
        == message.ui_artifact
    )
    assert storage.get_latest_ui_artifact("other", message.ui_artifact["id"]) is None
    # The migration is additive/idempotent; ordinary messages retain their shape.
    ChatStorage(str(tmp_path / "chat.db"))
    assert "uiArtifact" not in ChatMessage("user", "Hello", "user").to_dict()
    assert (
        "uiArtifact"
        not in StoredChatMessage("old", "user", "Hello", "user", 0).to_dict()
    )


def test_render_action_revisions_are_session_scoped(monkeypatch):
    original = artifact()
    event = Event(
        "Steps",
        "agent message",
        "INFO",
        event_type=EventType.AGENT_MESSAGE,
        ui_artifact=original,
    )
    streams = {
        "mine": SimpleNamespace(as_list=lambda: [event]),
        "other": SimpleNamespace(as_list=lambda: []),
    }
    manager = SimpleNamespace(
        event_stream_manager=SimpleNamespace(
            get_stream_by_id=streams.get, has_stream=lambda sid: sid in streams
        )
    )
    monkeypatch.setattr(InternalActionInterface, "state_manager", manager)
    delivery = AsyncMock()
    monkeypatch.setattr(InternalActionInterface, "do_chat", delivery)
    monkeypatch.setattr(
        "app.usage.chat_storage.get_chat_storage",
        lambda: SimpleNamespace(get_latest_ui_artifact=lambda sid, aid: None),
    )
    data = {"artifact_id": original["id"], "title": "Revised", "html": "<p>Revised</p>"}
    result = asyncio.run(render_ui({**data, "_session_id": "mine"}))
    assert result["revision"] == 2
    assert delivery.call_args.kwargs["ui_artifact"]["html"] == "<p>Revised</p>"
    assert delivery.call_args.kwargs["session_id"] == "mine"
    assert asyncio.run(render_ui({**data, "_session_id": "other"}))["status"] == "error"
    assert delivery.call_count == 1


def test_simulated_action_does_not_deliver(monkeypatch):
    delivery = AsyncMock()
    monkeypatch.setattr(InternalActionInterface, "do_chat", delivery)
    assert (
        asyncio.run(
            render_ui({"title": "Demo", "html": "<p>Hello</p>", "simulated_mode": True})
        )["status"]
        == "success"
    )
    delivery.assert_not_called()


def test_revision_lookup_survives_context_folding(tmp_path, monkeypatch):
    original = {**artifact(), "revision": 7}
    storage = ChatStorage(str(tmp_path / "chat.db"))
    storage.insert_message(
        StoredChatMessage(
            "old",
            "CraftBot",
            "Steps",
            "agent",
            1,
            session_id="mine",
            ui_artifact=original,
        )
    )
    streams = SimpleNamespace(
        has_stream=lambda sid: True,
        get_stream_by_id=lambda sid: SimpleNamespace(as_list=lambda: []),
    )
    monkeypatch.setattr(
        InternalActionInterface,
        "state_manager",
        SimpleNamespace(event_stream_manager=streams),
    )
    monkeypatch.setattr("app.usage.chat_storage.get_chat_storage", lambda: storage)
    monkeypatch.setattr(InternalActionInterface, "do_chat", AsyncMock())
    data = {"artifact_id": original["id"], "title": "Revised", "html": "<p>Updated</p>"}
    assert asyncio.run(render_ui({**data, "_session_id": "mine"}))["revision"] == 8
    assert asyncio.run(render_ui({**data, "_session_id": "other"}))["status"] == "error"
