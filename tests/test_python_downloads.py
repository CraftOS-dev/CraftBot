"""A newer upstream release must not strand installs pinned to Python 3.10."""

import io
import json
import urllib.request
import urllib.error

import pytest

from app.provision import runtimes


@pytest.fixture(autouse=True)
def configured_context_window():
    """Download selection needs no model configuration."""


@pytest.mark.parametrize("triple", sorted(runtimes.PBS_310_TRIPLES))
def test_api_rate_limit_uses_known_release_asset(monkeypatch, triple):
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: triple)

    def rate_limited(request, **kwargs):
        raise urllib.error.HTTPError(
            request.full_url, 403, "rate limit exceeded", {}, None
        )

    monkeypatch.setattr(urllib.request, "urlopen", rate_limited)
    assert runtimes._pbs_download_url(lambda message: None) == (
        f"{runtimes.PBS_310_ARCHIVE}-{triple}-install_only.tar.gz"
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


@pytest.mark.parametrize(
    "triple",
    [
        "x86_64-pc-windows-msvc",
        "x86_64-unknown-linux-gnu",
        "x86_64-apple-darwin",
        "aarch64-apple-darwin",
    ],
)
def test_retired_python_uses_last_supported_release(monkeypatch, triple):
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: triple)
    requests = []

    def fetch(request, **kwargs):
        requests.append(request.full_url)
        assets = (
            []
            if request.full_url == runtimes.PBS_API
            else [
                {
                    "name": f"cpython-3.10.22+20261009-{triple}-install_only.tar.gz",
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
    assert requests == [runtimes.PBS_API, runtimes.PBS_310_API]


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
