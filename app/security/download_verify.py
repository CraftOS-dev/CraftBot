"""Check downloaded programs against their publisher's checksum.

Hermes Agent pins a SHA-256 for every managed tool archive
(``pm/lock.json``) and OpenClaw checks npm ``dist.integrity`` and ClawHub's
sha256 before installing (both MIT). CraftBot fetches a few programs at run
time from each publisher's newest release, so there is nothing to pin in
the source; with "Verify downloads" on (Settings > Security > Tools), the
expected digest is taken from the publisher when the file is fetched:

- GitHub release assets (cloudflared, the Ollama installer): the asset's
  ``digest`` in GitHub's releases API, which GitHub computes on upload.
  The file is then fetched from that same release, so a new release
  published in between cannot cause a false mismatch.
- Node.js: ``SHASUMS256.txt``, published next to every release.
- python-build-standalone: the release's ``SHA256SUMS``.

A file that does not match, or whose digest cannot be obtained, is deleted
and the download fails. Downloads that already carry a pinned SHA-256 (the
embedding model, the bundled Agent App archives) are checked whatever this
setting says.

Stdlib only: node_runtime and the provisioning stages import this before
CraftBot's dependencies exist.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from typing import Optional, Tuple
from urllib.parse import quote

_TIMEOUT = 60
_MAX_METADATA = 4 * 1024 * 1024
_CHUNK = 256 * 1024
_GITHUB_API = "https://api.github.com"


class DownloadVerificationError(Exception):
    """A download could not be matched to its publisher's checksum."""


def enabled() -> bool:
    """Whether "Verify downloads" is on. False where CraftBot's settings
    cannot be read (a first install, before any exist)."""
    try:
        from app.security.policy import get_policy

        return bool(get_policy().verify_downloads)
    except Exception:
        return False


def _fetch(url: str, *, accept: str = "") -> bytes:
    """GET a small metadata document (a release record, a checksum list)."""
    try:
        from app.downloads import mirror_url, ssl_context

        fetched, context = mirror_url(url), ssl_context()
    except Exception:
        fetched, context = url, None
    headers = {"User-Agent": "CraftBot"}
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(fetched, headers=headers)
    with urllib.request.urlopen(request, timeout=_TIMEOUT, context=context) as response:
        return response.read(_MAX_METADATA)


def _hex_digest(value: str, what: str) -> str:
    value = (value or "").strip().lower()
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise DownloadVerificationError(f"{what} has no valid SHA-256 checksum")
    return value


def github_release_asset(repo: str, asset_name: str, tag: str = "latest") -> Tuple[str, str]:
    """(download URL, SHA-256) of a release asset, from GitHub's API."""
    owner_repo = "/".join(quote(part, safe="") for part in repo.split("/", 1))
    path = "latest" if tag == "latest" else f"tags/{quote(tag, safe='')}"
    url = f"{_GITHUB_API}/repos/{owner_repo}/releases/{path}"
    try:
        release = json.loads(_fetch(url, accept="application/vnd.github+json"))
    except Exception as exc:
        raise DownloadVerificationError(
            f"could not read the {repo} release to check {asset_name}: {exc}"
        ) from exc
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict) or asset.get("name") != asset_name:
            continue
        algorithm, _, value = str(asset.get("digest") or "").partition(":")
        if algorithm.lower() != "sha256":
            raise DownloadVerificationError(
                f"the {repo} release lists no SHA-256 checksum for {asset_name}"
            )
        download = asset.get("browser_download_url")
        if not download:
            break
        return download, _hex_digest(value, asset_name)
    raise DownloadVerificationError(
        f"{asset_name} is not in the {repo} release {release.get('tag_name') or tag}"
    )


def checksum_list_entry(sums_url: str, filename: str) -> str:
    """The SHA-256 a ``SHA256SUMS``-style list gives for ``filename``.

    Lines are ``<hex>  <name>`` (``*<name>`` in binary mode)."""
    try:
        text = _fetch(sums_url).decode("utf-8", "replace")
    except Exception as exc:
        raise DownloadVerificationError(
            f"could not read the checksum list for {filename}: {exc}"
        ) from exc
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1].strip().lstrip("*") == filename:
            return _hex_digest(parts[0], filename)
    raise DownloadVerificationError(f"the checksum list has no entry for {filename}")


def node_sha256(version: str, filename: str) -> str:
    """SHA-256 of a Node.js release file, from its SHASUMS256.txt."""
    return checksum_list_entry(
        f"https://nodejs.org/dist/{version}/SHASUMS256.txt", filename
    )


def sha256_of_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_bytes(data: bytes, expected: str, label: str) -> None:
    if hashlib.sha256(data).hexdigest() != expected:
        raise DownloadVerificationError(
            f"{label} does not match its publisher's checksum"
        )


def check_file(path: str, expected: str, label: str) -> None:
    """Raise, after deleting the file, when it does not match ``expected``."""
    try:
        actual: Optional[str] = sha256_of_file(path)
    except OSError:
        actual = None
    if actual == expected:
        return
    try:
        os.remove(path)
    except OSError:
        pass
    raise DownloadVerificationError(
        f"{label} does not match its publisher's checksum, so it was deleted"
    )
