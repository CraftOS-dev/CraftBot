"""Exercise every public Figma action through real account routing.

Only vendor HTTP and asset streaming are replaced; the provider, operation
dispatch, request shaping, pagination and filesystem writes are real.
"""

import asyncio
from pathlib import Path

import httpx
import pytest

from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.helpers.http import _shape
from craftos_integrations.providers.figma import FigmaProvider
from craftos_integrations.providers.figma import client as mod


FILE = {"file_key": "ABC"}
NODE = {**FILE, "node_ids": ["1-2"]}
COMMENT = {**FILE, "comment_id": "123"}
DOCUMENT = {"id": "1:2", "name": "Hero", "type": "FRAME"}

# Explicit HTTP expectations provide a contract check independent of method
# names: actions have to route an account and translate the public inputs.
CASES = [
    (
        "parse_figma_url",
        {"file_key": "https://www.figma.com/design/ABC/Test?node-id=1-2"},
        None,
        None,
        {},
        None,
        {},
    ),
    (
        "get_figma_file",
        {**FILE, "version": "v2"},
        "GET",
        "/v1/files/ABC",
        {"depth": 2, "version": "v2", "branch_data": "true"},
        None,
        {"document": DOCUMENT},
    ),
    (
        "get_figma_file_metadata",
        FILE,
        "GET",
        "/v1/files/ABC/meta",
        {},
        None,
        {"name": "QA file"},
    ),
    (
        "get_figma_nodes",
        NODE,
        "GET",
        "/v1/files/ABC/nodes",
        {"ids": "1:2", "depth": 2},
        None,
        {"nodes": {"1:2": {"document": DOCUMENT}, "9:9": None}},
    ),
    (
        "find_figma_nodes",
        {**FILE, "name": "hero"},
        "GET",
        "/v1/files/ABC",
        {"depth": 4, "branch_data": "true"},
        None,
        {"document": DOCUMENT},
    ),
    (
        "list_figma_versions",
        {**FILE, "limit": 2, "after": "next"},
        "GET",
        "/v1/files/ABC/versions",
        {"page_size": 2, "after": "next"},
        None,
        {"versions": [{"id": "v2"}], "pagination": {"next_page": "another"}},
    ),
    (
        "export_figma_images",
        NODE,
        "GET",
        "/v1/images/ABC",
        {"ids": "1:2", "format": "png", "scale": 1},
        None,
        {"images": {"1:2": "https://assets.figma.com/test.png"}},
    ),
    (
        "get_figma_image_fills",
        FILE,
        "GET",
        "/v1/files/ABC/images",
        {},
        None,
        {"meta": {"images": {"imageRef": "https://assets.figma.com/fill.png"}}},
    ),
    (
        "download_figma_images",
        NODE,
        "GET",
        "/v1/images/ABC",
        {"ids": "1:2", "format": "png", "scale": 1},
        None,
        {"images": {"1:2": "https://assets.figma.com/test.png"}},
    ),
    (
        "list_figma_comments",
        FILE,
        "GET",
        "/v1/files/ABC/comments",
        {"as_md": "true"},
        None,
        {"comments": [{"id": "123", "message": "QA"}]},
    ),
    (
        "post_figma_comment",
        {
            **FILE,
            "message": "QA",
            "client_meta": {"node_id": "1:2", "node_offset": {"x": 0, "y": 0}},
        },
        "POST",
        "/v1/files/ABC/comments",
        {},
        {
            "message": "QA",
            "client_meta": {"node_id": "1:2", "node_offset": {"x": 0, "y": 0}},
        },
        {"id": "123"},
    ),
    (
        "reply_figma_comment",
        {**COMMENT, "message": "Reply"},
        "POST",
        "/v1/files/ABC/comments",
        {},
        {"message": "Reply", "comment_id": "123"},
        {"id": "124"},
    ),
    (
        "delete_figma_comment",
        COMMENT,
        "DELETE",
        "/v1/files/ABC/comments/123",
        {},
        None,
        {},
    ),
    (
        "list_figma_comment_reactions",
        {**COMMENT, "cursor": "page2"},
        "GET",
        "/v1/files/ABC/comments/123/reactions",
        {"cursor": "page2"},
        None,
        {"reactions": [{"emoji": ":heart:"}], "pagination": {"next_page": "page3"}},
    ),
    (
        "add_figma_comment_reaction",
        {**COMMENT, "emoji": ":heart:"},
        "POST",
        "/v1/files/ABC/comments/123/reactions",
        {},
        {"emoji": ":heart:"},
        {},
    ),
    (
        "delete_figma_comment_reaction",
        {**COMMENT, "emoji": ":heart:"},
        "DELETE",
        "/v1/files/ABC/comments/123/reactions",
        {"emoji": ":heart:"},
        None,
        {},
    ),
    (
        "get_figma_current_user",
        {},
        "GET",
        "/v1/me",
        {},
        None,
        {"id": "qa-user", "handle": "QA"},
    ),
    (
        "list_figma_team_folders",
        {"team_id": "123"},
        "GET",
        "/v2/teams/123/folders",
        {},
        None,
        {"name": "QA team", "folders": [{"id": "456"}]},
    ),
    (
        "list_figma_subfolders",
        {"folder_id": "456"},
        "GET",
        "/v2/folders/456/folders",
        {},
        None,
        {"name": "QA folder", "folders": [{"id": "457"}]},
    ),
    (
        "list_figma_folder_files",
        {"folder_id": "456"},
        "GET",
        "/v2/folders/456/files",
        {},
        None,
        {"name": "QA folder", "files": [{"key": "ABC"}]},
    ),
    (
        "get_figma_folder_metadata",
        {"folder_id": "456"},
        "GET",
        "/v2/folders/456/meta",
        {},
        None,
        {"name": "QA folder"},
    ),
]

for resource, singular in (
    ("components", "component"),
    ("component_sets", "component_set"),
    ("styles", "style"),
):
    CASES.extend(
        [
            (
                f"list_figma_team_{resource}",
                {"team_id": "123", "limit": 2, "before": "previous"},
                "GET",
                f"/v1/teams/123/{resource}",
                {"page_size": 2, "before": "previous"},
                None,
                {
                    "status": 200,
                    "error": False,
                    "meta": {
                        resource: [{"key": "asset"}],
                        "cursor": {"before": "older"},
                    },
                },
            ),
            (
                f"list_figma_file_{resource}",
                {**FILE, "limit": 1, "offset": 1},
                "GET",
                f"/v1/files/ABC/{resource}",
                {},
                None,
                {
                    "status": 200,
                    "error": False,
                    "meta": {
                        resource: [
                            {"key": "first"},
                            {"key": "second"},
                            {"key": "third"},
                        ]
                    },
                },
            ),
            (
                f"get_figma_{singular}",
                {f"{singular}_key": "asset"},
                "GET",
                f"/v1/{resource}/asset",
                {},
                None,
                {
                    "status": 200,
                    "error": False,
                    "meta": {"key": "asset", "node_id": "1:2"},
                },
            ),
        ]
    )


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "load_config", lambda *a: mod.FigmaConfig())
    instance = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path / "credentials"),
        providers=[FigmaProvider()],
    )
    instance.store_credential(
        "figma", "qa-user", {"user_id": "qa-user", "access_token": "qa_fake_pat"}
    )
    instance.set_alias("figma", "qa-user", "qa")
    return instance


def test_coverage_includes_every_registered_operation():
    assert {case[0] for case in CASES} == {
        op.name for op in FigmaProvider().operations() if "figma_canvas" not in op.tags
    }
    assert len(CASES) == 30


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_public_operation_contract(system, monkeypatch, tmp_path, case):
    name, inputs, method, path, params, payload, body = case
    calls = []

    async def request(actual_method, url, **kwargs):
        calls.append((actual_method, url, kwargs))
        response = httpx.Response(204 if actual_method == "DELETE" else 200, json=body)
        kwargs["response_hook"](response)
        return _shape(response, kwargs["expected"], None)

    class AssetStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"qa-export"

    def asset_stream(actual_method, url, **kwargs):
        assert actual_method == "GET" and url == "https://assets.figma.com/test.png"
        assert "headers" not in kwargs and kwargs["follow_redirects"] is False
        return AssetStream()

    monkeypatch.setattr(mod, "arequest", request)
    monkeypatch.setattr(mod.httpx, "stream", asset_stream)
    inputs = dict(inputs)
    if name == "download_figma_images":
        inputs["output_dir"] = str(tmp_path / "exports")
    result = asyncio.run(system.execute("figma", name, inputs, account="qa"))
    assert result["status"] == "success", result
    if method is None:
        assert not calls and result["result"] == {"file_key": "ABC", "node_id": "1:2"}
        return
    assert len(calls) == 1
    actual_method, url, kwargs = calls[0]
    assert actual_method == method and url == mod.FIGMA_API + path
    assert kwargs["headers"] == {"X-Figma-Token": "qa_fake_pat"}
    assert kwargs["params"] == params and kwargs["json"] == payload
    data = result["result"]
    if name == "download_figma_images":
        assert Path(data["files"]["1:2"]).read_bytes() == b"qa-export"
    elif name.startswith("list_figma_file_"):
        resource = name.removeprefix("list_figma_file_")
        assert data["meta"][resource] == [{"key": "second"}]
        assert data["pagination"]["next_offset"] == 2
    elif name == "find_figma_nodes":
        assert data["nodes"][0]["id"] == "1:2"
        assert data["search_scope"] == "fetched_tree"
    elif name == "get_figma_nodes":
        assert data["nodes"]["9:9"] is None
        assert data["returned_nodes"] == 1
    elif name == "export_figma_images":
        assert data["failed_node_ids"] == [] and data["temporary_urls"]
    elif body.get("pagination"):
        assert data["pagination"] == body["pagination"]


@pytest.mark.parametrize(
    "name,inputs",
    [
        ("get_figma_file", {**FILE, "depth": 0}),
        ("get_figma_nodes", {**FILE, "node_ids": ["../bad"]}),
        ("export_figma_images", {**NODE, "format": "exe"}),
        ("export_figma_images", {**NODE, "scale": 5}),
        ("post_figma_comment", {**FILE, "message": " "}),
        ("reply_figma_comment", {**FILE, "comment_id": "", "message": "QA"}),
        ("list_figma_team_folders", {"team_id": "https://evil.test/team/123"}),
        ("get_figma_file_metadata", {"file_key": "https://evil.test/design/ABC"}),
    ],
)
def test_invalid_action_inputs_fail_before_http(system, monkeypatch, name, inputs):
    async def fail(*args, **kwargs):
        pytest.fail("Invalid input must not contact Figma")

    monkeypatch.setattr(mod, "arequest", fail)
    result = asyncio.run(system.execute("figma", name, inputs, account="qa"))
    assert result["status"] == "error" and result["message"]
