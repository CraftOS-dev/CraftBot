import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.agent_app import framework, framework_profile
from app.agent_app.framework_cli import CLIResult
from tests import test_agent_app_framework_host as host_tests

fixture = host_tests.fixture


def test_profile_uses_upstream_export_and_never_copies_host_credentials(
    fixture, tmp_path, monkeypatch
):
    host, cli, row = fixture
    root = tmp_path / "bundle"
    root.mkdir()
    monkeypatch.setattr(
        framework,
        "_list_apps",
        AsyncMock(return_value={"status": "success", "data": {"apps": [row]}}),
    )

    async def run(surface, args, **kwargs):
        assert surface == "agent-app" and args[:3] == [row["path"], "export", "--out"]
        Path(args[3]).write_bytes(b"upstream sanitized package")
        return CLIResult(0, '{"ok":true}', "")

    cli.run.side_effect = run

    async def check():
        await host.attach(row["path"], row["id"])
        host.store.put("delivery", "private", {"taskId": "private work"})
        entries = await framework_profile.export_packages(root)
        assert entries[0]["name"] == row["name"]
        assert sorted(p.name for p in (root / "framework_apps").iterdir()) == [
            "0000.zip",
            "index.json",
        ]
        assert "path" not in entries[0] and "sessionId" not in entries[0]

    asyncio.run(check())


def test_profile_import_stages_packages_without_running_or_overwriting_apps(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(framework_profile.paths, "STATE_ROOT", tmp_path / "state")
    root = tmp_path / "bundle" / "framework_apps"
    root.mkdir(parents=True)
    content = b"untrusted package"
    (root / "0000.zip").write_bytes(content)
    index = [
        {
            "file": "0000.zip",
            "name": "Shared app",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    ]
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
    result = framework_profile.stage_packages(root.parent)
    assert Path(result[0]["from"]).read_bytes() == content
    assert result[0]["name"] == "Shared app"
    assert not (tmp_path / "state/registry.json").exists()


@pytest.mark.parametrize(
    "filename", ["../outside.zip", "..\\outside.zip", "/outside.zip", "C:\\outside.zip"]
)
def test_profile_refuses_traversal_before_staging(tmp_path, monkeypatch, filename):
    monkeypatch.setattr(framework_profile.paths, "STATE_ROOT", tmp_path / "state")
    root = tmp_path / "bundle/framework_apps"
    root.mkdir(parents=True)
    (root / "index.json").write_text(json.dumps([{"file": filename}]), encoding="utf-8")
    with pytest.raises(ValueError, match="filename"):
        framework_profile.stage_packages(root.parent)
    assert not (tmp_path / "state").exists()
