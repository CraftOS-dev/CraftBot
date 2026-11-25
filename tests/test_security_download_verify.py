"""Verify downloads: run-time downloads must match their publisher's checksum."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

import pytest

from app.security import download_verify
from app.security.download_verify import DownloadVerificationError
from app.security.policy import SecurityStore, set_store_for_tests

PAYLOAD = b"the real program"
GOOD = hashlib.sha256(PAYLOAD).hexdigest()
BAD = hashlib.sha256(b"something else").hexdigest()


@pytest.fixture
def store(tmp_path):
    store = SecurityStore(tmp_path / "security.json")
    set_store_for_tests(store)
    yield store
    set_store_for_tests(None)


@pytest.fixture
def metadata(monkeypatch):
    """Stub publisher metadata: url -> bytes. Records every fetch."""
    served = {}
    fetched = []

    def fake(url, *, accept=""):
        fetched.append(url)
        if url not in served:
            raise OSError(f"404 {url}")
        return served[url]

    monkeypatch.setattr(download_verify, "_fetch", fake)
    return served, fetched


def release(name, digest, url="https://github.com/o/r/releases/download/v1/"):
    return json.dumps(
        {
            "tag_name": "v1",
            "assets": [
                {"name": name, "digest": digest, "browser_download_url": url + name}
            ],
        }
    ).encode()


# ── the checks themselves ──


def test_github_asset_digest(metadata):
    served, _ = metadata
    served["https://api.github.com/repos/o/r/releases/latest"] = release("tool", f"sha256:{GOOD}")
    url, digest = download_verify.github_release_asset("o/r", "tool")
    assert url.endswith("/v1/tool") and digest == GOOD


@pytest.mark.parametrize("digest", ["", "md5:abc", "sha256:nothex"])
def test_github_asset_without_a_usable_digest_fails(metadata, digest):
    served, _ = metadata
    served["https://api.github.com/repos/o/r/releases/latest"] = release("tool", digest)
    with pytest.raises(DownloadVerificationError):
        download_verify.github_release_asset("o/r", "tool")


def test_github_asset_missing_fails(metadata):
    served, _ = metadata
    served["https://api.github.com/repos/o/r/releases/latest"] = release("other", f"sha256:{GOOD}")
    with pytest.raises(DownloadVerificationError):
        download_verify.github_release_asset("o/r", "tool")


def test_checksum_list(metadata):
    served, _ = metadata
    served["https://x/SUMS"] = f"{BAD}  other.tar.gz\n{GOOD} *file.tar.gz\n".encode()
    assert download_verify.checksum_list_entry("https://x/SUMS", "file.tar.gz") == GOOD
    with pytest.raises(DownloadVerificationError):
        download_verify.checksum_list_entry("https://x/SUMS", "missing.tar.gz")


def test_unreachable_checksum_list_fails(metadata):
    with pytest.raises(DownloadVerificationError):
        download_verify.checksum_list_entry("https://x/SUMS", "file.tar.gz")


def test_check_file(tmp_path):
    good = tmp_path / "good"
    good.write_bytes(PAYLOAD)
    download_verify.check_file(str(good), GOOD, "good")
    bad = tmp_path / "bad"
    bad.write_bytes(b"tampered")
    with pytest.raises(DownloadVerificationError):
        download_verify.check_file(str(bad), GOOD, "bad")
    assert not bad.exists()


def test_enabled_follows_the_setting(store):
    assert download_verify.enabled() is False
    store.update({"verify_downloads": True})
    assert download_verify.enabled() is True


# ── cloudflared ──


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture
def cloudflared(tmp_path, monkeypatch):
    import sys

    from app.agent_app import sharing

    monkeypatch.setattr(sys, "platform", "linux")
    channel = sharing.TunnelChannel(terminate=lambda _p: None)
    monkeypatch.setattr(sharing.TunnelChannel, "_BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(channel, "_cloudflared_path", lambda: None)
    downloaded = []

    def fake_urlopen(request, timeout=None, context=None):
        downloaded.append(request.full_url)
        return _Response(PAYLOAD)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return channel, downloaded, tmp_path / "bin" / "cloudflared"


API = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"


def test_cloudflared_unchecked_when_off(store, metadata, cloudflared):
    _, fetched = metadata
    channel, downloaded, target = cloudflared
    assert asyncio.run(channel._ensure_cloudflared()) == str(target)
    assert fetched == []
    assert downloaded == [channel._CLOUDFLARED_URLS["linux"]]


def test_cloudflared_matching_digest_installs_that_release(store, metadata, cloudflared):
    served, _ = metadata
    channel, downloaded, target = cloudflared
    store.update({"verify_downloads": True})
    served[API] = release("cloudflared-linux-amd64", f"sha256:{GOOD}")
    assert asyncio.run(channel._ensure_cloudflared()) == str(target)
    assert target.read_bytes() == PAYLOAD
    assert downloaded == ["https://github.com/o/r/releases/download/v1/cloudflared-linux-amd64"]


def test_cloudflared_mismatch_is_not_installed(store, metadata, cloudflared):
    served, _ = metadata
    channel, _, target = cloudflared
    store.update({"verify_downloads": True})
    served[API] = release("cloudflared-linux-amd64", f"sha256:{BAD}")
    assert asyncio.run(channel._ensure_cloudflared()) is None
    assert not target.exists()


def test_cloudflared_without_a_digest_is_not_installed(store, metadata, cloudflared):
    channel, downloaded, target = cloudflared
    store.update({"verify_downloads": True})
    assert asyncio.run(channel._ensure_cloudflared()) is None
    assert downloaded == [] and not target.exists()


# ── Node ──


@pytest.fixture
def node(tmp_path, monkeypatch):
    from app import downloads, node_runtime

    suffix, ext = node_runtime._platform_suffix()
    ver = "v24.1.0"
    name = f"node-{ver}-{suffix}.{ext}"
    buffer = io.BytesIO()
    mode = "w:xz" if ext == "tar.xz" else "w:gz"
    if ext == "zip":
        pytest.skip("the Windows zip layout is covered elsewhere")
    with tarfile.open(fileobj=buffer, mode=mode) as tar:
        data = b"#!/bin/sh\n"
        info = tarfile.TarInfo(f"node-{ver}-{suffix}/bin/node")
        info.size = len(data)
        info.mode = 0o755
        tar.addfile(info, io.BytesIO(data))
    archive = buffer.getvalue()
    monkeypatch.setattr(node_runtime, "SIDECAR_DIR", tmp_path / "sidecar")
    monkeypatch.setattr(downloads, "cache_dir", lambda: None)

    def fake_once(url, dest, *args, **kwargs):
        Path(dest).write_bytes(archive)
        return dest

    monkeypatch.setattr(downloads, "_download_once", fake_once)
    url = f"https://nodejs.org/dist/{ver}/{name}"
    sums = f"https://nodejs.org/dist/{ver}/SHASUMS256.txt"
    digest = hashlib.sha256(archive).hexdigest()
    return node_runtime, ver, suffix, ext, url, sums, name, digest, archive


def test_node_unchecked_when_off(store, metadata, node):
    node_runtime, ver, suffix, ext, url, *_ = node
    _, fetched = metadata
    assert node_runtime._extract_node(None, ver, suffix, ext, lambda _m: None, url)
    assert fetched == []


def test_node_matching_shasums_installs(store, metadata, node):
    node_runtime, ver, suffix, ext, url, sums, name, digest, _ = node
    served, _ = metadata
    store.update({"verify_downloads": True})
    served[sums] = f"{BAD}  node-other.tar.gz\n{digest}  {name}\n".encode()
    assert node_runtime._extract_node(None, ver, suffix, ext, lambda _m: None, url)


def test_node_mismatch_is_not_installed(store, metadata, node):
    node_runtime, ver, suffix, ext, url, sums, name, *_ = node
    served, _ = metadata
    store.update({"verify_downloads": True})
    served[sums] = f"{BAD}  {name}\n".encode()
    said = []
    assert node_runtime._extract_node(None, ver, suffix, ext, said.append, url) is None
    assert any("SHA-256" in line for line in said)


def test_node_cached_archive_is_checked(store, metadata, node, tmp_path):
    node_runtime, ver, suffix, ext, url, sums, name, _, archive = node
    served, _ = metadata
    store.update({"verify_downloads": True})
    served[sums] = f"{BAD}  {name}\n".encode()
    cached = tmp_path / name
    cached.write_bytes(archive)
    assert node_runtime._extract_node(str(cached), ver, suffix, ext, lambda _m: None, url) is None


# ── python-build-standalone ──

PBS = "https://github.com/astral-sh/python-build-standalone/releases/download/20261009"
PBS_NAME = "cpython-3.10.22+20261009-x86_64-unknown-linux-gnu-install_only.tar.gz"


def test_pbs_unchecked_when_off(store, metadata):
    from app.provision import runtimes

    _, fetched = metadata
    assert runtimes._pbs_expected_sha256(f"{PBS}/x.tar.gz", None) is None
    assert fetched == []


def test_pbs_digest_from_the_release_list(store, metadata):
    from app.provision import runtimes

    served, _ = metadata
    store.update({"verify_downloads": True})
    served[f"{PBS}/SHA256SUMS"] = f"{GOOD}  {PBS_NAME}\n".encode()
    url = f"{PBS}/cpython-3.10.22%2B20261009-x86_64-unknown-linux-gnu-install_only.tar.gz"
    assert runtimes._pbs_expected_sha256(url, None) == GOOD
    assert runtimes._pbs_expected_sha256(None, f"/cache/{PBS_NAME}") == GOOD


def test_pbs_mismatch_fails_the_stage(store, metadata, tmp_path, monkeypatch):
    from app import downloads
    from app.provision import runtimes
    from app.provision.types import Context, Status

    served, _ = metadata
    store.update({"verify_downloads": True})
    served[f"{PBS}/SHA256SUMS"] = f"{GOOD}  {PBS_NAME}\n".encode()
    cached = tmp_path / PBS_NAME
    cached.write_bytes(b"tampered archive")
    monkeypatch.setattr(downloads, "find_cached", lambda _pattern: str(cached))
    monkeypatch.setattr(runtimes, "_pbs_triple", lambda: "x86_64-unknown-linux-gnu")
    ctx = Context(code_root=str(tmp_path), state_root=str(tmp_path / "state"))
    result = runtimes.PythonStage().apply(ctx, lambda _m: None)
    assert result.status == Status.FAILED
    assert "checksum" in result.detail
