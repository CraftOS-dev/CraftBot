"""Shared, host-only source-credential vault. No consumer routes.

Keys live in an injected OS facility; snapshots contain authenticated ciphertext
only. Owner verification is mandatory, with no working default verifier. The
service must own one instance per profile; SQLite serializes other-process writes.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import hmac
import math
from pathlib import Path
from threading import RLock, Timer
import time
from uuid import UUID, uuid4

from .contracts import CredentialKind, CredentialReference, CredentialSummary
from .errors import VaultError, VaultErrorCode as Code, sanitized_errors
from .identity import VaultOwner, VaultProfile
from .keys import (
    KeyStore,
    OwnerVerifier,
    VerificationUnavailable,
    WindowsCredentialKeyStore,
)
from .records import (
    CredentialDetails,
    MAX_ITEMS,
    _Record,
    decode,
    encode,
    origins,
    validate_fields,
)
from .secrets import Secret
from .storage import SnapshotStore
from .use_errors import CredentialUseError


class VaultState(str, Enum):
    LOCKED = "locked"
    READY = "ready"
    UNREADABLE = "unreadable"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class VaultStatus:
    state: VaultState
    unlock_epoch: UUID | None


@dataclass(frozen=True)
class SourceImport:
    credential_id: UUID
    kind: CredentialKind
    service: str
    account_label: str
    fields: Secret
    allowed_origins: tuple[str, ...]


def _cipher(key: Secret):
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise VaultError(Code.BACKEND_UNAVAILABLE) from None
    try:
        return Secret(Fernet(key.reveal()))
    except (TypeError, ValueError):
        raise VaultError(Code.UNREADABLE) from None


def _new_key() -> Secret:
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise VaultError(Code.BACKEND_UNAVAILABLE) from None
    return Secret(Fernet.generate_key())


class ProfileVault:
    def __init__(
        self,
        root: Path,
        owner: VaultOwner,
        profile: VaultProfile,
        *,
        key_store: KeyStore | None = None,
        verifier: OwnerVerifier | None = None,
        idle_seconds: float = 900,
        clock=time.monotonic,
    ) -> None:
        if owner.owner_id != profile.scope.owner_id:
            raise VaultError(Code.SCOPE_DENIED)
        if not math.isfinite(idle_seconds) or idle_seconds <= 0:
            raise VaultError(Code.INVALID)
        self.owner = owner
        self.profile = profile
        self.store = SnapshotStore(root, profile.scope)
        self._keys = key_store if key_store is not None else WindowsCredentialKeyStore()
        self._verifier = verifier if verifier is not None else VerificationUnavailable()
        self._idle = idle_seconds
        self._clock = clock
        self._lock = RLock()
        self._crypto: Secret | None = None
        self._key_tag: Secret | None = None
        self._state = VaultState.LOCKED
        self._epoch: UUID | None = None
        self._deadline = 0.0
        self._timer: Timer | None = None
        self._on_lock = (
            None  # Protected host cancellation hook; never a consumer callback.
        )

    def _clear(self, state: VaultState = VaultState.LOCKED) -> None:
        was_ready = self._state is VaultState.READY
        if self._timer is not None:
            self._timer.cancel()
        self._timer = None
        self._crypto = self._key_tag = None
        self._epoch = None
        self._deadline = 0.0
        self._state = state
        if was_ready and self._on_lock is not None:
            self._on_lock()

    def lock(self) -> None:
        """Also used by host OS-lock/sleep/app-exit hooks; no session sign-out."""
        with self._lock:
            self._clear()

    close = lock

    def _expire(self) -> None:
        with self._lock:
            if self._state is VaultState.READY:
                if self._clock() >= self._deadline:
                    self._clear()
                else:
                    self._schedule_lock()

    def _schedule_lock(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = Timer(max(0.001, self._deadline - self._clock()), self._expire)
        self._timer.daemon = True
        self._timer.start()

    def _activate(self, key: Secret) -> None:
        self._crypto = _cipher(key)
        self._key_tag = Secret(hashlib.sha256(key.reveal()).digest())
        self._epoch = uuid4()
        self._state = VaultState.READY
        self._deadline = self._clock() + self._idle
        self._schedule_lock()

    def status(self) -> VaultStatus:
        with self._lock:
            if self._state is VaultState.READY and self._clock() >= self._deadline:
                self._clear()
            return VaultStatus(self._state, self._epoch)

    def owner_activity(self) -> None:
        """Trusted owner UI events only; secret use never refreshes this timer."""
        with self._lock:
            self._require_ready()
            self._deadline = self._clock() + self._idle
            self._schedule_lock()

    def _require_ready(self) -> None:
        if self._state is VaultState.READY and self._clock() >= self._deadline:
            self._clear()
        if self._state is not VaultState.READY:
            raise VaultError(Code.LOCKED)

    def _verify_owner(self) -> None:
        try:
            if self._verifier.verify(self.owner) is not None:
                raise VaultError(Code.VERIFICATION_REQUIRED)
        except VaultError:
            raise
        except Exception:
            raise VaultError(Code.VERIFICATION_REQUIRED) from None

    def _load_key(self) -> Secret | None:
        try:
            return self._keys.load(self.profile.scope)
        except VaultError:
            raise
        except Exception:
            raise VaultError(Code.BACKEND_UNAVAILABLE) from None

    def _create_key(self, key: Secret) -> None:
        try:
            self._keys.create(self.profile.scope, key)
        except VaultError:
            raise
        except Exception:
            raise VaultError(Code.BACKEND_UNAVAILABLE) from None

    @contextmanager
    def _opening(self):
        with self._lock:
            self._clear()
            try:
                self._verify_owner()
                yield
            except VaultError as exc:
                if exc.code is Code.UNREADABLE:
                    self._clear(VaultState.UNREADABLE)
                elif exc.code in (Code.IO, Code.BACKEND_UNAVAILABLE):
                    self._clear(VaultState.UNAVAILABLE)
                else:
                    self._clear()
                raise
            except Exception:
                self._clear(VaultState.UNAVAILABLE)
                raise VaultError(Code.IO) from None
            except BaseException:
                self._clear()
                raise

    @sanitized_errors
    def initialize(self) -> VaultStatus:
        """Explicit owner action; never called implicitly by a read/unlock."""
        with self._opening():
            # An existing OS key without a DB may be lost data: never reset it.
            if not self.store.path.exists() and self._load_key() is not None:
                raise VaultError(Code.UNREADABLE)
            with self.store.transaction(initialize=True, write=True) as connection:
                if (
                    connection.execute("SELECT 1 FROM vault LIMIT 1").fetchone()
                    is not None
                ):
                    raise VaultError(Code.ALREADY_EXISTS)
                key = self._load_key()
                if key is None:
                    key = _new_key()
                    self._create_key(key)
                crypto = _cipher(key)
                SnapshotStore.write(
                    connection,
                    crypto.reveal().encrypt(
                        encode(self.owner, self.profile, []).reveal()
                    ),
                )
            self._activate(key)
        return self.status()

    @sanitized_errors
    def unlock(self) -> VaultStatus:
        with self._opening():
            if not self.store.path.is_file():
                raise VaultError(Code.UNREADABLE)
            key = self._load_key()
            if key is None:
                raise VaultError(Code.UNREADABLE)
            self._crypto = _cipher(key)
            with self.store.transaction() as connection:
                self._read(connection)  # Verify decrypt/schema/scope before READY.
            self._activate(key)
        return self.status()

    def _read(self, connection):
        try:
            plaintext = Secret(
                self._crypto.reveal().decrypt(SnapshotStore.read(connection))
            )
        except VaultError:
            raise
        except Exception:
            raise VaultError(Code.UNREADABLE) from None
        profile, records = decode(plaintext, self.owner, self.profile.scope)
        self.profile = profile
        return records

    @contextmanager
    def _operation(self, *, write=False, helper=False):
        with self._lock:
            self._require_ready()
            try:
                key = self._load_key()
                if key is None or not hmac.compare_digest(
                    self._key_tag.reveal(), hashlib.sha256(key.reveal()).digest()
                ):
                    raise VaultError(Code.UNREADABLE)
                # Helpers retain the writer reservation to prevent another
                # process changing/deleting the version before dispatch.
                with self.store.transaction(write=write or helper) as connection:
                    records = self._read(connection)
                    yield connection, records
                    if write:
                        SnapshotStore.write(
                            connection,
                            self._crypto.reveal().encrypt(
                                encode(self.owner, self.profile, records).reveal()
                            ),
                        )
            except CredentialUseError:
                # Policy/network failures do not indicate storage corruption.
                raise
            except VaultError as exc:
                if exc.code is Code.UNREADABLE:
                    self._clear(VaultState.UNREADABLE)
                elif exc.code in (Code.IO, Code.BACKEND_UNAVAILABLE):
                    self._clear(VaultState.UNAVAILABLE)
                raise
            except Exception:
                self._clear(VaultState.UNAVAILABLE)
                raise VaultError(Code.IO) from None
            except BaseException:
                self._clear()
                raise

    @sanitized_errors
    def list_items(self) -> tuple[CredentialDetails, ...]:
        with self._operation() as (_, records):
            return tuple(
                sorted(
                    (record.details for record in records),
                    key=lambda item: (
                        item.summary.service,
                        item.summary.account_label,
                        str(item.summary.reference.credential_id),
                    ),
                )
            )

    @sanitized_errors
    def create(
        self,
        kind: CredentialKind,
        service: str,
        account_label: str,
        fields: Secret,
        *,
        allowed_origins: tuple[str, ...] = (),
    ) -> CredentialDetails:
        """Secure owner-entry adapter must wrap fields before calling this API."""
        if not isinstance(fields, Secret) or not isinstance(fields.reveal(), dict):
            raise VaultError(Code.INVALID)
        fields = Secret(dict(fields.reveal()))
        validate_fields(kind, fields)
        allowed = origins(allowed_origins)
        if kind is CredentialKind.LOGIN and not allowed:
            raise VaultError(Code.INVALID)
        try:
            summary = CredentialSummary(
                CredentialReference(self.profile.scope, uuid4(), 1),
                kind,
                service,
                account_label,
            )
        except ValueError:
            raise VaultError(Code.INVALID) from None
        now = datetime.now(timezone.utc).isoformat()
        details = CredentialDetails(summary, allowed, now, now)
        with self._operation(write=True) as (_, records):
            if len(records) >= MAX_ITEMS:
                raise VaultError(Code.INVALID)
            records.append(_Record(details, fields))
        return details

    def _find(self, reference: CredentialReference, records: list[_Record]) -> _Record:
        if reference.scope != self.profile.scope:
            raise VaultError(Code.SCOPE_DENIED)
        for record in records:
            existing = record.details.summary.reference
            if existing.credential_id == reference.credential_id:
                if existing.version != reference.version:
                    raise VaultError(Code.CONFLICT)
                return record
        raise VaultError(Code.NOT_FOUND)

    @sanitized_errors
    def import_source(
        self,
        credential_id: UUID,
        kind: CredentialKind,
        service: str,
        account_label: str,
        fields: Secret,
        *,
        allowed_origins: tuple[str, ...],
    ):
        """Host migration only. Stable IDs make interrupted imports retryable.

        An existing ID is accepted only for exactly the same source and policy;
        migration never overwrites an edited item or silently creates duplicates.
        """
        return self.import_sources(
            (
                SourceImport(
                    credential_id, kind, service, account_label, fields, allowed_origins
                ),
            )
        )[0]

    @sanitized_errors
    def import_sources(self, values: tuple[SourceImport, ...]):
        """One encrypted transaction and read-back for a bounded migration batch."""
        if type(values) is not tuple or len(values) > MAX_ITEMS:
            raise VaultError(Code.INVALID)
        now = datetime.now(timezone.utc).isoformat()
        incoming, results = {}, []
        for value in values:
            if (
                type(value) is not SourceImport
                or value.credential_id in incoming
                or not isinstance(value.fields, Secret)
                or type(value.fields.reveal()) is not dict
            ):
                raise VaultError(Code.INVALID)
            fields = Secret(dict(value.fields.reveal()))
            validate_fields(value.kind, fields)
            allowed = origins(value.allowed_origins)
            if value.kind is CredentialKind.LOGIN and not allowed:
                raise VaultError(Code.INVALID)
            summary = CredentialSummary(
                CredentialReference(self.profile.scope, value.credential_id, 1),
                value.kind,
                value.service,
                value.account_label,
            )
            incoming[value.credential_id] = _Record(
                CredentialDetails(summary, allowed, now, now), fields
            )
        with self._operation(write=True) as (_, records):
            existing = {r.details.summary.reference.credential_id: r for r in records}
            if len(set(existing) | set(incoming)) > MAX_ITEMS:
                raise VaultError(Code.INVALID)
            for key, record in incoming.items():
                old = existing.get(key)
                if old is not None:
                    if (
                        old.details.summary != record.details.summary
                        or old.details.allowed_origins != record.details.allowed_origins
                        or old.fields.reveal() != record.fields.reveal()
                    ):
                        raise VaultError(Code.CONFLICT)
                    results.append(old.details)
                else:
                    records.append(record)
                    results.append(record.details)
        # Verify every imported source from the committed encrypted document.
        with self._operation() as (_, records):
            verified = {r.details.summary.reference.credential_id: r for r in records}
            for key, record in incoming.items():
                if (
                    key not in verified
                    or verified[key].details.summary != record.details.summary
                    or verified[key].fields.reveal() != record.fields.reveal()
                ):
                    raise VaultError(Code.UNREADABLE)
        return tuple(results)

    @contextmanager
    def _helper_record(self, reference: CredentialReference, epoch: UUID):
        """Broker internals only, under authorization and isolation checks.

        Keep same-instance updates/lock serialized until dispatch completes.
        There is deliberately no public read/reveal API or caller callback.
        """
        with self._operation(helper=True) as (_, records):
            self._require_epoch(epoch)
            yield self._find(reference, records)

    def _require_epoch(self, epoch: UUID) -> None:
        self._require_ready()
        if self._epoch != epoch:
            raise VaultError(Code.LOCKED)

    @sanitized_errors
    def update(
        self,
        reference: CredentialReference,
        *,
        service: str | None = None,
        account_label: str | None = None,
        fields: Secret | None = None,
        allowed_origins: tuple[str, ...] | None = None,
    ) -> CredentialDetails:
        with self._operation(write=True) as (_, records):
            record = self._find(reference, records)
            merged = Secret(dict(record.fields.reveal()))
            if fields is not None:
                if not isinstance(fields, Secret) or not isinstance(
                    fields.reveal(), dict
                ):
                    raise VaultError(Code.INVALID)
                # Empty fields preserve existing values; no implicit secret removal.
                merged.reveal().update(
                    {
                        key: value
                        for key, value in fields.reveal().items()
                        if value != ""
                    }
                )
            validate_fields(record.details.summary.kind, merged)
            allowed = (
                record.details.allowed_origins
                if allowed_origins is None
                else origins(allowed_origins)
            )
            if record.details.summary.kind is CredentialKind.LOGIN and not allowed:
                raise VaultError(Code.INVALID)
            try:
                summary = replace(
                    record.details.summary,
                    reference=replace(reference, version=reference.version + 1),
                    service=record.details.summary.service
                    if service is None
                    else service,
                    account_label=(
                        record.details.summary.account_label
                        if account_label is None
                        else account_label
                    ),
                )
            except ValueError:
                raise VaultError(Code.INVALID) from None
            record.details = replace(
                record.details,
                summary=summary,
                allowed_origins=allowed,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            record.fields = merged
            return record.details

    @sanitized_errors
    def delete(self, reference: CredentialReference) -> None:
        with self._operation(write=True) as (_, records):
            records.remove(self._find(reference, records))
