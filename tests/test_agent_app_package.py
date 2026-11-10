"""Exercise the shipped distribution without an upstream checkout or npm tree."""

import asyncio
import hashlib
import io
import json
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app import agent_app_package, node_runtime, paths
from app.agent_app.framework import configured_cli
from app.provision.agent_app_framework import AgentAppFrameworkStage
from app.provision.types import Context, Status
from scripts.build_agent_app_framework import make_zip


@pytest.fixture
def installed(tmp_path, monkeypatch):
    code = tmp_path / "installed code"
    state = tmp_path / "user state"
    for relative in agent_app_package.bundled_files():
        target = code / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(paths.CODE_ROOT / relative, target)
    monkeypatch.setattr(paths, "CODE_ROOT", code)
    monkeypatch.setattr(paths, "STATE_ROOT", state)
    monkeypatch.delenv("CRAFTBOT_AGENT_APP_PACKAGE", raising=False)
    monkeypatch.setenv("A2APP_HOME", str(tmp_path / "framework profile"))
    for name in ("A2APP_SKILLS_DIR", "A2APP_TOOLKITS_DIR", "NODE_PATH"):
        monkeypatch.delenv(name, raising=False)
    return code, state


def test_installer_uses_the_bundle_offline_and_doctor_is_read_only(installed):
    code, state = installed
    ctx = Context(str(code), str(state), offline=True)
    stage = AgentAppFrameworkStage()
    assert stage.check(ctx).status == Status.MISSING
    assert not state.exists()
    result = stage.apply(ctx, lambda _: None)
    assert result.ok, result
    package = Path(result.data["package"])
    assert package.is_relative_to(state)
    assert configured_cli().package_dir == package
    before = (package / "bin/agent-app.js").stat().st_mtime_ns
    assert stage.check(ctx).status == Status.SATISFIED
    assert stage.apply(ctx, lambda _: None).ok
    assert (package / "bin/agent-app.js").stat().st_mtime_ns == before
    assert not (state.parent / "framework profile").exists()


def test_concurrent_first_use_publishes_one_complete_package(installed):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: agent_app_package.ensure_package(), range(4)))
    assert len(set(results)) == 1
    package = results[0]
    assert list(package.parent.iterdir()) == [package]
    pin, files = agent_app_package.read_bundle(installed[0])
    assert package.name == pin["sha256"]
    assert all((package / name).read_bytes() == data for name, data in files.items())


def test_transient_windows_file_lock_retries_without_replacing_existing_cache(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        agent_app_package,
        "read_bundle",
        lambda _: ({"sha256": "fixture"}, {"bin/app.js": b"unchanged"}),
    )
    rename = agent_app_package.os.rename
    attempts = []

    def blocked_once(source, target):
        attempts.append(target)
        if len(attempts) == 1:
            error = PermissionError("Windows scanner holds directory")
            error.winerror = 5
            raise error
        rename(source, target)

    monkeypatch.setattr(agent_app_package.os, "rename", blocked_once)
    package = agent_app_package.ensure_package(tmp_path, tmp_path / "state")
    assert len(attempts) == 2
    assert (package / "bin/app.js").read_bytes() == b"unchanged"


@pytest.mark.parametrize("release_after", [4, None])
def test_windows_cache_publish_waits_for_scanner_but_has_a_deadline(
    tmp_path, monkeypatch, release_after
):
    monkeypatch.setattr(
        agent_app_package,
        "read_bundle",
        lambda _: ({"sha256": "fixture"}, {"bin/app.js": b"unchanged"}),
    )
    elapsed = [0.0]
    monkeypatch.setattr(agent_app_package.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(
        agent_app_package.time,
        "sleep",
        lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
    )
    rename = agent_app_package.os.rename

    def held_by_scanner(source, target):
        if release_after is None or elapsed[0] < release_after:
            error = PermissionError("Windows scanner holds directory")
            error.winerror = 32
            raise error
        rename(source, target)

    monkeypatch.setattr(agent_app_package.os, "rename", held_by_scanner)
    if release_after is None:
        with pytest.raises(PermissionError, match="scanner"):
            agent_app_package.ensure_package(tmp_path, tmp_path / "state")
        assert 10 <= elapsed[0] < 11
        assert not (tmp_path / "state/runtime/agent-app/fixture").exists()
    else:
        package = agent_app_package.ensure_package(tmp_path, tmp_path / "state")
        assert (package / "bin/app.js").read_bytes() == b"unchanged"
        assert release_after <= elapsed[0] < 5


def test_corrupt_shipped_archive_is_rejected_before_creating_state(installed):
    code, state = installed
    archive = code / agent_app_package.BUNDLE_DIR / agent_app_package.ARCHIVE
    archive.write_bytes(archive.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="checksum mismatch"):
        agent_app_package.ensure_package()
    assert not state.exists()
    assert not AgentAppFrameworkStage().apply(Context(str(code), str(state)), print).ok


def test_modified_cache_is_reported_instead_of_executed(installed):
    package = agent_app_package.ensure_package()
    (package / "bin/agent-app.js").write_text("modified", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete or modified"):
        configured_cli()


def test_explicit_override_remains_authoritative(installed, monkeypatch, tmp_path):
    override = tmp_path / "developer package"
    monkeypatch.setenv("CRAFTBOT_AGENT_APP_PACKAGE", str(override))
    assert configured_cli().package_dir == override
    assert not installed[1].exists()  # even a missing override must not fall back


@pytest.mark.parametrize(
    "entry", ["../escape.js", "/absolute.js", "C:/escape.js", "a\\b.js"]
)
def test_unsafe_bundle_paths_are_rejected_even_with_a_matching_hash(installed, entry):
    code, state = installed
    folder = code / agent_app_package.BUNDLE_DIR
    data = make_zip({entry: b"untrusted"})
    if "\\" in entry:
        # ZipInfo normalizes backslashes on Windows. Simulate an archive from
        # another platform by restoring the raw central/local-header names.
        data = data.replace(entry.replace("\\", "/").encode(), entry.encode())
    (folder / agent_app_package.ARCHIVE).write_bytes(data)
    pin = json.loads((folder / agent_app_package.PIN).read_text())
    pin["sha256"] = hashlib.sha256(data).hexdigest()
    (folder / agent_app_package.PIN).write_text(json.dumps(pin))
    with pytest.raises(ValueError, match="Invalid Agent-App bundle entry"):
        agent_app_package.ensure_package()
    assert not state.exists()


def test_packed_files_are_preserved_and_archive_order_is_stable():
    files = {"b.js": b"export const b = 1;\n", "a.md": b"# Skill\n"}
    data = make_zip(files)
    assert data == make_zip(dict(reversed(list(files.items()))))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == files


def test_standalone_distribution_runs_both_clis_and_finds_its_knowledge(
    installed, tmp_path
):
    if node_runtime.resolve() is None:
        pytest.skip("CraftBot's Node runtime is required")
    cli = configured_cli()
    pin, files = agent_app_package.read_bundle(installed[0])

    async def check():
        for surface in ("agent-app", "a2app"):
            result = await cli.run(surface, ["--version"], cwd=tmp_path)
            assert result.ok, result.stderr
            assert result.json()[surface] == pin["version"]
        result = await cli.run("agent-app", ["list", "--json"], cwd=tmp_path)
        assert result.ok, result.stderr
        assert result.json()["apps"] == []
        result = await cli.run("agent-app", ["skills"], cwd=tmp_path)
        assert result.ok, result.stderr
        assert len(result.json()["skills"]) == len(
            json.loads(files["skills/index.json"])["skills"]
        )
        assert Path(result.json()["dir"]) == cli.package_dir / "skills"
        for skill in result.json()["skills"]:
            assert Path(skill["path"]).is_file()
        result = await cli.run("agent-app", ["blueprints"], cwd=tmp_path)
        assert result.ok, result.stderr
        expected = {
            name.split("/")[1] for name in files if name.endswith("/a2app.toolkit.json")
        }
        assert {
            blueprint["id"] for blueprint in result.json()["blueprints"]
        } == expected

        # Exercise prepack's actual template assets, including _gitignore
        # restoration. Scaffolding this disposable app installs/starts nothing.
        project = tmp_path / "fixture app"
        result = await cli.run(
            "agent-app",
            [
                str(project),
                "scaffold",
                "--blueprint",
                "blueprint-react-node",
                "--name",
                "Bundle smoke",
            ],
            cwd=tmp_path,
        )
        assert result.ok, result.stderr
        assert (project / ".gitignore").is_file()
        assert (
            json.loads((project / "manifest.json").read_text())["name"]
            == "Bundle smoke"
        )
        toolkit = json.loads((project / ".a2app/toolkit.json").read_text())
        assert (
            Path(toolkit["source"]) == cli.package_dir / "toolkits/blueprint-react-node"
        )

    asyncio.run(check())
