"""Default filesystem CredentialStore for AccountSet documents.

Layout (``<project_root>/.credentials``):

    gmail.accounts.json        # AccountSet document
    .gmail.accounts.lock       # advisory-lock sidecar (empty)
    gmail.accounts.json.corrupt  # quarantined unparseable document
    gmail.json                 # not used; the account document is the store (
                               # read once by the upgrade migration, deleted
                               # when the last account is removed)

Guarantees:
  - ``replace`` is atomic (tmp file + os.replace) — a crash mid-write can
    never leave a torn document; the previous version survives.
  - ``locked`` serializes read-modify-write cycles across processes via
    fcntl.flock (POSIX) or msvcrt.locking (Windows) on the sidecar (the
    sidecar never gets replaced, so the
    lock's inode is stable — locking the data file itself would race with
    os.replace swapping inodes underneath the lock holder).
  - Unparseable documents are quarantined loudly, never silently treated
    as "no accounts" (which would look like a logout and destroy the
    evidence).
"""

from __future__ import annotations

import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

if os.name == "nt":
    import msvcrt

    def _lock_exclusive(f) -> None:
        # msvcrt.locking locks a byte range at the current file position, and
        # LK_LOCK gives up after ~10s — loop for flock-like blocking semantics.
        while True:
            try:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                continue

    def _lock_release(f) -> None:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_exclusive(f) -> None:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def _lock_release(f) -> None:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

from ..config import ConfigStore
from ..logger import get_logger

logger = get_logger(__name__)


class FileCredentialStore:
    def __init__(
        self,
        root: Optional[Path] = None,
    ) -> None:
        """``root`` defaults to ``<project_root>/.credentials``."""
        self._root = root

    # Resolved lazily: ConfigStore.project_root is set by the host at
    # startup, which may be after this store is constructed.
    def _dir(self) -> Path:
        path = self._root or (ConfigStore.project_root / ".credentials")
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path, stat.S_IRWXU)
        except OSError:
            pass
        return path

    def _path(self, provider_id: str) -> Path:
        return self._dir() / f"{provider_id}.accounts.json"

    # ────────────────────────────────────────────────────────────────────
    # CredentialStore protocol
    # ────────────────────────────────────────────────────────────────────

    def load(self, provider_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(provider_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            quarantine = path.with_suffix(path.suffix + ".corrupt")
            os.replace(path, quarantine)
            logger.error(
                f"[STORE] {path.name} is unparseable ({e}); quarantined to "
                f"{quarantine.name}. {provider_id} will read as disconnected — "
                f"the file is preserved for inspection/recovery."
            )
            return None

    def replace(self, provider_id: str, data: Dict[str, Any]) -> None:
        path = self._path(provider_id)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            if hasattr(os, "fchmod"):  # POSIX only; Windows ACLs don't map
                os.fchmod(f.fileno(), stat.S_IRUSR | stat.S_IWUSR)
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def delete(self, provider_id: str) -> None:
        path = self._path(provider_id)
        if path.exists():
            path.unlink()
            logger.info(f"[STORE] Removed {path.name}")

    @contextmanager
    def locked(self, provider_id: str) -> Iterator[None]:
        lock_path = self._dir() / f".{provider_id}.accounts.lock"
        with open(lock_path, "a+") as lock_file:
            _lock_exclusive(lock_file)
            try:
                yield
            finally:
                _lock_release(lock_file)

    def has_document(self, provider_id: str) -> bool:
        return self._path(provider_id).exists()

