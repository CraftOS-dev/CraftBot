"""Real bundled scaffold → marketplace/package install → native receipt.

No network, agents, live user state, or changes to the upstream package.
--no-start exercises acquisition, sanitization, re-vendoring and registration;
the real lifecycle and task suites cover serving and authenticated operations.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import paths, node_runtime
from app.agent_app import framework, framework_host
from app.agent_app.framework_host import FrameworkHost
from app.agent_app.framework_store import HostStore
from tests.test_agent_app_framework_host import Sessions


@pytest.mark.parametrize("auth_mode", ["none", "multi-user"])
def test_real_scaffold_preserves_creation_form_name_and_access(
    tmp_path, monkeypatch, auth_mode
):
    from pathlib import Path
    from agent_core.core.state.session import StateSession
    from app.agent_app.framework_commands import command

    monkeypatch.setattr(paths, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setenv("A2APP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE", raising=False)
    previous = framework_host._host

    async def check():
        agent = SimpleNamespace(
            session_manager=Sessions(),
            trigger_service=SimpleNamespace(emit=AsyncMock()),
            request_run_stop=AsyncMock(),
        )
        host = FrameworkHost(agent, AsyncMock(), HostStore(tmp_path / "host.sqlite3"))
        try:
            created = await host.request(
                {
                    "operation": "workflow",
                    "activity": "create",
                    "request": "A notes app",
                    "creation": {
                        "name": "QA Notes – chosen name",
                        "authMode": auth_mode,
                    },
                }
            )
            monkeypatch.setattr(
                StateSession,
                "bound",
                lambda: SimpleNamespace(session_id=created["sessionId"]),
            )
            args = [created["path"], "scaffold", "--blueprint", "blueprint-react-node"]
            with pytest.raises(ValueError, match="selected --name"):
                await command("agent-app", args + ["--name", "wrong"])
            assert not Path(created["path"]).exists()
            result = await command("agent-app", args)
            assert result["status"] == "success", result
            manifest = json.loads(
                Path(created["path"], "manifest.json").read_text(encoding="utf-8")
            )
            assert manifest["name"] == "QA Notes – chosen name"
            assert manifest["authMode"] == auth_mode
            assert host.scaffold_arguments("unrelated", args) == args
            different = [str(tmp_path / "another app"), *args[1:]]
            assert host.scaffold_arguments(created["sessionId"], different) == different
        finally:
            await host.close()

    try:
        asyncio.run(check())
    finally:
        framework_host._host = previous


@pytest.mark.parametrize("source_kind", ["folder", "zip", "catalogue"])
def test_real_install_receipt_and_sanitization(tmp_path, monkeypatch, source_kind):
    if node_runtime.resolve() is None:
        pytest.skip("CraftBot Node runtime required")
    monkeypatch.setattr(paths, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setenv("A2APP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE", raising=False)
    old_host = framework_host._host

    async def check():
        cli = framework.configured_cli()
        market = tmp_path / "marketplace with spaces"
        source = market / "fixture"
        market.mkdir()
        scaffold = await cli.run(
            "agent-app",
            [str(source), "scaffold", "--blueprint", "blueprint-react-node"],
            cwd=cli.package_dir,
            timeout=60,
        )
        assert scaffold.ok, scaffold.stderr
        (source / ".agent-token").write_text("publisher-secret", encoding="utf-8")
        (source / "data").mkdir(exist_ok=True)
        (source / "data/private.txt").write_text("publisher data", encoding="utf-8")
        (market / "catalogue.json").write_text(
            json.dumps(
                {
                    "apps": [
                        {
                            "id": "fixture",
                            "name": "Fixture",
                            "folder": "fixture",
                            "agentAppVersion": "0.1.0",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        agent = SimpleNamespace(
            session_manager=Sessions(),
            trigger_service=SimpleNamespace(emit=AsyncMock()),
            request_run_stop=AsyncMock(),
        )
        host = FrameworkHost(agent, AsyncMock(), HostStore(tmp_path / "host.sqlite3"))
        try:
            package = source
            if source_kind == "zip":
                package = tmp_path / "fixture export.zip"
                exported = await cli.run(
                    "agent-app",
                    [str(source), "export", "--out", str(package)],
                    cwd=cli.package_dir,
                )
                assert exported.ok, exported.stderr
                import zipfile

                with zipfile.ZipFile(package) as archive:
                    assert not any(
                        name.endswith(("private.txt", ".agent-token"))
                        for name in archive.namelist()
                    )
            request = (
                {"id": "fixture", "source": str(market)}
                if source_kind == "catalogue"
                else {"from": str(package)}
            )
            await host.start_install({**request, "noStart": True}, "installation")
            await host.jobs["installation"]
            receipt = host.store.get("install", "installation")
            assert receipt["status"] == "success", receipt
            assert receipt["sessionId"]
            assert receipt["result"]["trust"] == (
                "catalogued" if source_kind == "catalogue" else "untrusted"
            )
            assert receipt["result"]["served"] is False
            from pathlib import Path

            installed = Path(receipt["result"]["dir"])
            assert installed != source
            assert not (installed / "data/private.txt").exists()
            assert (installed / ".agent-token").read_text() != "publisher-secret"
            assert (source / ".agent-token").read_text() == "publisher-secret"
            assert len(receipt["steps"]) > 4
            agent.trigger_service.emit.assert_not_awaited()
            snapshot = await framework.list_apps()
            row = next(
                r for r in snapshot["data"]["apps"] if r["path"] == str(installed)
            )
            assert row["status"] == "stopped"
        finally:
            await host.close()

    try:
        asyncio.run(check())
    finally:
        framework_host._host = old_host
