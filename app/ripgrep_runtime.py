"""The ripgrep binary bundled with CraftBot, which grep_files runs.

The official release binary for every platform CraftBot ships is committed
under app/vendor/ripgrep/<target>/; scripts/vendor_ripgrep.py puts it there
after checking each archive against the checksum the release publishes.

The path comes from the code tree, never from user data, so the binary moves
and upgrades together with the code that parses its `--json` output. Nothing
is downloaded at runtime. The install pipeline only checks that the binary
runs (RipgrepStage): unzipping the install payload drops the executable bit
on macOS and Linux, and the stage restores it.

Stdlib-only: install.py imports the provisioning stages before any
dependencies exist.
"""

import platform
import sys
from pathlib import Path
from typing import List, Optional

# (sys.platform, machine) -> ripgrep release target, one per platform
# CraftBot ships a dependency lock for.
TARGETS = {
    ("win32", "x86_64"): "x86_64-pc-windows-msvc",
    ("darwin", "aarch64"): "aarch64-apple-darwin",
    ("linux", "x86_64"): "x86_64-unknown-linux-musl",
}

# platform.machine() spellings -> the names TARGETS uses.
_MACHINES = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
}

_CODE_ROOT = Path(__file__).resolve().parents[1]


def binary_name(plat: str = sys.platform) -> str:
    return "rg.exe" if plat == "win32" else "rg"


def bundled_files() -> List[str]:
    """Code-root-relative path of every bundled binary."""
    return [
        f"app/vendor/ripgrep/{target}/{binary_name(plat)}"
        for (plat, _machine), target in TARGETS.items()
    ]


def binary_path(code_root: Optional[Path] = None) -> Path:
    """Where this machine's rg sits under code_root (default: this code tree).

    Raises RuntimeError when CraftBot bundles no ripgrep for this platform.
    """
    machine = _MACHINES.get(platform.machine().lower(), platform.machine())
    target = TARGETS.get((sys.platform, machine))
    if target is None:
        raise RuntimeError(
            f"ripgrep is not bundled for {sys.platform} on {platform.machine()}"
        )
    root = code_root if code_root is not None else _CODE_ROOT
    return root / "app" / "vendor" / "ripgrep" / target / binary_name()


def resolve(code_root: Optional[Path] = None) -> str:
    """Path of the rg binary grep_files runs. Raises RuntimeError with the reason."""
    path = binary_path(code_root)
    if not path.is_file():
        raise RuntimeError(f"the bundled ripgrep is missing from this install: {path}")
    return str(path)
