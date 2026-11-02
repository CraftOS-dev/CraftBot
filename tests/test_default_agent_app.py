"""The included board is acquired during a fresh install, never on startup."""

import asyncio
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import AsyncMock
import zipfile

import pytest

from app.provision import default_agent_app as default
from app.provision.types import Context, Status

CODE_ROOT = Path(__file__).resolve().parents[1]


def context(tmp_path, **kwargs):
    return Context(code_root=str(CODE_ROOT), state_root=str(tmp_path), **kwargs)


@pytest.mark.parametrize(
    "existing",
    ["install.json", "agent_file_system/workspace", "app/config/settings.json"],
)
def test_existing_install_without_apps_is_not_new(tmp_path, existing):
    path = tmp_path / existing
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix:
        path.write_text("{}")
    else:
        path.mkdir()
    assert not default.is_new_install(str(tmp_path))


def test_source_config_identifies_existing_install(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "config.json").write_text("{}")
    assert not default.is_new_install(str(tmp_path / "state"), str(code))


def test_fresh_checkout_with_shipped_settings_installs_kanban(tmp_path, monkeypatch):
    from app import provision
    from app.provision import proc

    settings = tmp_path / "app/config/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}")
    fresh = default.is_new_install(str(tmp_path), str(tmp_path))
    assert fresh, "Tracked settings are source defaults, not an installed runtime"
    ctx = Context(code_root=str(tmp_path), state_root=str(tmp_path), new_install=fresh)

    def acquire(*args, **kwargs):
        (tmp_path / default.RECEIPT).write_text('{"status":"installed"}')
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(proc, "run", acquire)
    report = provision.install(ctx=ctx, stages=[default.DefaultAgentAppStage()])
    assert report.ok
    assert report.results[0][1].status == Status.SATISFIED


def test_new_install_receipt_survives_interrupted_setup(tmp_path):
    ctx = context(tmp_path, new_install=True)
    assert default.is_new_install(str(tmp_path))
    default.prepare_install(ctx)
    # Installation has now written config; a retry is no longer "new".
    (tmp_path / "install.json").write_text("{}")
    retry = context(tmp_path)
    default.prepare_install(retry)
    assert default.DefaultAgentAppStage().check(retry).status == Status.MISSING


def test_existing_install_is_skipped_without_writing_state(tmp_path):
    stage = default.DefaultAgentAppStage()
    ctx = context(tmp_path)
    assert stage.check(ctx).status == Status.SKIPPED
    assert stage.apply(ctx, lambda _: None).status == Status.SKIPPED
    assert not list(tmp_path.iterdir())


def test_completed_install_never_recreates_a_deleted_board(tmp_path):
    receipt = tmp_path / default.RECEIPT
    receipt.write_text('{"status":"installed","projectId":"deleted"}')
    ctx = context(tmp_path, new_install=True)
    default.prepare_install(ctx)
    assert default.DefaultAgentAppStage().check(ctx).status == Status.SATISFIED
    asyncio.run(default.install_bundled_app(CODE_ROOT, tmp_path))
    assert list(tmp_path.iterdir()) == [receipt]


def test_doctor_is_read_only_even_for_new_installs(tmp_path):
    from app import provision

    report = provision.doctor(
        ctx=context(tmp_path, new_install=True), stages=[default.DefaultAgentAppStage()]
    )
    assert report.results[0][1].status == Status.MISSING
    assert not list(tmp_path.iterdir())


def test_stage_uses_target_interpreter_code_and_state(tmp_path, monkeypatch):
    from app.provision import proc

    ctx = context(tmp_path, new_install=True, service_python=["target-python"])
    captured = {}

    def run(cmd, log, **kwargs):
        captured.update(cmd=cmd, **kwargs)
        (tmp_path / default.RECEIPT).write_text('{"status":"installed"}')
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(proc, "run", run)
    assert default.DefaultAgentAppStage().apply(ctx, lambda _: None).ok
    assert captured["cmd"][0] == "target-python"
    assert captured["cwd"] == str(CODE_ROOT)
    assert captured["env"]["CRAFTBOT_HOME"] == str(tmp_path.resolve())


def test_failed_stage_keeps_pending_receipt_and_reports_error(tmp_path, monkeypatch):
    from app.provision import proc

    monkeypatch.setattr(
        proc,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 1, "", "ERROR: no Node"),
    )
    result = default.DefaultAgentAppStage().apply(
        context(tmp_path, new_install=True), lambda _: None
    )
    assert result.status == Status.FAILED
    assert "no Node" in result.detail
    assert json.loads((tmp_path / default.RECEIPT).read_text())["status"] == "pending"


def test_bundle_contains_app_and_license_without_runtime_state():
    bundle = CODE_ROOT / default.BUNDLE_DIR
    metadata = json.loads((bundle / "source.json").read_text())
    data = (bundle / "kanban-board.zip").read_bytes()
    assert hashlib.sha256(data).hexdigest() == metadata["sha256"]
    assert len(metadata["revision"]) == 40
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert {
            "manifest.json",
            "LICENSE",
            "AGENT_APP.md",
            "reference/requirements.md",
            "frontend/package-lock.json",
            "operations.json",
        } <= set(names)
        assert any(name.startswith("pb/pb_migrations/") for name in names)
        assert not any(
            set(Path(name).parts)
            & {"pb_data", ".superuser", "node_modules", ".factory"}
            for name in names
        )
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["marketplaceAppId"] == "kanban-board"


def test_real_import_registers_one_normal_app_and_retry_reuses_it(
    tmp_path, monkeypatch
):
    from app.agent_app.manager import AgentAppManager
    from app.agent_app.runner import AgentAppRunner

    # Exercise real extraction, identity/port replacement and persistence.
    # The tooling process is covered separately in the disposable smoke run.
    monkeypatch.setattr(AgentAppRunner, "kit_sync", AsyncMock())
    default.prepare_install(context(tmp_path, new_install=True))
    asyncio.run(default.install_bundled_app(CODE_ROOT, tmp_path))

    workspace = tmp_path / "agent_file_system" / "workspace"
    manager = AgentAppManager(workspace)
    assert len(manager.projects) == 1
    project = next(iter(manager.projects.values()))
    assert project.name == "Kanban Board"
    assert project.auto_launch is True
    manifest = json.loads((Path(project.path) / "manifest.json").read_text())
    assert manifest["id"] == project.id
    assert manifest["port"] == project.port
    assert "{{PORT}}" not in manifest["pipeline"]["start"]
    assert (Path(project.path) / "AGENT_APP.md").is_file()

    # Simulate a crash after registration, before the completion receipt.
    (tmp_path / default.RECEIPT).write_text('{"status":"pending"}')
    asyncio.run(default.install_bundled_app(CODE_ROOT, tmp_path))
    reloaded = AgentAppManager(workspace)
    assert list(reloaded.projects) == [project.id]
    assert (
        json.loads((tmp_path / default.RECEIPT).read_text())["projectId"] == project.id
    )


def test_corrupt_bundle_does_not_register_an_app(tmp_path):
    code = tmp_path / "code"
    bundle = code / default.BUNDLE_DIR
    bundle.mkdir(parents=True)
    (bundle / "source.json").write_text('{"sha256":"wrong"}')
    (bundle / "kanban-board.zip").write_bytes(b"broken")
    state = tmp_path / "state"
    default.prepare_install(context(state, new_install=True))
    with pytest.raises(ValueError, match="checksum"):
        asyncio.run(default.install_bundled_app(code, state))
    assert not (state / "agent_file_system").exists()


def test_registration_must_persist_before_install_is_complete(tmp_path, monkeypatch):
    from app.agent_app.manager import AgentAppManager
    from app.agent_app.runner import AgentAppRunner

    monkeypatch.setattr(AgentAppRunner, "kit_sync", AsyncMock())
    monkeypatch.setattr(AgentAppManager, "_save_projects", lambda self: None)
    default.prepare_install(context(tmp_path, new_install=True))
    with pytest.raises(FileNotFoundError):
        asyncio.run(default.install_bundled_app(CODE_ROOT, tmp_path))
    assert json.loads((tmp_path / default.RECEIPT).read_text())["status"] == "pending"


def test_runner_tools_come_from_code_not_the_users_workspace(tmp_path, monkeypatch):
    from app import paths
    from app.agent_app.manager import AgentAppManager

    monkeypatch.setattr(paths, "CODE_ROOT", CODE_ROOT)
    manager = AgentAppManager(tmp_path / "separate-user-data")
    assert manager.runner.cli_path == CODE_ROOT / "agent-app/tools/src/cli.ts"


def test_bundle_builder_is_repeatable_and_rejects_user_data():
    sys.path.insert(0, str(CODE_ROOT / "scripts"))
    from bundle_default_agent_app import build_bundle

    def source(extra=None):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("upstream/LICENSE", "MIT")
            archive.writestr("upstream/kanban-board/manifest.json", "{}")
            if extra:
                archive.writestr(extra, "private")
        return data.getvalue()

    assert build_bundle(source()) == build_bundle(source())
    with pytest.raises(ValueError, match="runtime state"):
        build_bundle(source("upstream/kanban-board/pb/pb_data/data.db"))


def test_packaging_requires_the_default_bundle():
    sys.path.insert(0, str(CODE_ROOT / "scripts"))
    from package_source import wanted

    assert wanted("app/data/default_agent_app/kanban-board.zip")
    assert wanted("app/data/default_agent_app/source.json")


@pytest.mark.parametrize("include_bundle", [True, False])
def test_release_payload_includes_and_requires_kanban(
    tmp_path, monkeypatch, include_bundle
):
    sys.path.insert(0, str(CODE_ROOT / "scripts"))
    import package_source
    from app import ripgrep_runtime

    # Model a release checkout without staging this task's working changes.
    root = tmp_path / "release"
    required = [
        "run.py",
        "main.py",
        "requirements.txt",
        "app/paths.py",
        "app/provision/__init__.py",
        "app/provision/default_agent_app.py",
        "craftos_integrations/providers/whatsapp_web/bridge.js",
        "installer/helpers.py",
        "installer/metadata.py",
        "installer/payload.py",
        "requirements/lock-test.txt",
    ]
    if include_bundle:
        required.extend(
            [
                "app/data/default_agent_app/kanban-board.zip",
                "app/data/default_agent_app/source.json",
            ]
        )
    for rel in required + ["app/ui_layer/browser/frontend/dist/index.html"]:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        original = CODE_ROOT / rel
        target.write_bytes(
            original.read_bytes()
            if rel.startswith("app/data/default_agent_app/")
            else b"fixture"
        )
    monkeypatch.setattr(package_source, "REPO_ROOT", root)
    monkeypatch.setattr(package_source, "tracked_files", lambda: required)
    monkeypatch.setattr(ripgrep_runtime, "bundled_files", lambda: [])
    payload = tmp_path / "CraftBot-src.zip"
    assert package_source.build(payload) == (0 if include_bundle else 1)
    if include_bundle:
        with zipfile.ZipFile(payload) as archive:
            board = archive.read("app/data/default_agent_app/kanban-board.zip")
        with zipfile.ZipFile(io.BytesIO(board)) as archive:
            assert "AGENT_APP.md" in archive.namelist()
