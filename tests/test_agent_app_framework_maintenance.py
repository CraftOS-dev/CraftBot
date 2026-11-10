"""Host controls exercise disposable apps only; upstream stays unchanged."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.agent_app import framework, framework_maintenance as maintenance
from app.agent_app.framework_commands import TaskAuthority
from tests.test_agent_app_framework_host import fixture as fixture


@pytest.mark.parametrize("mode", ["cli", "parent-toolkit", None])
def test_remove_captures_parent_toolkit_data_before_upstream_deletion(
    fixture, monkeypatch, mode
):
    host, _, row = fixture
    monkeypatch.setattr(
        maintenance,
        "housekeeping",
        AsyncMock(return_value={"backupSupport": {"mode": mode}}),
    )
    backup = AsyncMock()
    monkeypatch.setattr(host.maintenance, "backup", backup)

    async def check():
        await maintenance.FrameworkMaintenance.before_remove(
            host.maintenance, row["path"], row["id"]
        )
        if mode == "parent-toolkit":
            backup.assert_awaited_once_with(
                row["path"], row["id"], trigger="pre-remove"
            )
        else:
            backup.assert_not_awaited()

    asyncio.run(check())


def test_preferences_patch_without_resetting_other_controls(fixture):
    host, _, row = fixture

    async def check():
        request = {"operation": "preference", "path": row["path"], "appId": row["id"]}
        await host.request({**request, "autoStart": True})
        saved = await host.request(
            {
                **request,
                "logCleanup": True,
                "backupsEnabled": True,
                "backupKeep": 3,
                "backupInterval": "6h",
            }
        )
        assert saved["autoStart"] and saved["logCleanup"] and saved["nextBackupAt"] > 0
        with pytest.raises(ValueError):
            await host.request({**request, "backupKeep": 0})
        with pytest.raises(ValueError):
            await host.request({**request, "backupInterval": "every second"})
        assert host.store.get("attachment", saved["key"]) == saved

    asyncio.run(check())


@pytest.mark.parametrize(
    "fail_backup,fail_restart", [(False, False), (True, False), (False, True)]
)
def test_backup_restores_running_state_and_retains_restart_receipt(
    fixture, monkeypatch, fail_backup, fail_restart
):
    host, _, row = fixture
    events = []

    async def lifecycle(path, app_id, op, **kwargs):
        events.append(op)
        if op == "start" and fail_restart:
            return {"status": "error", "message": "restart failed"}
        row["status"] = "running" if op == "start" else "stopped"
        return {"status": "success"}

    async def command(surface, args, **kwargs):
        assert framework.lifecycle_lock(row["path"]).locked()
        assert kwargs["_locked"] is True
        events.append(args[1])
        return {
            "status": "error" if fail_backup else "success",
            "stderr": "capture failed" if fail_backup else "",
            "data": {"ok": not fail_backup, "backup": "new"},
        }

    monkeypatch.setattr(framework, "change_app_state_locked", lifecycle)
    monkeypatch.setattr(maintenance, "command", command)
    monkeypatch.setattr(
        maintenance, "housekeeping", AsyncMock(return_value={"backups": []})
    )

    async def check():
        if fail_backup or fail_restart:
            with pytest.raises(RuntimeError):
                await host.maintenance.backup(row["path"], row["id"])
        else:
            await host.maintenance.backup(row["path"], row["id"])
        saved = host.store.all("attachment")[0]
        assert bool(saved.get("maintenanceResume")) == fail_restart
        assert bool(saved.get("backupError")) == (fail_backup or fail_restart)
        assert events == ["stop", "backup", "start"]

    asyncio.run(check())


def test_retention_preserves_unowned_snapshots_and_stopped_state(fixture, monkeypatch):
    host, _, row = fixture
    row["status"] = "stopped"
    house = AsyncMock(
        return_value={
            "backups": [{"filename": name} for name in ["new", "external", "old"]]
        }
    )
    monkeypatch.setattr(maintenance, "housekeeping", house)
    monkeypatch.setattr(
        maintenance,
        "command",
        AsyncMock(
            return_value={"status": "success", "data": {"ok": True, "backup": "new"}}
        ),
    )
    change = AsyncMock()
    monkeypatch.setattr(framework, "change_app_state_locked", change)

    async def check():
        saved = await host.attach(row["path"], row["id"])
        host.maintenance.patch(saved, {"backupKeep": 1})
        host.store.put("backup", saved["key"] + ":old", {"trigger": "scheduled"})
        host.store.put("backup", saved["key"] + ":external", {"trigger": "manual"})
        await host.maintenance.backup(row["path"], row["id"], trigger="scheduled")
        assert house.await_args.args[3:] == ("delete", "old")
        change.assert_not_called()

    asyncio.run(check())


def test_scheduler_only_runs_due_profile_and_defers_active_tasks(fixture, monkeypatch):
    host, _, row = fixture
    command = AsyncMock()
    monkeypatch.setattr(maintenance, "command", command)

    async def check():
        saved = await host.attach(row["path"], row["id"])
        saved.update(backupsEnabled=True, nextBackupAt=10)
        host.store.put("attachment", saved["key"], saved)
        host.bridge.runs["active"] = {
            "path": row["path"],
            "authority": TaskAuthority("http://127.0.0.1:8123", "task", "secret"),
        }
        await host.maintenance.tick(now=11)
        latest = host.store.get("attachment", saved["key"])
        assert latest["nextBackupAt"] == 311
        assert "active tasks" in latest["backupError"]
        command.assert_not_called()
        host.bridge.runs.clear()
        backup = AsyncMock()
        monkeypatch.setattr(host.maintenance, "backup", backup)
        await host.maintenance.tick(now=310)
        backup.assert_not_called()
        await host.maintenance.tick(now=312)
        backup.assert_awaited_once_with(row["path"], row["id"], trigger="scheduled")

    asyncio.run(check())


def test_backup_serializes_against_sidebar_lifecycle(fixture, monkeypatch):
    host, _, row = fixture
    row["status"] = "stopped"
    monkeypatch.setattr(
        maintenance, "housekeeping", AsyncMock(return_value={"backups": []})
    )

    async def check():
        entered, finish = asyncio.Event(), asyncio.Event()

        async def capture(*args, **kwargs):
            entered.set()
            await finish.wait()
            return {"status": "success", "data": {"ok": True, "backup": "new"}}

        monkeypatch.setattr(maintenance, "command", capture)
        backup = asyncio.create_task(host.maintenance.backup(row["path"], row["id"]))
        await entered.wait()
        change = AsyncMock(return_value={"status": "success"})
        monkeypatch.setattr(framework, "change_app_state_locked", change)
        start = asyncio.create_task(
            framework.change_app_state(row["path"], row["id"], "start")
        )
        await asyncio.sleep(0)
        change.assert_not_called()
        finish.set()
        await asyncio.wait_for(asyncio.gather(backup, start), 3)
        change.assert_awaited_once()

    asyncio.run(check())


def test_finished_app_task_does_not_block_later_backup(fixture, monkeypatch):
    host, _, row = fixture
    row["status"] = "stopped"
    host.bridge.runs["finished"] = {
        "path": row["path"],
        "authority": TaskAuthority(
            "http://127.0.0.1:8123", "task", "", active=False, outcome="completed"
        ),
    }
    monkeypatch.setattr(
        maintenance, "housekeeping", AsyncMock(return_value={"backups": []})
    )
    capture = AsyncMock(
        return_value={"status": "success", "data": {"ok": True, "backup": "after-task"}}
    )
    monkeypatch.setattr(maintenance, "command", capture)

    async def check():
        result = await host.maintenance.backup(row["path"], row["id"])
        assert result["data"]["backup"] == "after-task"
        capture.assert_awaited_once()

    asyncio.run(check())


def test_real_housekeeping_uses_pinned_library_and_confines_deletes(
    tmp_path, monkeypatch
):
    from app import paths

    monkeypatch.setattr(paths, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setenv("A2APP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE", raising=False)
    app = tmp_path / "fixture"
    app.mkdir()
    (app / "manifest.json").write_text(json.dumps({"id": "fixture", "port": 65534}))
    root = app / ".a2app" / "backups"
    names = ["2026-11-09T12-00-00-000Z-1-0", "2026-11-09T12-01-00-000Z-pre-restore-1-0"]
    for name in names:
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "data").write_bytes(b"fixture")
    log = app / ".a2app" / "serve.log"
    log.write_text("old log")
    toolkit = tmp_path / "toolkit"
    toolkit.mkdir()
    (toolkit / "a2app.toolkit.json").write_text(
        json.dumps({"id": "fixture", "lifecycle": {"dataDir": "data"}})
    )
    (app / ".a2app" / "toolkit.json").write_text(
        json.dumps({"id": "fixture", "source": str(toolkit)})
    )
    (app / "data").mkdir()
    data = app / "data" / "state.txt"
    data.write_text("before")

    async def check():
        cli = framework.configured_cli()
        result = await maintenance.housekeeping(cli, str(app), "fixture", "list")
        assert [b["filename"] for b in result["backups"]] == names[:1]
        assert result["backups"][0]["size"] == 7
        with pytest.raises(RuntimeError, match="existing user backup"):
            await maintenance.housekeeping(
                cli, str(app), "fixture", "delete", "../manifest.json"
            )
        with pytest.raises(RuntimeError, match="existing user backup"):
            await maintenance.housekeeping(cli, str(app), "fixture", "delete", names[1])
        with pytest.raises(RuntimeError, match="identity"):
            await maintenance.housekeeping(
                cli, str(app), "different", "delete", names[0]
            )
        await maintenance.housekeeping(cli, str(app), "fixture", "clean-logs")
        assert log.read_text() == ""
        await maintenance.housekeeping(cli, str(app), "fixture", "delete", names[0])
        assert not (root / names[0]).exists() and (root / names[1]).is_dir()
        capture = await cli.run("agent-app", [str(app), "backup"], cwd=cli.package_dir)
        assert capture.ok, capture.stderr
        backup_id = capture.json()["backup"]
        data.write_text("after")
        restore = await cli.run(
            "agent-app", [str(app), "restore", backup_id], cwd=cli.package_dir
        )
        assert restore.ok, restore.stderr
        assert data.read_text() == "before"
        assert (root / restore.json()["rollback"] / "state.txt").read_text() == "after"
        # A hard-linked log must not clear another file's contents.
        import os

        log.unlink()
        os.link(data, log)
        with pytest.raises(RuntimeError, match="unlinked file"):
            await maintenance.housekeeping(cli, str(app), "fixture", "clean-logs")
        assert data.read_text() == "before"

    asyncio.run(check())
