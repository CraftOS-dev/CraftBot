"""Synthetic source documents only; never inspect a user's Settings or tokens."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from uuid import uuid4

from app.credentials.errors import VaultError
from app.credentials.identity import VaultOwner, VaultProfile, VaultScope
from app.credentials.migration import classify_integration, migrate_model_document
from app.credentials.migration import migrate_browser_document
from app.credentials.references import parse
from app.credentials.secrets import Secret
from app.credentials.vault import ProfileVault


class MemoryKeys:
    def __init__(self):
        self.keys = {}

    def load(self, scope):
        return self.keys.get(scope)

    def create(self, scope, value):
        self.keys[scope] = value


class ModelMigrationTests(unittest.TestCase):
    def test_browser_import_preserves_stable_ids_without_disclosing_login_fields(self):
        document = Secret(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "legacy-id",
                        "site": "example.test",
                        "username": "private-login-name",
                        "password": "synthetic-browser-secret",
                        "label": "Work",
                    }
                ],
            }
        )
        mapping = migrate_browser_document(self.vault, "browser-source", document)
        retry = migrate_browser_document(self.vault, "browser-source", document)
        self.assertEqual(mapping, retry)
        self.assertEqual(len(self.vault.list_items()), 1)
        self.assertNotIn("private-login-name", repr(self.vault.list_items()))
        self.assertNotIn("synthetic-browser-secret", repr(mapping))
        broken = Secret({"version": 1, "entries": document.reveal()["entries"] * 2})
        with self.assertRaises(VaultError):
            migrate_browser_document(self.vault, "browser-source", broken)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        owner = VaultOwner(uuid4(), "test-os:migration")
        self.vault = ProfileVault(
            Path(self.temp.name),
            owner,
            VaultProfile(VaultScope(owner.owner_id, uuid4()), "Work"),
            key_store=MemoryKeys(),
            verifier=Mock(verify=Mock(return_value=None)),
        )
        self.vault.initialize()

    def tearDown(self):
        self.vault.close()
        self.temp.cleanup()

    def test_model_pool_retirement_preserves_token_and_session_fields_exactly(self):
        document = Secret(
            {
                "api_keys": {"openai": "synthetic-primary"},
                "extra_api_keys": {"openai": ["synthetic-secondary"]},
                "session_id": "derived-session-id",
                "subscription": {
                    "access_token": "derived-access",
                    "refresh_token": "derived-refresh",
                },
            }
        )
        commit = Mock()
        result = migrate_model_document(
            self.vault, "synthetic-source", document, commit
        )
        migrated = commit.call_args.args[0].reveal()
        self.assertEqual(result.imported, 2)
        self.assertEqual(migrated["subscription"], document.reveal()["subscription"])
        self.assertEqual(migrated["session_id"], document.reveal()["session_id"])
        self.assertEqual(
            parse(migrated["api_keys"]["openai"]).profile_id,
            self.vault.profile.scope.profile_id,
        )
        self.assertNotIn("synthetic-primary", repr(migrated))
        self.assertEqual(document.reveal()["api_keys"]["openai"], "synthetic-primary")
        second = Mock()
        retry = migrate_model_document(
            self.vault, "synthetic-source", Secret(migrated), second
        )
        self.assertEqual((retry.imported, retry.retained_references), (0, 2))
        self.assertEqual(len(self.vault.list_items()), 2)

    def test_interrupted_commit_reuses_ids_and_refuses_changed_source(self):
        document = Secret({"api_keys": {"openai": "synthetic-source-A"}})
        with self.assertRaises(VaultError):
            migrate_model_document(
                self.vault,
                "same-source",
                document,
                Mock(side_effect=OSError("interrupted")),
            )
        existing = self.vault.list_items()[0].summary.reference
        commit = Mock()
        migrate_model_document(self.vault, "same-source", document, commit)
        self.assertEqual(self.vault.list_items()[0].summary.reference, existing)
        with self.assertRaises(VaultError):
            migrate_model_document(
                self.vault,
                "same-source",
                Secret({"api_keys": {"openai": "changed-source"}}),
                commit,
            )
        self.assertEqual(len(self.vault.list_items()), 1)

    def test_unknown_or_ambiguous_sources_abort_before_retirement(self):
        for document in (
            {"api_keys": {"unknown": "source-value"}},
            {"api_keys": {"openai": "valid"}, "extra_api_keys": {"openai": "bad-pool"}},
            {
                "endpoints": {"aws_region": "unsupported-region"},
                "aws_credentials": {
                    "access_key_id": "static-id",
                    "secret_access_key": "static-secret",
                },
            },
        ):
            commit = Mock()
            with self.subTest(document=document), self.assertRaises(VaultError):
                migrate_model_document(self.vault, "source", Secret(document), commit)
            commit.assert_not_called()
            self.assertEqual(self.vault.list_items(), ())

    def test_static_aws_migration_retires_only_source_pair_and_preserves_sessions(self):
        document = Secret(
            {
                "aws_credentials": {
                    "access_key_id": "SYNTHETICACCESSKEY123",
                    "secret_access_key": "SyntheticSigningSecret1234567890",
                    "note": "non-secret setting",
                },
                "endpoints": {"aws_region": "us-east-1"},
                "session_id": "existing-session",
            }
        )
        commit = Mock()
        result = migrate_model_document(self.vault, "aws-source", document, commit)
        migrated = commit.call_args.args[0].reveal()
        self.assertEqual(result.imported, 1)
        self.assertEqual(migrated["aws_credentials"]["auth_mode"], "vault")
        parse(migrated["aws_credentials"]["source_reference"])
        self.assertNotIn("access_key_id", migrated["aws_credentials"])
        self.assertNotIn("secret_access_key", migrated["aws_credentials"])
        self.assertEqual(migrated["session_id"], "existing-session")
        self.assertEqual(migrated["aws_credentials"]["note"], "non-secret setting")
        temporary = Secret(
            {
                "aws_credentials": {
                    "access_key_id": "derived-id",
                    "secret_access_key": "derived-secret",
                    "session_token": "derived-session",
                }
            }
        )
        commit = Mock()
        result = migrate_model_document(
            self.vault, "temporary-source", temporary, commit
        )
        self.assertEqual(result.imported, 0)
        self.assertEqual(commit.call_args.args[0].reveal(), temporary.reveal())

    def test_classification_does_not_treat_access_token_field_as_provenance(self):
        self.assertEqual(
            classify_integration(
                "figma", {"access_token": "same-field", "auth_kind": "pat"}
            ),
            "source",
        )
        self.assertEqual(
            classify_integration(
                "figma", {"access_token": "same-field", "auth_kind": "oauth"}
            ),
            "derived",
        )
        self.assertEqual(
            classify_integration("slack", {"bot_token": "ambiguous"}), "review_required"
        )
        self.assertEqual(
            classify_integration("gmail", {"access_token": "generated"}), "derived"
        )
