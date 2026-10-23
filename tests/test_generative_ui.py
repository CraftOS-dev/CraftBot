"""Artifact validation, delivery, history migrations and session-safe revisions."""

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agent_core.core.event_stream.event import Event, EventType
from agent_core.core.action_framework.registry import ActionRegistry
from agent_core.core.impl.action.executor import ActionExecutor
from agent_core.core.impl.event_stream.manager import EventStreamManager
from app.data.action.render_ui import render_ui
from app.agent_base import AgentBase
from app import generative_ui
from app.generative_ui import (
    MAX_HTML_BYTES,
    closed_artifact,
    make_artifact,
    read_images,
)
from app.internal_action_interface import InternalActionInterface
from app.state.state_manager import StateManager
from app.ui_layer.adapters.base import InterfaceAdapter
from app.ui_layer.adapters.browser_adapter import BrowserAdapter, BrowserChatComponent
from app.ui_layer.components.types import ChatMessage
from app.ui_layer.events.transformer import EventTransformer
from app.usage.chat_storage import ChatStorage, StoredChatMessage


def artifact():
    return make_artifact(
        {"title": "Interactive steps", "html": "<button>Next</button>"}
    )


@pytest.mark.parametrize(
    "html",
    [
        "<input>",
        "<textarea></textarea>",
        "<select></select>",
        '<input id="a"><textarea id="a"></textarea>',
        '<input type="password" id="secret">',
        '<input type="file" id="upload">',
        '<input id="__proto__">',
    ],
)
def test_controls_contract_rejects_unpersistable_or_sensitive_fields(html):
    with pytest.raises(ValueError):
        make_artifact({"title": "Fields", "html": html, "persistence": "controls"})


def test_controls_contract_accepts_stable_keys_and_manual_custom_outputs():
    html = '<input id="amount"><input type id="default-type"><input type="radio" data-craftbot-state="choice" value="a"><input type="radio" data-craftbot-state="choice" value="b">'
    assert (
        make_artifact({"title": "Form", "html": html, "persistence": "controls"})[
            "persistence"
        ]
        == "controls"
    )
    assert (
        make_artifact(
            {"title": "Canvas", "html": "<canvas></canvas>", "persistence": "manual"}
        )["persistence"]
        == "manual"
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
        {"image_origins": ["http://tile.example.org"]},
        {"image_origins": "https://tile.example.org"},
        {"libraries": "three"},
        {"libraries": ["three", "jquery"]},
        {"libraries": [{}]},
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
        lambda: SimpleNamespace(
            get_latest_ui_artifact=lambda sid, aid: None,
            store_ui_images=lambda sid, aid, images: {},
        ),
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


def stored(storage, message_id, session_id, data):
    storage.insert_message(
        StoredChatMessage(
            message_id,
            "CraftBot",
            data["title"],
            "agent",
            1,
            session_id=session_id,
            ui_artifact=data,
        )
    )


def test_closing_an_output_drops_its_code_but_keeps_its_numbering(
    tmp_path, monkeypatch
):
    """Closed: every stored revision keeps only id, title and revision (so a
    later revision numbers on); other outputs and sessions are untouched."""
    first = artifact()
    second = {**first, "revision": 2, "html": "<p>Two</p>"}
    other = make_artifact({"title": "Other", "html": "<p>Other</p>"})
    storage = ChatStorage(str(tmp_path / "chat.db"))
    stored(storage, "r1", "mine", first)
    stored(storage, "r2", "mine", second)
    stored(storage, "b1", "mine", other)
    stored(storage, "elsewhere", "theirs", first)

    assert storage.close_ui_artifact("mine", first["id"]) == 2
    rows = {m.message_id: m.ui_artifact for m in storage.get_messages()}
    marker = {"id": first["id"], "title": first["title"], "closed": True}
    assert rows["r1"] == {**marker, "revision": 1}
    assert rows["r2"] == {**marker, "revision": 2}
    assert rows["b1"] == other
    assert rows["elsewhere"] == first
    assert storage.close_ui_artifact("mine", "missing") == 0

    # The agent can still revise it: the new revision numbers on.
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
    data = {"artifact_id": first["id"], "title": "Again", "html": "<p>Again</p>"}
    assert asyncio.run(render_ui({**data, "_session_id": "mine"}))["revision"] == 3


def test_closing_an_output_drops_its_code_from_the_sessions_events():
    first, other = artifact(), make_artifact({"title": "Other", "html": "<p>x</p>"})
    streams = EventStreamManager(llm=SimpleNamespace())
    stream = streams.create_stream("mine")
    for data in (first, other):
        stream.log(
            "agent message",
            data["title"],
            event_type=EventType.AGENT_MESSAGE,
            ui_artifact=data,
        )
    persist = Mock()
    agent = SimpleNamespace(
        event_stream_manager=streams, _persist_session_stream=persist
    )
    assert AgentBase.close_ui_artifact(agent, "mine", first["id"]) == 1
    carried = [
        record.event.ui_artifact
        for record in stream.tail_events
        if record.event.ui_artifact
    ]
    assert closed_artifact(first) in carried and other in carried
    assert all("html" not in a for a in carried if a["id"] == first["id"])
    persist.assert_called_once_with("mine")
    assert AgentBase.close_ui_artifact(agent, "nobody", first["id"]) == 0


def test_the_close_request_reaches_storage_events_and_every_client(tmp_path):
    first = artifact()
    storage = ChatStorage(str(tmp_path / "chat.db"))
    stored(storage, "r1", "mine", first)
    chat = BrowserChatComponent.__new__(BrowserChatComponent)
    chat._messages = [
        ChatMessage(
            "CraftBot", first["title"], "agent", session_id="mine", ui_artifact=first
        )
    ]
    chat._storage = storage
    chat._db = ThreadPoolExecutor(max_workers=1)
    agent = SimpleNamespace(close_ui_artifact=Mock(return_value=1))
    adapter = SimpleNamespace(
        _chat=chat,
        _controller=SimpleNamespace(agent=agent),
        _broadcast=AsyncMock(),
    )
    request = {"sessionId": "mine", "artifactId": first["id"]}
    asyncio.run(BrowserAdapter._handle_generative_ui_close(adapter, request))

    assert chat._messages[0].ui_artifact == closed_artifact(first)
    assert storage.get_messages()[0].ui_artifact == closed_artifact(first)
    agent.close_ui_artifact.assert_called_once_with("mine", first["id"])
    adapter._broadcast.assert_awaited_once_with(
        {"type": "generative_ui_closed", "data": request}
    )

    # A malformed request changes nothing.
    for bad in ({}, {"sessionId": "mine"}, {"sessionId": "", "artifactId": "x"}):
        asyncio.run(BrowserAdapter._handle_generative_ui_close(adapter, bad))
    assert adapter._broadcast.await_count == 1
    chat._db.shutdown()


# A 1x1 PNG.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_libraries_and_image_origins_are_explicit_and_normalized():
    data = make_artifact(
        {
            "title": "Map",
            "html": "<div id=map></div>",
            "libraries": ["three", "leaflet", "three"],
            "image_origins": ["https://Tile.OpenStreetMap.org:443/"],
        }
    )
    assert data["libraries"] == ["leaflet", "three"]
    assert data["image_origins"] == ["https://tile.openstreetmap.org"]
    plain = artifact()
    assert plain["libraries"] == [] and plain["image_origins"] == []


def test_images_are_read_by_their_own_bytes(tmp_path):
    files = {
        "photo": (b"\xff\xd8\xff\xe0" + b"0" * 16, "jpg"),
        "logo": (PNG, "png"),
        "loop": (b"GIF89a" + b"0" * 16, "gif"),
        "art": (b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"0" * 16, "webp"),
    }
    paths = {}
    for name, (data, _) in files.items():
        (tmp_path / f"{name}.bin").write_bytes(data)
        paths[name] = str(tmp_path / f"{name}.bin")
    assert read_images(paths) == files
    assert read_images({}) == {}


def test_rejects_invalid_images(tmp_path, monkeypatch):
    image = tmp_path / "hero.png"
    image.write_bytes(PNG)
    (tmp_path / "notes.txt").write_text("not an image")
    for value in (
        "hero.png",
        {"hero-image": str(image)},
        {"1hero": str(image)},
        {"hero": str(tmp_path / "missing.png")},
        {"hero": str(tmp_path)},
        {"hero": 5},
        {"hero": str(tmp_path / "notes.txt")},
        {f"i{n}": str(image) for n in range(9)},
    ):
        with pytest.raises(ValueError):
            read_images(value)
    monkeypatch.setattr(generative_ui, "MAX_IMAGE_BYTES", len(PNG) - 1)
    with pytest.raises(ValueError):
        read_images({"hero": str(image)})
    monkeypatch.setattr(generative_ui, "MAX_IMAGE_BYTES", len(PNG))
    monkeypatch.setattr(generative_ui, "MAX_TOTAL_IMAGE_BYTES", len(PNG) * 2 - 1)
    with pytest.raises(ValueError):
        read_images({"one": str(image), "two": str(image)})


def test_output_images_live_with_the_chat_history(tmp_path):
    """Stored per output (content-addressed, so revisions share them), served
    only by their exact stored path, and gone with the output or its chat."""
    storage = ChatStorage(str(tmp_path / "chat.db"))
    first = storage.store_ui_images("mine", "map", {"hero": (PNG, "png")})
    again = storage.store_ui_images("mine", "map", {"cover": (PNG, "png")})
    assert first["hero"] == again["cover"]
    assert storage.ui_image_file(first["hero"]).read_bytes() == PNG
    other = storage.store_ui_images("mine", "chart", {"hero": (PNG, "png")})
    theirs = storage.store_ui_images("theirs", "map", {"hero": (PNG, "png")})
    assert len({first["hero"], other["hero"], theirs["hero"]}) == 3
    assert storage.store_ui_images("mine", "plain", {}) == {}
    for path in (
        "",
        "../chat.db",
        first["hero"].replace(".png", ".txt"),
        first["hero"] + "/x",
        "/".join(first["hero"].split("/")[:2]),
        first["hero"].replace("/", "\\"),
    ):
        assert storage.ui_image_file(path) is None

    stored(
        storage,
        "r1",
        "mine",
        {**make_artifact({"title": "Map", "html": "<p>"}), "id": "map"},
    )
    storage.close_ui_artifact("mine", "map")
    assert storage.ui_image_file(first["hero"]) is None
    assert storage.ui_image_file(other["hero"]) is not None
    storage.clear_messages("mine")
    assert storage.ui_image_file(other["hero"]) is None
    assert storage.ui_image_file(theirs["hero"]) is not None
    storage.clear_messages()
    assert storage.ui_image_file(theirs["hero"]) is None


def test_render_action_stores_images_for_the_output(tmp_path, monkeypatch):
    image = tmp_path / "hero.png"
    image.write_bytes(PNG)
    storage = ChatStorage(str(tmp_path / "chat.db"))
    monkeypatch.setattr("app.usage.chat_storage.get_chat_storage", lambda: storage)
    delivery = AsyncMock()
    monkeypatch.setattr(InternalActionInterface, "do_chat", delivery)
    data = {
        "title": "Trip",
        "html": "<img id=hero>",
        "images": {"hero": str(image)},
        "_session_id": "mine",
    }
    result = asyncio.run(render_ui(data))
    stored_images = delivery.call_args.kwargs["ui_artifact"]["images"]
    assert storage.ui_image_file(stored_images["hero"]).read_bytes() == PNG
    assert stored_images["hero"].split("/")[1] == result["artifact_id"]

    bad = asyncio.run(render_ui({**data, "images": {"hero": str(tmp_path)}}))
    assert bad["status"] == "error" and delivery.call_count == 1


def test_stored_images_are_served_by_exact_path_only(tmp_path, monkeypatch):
    from aiohttp import web

    storage = ChatStorage(str(tmp_path / "chat.db"))
    monkeypatch.setattr("app.usage.chat_storage.get_chat_storage", lambda: storage)
    path = storage.store_ui_images("mine", "map", {"hero": (PNG, "png")})["hero"]
    serve = BrowserAdapter._generative_ui_image_handler

    response = asyncio.run(serve(None, SimpleNamespace(match_info={"path": path})))
    assert response.headers["Content-Type"] == "image/png"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    for bad in ("../chat.db", path.replace(".png", ".gif"), ""):
        with pytest.raises(web.HTTPNotFound):
            asyncio.run(serve(None, SimpleNamespace(match_info={"path": bad})))


def test_map_settings_take_defaults_for_unusable_values(monkeypatch):
    from app import config

    defaults = config._get_default_settings()["generative_ui"]
    monkeypatch.setattr(config, "get_settings", lambda: {})
    assert config.get_generative_ui_settings() == defaults
    custom = {
        "map_tiles_url": "https://tiles.example.org/{z}/{x}/{y}.png",
        "map_attribution": "Example",
        "map_max_zoom": 17,
    }
    monkeypatch.setattr(config, "get_settings", lambda: {"generative_ui": custom})
    assert config.get_generative_ui_settings() == custom
    for bad in (
        {"map_tiles_url": "http://tiles.example.org/{z}/{x}/{y}.png"},
        {"map_tiles_url": "https://tiles.example.org/{z}/{x}.png"},
        {"map_attribution": 3},
        {"map_max_zoom": 23},
        {"map_max_zoom": True},
    ):
        monkeypatch.setattr(
            config, "get_settings", lambda bad=bad: {"generative_ui": bad}
        )
        assert config.get_generative_ui_settings() == defaults


def test_tile_lifetime_follows_the_servers_caching_headers():
    from app import map_tiles

    assert map_tiles._lifetime({"Cache-Control": "public, max-age=600"}) == 600
    assert map_tiles._lifetime({"Cache-Control": "no-store"}) == 0
    assert map_tiles._lifetime({"Cache-Control": "no-cache, max-age=600"}) == 0
    assert map_tiles._lifetime({"Expires": "Thu, 01 Jan 1970 00:00:00 GMT"}) == 0
    assert map_tiles._lifetime({"Expires": "not a date"}) == 0
    assert map_tiles._lifetime({}) == map_tiles.DEFAULT_TILE_SECONDS
    assert map_tiles.valid_tile(0, 0, 0, 19)
    assert map_tiles.valid_tile(3, 7, 7, 19)
    assert not map_tiles.valid_tile(3, 8, 0, 19)
    assert not map_tiles.valid_tile(20, 0, 0, 19)


def test_tiles_are_fetched_once_and_cached_for_their_lifetime(tmp_path, monkeypatch):
    from app import map_tiles

    template = "https://tiles.example.org/{z}/{x}/{y}.png"
    monkeypatch.setattr(map_tiles, "_cache_root", tmp_path)
    monkeypatch.setattr(
        map_tiles,
        "get_generative_ui_settings",
        lambda: {"map_tiles_url": template},
    )
    downloads = []

    async def download(url):
        downloads.append(url)
        await asyncio.sleep(0.01)
        return PNG, "image/png", 600 if url.endswith("/1/0/1.png") else 0

    monkeypatch.setattr(map_tiles, "_download", download)

    async def run():
        # Requests for one tile share a download.
        first = await asyncio.gather(*(map_tiles.get_tile(1, 0, 1) for _ in range(3)))
        cached = await map_tiles.get_tile(1, 0, 1)
        uncacheable = [await map_tiles.get_tile(2, 1, 1) for _ in range(2)]
        return first, cached, uncacheable

    first, cached, uncacheable = asyncio.run(run())
    assert first == [(PNG, "image/png")] * 3 and cached == (PNG, "image/png")
    assert uncacheable == [(PNG, "image/png")] * 2
    assert downloads == [
        "https://tiles.example.org/1/0/1.png",
        "https://tiles.example.org/2/1/1.png",
        "https://tiles.example.org/2/1/1.png",
    ]


def test_tile_routes_serve_tiles_and_map_details(monkeypatch):
    from aiohttp import web

    from app import config, map_tiles

    monkeypatch.setattr(
        config,
        "get_generative_ui_settings",
        lambda: {
            "map_tiles_url": "https://tiles.example.org/{z}/{x}/{y}.png",
            "map_attribution": "Example tiles",
            "map_max_zoom": 5,
        },
    )
    details = asyncio.run(BrowserAdapter._generative_ui_map_handler(None, None))
    assert details.text == '{"attribution": "Example tiles", "maxZoom": 5}'

    async def tile(z, x, y):
        if x == 1:
            raise map_tiles.TileUnavailable("503")
        return PNG, "image/png"

    monkeypatch.setattr(map_tiles, "get_tile", tile)
    serve = BrowserAdapter._generative_ui_tile_handler

    def request(z, x, y):
        return SimpleNamespace(match_info={"z": str(z), "x": str(x), "y": str(y)})

    response = asyncio.run(serve(None, request(2, 0, 3)))
    assert response.body == PNG and response.content_type == "image/png"
    with pytest.raises(web.HTTPBadGateway):
        asyncio.run(serve(None, request(2, 1, 3)))
    for z, x, y in ((6, 0, 0), (2, 4, 0), (2, 0, 4)):
        with pytest.raises(web.HTTPNotFound):
            asyncio.run(serve(None, request(z, x, y)))
