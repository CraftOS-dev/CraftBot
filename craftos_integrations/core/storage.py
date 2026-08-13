"""Default filesystem CredentialStore for AccountSet documents.

Layout (same directory as the legacy store, ``<project_root>/.credentials``):

    gmail.accounts.json        # AccountSet document
    .gmail.accounts.lock       # advisory-lock sidecar (empty)
    gmail.accounts.json.corrupt  # quarantined unparseable document
    gmail.json                 # legacy single-credential file (pre-multi-account installs;
                               # read once by the upgrade migration, deleted
                               # when the last account is removed)

Guarantees:
  - ``replace`` is atomic (tmp file + os.replace) — a crash mid-write can
    never leave a torn document; the previous version survives.
  - ``locked`` serializes read-modify-write cycles across processes via
    fcntl.flock on the sidecar (the sidecar never gets replaced, so the
    lock's inode is stable — locking the data file itself would race with
    os.replace swapping inodes underneath the lock holder).
  - Unparseable documents are quarantined loudly, never silently treated
    as "no accounts" (which would look like a logout and destroy the
    evidence).
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional

from ..config import ConfigStore
from ..logger import get_logger

logger = get_logger(__name__)


class FileCredentialStore:
    def __init__(
        self,
        root: Optional[Path] = None,
        legacy_filenames: Optional[Mapping[str, str]] = None,
    ) -> None:
        """``root`` defaults to the legacy store's directory so migration can
        find pre-multi-account files. ``legacy_filenames`` maps provider ids whose old
        cred file isn't simply ``<provider_id>.json``."""
        self._root = root
        self._legacy_filenames = dict(legacy_filenames or {})

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
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def has_document(self, provider_id: str) -> bool:
        return self._path(provider_id).exists()

    def _legacy_path(self, provider_id: str) -> Path:
        filename = self._legacy_filenames.get(provider_id, f"{provider_id}.json")
        return self._dir() / filename

    def delete_legacy(self, provider_id: str) -> None:
        """Remove the pre-multi-account single-account credential file, if present.

        Called by the system when the last account is removed: the
        one-time upgrade migration re-imports any surviving legacy file
        into a provider with no AccountSet document, so a disconnect must delete
        both the document AND the legacy file or the just-removed account
        would resurrect on the next load."""
        legacy = self._legacy_path(provider_id)
        if legacy.exists():
            legacy.unlink()
            logger.info(f"[STORE] Removed legacy {legacy.name}")

    def load_legacy(self, provider_id: str) -> Optional[Dict[str, Any]]:
        path = self._legacy_path(provider_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # A corrupt legacy file just means "nothing to migrate" —
            # leave it in place for inspection.
            logger.warning(f"[STORE] Legacy {path.name} unparseable, skipping: {e}")
            return None
