"""Reset includes registry apps and never bypasses their backup/removal flow."""

import asyncio
import hashlib
import json
import socket
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import paths
from app.agent_app import framework, framework_host
from app.agent_app.framework_host import FrameworkHost
from app.agent_app.framework_store import HostStore
from app.agent_base import AgentBase
from tests.test_agent_app_framework_host import Sessions, fixture as host_fixture

fixture = host_fixture


def test_reset_removes_present_and_missing_apps_and_reports_failed_backup(
    fixture, monkeypatch
):
    host, _, row = fixture
    missing = {
        **row,
        "id": "missing",
        "path": row["path"] + "-missing",
        "status": "missing",
    }
    failed = {
        **row,
        "id": "failed",
        "path": row["path"] + "-failed",
        "name": "Keep my data",
    }
    monkeypatch.setattr(
        framework,
        "list_apps",
        AsyncMock(
            return_value={
                "status": "success",
                "data": {
                    "apps": [row, missing, failed],
                    "connected": [{"id": "remote"}],
                },
            }
        ),
    )
    requests = []

    async def manage(request):
        requests.append(request)
        if request["appId"] == "failed":
            raise RuntimeError("Backup failed")
        return {"status": "success", "data": {"ok": True}}

    host.request = manage
    result = asyncio.run(host.reset_apps())
    assert result == {"deleted": 2, "failures": ["Keep my data: Backup failed"]}
    assert [r["verb"] for r in requests] == ["remove", "forget", "remove"]
    assert all(r["confirm"] == r["appId"] and r["stopFirst"] for r in requests)
    assert not host.resetting


def test_reset_cancels_install_before_listing_and_blocks_new_work(fixture, monkeypatch):
    host, _, _ = fixture
    events = []

    async def install():
        try:
            await asyncio.Event().wait()
        finally:
            events.append("install stopped")

    async def snapshot():
        assert events == ["install stopped"]
        with pytest.raises(RuntimeError, match="reset"):
            await host.start_install({"id": "new"}, "new")
        with pytest.raises(RuntimeError, match="reset"):
            await host.workflow("create", "new")
        return {"status": "success", "data": {"apps": []}}

    monkeypatch.setattr(framework, "list_apps", snapshot)

    async def check():
        host.jobs["install"] = asyncio.create_task(install())
        await asyncio.sleep(0)
        assert await host.reset_apps() == {"deleted": 0, "failures": []}

    asyncio.run(check())


def test_reset_stops_pending_creation_before_registry_snapshot(fixture, monkeypatch):
    host, _, _ = fixture
    session = host.agent.session_manager.create_session(
        session_type="agent_app", title="Building", agent_app_framework_pending=True
    )
    host.agent.delete_session = AsyncMock(return_value=True)

    async def snapshot():
        host.agent.request_run_stop.assert_awaited_once_with(session.id)
        return {"status": "success", "data": {"apps": []}}

    monkeypatch.setattr(framework, "list_apps", snapshot)
    assert asyncio.run(host.reset_apps()) == {"deleted": 0, "failures": []}
    host.agent.delete_session.assert_awaited_once_with(session.id)


@pytest.mark.parametrize("legacy", [True, False])
def test_agent_reset_includes_framework_even_without_legacy_manager(
    monkeypatch, legacy
):
    agent = AgentBase.__new__(AgentBase)
    agent.framework_host = SimpleNamespace(
        reset_apps=AsyncMock(return_value={"deleted": 2, "failures": []})
    )
    manager = SimpleNamespace(
        list_projects=lambda: [SimpleNamespace(id="legacy")],
        delete_project=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.agent_app.get_agent_app_manager", lambda: manager if legacy else None
    )
    assert asyncio.run(agent._delete_all_agent_app_projects()) == (3 if legacy else 2)


def test_selected_reset_reports_failure_and_preserves_registered_workspace_app(
    tmp_path, monkeypatch
):
    agent = AgentBase.__new__(AgentBase)
    agent._delete_all_agent_app_projects = AsyncMock(
        side_effect=RuntimeError("Backup failed")
    )
    app = tmp_path / "workspace" / "projects" / "app"
    app.mkdir(parents=True)
    (app / "important.txt").write_text("keep")
    (tmp_path / "workspace" / "scratch.txt").write_text("discard")
    agent._framework_app_paths = AsyncMock(return_value=[str(app)])
    monkeypatch.setattr("app.agent_base.AGENT_FILE_SYSTEM_PATH", tmp_path)
    with pytest.raises(RuntimeError, match="Reset incomplete.*Backup failed"):
        asyncio.run(agent._reset_selected_components(["agentapp", "workspace"]))
    assert (app / "important.txt").read_text() == "keep"
    assert not (tmp_path / "workspace" / "scratch.txt").exists()


def test_workspace_only_reset_keeps_apps_and_registry_failure_keeps_workspace(
    tmp_path, monkeypatch
):
    agent = AgentBase.__new__(AgentBase)
    agent._delete_all_agent_app_projects = AsyncMock()
    agent._framework_app_paths = AsyncMock(
        side_effect=RuntimeError("Registry unavailable")
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "keep.txt").write_text("keep")
    monkeypatch.setattr("app.agent_base.AGENT_FILE_SYSTEM_PATH", tmp_path)
    with pytest.raises(RuntimeError, match="Registry unavailable"):
        asyncio.run(agent._reset_selected_components(["workspace"]))
    agent._delete_all_agent_app_projects.assert_not_awaited()
    assert (workspace / "keep.txt").exists()


def test_real_registry_reset_archives_data_and_forgets_stale_entry(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(paths, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setenv("A2APP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE", raising=False)
    previous = framework_host._host

    async def check():
        cli = framework.configured_cli()
        agent = SimpleNamespace(
            session_manager=Sessions(),
            request_run_stop=AsyncMock(),
            delete_session=AsyncMock(return_value=True),
        )
        host = FrameworkHost(agent, AsyncMock(), HostStore(tmp_path / "host.sqlite3"))
        try:
            apps = [tmp_path / "present", tmp_path / "missing"]
            for app in apps:
                result = await cli.run(
                    "agent-app",
                    [str(app), "scaffold", "--blueprint", "blueprint-react-node"],
                    cwd=cli.package_dir,
                )
                assert result.ok, result.stderr
                manifest = json.loads((app / "manifest.json").read_text())
                await host.attach(str(app), manifest["id"])
            (apps[0] / "data").mkdir(exist_ok=True)
            (apps[0] / "data" / "important.txt").write_text("user data")
            (apps[1] / "manifest.json").unlink()
            result = await host.reset_apps()
            assert result == {"deleted": 2, "failures": []}
            assert not apps[0].exists()
            assert apps[1].exists()  # Forget cannot delete unrecognised files.
            assert (await framework.list_apps())["data"]["apps"] == []
            backups = list((tmp_path / "home" / "removed").rglob("important.txt"))
            assert len(backups) == 1 and backups[0].read_text() == "user data"
            assert agent.request_run_stop.await_count == 2
            assert agent.delete_session.await_count == 2
            assert all(
                not a.get("autoStart") and not a.get("tasksAllowed")
                for a in host.store.all("attachment")
            )
        finally:
            await host.close()

    try:
        asyncio.run(check())
    finally:
        framework_host._host = previous


def test_real_reset_stops_dev_server_that_locks_app_directory(tmp_path, monkeypatch):
    """Reproduce EBUSY on Windows, then reset through the real packaged CLI."""
    monkeypatch.setattr(paths, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setenv("A2APP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE", raising=False)
    home, app, toolkit = tmp_path / "home", tmp_path / "app", tmp_path / "toolkit"
    for folder in (home, app / ".a2app", app / "data", toolkit):
        folder.mkdir(parents=True)
    assert app.resolve().is_relative_to(tmp_path.resolve())
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    manifest = {"id": "reset-dev", "name": "Reset dev fixture", "port": port,
                "pipeline": {"start": "node server.cjs", "health": "/api/_a2app"}}
    (app / "manifest.json").write_text(json.dumps(manifest))
    (app / "server.cjs").write_text(
        "const fs=require('fs');fs.mkdirSync(process.env.A2APP_DATA_DIR,{recursive:true});"
        "require('http').createServer((q,s)=>{s.setHeader('content-type','application/json');"
        "s.end(JSON.stringify({a2app:true,app:{id:'reset-dev'}}));})"
        ".listen(Number(process.env.PORT),'127.0.0.1');"
    )
    (app / "data" / "important.txt").write_text("preserve live data")
    (toolkit / "a2app.toolkit.json").write_text(json.dumps({
        "id": "reset-fixture", "lifecycle": {"dataDir": "data"},
        "systemPaths": ["manifest.json", "server.cjs"],
    }))
    (app / ".a2app" / "toolkit.json").write_text(json.dumps({"id": "reset-fixture", "source": str(toolkit)}))
    (app / ".a2app" / "system-hashes.json").write_text(json.dumps({
        name: "sha256:" + hashlib.sha256((app / name).read_bytes()).hexdigest()
        for name in ("manifest.json", "server.cjs")
    }))
    (home / "registry.json").write_text(json.dumps({
        "version": 1, "apps": [{"id": "reset-dev", "name": manifest["name"], "path": str(app), "port": port}],
    }))
    previous = framework_host._host

    async def check():
        cli = framework.configured_cli()
        agent = SimpleNamespace(session_manager=Sessions(), request_run_stop=AsyncMock(), delete_session=AsyncMock(return_value=True))
        host = FrameworkHost(agent, AsyncMock(), HostStore(tmp_path / "host.sqlite3"))
        try:
            started = await cli.run("agent-app", [str(app), "dev"], cwd=cli.package_dir)
            assert started.ok, started.stderr
            dev = json.loads((app / ".a2app" / "dev.json").read_text())
            with socket.create_connection(("127.0.0.1", dev["port"]), timeout=2):
                pass
            # This is the previous CraftBot flow: live stopped, dev still up.
            if sys.platform == "win32":
                failed = await cli.run("agent-app", [str(app), "remove", "--yes"], cwd=cli.package_dir)
                assert not failed.ok and "EBUSY" in failed.stderr, failed.stderr
                assert app.exists()
            assert await host.reset_apps() == {"deleted": 1, "failures": []}
            assert not app.exists()
            assert (await framework.list_apps())["data"]["apps"] == []
            with pytest.raises(OSError):
                socket.create_connection(("127.0.0.1", dev["port"]), timeout=1)
            backups = list((home / "removed").rglob("important.txt"))
            assert backups and all(p.read_text() == "preserve live data" for p in backups)
        finally:
            if app.exists():
                await cli.run("agent-app", [str(app), "stop", "--dev"], cwd=cli.package_dir)
            await host.close()

    try:
        asyncio.run(check())
    finally:
        framework_host._host = previous
