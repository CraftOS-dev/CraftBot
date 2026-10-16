"""In-memory, host-owned identity directory; persistence belongs to CM-02.

Not a consumer API. Its caller must already be a trusted host component.
This directory neither verifies OS identities nor grants credential access.
"""

from __future__ import annotations

from contextlib import contextmanager
from threading import RLock
from uuid import UUID

from .identity import (
    CallerBinding,
    CallerIdentity,
    ExecutionContext,
    VaultOwner,
    VaultProfile,
    VaultScope,
)


class IdentityError(ValueError):
    """Fixed, value-free identity errors, safe for a host adapter to map."""


class IdentityDirectory:
    def __init__(self) -> None:
        self._owners: dict[UUID, VaultOwner] = {}
        self._profiles: dict[UUID, VaultProfile] = {}
        self._bindings: dict[UUID, CallerBinding] = {}
        self._revoked: set[UUID] = set()
        self._lock = RLock()

    def register_owner(self, owner: VaultOwner) -> None:
        with self._lock:
            existing = self._owners.get(owner.owner_id)
            if existing is not None and existing != owner:
                raise IdentityError("owner_conflict")
            if any(
                other.os_identity == owner.os_identity and other != owner
                for other in self._owners.values()
            ):
                raise IdentityError("owner_conflict")
            self._owners[owner.owner_id] = owner

    def register_profile(self, profile: VaultProfile) -> None:
        with self._lock:
            if profile.scope.owner_id not in self._owners:
                raise IdentityError("owner_unknown")
            existing = self._profiles.get(profile.scope.profile_id)
            if existing is not None and existing != profile:
                raise IdentityError("profile_conflict")
            self._profiles[profile.scope.profile_id] = profile

    def bind(self, binding: CallerBinding) -> None:
        """Register an explicitly authorized channel/profile association.

        Does not create a grant. A different profile/revision/runtime requires
        a new binding; labels, parent sessions and app manifests confer none.
        """
        with self._lock:
            if binding.binding_id in self._revoked:
                raise IdentityError("binding_revoked")
            profile = self._profiles.get(binding.scope.profile_id)
            if profile is None or profile.scope != binding.scope:
                raise IdentityError("profile_unknown")
            existing = self._bindings.get(binding.binding_id)
            if existing is not None and existing != binding:
                raise IdentityError("binding_conflict")
            self._bindings[binding.binding_id] = binding

    def require_vault(self, owner: VaultOwner, scope: VaultScope) -> None:
        """Reject host bootstrap wiring to a different OS owner/catalog scope."""
        with self._lock:
            if self._owners.get(owner.owner_id) != owner:
                raise IdentityError("owner_unknown")
            profile = self._profiles.get(scope.profile_id)
            if (
                owner.owner_id != scope.owner_id
                or profile is None
                or profile.scope != scope
            ):
                raise IdentityError("scope_denied")

    def resolve(
        self, binding_id: UUID, authenticated_caller: CallerIdentity, execution_id: UUID
    ) -> ExecutionContext:
        """Resolve using transport-authenticated identity, not caller JSON.

        There is deliberately no fallback to main, a parent's binding, or a
        global active profile. A new app revision/runtime cannot reuse a binding.
        """
        with self._lock:
            binding = self._bindings.get(binding_id)
            if binding is None or binding.caller != authenticated_caller:
                raise IdentityError("caller_unbound")
            return ExecutionContext(binding, execution_id)

    def revoke(self, binding_id: UUID) -> None:
        """Invalidate a channel without altering profiles or token/session data."""
        with self._lock:
            self._bindings.pop(binding_id, None)
            self._revoked.add(binding_id)

    def require_current(self, context: ExecutionContext) -> None:
        """Recheck at use time: a previously resolved context may be revoked."""
        with self._lock:
            if self._bindings.get(context.binding.binding_id) != context.binding:
                raise IdentityError("caller_unbound")

    def require_scope(self, context: ExecutionContext, scope: VaultScope) -> None:
        """Reject cross-profile/owner references even for the same human owner."""
        with self._lock:
            self.require_current(context)
            if context.binding.scope != scope:
                raise IdentityError("scope_denied")

    @contextmanager
    def hold_current(self, context: ExecutionContext):
        """Serialize dispatch with revocation; already sent requests cannot be undone."""
        with self._lock:
            self.require_current(context)
            yield
