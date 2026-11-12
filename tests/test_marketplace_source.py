"""CraftBot's marketplace preference is forwarded to the upstream CLI."""

import asyncio
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.error import HTTPError

import pytest

from app.agent_app import marketplace_source as source


@pytest.mark.parametrize(
    "configured,expected", [(None, "main"), ("staging", "staging")]
)
def test_only_settings_selects_the_marketplace_branch(
    monkeypatch, configured, expected
):
    monkeypatch.setenv("CRAFTBOT_MARKETPLACE_REF", " preview ")
    monkeypatch.setattr("app.config.get_marketplace_ref", lambda: configured)
    assert source.ref() == expected


@pytest.mark.parametrize(
    "args,expected,lookup",
    [
        (
            ["inspect", "--from", "https://github.com/owner/repo"],
            "release/default",
            True,
        ),
        (
            ["install", "--from", "https://www.github.com/owner/repo.git/"],
            "release/default",
            True,
        ),
        (
            ["inspect", "--from", "https://github.com/owner/repo/tree/master/app"],
            "",
            False,
        ),
        (
            ["install", "--from", "git+https://github.com/owner/repo.git#release"],
            "",
            False,
        ),
        (["inspect", "--from", "C:/imports/app.zip"], "", False),
        (["install", "kanban-board"], "staging", False),
        (["marketplace", "list"], "staging", False),
    ],
)
def test_import_branch_is_isolated_from_marketplace(
    tmp_path, monkeypatch, args, expected, lookup
):
    from app import node_runtime
    from app.agent_app import framework_cli

    # Capture the real subprocess boundary without downloading or installing apps.
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/agent-app.js").write_text(
        "import json, os, sys\n"
        "print(json.dumps({'args': sys.argv[1:], 'ref': os.environ['A2APP_MARKETPLACE_REF']}))\n"
    )
    monkeypatch.setattr(
        node_runtime,
        "resolve",
        lambda: SimpleNamespace(
            node=sys.executable,
            version="v24.0.0",
            bin_dir=str(Path(sys.executable).parent),
        ),
    )
    monkeypatch.setattr("app.config.get_framework_toolkits_dir", lambda: "configured")
    monkeypatch.setattr("app.config.get_marketplace_ref", lambda: "staging")
    requests = []

    def metadata(request, *, timeout):
        assert lookup, (
            "Explicit sources and marketplace commands must not resolve a default branch"
        )
        assert request.full_url == "https://api.github.com/repos/owner/repo"
        assert timeout == 20
        requests.append(request)
        return io.BytesIO(b'{"default_branch":"release/default"}')

    monkeypatch.setattr(framework_cli, "urlopen", metadata)
    cli = framework_cli.AgentAppCLI(tmp_path, home=tmp_path / "home")
    result = asyncio.run(cli.run("agent-app", args, cwd=tmp_path))
    assert result.ok, result.stderr
    assert result.json() == {"args": args, "ref": expected}
    assert len(requests) == int(lookup)


@pytest.mark.parametrize("response", [b"{}", b"not json", None])
def test_import_default_branch_failure_does_not_guess_main(monkeypatch, response):
    from app.agent_app import framework_cli

    def unavailable(*args, **kwargs):
        if response is None:
            raise HTTPError(
                "https://api.github.com/repos/owner/repo", 403, "rate limited", {}, None
            )
        return io.BytesIO(response)

    monkeypatch.setattr(framework_cli, "urlopen", unavailable)
    with pytest.raises(
        ValueError, match="Could not read the default branch.*Retry, or paste"
    ):
        framework_cli._import_default_ref("https://github.com/owner/repo")


@pytest.mark.parametrize(
    "identity,kind,status,expected",
    [
        ("native-id", "marketplace", "running", True),
        ("native-id", "marketplace", "stopped", True),
        ("replacement-id", "marketplace", "running", False),
        ("native-id", "export", "running", False),
        ("native-id", "marketplace", "missing", False),
    ],
)
def test_registry_marketplace_identity_uses_matching_upstream_provenance(
    tmp_path, identity, kind, status, expected
):
    from app.agent_app.framework import _list_apps

    provenance = {
        "kind": kind,
        "catalogueId": "kanban-board",
        "location": "github:example/apps",
        "ref": "staging",
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps({"id": identity, "source": provenance})
    )
    row = {
        "id": "native-id",
        "name": "Renamed board",
        "path": str(tmp_path),
        "status": status,
    }
    result = SimpleNamespace(
        code=0,
        stderr="",
        timed_out=False,
        ok=True,
        json=lambda: {"ok": True, "apps": [row], "connected": []},
    )
    cli = SimpleNamespace(package_dir=tmp_path, run=AsyncMock(return_value=result))
    response = asyncio.run(_list_apps(cli))
    assert response["status"] == "success"
    assert response["data"]["apps"][0]["id"] == "native-id"
    assert ("marketplace" in row) == expected
    if expected:
        assert row["marketplace"] == {
            "id": "kanban-board",
            "location": "github:example/apps",
            "ref": "staging",
        }
    # A broken manifest must still leave an actionable registry row.
    (tmp_path / "manifest.json").write_text("not json")
    row.pop("marketplace", None)
    assert asyncio.run(_list_apps(cli))["status"] == "success"
    assert "marketplace" not in row
