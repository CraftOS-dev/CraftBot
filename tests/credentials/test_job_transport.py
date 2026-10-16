"""Authorization and bounded transport controls for asynchronous operations."""

import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from uuid import uuid4

from app.credentials.broker import GrantMode
from app.credentials.contracts import CredentialKind, HelperOperation
from app.credentials.execution import OperationJob
from app.credentials.helpers import HelperRegistry, HttpsJsonOperation
from app.credentials.host_service import ProtectedHost
from app.credentials.use_errors import CredentialUseError
import test_broker as broker_test_support


class JobTransportTests(unittest.TestCase):
    def setUp(self):
        self.case = broker_test_support.CredentialBrokerTests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.host = object.__new__(ProtectedHost)
        self.host.owner = self.case.owner
        self.host.views = {}
        self.host.vaults = {self.case.profile.scope.profile_id: self.case.vault}
        self.host.consent = Mock()
        self.host.consent.verify.return_value = None
        self.host.broker = self.case.broker
        self.case.broker._verifier = self.host.consent
        self.launch = SimpleNamespace(
            payload_ready=True,
            payload_text="null",
            context=self.case.context,
            job=None,
            deadline=time.monotonic() + 900,
            controller=Mock(alive=Mock(return_value=True)),
        )
        self.host.leases = {uuid4(): self.launch}
        self.host._consumer = Mock(return_value=self.launch)
        self.peer = SimpleNamespace(
            sid=self.case.owner.os_identity,
            container=False,
            elevated=False,
            alive=lambda: True,
            session=1,
        )

    def request(self, method, repeat):
        spec = HttpsJsonOperation(
            HelperOperation("integration_example", "read"),
            CredentialKind.API_KEY,
            "https://example.test/items",
            method=method,
        )
        self.host.registry = HelperRegistry((spec,))
        self.case.broker._registry = self.host.registry
        return self.host.dispatch(
            self.peer,
            dict(
                op="request_use",
                helper="integration_example",
                operation="read",
                credential_id=str(self.case.reference.credential_id),
                credential_version=1,
                repeat=repeat,
            ),
        )

    def test_repeated_read_needs_fresh_native_consent_and_exact_binding(self):
        response = self.request("GET", True)
        self.host.consent.verify.assert_called_once_with(self.case.owner)
        self.assertIn("repeated GET", self.host.consent.message)
        self.assertIn("15-minute", self.host.consent.message)
        grant = next(iter(self.case.broker._grants.values()))
        self.assertEqual(grant.mode, GrantMode.BINDING)
        other = self.case.new_context()
        self.launch.context = other
        with self.assertRaises(CredentialUseError):
            self.host.dispatch(
                self.peer, dict(op="authorize_grant", grant_id=response["grant_id"])
            )

    def test_repetition_cannot_broaden_to_writes_or_untyped_values(self):
        for method, repeat in (("POST", True), ("PATCH", True), ("GET", "true")):
            with (
                self.subTest(method=method, repeat=repeat),
                self.assertRaises(CredentialUseError),
            ):
                self.request(method, repeat)
        self.host.consent.verify.assert_not_called()
        self.assertEqual(self.case.broker._grants, {})

    def test_legacy_sync_dispatch_cannot_monopolize_the_control_pipe(self):
        for op in ("use", "use_staged"):
            with self.subTest(op=op), self.assertRaises(CredentialUseError):
                self.host.dispatch(self.peer, {"op": op, "capability": "x" * 43})
        self.assertEqual(self.case.broker._pending, {})

    def test_idle_lock_cancels_active_profile_jobs(self):
        self.launch.job = OperationJob(lambda job: None)
        self.case.vault._on_lock = lambda: self.host._cancel_profile(
            self.case.profile.scope
        )
        self.case.now += 901
        self.case.vault._expire()
        self.assertTrue(self.launch.job.cancelled.is_set())

    def test_catalog_paging_bounds_serialized_bytes_and_advances_without_skips(self):
        query = tuple("field_" + str(i) + "_" + "a" * 36 for i in range(60))
        specs = tuple(
            HttpsJsonOperation(
                HelperOperation("model_example", "op_" + str(i)),
                CredentialKind.API_KEY,
                "https://example.test/" + "a" * 1800 + str(i),
                method="GET",
                query_fields=query,
            )
            for i in range(8)
        )
        self.host.registry = HelperRegistry(specs)
        offset, seen = 0, []
        while True:
            page = self.host.dispatch(self.peer, {"op": "catalog", "offset": offset})
            self.assertLess(len(json.dumps(page, ensure_ascii=True).encode()), 65536)
            seen.extend(row["operation"] for row in page["helpers"])
            if offset == 0:
                self.assertLess(len(page["helpers"]), 8)
            if not page["more"]:
                break
            self.assertGreater(page["next_offset"], offset)
            offset = page["next_offset"]
        self.assertEqual(seen, ["op_" + str(i) for i in range(8)])

    def test_astral_unicode_output_cannot_overflow_native_frame(self):
        job = OperationJob(lambda job: None)
        job.emit("\U0001f680" * 10000)
        offset, result = 0, ""
        while offset < len(job.body):
            page = job.snapshot(offset)
            self.assertLess(len(json.dumps(page, ensure_ascii=True).encode()), 65536)
            result += page["chunk"]
            offset += len(page["chunk"])
        self.assertEqual(result, job.body)
