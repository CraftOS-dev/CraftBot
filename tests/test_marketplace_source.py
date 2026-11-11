"""CraftBot's marketplace preference is forwarded to the upstream CLI."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent_app import marketplace_source as source


def test_settings_branch_is_used_when_environment_override_is_absent(monkeypatch):
    monkeypatch.delenv("CRAFTBOT_MARKETPLACE_REF", raising=False)
    monkeypatch.setattr("app.config.get_marketplace_ref", lambda: "staging")
    assert source.ref() == "staging"


def test_configured_branch_is_preserved_across_fallback(monkeypatch):
    monkeypatch.setenv("CRAFTBOT_MARKETPLACE_REF", " preview ")
    monkeypatch.setattr("app.config.get_marketplace_ref", lambda: "staging")
    assert source.ref() == "preview"


@pytest.mark.parametrize("identity,kind,status,expected", [
    ("native-id", "marketplace", "running", True),
    ("native-id", "marketplace", "stopped", True),
    ("replacement-id", "marketplace", "running", False),
    ("native-id", "export", "running", False),
    ("native-id", "marketplace", "missing", False),
])
def test_registry_marketplace_identity_uses_matching_upstream_provenance(tmp_path, identity, kind, status, expected):
    from app.agent_app.framework import _list_apps

    provenance = {"kind": kind, "catalogueId": "kanban-board", "location": "github:example/apps", "ref": "staging"}
    (tmp_path / "manifest.json").write_text(json.dumps({"id": identity, "source": provenance}))
    row = {"id": "native-id", "name": "Renamed board", "path": str(tmp_path), "status": status}
    result = SimpleNamespace(code=0, stderr="", timed_out=False, ok=True, json=lambda: {"ok": True, "apps": [row], "connected": []})
    cli = SimpleNamespace(package_dir=tmp_path, run=AsyncMock(return_value=result))
    response = asyncio.run(_list_apps(cli))
    assert response["status"] == "success"
    assert response["data"]["apps"][0]["id"] == "native-id"
    assert ("marketplace" in row) == expected
    if expected:
        assert row["marketplace"] == {"id": "kanban-board", "location": "github:example/apps", "ref": "staging"}
    # A broken manifest must still leave an actionable registry row.
    (tmp_path / "manifest.json").write_text("not json")
    row.pop("marketplace", None)
    assert asyncio.run(_list_apps(cli))["status"] == "success"
    assert "marketplace" not in row
