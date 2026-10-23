#!/usr/bin/env python3
"""Refresh the ripgrep binaries committed under app/vendor/ripgrep/.

What this is for
    grep_files runs a ripgrep (rg) binary that ships inside CraftBot, one per
    platform listed in app.ripgrep_runtime.TARGETS. Those binaries are already
    committed, so nothing runs this script at install time or at runtime. It
    exists for the two moments the committed binaries have to change, and as a
    record of exactly where they came from.

When to run it
    * Upgrading ripgrep: change VERSION below, then run it.
    * Supporting another platform: add the platform to
      app.ripgrep_runtime.TARGETS (its release target name is in the asset
      list of the GitHub release), then run it.

How
    1. python scripts/vendor_ripgrep.py
    2. python -m pytest tests/test_ripgrep_runtime.py tests/test_grep_files.py
    3. Stage the binaries. Git on Windows does not record the executable bit
       (core.fileMode=false), so mark the macOS and Linux ones explicitly or a
       git clone or Docker image will get files rg cannot be run from:
           git add app/vendor/ripgrep
           git update-index --chmod=+x app/vendor/ripgrep/*/rg
       Check with `git ls-files -s app/vendor/ripgrep`: rg entries must read 100755.

What it guarantees
    Every binary comes from the official release at
    github.com/BurntSushi/ripgrep and matches the .sha256 file that release
    publishes next to the archive. A mismatch stops the script before anything
    is written. The checksum comes from the same release, so it proves the
    download is intact, not that the release itself is trustworthy.
"""

from __future__ import annotations

import hashlib
import io
import re
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Lets the script import app.* when run from anywhere as a plain file.
sys.path.insert(0, str(REPO_ROOT))

# The ripgrep release the committed binaries are taken from. Bumping this is
# the whole upgrade; grep_files parses `rg --json`, so run the tests after.
VERSION = "15.2.0"

_RELEASE = "https://github.com/BurntSushi/ripgrep/releases/download/{version}/{asset}"


def _fetch(url: str) -> bytes:
    """Download url into memory. Archives are about 2 MB each."""
    # CraftBot's shared SSL context: it prefers certifi's roots because the
    # Windows certificate store fails to load under some OpenSSL builds.
    from app import downloads

    req = urllib.request.Request(url, headers={"User-Agent": "CraftBot"})
    with urllib.request.urlopen(
        req, timeout=120, context=downloads.ssl_context()
    ) as resp:
        return resp.read()


def _published_sha256(asset_url: str) -> str:
    """The sha256 the release publishes for asset_url, from <asset>.sha256."""
    # The two formats differ: Unix assets publish "<hex>  <name>", Windows ones
    # publish CertUtil output with the hex on its own line. Both contain exactly
    # one 64-character hex string, and anything else is refused rather than
    # guessed at.
    text = _fetch(asset_url + ".sha256").decode("utf-8", "replace")
    found = re.findall(r"\b[0-9a-fA-F]{64}\b", text)
    if len(found) != 1:
        raise RuntimeError(f"unexpected checksum file for {asset_url}: {text!r}")
    return found[0].lower()


def _binary_from_archive(archive: bytes, ext: str, member: str) -> bytes:
    """Read one file out of a release archive (.zip on Windows, .tar.gz elsewhere)."""
    if ext == ".zip":
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            return zf.read(member)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        handle = tf.extractfile(member)
        if handle is None:
            raise RuntimeError(f"{member} is not a file in the archive")
        return handle.read()


def main() -> int:
    # TARGETS is the single list of bundled platforms: grep_files resolves its
    # binary from it, the release build (scripts/package_source.py) refuses a
    # payload missing any of them, and this script fills exactly those folders.
    from app import ripgrep_runtime

    for (plat, _machine), target in ripgrep_runtime.TARGETS.items():
        ext = ".zip" if plat == "win32" else ".tar.gz"
        name = ripgrep_runtime.binary_name(plat)
        url = _RELEASE.format(version=VERSION, asset=f"ripgrep-{VERSION}-{target}{ext}")

        print(f"{target}:")
        archive = _fetch(url)
        expected = _published_sha256(url)
        actual = hashlib.sha256(archive).hexdigest()
        if actual != expected:
            print(
                f"  sha256 {actual} does not match the published {expected}",
                file=sys.stderr,
            )
            return 1
        print(f"  verified sha256 {actual}")

        # Release archives keep everything under ripgrep-<version>-<target>/;
        # only the rg binary is kept (docs and shell completions are not needed).
        binary = _binary_from_archive(
            archive, ext, f"ripgrep-{VERSION}-{target}/{name}"
        )
        dest = REPO_ROOT / "app" / "vendor" / "ripgrep" / target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(binary)
        # Takes effect on macOS and Linux only. On Windows the bit has to be set
        # in git instead (see step 3 at the top).
        if plat != "win32":
            dest.chmod(0o755)
        print(f"  wrote {dest.relative_to(REPO_ROOT)} ({len(binary) / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
