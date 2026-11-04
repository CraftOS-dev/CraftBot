"""Release-owned runtime downloads. Stdlib-only: used before pip is available."""

import json
import platform
import sys
from pathlib import Path
from urllib.parse import urlparse

MANIFEST_PATH = Path(__file__).with_name("runtime-manifest.json")


def manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def version(runtime):
    return manifest()[runtime]["version"]


def target(runtime):
    machine = platform.machine().lower()
    if machine not in ("amd64", "x86_64", "arm64", "aarch64"):
        raise ValueError(f"Unsupported CPU architecture: {machine}")
    arm = machine in ("arm64", "aarch64")
    if runtime == "python":
        # The locked Windows Python is x64, including under ARM64 emulation.
        if sys.platform == "win32":
            return "x86_64-pc-windows-msvc"
        arch = "aarch64" if arm else "x86_64"
        suffix = {"darwin": "apple-darwin", "linux": "unknown-linux-gnu"}
    else:
        arch = "arm64" if arm else "x64"
        suffix = {"win32": "win", "darwin": "darwin", "linux": "linux"}
    if sys.platform not in suffix:
        raise ValueError(f"Unsupported operating system: {sys.platform}")
    return (
        f"{arch}-{suffix[sys.platform]}"
        if runtime == "python"
        else f"{suffix[sys.platform]}-{arch}"
    )


def asset(runtime, platform_target=None):
    key = platform_target or target(runtime)
    try:
        item = manifest()[runtime]["assets"][key]
    except KeyError as exc:
        raise ValueError(f"No approved {runtime} download for {key}") from exc
    digest = item.get("sha256", "")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError(f"Invalid {runtime} checksum for {key}")
    if urlparse(item["url"]).scheme != "https":
        raise ValueError("Runtime downloads must use HTTPS")
    return item
