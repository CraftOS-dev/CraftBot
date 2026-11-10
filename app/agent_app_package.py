"""Locate and unpack CraftBot's pinned, unchanged Agent-App distribution.

Stdlib-only for installers. No network, package manager or app registry access.
Code ships in the source payload; its verified cache lives under STATE_ROOT.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

from app import paths

BUNDLE_DIR = Path("app/vendor/agent-app")
ARCHIVE = "agent-app-framework.zip"
PIN = "source.json"
REQUIRED = (
    "package.json",
    "LICENSE",
    "bin/agent-app.js",
    "bin/a2app.js",
    "dist/agent-app.js",
    "dist/a2app.js",
    "node_modules/@a2app/sdk/package.json",
    "node_modules/@a2app/sdk/dist/index.js",
    "node_modules/@a2app/rules/package.json",
    "node_modules/@a2app/rules/dist/index.js",
    "skills/index.json",
    "toolkits/blueprint-react-node/a2app.toolkit.json",
)


def bundled_files() -> list[str]:
    return [(BUNDLE_DIR / name).as_posix() for name in (PIN, ARCHIVE)]


def read_bundle(code_root: Path) -> tuple[dict, dict[str, bytes]]:
    """Verify the pin and archive before any executable bytes are installed."""
    folder = code_root / BUNDLE_DIR
    pin = json.loads((folder / PIN).read_text(encoding="utf-8"))
    if not re.fullmatch(r"[0-9a-f]{64}", pin.get("sha256", "")) or not re.fullmatch(
        r"[0-9a-f]{40}", pin.get("revision", "")
    ):
        raise ValueError("Invalid Agent-App distribution pin.")
    content = (folder / ARCHIVE).read_bytes()
    if hashlib.sha256(content).hexdigest() != pin["sha256"]:
        raise ValueError(
            "Bundled Agent-App checksum mismatch; restore the pinned distribution."
        )
    files = {}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            if (
                info.orig_filename != info.filename
                or name.is_absolute()
                or ".." in name.parts
                or "\\" in info.filename
                or ":" in info.filename
                or info.filename != name.as_posix()
                or info.filename in files
                or (info.external_attr >> 16) & 0o170000 != 0o100000
            ):
                raise ValueError(f"Invalid Agent-App bundle entry: {info.filename}")
            files[info.filename] = archive.read(info)
    missing = set(REQUIRED) - files.keys()
    if missing:
        raise ValueError(f"Incomplete Agent-App bundle: {sorted(missing)}")
    package = json.loads(files["package.json"])
    if (
        package.get("name") != "agent-app-framework"
        or package.get("version") != pin["version"]
    ):
        raise ValueError("Agent-App package identity/version differs from its pin.")
    return pin, files


def _cache(state_root: Path, pin: dict) -> Path:
    return state_root / "runtime/agent-app" / pin["sha256"]


def _verify_cache(folder: Path, files: dict[str, bytes]) -> None:
    for name, expected in files.items():
        path = folder / name
        if not path.is_file() or path.read_bytes() != expected:
            raise ValueError(
                f"Pinned Agent-App cache is incomplete or modified: {path}. "
                f"Remove the cache at {folder} and retry."
            )


def cached_package(code_root: Path, state_root: Path) -> Path | None:
    """Read-only installer/doctor check; never creates a cache."""
    pin, files = read_bundle(code_root)
    folder = _cache(state_root, pin)
    if not folder.exists():
        return None
    _verify_cache(folder, files)
    return folder


def ensure_package(
    code_root: Path | None = None, state_root: Path | None = None
) -> Path:
    """Publish a complete cache atomically; concurrent callers share that result."""
    pin, files = read_bundle(code_root if code_root is not None else paths.CODE_ROOT)
    folder = _cache(state_root if state_root is not None else paths.STATE_ROOT, pin)
    if folder.exists():
        _verify_cache(folder, files)
        return folder
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".unpack-", dir=folder.parent) as temporary:
        staged = Path(temporary) / "package"
        for name, data in files.items():
            path = staged / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        deadline = time.monotonic() + 10
        while True:
            try:
                os.rename(staged, folder)
                break
            except OSError as error:
                # Another process can publish the same content while we unpack.
                if folder.is_dir():
                    _verify_cache(folder, files)
                    break
                # Windows scanners can briefly hold newly extracted files.
                # Never replace a destination or mask a permanent/other failure.
                if (
                    getattr(error, "winerror", None) not in {5, 32}
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(0.1)
    return folder
