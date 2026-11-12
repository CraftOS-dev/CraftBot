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


def test_framework_install_is_required_offline_and_checked_without_registry_changes(
    tmp_path, monkeypatch
):
    from app import node_runtime, provision
    from app.provision.agent_app_framework import AgentAppFrameworkStage

    if node_runtime.resolve() is None:
        pytest.skip("Node runtime unavailable")
    home = tmp_path / "a2app"
    monkeypatch.setenv("A2APP_HOME", str(home))
    ctx = context(tmp_path / "state", offline=True)
    stage = AgentAppFrameworkStage()
    assert stage.check(ctx).status is Status.MISSING
    assert not Path(ctx.state_root).exists()
    stages = provision.default_stages()
    names = [s.name for s in stages]
    assert (
        names.index("node") < names.index(stage.name) < names.index("default-agent-app")
    )
    assert not next(s for s in stages if s.name == "node").optional
    assert not stage.optional
    report = provision.install(ctx=ctx, stages=[stage])
    assert report.ok, report.to_dict()
    assert stage.check(ctx).status is Status.SATISFIED
    assert not home.exists()
    assert not (Path(ctx.state_root) / "agent-apps").exists()
    assert not (Path(ctx.state_root) / default.RECEIPT).exists()
    package = Path(report.results[0][1].data["package"])
    toolkit = Path(report.results[0][1].data["toolkits"])
    assert (package / "bin/a2app.js").is_file()
    assert (toolkit / "blueprint-pocketbase-kit/a2app.toolkit.json").is_file()
    (package / "bin/a2app.js").write_text("broken")
    assert stage.check(ctx).status is Status.DEGRADED
    assert stage.apply(ctx, lambda _m: None).status is Status.FAILED


@pytest.mark.parametrize("failed_cli", ["agent-app", "a2app"])
def test_framework_cli_failure_stops_install_and_is_reported_as_required(
    tmp_path, monkeypatch, failed_cli
):
    from types import SimpleNamespace
    from app import provision
    from app.provision import agent_app_framework as stage_module
    from app.provision.types import StageResult

    monkeypatch.setattr(
        stage_module.agent_app_package, "cached_package", lambda *a: tmp_path
    )
    monkeypatch.setattr(
        stage_module.agent_app_package, "ensure_package", lambda *a: tmp_path
    )
    monkeypatch.setattr(
        stage_module, "bundled_toolkits", lambda *a, **kw: tmp_path / "toolkits"
    )
    monkeypatch.setattr(
        stage_module.node_runtime, "resolve", lambda: SimpleNamespace(node="node")
    )
    monkeypatch.setattr(stage_module.node_runtime, "child_env", lambda: {})

    def probe(command, **kwargs):
        failed = Path(command[1]).stem == failed_cli
        return subprocess.CompletedProcess(
            command, 1 if failed else 0, "help", "missing SDK" if failed else ""
        )

    monkeypatch.setattr(stage_module.proc, "run", probe)
    later = SimpleNamespace(
        name="later",
        optional=False,
        check=lambda ctx: pytest.fail("continued past failed framework"),
    )
    report = provision.install(
        ctx=context(tmp_path), stages=[stage_module.AgentAppFrameworkStage(), later]
    )
    assert [name for name, _ in report.required_failures] == ["agent-app-framework"]
    assert "missing SDK" in report.required_failures[0][1].detail
    optional = SimpleNamespace(
        name="optional",
        description="Optional integration",
        optional=True,
        check=lambda ctx: StageResult(Status.MISSING),
        apply=lambda ctx, log: StageResult(Status.FAILED),
    )
    report = provision.install(ctx=context(tmp_path), stages=[optional])
    assert report.failures and not report.required_failures


def test_node_provisioning_requires_npm_and_a_supported_runtime(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import node_runtime, provision
    from app.provision.runtimes import NodeStage

    runtime = SimpleNamespace(node="node", npm=None, version="v24.0.0", source="path")
    monkeypatch.setattr(node_runtime, "resolve", lambda **kw: runtime)
    stage = NodeStage()
    assert stage.check(context(tmp_path)).status is Status.MISSING
    runtime.version = "v18.0.0"
    assert stage.check(context(tmp_path)).status is Status.DEGRADED
    report = provision.install(ctx=context(tmp_path, offline=True), stages=[stage])
    assert [name for name, _ in report.required_failures] == ["node"]


def test_node_without_npm_does_not_shadow_complete_sidecar(tmp_path, monkeypatch):
    from app import node_runtime

    incomplete, complete = str(tmp_path / "bare-node"), str(tmp_path / "sidecar-node")
    monkeypatch.delenv("CRAFTBOT_NODE", raising=False)
    monkeypatch.setattr(node_runtime, "_cached", None)
    monkeypatch.setattr(node_runtime, "_resolved", False)
    monkeypatch.setattr(
        node_runtime.shutil,
        "which",
        lambda name: incomplete if name == "node" else None,
    )
    monkeypatch.setattr(
        node_runtime,
        "_sibling_npm",
        lambda node: "sidecar-npm" if node == complete else None,
    )
    monkeypatch.setattr(node_runtime, "probe_version", lambda node: "v24.0.0")
    monkeypatch.setattr(node_runtime, "discover_node", lambda: complete)
    runtime = node_runtime.resolve(refresh=True)
    assert (runtime.node, runtime.npm) == (complete, "sidecar-npm")


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
            "catalogue.json",
            "kanban-board/manifest.json",
            "kanban-board/LICENSE",
            "kanban-board/AGENT_APP.md",
            "kanban-board/reference/requirements.md",
            "kanban-board/frontend/package-lock.json",
            "kanban-board/operations.json",
            "toolkits/blueprint-pocketbase-kit/a2app.toolkit.json",
        } <= set(names)
        assert any(name.startswith("kanban-board/pb/pb_migrations/") for name in names)
        assert not any(
            set(Path(name).parts)
            & {"pb_data", ".superuser", "node_modules", ".factory"}
            for name in names
        )
        manifest = json.loads(archive.read("kanban-board/manifest.json"))
        assert manifest["id"] == "kanban-board"
        assert metadata["ref"] == "main"


def test_native_install_and_interrupted_retry_reuse_registered_app(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from app.agent_app import framework
    from app.agent_app.framework_cli import CLIResult
    from app.agent_app.framework_store import HostStore

    destination = (tmp_path / "agent-apps/kanban-board").resolve()
    rows = []

    async def run(surface, args, **kwargs):
        assert surface == "agent-app"
        toolkits = Path(kwargs["env_extra"]["A2APP_TOOLKITS_DIR"])
        assert (toolkits / "blueprint-pocketbase-kit/a2app.toolkit.json").is_file()
        if args[0] == "install":
            assert args[:2] == ["install", "kanban-board"]
            assert not destination.exists()
            destination.mkdir(parents=True)
            (destination / "manifest.json").write_text(
                json.dumps(
                    {
                        "source": {
                            "catalogueId": "kanban-board",
                            "location": args[args.index("--source") + 1],
                        }
                    }
                ),
                encoding="utf-8",
            )
            rows.append(
                {
                    "id": "fresh-native-id",
                    "name": "Kanban Board",
                    "path": str(destination),
                    "status": "running",
                }
            )
        else:
            assert args == [str(destination), "serve", "--install"]
            rows[0]["status"] = "running"
        return CLIResult(0, '{"ok":true}', "")

    cli = SimpleNamespace(
        home=tmp_path / "home", package_dir=tmp_path, run=AsyncMock(side_effect=run)
    )
    monkeypatch.setattr(framework, "configured_cli", lambda: cli)
    monkeypatch.setattr(
        framework,
        "_list_apps",
        AsyncMock(side_effect=lambda _: {"status": "success", "data": {"apps": rows}}),
    )
    default.prepare_install(context(tmp_path, new_install=True))
    asyncio.run(default.install_bundled_app(CODE_ROOT, tmp_path))
    assert not (tmp_path / "agent_file_system").exists()
    assert (
        HostStore(tmp_path / "agent-app-host.sqlite3").all("attachment")[0]["autoStart"]
        is True
    )
    assert len(rows) == 1
    rows[0]["status"] = "stopped"
    default._write_receipt(tmp_path, {"status": "pending"})
    asyncio.run(default.install_bundled_app(CODE_ROOT, tmp_path))
    assert len(rows) == 1 and cli.run.call_count == 2
    assert default._read_receipt(tmp_path)["frameworkAppId"] == "fresh-native-id"
    # A reused location must not silently adopt someone else's app.
    default._write_receipt(tmp_path, {"status": "pending"})
    (destination / "manifest.json").write_text('{"source":{}}', encoding="utf-8")
    with pytest.raises(ValueError, match="another source"):
        asyncio.run(default.install_bundled_app(CODE_ROOT, tmp_path))


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


def test_occupied_unregistered_destination_and_missing_registration_fail(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from app.agent_app import framework
    from app.agent_app.framework_cli import CLIResult

    cli = SimpleNamespace(
        home=tmp_path / "home",
        package_dir=tmp_path,
        run=AsyncMock(return_value=CLIResult(0, '{"ok":true}', "")),
    )
    monkeypatch.setattr(framework, "configured_cli", lambda: cli)
    monkeypatch.setattr(
        framework,
        "_list_apps",
        AsyncMock(return_value={"status": "success", "data": {"apps": []}}),
    )
    default.prepare_install(context(tmp_path, new_install=True))
    with pytest.raises(RuntimeError, match="running registered"):
        asyncio.run(default.install_bundled_app(CODE_ROOT, tmp_path))
    assert default._read_receipt(tmp_path)["status"] == "pending"
    (tmp_path / "agent-apps/kanban-board").mkdir(parents=True)
    cli.run.reset_mock()
    with pytest.raises(ValueError, match="already exists"):
        asyncio.run(default.install_bundled_app(CODE_ROOT, tmp_path))
    cli.run.assert_not_called()


def test_bundle_builder_is_repeatable_and_rejects_user_data():
    sys.path.insert(0, str(CODE_ROOT / "scripts"))
    from bundle_default_agent_app import build_bundle

    def source(extra=None, version="0.1.0"):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("upstream/LICENSE", "MIT")
            archive.writestr(
                "upstream/catalogue.json",
                json.dumps(
                    {
                        "apps": [
                            {
                                "id": "kanban-board",
                                "folder": "kanban-board",
                                "toolkit": "blueprint-pocketbase-kit",
                            }
                        ]
                    }
                ),
            )
            archive.writestr(
                "upstream/kanban-board/manifest.json",
                json.dumps({"agentAppVersion": version}),
            )
            archive.writestr(
                "upstream/kanban-board/.a2app/toolkit.json",
                '{"id":"blueprint-pocketbase-kit"}',
            )
            archive.writestr(
                "upstream/toolkits/blueprint-pocketbase-kit/a2app.toolkit.json",
                '{"id":"blueprint-pocketbase-kit"}',
            )
            if extra:
                archive.writestr(extra, "private")
        return data.getvalue()

    assert build_bundle(source()) == build_bundle(source())
    with zipfile.ZipFile(io.BytesIO(build_bundle(source()))) as archive:
        assert (
            archive.read("kanban-board/manifest.json")
            == b'{"agentAppVersion": "0.1.0"}'
        )
        assert (
            "toolkits/blueprint-pocketbase-kit/a2app.toolkit.json" in archive.namelist()
        )
    with pytest.raises(ValueError, match="legacy format"):
        build_bundle(source(version=2))
    with pytest.raises(ValueError, match="runtime state"):
        build_bundle(source("upstream/kanban-board/pb/pb_data/data.db"))
    with pytest.raises(ValueError, match="runtime state"):
        build_bundle(
            source(
                "upstream/toolkits/blueprint-pocketbase-kit/template/credentials.json"
            )
        )


def test_one_off_bundle_ref_does_not_change_future_main_updates(tmp_path, monkeypatch):
    sys.path.insert(0, str(CODE_ROOT / "scripts"))
    import bundle_default_agent_app as builder

    config = tmp_path / "source.json"
    config.write_text('{"repository":"CraftOS-dev/living-ui-marketplace","ref":"main"}')
    monkeypatch.setattr(builder, "DESTINATION", tmp_path)
    monkeypatch.setattr(builder, "build_bundle", lambda _: b"checked bundle")
    monkeypatch.setenv("CRAFTBOT_MARKETPLACE_REF", "staging")
    urls = []

    def download(request, **kwargs):
        urls.append(request.full_url)
        return io.BytesIO(
            b'{"sha":"pinned-commit"}'
            if "/commits/" in request.full_url
            else b"archive"
        )

    monkeypatch.setattr(builder, "urlopen", download)
    monkeypatch.setattr(sys, "argv", ["bundle", "--ref", "staging"])
    builder.main()
    assert json.loads(config.read_text())["sourceRef"] == "staging"
    assert json.loads(config.read_text())["ref"] == "main"
    monkeypatch.setattr(sys, "argv", ["bundle"])
    builder.main()
    assert urls[0].endswith("/commits/staging")
    assert urls[2].endswith("/commits/main")
    assert json.loads(config.read_text())["sourceRef"] == "main"


def test_packaging_requires_the_default_bundle():
    sys.path.insert(0, str(CODE_ROOT / "scripts"))
    from package_source import wanted

    assert wanted("app/data/default_agent_app/kanban-board.zip")
    assert wanted("app/data/default_agent_app/source.json")


@pytest.mark.parametrize(
    "missing",
    [None, "default", "framework", "pin", "maintenance", "housekeeping", "sharing"],
)
def test_release_payload_includes_and_requires_app_bundles(
    tmp_path, monkeypatch, missing
):
    sys.path.insert(0, str(CODE_ROOT / "scripts"))
    import package_source
    from app import agent_app_package, ripgrep_runtime

    # Model a release checkout without staging this task's working changes.
    root = tmp_path / "release"
    required = [
        "run.py",
        "main.py",
        "requirements.txt",
        "app/paths.py",
        "app/agent_app_package.py",
        "app/agent_app/framework.py",
        "app/agent_app/framework_cli.py",
        "app/agent_app/framework_maintenance.py",
        "app/agent_app/framework_maintenance.mjs",
        "app/agent_app/framework_sharing.py",
        "app/data/action/agent_app_framework_actions.py",
        "app/provision/agent_app_framework.py",
        "app/provision/__init__.py",
        "app/provision/default_agent_app.py",
        "craftos_integrations/providers/whatsapp_web/bridge.js",
        "installer/helpers.py",
        "installer/metadata.py",
        "installer/payload.py",
        "requirements/lock-test.txt",
    ]
    if missing != "default":
        required.extend(
            [
                "app/data/default_agent_app/kanban-board.zip",
                "app/data/default_agent_app/source.json",
            ]
        )
    required.extend(agent_app_package.bundled_files())
    # These exist in the build tree but an incomplete git file list must still
    # fail the payload check (the new assets need to be committed before release).
    omitted = {
        "framework": "app/vendor/agent-app/agent-app-framework.zip",
        "pin": "app/vendor/agent-app/source.json",
        "maintenance": "app/agent_app/framework_maintenance.py",
        "housekeeping": "app/agent_app/framework_maintenance.mjs",
        "sharing": "app/agent_app/framework_sharing.py",
    }.get(missing)
    for rel in required + ["app/ui_layer/browser/frontend/dist/index.html"]:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        original = CODE_ROOT / rel
        target.write_bytes(
            original.read_bytes()
            if rel.startswith(("app/data/default_agent_app/", "app/vendor/agent-app/"))
            else b"fixture"
        )
    monkeypatch.setattr(package_source, "REPO_ROOT", root)
    monkeypatch.setattr(
        package_source, "tracked_files", lambda: [r for r in required if r != omitted]
    )
    monkeypatch.setattr(ripgrep_runtime, "bundled_files", lambda: [])
    payload = tmp_path / "CraftBot-src.zip"
    assert package_source.build(payload) == (0 if missing is None else 1)
    if missing is None:
        with zipfile.ZipFile(payload) as archive:
            board = archive.read("app/data/default_agent_app/kanban-board.zip")
        with zipfile.ZipFile(io.BytesIO(board)) as archive:
            assert "kanban-board/AGENT_APP.md" in archive.namelist()


def test_framework_board_package_and_cache_are_sanitized(tmp_path):
    bundle = CODE_ROOT / default.BUNDLE_DIR
    source = json.loads((bundle / "source.json").read_text(encoding="utf-8"))
    archive = bundle / "kanban-board.zip"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == source["sha256"]
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        assert {
            "catalogue.json",
            "kanban-board/LICENSE",
            "kanban-board/manifest.json",
            "kanban-board/frontend/package-lock.json",
            "kanban-board/.a2app/toolkit.json",
        } <= set(names)
        assert not any(
            set(Path(n).parts)
            & {
                "pb_data",
                "pb_public",
                "node_modules",
                ".superuser",
                "dev",
                "live",
                "credentials.json",
            }
            for n in names
        )
        assert json.loads(z.read("kanban-board/.a2app/toolkit.json")) == {
            "id": "blueprint-pocketbase-kit"
        }
        assert "toolkits/blueprint-pocketbase-kit/a2app.toolkit.json" in names
    cache = default._local_catalogue(archive, tmp_path, source["sha256"])
    assert default._local_catalogue(archive, tmp_path, source["sha256"]) == cache
    (cache / "kanban-board/injected.js").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ValueError, match="cache changed"):
        default._local_catalogue(archive, tmp_path, source["sha256"])


def test_default_catalogue_retries_a_transient_windows_extraction_lock(
    tmp_path, monkeypatch
):
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("catalogue.json", '{"apps":[]}')
        package.writestr("kanban-board/manifest.json", '{"id":"fixture"}')
    rename = Path.rename
    attempts = []

    def blocked_once(source, target):
        attempts.append(target)
        if len(attempts) == 1:
            error = PermissionError("Scanner holds extracted files")
            error.winerror = 5
            raise error
        return rename(source, target)

    monkeypatch.setattr(Path, "rename", blocked_once)
    cache = default._local_catalogue(archive, tmp_path / "state", "fixture")
    assert len(attempts) == 2
    assert (cache / "kanban-board/manifest.json").read_text() == '{"id":"fixture"}'
    assert default._local_catalogue(archive, tmp_path / "state", "fixture") == cache
    assert len(attempts) == 2


def test_cli_discovers_bundled_toolkit_without_installing_an_app(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import node_runtime, paths
    from app.agent_app.framework_cli import AgentAppCLI

    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/agent-app.js").touch()
    monkeypatch.setattr(paths, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(
        node_runtime,
        "resolve",
        lambda: SimpleNamespace(node=sys.executable, version="v24.0.0"),
    )
    monkeypatch.setattr(node_runtime, "child_env", lambda: {})
    monkeypatch.setattr("app.config.get_framework_toolkits_dir", lambda: None)
    cli = AgentAppCLI(tmp_path, home=tmp_path / "registry")
    _, env = cli._prepare("agent-app", {})
    toolkit = (
        Path(env["A2APP_TOOLKITS_DIR"]) / "blueprint-pocketbase-kit/a2app.toolkit.json"
    )
    assert toolkit.is_file()
    assert not (tmp_path / "registry").exists()
    assert not (paths.STATE_ROOT / default.RECEIPT).exists()
    assert not (paths.STATE_ROOT / "agent-apps").exists()

    def unexpected(*args):
        pytest.fail("An explicit toolkit directory must bypass the bundled fallback")

    monkeypatch.setattr(default, "bundled_toolkits", unexpected)
    monkeypatch.setattr("app.config.get_framework_toolkits_dir", lambda: "configured")
    assert cli._prepare("agent-app", {})[1]["A2APP_TOOLKITS_DIR"] == "configured"
    monkeypatch.setattr(
        node_runtime, "child_env", lambda: {"A2APP_TOOLKITS_DIR": "environment"}
    )
    assert cli._prepare("agent-app", {})[1]["A2APP_TOOLKITS_DIR"] == "environment"
    assert (
        cli._prepare("agent-app", {"A2APP_TOOLKITS_DIR": "invocation"})[1][
            "A2APP_TOOLKITS_DIR"
        ]
        == "invocation"
    )
