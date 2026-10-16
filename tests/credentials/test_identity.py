"""Host identity invariants; synthetic metadata only, no vault or OS access."""

from dataclasses import FrozenInstanceError, asdict, replace
import unittest
from uuid import UUID, uuid4

from app.credentials.contracts import (
    CredentialKind,
    CredentialReference,
    CredentialSummary,
    IsolationUnavailable,
    UnavailableIsolationBoundary,
)
from app.credentials.directory import IdentityDirectory, IdentityError
from app.credentials.identity import (
    AppDeployment,
    CallerBinding,
    CallerIdentity,
    CallerKind,
    VaultOwner,
    VaultProfile,
    VaultScope,
)


class CredentialIdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = IdentityDirectory()
        self.owner = VaultOwner(uuid4(), "test-os:owner-a")
        self.other_owner = VaultOwner(uuid4(), "test-os:owner-b")
        for owner in (self.owner, self.other_owner):
            self.directory.register_owner(owner)
        self.personal = VaultProfile(
            VaultScope(self.owner.owner_id, uuid4()), "Personal"
        )
        self.work = VaultProfile(VaultScope(self.owner.owner_id, uuid4()), "Work")
        self.foreign = VaultProfile(
            VaultScope(self.other_owner.owner_id, uuid4()), "Work"
        )
        for profile in (self.personal, self.work, self.foreign):
            self.directory.register_profile(profile)
        self.caller = CallerIdentity(CallerKind.AGENT_SESSION, "main", uuid4())
        self.binding = CallerBinding(uuid4(), self.caller, self.work.scope)
        self.directory.bind(self.binding)

    def context(self, binding=None, caller=None):
        binding = binding or self.binding
        return self.directory.resolve(
            binding.binding_id, caller or binding.caller, uuid4()
        )

    def test_profiles_are_namespaces_not_labels(self):
        duplicate_label = VaultProfile(VaultScope(self.owner.owner_id, uuid4()), "Work")
        self.directory.register_profile(duplicate_label)
        for forbidden in (self.personal, self.foreign, duplicate_label):
            with self.subTest(profile=forbidden.scope):
                with self.assertRaisesRegex(IdentityError, "^scope_denied$"):
                    self.directory.require_scope(self.context(), forbidden.scope)
        self.directory.require_scope(self.context(), self.work.scope)

    def test_unknown_owner_and_cross_owner_profile_claims_are_rejected(self):
        with self.assertRaisesRegex(IdentityError, "^owner_unknown$"):
            self.directory.register_profile(
                VaultProfile(VaultScope(uuid4(), uuid4()), "Unknown")
            )
        forged = replace(
            self.binding,
            binding_id=uuid4(),
            scope=VaultScope(self.other_owner.owner_id, self.work.scope.profile_id),
        )
        with self.assertRaisesRegex(IdentityError, "^profile_unknown$"):
            self.directory.bind(forged)

    def test_identity_ids_cannot_be_reassigned(self):
        for mutation in (
            lambda: self.directory.register_owner(
                replace(self.owner, os_identity="other")
            ),
            lambda: self.directory.register_owner(
                replace(self.owner, owner_id=uuid4())
            ),
            lambda: self.directory.register_profile(
                replace(self.work, label="Replaced")
            ),
            lambda: self.directory.bind(
                replace(self.binding, scope=self.personal.scope)
            ),
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(IdentityError):
                    mutation()
        self.directory.register_owner(self.owner)  # Identical bootstrap is idempotent.
        self.directory.register_profile(self.work)
        self.directory.bind(self.binding)
        self.directory.require_scope(self.context(), self.work.scope)

    def test_profile_switch_uses_an_explicit_new_binding(self):
        old_context = self.context()
        new_binding = replace(
            self.binding, binding_id=uuid4(), scope=self.personal.scope
        )
        self.directory.bind(new_binding)
        self.directory.require_scope(old_context, self.work.scope)
        self.directory.require_scope(self.context(new_binding), self.personal.scope)
        with self.assertRaises(FrozenInstanceError):
            old_context.binding.scope = self.personal.scope

    def test_subagents_and_restarted_sessions_do_not_inherit_bindings(self):
        for caller in (
            replace(self.caller, kind=CallerKind.SUBAGENT),
            replace(self.caller, subject_id="child"),
            replace(self.caller, instance_id=uuid4()),
        ):
            with self.subTest(caller=caller):
                with self.assertRaisesRegex(IdentityError, "^caller_unbound$"):
                    self.context(caller=caller)
        with self.assertRaisesRegex(IdentityError, "^caller_unbound$"):
            self.directory.resolve(uuid4(), self.caller, uuid4())

    def test_app_revision_deployment_and_runtime_are_bound(self):
        app = CallerIdentity(
            CallerKind.AGENT_APP,
            "installed-app",
            uuid4(),
            "revision-a",
            AppDeployment.LIVE,
        )
        binding = CallerBinding(uuid4(), app, self.work.scope)
        self.directory.bind(binding)
        self.directory.require_current(self.context(binding))
        for impostor in (
            replace(app, subject_id="other-app"),
            replace(app, app_revision="revision-b"),
            replace(app, deployment=AppDeployment.DEVELOPMENT),
            replace(app, instance_id=uuid4()),
        ):
            with self.subTest(impostor=impostor):
                with self.assertRaisesRegex(IdentityError, "^caller_unbound$"):
                    self.context(binding, impostor)

    def test_revocation_invalidates_inflight_context_and_cannot_be_undone(self):
        context = self.context()
        self.directory.revoke(self.binding.binding_id)
        with self.assertRaisesRegex(IdentityError, "^caller_unbound$"):
            self.directory.require_current(context)
        with self.assertRaisesRegex(IdentityError, "^caller_unbound$"):
            self.context()
        with self.assertRaisesRegex(IdentityError, "^binding_revoked$"):
            self.directory.bind(self.binding)

    def test_invalid_identifiers_and_app_identity_are_not_coerced(self):
        invalid = (
            lambda: VaultOwner(UUID(int=0), "test-os:owner"),
            lambda: VaultScope("main", uuid4()),
            lambda: CallerIdentity("agent_session", "main", uuid4()),
            lambda: CallerIdentity(CallerKind.AGENT_APP, "app", uuid4()),
            lambda: CallerIdentity(
                CallerKind.AGENT_SESSION, "main", uuid4(), "revision"
            ),
            lambda: VaultProfile(self.work.scope, "\n"),
            lambda: CredentialReference(self.work.scope, uuid4(), True),
            lambda: CredentialReference(self.work.scope, uuid4(), 0),
        )
        for factory in invalid:
            with self.subTest(factory=factory):
                with self.assertRaises(ValueError):
                    factory()

    def test_consumer_summary_has_no_secret_fields(self):
        summary = CredentialSummary(
            CredentialReference(self.work.scope, uuid4(), 1),
            CredentialKind.API_KEY,
            "synthetic-provider",
            "Work account",
        )
        self.assertEqual(
            set(asdict(summary)), {"reference", "kind", "service", "account_label"}
        )
        self.assertNotIn(self.owner.os_identity, repr(self.owner))

    def test_no_caller_kind_bypasses_unavailable_isolation(self):
        boundary = UnavailableIsolationBoundary()
        callers = (
            self.caller,
            replace(self.caller, kind=CallerKind.SUBAGENT),
            CallerIdentity(
                CallerKind.AGENT_APP, "app", uuid4(), "revision", AppDeployment.LIVE
            ),
        )
        for caller in callers:
            binding = CallerBinding(uuid4(), caller, self.work.scope)
            self.directory.bind(binding)
            with self.subTest(caller=caller.kind):
                with self.assertRaisesRegex(
                    IsolationUnavailable, "^credential_isolation_unavailable$"
                ):
                    boundary.require_isolated(self.context(binding))


if __name__ == "__main__":
    unittest.main()
