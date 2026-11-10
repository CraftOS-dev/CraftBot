"""Native references use fresh identities and no app records or credentials."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent_app import framework, framework_host
from app.agent_app.framework_references import describe_reference, reference_app
from app.agent_app.framework_store import HostStore


def test_native_identity_and_retired_id_resolve_only_in_current_profile(
    tmp_path, monkeypatch
):
    home, app = tmp_path / "home", tmp_path / "app"
    app.mkdir()
    (app / "manifest.json").write_text(
        json.dumps(
            {
                "modules": [
                    {"name": "notes", "summary": "Notes", "credential": "never copied"}
                ],
                "credentials": "never copied",
            }
        ),
        encoding="utf-8",
    )
    row = {"id": "new", "name": "Notes", "path": str(app), "status": "running"}
    store = HostStore(tmp_path / "host.sqlite3")
    monkeypatch.setattr(framework_host, "_host", SimpleNamespace(store=store))
    monkeypatch.setattr(framework, "configured_cli", lambda: SimpleNamespace(home=home))
    listing = AsyncMock(return_value={"status": "success", "data": {"apps": [row]}})
    monkeypatch.setattr(framework, "_list_apps", listing)
    receipt = {
        "legacyId": "old",
        "home": str(home),
        "target": str(app),
        "appId": "new",
        "phase": "complete",
    }
    store.put("migration", "migration", receipt)

    async def check():
        assert await reference_app("framework:" + json.dumps([str(app), "new"])) == row
        assert await reference_app("old") == row
        detail = await describe_reference(row)
        assert "never copied" not in json.dumps(detail)
        assert detail["operationDiscovery"]["args"] == [str(app)]
        with pytest.raises(ValueError, match="no longer registered"):
            await reference_app("framework:" + json.dumps([str(app), "old"]))
        store.put("migration", "migration", {**receipt, "phase": "rolled_back"})
        assert await reference_app("old") is None
        store.put(
            "migration", "migration", {**receipt, "home": str(tmp_path / "other")}
        )
        assert await reference_app("old") is None
        listing.reset_mock()
        assert await reference_app("unrelated") is None
        listing.assert_not_called()

    asyncio.run(check())


@pytest.mark.parametrize("identity", ["{}", "[1,2]", '["path"]', "not-json"])
def test_invalid_native_identity_is_rejected(tmp_path, monkeypatch, identity):
    monkeypatch.setattr(
        framework, "configured_cli", lambda: SimpleNamespace(home=tmp_path)
    )
    with pytest.raises(ValueError, match="Invalid framework"):
        asyncio.run(reference_app("framework:" + identity))
