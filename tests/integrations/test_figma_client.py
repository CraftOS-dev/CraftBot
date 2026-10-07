"""Captured API shapes; all HTTP is mocked, exports use temporary directories."""

import asyncio
import base64
import time

import httpx
import pytest

from craftos_integrations.config import ConfigStore
from craftos_integrations.helpers import http as http_helpers
from craftos_integrations.providers.figma import client as mod
from craftos_integrations.providers.figma.client import (
    FigmaClient,
    FigmaConfig,
    parse_file_reference,
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mod, "load_config", lambda *a: FigmaConfig())
    instance = FigmaClient()
    instance.bind_credential(
        {"access_token": "fake_pat", "user_id": "1"}, lambda x: None
    )
    return instance


@pytest.fixture
def api(monkeypatch):
    calls = []
    responses = []

    async def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        status, body, headers = responses.pop(0)
        response = httpx.Response(status, json=body, headers=headers)
        if kwargs.get("response_hook"):
            kwargs["response_hook"](response)
        return http_helpers._shape(response, kwargs.get("expected", (200, 201)), None)

    monkeypatch.setattr(mod, "arequest", request)
    return calls, responses


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/design/abc",
        "https://figma.com.evil.test/design/abc",
        "https://www.figma.com/files/team/1",
        "../secret",
        "http://www.figma.com/design/abc",
    ],
)
def test_rejects_non_file_references(url):
    with pytest.raises(ValueError):
        parse_file_reference(url)


def test_url_node_normalization_and_branch_key():
    assert parse_file_reference(
        "https://www.figma.com/design/ABC/name?node-id=12-34"
    ) == {"file_key": "ABC", "node_id": "12:34"}
    assert (
        parse_file_reference(
            "https://www.figma.com/design/BranchKey/title?node-id=I12%3A34%3B56%3A78"
        )["node_id"]
        == "I12:34;56:78"
    )


@pytest.mark.parametrize("status", [401, 403])
def test_pat_folder_metadata_falls_back_to_access_checked_basic_fields(
    client, api, status
):
    calls, responses = api
    responses.extend(
        [
            (status, {"err": "Missing scope"}, {}),
            (200, {"name": "Team folder", "folders": []}, {}),
        ]
    )
    result = asyncio.run(client.get_folder_metadata("123"))
    assert result["result"] == {
        "id": "123",
        "name": "Team folder",
        "partial_metadata": True,
        "source": "folder_listing",
        "unavailable_fields": [
            "thumbnail_url",
            "file_count",
            "updated_at",
            "created_at",
        ],
    }
    assert [call[1] for call in calls] == [
        mod.FIGMA_API + "/v2/folders/123/meta",
        mod.FIGMA_API + "/v2/folders/123/folders",
    ]


@pytest.mark.parametrize("status", [401, 403])
def test_folder_metadata_does_not_fall_back_for_oauth(client, api, status):
    client.bind_credential(
        {"access_token": "fake", "auth_kind": "oauth"}, lambda x: None
    )
    calls, responses = api
    responses.append((status, {"err": "Denied"}, {}))
    result = asyncio.run(client.get_folder_metadata("123"))
    assert "error" in result and result["details"]["status"] == status
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_pat_folder_metadata_fallback_still_requires_valid_token_and_access(
    client, api, status
):
    _, responses = api
    responses.extend([(status, {"err": "scope"}, {}), (status, {"err": "denied"}, {})])
    result = asyncio.run(client.get_folder_metadata("123"))
    assert "error" in result and result["details"]["status"] == status


def test_full_folder_metadata_is_preserved(client, api):
    calls, responses = api
    metadata = {
        "id": "123",
        "name": "Team folder",
        "file_count": 4,
        "updated_at": "2026-10-05",
    }
    responses.append((200, metadata, {}))
    assert asyncio.run(client.get_folder_metadata("123"))["result"] == metadata
    assert len(calls) == 1


def test_version_pagination_url_preserves_secondary_cursor_and_bounds_size(client, api):
    calls, responses = api
    responses.append((200, {"versions": [], "pagination": {}}, {}))
    asyncio.run(
        client.list_versions(
            "ABC",
            limit=200,
            before=mod.FIGMA_API
            + "/v1/files/ABC/versions?before=123&secondary_before=42&column=date&secondary_column=default&page_size=999&ignored=1",
        )
    )
    assert calls[0][1] == mod.FIGMA_API + "/v1/files/ABC/versions"
    assert calls[0][2]["params"] == {
        "before": "123",
        "secondary_before": "42",
        "column": "date",
        "secondary_column": "default",
        "page_size": 100,
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/v1/files/ABC/versions?after=1",
        "http://api.figma.com/v1/files/ABC/versions?after=1",
        "https://api.figma.com/v1/files/OTHER/versions?after=1",
        "https://user:pass@api.figma.com/v1/files/ABC/versions?after=1",
        "https://api.figma.com:444/v1/files/ABC/versions?after=1",
        "https://api.figma.com/v1/files/ABC/versions?page_size=5",
    ],
)
def test_version_pagination_rejects_unrelated_urls_before_http(client, api, url):
    calls, _ = api
    with pytest.raises(ValueError):
        asyncio.run(client.list_versions("ABC", after=url))
    assert calls == []


def test_version_pagination_url_cannot_be_combined_with_another_cursor(client, api):
    calls, _ = api
    with pytest.raises(ValueError):
        asyncio.run(
            client.list_versions(
                "ABC",
                before=mod.FIGMA_API + "/v1/files/ABC/versions?before=123",
                after="other",
            )
        )
    assert calls == []


def test_node_url_supplies_ids_and_depth(client, api):
    calls, responses = api
    responses.append((200, {"nodes": {"12:34": None}}, {}))
    result = asyncio.run(
        client.get_nodes(
            "https://www.figma.com/design/ABC/name?node-id=12-34", version="42"
        )
    )
    assert calls[0][1].endswith("/v1/files/ABC/nodes")
    assert calls[0][2]["params"] == {"ids": "12:34", "depth": 2, "version": "42"}
    assert result["result"]["nodes"]["12:34"] is None


def test_document_budget_is_global_and_does_not_poison_cache(client, api, monkeypatch):
    monkeypatch.setattr(
        mod, "load_config", lambda *a: FigmaConfig(max_document_nodes=2)
    )
    calls, responses = api
    document = {
        "id": "0:0",
        "name": "Root",
        "children": [
            {"id": "1:1", "name": "A", "children": [{"id": "2:2"}]},
            {"id": "3:3"},
        ],
    }
    responses.append((200, {"document": document}, {}))
    first = asyncio.run(client.get_file("ABC"))
    assert first["result"]["returned_nodes"] == 2 and first["result"]["truncated"]
    assert len(first["result"]["document"]["children"]) == 1
    first["result"]["document"]["name"] = "tampered"
    second = asyncio.run(client.get_file("ABC"))
    assert second["result"]["document"]["name"] == "Root"
    assert len(calls) == 1


def test_mutation_clears_cached_reads_and_reply_is_root_comment(client, api):
    calls, responses = api
    responses.extend(
        [
            (200, {"comments": []}, {}),
            (201, {"id": "reply"}, {}),
            (200, {"comments": [{"id": "reply"}]}, {}),
        ]
    )

    async def run():
        await client.list_comments("ABC")
        await client.reply_comment("ABC", "root", "hello")
        return await client.list_comments("ABC")

    assert asyncio.run(run())["result"]["comments"] == [{"id": "reply"}]
    assert calls[1][2]["json"] == {"comment_id": "root", "message": "hello"}
    assert len(calls) == 3


def test_delete_reaction_uses_query_and_accepts_empty_response(client, api):
    calls, responses = api
    responses.append((204, None, {}))
    result = asyncio.run(client.delete_comment_reaction("ABC", "123", ":heart:"))
    assert result["ok"] and calls[0][0] == "DELETE"
    assert calls[0][2]["params"] == {"emoji": ":heart:"}
    assert calls[0][2]["json"] is None


def test_local_pagination_preserves_library_metadata(client, api):
    _, responses = api
    responses.append(
        (
            200,
            {
                "status": 200,
                "error": False,
                "meta": {"components": [{"key": str(i)} for i in range(5)]},
            },
            {},
        )
    )
    result = asyncio.run(client.list_file_components("ABC", limit=2, offset=1))[
        "result"
    ]
    assert result["meta"]["components"] == [{"key": "1"}, {"key": "2"}]
    assert result["pagination"] == {"total": 5, "next_offset": 3, "local": True}


def test_server_pagination_is_forwarded_without_losing_cursors(client, api):
    calls, responses = api
    responses.append(
        (200, {"meta": {"components": [], "cursor": {"after": "next"}}}, {})
    )
    result = asyncio.run(
        client.list_team_components(
            "https://www.figma.com/files/user/team/123", limit=300, after="cursor"
        )
    )
    assert calls[0][1].endswith("/v1/teams/123/components")
    assert calls[0][2]["params"] == {"page_size": 100, "after": "cursor"}
    assert result["result"]["meta"]["cursor"]["after"] == "next"


def test_reads_honor_retry_after_but_writes_are_never_replayed(
    client, api, monkeypatch
):
    calls, responses = api
    delays = []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(mod.asyncio, "sleep", sleep)
    responses.extend(
        [
            (429, {}, {"Retry-After": "2"}),
            (200, {"id": "1"}, {}),
            (429, {}, {"Retry-After": "60"}),
        ]
    )
    assert asyncio.run(client.get_current_user())["ok"]
    error = asyncio.run(client.post_comment("ABC", "hello"))
    assert "60 seconds" in error["error"] and delays == [2]
    assert len(calls) == 3


def test_long_rate_limit_returns_actionable_error_without_sleep(client, api):
    calls, responses = api
    responses.append((429, {}, {"Retry-After": "3600"}))
    result = asyncio.run(client.get_current_user())
    assert result["details"]["retry_after"] == 3600 and len(calls) == 1


@pytest.mark.parametrize("status", [401, 403, 404])
def test_access_errors_do_not_retry_blindly(client, api, status):
    calls, responses = api
    responses.append((status, {}, {}))
    assert "error" in asyncio.run(client.get_current_user())
    assert len(calls) == 1


def test_export_reports_individual_failed_nodes(client, api):
    _, responses = api
    responses.append(
        (200, {"images": {"1:2": "https://assets.figma.com/a.png", "3:4": None}}, {})
    )
    result = asyncio.run(client.export_images("ABC", ["1-2", "3:4"]))
    assert result["result"]["failed_node_ids"] == ["3:4"]


def test_downloads_are_unique_and_never_forward_credentials(
    client, monkeypatch, tmp_path
):
    async def export(*a, **k):
        return {
            "ok": True,
            "result": {
                "images": {"1:2": "https://assets.figma.com/a.png"},
                "failed_node_ids": [],
            },
        }

    monkeypatch.setattr(client, "export_images", export)

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"image-bytes"

    def stream(method, url, **kwargs):
        assert "headers" not in kwargs and not kwargs["follow_redirects"]
        return Stream()

    monkeypatch.setattr(mod.httpx, "stream", stream)
    first = asyncio.run(client.download_images("ABC", str(tmp_path), ["1:2"]))
    second = asyncio.run(client.download_images("ABC", str(tmp_path), ["1:2"]))
    assert first["result"]["files"] != second["result"]["files"]
    assert all(p.read_bytes() == b"image-bytes" for p in tmp_path.iterdir())


def test_refresh_is_single_flight_and_persists_new_token(client, api, monkeypatch):
    monkeypatch.setattr(
        ConfigStore,
        "_oauth",
        {"FIGMA_CLIENT_ID": "app", "FIGMA_CLIENT_SECRET": "secret"},
    )
    updates = []
    client.bind_credential(
        {
            "user_id": "1",
            "auth_kind": "oauth",
            "access_token": "expired",
            "refresh_token": "refresh",
            "token_expiry": 1,
        },
        updates.append,
    )
    calls, responses = api
    responses.append((200, {"access_token": "new", "expires_in": 3600}, {}))

    async def run():
        return await asyncio.gather(
            client.refresh_access_token(), client.refresh_access_token()
        )

    assert all(r["ok"] for r in asyncio.run(run()))
    assert len(calls) == 1 and len(updates) == 1
    assert calls[0][1].endswith("/v1/oauth/refresh")
    assert (
        calls[0][2]["headers"]["Authorization"]
        == "Basic " + base64.b64encode(b"app:secret").decode()
    )
    assert client._headers() == {"Authorization": "Bearer new"}
    assert updates[0]["refresh_token"] == "refresh"
    assert updates[0]["token_expiry"] > time.time()


@pytest.mark.parametrize("failure", ["interrupted", "oversized"])
def test_download_removes_partial_files_and_reports_partial_success(
    client, monkeypatch, tmp_path, failure
):
    async def export(*a, **k):
        return {
            "ok": True,
            "result": {
                "images": {
                    "1:2": "https://assets.figma.com/good.png",
                    "3:4": "https://assets.figma.com/bad.png",
                },
                "failed_node_ids": [],
            },
        }

    monkeypatch.setattr(client, "export_images", export)

    class Stream:
        def __init__(self, url):
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            if self.url.endswith("good.png"):
                yield b"complete"
            elif failure == "interrupted":
                yield b"partial"
                raise httpx.ReadError("Connection lost")
            else:
                chunk = b"x" * (1024 * 1024)
                for _ in range(51):
                    yield chunk

    monkeypatch.setattr(mod.httpx, "stream", lambda method, url, **kw: Stream(url))
    result = asyncio.run(client.download_images("ABC", str(tmp_path), ["1:2", "3:4"]))
    assert result["ok"] and result["result"]["failed_node_ids"] == ["3:4"]
    files = list(tmp_path.iterdir())
    assert len(files) == 1 and files[0].read_bytes() == b"complete"


def test_download_refuses_untrusted_hosts_before_opening_connection(
    client, monkeypatch, tmp_path
):
    async def export(*a, **k):
        return {
            "ok": True,
            "result": {
                "images": {"1:2": "https://figma.com.evil.test/image.png"},
                "failed_node_ids": [],
            },
        }

    def fail(*a, **k):
        pytest.fail("Unexpected connection to untrusted asset host")

    monkeypatch.setattr(client, "export_images", export)
    monkeypatch.setattr(mod.httpx, "stream", fail)
    result = asyncio.run(client.download_images("ABC", str(tmp_path), ["1:2"]))
    assert "error" in result and result["details"]["failed_node_ids"] == ["1:2"]
    assert not list(tmp_path.iterdir())


def test_download_rejects_relative_directory_before_export(client, monkeypatch):
    async def fail(*a, **k):
        pytest.fail("Invalid output directory must not trigger an export")

    monkeypatch.setattr(client, "export_images", fail)
    with pytest.raises(ValueError, match="absolute"):
        asyncio.run(client.download_images("ABC", "relative", ["1:2"]))


def test_failed_refresh_keeps_existing_credential(client, api, monkeypatch):
    monkeypatch.setattr(
        ConfigStore,
        "_oauth",
        {"FIGMA_CLIENT_ID": "app", "FIGMA_CLIENT_SECRET": "secret"},
    )
    updates = []
    client.bind_credential(
        {
            "user_id": "1",
            "auth_kind": "oauth",
            "access_token": "expired",
            "refresh_token": "refresh",
            "token_expiry": 1,
        },
        updates.append,
    )
    _, responses = api
    responses.append((400, {"error": "invalid_grant"}, {}))
    assert "error" in asyncio.run(client.refresh_access_token())
    assert not updates and client._load().access_token == "expired"


def test_http_response_hook_preserves_existing_envelope(monkeypatch):
    response = httpx.Response(429, text="rate limit", headers={"Retry-After": "20"})
    monkeypatch.setattr(http_helpers.httpx, "request", lambda *a, **k: response)
    captured = []
    plain = http_helpers.request("GET", "https://example.test")
    hooked = asyncio.run(
        http_helpers.arequest(
            "GET",
            "https://example.test",
            response_hook=lambda r: captured.append(r.headers["Retry-After"]),
        )
    )
    assert plain == hooked == {"error": "API error: 429", "details": "rate limit"}
    assert captured == ["20"]
