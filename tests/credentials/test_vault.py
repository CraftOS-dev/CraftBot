"""Synthetic profile-vault storage tests; never read legacy/user credentials."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet

from app.credentials.contracts import CredentialKind
from app.credentials.errors import VaultError, VaultErrorCode as Code
from app.credentials.identity import VaultOwner, VaultProfile, VaultScope
from app.credentials.secrets import Secret
from app.credentials.storage import SnapshotStore
from app.credentials.vault import ProfileVault, VaultState


class MemoryKeys:
    """Test-only replacement for the OS facility, not a production fallback."""

    def __init__(self):
        self.keys = {}
        self.created = 0
        self.fail = False

    def load(self, scope):
        if self.fail:
            raise RuntimeError("synthetic backend failure")
        return self.keys.get(scope)

    def create(self, scope, key):
        if scope in self.keys:
            raise AssertionError("key would be replaced")
        self.keys[scope] = key
        self.created += 1


class VerifiedTestOwner:
    def __init__(self, owner):
        self.owner = owner

    def verify(self, owner):
        if owner != self.owner:
            raise VaultError(Code.VERIFICATION_REQUIRED)


class ProfileVaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "vaults"
        self.owner = VaultOwner(uuid4(), "test-os:synthetic-owner")
        self.profile = VaultProfile(VaultScope(self.owner.owner_id, uuid4()), "Work")
        self.keys = MemoryKeys()
        self.now = 1000.0
        self.instances = []
        self.vault = self.make_vault()
        self.vault.initialize()

    def tearDown(self):
        for vault in self.instances:
            vault.close()
        self.temp.cleanup()

    def make_vault(self, profile=None, owner=None, **kwargs):
        options = {
            "key_store": self.keys,
            "verifier": VerifiedTestOwner(self.owner),
            "clock": lambda: self.now,
        }
        options.update(kwargs)
        vault = ProfileVault(
            self.root, owner or self.owner, profile or self.profile, **options
        )
        self.instances.append(vault)
        return vault

    def add_login(self, vault=None):
        return (vault or self.vault).create(
            CredentialKind.LOGIN,
            "example.test",
            "Work account",
            Secret(
                {
                    "username": "synthetic@example.test",
                    "password": "seeded-password\nline2",
                }
            ),
            allowed_origins=("https://Example.test:443/",),
        )

    def document(self, vault=None):
        vault = vault or self.vault
        with closing(sqlite3.connect(vault.store.path)) as connection, connection:
            encrypted = SnapshotStore.read(connection)
        return json.loads(
            Fernet(self.keys.keys[vault.profile.scope].reveal()).decrypt(encrypted)
        )

    def assert_code(self, code, fn):
        with self.assertRaises(VaultError) as caught:
            fn()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code.value)

    def test_crud_restart_versions_and_metadata_only_results(self):
        login = self.add_login()
        api = self.vault.create(
            CredentialKind.API_KEY,
            "provider",
            "Primary",
            Secret({"api_key": "seeded-api-key"}),
        )
        self.vault.create(
            CredentialKind.SERVICE_SECRET,
            "figma",
            "Manual PAT",
            Secret({"access_token": "seeded-pat"}),
        )
        self.assertEqual(login.allowed_origins, ("https://example.test",))
        self.assertEqual(len(self.vault.list_items()), 3)
        public = repr(tuple(asdict(item) for item in self.vault.list_items()))
        for hidden in (
            "seeded-password",
            "seeded-api-key",
            "seeded-pat",
            self.owner.os_identity,
        ):
            self.assertNotIn(hidden, public)
        changed = self.vault.update(
            login.summary.reference,
            account_label="Renamed",
            fields=Secret({"password": ""}),
        )
        self.assertEqual(
            changed.summary.reference.credential_id,
            login.summary.reference.credential_id,
        )
        self.assertEqual(changed.summary.reference.version, 2)
        self.assert_code(
            Code.CONFLICT, lambda: self.vault.delete(login.summary.reference)
        )
        self.vault.delete(api.summary.reference)
        restarted = self.make_vault(
            profile=replace(self.profile, label="Stale caller label")
        )
        self.assertEqual(restarted.status().state, VaultState.LOCKED)
        restarted.unlock()
        self.assertEqual(restarted.profile.label, "Work")
        self.assertEqual(len(restarted.list_items()), 2)
        saved = self.document(restarted)
        self.assertEqual(
            saved["items"][0]["fields"]["password"], "seeded-password\nline2"
        )

    def test_profiles_have_independent_keys_and_reject_foreign_references(self):
        item = self.add_login()
        personal = self.make_vault(
            profile=replace(
                self.profile,
                scope=VaultScope(self.owner.owner_id, uuid4()),
                label="Personal",
            )
        )
        personal.initialize()
        self.assertEqual(personal.list_items(), ())
        self.assertNotEqual(
            self.keys.keys[self.profile.scope].reveal(),
            self.keys.keys[personal.profile.scope].reveal(),
        )
        self.assert_code(
            Code.SCOPE_DENIED, lambda: personal.delete(item.summary.reference)
        )
        self.assertEqual(len(self.vault.list_items()), 1)

    def test_default_verifier_fails_before_key_or_disk_access(self):
        root = Path(self.temp.name) / "unverified"
        vault = ProfileVault(root, self.owner, self.profile, key_store=self.keys)
        self.instances.append(vault)
        self.assert_code(Code.VERIFICATION_REQUIRED, vault.initialize)
        self.assertFalse(root.exists())

    def test_boolean_verifier_results_are_not_owner_verification(self):
        class BooleanVerifier:
            def verify(self, owner):
                return False

        vault = self.make_vault(verifier=BooleanVerifier())
        self.assert_code(Code.VERIFICATION_REQUIRED, vault.unlock)
        self.assertIsNone(vault._crypto)

    def test_missing_crypto_backend_fails_closed(self):
        with patch(
            "app.credentials.vault._cipher",
            side_effect=VaultError(Code.BACKEND_UNAVAILABLE),
        ):
            self.assert_code(Code.BACKEND_UNAVAILABLE, self.vault.unlock)
        self.assertEqual(self.vault.status().state, VaultState.UNAVAILABLE)
        self.assertIsNone(self.vault._crypto)

    def test_wrong_owner_and_missing_key_never_create_replacement_key(self):
        item = self.add_login()
        created = self.keys.created
        self.vault.lock()
        del self.keys.keys[self.profile.scope]
        self.assert_code(Code.UNREADABLE, self.vault.unlock)
        self.assert_code(Code.ALREADY_EXISTS, self.vault.initialize)
        self.assertEqual(self.keys.created, created)
        wrong = self.make_vault(owner=replace(self.owner, os_identity="test-os:other"))
        self.assert_code(Code.VERIFICATION_REQUIRED, wrong.unlock)
        self.assertIsNotNone(item.summary.reference)

    def test_lock_and_idle_expiry_drop_key_state_and_rotate_epoch(self):
        self.add_login()
        first = self.vault.status().unlock_epoch
        self.now += 899
        self.vault.list_items()  # Agent use does not extend the owner timer.
        self.now += 2
        self.assert_code(Code.LOCKED, self.vault.list_items)
        self.assertIsNone(self.vault._crypto)
        self.assertIsNone(self.vault._key_tag)
        self.assertIsNone(self.vault.status().unlock_epoch)
        self.vault.unlock()
        self.assertNotEqual(first, self.vault.status().unlock_epoch)
        self.now += 800
        self.vault.owner_activity()
        self.now += 800
        self.assertEqual(self.vault.status().state, VaultState.READY)
        self.vault.lock()  # Host sleep/OS-lock/app-exit use the same hook.
        self.assertIsNone(self.vault._crypto)

    def test_timer_locks_without_a_subsequent_api_call(self):
        import time

        self.vault.close()
        vault = self.make_vault(idle_seconds=0.03, clock=time.monotonic)
        vault.unlock()
        timer = vault._timer
        timer.join(2)
        self.assertIsNone(vault._crypto)
        self.assertEqual(vault._state, VaultState.LOCKED)

    def test_backend_failure_while_unlocked_fails_closed(self):
        self.keys.fail = True
        self.assert_code(Code.BACKEND_UNAVAILABLE, self.vault.list_items)
        self.assertEqual(self.vault.status().state, VaultState.UNAVAILABLE)
        self.assertIsNone(self.vault._crypto)
        self.keys.fail = False
        self.vault.unlock()
        self.assertEqual(self.vault.status().state, VaultState.READY)

    def test_ciphertext_corruption_and_wrong_keys_are_preserved(self):
        self.add_login()
        original_key = self.keys.keys[self.profile.scope]
        self.vault.lock()
        self.keys.keys[self.profile.scope] = Secret(Fernet.generate_key())
        before = self.vault.store.path.read_bytes()
        self.assert_code(Code.UNREADABLE, self.vault.unlock)
        self.assertEqual(before, self.vault.store.path.read_bytes())
        self.keys.keys[self.profile.scope] = original_key
        self.vault.unlock()
        with closing(sqlite3.connect(self.vault.store.path)) as connection, connection:
            connection.execute("UPDATE vault SET current=?", (b"corrupted",))
        before = self.vault.store.path.read_bytes()
        self.assert_code(Code.UNREADABLE, self.vault.list_items)
        self.assert_code(Code.ALREADY_EXISTS, self.vault.initialize)
        self.assertEqual(before, self.vault.store.path.read_bytes())

    def test_missing_or_invalid_database_is_not_reset(self):
        self.vault.lock()
        self.vault.store.path.unlink()
        self.assert_code(Code.UNREADABLE, self.vault.unlock)
        self.assert_code(Code.UNREADABLE, self.vault.initialize)
        self.assertFalse(self.vault.store.path.exists())
        self.vault.store.path.write_bytes(b"not a sqlite database")
        self.assert_code(Code.UNREADABLE, self.vault.unlock)
        self.assert_code(Code.UNREADABLE, self.vault.initialize)
        self.assertEqual(self.vault.store.path.read_bytes(), b"not a sqlite database")

    def test_empty_existing_schema_is_corrupt_not_a_new_vault(self):
        self.vault.lock()
        with closing(sqlite3.connect(self.vault.store.path)) as connection, connection:
            connection.execute("DELETE FROM vault")
        created = self.keys.created
        self.assert_code(Code.UNREADABLE, self.vault.initialize)
        self.assertEqual(created, self.keys.created)

    def test_failed_transaction_preserves_current_and_previous_snapshot(self):
        item = self.add_login()
        real_write = SnapshotStore.write
        before = self.vault.store.path.read_bytes()

        def fail_after_write(connection, encrypted):
            real_write(connection, encrypted)
            raise OSError("synthetic disk failure")

        with patch.object(SnapshotStore, "write", side_effect=fail_after_write):
            self.assert_code(
                Code.IO,
                lambda: self.vault.update(
                    item.summary.reference, fields=Secret({"password": "replacement"})
                ),
            )
        self.assertEqual(self.vault.store.path.read_bytes(), before)
        self.vault.unlock()
        self.assertEqual(self.vault.list_items()[0].summary.reference.version, 1)
        self.assertEqual(
            self.document()["items"][0]["fields"]["password"], "seeded-password\nline2"
        )

    def test_failed_initial_save_reuses_key_on_explicit_retry(self):
        other = self.make_vault(
            profile=replace(
                self.profile, scope=VaultScope(self.owner.owner_id, uuid4())
            )
        )
        with patch.object(SnapshotStore, "write", side_effect=OSError("synthetic")):
            self.assert_code(Code.IO, other.initialize)
        created = self.keys.created
        other.initialize()
        self.assertEqual(created, self.keys.created)
        self.assertEqual(other.list_items(), ())

    def test_diagnostic_tracebacks_redact_fields_and_backend_errors(self):
        from loguru import logger

        messages = []
        fields = Secret({"api_key": "synthetic-trace-secret"})
        backend_error = Secret("synthetic-hidden-backend-message")

        def reject_write(connection, encrypted):
            raise OSError(backend_error.reveal())

        sink = logger.add(messages.append, diagnose=True, backtrace=True)
        try:
            with patch.object(SnapshotStore, "write", side_effect=reject_write):
                try:
                    self.vault.create(
                        CredentialKind.API_KEY, "provider", "Account", fields
                    )
                except VaultError:
                    logger.exception("Synthetic vault failure")
        finally:
            logger.remove(sink)
        output = "".join(messages)
        self.assertIn(Code.IO.value, output)
        self.assertNotIn(fields.reveal()["api_key"], output)
        self.assertNotIn(backend_error.reveal(), output)

    def test_independent_instances_serialize_writes_without_lost_items(self):
        def writer(index):
            vault = self.make_vault()
            try:
                vault.unlock()
                return vault.create(
                    CredentialKind.API_KEY,
                    "provider",
                    str(index),
                    Secret({"api_key": "synthetic-concurrent-key"}),
                )
            finally:
                vault.close()

        with ThreadPoolExecutor(max_workers=6) as workers:
            results = list(workers.map(writer, range(18)))
        self.assertEqual(len(self.vault.list_items()), 18)
        self.assertEqual(
            len({item.summary.reference.credential_id for item in results}), 18
        )

    def test_every_persisted_file_contains_only_encrypted_source_data(self):
        self.add_login()
        self.vault.create(
            CredentialKind.API_KEY,
            "provider",
            "Account",
            Secret({"api_key": "seeded-api-key"}),
        )
        forbidden = (
            b"seeded-password",
            b"seeded-api-key",
            b"synthetic@example.test",
            self.keys.keys[self.profile.scope].reveal(),
        )
        for path in self.root.rglob("*"):
            if path.is_file():
                for value in forbidden:
                    self.assertNotIn(value, path.read_bytes())
        with closing(sqlite3.connect(self.vault.store.path)) as connection, connection:
            previous = connection.execute("SELECT previous FROM vault").fetchone()[0]
        decoded = Fernet(self.keys.keys[self.profile.scope].reveal()).decrypt(previous)
        self.assertEqual(len(json.loads(decoded)["items"]), 1)

    @unittest.skipUnless(os.name == "nt", "Windows ACL test")
    def test_windows_dacl_has_no_other_user_or_inherited_access(self):
        import win32security

        for path in (self.root, self.vault.store.directory, self.vault.store.path):
            descriptor = win32security.GetFileSecurity(
                str(path), win32security.DACL_SECURITY_INFORMATION
            )
            self.assertTrue(descriptor.GetSecurityDescriptorControl()[0] & 0x1000)
            acl = descriptor.GetSecurityDescriptorDacl()
            allowed = {
                win32security.ConvertSidToStringSid(acl.GetAce(index)[2])
                for index in range(acl.GetAceCount())
            }
            self.assertEqual(allowed, {"S-1-3-4", "S-1-5-18"})  # OWNER RIGHTS, SYSTEM

    def test_existing_token_and_session_files_are_never_touched(self):
        legacy = Path(self.temp.name) / ".credentials"
        legacy.mkdir()
        tokens = legacy / "gmail.accounts.json"
        tokens.write_bytes(b'{"access_token":"synthetic-existing-token"}')
        session = legacy / "browser-profile"
        session.mkdir()
        cookies = session / "Cookies"
        cookies.write_bytes(b"synthetic-existing-cookie-db")
        before = {path: path.read_bytes() for path in (tokens, cookies)}
        item = self.add_login()
        self.vault.delete(item.summary.reference)
        self.vault.lock()
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_invalid_inputs_and_origins_never_change_snapshot(self):
        before = self.vault.store.path.read_bytes()
        invalid = (
            lambda: self.vault.create(
                CredentialKind.API_KEY, "p", "a", Secret({"api_key": ""})
            ),
            lambda: self.vault.create(
                CredentialKind.LOGIN, "p", "a", Secret({"password": "p"})
            ),
            lambda: self.vault.create(
                CredentialKind.LOGIN,
                "p",
                "a",
                Secret({"username": "u", "password": "p"}),
            ),
        )
        for operation in invalid:
            self.assert_code(Code.INVALID, operation)
        for origin in (
            "http://example.test",
            "https://u:p@example.test",
            "https://example.test/login",
            "https://example.test?q=secret",
            "https://example.test/#fragment",
            "https://example.test\\@evil.test",
            "https://example.test:0",
        ):
            self.assert_code(
                Code.INVALID,
                lambda: self.vault.create(
                    CredentialKind.LOGIN,
                    "p",
                    "a",
                    Secret({"username": "u", "password": "p"}),
                    allowed_origins=(origin,),
                ),
            )
        self.assertEqual(before, self.vault.store.path.read_bytes())

    def test_valid_ciphertext_with_wrong_scope_or_unknown_format_is_rejected(self):
        self.add_login()
        document = self.document()
        for update in (
            {"profile_id": str(uuid4())},
            {"owner_id": str(uuid4())},
            {"os_identity": "test-os:foreign"},
            {"format": 2},
            {"unexpected": "field"},
        ):
            changed = {**document, **update}
            encrypted = Fernet(self.keys.keys[self.profile.scope].reveal()).encrypt(
                json.dumps(changed).encode()
            )
            with (
                closing(sqlite3.connect(self.vault.store.path)) as connection,
                connection,
            ):
                connection.execute("UPDATE vault SET current=?", (encrypted,))
            self.assert_code(Code.UNREADABLE, self.vault.unlock)

    @unittest.skipIf(os.name == "nt", "POSIX access-mode test")
    def test_posix_file_access_is_owner_only(self):
        self.assertEqual(self.vault.store.path.stat().st_mode & 0o777, 0o600)
        for directory in (
            self.root,
            self.vault.store.directory.parent,
            self.vault.store.directory,
        ):
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)

    def test_symlinked_snapshot_is_rejected(self):
        self.vault.lock()
        other = Path(self.temp.name) / "outside"
        other.write_bytes(b"untouched")
        self.vault.store.path.unlink()
        try:
            self.vault.store.path.symlink_to(other)
        except OSError:
            self.skipTest("Symlink creation is unavailable")
        self.assert_code(Code.IO, self.vault.unlock)
        self.assertEqual(other.read_bytes(), b"untouched")
