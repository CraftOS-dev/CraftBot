"""Offline owner-file adapter for model Settings migration on Windows.

Reads/writes impersonate the unelevated enrolled owner. Vault/key operations run
as SYSTEM after reverting. Never use a SYSTEM file read on a caller-selected
path. Normal application writers must be stopped before this owner action.
"""

from contextlib import contextmanager, closing
import hashlib
import json
import os
from pathlib import Path
import stat
import re
from uuid import uuid4

from .errors import VaultError, VaultErrorCode as Code
from .secrets import Secret
from .windows_host import api


class OwnerSettingsSource:
    def __init__(self, path, owner_sid, session, *, filename="settings.json"):
        self.path = Path(path)
        if (
            not self.path.is_absolute()
            or not (
                filename
                in (
                    "settings.json",
                    "mini_browser_vault.enc",
                    "mini_browser_vault.enc.bak",
                    "mini_browser_vault.key",
                    ".env",
                    ".env.local",
                )
                or re.fullmatch(
                    r"(?:github|figma|slack|discord|stripe|notion|hubspot|posthog|supabase|line|telegram_bot|telegram_user|twitter|lark|lark_drive|lark_calendar|whatsapp_business|jira|gmail|google_drive|google_calendar|google_docs|google_youtube|linkedin|outlook)\.accounts\.json",
                    filename,
                )
            )
            or self.path.name != filename
            or len(self.path.drive) != 2
            or self.path.drive[1] != ":"
            or ".." in self.path.parts
            or any(ord(c) < 32 for c in str(path))
        ):
            raise VaultError(Code.INVALID)
        self.owner_sid, self.session = owner_sid, session
        self.handle = None
        self.digest = None

    @contextmanager
    def _owner(self):
        _, _, _, _, security, ts, _ = api()
        with closing(ts.WTSQueryUserToken(self.session)) as token:
            from .windows_host import token_value

            if security.ConvertSidToStringSid(
                security.GetTokenInformation(token, 1)[0]
            ) != self.owner_sid or token_value(token, 20):
                raise VaultError(Code.VERIFICATION_REQUIRED)
            security.ImpersonateLoggedOnUser(token)
            try:
                yield
            finally:
                try:
                    if security.RevertToSelf() is False:
                        os._exit(1)
                except BaseException:
                    os._exit(1)  # Never continue in an unknown security context.

    def read(self):
        return Secret(json.loads(self.read_bytes().reveal()))

    def read_bytes(self, limit=4_000_000):
        import win32file

        with self._owner():
            for path in (self.path, *self.path.parents):
                attributes = path.stat(follow_symlinks=False)
                if (
                    stat.S_ISLNK(attributes.st_mode)
                    or attributes.st_file_attributes & 0x400
                ):
                    raise VaultError(Code.INVALID)
            self.handle = win32file.CreateFile(
                str(self.path), 0x80000000, 1 | 4, None, 3, 0x00200000, None
            )
            info = win32file.GetFileInformationByHandle(self.handle)
            if info[0] & 0x400:
                raise VaultError(Code.INVALID)
            raw = Secret(win32file.ReadFile(self.handle, limit + 1)[1])
            if len(raw.reveal()) > limit:
                raise VaultError(Code.INVALID)
        self.digest = Secret(hashlib.sha256(raw.reveal()).digest())
        return raw

    def commit(self, document: Secret):
        encoded = Secret(
            json.dumps(
                document.reveal(), indent=2, ensure_ascii=False, allow_nan=False
            ).encode("utf-8")
        )
        self.commit_bytes(encoded)

    def commit_text(self, document: Secret):
        self.commit_bytes(Secret(document.reveal().encode("utf-8")))

    def commit_bytes(self, encoded: Secret):
        if self.handle is None or self.digest is None:
            raise VaultError(Code.INVALID)
        import hmac
        import win32file

        temporary = self.path.with_name(".credential-migration-" + uuid4().hex + ".tmp")
        with self._owner():
            # The retained source handle denies in-place writers. Check a second
            # pathname read too, so an atomic replacement by another owner writer
            # is detected. This is an offline migration, not a live refresh hook.
            current = Secret(self.path.read_bytes())
            if not hmac.compare_digest(
                self.digest.reveal(), hashlib.sha256(current.reveal()).digest()
            ):
                raise VaultError(Code.CONFLICT)
            try:
                with temporary.open("xb") as stream:
                    stream.write(encoded.reveal())
                    stream.flush()
                    os.fsync(stream.fileno())
                win32file.MoveFileEx(str(temporary), str(self.path), 1 | 8)
            finally:
                temporary.unlink(missing_ok=True)
                self.handle.Close()
                self.handle = None

    def close(self):
        if self.handle is not None:
            self.handle.Close()
            self.handle = None
