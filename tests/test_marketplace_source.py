"""Marketplace fallback and deterministic installation contracts."""

import asyncio
import io
import json
import urllib.error
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.agent_app import marketplace_source as source
from app.agent_app import wizard
from app.agent_app.manager import AgentAppManager


CATALOGUE = json.dumps(
    {"apps": [{"id": "kanban-board", "folder": "kanban-board", "description": "Tasks"}]}
).encode()


@pytest.fixture(autouse=True)
def marketplace_ref(monkeypatch):
    monkeypatch.setenv("CRAFTBOT_MARKETPLACE_REF", "main")


@pytest.fixture
def transport(monkeypatch):
    """Mock the HTTP boundary, so callers exercise the real fallback logic."""
    calls = []
    responses = []

    def urlopen(request, *, timeout, context):
        calls.append(request.full_url)
        assert request.get_header("User-agent") == "CraftBot"
        assert timeout > 0
        assert context is not None
        if not responses:
            raise AssertionError(f"Unexpected request: {request.full_url}")
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(response)

    monkeypatch.setattr(source.urllib.request, "urlopen", urlopen)
    return calls, responses


def missing():
    return urllib.error.HTTPError("https://github.com/", 404, "Not Found", {}, None)


def test_catalogue_prefers_new_repository_and_uses_matching_thumbnails(transport):
    calls, responses = transport
    responses.append(CATALOGUE)

    catalogue = source.fetch_catalogue()

    assert calls == [source.catalogue_url(source.REPO)]
    assert catalogue["apps"][0]["preview"] == source.thumbnail_url("kanban-board")


@pytest.mark.parametrize(
    "unavailable",
    [
        missing(),
        urllib.error.URLError("offline"),
        TimeoutError("timed out"),
        b"not JSON",
        b"[]",
    ],
)
def test_catalogue_falls_back_before_rename(transport, unavailable):
    calls, responses = transport
    responses.extend([unavailable, CATALOGUE])

    catalogue = source.fetch_catalogue()

    assert calls == [source.catalogue_url(repo) for repo in source.REPOS]
    assert catalogue["apps"][0]["preview"] == source.thumbnail_url(
        "kanban-board", source.LEGACY_REPO
    )


def test_catalogue_preserves_publisher_preview_and_trailing_comma_support(transport):
    _, responses = transport
    responses.append(
        b'{"apps": [{"id": "board", "folder": "board", '
        b'"preview": "https://example.com/preview.png",},],}'
    )

    assert (
        source.fetch_catalogue()["apps"][0]["preview"]
        == "https://example.com/preview.png"
    )


def test_both_catalogues_unavailable_propagates_final_error(transport):
    calls, responses = transport
    error = urllib.error.URLError("fallback also unavailable")
    responses.extend([missing(), error])

    with pytest.raises(urllib.error.URLError) as raised:
        source.fetch_catalogue()

    assert raised.value is error
    assert calls == [source.catalogue_url(repo) for repo in source.REPOS]


@pytest.mark.parametrize("repo", ["agent-app-collection", "living-ui-marketplace"])
@pytest.mark.parametrize("before_rename", [True, False])
def test_archive_accepts_both_aliases_in_new_first_order(
    transport, repo, before_rename
):
    calls, responses = transport
    if before_rename:
        responses.append(missing())
    responses.append(b"archive bytes")

    assert source.download_archive("CraftOS-dev", repo) == b"archive bytes"

    expected = [source.zip_url("CraftOS-dev", "agent-app-collection")]
    if before_rename:
        expected.append(source.zip_url("CraftOS-dev", "living-ui-marketplace"))
    assert calls == expected


@pytest.mark.parametrize(
    "owner,repo", [("someone", "living-ui-marketplace"), ("CraftOS-dev", "custom-apps")]
)
def test_custom_repositories_do_not_fall_back_to_official_marketplace(
    transport, owner, repo
):
    calls, responses = transport
    responses.append(missing())

    with pytest.raises(urllib.error.HTTPError):
        source.download_archive(owner, repo)

    assert calls == [source.zip_url(owner, repo)]


def test_configured_branch_is_preserved_across_fallback(transport, monkeypatch):
    monkeypatch.setenv("CRAFTBOT_MARKETPLACE_REF", "feature/pipeline")
    calls, responses = transport
    responses.extend([missing(), CATALOGUE, missing(), b"archive"])

    catalogue = source.fetch_catalogue()
    source.download_archive("CraftOS-dev", "living-ui-marketplace")

    assert calls == [source.catalogue_url(repo) for repo in source.REPOS] + [
        source.zip_url(*repo.split("/")) for repo in source.REPOS
    ]
    assert all(
        "/feature/pipeline/" in url or "/feature/pipeline.zip" in url for url in calls
    )
    assert catalogue["apps"][0]["preview"] == source.thumbnail_url(
        "kanban-board", source.LEGACY_REPO
    )


def test_settings_branch_is_used_when_environment_override_is_absent(monkeypatch):
    monkeypatch.delenv("CRAFTBOT_MARKETPLACE_REF")
    monkeypatch.setattr("app.config.get_marketplace_ref", lambda: "staging")

    assert "/staging/catalogue.json" in source.catalogue_url()
    assert "/staging.zip" in source.zip_url("CraftOS-dev", "agent-app-collection")


@pytest.mark.parametrize("new_branch", ["main", "other"])
def test_local_checkout_supports_both_names_and_requires_matching_branch(
    tmp_path, monkeypatch, new_branch
):
    fake_source = tmp_path / "CraftBot" / "app" / "agent_app" / "marketplace_source.py"
    monkeypatch.setattr(source, "__file__", str(fake_source))
    catalogues = []
    for repository, branch in zip(source.REPOS, (new_branch, "main")):
        root = tmp_path / repository.split("/")[-1]
        (root / ".git").mkdir(parents=True)
        (root / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
        catalogue = root / "catalogue.json"
        catalogue.write_bytes(CATALOGUE)
        catalogues.append(catalogue)

    assert source.local_catalogue() == catalogues[0 if new_branch == "main" else 1]


def test_wizard_uses_fallback_catalogue(transport, monkeypatch):
    calls, responses = transport
    responses.extend([missing(), CATALOGUE])
    monkeypatch.setattr(source, "local_catalogue", lambda: None)
    monkeypatch.setattr(wizard, "_MARKETPLACE_CACHE", {})

    assert wizard._marketplace_catalogue()[0]["id"] == "kanban-board"
    assert calls == [source.catalogue_url(repo) for repo in source.REPOS]
    wizard._marketplace_catalogue()
    assert len(calls) == 2, "The existing wizard cache should still apply"


def test_wizard_can_build_when_both_repositories_are_unavailable(
    transport, monkeypatch
):
    _, responses = transport
    responses.extend([missing(), missing()])
    monkeypatch.setattr(source, "local_catalogue", lambda: None)
    monkeypatch.setattr(wizard, "_MARKETPLACE_CACHE", {})

    assert wizard._marketplace_catalogue() == []


def test_browser_catalogue_uses_fallback_thumbnails(transport):
    from app.ui_layer.adapters.browser_adapter import BrowserAdapter

    calls, responses = transport
    responses.extend([missing(), CATALOGUE])
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter._broadcast = AsyncMock()
    adapter._marketplace_previews = {}

    asyncio.run(adapter._handle_marketplace_list())

    payload = adapter._broadcast.call_args.args[0]["data"]
    assert payload["success"] is True
    assert payload["apps"][0]["preview"] == source.thumbnail_url(
        "kanban-board", source.LEGACY_REPO
    )
    thumbnail = payload["apps"][0]["thumbnail"]
    assert thumbnail.startswith("/api/agent-app/marketplace-thumbnail/")
    assert adapter._marketplace_previews[thumbnail.rsplit("/", 1)[1]] == (
        payload["apps"][0]["preview"]
    )
    assert calls == [source.catalogue_url(repo) for repo in source.REPOS]


def test_legacy_agent_action_uses_fallback_catalogue(transport, monkeypatch):
    from app.data.action.agent_app_actions import agent_app_marketplace_list
    from app.agent_app import framework_transition

    monkeypatch.setattr(framework_transition, "is_framework_request", lambda _: False)

    calls, responses = transport
    responses.extend([missing(), CATALOGUE])

    result = asyncio.run(agent_app_marketplace_list({}))

    assert result["status"] == "success"
    assert result["apps"][0]["id"] == "kanban-board"
    assert calls == [source.catalogue_url(repo) for repo in source.REPOS]


@pytest.mark.parametrize("before_rename", [True, False])
@pytest.mark.parametrize("launch_succeeds", [True, False])
def test_browser_install_keeps_one_tab_and_requires_no_agent_run(
    tmp_path, monkeypatch, transport, before_rename, launch_succeeds
):
    """Exercise the UI, extraction, registration and launch orchestration.

    Only network, kit sync, the server pipeline and external UI/session/factory
    services are substituted. This is not a real PocketBase startup test.
    """
    from agent_core.core.impl.llm.interface import LLMInterface
    from app.ui_layer.adapters.browser_adapter import BrowserAdapter

    calls, responses = transport
    repository = "living-ui-marketplace" if before_rename else "agent-app-collection"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            f"{repository}-main/kanban-board/manifest.json",
            json.dumps({"agentAppVersion": 2, "craftbotVersion": "1.4.4"}),
        )
        zf.writestr(f"{repository}-main/kanban-board/app.txt", "Installed app")
    if before_rename:
        responses.append(missing())
    responses.append(archive.getvalue())
    manager = AgentAppManager(workspace_root=tmp_path)
    monkeypatch.setattr(manager, "_allocate_port", lambda: 3100)
    monkeypatch.setattr(manager.runner, "kit_sync", AsyncMock())
    pipeline = AsyncMock(
        return_value={"status": "success", "process": None}
        if launch_succeeds
        else {"status": "error", "step": "validation", "errors": ["Build failed"]}
    )
    monkeypatch.setattr(manager, "_run_launch_pipeline", pipeline)
    monkeypatch.setattr(manager, "_broadcast_ready", AsyncMock())
    monkeypatch.setattr(
        "app.factory.host_craftbot.get_factory_host", lambda: Mock()
    )

    # Count attempts even if a caller catches the exception. Installation must
    # neither enqueue an agent turn nor make a direct model call.
    dispatch = AsyncMock(side_effect=AssertionError("Install started an agent run"))
    monkeypatch.setattr(manager, "start_development_run", dispatch)
    model_calls = []
    for method in (
        "generate_response",
        "generate_response_async",
        "generate_response_with_session",
        "generate_response_with_session_async",
        "generate_side_response_with_session",
    ):
        mock_type = AsyncMock if method.endswith("_async") else Mock
        call = mock_type(side_effect=AssertionError("Install called a model"))
        monkeypatch.setattr(LLMInterface, method, call)
        model_calls.append(call)

    sessions = Mock()
    sessions.create_session.side_effect = lambda **kwargs: SimpleNamespace(
        id=kwargs["session_id"]
    )
    manager.bind_session_manager(sessions, SimpleNamespace(emit=dispatch))
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter._agent_app_manager = manager
    adapter._broadcast = AsyncMock()
    adapter._display_chat_message = AsyncMock()
    adapter._controller = SimpleNamespace(submit_message=dispatch)
    adapter.submit_message = dispatch

    asyncio.run(adapter._handle_marketplace_install("kanban-board", "Board", "Tasks"))

    events = [call.args[0] for call in adapter._broadcast.call_args_list]
    assert events[0]["type"] == "agent_app_create"
    project_id = events[0]["data"]["projectId"]
    assert events[-1]["type"] == "agent_app_marketplace_install"
    result = events[-1]["data"]
    assert result["projectId"] == result["project"]["id"] == project_id
    assert list(manager.projects) == [project_id]
    assert result["status"] == ("success" if launch_succeeds else "error"), result
    assert manager.projects[project_id].status == (
        "running" if launch_succeeds else "error"
    )
    assert result["project"]["sessionId"] == f"agentapp_{project_id}"
    sessions.create_session.assert_called_once()
    pipeline.assert_awaited_once()
    dispatch.assert_not_called()
    for call in model_calls:
        call.assert_not_called()

    if launch_succeeds:
        ready = [event["data"] for event in events if event["type"] == "agent_app_ready"]
        assert len(ready) == 1
        assert ready[0]["projectId"] == project_id
        assert ready[0]["sessionId"] == result["project"]["sessionId"]
        assert ready[0]["url"] == result["url"] == "http://127.0.0.1:3100"
        adapter._display_chat_message.assert_awaited_once()
    else:
        assert not any(event["type"] == "agent_app_ready" for event in events)
        errors = [event["data"] for event in events if event["type"] == "agent_app_error"]
        assert len(errors) == 1
        assert errors[0]["projectId"] == project_id
        assert "Build failed" in errors[0]["error"]
        adapter._display_chat_message.assert_not_called()

    project_path = Path(result["project"]["path"])
    assert (project_path / "app.txt").read_text() == "Installed app"
    assert (
        json.loads((project_path / "manifest.json").read_text())["marketplaceAppId"]
        == "kanban-board"
    )
    assert calls[0] == source.zip_url("CraftOS-dev", "agent-app-collection")
    assert len(calls) == (2 if before_rename else 1)
