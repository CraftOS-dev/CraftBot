"""Backups never stop a running app, and back off on failure.

A running app is backed up live (`backup-live`), so its visitors, share links
and agent tasks carry on. Only restore, which replaces the data the app has
open, stops and restarts it. A backup that keeps failing is not retried every
few minutes.
"""

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

from app.agent_app import framework, framework_maintenance
from app.agent_app.framework_maintenance import (
    BackupFailed,
    FrameworkMaintenance,
    retry_delay,
)

HOME = Path("C:/home/.a2app")
KEY = "app-key"


class _Store:
    def __init__(self):
        self.rows = {}

    def all(self, kind):
        return [dict(v) for (k, _), v in self.rows.items() if k == kind]

    def get(self, kind, key):
        value = self.rows.get((kind, key))
        return dict(value) if value is not None else None

    def put(self, kind, key, value):
        self.rows[(kind, key)] = dict(value)


def _maintenance(monkeypatch, **attachment):
    store = _Store()
    store.put(
        "attachment",
        KEY,
        {
            "key": KEY,
            "home": str(HOME),
            "path": "C:/apps/notes",
            "appId": "notes",
            "name": "Notes",
            "backupsEnabled": True,
            "backupInterval": "hourly",
            "nextBackupAt": 0,
            **attachment,
        },
    )

    async def changed():
        pass

    host = SimpleNamespace(store=store, closing=False, changed=changed)
    monkeypatch.setattr(
        framework, "configured_cli", lambda: SimpleNamespace(home=HOME)
    )
    return FrameworkMaintenance(host), store


def _running_app(monkeypatch, maintenance, store, *, live=None, active_task=False):
    """Wire backup() to a running app; record lifecycle and housekeeping calls."""
    calls = SimpleNamespace(lifecycle=[], housekeeping=[], commands=[])

    async def selected(path, app_id):
        return {"status": "running"}

    async def attach(path, app_id):
        return store.get("attachment", KEY)

    async def change(path, app_id, operation, **options):
        calls.lifecycle.append((operation, options))
        return {"status": "success"}

    async def housekeeping(cli, path, app_id, operation, *args, timeout=120):
        calls.housekeeping.append(operation)
        if operation == "layout":
            return {"backupSupport": {"mode": "cli"}}
        if operation == "list":
            return {"backups": [{"filename": "b1"}]}
        if operation == "backup-live":
            if live:
                raise RuntimeError(live)
            return {"ok": True, "backup": "b2", "path": "x"}
        raise AssertionError(operation)

    async def command(*args, **kwargs):
        calls.commands.append(args)
        return {"status": "success", "data": {"ok": True}}

    authority = SimpleNamespace(active=active_task)
    maintenance.host.selected = selected
    maintenance.host.attach = attach
    maintenance.host.bridge = SimpleNamespace(
        runs={"r": {"path": "C:/apps/notes", "authority": authority}}
    )
    monkeypatch.setattr(framework, "change_app_state_locked", change)
    monkeypatch.setattr(framework_maintenance, "housekeeping", housekeeping)
    monkeypatch.setattr(framework_maintenance, "command", command)
    return calls


def test_retry_delay_doubles_and_never_exceeds_the_interval():
    assert [retry_delay(n, "hourly") for n in (1, 2, 3, 4, 5, 9)] == [
        300,
        600,
        1200,
        2400,
        3600,
        3600,
    ]
    assert retry_delay(9, "weekly") == 300 * 2**8


def test_a_running_app_is_backed_up_live_without_stopping_it(monkeypatch):
    maintenance, store = _maintenance(monkeypatch, backupFailures=2)
    # A busy agent task no longer blocks a backup: nothing interrupts it.
    calls = _running_app(monkeypatch, maintenance, store, active_task=True)

    before = time.time()
    asyncio.run(maintenance.tick(now=1000))
    after = time.time()

    assert calls.lifecycle == []
    assert calls.commands == []
    assert "backup-live" in calls.housekeeping
    saved = store.get("attachment", KEY)
    assert saved["backupError"] is None
    assert "backupFailures" not in saved
    assert "maintenanceResume" not in saved
    assert before + 3600 <= saved["nextBackupAt"] <= after + 3600
    assert store.get("backup", KEY + ":b2") == {"trigger": "scheduled"}


def test_a_failed_live_backup_backs_off_and_never_restarts(monkeypatch):
    maintenance, store = _maintenance(monkeypatch, backupFailures=1)
    calls = _running_app(monkeypatch, maintenance, store, live="disk full")

    before = time.time()
    asyncio.run(maintenance.tick(now=1000))
    after = time.time()

    assert calls.lifecycle == []
    saved = store.get("attachment", KEY)
    assert saved["backupFailures"] == 2
    assert saved["backupError"] == "disk full"
    # backup() stamps the real clock; a second straight failure waits 10 min.
    assert before + 600 <= saved["nextBackupAt"] <= after + 600


def test_restoring_a_running_app_still_stops_and_restarts_it(monkeypatch):
    maintenance, store = _maintenance(monkeypatch)
    calls = _running_app(monkeypatch, maintenance, store)

    asyncio.run(maintenance.backup("C:/apps/notes", "notes", "restore", "b1"))

    assert calls.lifecycle == [
        ("stop", {"preserve_shares": True, "reason": "manual restore"}),
        ("start", {"reason": "after manual restore"}),
    ]
    assert calls.commands == [("agent-app", ["C:/apps/notes", "restore", "b1"])]
    assert "maintenanceResume" not in store.get("attachment", KEY)


def test_failures_before_the_backup_starts_back_off(monkeypatch):
    maintenance, store = _maintenance(monkeypatch)

    async def backup(path, app_id, trigger="manual"):
        raise ValueError("The app is unavailable. Refresh its status.")

    maintenance.backup = backup
    delays = []
    for now in (1000, 5000, 9000):
        asyncio.run(maintenance.tick(now=now))
        saved = store.get("attachment", KEY)
        delays.append(saved["nextBackupAt"] - now)
    assert delays == [300, 600, 1200]
    assert saved["backupFailures"] == 3
    assert saved["backupError"] == "The app is unavailable. Refresh its status."


def test_a_failure_backup_recorded_is_not_counted_twice(monkeypatch):
    maintenance, store = _maintenance(monkeypatch, backupFailures=2)

    async def backup(path, app_id, trigger="manual"):
        raise BackupFailed("already recorded")

    maintenance.backup = backup
    asyncio.run(maintenance.tick(now=1000))
    saved = store.get("attachment", KEY)
    assert saved["backupFailures"] == 2
    assert "backupError" not in saved


def test_changing_the_schedule_clears_the_failure_streak(monkeypatch):
    maintenance, store = _maintenance(monkeypatch, backupFailures=4)
    saved = maintenance.patch(store.get("attachment", KEY), {"backupInterval": "daily"})
    assert "backupFailures" not in saved
