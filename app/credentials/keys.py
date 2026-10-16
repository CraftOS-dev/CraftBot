"""Host key facility and owner-verification ports; no raw-file fallback.

Windows stores the encryption key as a generic OS credential, NOT beside the
vault. Same-user hostile code still requires the CM-03 isolation boundary.
"""

from __future__ import annotations

import sys
from typing import Protocol

from .errors import VaultError, VaultErrorCode as Code
from .identity import VaultOwner, VaultScope
from .secrets import Secret


def key_target(scope: VaultScope) -> str:
    return f"CraftBot/Vault/v1/{scope.owner_id}/{scope.profile_id}"


class KeyStore(Protocol):
    """Internal OS adapter. create is called under the profile write lock."""

    def load(self, scope: VaultScope) -> Secret | None: ...

    def create(self, scope: VaultScope, key: Secret) -> None: ...


class OwnerVerifier(Protocol):
    """Must perform real owner verification; caller flags are not evidence."""

    def verify(self, owner: VaultOwner) -> None: ...


class VerificationUnavailable:
    def verify(self, owner: VaultOwner) -> None:
        raise VaultError(Code.VERIFICATION_REQUIRED)


class WindowsCredentialKeyStore:
    """Uses the already-declared Windows pywin32 dependency, loaded lazily.

    No credential enumeration, user login-password access or key deletion.
    A missing Windows/logon/backend fails closed. Keys stay device-bound.
    """

    @staticmethod
    def _api():
        if sys.platform != "win32":
            raise VaultError(Code.BACKEND_UNAVAILABLE)
        try:
            import win32cred

            return win32cred
        except ImportError:
            raise VaultError(Code.BACKEND_UNAVAILABLE) from None

    def load(self, scope: VaultScope) -> Secret | None:
        api = self._api()
        try:
            record = Secret(api.CredRead(key_target(scope), api.CRED_TYPE_GENERIC, 0))
        except Exception as exc:
            if getattr(exc, "winerror", None) == 1168:  # ERROR_NOT_FOUND only
                return None
            raise VaultError(Code.BACKEND_UNAVAILABLE) from None
        key = Secret(record.reveal().get("CredentialBlob"))
        # pywin32 writes generic CredentialBlob strings as UTF-16LE and reads
        # bytes back. Fernet itself takes a 44-byte ASCII base64 key.
        if not isinstance(key.reveal(), bytes) or len(key.reveal()) != 88:
            raise VaultError(Code.UNREADABLE)
        try:
            key = Secret(key.reveal().decode("utf-16-le").encode("ascii"))
        except UnicodeError:
            raise VaultError(Code.UNREADABLE) from None
        if len(key.reveal()) != 44:
            raise VaultError(Code.UNREADABLE)
        return key

    def create(self, scope: VaultScope, key: Secret) -> None:
        if (
            not isinstance(key, Secret)
            or not isinstance(key.reveal(), bytes)
            or len(key.reveal()) != 44
        ):
            raise VaultError(Code.INVALID)
        if self.load(scope) is not None:
            raise VaultError(Code.CONFLICT)
        api = self._api()
        try:
            api.CredWrite(
                {
                    "Type": api.CRED_TYPE_GENERIC,
                    "TargetName": key_target(scope),
                    "UserName": "CraftBot vault key",
                    "CredentialBlob": key.reveal().decode("ascii"),
                    "Persist": api.CRED_PERSIST_LOCAL_MACHINE,
                },
                0,
            )
        except Exception:
            raise VaultError(Code.BACKEND_UNAVAILABLE) from None
