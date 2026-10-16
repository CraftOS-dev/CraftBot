"""Owner-only offline retirement of the three current legacy browser files.

Encrypted legacy history is archived under the SYSTEM state root. Its old key
is itself encrypted inside a non-usable vault recovery item, never a key file.
The metadata journal makes source deletion resumable after destination proof.
"""

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from uuid import uuid5

from .contracts import CredentialKind
from .errors import VaultError, VaultErrorCode as Code
from .migration import migrate_browser_document
from .migration_source import OwnerSettingsSource
from .references import parse
from .secrets import Secret
from .windows_host import private_acl

FILES = (
    "mini_browser_vault.enc",
    "mini_browser_vault.enc.bak",
    "mini_browser_vault.key",
)


def migrate_browser_files(vault, path, state: Path, owner_sid, session):
    from cryptography.fernet import Fernet

    path = Path(path)
    if path.name != FILES[0]:
        raise VaultError(Code.INVALID)
    source_id = hashlib.sha256(str(path).casefold().encode("utf-8")).hexdigest()
    archive = state / "legacy-browser" / str(vault.profile.scope.profile_id) / source_id
    archive.mkdir(parents=True, exist_ok=True)
    private_acl(archive)
    journal = archive / "migration.json"
    sources = {}
    try:
        if journal.exists():
            proof = json.loads(journal.read_text(encoding="utf-8"))
        else:
            raw = {}
            for name in FILES:
                source = OwnerSettingsSource(
                    path.with_name(name), owner_sid, session, filename=name
                )
                if name == FILES[1]:
                    with source._owner():
                        if not source.path.exists():
                            continue
                sources[name] = source
                raw[name] = source.read_bytes(32_000_000 if name != FILES[2] else 65536)
            scheme, separator, wrapped = raw[FILES[2]].reveal().strip().partition(b":")
            if not separator or not wrapped:
                raise VaultError(Code.UNREADABLE)
            if scheme == b"raw":
                key = Secret(wrapped)
            elif scheme == b"dpapi":
                import win32crypt

                with sources[FILES[2]]._owner():
                    key = Secret(
                        win32crypt.CryptUnprotectData(
                            base64.b64decode(wrapped, validate=True),
                            b"CraftBot/mini-browser/vault-key/v1",
                            None,
                            None,
                            1,
                        )[1]
                    )
            else:
                raise VaultError(Code.UNREADABLE)
            plaintext = Secret(Fernet(key.reveal()).decrypt(raw[FILES[0]].reveal()))
            mapping = migrate_browser_document(
                vault, source_id, Secret(json.loads(plaintext.reveal()))
            )
            recovery = vault.import_source(
                uuid5(vault.profile.scope.profile_id, source_id + "/recovery-key"),
                CredentialKind.SERVICE_SECRET,
                "Legacy browser recovery",
                source_id[:12],
                Secret({"legacy_key": key.reveal().decode("ascii")}),
                allowed_origins=(),
            )
            # Archive authenticated ciphertext only. The old source key never
            # appears in this directory or in the metadata deletion journal.
            hashes = {}
            for name, contents in raw.items():
                hashes[name] = hashlib.sha256(contents.reveal()).hexdigest()
                if name == FILES[2]:
                    continue
                target = archive / name
                with target.open("wb") as stream:
                    stream.write(contents.reveal())
                    stream.flush()
                    os.fsync(stream.fileno())
                private_acl(target)
                if hashlib.sha256(target.read_bytes()).hexdigest() != hashes[name]:
                    raise VaultError(Code.IO)
            proof = {
                "version": 1,
                "profile_id": str(vault.profile.scope.profile_id),
                "mapping": mapping,
                "files": hashes,
                "recovery_id": str(recovery.summary.reference.credential_id),
            }
            temporary = archive / "migration.new"
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write(json.dumps(proof))
                stream.flush()
                os.fsync(stream.fileno())
            private_acl(temporary)
            import win32file

            win32file.MoveFileEx(str(temporary), str(journal), 1 | 8)
        if (
            proof["version"] != 1
            or proof["profile_id"] != str(vault.profile.scope.profile_id)
            or set(proof["files"]) - set(FILES)
        ):
            raise VaultError(Code.UNREADABLE)
        current = {
            str(i.summary.reference.credential_id): i.summary.reference.version
            for i in vault.list_items()
        }
        for reference in proof["mapping"].values():
            ref = parse(reference)
            if (
                ref.profile_id != vault.profile.scope.profile_id
                or current.get(str(ref.credential_id)) != ref.version
            ):
                raise VaultError(Code.CONFLICT)
        if current.get(proof["recovery_id"]) != 1:
            raise VaultError(Code.CONFLICT)
        for name, expected in proof["files"].items():
            if (
                name != FILES[2]
                and hashlib.sha256((archive / name).read_bytes()).hexdigest()
                != expected
            ):
                raise VaultError(Code.UNREADABLE)
            source = sources.get(name)
            if source is None:
                source = OwnerSettingsSource(
                    path.with_name(name), owner_sid, session, filename=name
                )
                sources[name] = source
            with source._owner():
                if not source.path.exists():
                    continue  # Earlier verified retirement completed this file.
                contents = Secret(source.path.read_bytes())
                if not hmac.compare_digest(
                    hashlib.sha256(contents.reveal()).hexdigest(), expected
                ):
                    raise VaultError(Code.CONFLICT)
                source.path.unlink()
        return {
            "imported": len(proof["mapping"]),
            "mapping_retained_by_host": True,
            "restart_required": True,
        }
    finally:
        for source in sources.values():
            source.close()
