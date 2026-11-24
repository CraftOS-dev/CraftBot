"""A live backup copies a running app's data consistently, in a form the
framework's own `restore` accepts.

Runs CraftBot's housekeeping script and the vendored Agent-App CLI for real. A
writer keeps committing transactions throughout, standing in for the served
app that holds its database open.
"""

import asyncio
import sqlite3
import threading
import time

import pytest

from app import agent_app_package, node_runtime
from app.agent_app.framework_cli import AgentAppCLI
from app.agent_app.framework_maintenance import housekeeping

BATCH = 50  # rows per transaction: a torn copy shows as a partial batch


def _cli(tmp_path, monkeypatch):
    runtime = node_runtime.resolve()
    if runtime is None or (node_runtime.major_of(runtime.version) or 0) < 24:
        pytest.skip("needs CraftBot's Node 24 runtime (node:sqlite)")
    package = agent_app_package.ensure_package(state_root=tmp_path / "state")
    # The framework's own blueprints; never the bundled Kanban toolkit cache.
    monkeypatch.setenv("A2APP_TOOLKITS_DIR", str(package / "toolkits"))
    return AgentAppCLI(package, home=tmp_path / "home")


def _write(db_path, stop):
    db = sqlite3.connect(db_path, isolation_level=None, timeout=30)
    try:
        while not stop.is_set():
            db.execute("BEGIN IMMEDIATE")
            db.executemany("INSERT INTO t (v) VALUES (?)", [("x" * 200,)] * BATCH)
            db.execute("COMMIT")
    finally:
        db.close()


def _rows(db_path):
    db = sqlite3.connect(db_path)
    try:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        return db.execute("SELECT count(*) FROM t").fetchone()[0]
    finally:
        db.close()


def test_a_live_backup_is_consistent_and_restorable(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch)
    app = tmp_path / "notes"
    created = asyncio.run(
        cli.run(
            "agent-app",
            [str(app), "scaffold", "--blueprint", "blueprint-react-node", "--name", "Notes"],
            cwd=cli.package_dir,
            timeout=300,
        )
    )
    assert created.code == 0, created.stderr
    app_id = created.json()["id"]

    data = app / "data"
    (data / "uploads").mkdir(parents=True)
    (data / "empty").mkdir()
    (data / "uploads" / "photo.txt").write_text("hello", encoding="utf-8")
    (data / "a2app-state.json").write_text('{"v": 1}', encoding="utf-8")
    db = sqlite3.connect(data / "db.sqlite")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    db.commit()
    db.close()

    stop = threading.Event()
    writer = threading.Thread(target=_write, args=(data / "db.sqlite", stop))
    writer.start()
    try:
        time.sleep(0.3)  # the database is mid-write, with -wal/-shm present
        assert (data / "db.sqlite-wal").exists()
        doc = asyncio.run(housekeeping(cli, str(app), app_id, "backup-live"))
    finally:
        stop.set()
        writer.join()

    backup = app / ".a2app" / "backups" / doc["backup"]
    assert sorted(p.relative_to(backup).as_posix() for p in backup.rglob("*")) == [
        "a2app-state.json",
        "db.sqlite",
        "empty",
        "uploads",
        "uploads/photo.txt",
    ]
    rows = _rows(backup / "db.sqlite")
    assert rows > 0 and rows % BATCH == 0
    assert not list(backup.parent.glob("*.staging-*"))
    listing = asyncio.run(housekeeping(cli, str(app), app_id, "list"))
    assert doc["backup"] in [b["filename"] for b in listing["backups"]]

    restored = asyncio.run(
        cli.run(
            "agent-app",
            [str(app), "restore", doc["backup"]],
            cwd=cli.package_dir,
            timeout=120,
        )
    )
    assert restored.code == 0, restored.stderr
    assert _rows(data / "db.sqlite") == rows
    assert (data / "uploads" / "photo.txt").read_text(encoding="utf-8") == "hello"
