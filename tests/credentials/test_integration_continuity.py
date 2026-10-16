"""Source references must not change the ownership of existing OAuth state."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from uuid import uuid4

from app.credentials.references import SourceReference
from craftos_integrations.contracts import Operation
from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem


class Provider:
    id = "synthetic"
    family = None

    def __init__(self):
        self.built = []

    def build_client(self, credential, persist):
        self.built.append(credential)
        return SimpleNamespace(read=lambda value: (credential["email"], value))

    def operations(self):
        async def read(client, data):
            # Exercise the existing operation wrapper, not an SPI bypass.
            return {"result": client.read(data["value"].strip())}

        return [Operation("read", "Synthetic read", {}, {}, read)]


class SourceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.provider, self.spi = Provider(), Mock()
        self.system = IntegrationSystem(
            FileCredentialStore(root=Path(self.temporary.name)),
            providers=[self.provider],
            source_credentials=self.spi,
        )
        self.reference = SourceReference(uuid4(), uuid4(), 1).encode()
        self.spi.connect.return_value = (
            "person@example.test",
            {"email": "person@example.test", "auth_kind": "vault"},
        )
        self.spi.client_for.return_value = SimpleNamespace(
            read=lambda value: ("source", value)
        )

    def run_read(self, account=None):
        return asyncio.run(
            self.system.execute(
                "synthetic", "read", {"value": "  data  "}, account=account
            )
        )

    def test_source_connect_and_rebind_preserve_alias_and_operation_wrapper(self):
        identity = self.system.connect_source("synthetic", self.reference)
        self.system.set_alias("synthetic", identity, "Work")
        self.assertEqual(self.run_read("Work"), {"result": ("source", "data")})
        self.assertEqual(self.provider.built, [])
        replacement = SourceReference(uuid4(), uuid4(), 2).encode()
        self.system.connect_source("synthetic", replacement)
        self.assertEqual(self.system.list_accounts("synthetic")[0].alias, "Work")
        record = self.system.accounts.credential_for("synthetic", identity)
        self.assertEqual(record["source_reference"], replacement)
        self.assertNotIn("access_token", record)
        self.assertFalse(self.system.list_accounts("synthetic")[0].listen)

    def test_source_binding_cannot_overwrite_connected_oauth_identity(self):
        original = {
            "email": "person@example.test",
            "access_token": "synthetic-generated-access",
            "refresh_token": "synthetic-generated-refresh",
            "session_id": "synthetic-session",
        }
        self.system.store_credential("synthetic", "person@example.test", original)
        with self.assertRaisesRegex(ValueError, "credential_account_already_connected"):
            self.system.connect_source("synthetic", self.reference)
        self.assertEqual(
            self.system.accounts.credential_for("synthetic", "person@example.test"),
            original,
        )

    def test_generated_account_executes_and_refreshes_without_vault(self):
        self.spi.client_for.side_effect = RuntimeError("synthetic-vault-locked")
        original = {
            "email": "oauth@example.test",
            "access_token": "generated",
            "refresh_token": "refresh",
            "session_id": "session",
        }
        self.system.store_credential("synthetic", "oauth@example.test", original)
        self.assertEqual(self.run_read(), {"result": ("oauth@example.test", "data")})
        refreshed = {**original, "access_token": "renewed"}
        self.system.update_credential("synthetic", "oauth@example.test", refreshed)
        self.assertEqual(
            self.system.accounts.credential_for("synthetic", "oauth@example.test"),
            refreshed,
        )
        self.spi.client_for.assert_not_called()

    def test_source_listener_setting_preserves_reference_and_never_gets_values(self):
        identity = self.system.connect_source("synthetic", self.reference)
        before = self.system.accounts.credential_for("synthetic", identity)
        self.system.set_listening("synthetic", identity, True)
        self.assertTrue(self.system.list_accounts("synthetic")[0].listen)
        self.assertEqual(
            before, self.system.accounts.credential_for("synthetic", identity)
        )
