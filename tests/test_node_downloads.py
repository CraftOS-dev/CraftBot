"""The private Node comes only from the pinned release, checked against its SHA-256."""

import json
import re
import sys
import urllib.request

import pytest

from app import downloads, node_runtime

DOWNLOADS = json.loads(node_runtime.NODE_CONFIG_PATH.read_text(encoding="utf-8"))
ARCHIVES = sorted(DOWNLOADS["sha256"])


@pytest.fixture
def download_config(monkeypatch, tmp_path):
    path = tmp_path / "node_downloads.json"
    monkeypatch.setattr(node_runtime, "NODE_CONFIG_PATH", path)
    return path


@pytest.fixture(autouse=True)
def configured_context_window():
    """Download selection needs no model configuration."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """The version is pinned, so nodejs.org's index is never asked."""
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **kw: pytest.fail("network used")
    )


def _platform(monkeypatch, archive):
    suffix, ext = archive.split(".", 1)
    monkeypatch.setattr(node_runtime, "_platform_suffix", lambda: (suffix, ext))


def test_the_pin_is_on_the_supported_major():
    assert node_runtime.major_of(DOWNLOADS["version"]) == node_runtime.MIN_NODE_MAJOR


@pytest.mark.parametrize("archive", ARCHIVES)
def test_every_platform_resolves_its_pinned_archive(monkeypatch, archive):
    _platform(monkeypatch, archive)
    version = DOWNLOADS["version"]
    assert node_runtime.pinned_download() == (
        version,
        f"{DOWNLOADS['download_base']}/{version}/node-{version}-{archive}",
        DOWNLOADS["sha256"][archive],
    )
    assert re.fullmatch(r"[0-9a-f]{64}", DOWNLOADS["sha256"][archive])


def test_platform_without_a_pin_is_refused(monkeypatch, download_config):
    archive = ARCHIVES[0]
    pins = {k: v for k, v in DOWNLOADS["sha256"].items() if k != archive}
    download_config.write_text(json.dumps(dict(DOWNLOADS, sha256=pins)))
    _platform(monkeypatch, archive)
    logs = []
    assert node_runtime.pinned_download(log=logs.append) is None
    assert any("No pinned Node" in message for message in logs)


@pytest.mark.parametrize("version", ["v22.11.0", "24.22.3", "v24.22"])
def test_configuration_cannot_supply_another_line(
    monkeypatch, download_config, version
):
    download_config.write_text(json.dumps(dict(DOWNLOADS, version=version)))
    _platform(monkeypatch, ARCHIVES[0])
    assert node_runtime.pinned_download() is None


@pytest.mark.parametrize("contents", [None, "not JSON", "{}"])
def test_missing_or_invalid_configuration_fails_clearly(
    monkeypatch, download_config, contents
):
    if contents is not None:
        download_config.write_text(contents, encoding="utf-8")
    logs = []
    assert node_runtime.pinned_download(log=logs.append) is None
    assert "Invalid Node download configuration" in logs[0]


def test_the_sidecar_downloads_against_the_pin(monkeypatch, tmp_path):
    archive = next(name for name in ARCHIVES if name.startswith("linux-"))
    _platform(monkeypatch, archive)
    monkeypatch.setattr(node_runtime, "SIDECAR_DIR", tmp_path)
    calls = []

    def download(url, dest, **kwargs):
        calls.append((url, kwargs.get("expected_sha256")))
        raise ValueError("SHA-256 verification failed")

    monkeypatch.setattr(downloads, "download", download)
    assert node_runtime.download_sidecar() is None
    assert calls == [node_runtime.pinned_download()[1:]]
    assert [path.name for path in tmp_path.iterdir()] == []


def _node(path, version):
    """A node binary that reports `version`, as probe_version asks it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho {version}\n")
    path.chmod(0o755)
    return path


@pytest.mark.skipif(sys.platform == "win32", reason="unix node layout")
def test_a_path_node_whose_npm_it_cannot_run_gives_way_to_the_sidecar(
    monkeypatch, tmp_path
):
    # Arch's nodejs: node on PATH with no npm beside it, and another install's
    # npm (a version manager's) found on PATH instead.
    path_node = _node(tmp_path / "usr" / "bin" / "node", "v26.12.0")
    foreign_npm = tmp_path / "mise" / "bin" / "npm"
    foreign_npm.parent.mkdir(parents=True)
    foreign_npm.write_text("#!/bin/sh\n")
    which = {"node": str(path_node), "npm": str(foreign_npm)}
    monkeypatch.setattr(node_runtime.shutil, "which", lambda name: which.get(name))
    monkeypatch.setattr(node_runtime, "_recorded_node", lambda: None)
    monkeypatch.delenv("CRAFTBOT_NODE", raising=False)

    # The sidecar, laid out as nodejs.org's archive is.
    sidecar = tmp_path / "sidecar"
    root = sidecar / "node-v24.22.3-linux-x64"
    _node(root / "bin" / "node", "v24.22.3")
    cli = root / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("")
    (root / "bin" / "npm").symlink_to("../lib/node_modules/npm/bin/npm-cli.js")
    monkeypatch.setattr(node_runtime, "SIDECAR_DIR", sidecar)
    monkeypatch.setattr(node_runtime.Path, "home", lambda: tmp_path / "home")

    rt = node_runtime.resolve(refresh=True)

    assert rt.source == "discovered"
    assert rt.node == str(root / "bin" / "node")
    assert node_runtime.npm_command(rt) == [str(root / "bin" / "node"), str(cli)]
