"""Atomic profile snapshots. SQLite journals contain encrypted blobs only.

One connection per operation, with BEGIN IMMEDIATE for cross-process writers.
No database, temporary file or backup ever holds plaintext vault data or keys.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import stat

from .errors import VaultError, VaultErrorCode as Code
from .identity import VaultScope

MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


def _private(path: Path, *, directory: bool) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise VaultError(Code.IO)  # Includes Windows junctions/reparse points.
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise VaultError(Code.IO)
    if os.name == "nt":
        try:
            import win32security

            # Grant the object's owner and SYSTEM full access; inherit to children.
            sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                "D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)", 1
            )
            win32security.SetFileSecurity(
                str(path),
                win32security.DACL_SECURITY_INFORMATION
                | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                sd,
            )
        except Exception:
            raise VaultError(Code.BACKEND_UNAVAILABLE) from None
    else:
        if info.st_uid != os.geteuid():
            raise VaultError(Code.IO)
        os.chmod(path, 0o700 if directory else 0o600)


class SnapshotStore:
    def __init__(self, root: Path, scope: VaultScope) -> None:
        # Explicit host-owned root; never default to legacy .credentials or scan it.
        self.root = Path(root).absolute()
        self.directory = self.root / str(scope.owner_id) / str(scope.profile_id)
        self.path = self.directory / "vault.sqlite3"

    @contextmanager
    def transaction(self, *, write: bool = False, initialize: bool = False):
        connection = None
        try:
            if initialize:
                for directory in (self.root, self.directory.parent, self.directory):
                    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                    _private(directory, directory=True)
            else:
                for directory in (self.root, self.directory.parent, self.directory):
                    _private(directory, directory=True)
            if self.path.exists():
                _private(self.path, directory=False)
            elif not initialize:
                raise VaultError(Code.UNREADABLE)
            connection = sqlite3.connect(
                str(self.path) if initialize else self.path.as_uri() + "?mode=rw",
                timeout=5,
                uri=not initialize,
            )
            _private(self.path, directory=False)
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE" if write or initialize else "BEGIN")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if initialize and not tables and version == 0:
                connection.execute(
                    "CREATE TABLE vault (id INTEGER PRIMARY KEY CHECK(id=1), "
                    "current BLOB NOT NULL, previous BLOB)"
                )
                connection.execute("PRAGMA user_version=1")
            elif tables != {"vault"} or version != 1:
                raise VaultError(Code.UNREADABLE)
            elif initialize:
                raise VaultError(
                    Code.ALREADY_EXISTS
                    if connection.execute("SELECT 1 FROM vault WHERE id=1").fetchone()
                    else Code.UNREADABLE
                )
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
            raise VaultError(
                Code.UNREADABLE
                if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB)
                else Code.IO
            ) from None
        except OSError:
            raise VaultError(Code.IO) from None
        finally:
            if connection is not None:
                connection.close()  # Roll back any failed transaction.

    @staticmethod
    def read(connection) -> bytes:
        row = connection.execute(
            "SELECT length(current) FROM vault WHERE id=1"
        ).fetchone()
        if row is None or not 0 < row[0] <= MAX_SNAPSHOT_BYTES:
            raise VaultError(Code.UNREADABLE)
        row = connection.execute("SELECT current FROM vault WHERE id=1").fetchone()
        if not isinstance(row[0], bytes):
            raise VaultError(Code.UNREADABLE)
        return row[0]

    @staticmethod
    def write(connection, encrypted: bytes) -> None:
        if not 0 < len(encrypted) <= MAX_SNAPSHOT_BYTES:
            raise VaultError(Code.INVALID)
        connection.execute(
            "INSERT INTO vault(id,current) VALUES(1,?) "
            "ON CONFLICT(id) DO UPDATE SET previous=current, current=excluded.current",
            (encrypted,),
        )
