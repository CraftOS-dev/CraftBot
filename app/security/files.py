"""Owner-only file creation for anything that holds secrets.

One helper creates such files, so permissions cannot regress through an
ad-hoc ``open()`` (Hermes CVE-2026-53870, Pi CVE-2026-54327). Files are
created ``0600`` at open time, never chmod-ed afterwards, and replaced
atomically. On Windows the mode bits are a no-op and the per-user profile
directory's ACL is what protects them.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterable

OWNER_FILE = stat.S_IRUSR | stat.S_IWUSR  # 0600
OWNER_DIR = stat.S_IRWXU  # 0700


def ensure_private_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, OWNER_DIR)
    except OSError:
        pass
    return path


def write_private_bytes(path: Path, data: bytes) -> None:
    """Atomically replace ``path`` with ``data``, readable by the owner only."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        # mkstemp already creates the file 0600; make that explicit for
        # platforms whose umask handling differs.
        try:
            os.fchmod(fd, OWNER_FILE)
        except (AttributeError, OSError):
            pass
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_private_json(path: Path, value: Any) -> None:
    data = json.dumps(value, indent=2, ensure_ascii=False).encode("utf-8")
    write_private_bytes(path, data)


def restrict_to_owner(path: Path) -> bool:
    """Tighten an existing secret file to owner-only. True when it changed."""
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return False
    if not stat.S_ISREG(mode) or stat.S_IMODE(mode) & 0o077 == 0:
        return False
    try:
        os.chmod(path, OWNER_FILE)
        return True
    except OSError:
        return False


def is_private(path: Path) -> bool:
    """Whether a file is readable by its owner alone (always True on Windows)."""
    if os.name == "nt":
        return True
    try:
        return stat.S_IMODE(os.stat(path).st_mode) & 0o077 == 0
    except OSError:
        return True


def restrict_all(paths: Iterable[Path]) -> int:
    return sum(1 for p in paths if restrict_to_owner(p))
