"""Reference identity, storage, extraction and access invariants (no live models)."""

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from app.references import ReferenceError, create_reference_service
from app.references.providers import AgentAppReferenceProvider
from app.references.service import TOTAL_BYTES, reference_token_budget
from app.usage.chat_storage import ChatStorage, StoredChatMessage
from app.ui_layer.components.types import ChatMessage


@pytest.fixture
def system(tmp_path):
    storage = ChatStorage(str(tmp_path / "chat.db"))
    sources = {
        key: SimpleNamespace(id=key, title=key) for key in ("dest", "source", "other")
    }
    sessions = SimpleNamespace(get=sources.get)
    project = SimpleNamespace(
        id="app-1",
        name="Weather",
        description="Forecasts",
        features=["alerts"],
        project_type="native",
        status="stopped",
        backend_port=None,
        port=None,
        backend_url=None,
        url=None,
        bridge_token="SECRET",
        path="private",
        session_id="other",
    )
    apps = SimpleNamespace(
        get_project=lambda key: project if key == project.id else None
    )
    return create_reference_service(sessions, storage, apps), storage, sources, project


def put(storage, id, session="source", content="hello", style="user", references=None):
    storage.insert_message(
        StoredChatMessage(
            message_id=id,
            sender=style,
            style=style,
            content=content,
            timestamp=1,
            session_id=session,
            references=references,
        )
    )


def test_snapshots_round_trip_and_old_rows(system):
    service, storage, _, _ = system
    put(storage, "old")
    snapshots = asyncio.run(
        service.resolve([{"kind": "session", "targetId": "source"}], "dest")
    )
    put(storage, "new", "dest", references=snapshots)
    stored = storage.get_recent_messages("dest")[0]
    assert stored.references == snapshots
    assert stored.to_dict()["references"] == snapshots
    assert (
        ChatMessage("You", "Hi", "user", references=snapshots).to_dict()["references"]
        == snapshots
    )
    assert storage.get_recent_messages("source")[0].references is None
    assert storage.has_reference("dest", "session", "source")
    assert not storage.has_reference("other", "session", "source")


@pytest.mark.parametrize(
    "inputs",
    [
        None,
        {},
        [None],
        [{"kind": [], "targetId": "source"}],
        [{"kind": "unknown", "targetId": "source"}],
        [{"kind": "session", "targetId": ""}],
        [{"kind": "session", "targetId": "dest"}],
        [{"kind": "session", "targetId": "x" * 257}],
        [{"kind": "session", "targetId": "source"}] * 9,
    ],
)
def test_rejects_invalid_inputs(system, inputs):
    with pytest.raises(ReferenceError):
        asyncio.run(system[0].resolve(inputs, "dest"))


def test_deduplicates_and_captures_send_time(system):
    service, storage, _, _ = system
    put(storage, "one", content="initial")
    ref = {"kind": "session", "targetId": "source"}
    snapshots = asyncio.run(service.resolve([ref, ref], "dest"))
    assert len(snapshots) == 1
    put(storage, "two", content="later")
    assert (
        "initial" in snapshots[0]["excerpt"] and "later" not in snapshots[0]["excerpt"]
    )
    assert "later" in asyncio.run(service.resolve([ref], "dest"))[0]["excerpt"]


def test_read_requires_attachment_and_current_source(system):
    service, storage, sources, _ = system
    ref = {"kind": "session", "targetId": "source"}
    with pytest.raises(ReferenceError, match="not attached"):
        asyncio.run(service.read(ref, "dest"))
    snapshots = asyncio.run(service.resolve([ref], "dest"))
    put(storage, "attached", "dest", references=snapshots)
    assert asyncio.run(service.read(ref, "dest"))["live"]
    del sources["source"]
    with pytest.raises(ReferenceError, match="no longer"):
        asyncio.run(service.read(ref, "dest"))
    assert storage.get_recent_messages("dest")[0].references == snapshots
    storage.clear_messages("dest")
    assert not storage.has_reference("dest", "session", "source")


def test_transcript_is_bounded_visible_and_non_recursive(system):
    service, storage, _, _ = system
    put(storage, "private", content="HIDDEN REASONING", style="system")
    put(
        storage,
        "nested",
        references=[
            {"kind": "session", "targetId": "other", "excerpt": "NESTED SECRET"}
        ],
    )
    put(storage, "large", content="😀" * 10000)
    result = asyncio.run(
        service.resolve([{"kind": "session", "targetId": "source"}], "dest")
    )[0]
    assert len(result["excerpt"].encode("utf-8")) <= 8192
    assert result["truncated"]
    assert (
        "HIDDEN REASONING" not in result["excerpt"]
        and "NESTED SECRET" not in result["excerpt"]
    )
    assert "quoted source data" in service.render([result])


def test_backward_pages_handle_equal_timestamps_and_new_arrivals(system):
    _, storage, _, _ = system
    for i in range(6):
        put(storage, f"old-{i}", content="hello " * 8)
    page = storage.reference_page("source", None, 270)
    assert page["nextCursor"]
    seen = [json.loads(line)["messageId"] for line in page["text"].splitlines()]
    put(storage, "new-arrival")
    while page["nextCursor"]:
        page = storage.reference_page("source", page["nextCursor"], 270)
        seen.extend(json.loads(line)["messageId"] for line in page["text"].splitlines())
    assert len(seen) == len(set(seen)) == 6
    assert "new-arrival" not in seen


def test_cursors_cannot_cross_sources_or_survive_clear(system):
    _, storage, _, _ = system
    for i in range(4):
        put(storage, str(i), content="x" * 100)
    cursor = storage.reference_page("source", None, 220)["nextCursor"]
    with pytest.raises(ReferenceError):
        storage.reference_page("other", cursor, 220)
    with pytest.raises(ReferenceError):
        storage.reference_page("source", "garbage", 220)
    storage.clear_messages("source")
    put(storage, "fresh")
    with pytest.raises(ReferenceError, match="changed"):
        storage.reference_page("source", cursor, 220)


def test_stopped_app_does_not_launch_or_expose_secrets(system):
    service, _, _, _ = system
    result = asyncio.run(
        service.resolve([{"kind": "agent_app", "targetId": "app-1"}], "dest")
    )[0]
    assert "Weather" in result["excerpt"] and "not running" in result["excerpt"]
    assert "SECRET" not in result["excerpt"] and "private" not in result["excerpt"]


def test_running_app_uses_optional_bounded_schema(system, monkeypatch):
    service, _, _, app = system
    app.status, app.url = "running", "http://127.0.0.1:12345"
    monkeypatch.setattr(
        AgentAppReferenceProvider,
        "_describe",
        staticmethod(lambda base_url: {"entities": {"notes": {}}}),
    )
    result = asyncio.run(
        service.resolve([{"kind": "agent_app", "targetId": "app-1"}], "dest")
    )[0]
    assert "notes" in result["excerpt"]


@pytest.mark.parametrize(
    "backend_url,url,expected",
    [
        ("http://192.168.1.20:3000", "http://192.168.1.20:8080", "http://192.168.1.20:3000"),
        (None, "https://notes.example.test", "https://notes.example.test"),
    ],
)
def test_app_schema_comes_from_the_registered_address(
    system, monkeypatch, backend_url, url, expected
):
    """External apps need not listen on 127.0.0.1:<port>; use what the manager
    registered, as the agent's own app note does."""
    service, _, _, app = system
    app.status, app.project_type = "running", "external"
    app.backend_url, app.url = backend_url, url
    asked = []
    monkeypatch.setattr(
        AgentAppReferenceProvider,
        "_describe",
        staticmethod(lambda base_url: asked.append(base_url) or {"entities": {}}),
    )
    asyncio.run(service.resolve([{"kind": "agent_app", "targetId": "app-1"}], "dest"))
    assert asked == [expected]


def test_describe_refuses_non_http_addresses():
    assert AgentAppReferenceProvider._describe("file:///etc/passwd") is None


def test_app_describe_filters_records_credentials_and_system_operations(monkeypatch):
    import io
    import urllib.request

    response = {
        "token": "PRIVATE ROOT",
        "records": ["CUSTOMER DATA"],
        "entities": {
            "notes": {
                "fields": {"title": {"type": "string", "secret": "PRIVATE FIELD"}}
            }
        },
        "operations": [
            {"name": "notes.list", "description": "List notes", "secret": "PRIVATE OP"},
            {"name": "system.inspect", "system": True},
        ],
    }
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(
            open=lambda *args, **kw: io.BytesIO(json.dumps(response).encode())
        ),
    )
    result = AgentAppReferenceProvider._describe("http://127.0.0.1:12345")
    assert result["entities"]["notes"]["fields"]["title"] == {"type": "string"}
    assert result["operations"] == [{"name": "notes.list", "description": "List notes"}]
    assert "PRIVATE" not in json.dumps(result) and "CUSTOMER" not in json.dumps(result)


def test_total_budget_and_no_cross_session_read(system):
    service, storage, sources, _ = system
    refs = []
    for i in range(8):
        key = f"source-{i}"
        sources[key] = SimpleNamespace(title=key)
        put(storage, key, key, content="字" * 10000)
        refs.append({"kind": "session", "targetId": key})
    snapshots = asyncio.run(service.resolve(refs, "dest"))
    assert sum(len(r["excerpt"].encode()) for r in snapshots) <= TOTAL_BYTES
    assert "source-7" not in snapshots[0]["excerpt"]


def test_long_message_can_be_read_completely_across_pages(system):
    _, storage, _, _ = system
    original = '😀 quoted "text"\n' * 100
    put(storage, "long", content=original)
    page, chunks = storage.reference_page("source", None, 512), []
    for _ in range(100):
        assert len(page["text"].encode("utf-8")) <= 512
        chunks.extend(json.loads(line)["content"] for line in page["text"].splitlines())
        if not page["nextCursor"]:
            break
        page = storage.reference_page("source", page["nextCursor"], 512)
    assert "".join(chunks) == original


def test_small_token_budget_preserves_continuation_cursor(system):
    service, storage, _, _ = system
    service.token_budget, service.token_count = 1800, len
    original = "content " * 1000
    put(storage, "long", content=original)
    ref = {"kind": "session", "targetId": "source"}
    snapshot = asyncio.run(service.resolve([ref], "dest"))[0]
    put(storage, "attached", "dest", references=[snapshot])
    assert len(service.render([snapshot])) <= 1800
    chunks = [json.loads(snapshot["excerpt"])["content"]]
    cursor = snapshot["nextCursor"]
    while cursor:
        page = asyncio.run(service.read(ref, "dest", cursor))
        chunks.extend(
            json.loads(line)["content"] for line in page["excerpt"].splitlines()
        )
        cursor = page["nextCursor"]
    assert "".join(chunks) == original


def test_read_action_uses_the_injected_destination_scope(system, monkeypatch):
    from app.data.action.reference_actions import read_reference
    import app.references

    service, storage, _, _ = system
    ref = {"kind": "session", "targetId": "source"}
    snapshots = asyncio.run(service.resolve([ref], "dest"))
    put(storage, "attached", "dest", references=snapshots)
    monkeypatch.setattr(app.references, "create_reference_service", lambda: service)
    assert "error" in asyncio.run(
        read_reference({"kind": "session", "target_id": "source"})
    )
    assert "error" in asyncio.run(
        read_reference(
            {"kind": "session", "target_id": "source", "_session_id": "other"}
        )
    )
    assert asyncio.run(
        read_reference(
            {"kind": "session", "target_id": "source", "_session_id": "dest"}
        )
    )["live"]


@pytest.mark.parametrize("field", ["high", "before", "row", "offset"])
@pytest.mark.parametrize(
    "value", [1 << 63, 10**100, -(1 << 63) - 1, 1.5, float("inf"), "1", True]
)
def test_cursor_positions_reject_non_sqlite_integers(system, field, value):
    _, storage, _, _ = system
    put(storage, "cursor-source", content="visible source")
    state = {"session": "source", "high": 1, "before": 2, "row": 0, "offset": 0}
    state[field] = value
    cursor = base64.urlsafe_b64encode(json.dumps(state).encode()).decode()

    with pytest.raises(ReferenceError, match="Invalid reference cursor"):
        storage.reference_page("source", cursor, 512)

    assert storage.get_recent_messages("source")[0].content == "visible source"


@pytest.mark.parametrize(
    "window,budget", [(None, 8192), (1_000_000, 8192), (16_000, 2000), (512, 128)]
)
def test_token_budget_follows_the_running_models_window(window, budget):
    assert reference_token_budget(window) == budget


def test_service_budget_comes_from_the_llm_not_settings(system):
    _, storage, sources, project = system
    service = create_reference_service(
        SimpleNamespace(get=sources.get),
        storage,
        SimpleNamespace(get_project=lambda key: None),
        llm=SimpleNamespace(context_window=lambda: 16_000),
    )
    assert service.token_budget == 2000
