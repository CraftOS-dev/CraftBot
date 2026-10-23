"""The ripgrep binary ships in the code tree and the install stage keeps it runnable."""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from app import ripgrep_runtime
from app.provision.runtimes import RipgrepStage
from app.provision.types import Context, Status

REPO_ROOT = Path(__file__).resolve().parents[1]


def _bundled_here() -> bool:
    try:
        ripgrep_runtime.binary_path()
    except RuntimeError:
        return False
    return True


def test_every_bundled_binary_is_in_the_tree():
    for rel in ripgrep_runtime.bundled_files():
        path = REPO_ROOT / rel
        assert path.is_file(), rel
        assert path.stat().st_size > 1_000_000, rel


@pytest.mark.skipif(
    not _bundled_here(), reason="ripgrep is not bundled for this platform"
)
def test_resolves_to_a_binary_that_runs():
    path = ripgrep_runtime.resolve()

    assert Path(path).is_relative_to(REPO_ROOT / "app" / "vendor" / "ripgrep")
    out = subprocess.run([path, "--version"], capture_output=True, text=True)
    assert out.returncode == 0
    assert out.stdout.startswith("ripgrep ")


def test_unbundled_platform_is_named_in_the_error(monkeypatch):
    monkeypatch.setattr(ripgrep_runtime.platform, "machine", lambda: "sparc64")

    with pytest.raises(RuntimeError, match="not bundled for .* on sparc64"):
        ripgrep_runtime.resolve()


@pytest.mark.skipif(
    not _bundled_here(), reason="ripgrep is not bundled for this platform"
)
def test_missing_binary_is_an_error(tmp_path):
    with pytest.raises(RuntimeError, match="missing from this install"):
        ripgrep_runtime.resolve(tmp_path)


def _ctx(code_root: Path) -> Context:
    return Context(code_root=str(code_root), state_root=str(code_root))


@pytest.mark.skipif(
    not _bundled_here(), reason="ripgrep is not bundled for this platform"
)
def test_stage_checks_the_tree_it_is_given(tmp_path):
    assert RipgrepStage().check(_ctx(REPO_ROOT)).status is Status.SATISFIED
    assert RipgrepStage().check(_ctx(tmp_path)).status is Status.MISSING


@pytest.mark.skipif(
    sys.platform == "win32" or not _bundled_here(),
    reason="the executable bit only exists on macOS and Linux",
)
def test_stage_restores_the_executable_bit_an_unzip_dropped(tmp_path):
    rel = ripgrep_runtime.binary_path().relative_to(REPO_ROOT)
    copy = tmp_path / rel
    copy.parent.mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / rel, copy)
    os.chmod(copy, 0o644)
    stage = RipgrepStage()

    assert stage.check(_ctx(tmp_path)).status is Status.DEGRADED
    assert stage.apply(_ctx(tmp_path), lambda _m: None).status is Status.SATISFIED
    assert copy.stat().st_mode & stat.S_IXUSR
