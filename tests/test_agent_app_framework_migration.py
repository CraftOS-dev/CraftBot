"""Migration safety: preserve data, require a fresh verified target, no replay."""

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent_app import framework
from app.agent_app.framework_cli import CLIResult
from app.agent_app.framework_migration import (
    FrameworkMigration,
    data_inventory,
    verify_data,
)
from app.agent_app.manager import AgentAppProject
from tests.test_agent_app_framework_host import fixture as host_fixture

fixture = host_fixture


def database(path):
    path.mkdir(parents=True)
    with sqlite3.connect(path / "data.db") as db:
        db.executescript(
            "CREATE TABLE cards(id TEXT PRIMARY KEY, title TEXT, board TEXT); CREATE TABLE users(id TEXT, password TEXT); INSERT INTO cards VALUES('one','Preserve this','board1'); INSERT INTO users VALUES('owner','private-hash');"
        )
    (path / "storage").mkdir()
    (path / "storage/upload.txt").write_text("Retain file", encoding="utf-8")


def test_audit_catches_records_relations_accounts_and_files(tmp_path):
    database(tmp_path / "data")
    before = data_inventory(tmp_path / "data")
    assert "Preserve this" not in json.dumps(before)
    assert "private-hash" not in json.dumps(before)
    assert verify_data(before, tmp_path / "data") == before
    with sqlite3.connect(tmp_path / "data/data.db") as db:
        db.execute("UPDATE cards SET board='different'")
    with pytest.raises(ValueError, match="table:cards"):
        verify_data(before, tmp_path / "data")
    with sqlite3.connect(tmp_path / "data/data.db") as db:
        db.execute("UPDATE cards SET board='board1'")
        db.execute("DELETE FROM users")
    with pytest.raises(ValueError, match="table:users"):
        verify_data(before, tmp_path / "data")
    (tmp_path / "data/storage/upload.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="file:upload.txt"):
        verify_data(before, tmp_path / "data")


def test_audit_checks_collection_identity_and_relation_definitions(tmp_path):
    database(tmp_path / "data")
    with sqlite3.connect(tmp_path / "data/data.db") as db:
        db.execute(
            "CREATE TABLE _collections(id TEXT, name TEXT, fields TEXT, updated TEXT)"
        )
        db.execute(
            "INSERT INTO _collections VALUES('cards-id','cards','original-relations','before')"
        )
    before = data_inventory(tmp_path / "data")
    with sqlite3.connect(tmp_path / "data/data.db") as db:
        db.execute("UPDATE _collections SET updated='after'")
    verify_data(before, tmp_path / "data")
    with sqlite3.connect(tmp_path / "data/data.db") as db:
        db.execute("UPDATE _collections SET fields='different-relation-target'")
    with pytest.raises(ValueError, match="collection:cards"):
        verify_data(before, tmp_path / "data")


def prepare(fixture, tmp_path, monkeypatch):
    host, cli, row = fixture
    source = tmp_path / "legacy"
    database(source / "pb/pb_data")
    (source / "manifest.json").write_text('{"id":"old"}', encoding="utf-8")
    (source / ".agent-token").write_text("old-secret", encoding="utf-8")
    project = AgentAppProject(
        "old", "Old board", "", str(source), session_id="old-chat"
    )
    registry = tmp_path / "legacy-registry.json"
    manager = SimpleNamespace(
        projects={"old": project},
        _projects_file=registry,
        _live_ops=set(),
        instances=SimpleNamespace(shadow=lambda _: None),
        _launch_lock=lambda _: asyncio.Lock(),
        stop_project=AsyncMock(return_value=True),
    )
    manager.get_project = manager.projects.get
    manager.list_projects = lambda: list(manager.projects.values())
    manager._save_projects = lambda: registry.write_text(
        json.dumps({"projects": [p.to_dict() for p in manager.projects.values()]}),
        encoding="utf-8",
    )
    manager._save_projects()
    host.agent.trigger_service.cancel_sessions = AsyncMock()
    host.require_verified = lambda _: None
    Path(row["path"], "manifest.json").write_text(
        '{"id":"app","pipeline":{"start":"node pb-serve.mjs"}}', encoding="utf-8"
    )
    monkeypatch.setattr(
        framework, "open_app_view", AsyncMock(return_value={"status": "success"})
    )
    cli.run.return_value = CLIResult(0, '{"ok":true}', "")
    migration = FrameworkMigration(host, manager)
    return migration, project, row


def test_cutover_keeps_original_and_private_recovery_and_retires_only_registration(
    fixture, tmp_path, monkeypatch
):
    migration, project, row = prepare(fixture, tmp_path, monkeypatch)

    async def check():
        result = await migration.cutover(project.id, row["path"], row["id"], project.id)
        assert result["phase"] == "complete"
        assert not migration.manager.projects
        assert Path(project.path, "pb/pb_data/data.db").exists()
        assert (
            Path(result["recovery"], "source/.agent-token").read_text() == "old-secret"
        )
        assert result["dataBefore"] == result["dataAfter"]
        assert "old-secret" not in json.dumps(result)
        migration.host.agent.trigger_service.cancel_sessions.assert_awaited_once_with(
            ["old-chat"]
        )
        assert migration.host.agent.trigger_service.emit.await_count == 0

    asyncio.run(check())


def test_read_only_audit_exposes_counts_and_dependencies_without_records(
    fixture, tmp_path, monkeypatch
):
    migration, project, _ = prepare(fixture, tmp_path, monkeypatch)
    source = Path(project.path)
    (source / "client.ts").write_text("fetch('/api/llm')", encoding="utf-8")
    report = migration.audit(project.id)
    assert report["data"]["tables"]["cards"]["count"] == 1
    assert report["providerReferences"] == ["client.ts"]
    assert "private-hash" not in json.dumps(report)
    assert "Preserve this" not in json.dumps(report)
    assert not migration.host.store.all("migration")
    migration.manager.stop_project.assert_not_awaited()


def test_rollback_requires_original_code_and_data_still_match(
    fixture, tmp_path, monkeypatch
):
    migration, project, row = prepare(fixture, tmp_path, monkeypatch)

    async def check():
        result = await migration.cutover(project.id, row["path"], row["id"], project.id)
        Path(project.path, "changed.py").write_text("print(1)", encoding="utf-8")
        with pytest.raises(ValueError, match="code changed"):
            await migration.rollback(result["id"], project.id)
        assert project.id not in migration.manager.projects

    asyncio.run(check())


def test_existing_target_data_and_unverified_target_leave_source_running(
    fixture, tmp_path, monkeypatch
):
    migration, project, row = prepare(fixture, tmp_path, monkeypatch)
    Path(row["path"], "pb/pb_data").mkdir(parents=True)
    with pytest.raises(ValueError, match="already has live data"):
        asyncio.run(migration.cutover(project.id, row["path"], row["id"], project.id))
    migration.manager.stop_project.assert_not_awaited()
    assert not migration.host.store.all("migration")


def test_failed_data_check_retains_registration_and_is_not_replayed(
    fixture, tmp_path, monkeypatch
):
    migration, project, row = prepare(fixture, tmp_path, monkeypatch)

    async def run(surface, args, **kwargs):
        if args[1] == "promote":
            with sqlite3.connect(Path(row["path"], "pb/pb_data/data.db")) as db:
                db.execute("DELETE FROM cards")
        return CLIResult(0, '{"ok":true}', "")

    fixture[1].run.side_effect = run
    with pytest.raises(ValueError, match="changed existing data"):
        asyncio.run(migration.cutover(project.id, row["path"], row["id"], project.id))
    assert migration.manager.get_project(project.id) is project
    receipt = migration.host.store.all("migration")[0]
    assert receipt["phase"] == "interrupted"
    assert Path(receipt["recovery"], "data/data.db").exists()
    count = fixture[1].run.await_count
    FrameworkMigration(migration.host, migration.manager)
    assert fixture[1].run.await_count == count


def test_rollback_restores_old_registration_without_overwriting_either_database(
    fixture, tmp_path, monkeypatch
):
    migration, project, row = prepare(fixture, tmp_path, monkeypatch)

    async def check():
        result = await migration.cutover(project.id, row["path"], row["id"], project.id)
        with sqlite3.connect(Path(row["path"], "pb/pb_data/data.db")) as db:
            db.execute("UPDATE cards SET title='Later new-app change'")
        result = await migration.rollback(result["id"], project.id)
        assert result["phase"] == "rolled_back"
        assert migration.manager.get_project(project.id).auto_launch is False
        with sqlite3.connect(Path(project.path, "pb/pb_data/data.db")) as db:
            assert (
                db.execute("SELECT title FROM cards").fetchone()[0] == "Preserve this"
            )
        with sqlite3.connect(Path(row["path"], "pb/pb_data/data.db")) as db:
            assert (
                db.execute("SELECT title FROM cards").fetchone()[0]
                == "Later new-app change"
            )

    asyncio.run(check())
