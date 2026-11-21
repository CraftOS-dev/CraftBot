"""The private Node comes only from the pinned release, checked against its SHA-256."""

import json
import re
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
