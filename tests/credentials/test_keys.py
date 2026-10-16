"""OS key adapter tests. Real smoke test uses only a fresh synthetic UUID target."""

from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet

from app.credentials.errors import VaultError, VaultErrorCode as Code
from app.credentials.identity import VaultScope
from app.credentials import keys
from app.credentials.keys import WindowsCredentialKeyStore, key_target
from app.credentials.secrets import Secret


class FakeWinCred:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self):
        self.records = {}
        self.fail_read = self.fail_write = False

    def CredRead(self, target, kind, flags):
        if self.fail_read or target not in self.records:
            failure = OSError("synthetic OS error")
            failure.winerror = 5 if self.fail_read else 1168
            raise failure
        return self.records[target]

    def CredWrite(self, record, flags):
        if self.fail_write:
            raise OSError("synthetic write error")
        self.records[record["TargetName"]] = {
            **record,
            "CredentialBlob": record["CredentialBlob"].encode("utf-16-le"),
        }


class KeyStoreTests(unittest.TestCase):
    def setUp(self):
        self.scope = VaultScope(uuid4(), uuid4())
        self.backend = WindowsCredentialKeyStore()
        self.api = FakeWinCred()
        self.key = Secret(Fernet.generate_key())

    def test_stores_key_only_in_os_facility_and_never_overwrites(self):
        with patch.object(self.backend, "_api", return_value=self.api):
            self.assertIsNone(self.backend.load(self.scope))
            self.backend.create(self.scope, self.key)
            self.assertEqual(self.backend.load(self.scope).reveal(), self.key.reveal())
            self.assertEqual(self.api.records[key_target(self.scope)]["Persist"], 2)
            with self.assertRaises(VaultError) as caught:
                self.backend.create(self.scope, Secret(Fernet.generate_key()))
            self.assertEqual(caught.exception.code, Code.CONFLICT)
            self.assertEqual(self.backend.load(self.scope).reveal(), self.key.reveal())

    def test_read_errors_and_write_errors_do_not_fall_back(self):
        with patch.object(self.backend, "_api", return_value=self.api):
            self.api.fail_read = True
            with self.assertRaises(VaultError) as caught:
                self.backend.load(self.scope)
            self.assertEqual(caught.exception.code, Code.BACKEND_UNAVAILABLE)
            self.api.fail_read = False
            self.api.fail_write = True
            with self.assertRaises(VaultError) as caught:
                self.backend.create(self.scope, self.key)
            self.assertEqual(caught.exception.code, Code.BACKEND_UNAVAILABLE)
            self.assertEqual(self.api.records, {})

    def test_bad_key_blob_is_not_treated_as_missing(self):
        self.api.records[key_target(self.scope)] = {"CredentialBlob": b"bad"}
        with patch.object(self.backend, "_api", return_value=self.api):
            with self.assertRaises(VaultError) as caught:
                self.backend.load(self.scope)
            self.assertEqual(caught.exception.code, Code.UNREADABLE)

    def test_unsupported_platform_fails_closed(self):
        with patch.object(keys, "sys", SimpleNamespace(platform="unsupported")):
            with self.assertRaises(VaultError) as caught:
                self.backend.load(self.scope)
            self.assertEqual(caught.exception.code, Code.BACKEND_UNAVAILABLE)

    @unittest.skipUnless(sys.platform == "win32", "Windows key-facility smoke test")
    def test_real_windows_facility_roundtrip_for_synthetic_key(self):
        # No enumeration or reads of existing user credentials. This UUID target
        # belongs only to this test; deletion is confined to that exact target.
        import win32cred

        target = key_target(self.scope)
        self.assertIsNone(self.backend.load(self.scope))
        try:
            self.backend.create(self.scope, self.key)
            self.assertEqual(self.backend.load(self.scope).reveal(), self.key.reveal())
        finally:
            try:
                win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
            except Exception as exc:
                if getattr(exc, "winerror", None) != 1168:
                    raise

    @unittest.skipUnless(sys.platform == "win32", "Windows full vault smoke test")
    def test_real_key_facility_with_profile_vault_restart(self):
        import tempfile
        from pathlib import Path
        import win32cred

        from app.credentials.contracts import CredentialKind
        from app.credentials.identity import VaultOwner, VaultProfile
        from app.credentials.vault import ProfileVault

        owner = VaultOwner(self.scope.owner_id, "test-os:synthetic-owner")
        profile = VaultProfile(self.scope, "Synthetic smoke test")
        # Test verification only. Production has no default owner verifier.
        verifier = SimpleNamespace(verify=lambda owner: None)
        vault = restarted = None
        with tempfile.TemporaryDirectory() as root:
            try:
                vault = ProfileVault(
                    Path(root) / "vaults", owner, profile, verifier=verifier
                )
                vault.initialize()
                vault.create(
                    CredentialKind.API_KEY,
                    "synthetic-provider",
                    "Synthetic account",
                    Secret({"api_key": "synthetic-smoke-test-value"}),
                )
                vault.close()
                restarted = ProfileVault(
                    Path(root) / "vaults", owner, profile, verifier=verifier
                )
                restarted.unlock()
                self.assertEqual(len(restarted.list_items()), 1)
            finally:
                if vault is not None:
                    vault.close()
                if restarted is not None:
                    restarted.close()
                try:
                    win32cred.CredDelete(
                        key_target(self.scope), win32cred.CRED_TYPE_GENERIC, 0
                    )
                except Exception as exc:
                    if getattr(exc, "winerror", None) != 1168:
                        raise
