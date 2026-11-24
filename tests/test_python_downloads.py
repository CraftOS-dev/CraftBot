"""The private Python comes only from the pinned release, checked against its SHA-256."""

import json
import re
import urllib.request

import pytest

from app import downloads
from app.provision import runtimes
from app.provision.types import Context, Status

DOWNLOADS = json.loads(runtimes.PBS_CONFIG_PATH.read_text(encoding="utf-8"))
PLATFORMS = DOWNLOADS["fallback_platforms"]


@pytest.fixture
def download_config(monkeypatch, tmp_path):
    path = tmp_path / "python_downloads.json"
    monkeypatch.setattr(runtimes, "PBS_CONFIG_PATH", path)
    return path


@pytest.fixture(autouse=True)
def configured_context_window():
    """Download selection needs no model configuration."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Resolving the pinned build never asks GitHub anything, so a rate limit
    or an unreachable index cannot fail an install."""
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **kw: pytest.fail("network used")
    )


@pytest.mark.parametrize("triple", PLATFORMS)
def test_every_platform_resolves_its_pinned_archive(monkeypatch, triple):
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: triple)
    release, version = DOWNLOADS["fallback_release"], DOWNLOADS["fallback_version"]
    assert runtimes._pbs_download(lambda message: None) == (
        f"{DOWNLOADS['download_base']}/{DOWNLOADS['repository']}/releases/download/"
        f"{release}/cpython-{version}%2B{release}-{triple}-install_only.tar.gz",
        DOWNLOADS["sha256"][triple],
    )
    assert re.fullmatch(r"[0-9a-f]{64}", DOWNLOADS["sha256"][triple])


def test_platform_without_a_pin_is_refused(monkeypatch, download_config):
    triple = PLATFORMS[0]
    pins = {k: v for k, v in DOWNLOADS["sha256"].items() if k != triple}
    download_config.write_text(json.dumps(dict(DOWNLOADS, sha256=pins)))
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: triple)
    logs = []
    assert runtimes._pbs_download(logs.append) is None
    assert any("no pinned Python" in message for message in logs)


@pytest.mark.parametrize(
    "version,triple",
    [("3.11.0", PLATFORMS[0]), (DOWNLOADS["fallback_version"], "unsupported")],
)
def test_configuration_cannot_supply_wrong_version_or_platform(
    monkeypatch, download_config, version, triple
):
    download_config.write_text(json.dumps(dict(DOWNLOADS, fallback_version=version)))
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: triple)
    assert runtimes._pbs_download(lambda message: None) is None


@pytest.mark.parametrize("contents", [None, "not JSON", "{}"])
def test_missing_or_invalid_configuration_fails_clearly(
    monkeypatch, download_config, contents
):
    if contents is not None:
        download_config.write_text(contents, encoding="utf-8")
    logs = []
    assert runtimes._pbs_download(logs.append) is None
    assert "invalid Python download configuration" in logs[0]


def test_the_stage_downloads_against_the_pin(monkeypatch, tmp_path):
    triple = PLATFORMS[0]
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: triple)
    calls = []

    def download(url, dest, **kwargs):
        calls.append((url, kwargs.get("expected_sha256")))
        raise ValueError("SHA-256 verification failed")

    monkeypatch.setattr(downloads, "download", download)
    ctx = Context(code_root=str(tmp_path), state_root=str(tmp_path))
    result = runtimes.PythonStage().apply(ctx, lambda message: None)

    assert result.status == Status.FAILED
    assert calls == [runtimes._pbs_download(lambda message: None)]
    assert not (tmp_path / "runtime" / "python" / "python").exists()
