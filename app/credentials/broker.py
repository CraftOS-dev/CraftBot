"""Host-owned authorization and trusted execution, with no secret-returning API.

Never expose this Python object to consumer code or deserialize its context from
JSON. A future protected IPC adapter must resolve caller identity out of band.
The default isolation/owner-verification adapters deny all credential use.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
import hashlib
import json
import math
import re
import secrets
from threading import RLock
import time
from uuid import UUID, uuid4

from .contracts import (
    CredentialReference,
    CredentialSummary,
    HelperOperation,
    UnavailableIsolationBoundary,
)
from .directory import IdentityDirectory
from .helpers import (
    HelperRegistry,
    HelperResult,
    HttpsCredentialCheck,
    HttpsJsonOperation,
    JsonResult,
    _execute_check,
    _execute_json,
    require_match,
)
from .identity import CallerBinding, ExecutionContext, VaultScope
from .keys import VerificationUnavailable
from .use_errors import CredentialUseError, UseCode, use_boundary
from .vault import ProfileVault, VaultState
from .browser_helper import HttpsFormLogin, _execute_form


class GrantMode(str, Enum):
    ONCE = "once"
    BINDING = "binding"  # Until expiry/lock/revocation; never crosses a restart.


@dataclass(frozen=True)
class Grant:
    grant_id: UUID
    binding: CallerBinding
    reference: CredentialReference
    helper: HttpsCredentialCheck
    unlock_epoch: UUID
    expires_at: float  # Host monotonic time; not a serialized wall-clock claim.
    mode: GrantMode
    request_digest: bytes | None

    @property
    def operation(self) -> HelperOperation:
        return self.helper.operation


@dataclass(frozen=True)
class UseCapability:
    handle: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.handle, str) or not re.fullmatch(
            r"[A-Za-z0-9_\-]{43}", self.handle
        ):
            raise ValueError("invalid_capability")


@dataclass(frozen=True)
class _PendingUse:
    grant_id: UUID
    context: ExecutionContext
    expires_at: float


@dataclass(frozen=True)
class AuditEvent:
    action: str
    outcome: str
    binding_id: UUID | None
    execution_id: UUID | None
    scope: VaultScope | None
    grant_id: UUID | None


@dataclass(frozen=True)
class UseOffer:
    grant_id: UUID
    summary: CredentialSummary
    operation: HelperOperation


def canonical_request(payload):
    """Freeze caller data before approval/dispatch; never log the representation."""
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        if len(encoded) > 32_000_020:
            raise ValueError()
        return json.loads(encoded), hashlib.sha256(encoded).digest()
    except (TypeError, ValueError, RecursionError):
        raise CredentialUseError(UseCode.DENIED) from None


def _audited(action):
    def decorate(operation):
        @wraps(operation)
        def audited(self, context, *args, **kwargs):
            try:
                result = operation(self, context, *args, **kwargs)
            except Exception:
                self._event(action, context, "denied")
                raise
            except BaseException:
                self._event(action, context, "interrupted")
                raise
            outcome = result.value if type(result) is HelperResult else "allowed"
            self._event(
                action, context, outcome, result if type(result) is Grant else None
            )
            return result

        return audited

    return decorate


class CredentialBroker:
    def __init__(
        self,
        directory: IdentityDirectory,
        vaults: tuple[ProfileVault, ...],
        registry: HelperRegistry,
        *,
        isolation=None,
        owner_verifier=None,
        clock=time.monotonic,
    ):
        self._directory = directory
        for vault in vaults:
            directory.require_vault(vault.owner, vault.profile.scope)
        self._vaults = {vault.profile.scope: vault for vault in vaults}
        if len(self._vaults) != len(vaults):
            raise ValueError("duplicate_profile_vault")
        self._registry = registry
        self._isolation = (
            isolation if isolation is not None else UnavailableIsolationBoundary()
        )
        self._verifier = (
            owner_verifier if owner_verifier is not None else VerificationUnavailable()
        )
        self._clock = clock
        self._grants: dict[UUID, Grant] = {}
        self._pending: dict[bytes, _PendingUse] = {}
        self._audit: deque[AuditEvent] = deque(maxlen=512)
        self._lock = RLock()

    def _event(self, action, context, outcome, grant=None):
        # No secret values, capability handles, response text, caller input labels
        # or paths. Bounded in-memory host audit; never a consumer subscription.
        valid = type(context) is ExecutionContext
        with self._lock:
            self._audit.append(
                AuditEvent(
                    action,
                    outcome,
                    context.binding.binding_id
                    if valid
                    else (grant.binding.binding_id if grant else None),
                    context.execution_id if valid else None,
                    context.binding.scope
                    if valid
                    else (grant.reference.scope if grant else None),
                    grant.grant_id if grant else None,
                )
            )

    def audit_events(self) -> tuple[AuditEvent, ...]:
        """Host owner diagnostics only; persistence/export needs an owner adapter."""
        with self._lock:
            return tuple(self._audit)

    def add_profile(self, vault: ProfileVault) -> None:
        """Protected owner catalog operation; never a consumer route."""
        with self._lock:
            self._directory.require_vault(vault.owner, vault.profile.scope)
            if vault.profile.scope in self._vaults:
                raise CredentialUseError(UseCode.DENIED)
            self._vaults[vault.profile.scope] = vault

    def revoke_scoped(self, grant_id: UUID, scope: VaultScope) -> None:
        with self._lock:
            grant = self._grants.get(grant_id)
            if grant is not None and grant.reference.scope != scope:
                raise CredentialUseError(UseCode.DENIED)
            self.revoke(grant_id)

    def _prune(self):
        now = self._clock()
        self._grants = {
            key: grant for key, grant in self._grants.items() if grant.expires_at > now
        }
        self._pending = {
            key: pending
            for key, pending in self._pending.items()
            if pending.expires_at > now and pending.grant_id in self._grants
        }

    def _vault(self, context, reference):
        if (
            type(context) is not ExecutionContext
            or type(reference) is not CredentialReference
        ):
            raise CredentialUseError(UseCode.DENIED)
        self._directory.require_scope(context, reference.scope)
        vault = self._vaults.get(reference.scope)
        if vault is None:
            raise CredentialUseError(UseCode.DENIED)
        return vault

    def _isolated(self, context):
        # Returning a boolean/attestation is not an implementation of this check.
        try:
            verified = self._isolation.require_isolated(context) is None
        except Exception:
            verified = False
        if not verified:
            raise CredentialUseError(UseCode.ISOLATION)

    def _guard(self, grant, context, vault):
        if grant.binding != context.binding:
            raise CredentialUseError(UseCode.DENIED)
        if self._grants.get(grant.grant_id) != grant:
            raise CredentialUseError(UseCode.DENIED)
        if self._clock() >= grant.expires_at:
            raise CredentialUseError(UseCode.EXPIRED)
        if self._registry.require(grant.operation) != grant.helper:
            raise CredentialUseError(UseCode.DENIED)
        self._directory.require_scope(context, grant.reference.scope)
        vault._require_epoch(grant.unlock_epoch)
        self._isolated(context)

    @use_boundary
    @_audited("approve")
    def approve(
        self,
        context: ExecutionContext,
        reference: CredentialReference,
        operation: HelperOperation,
        *,
        mode: GrantMode = GrantMode.ONCE,
        lifetime: float = 900,
        payload=None,
    ) -> Grant:
        """Owner channel only: fresh verification for this exact displayed request.

        Verification alone is not consent. The protected owner UI must display
        caller/revision/deployment, profile/account, operation AND exact endpoint,
        then invoke this method only following the owner's explicit approval.
        Never publish it on the agent/app request transport.
        """
        _, request_digest = canonical_request(payload)
        with self._lock:
            if (
                type(mode) is not GrantMode
                or type(lifetime) not in (float, int)
                or not math.isfinite(lifetime)
                or not 0 < lifetime <= 3600
            ):
                raise CredentialUseError(UseCode.DENIED)
            vault = self._vault(context, reference)
            specification = self._registry.require(operation)
            self._isolated(context)
            try:
                verified = self._verifier.verify(vault.owner) is None
            except Exception:
                verified = False
            if not verified:
                raise CredentialUseError(UseCode.VERIFICATION)
            # Do not pin a slow owner prompt to an obsolete unlock epoch.
            with self._directory.hold_current(context), vault._lock:
                epoch = vault.status().unlock_epoch
                vault._require_epoch(epoch)
                with vault._helper_record(reference, epoch) as record:
                    require_match(specification, record.details)
                self._isolated(context)
                self._prune()
                if len(self._grants) >= 4096:
                    raise CredentialUseError(UseCode.LIMIT)
                grant = Grant(
                    uuid4(),
                    context.binding,
                    reference,
                    specification,
                    epoch,
                    self._clock() + lifetime,
                    mode,
                    request_digest if mode is GrantMode.ONCE else None,
                )
                self._grants[grant.grant_id] = grant
                return grant

    @use_boundary
    @_audited("authorize")
    def authorize(self, context: ExecutionContext, grant_id: UUID) -> UseCapability:
        """Consumer use interface, with context supplied by authenticated host IPC."""
        with self._lock:
            grant = self._grants.get(grant_id)
            if grant is None:
                raise CredentialUseError(UseCode.DENIED)
            vault = self._vault(context, grant.reference)
            with self._directory.hold_current(context), vault._lock:
                self._guard(grant, context, vault)
                with vault._helper_record(
                    grant.reference, grant.unlock_epoch
                ) as record:
                    require_match(
                        self._registry.require(grant.operation), record.details
                    )
                self._guard(grant, context, vault)
                self._prune()
                if len(self._pending) >= 8192:
                    raise CredentialUseError(UseCode.LIMIT)
                capability = UseCapability(secrets.token_urlsafe(32))
                self._pending[self._digest(capability)] = _PendingUse(
                    grant_id, context, min(self._clock() + 30, grant.expires_at)
                )
                return capability

    @use_boundary
    def status(self, context: ExecutionContext) -> VaultState:
        """Bound profile state only; no key material or owner-unlock operation."""
        if type(context) is not ExecutionContext:
            raise CredentialUseError(UseCode.DENIED)
        with self._directory.hold_current(context):
            vault = self._vaults.get(context.binding.scope)
            if vault is None:
                raise CredentialUseError(UseCode.DENIED)
            return vault.status().state

    @use_boundary
    def find(self, context: ExecutionContext) -> tuple[UseOffer, ...]:
        """Discover only current approvals for this binding, never all accounts."""
        if type(context) is not ExecutionContext:
            raise CredentialUseError(UseCode.DENIED)
        with self._lock, self._directory.hold_current(context):
            self._prune()
            offers = []
            for grant in tuple(self._grants.values()):
                if grant.binding != context.binding:
                    continue
                vault = self._vault(context, grant.reference)
                with vault._lock:
                    self._guard(grant, context, vault)
                    with vault._helper_record(
                        grant.reference, grant.unlock_epoch
                    ) as record:
                        require_match(
                            self._registry.require(grant.operation), record.details
                        )
                        offers.append(
                            UseOffer(
                                grant.grant_id, record.details.summary, grant.operation
                            )
                        )
            return tuple(offers)

    @staticmethod
    def _digest(capability):
        if type(capability) is not UseCapability:
            raise CredentialUseError(UseCode.CAPABILITY)
        return hashlib.sha256(capability.handle.encode("ascii")).digest()

    @use_boundary
    @_audited("execute")
    def execute(
        self,
        context: ExecutionContext,
        capability: UseCapability,
        payload=None,
        *,
        execution=None,
    ) -> HelperResult | JsonResult:
        from contextlib import ExitStack

        grant = None
        payload, request_digest = canonical_request(payload)
        try:
            with ExitStack() as held:
                held.enter_context(self._lock)
                digest = self._digest(capability)
                pending = self._pending.get(digest)
                if pending is None or pending.context != context:
                    raise CredentialUseError(UseCode.CAPABILITY)
                del self._pending[digest]
                if self._clock() >= pending.expires_at:
                    raise CredentialUseError(UseCode.CAPABILITY)
                grant = self._grants.get(pending.grant_id)
                if grant is None:
                    raise CredentialUseError(UseCode.DENIED)
                if (
                    grant.mode is GrantMode.ONCE
                    and grant.request_digest != request_digest
                ):
                    raise CredentialUseError(UseCode.DENIED)
                vault = self._vault(context, grant.reference)
                held.enter_context(self._directory.hold_current(context))
                held.enter_context(vault._lock)
                self._guard(grant, context, vault)
                record = held.enter_context(
                    vault._helper_record(grant.reference, grant.unlock_epoch)
                )
                specification = self._registry.require(grant.operation)
                require_match(specification, record.details)

                def before_send():
                    if execution is not None and execution.cancelled.is_set():
                        raise CredentialUseError(UseCode.INTERRUPTED)
                    if self._clock() >= pending.expires_at:
                        raise CredentialUseError(UseCode.CAPABILITY)
                    self._guard(grant, context, vault)

                def dispatched():
                    # Spend one-use authority before releasing the dispatch
                    # reservation. Other pending capabilities cannot replay it.
                    if grant.mode is GrantMode.ONCE:
                        self._retire(grant.grant_id)
                    held.close()
                    if execution is not None:
                        execution.dispatched.set()

                if type(specification) is HttpsFormLogin:
                    result = _execute_form(
                        specification, record.fields, before_send, payload
                    )
                elif type(specification) is HttpsJsonOperation:
                    result = _execute_json(
                        specification,
                        record.fields,
                        before_send,
                        payload,
                        execution=execution,
                        after_send=dispatched,
                    )
                else:
                    if payload not in (None, {"body": None}):
                        raise CredentialUseError(UseCode.DENIED)
                    result = _execute_check(specification, record.fields, before_send)
                if type(result) not in (HelperResult, JsonResult):
                    raise CredentialUseError(UseCode.HELPER)
                return result
        finally:
            if grant is not None and grant.mode is GrantMode.ONCE:
                with self._lock:
                    self._retire(grant.grant_id)

    def _retire(self, grant_id):
        self._grants.pop(grant_id, None)
        self._pending = {
            key: value
            for key, value in self._pending.items()
            if value.grant_id != grant_id
        }

    def capability_grant(self, context, capability):
        """Host-internal cancellation bookkeeping; possession grants no authority."""
        with self._lock:
            pending = self._pending.get(self._digest(capability))
            if pending is None or pending.context != context:
                raise CredentialUseError(UseCode.CAPABILITY)
            return pending.grant_id

    def revoke(self, grant_id: UUID) -> None:
        """Trusted host/owner revocation. Already dispatched requests finish first."""
        with self._lock:
            grant = self._grants.pop(grant_id, None)
            self._pending = {
                key: value
                for key, value in self._pending.items()
                if value.grant_id != grant_id
            }
            if grant is not None:
                self._event("revoke", None, "revoked", grant)

    @use_boundary
    @_audited("cancel")
    def cancel(self, context: ExecutionContext, capability: UseCapability) -> None:
        """Cancel queued use. A dispatched HTTPS request cannot be retracted."""
        with self._lock:
            self._directory.require_current(context)
            digest = self._digest(capability)
            pending = self._pending.get(digest)
            if pending is None or pending.context != context:
                raise CredentialUseError(UseCode.CAPABILITY)
            del self._pending[digest]
