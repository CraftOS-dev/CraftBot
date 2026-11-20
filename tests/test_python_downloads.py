"""A newer upstream release must not strand installs pinned to Python 3.10."""

import io
import json
import urllib.request
import urllib.error

import pytest

from app.provision import runtimes

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


@pytest.mark.parametrize("triple", PLATFORMS)
def test_api_rate_limit_uses_known_release_asset(monkeypatch, triple):
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: triple)

    def rate_limited(request, **kwargs):
        raise urllib.error.HTTPError(
            request.full_url, 403, "rate limit exceeded", {}, None
        )

    monkeypatch.setattr(urllib.request, "urlopen", rate_limited)
    assert runtimes._pbs_download_url(lambda message: None) == (
        f"{DOWNLOADS['download_base']}/{DOWNLOADS['repository']}/releases/download/"
        f"{DOWNLOADS['fallback_release']}/cpython-{DOWNLOADS['fallback_version']}"
        f"%2B{DOWNLOADS['fallback_release']}-{triple}-install_only.tar.gz"
    )


def test_unavailable_index_never_falls_back_to_wrong_python_version(monkeypatch):
    monkeypatch.setattr(runtimes, "TARGET_PYTHON", (3, 11))
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: "x86_64-unknown-linux-gnu")
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")),
    )
    assert runtimes._pbs_download_url(lambda message: None) is None


@pytest.mark.parametrize("triple", PLATFORMS)
def test_retired_python_uses_last_supported_release(monkeypatch, triple):
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: triple)
    requests = []
    api = f"{DOWNLOADS['api_base']}/repos/{DOWNLOADS['repository']}/releases"

    def fetch(request, **kwargs):
        requests.append(request.full_url)
        assets = (
            []
            if request.full_url == f"{api}/latest"
            else [
                {
                    "name": (
                        f"cpython-{DOWNLOADS['fallback_version']}"
                        f"+{DOWNLOADS['fallback_release']}-{triple}-install_only.tar.gz"
                    ),
                    "browser_download_url": "https://example.test/compatible-python.tar.gz",
                }
            ]
        )
        return io.BytesIO(json.dumps({"assets": assets}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fetch)
    assert (
        runtimes._pbs_download_url(lambda message: None)
        == "https://example.test/compatible-python.tar.gz"
    )
    assert requests == [f"{api}/latest", f"{api}/tags/{DOWNLOADS['fallback_release']}"]


def test_latest_matching_asset_takes_priority(monkeypatch):
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: "x86_64-unknown-linux-gnu")
    requests = []

    def fetch(request, **kwargs):
        requests.append(request.full_url)
        return io.BytesIO(
            json.dumps(
                {
                    "assets": [
                        {
                            "name": "cpython-3.10.99+test-x86_64-unknown-linux-gnu-install_only.tar.gz",
                            "browser_download_url": "https://example.test/newer-python.tar.gz",
                        }
                    ]
                }
            ).encode()
        )

    monkeypatch.setattr(urllib.request, "urlopen", fetch)
    assert runtimes._pbs_download_url(lambda message: None) == (
        "https://example.test/newer-python.tar.gz"
    )
    assert len(requests) == 1


@pytest.mark.parametrize("fail_on", [1, 2])
def test_configuration_controls_indexes_archive_and_log(
    monkeypatch, download_config, fail_on
):
    config = dict(
        DOWNLOADS,
        api_base="https://api.example.test/",
        download_base="https://downloads.example.test/",
        repository="maintainer/python",
        fallback_release="20990101",
        fallback_version="3.10.99",
        fallback_platforms=["test-platform"],
    )
    download_config.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: "test-platform")
    requests, logs = [], []

    def fetch(request, **kwargs):
        requests.append(request.full_url)
        if len(requests) == fail_on:
            raise OSError("index unavailable")
        return io.BytesIO(b'{"assets": []}')

    monkeypatch.setattr(urllib.request, "urlopen", fetch)
    assert runtimes._pbs_download_url(logs.append) == (
        "https://downloads.example.test/maintainer/python/releases/download/20990101/"
        "cpython-3.10.99%2B20990101-test-platform-install_only.tar.gz"
    )
    assert (
        requests
        == [
            "https://api.example.test/repos/maintainer/python/releases/latest",
            "https://api.example.test/repos/maintainer/python/releases/tags/20990101",
        ][:fail_on]
    )
    assert any("archived Python 3.10.99" in message for message in logs)


@pytest.mark.parametrize(
    "version,triple",
    [("3.11.0", PLATFORMS[0]), (DOWNLOADS["fallback_version"], "unsupported")],
)
def test_configuration_cannot_supply_wrong_version_or_platform(
    monkeypatch, download_config, version, triple
):
    download_config.write_text(json.dumps(dict(DOWNLOADS, fallback_version=version)))
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: triple)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")),
    )
    assert runtimes._pbs_download_url(lambda message: None) is None


@pytest.mark.parametrize("contents", [None, "not JSON", "{}"])
def test_missing_or_invalid_configuration_fails_clearly(
    monkeypatch, download_config, contents
):
    if contents is not None:
        download_config.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **kw: pytest.fail("network used")
    )
    logs = []
    assert runtimes._pbs_download_url(logs.append) is None
    assert "invalid Python download configuration" in logs[0]


def test_missing_matching_python_does_not_select_a_different_version(monkeypatch):
    data = {
        "assets": [
            {
                "name": "cpython-3.11.0+20261110-x86_64-unknown-linux-gnu-install_only.tar.gz",
                "browser_download_url": "https://example.test/wrong-python.tar.gz",
            }
        ]
    }
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: "x86_64-unknown-linux-gnu")
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **kw: io.BytesIO(json.dumps(data).encode()),
    )
    assert runtimes._pbs_download_url(lambda message: None) is None
