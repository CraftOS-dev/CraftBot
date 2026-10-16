"""Authorization against synthetic vaults and mocked TLS/HTTP, no user secrets."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from dataclasses import asdict, replace, FrozenInstanceError
import io
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

from app.credentials.broker import CredentialBroker, GrantMode, UseCapability
from app.credentials.contracts import CredentialKind, HelperOperation
from app.credentials.directory import IdentityDirectory, IdentityError
from app.credentials.errors import VaultError
from app.credentials.helpers import (
    HelperRegistry,
    HelperResult,
    HttpsCredentialCheck,
    _execute_check,
)
from app.credentials.identity import (
    AppDeployment,
    CallerBinding,
    CallerIdentity,
    CallerKind,
    ExecutionContext,
    VaultOwner,
    VaultProfile,
    VaultScope,
)
from app.credentials.secrets import Secret
from app.credentials.use_errors import CredentialUseError, UseCode
from app.credentials.vault import ProfileVault, VaultState


class TestKeys:
    __test__ = False

    def __init__(self):
        self.keys = {}

    def load(self, scope):
        return self.keys.get(scope)

    def create(self, scope, key):
        self.keys[scope] = key


class SyntheticIsolation:
    """Tests only. This is deliberately NOT a shipped OS isolation adapter."""

    def __init__(self):
        self.available = True
        self.checked = []

    def require_isolated(self, context):
        self.checked.append(context)
        if not self.available:
            raise RuntimeError("synthetic isolation lost")


@contextmanager
def wire(status=200):
    """Exercise real helper flow, replacing only DNS, sockets, TLS and HTTP I/O."""
    with ExitStack() as stack:
        resolver = stack.enter_context(
            patch("app.credentials.helpers.socket.getaddrinfo")
        )
        resolver.return_value = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", 443),
            )
        ]
        transport = MagicMock()
        transport.__enter__.return_value = transport
        factory = stack.enter_context(
            patch("app.credentials.helpers.socket.socket", return_value=transport)
        )
        tls = MagicMock()
        stack.enter_context(
            patch(
                "app.credentials.helpers.ssl.create_default_context", return_value=tls
            )
        )
        connection = MagicMock()
        stack.enter_context(
            patch(
                "app.credentials.helpers.http.client.HTTPSConnection",
                return_value=connection,
            )
        )
        response = MagicMock()
        response.status = status
        response.__enter__.return_value = response
        connection.getresponse.return_value = response
        yield connection, response, resolver, factory, transport, tls


class CredentialBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 1000.0
        self.owner = VaultOwner(uuid4(), "test-os:cm03-owner")
        self.profile = VaultProfile(VaultScope(self.owner.owner_id, uuid4()), "Work")
        self.keys = TestKeys()
        self.verifier = Mock()
        self.verifier.verify.return_value = None
        self.vault = ProfileVault(
            Path(self.temp.name) / "vaults",
            self.owner,
            self.profile,
            key_store=self.keys,
            verifier=self.verifier,
            clock=lambda: self.now,
        )
        self.vault.initialize()
        self.reference = self.vault.create(
            CredentialKind.API_KEY,
            "Example",
            "Synthetic account",
            Secret({"api_key": "seeded-API_key/CM03=="}),
            allowed_origins=("https://example.test",),
        ).summary.reference
        self.directory = IdentityDirectory()
        self.directory.register_owner(self.owner)
        self.directory.register_profile(self.profile)
        self.context = self.new_context()
        self.isolation = SyntheticIsolation()
        self.specification = HttpsCredentialCheck(
            HelperOperation("example", "check"),
            CredentialKind.API_KEY,
            "https://example.test/v1/account",
        )
        self.registry = HelperRegistry((self.specification,))
        self.broker = self.make_broker()
        self.verifier.reset_mock()

    def tearDown(self):
        self.vault.close()
        self.temp.cleanup()

    def new_context(self, *, profile=None, caller=None):
        caller = caller or CallerIdentity(CallerKind.AGENT_SESSION, "main", uuid4())
        binding = CallerBinding(uuid4(), caller, (profile or self.profile).scope)
        self.directory.bind(binding)
        return self.directory.resolve(binding.binding_id, caller, uuid4())

    def make_broker(self, **overrides):
        options = dict(
            isolation=self.isolation,
            owner_verifier=self.verifier,
            clock=lambda: self.now,
        )
        options.update(overrides)
        return CredentialBroker(self.directory, (self.vault,), self.registry, **options)

    def approve(self, **options):
        return self.broker.approve(
            self.context, self.reference, self.specification.operation, **options
        )

    def capability(self, **options):
        grant = self.approve(**options)
        return grant, self.broker.authorize(self.context, grant.grant_id)

    def assert_code(self, code, function):
        with self.assertRaises(CredentialUseError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code.value)
        self.assertIsNone(caught.exception.__context__)

    def test_no_implicit_grants_and_owner_management_is_separate(self):
        self.assertEqual(self.broker.find(self.context), ())
        self.assertEqual(self.broker.status(self.context), VaultState.READY)
        self.assert_code(
            UseCode.DENIED, lambda: self.broker.authorize(self.context, uuid4())
        )
        self.assert_code(
            UseCode.CAPABILITY,
            lambda: self.broker.execute(self.context, UseCapability("x" * 43)),
        )
        for name in ("reveal", "get_secret", "get_key", "unlock", "open_entry"):
            self.assertFalse(hasattr(self.broker, name))

    def test_bootstrap_rejects_wrong_os_owner_with_same_owner_uuid(self):
        mismatched = IdentityDirectory()
        mismatched.register_owner(
            replace(self.owner, os_identity="test-os:other-owner")
        )
        mismatched.register_profile(self.profile)
        with self.assertRaises(IdentityError):
            CredentialBroker(mismatched, (self.vault,), self.registry)

    def test_tls_verification_failure_never_sends_credentials(self):
        import ssl

        _, capability = self.capability()
        with wire() as (connection, _, _, _, _, tls):
            tls.wrap_socket.side_effect = ssl.SSLCertVerificationError(
                "synthetic TLS failure"
            )
            self.assert_code(
                UseCode.HELPER, lambda: self.broker.execute(self.context, capability)
            )
            connection.request.assert_not_called()
            connection.close.assert_called_once()

    def test_approved_check_never_returns_response_or_client_or_raw_value(self):
        grant, capability = self.capability()
        self.verifier.verify.assert_called_once_with(self.owner)
        self.assertNotIn(capability.handle, repr(capability))
        with wire() as (connection, response, resolver, factory, transport, tls):
            result = self.broker.execute(self.context, capability)
            self.assertIs(result, HelperResult.ACCEPTED)
            connection.request.assert_called_once_with(
                "GET",
                "/v1/account",
                headers={
                    "Authorization": "Bearer seeded-API_key/CM03==",
                    "Connection": "close",
                    "Accept": "application/json",
                },
            )
            resolver.assert_called_once_with(
                "example.test", 443, type=socket.SOCK_STREAM
            )
            transport.connect.assert_called_once_with(("93.184.216.34", 443))
            tls.wrap_socket.assert_called_once_with(
                transport, server_hostname="example.test"
            )
            response.read.assert_not_called()
            connection.close.assert_called_once()
            self.assertEqual(connection.auto_open, 0)
            connection.set_debuglevel.assert_called_once_with(0)
        self.assertEqual(self.broker.find(self.context), ())
        self.assert_code(
            UseCode.DENIED, lambda: self.broker.authorize(self.context, grant.grant_id)
        )
        self.assert_code(
            UseCode.CAPABILITY, lambda: self.broker.execute(self.context, capability)
        )
        self.assertNotIn("seeded-API", repr(self.broker.audit_events()))

    def test_binding_grant_still_requires_distinct_one_time_capabilities(self):
        grant, capability = self.capability(mode=GrantMode.BINDING)
        offers = self.broker.find(self.context)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].summary.reference, self.reference)
        self.assertNotIn("seeded-API", repr(asdict(offers[0])))
        with wire() as (connection, *_):
            self.broker.execute(self.context, capability)
            next_context = ExecutionContext(self.context.binding, uuid4())
            next_capability = self.broker.authorize(next_context, grant.grant_id)
            self.assert_code(
                UseCode.CAPABILITY,
                lambda: self.broker.execute(self.context, next_capability),
            )
            self.broker.execute(next_context, next_capability)
            self.assertEqual(connection.request.call_count, 2)

    def test_wrong_sessions_subagents_apps_revisions_and_deployments(self):
        grant, capability = self.capability(mode=GrantMode.BINDING)
        app = CallerIdentity(
            CallerKind.AGENT_APP, "project-a", uuid4(), "sha256:one", AppDeployment.LIVE
        )
        callers = [
            CallerIdentity(CallerKind.AGENT_SESSION, "main", uuid4()),
            CallerIdentity(CallerKind.SUBAGENT, "main", uuid4()),
            app,
            replace(app, subject_id="project-b"),
            replace(app, app_revision="sha256:two"),
            replace(app, deployment=AppDeployment.DEVELOPMENT),
        ]
        with wire() as (connection, *_):
            for caller in callers:
                other = self.new_context(caller=caller)
                self.assertEqual(self.broker.find(other), ())
                self.assert_code(
                    UseCode.DENIED, lambda: self.broker.authorize(other, grant.grant_id)
                )
                self.assert_code(
                    UseCode.CAPABILITY, lambda: self.broker.execute(other, capability)
                )
            connection.request.assert_not_called()
            self.broker.execute(
                self.context, capability
            )  # Wrong callers did not steal/burn it.

    def test_agent_app_can_use_its_own_approval_but_no_other_revision_can(self):
        caller = CallerIdentity(
            CallerKind.AGENT_APP, "project-a", uuid4(), "sha256:one", AppDeployment.LIVE
        )
        context = self.new_context(caller=caller)
        grant = self.broker.approve(
            context, self.reference, self.specification.operation
        )
        capability = self.broker.authorize(context, grant.grant_id)
        with wire():
            self.assertEqual(
                self.broker.execute(context, capability), HelperResult.ACCEPTED
            )

    def test_other_profile_owner_and_forged_binding_are_denied(self):
        other = VaultProfile(VaultScope(self.owner.owner_id, uuid4()), "Work")
        self.directory.register_profile(other)
        other_context = self.new_context(profile=other)
        self.assert_code(
            UseCode.DENIED,
            lambda: self.broker.approve(
                other_context, self.reference, self.specification.operation
            ),
        )
        forged_reference = replace(self.reference, scope=VaultScope(uuid4(), uuid4()))
        self.assert_code(
            UseCode.DENIED,
            lambda: self.broker.approve(
                self.context, forged_reference, self.specification.operation
            ),
        )
        forged_context = replace(
            self.context, binding=replace(self.context.binding, binding_id=uuid4())
        )
        self.assert_code(
            UseCode.DENIED,
            lambda: self.broker.approve(
                forged_context, self.reference, self.specification.operation
            ),
        )
        self.verifier.verify.assert_not_called()

    def test_unregistered_operations_wrong_kind_and_destinations_are_denied(self):
        for operation in (
            HelperOperation("example", "read_secret"),
            HelperOperation("python:eval", "check"),
        ):
            self.assert_code(
                UseCode.DENIED,
                lambda: self.broker.approve(self.context, self.reference, operation),
            )
        for specification in (
            replace(self.specification, endpoint="https://other.test/v1/account"),
            replace(self.specification, kind=CredentialKind.LOGIN),
        ):
            self.registry = HelperRegistry((specification,))
            broker = self.make_broker()
            self.assert_code(
                UseCode.DENIED,
                lambda: broker.approve(
                    self.context, self.reference, specification.operation
                ),
            )

    def test_default_or_lost_isolation_never_dispatches(self):
        default = self.make_broker(isolation=None)
        self.assert_code(
            UseCode.ISOLATION,
            lambda: default.approve(
                self.context, self.reference, self.specification.operation
            ),
        )
        grant, capability = self.capability(mode=GrantMode.BINDING)
        self.isolation.available = False
        with wire() as (connection, *_):
            self.assert_code(
                UseCode.ISOLATION, lambda: self.broker.execute(self.context, capability)
            )
            self.assert_code(
                UseCode.ISOLATION,
                lambda: self.broker.authorize(self.context, grant.grant_id),
            )
            connection.request.assert_not_called()

    def test_boolean_isolation_and_owner_verification_are_not_success(self):
        boolean_isolation = Mock()
        boolean_isolation.require_isolated.return_value = True
        broker = self.make_broker(isolation=boolean_isolation)
        self.assert_code(
            UseCode.ISOLATION,
            lambda: broker.approve(
                self.context, self.reference, self.specification.operation
            ),
        )
        for result in (True, False):
            self.verifier.verify.return_value = result
            self.assert_code(UseCode.VERIFICATION, self.approve)
        self.verifier.verify.side_effect = RuntimeError("synthetic verifier exception")
        self.assert_code(UseCode.VERIFICATION, self.approve)
        default = self.make_broker(owner_verifier=None)
        self.assert_code(
            UseCode.VERIFICATION,
            lambda: default.approve(
                self.context, self.reference, self.specification.operation
            ),
        )

    def test_capability_expiry_grant_expiry_and_invalid_lifetimes(self):
        grant, capability = self.capability(mode=GrantMode.BINDING, lifetime=60)
        self.now += 30
        self.assert_code(
            UseCode.CAPABILITY, lambda: self.broker.execute(self.context, capability)
        )
        self.now += 30
        self.assert_code(
            UseCode.EXPIRED, lambda: self.broker.authorize(self.context, grant.grant_id)
        )
        for lifetime in (0, -1, 3601, float("nan"), float("inf"), True, "900"):
            self.assert_code(UseCode.DENIED, lambda: self.approve(lifetime=lifetime))
        self.assert_code(UseCode.DENIED, lambda: self.approve(mode="once"))

    def test_lock_reunlock_new_epoch_does_not_resurrect_authority(self):
        grant, capability = self.capability(mode=GrantMode.BINDING)
        self.vault.lock()
        self.assertEqual(self.broker.status(self.context), VaultState.LOCKED)
        self.assert_code(
            UseCode.LOCKED, lambda: self.broker.authorize(self.context, grant.grant_id)
        )
        self.vault.unlock()
        self.assert_code(
            UseCode.LOCKED, lambda: self.broker.execute(self.context, capability)
        )
        self.assert_code(
            UseCode.LOCKED, lambda: self.broker.authorize(self.context, grant.grant_id)
        )

    def test_idle_time_is_not_renewed_by_use(self):
        grant, capability = self.capability(mode=GrantMode.BINDING, lifetime=3600)
        self.now += 899
        fresh = self.broker.authorize(self.context, grant.grant_id)
        with wire():
            self.broker.execute(self.context, fresh)
        self.now += 1
        self.assertEqual(self.vault.status().state, VaultState.LOCKED)
        self.assert_code(
            UseCode.CAPABILITY, lambda: self.broker.execute(self.context, capability)
        )

    def test_version_update_and_deletion_invalidate_pending_use(self):
        grant, capability = self.capability(mode=GrantMode.BINDING)
        self.reference = self.vault.update(
            self.reference, fields=Secret({"api_key": "replacement"})
        ).summary.reference
        with wire() as (connection, *_):
            self.assert_code(
                UseCode.CHANGED, lambda: self.broker.execute(self.context, capability)
            )
            self.assert_code(
                UseCode.CHANGED,
                lambda: self.broker.authorize(self.context, grant.grant_id),
            )
            grant, capability = self.capability(mode=GrantMode.BINDING)
            self.vault.delete(self.reference)
            self.assert_code(
                UseCode.UNAVAILABLE,
                lambda: self.broker.execute(self.context, capability),
            )
            connection.request.assert_not_called()

    def test_revocation_binding_revocation_and_cancellation(self):
        grant, capability = self.capability(mode=GrantMode.BINDING)
        self.broker.cancel(self.context, capability)
        self.assert_code(
            UseCode.CAPABILITY, lambda: self.broker.execute(self.context, capability)
        )
        capability = self.broker.authorize(self.context, grant.grant_id)
        self.broker.revoke(grant.grant_id)
        self.assert_code(
            UseCode.CAPABILITY, lambda: self.broker.execute(self.context, capability)
        )
        grant, capability = self.capability(mode=GrantMode.BINDING)
        self.directory.revoke(self.context.binding.binding_id)
        self.assert_code(
            UseCode.DENIED, lambda: self.broker.execute(self.context, capability)
        )
        self.assert_code(
            UseCode.DENIED, lambda: self.broker.authorize(self.context, grant.grant_id)
        )

    def test_restart_discards_grants_and_pending_capabilities(self):
        grant, capability = self.capability()
        restarted = self.make_broker()
        self.assert_code(
            UseCode.DENIED, lambda: restarted.authorize(self.context, grant.grant_id)
        )
        self.assert_code(
            UseCode.CAPABILITY, lambda: restarted.execute(self.context, capability)
        )

    def test_same_helper_id_cannot_rebind_an_approved_destination_or_policy(self):
        for replacement in (
            replace(self.specification, endpoint="https://other.test/v1/account"),
            replace(self.specification, endpoint="https://example.test/other-path"),
            replace(self.specification, kind=CredentialKind.LOGIN),
        ):
            grant, capability = self.capability(mode=GrantMode.BINDING)
            # Simulate a trusted host configuration reload. There is no public
            # registry mutation API; approvals still pin the full descriptor.
            self.broker._registry = HelperRegistry((replacement,))
            with wire() as (connection, *_):
                self.assert_code(
                    UseCode.DENIED,
                    lambda: self.broker.execute(self.context, capability),
                )
                self.assert_code(
                    UseCode.DENIED,
                    lambda: self.broker.authorize(self.context, grant.grant_id),
                )
                connection.request.assert_not_called()
            self.broker._registry = self.registry

    def test_existing_tokens_sessions_and_cookies_are_not_changed_by_helper_use(self):
        existing = Path(self.temp.name) / "existing-auth"
        existing.mkdir()
        files = {
            existing
            / "provider-tokens.json": b'{"access_token":"synthetic-access","refresh_token":"synthetic-refresh"}',
            existing / "browser-session.json": b'{"session_id":"synthetic-session"}',
            existing / "cookies.sqlite": b"synthetic-existing-cookie-bytes",
        }
        for path, value in files.items():
            path.write_bytes(value)
        _, capability = self.capability()
        with wire():
            self.broker.execute(self.context, capability)
        self.vault.lock()
        for path, value in files.items():
            self.assertEqual(path.read_bytes(), value)

    def test_interruptions_spend_once_grant_without_returning_secret_tracebacks(self):
        import traceback

        grant, capability = self.capability()
        with wire() as (connection, *_):
            connection.request.side_effect = KeyboardInterrupt("seeded-API_key/CM03==")
            try:
                self.broker.execute(self.context, capability)
            except KeyboardInterrupt as error:
                formatted = "".join(traceback.format_exception(error))
                self.assertNotIn("seeded-API_key", formatted)
                self.assertIsNone(error.__context__)
            else:
                self.fail("interruption was swallowed")
        self.assertEqual(self.vault.status().state, VaultState.LOCKED)
        self.assert_code(
            UseCode.DENIED, lambda: self.broker.authorize(self.context, grant.grant_id)
        )

    def test_concurrent_replay_sends_exactly_once(self):
        _, capability = self.capability()

        def attempt():
            try:
                return self.broker.execute(self.context, capability)
            except CredentialUseError as error:
                return error.code

        with wire() as (connection, *_), ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: attempt(), range(8)))
            self.assertEqual(results.count(HelperResult.ACCEPTED), 1)
            self.assertEqual(results.count(UseCode.CAPABILITY), 7)
            connection.request.assert_called_once()

    def test_once_grant_cannot_be_multiplied_by_issuing_several_capabilities(self):
        grant, first = self.capability()
        second = self.broker.authorize(self.context, grant.grant_id)
        with wire() as (connection, *_):
            self.broker.execute(self.context, first)
            self.assert_code(
                UseCode.CAPABILITY, lambda: self.broker.execute(self.context, second)
            )
            connection.request.assert_called_once()

    def test_recheck_after_slow_dns_and_tls_before_secret_send(self):
        for phase in ("dns", "tls", "isolation"):
            _, capability = self.capability(mode=GrantMode.BINDING)
            with wire() as (connection, _, resolver, _, _, tls):
                if phase == "dns":
                    addresses = resolver.return_value

                    def slow_dns(*args, **kwargs):
                        self.now += 31
                        return addresses

                    resolver.side_effect = slow_dns
                elif phase == "tls":

                    def slow_tls(*args, **kwargs):
                        self.now += 31
                        return MagicMock()

                    tls.wrap_socket.side_effect = slow_tls
                else:

                    def lost_boundary(*args, **kwargs):
                        self.isolation.available = False
                        return MagicMock()

                    tls.wrap_socket.side_effect = lost_boundary
                self.assert_code(
                    UseCode.ISOLATION if phase == "isolation" else UseCode.CAPABILITY,
                    lambda: self.broker.execute(self.context, capability),
                )
                connection.request.assert_not_called()

    def test_network_exception_echoes_never_escape_diagnostic_tracebacks(self):
        from loguru import logger

        seed = Secret("Bearer seeded-API_key/CM03==")
        grant, capability = self.capability()
        output = io.StringIO()
        sink = logger.add(output, diagnose=True, backtrace=True, colorize=False)
        try:
            with wire() as (connection, *_):
                connection.getresponse.side_effect = RuntimeError(seed.reveal())
                try:
                    self.broker.execute(self.context, capability)
                except CredentialUseError:
                    logger.exception("synthetic helper failure")
                self.assertEqual(self.vault.status().state, VaultState.READY)
            self.assertNotIn(seed.reveal(), output.getvalue())
            self.assertNotIn("seeded-API_key", output.getvalue())
            self.assertNotIn(capability.handle, output.getvalue())
            self.assertIn(UseCode.HELPER.value, output.getvalue())
            self.assert_code(
                UseCode.DENIED,
                lambda: self.broker.authorize(self.context, grant.grant_id),
            )
        finally:
            logger.remove(sink)

    def test_audit_is_bounded_value_free_and_includes_denials(self):
        for _ in range(520):
            self.assert_code(
                UseCode.DENIED, lambda: self.broker.authorize(self.context, uuid4())
            )
        events = self.broker.audit_events()
        self.assertEqual(len(events), 512)
        self.assertTrue(
            all(
                event.action == "authorize" and event.outcome == "denied"
                for event in events
            )
        )
        self.assertNotIn("seeded-API", repr(events))
        self.assertNotIn(self.owner.os_identity, repr(events))


class FixedHelperTests(unittest.TestCase):
    def test_bedrock_signs_only_reviewed_destination_and_filters_both_source_fields(
        self,
    ):
        from app.credentials.helpers import HttpsJsonOperation, _execute_json

        spec = HttpsJsonOperation(
            HelperOperation("model_bedrock", "converse"),
            CredentialKind.SERVICE_SECRET,
            "https://bedrock-runtime.us-east-1.amazonaws.com/model/synthetic.model-v1:0/converse",
            secret_field="secret_access_key",
            protocol="aws_bedrock",
        )
        access, secret = "SYNTHETICACCESSKEY123", "SyntheticSigningSecret1234567890"
        with wire() as (connection, response, *_):
            response.getheader.return_value = "application/json"
            response.read.return_value = (
                '{"id":"' + access + '","echo":"' + secret + '"}'
            ).encode()
            result = _execute_json(
                spec,
                Secret({"access_key_id": access, "secret_access_key": secret}),
                Mock(),
                {"body": {"messages": []}},
            )
            headers = connection.request.call_args.args[3]
            self.assertTrue(
                headers["Authorization"].startswith(
                    "AWS4-HMAC-SHA256 Credential=" + access + "/"
                )
            )
            self.assertNotIn(secret, headers["Authorization"])
            self.assertNotIn(access, result.body)
            self.assertNotIn(secret, result.body)
            self.assertIn("x-amz-date", headers)
        for endpoint in (
            "https://attacker.test/model/x/converse",
            "https://bedrock-runtime.us-east-1.amazonaws.com:443/model/x/converse",
            "https://bedrock-runtime.us-east-1.amazonaws.com/model/%2Fx/converse",
            "https://bedrock-runtime.us-east-1.amazonaws.com/other",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                replace(spec, endpoint=endpoint)

    def test_json_operation_releases_only_sanitized_data_and_no_headers(self):
        import base64
        import json
        from app.credentials.helpers import HttpsJsonOperation, _execute_json

        spec = HttpsJsonOperation(
            HelperOperation("model_example", "chat"),
            CredentialKind.API_KEY,
            "https://example.test/v1/chat",
            protocol="openai",
        )
        seed = "seeded-secret-JSON/CM04=="
        body = json.dumps(
            {"content": seed, "encoded": base64.b64encode(seed.encode()).decode()}
        )
        with wire() as (connection, response, *_):
            response.read.return_value = body.encode()
            response.getheader.return_value = "application/json"
            result = _execute_json(
                spec,
                Secret({"api_key": seed}),
                Mock(),
                {"body": {"model": "synthetic"}},
            )
            self.assertNotIn(seed, result.body)
            self.assertNotIn(base64.b64encode(seed.encode()).decode(), result.body)
            self.assertEqual(
                json.loads(result.body),
                {"content": "[redacted]", "encoded": "[redacted]"},
            )
            self.assertEqual(connection.request.call_args.args[0], "POST")
            self.assertEqual(result.status, 200)

    def test_json_errors_redirects_and_consumer_transport_arguments_cannot_escape(self):
        from app.credentials.helpers import HttpsJsonOperation, _execute_json

        spec = HttpsJsonOperation(
            HelperOperation("integration_example", "read"),
            CredentialKind.API_KEY,
            "https://example.test/v1/read",
        )
        for status in (302, 401, 429, 500):
            with self.subTest(status=status), wire(status) as (_, response, *_):
                response.read.return_value = b"seeded-provider-error-containing-secret"
                result = _execute_json(
                    spec, Secret({"api_key": "synthetic-key"}), Mock(), {"body": {}}
                )
                self.assertNotIn("seeded", result.body)
                response.read.assert_not_called()
        for value in (
            {"body": {}, "url": "https://attacker.test"},
            {"body": {}, "headers": {}},
            {"body": []},
        ):
            with self.subTest(value=value), wire() as (connection, *_):
                with self.assertRaises(CredentialUseError):
                    _execute_json(
                        spec, Secret({"api_key": "synthetic-key"}), Mock(), value
                    )
                connection.request.assert_not_called()

    def test_json_stream_buffers_split_echoes_and_rejects_non_json_records(self):
        from app.credentials.helpers import HttpsJsonOperation, _execute_json

        spec = HttpsJsonOperation(
            HelperOperation("model_example", "stream"),
            CredentialKind.API_KEY,
            "https://example.test/v1/stream",
            protocol="openai",
        )
        with wire() as (_, response, *_):
            response.getheader.return_value = "text/event-stream; charset=utf-8"
            response.read.return_value = (
                b'data: {"content":"synthetic-echo-key"}\n\ndata: [DONE]\n\n'
            )
            result = _execute_json(
                spec,
                Secret({"api_key": "synthetic-echo-key"}),
                Mock(),
                {"body": {"stream": True}},
            )
            self.assertNotIn("synthetic-echo-key", result.body)
            response.read.return_value = b"data: not-json\n\n"
            with self.assertRaises(CredentialUseError):
                _execute_json(
                    spec,
                    Secret({"api_key": "synthetic-echo-key"}),
                    Mock(),
                    {"body": {"stream": True}},
                )

    def test_semantic_stream_fragments_cannot_reassemble_a_source_key(self):
        import json
        from app.credentials.helpers import HttpsJsonOperation, _execute_json

        spec = HttpsJsonOperation(
            HelperOperation("model_example", "stream"),
            CredentialKind.API_KEY,
            "https://example.test/v1/stream",
            protocol="openai",
        )
        for fragments in (
            ["synthetic-", "split-key"],
            ["c3ludGhldGlj", "LXNwbGl0LWtleQ=="],
        ):
            with self.subTest(fragments=fragments), wire() as (_, response, *_):
                response.getheader.return_value = "text/event-stream"
                response.read.return_value = "\n\n".join(
                    "data: "
                    + json.dumps(
                        {"id": str(i), "choices": [{"delta": {"content": part}}]}
                    )
                    for i, part in enumerate(fragments)
                ).encode()
                with self.assertRaises(CredentialUseError):
                    _execute_json(
                        spec,
                        Secret({"api_key": "synthetic-split-key"}),
                        Mock(),
                        {"body": {"stream": True}},
                    )

    def test_unused_service_fields_do_not_influence_provider_output(self):
        from app.credentials.helpers import HttpsJsonOperation, _execute_json

        spec = HttpsJsonOperation(
            HelperOperation("integration_example", "read"),
            CredentialKind.SERVICE_SECRET,
            "https://example.test/read",
            secret_field="selected",
        )
        with wire() as (_, response, *_):
            response.getheader.return_value = "application/json"
            response.read.return_value = b'{"content":"unrelated-private-field"}'
            result = _execute_json(
                spec,
                Secret(
                    {"selected": "sent-source-key", "unused": "unrelated-private-field"}
                ),
                Mock(),
                {"body": {}},
            )
            self.assertIn("unrelated-private-field", result.body)

    def setUp(self):
        self.specification = HttpsCredentialCheck(
            HelperOperation("example", "check"),
            CredentialKind.API_KEY,
            "https://example.test/v1/account",
        )

    def test_invalid_registry_entries_and_mutation_are_rejected(self):
        for entries in (
            [self.specification],
            (lambda: "secret",),
            (self.specification, self.specification),
        ):
            with self.assertRaises(ValueError):
                HelperRegistry(entries)
        with self.assertRaises(FrozenInstanceError):
            self.specification.endpoint = "https://other.test"
        registry = HelperRegistry((self.specification,))
        with self.assertRaises(TypeError):
            registry._entries[self.specification.operation] = self.specification

    def test_total_deadline_shuts_down_a_stalled_response(self):
        from threading import Event, Timer

        aborted = Event()
        with wire() as (connection, _, _, _, _, tls):
            tls.wrap_socket.return_value.shutdown.side_effect = lambda _: aborted.set()

            def stalled_response():
                aborted.wait(1)
                raise ConnectionResetError("synthetic stalled response")

            connection.getresponse.side_effect = stalled_response
            with patch(
                "app.credentials.helpers.Timer",
                side_effect=lambda interval, callback, args: Timer(
                    0.01, callback, args
                ),
            ):
                with self.assertRaises(CredentialUseError) as caught:
                    _execute_check(
                        self.specification, Secret({"api_key": "seed"}), Mock()
                    )
            self.assertEqual(caught.exception.code, UseCode.HELPER)
            self.assertTrue(aborted.is_set())
            tls.wrap_socket.return_value.shutdown.assert_called_once_with(
                socket.SHUT_RDWR
            )
            connection.close.assert_called_once()

    def test_dns_returning_after_request_budget_cannot_send_credentials(self):
        with wire() as (connection, _, _, factory, *_):
            with patch(
                "app.credentials.helpers.time.monotonic", side_effect=(100, 111)
            ):
                with self.assertRaises(CredentialUseError):
                    _execute_check(
                        self.specification, Secret({"api_key": "seed"}), Mock()
                    )
            connection.request.assert_not_called()
            factory.assert_not_called()

    def test_encoded_secret_exception_cannot_escape_diagnostic_logging(self):
        from loguru import logger

        specification = replace(self.specification, kind=CredentialKind.LOGIN)
        fields = Secret({"username": "user", "password": "synthetic-password"})
        echoed = Secret("Basic dXNlcjpzeW50aGV0aWMtcGFzc3dvcmQ=")
        output = io.StringIO()
        sink = logger.add(output, diagnose=True, backtrace=True, colorize=False)
        try:
            with wire() as (connection, *_):
                connection.getresponse.side_effect = RuntimeError(echoed.reveal())
                try:
                    _execute_check(specification, fields, Mock())
                except CredentialUseError:
                    logger.exception("synthetic encoded helper failure")
            self.assertNotIn(echoed.reveal(), output.getvalue())
            self.assertNotIn(fields.reveal()["password"], output.getvalue())
            self.assertIn(UseCode.HELPER.value, output.getvalue())
        finally:
            logger.remove(sink)

    def test_endpoint_validation(self):
        for endpoint in (
            "http://example.test",
            "https://user:pass@example.test",
            "https://example.test?callback=https://other.test",
            "https://example.test/#fragment",
            "https://example.test:",
            "https://example.test:0",
            "https://example.test:65536",
            "https://example.test\\@other.test",
            "https://example.test/\r\ninjected",
            "https://exämple.test",
            " https://example.test",
            "https://example.test/?",
        ):
            with (
                self.subTest(endpoint=endpoint),
                self.assertRaises((ValueError, VaultError)),
            ):
                replace(self.specification, endpoint=endpoint)

    def test_private_special_mixed_and_empty_dns_never_send_secrets(self):
        addresses = [
            "127.0.0.1",
            "10.1.2.3",
            "169.254.169.254",
            "100.64.0.1",
            "0.0.0.0",
            "224.0.0.1",
            "::1",
            "fc00::1",
            "fe80::1",
            "::ffff:127.0.0.1",
            "2002:7f00:1::",
            "fec0::1",
        ]
        for address in addresses:
            with (
                self.subTest(address=address),
                wire() as (connection, _, resolver, factory, *_),
            ):
                resolver.return_value = [
                    (
                        socket.AF_INET6 if ":" in address else socket.AF_INET,
                        socket.SOCK_STREAM,
                        socket.IPPROTO_TCP,
                        "",
                        (address, 443),
                    )
                ]
                with self.assertRaises(CredentialUseError) as caught:
                    _execute_check(
                        self.specification, Secret({"api_key": "seed"}), Mock()
                    )
                self.assertEqual(caught.exception.code, UseCode.DENIED)
                factory.assert_not_called()
                connection.request.assert_not_called()
        for mixed in (False, True):
            with wire() as (connection, _, resolver, factory, *_):
                resolver.return_value = (
                    resolver.return_value
                    + [
                        (
                            socket.AF_INET,
                            socket.SOCK_STREAM,
                            socket.IPPROTO_TCP,
                            "",
                            ("127.0.0.1", 443),
                        )
                    ]
                    if mixed
                    else []
                )
                with self.assertRaises(CredentialUseError):
                    _execute_check(
                        self.specification, Secret({"api_key": "seed"}), Mock()
                    )
                factory.assert_not_called()

    def test_redirects_and_response_echoes_only_return_coarse_outcomes(self):
        for status, expected in (
            (200, HelperResult.ACCEPTED),
            (204, HelperResult.ACCEPTED),
            (401, HelperResult.REJECTED),
            (403, HelperResult.REJECTED),
            (302, HelperResult.UNAVAILABLE),
            (307, HelperResult.UNAVAILABLE),
            (500, HelperResult.UNAVAILABLE),
        ):
            with wire(status) as (connection, response, *_):
                response.reason = "seeded-response-echo"
                response.headers = {
                    "Location": "https://other.test/seeded-value",
                    "Set-Cookie": "seeded-token",
                }
                result = _execute_check(
                    self.specification, Secret({"api_key": "seed"}), Mock()
                )
                self.assertIs(result, expected)
                connection.request.assert_called_once()
                response.read.assert_not_called()
                self.assertNotIn("seeded", repr(result))

    def test_basic_and_explicit_service_secret_use_stay_inside_helper(self):
        for specification, fields, expected in (
            (
                replace(self.specification, kind=CredentialKind.LOGIN),
                {"username": "user", "password": "synthetic-password"},
                "Basic dXNlcjpzeW50aGV0aWMtcGFzc3dvcmQ=",
            ),
            (
                replace(
                    self.specification,
                    kind=CredentialKind.SERVICE_SECRET,
                    secret_field="personal_access_token",
                ),
                {"personal_access_token": "synthetic-pat"},
                "Bearer synthetic-pat",
            ),
        ):
            with wire() as (connection, *_):
                self.assertIs(
                    _execute_check(specification, Secret(fields), Mock()),
                    HelperResult.ACCEPTED,
                )
                self.assertEqual(
                    connection.request.call_args.kwargs["headers"]["Authorization"],
                    expected,
                )

    def test_header_injection_and_ambiguous_basic_username_are_denied(self):
        for specification, fields in (
            (self.specification, {"api_key": "seed\r\nX-Header: yes"}),
            (
                replace(self.specification, kind=CredentialKind.LOGIN),
                {"username": "user:other", "password": "seed"},
            ),
            (
                replace(self.specification, kind=CredentialKind.LOGIN),
                {"username": "user", "password": "seed\nline"},
            ),
        ):
            with wire() as (connection, *_), self.assertRaises(CredentialUseError):
                _execute_check(specification, Secret(fields), Mock())
            connection.request.assert_not_called()
