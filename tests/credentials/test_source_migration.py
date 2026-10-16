"""Only synthetic offline account/env documents; no ConfigStore or live paths."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from uuid import uuid4

from app.credentials.identity import VaultOwner, VaultProfile, VaultScope
from app.credentials.migration import (
    migrate_integration_document,
    migrate_environment_document,
)
from app.credentials.references import is_reference
from app.credentials.secrets import Secret
from app.credentials.errors import VaultError
from app.credentials.vault import ProfileVault
from test_migration import MemoryKeys


class SourceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        owner = VaultOwner(uuid4(), "test-os:source-migration")
        self.vault = ProfileVault(
            Path(self.temporary.name),
            owner,
            VaultProfile(VaultScope(owner.owner_id, uuid4()), "Work"),
            key_store=MemoryKeys(),
            verifier=Mock(verify=Mock(return_value=None)),
        )
        self.addCleanup(self.vault.close)
        self.vault.initialize()

    def document(self, **credentials):
        return Secret(
            {
                "version": 2,
                "primary": next(iter(credentials)),
                "accounts": {
                    identity: {
                        "credential": data,
                        "alias": identity + "-alias",
                        "listen": True,
                        "added_at": "original",
                    }
                    for identity, data in credentials.items()
                },
            }
        )

    def test_only_classified_manual_fields_retire_and_account_controls_stay(self):
        document = self.document(
            manual={
                "auth_kind": "pat",
                "access_token": "synthetic-source-key",
                "session_id": "existing-session",
            },
            oauth={
                "auth_kind": "oauth",
                "access_token": "generated-access",
                "refresh_token": "generated-refresh",
                "expires_at": 123,
            },
        )
        before, committed = copy.deepcopy(document.reveal()), []
        outcome = migrate_integration_document(
            self.vault, "account-file", "figma", document, committed.append
        )
        result = committed[0].reveal()
        self.assertEqual(outcome.imported, 1)
        self.assertEqual(outcome.retained_derived, 1)
        self.assertEqual(document.reveal(), before)
        self.assertEqual(result["accounts"]["oauth"], before["accounts"]["oauth"])
        manual = result["accounts"]["manual"]
        self.assertEqual(manual["credential"]["session_id"], "existing-session")
        self.assertTrue(is_reference(manual["credential"]["source_reference"]))
        self.assertNotIn("access_token", manual["credential"])
        self.assertEqual(
            {k: v for k, v in manual.items() if k != "credential"},
            {
                k: v
                for k, v in before["accounts"]["manual"].items()
                if k != "credential"
            },
        )
        self.assertNotIn("synthetic-source-key", str(result))

    def test_ambiguous_provenance_needs_explicit_selection_and_cannot_override_oauth(
        self,
    ):
        document = self.document(account={"bot_token": "synthetic-slack-source"})
        result = []
        outcome = migrate_integration_document(
            self.vault, "slack-file", "slack", document, result.append
        )
        self.assertEqual((outcome.imported, outcome.review_required), (0, 1))
        self.assertEqual(result[0].reveal(), document.reveal())
        selected = []
        outcome = migrate_integration_document(
            self.vault,
            "slack-file",
            "slack",
            document,
            selected.append,
            source_accounts=("account",),
        )
        self.assertEqual(outcome.imported, 1)
        with self.assertRaises(VaultError):
            migrate_integration_document(
                self.vault,
                "oauth-file",
                "slack",
                self.document(
                    account={"bot_token": "generated", "refresh_token": "refresh"}
                ),
                Mock(),
                source_accounts=("account",),
            )

    def test_oauth_client_secret_moves_but_generated_account_has_no_source_binding(
        self,
    ):
        document = self.document(
            account={
                "access_token": "existing-access",
                "refresh_token": "existing-refresh",
                "client_id": "public-client",
                "client_secret": "synthetic-client-secret",
                "session_id": "session",
            }
        )
        results = []
        outcome = migrate_integration_document(
            self.vault, "gmail-file", "gmail", document, results.append
        )
        data = results[0].reveal()["accounts"]["account"]["credential"]
        self.assertEqual(outcome.imported, 1)
        self.assertTrue(is_reference(data["client_secret"]))
        self.assertNotIn("source_reference", data)
        self.assertEqual(
            {k: v for k, v in data.items() if k != "client_secret"},
            {
                k: v
                for k, v in document.reveal()["accounts"]["account"][
                    "credential"
                ].items()
                if k != "client_secret"
            },
        )
        self.assertEqual(
            self.vault.list_items()[0].allowed_origins,
            ("https://oauth2.googleapis.com",),
        )

    def test_commit_failure_reuses_verified_ids_on_retry_and_changed_source_aborts(
        self,
    ):
        document = self.document(account={"api_key": "synthetic-stripe-source"})
        with self.assertRaises(VaultError):
            migrate_integration_document(
                self.vault,
                "stripe-file",
                "stripe",
                document,
                Mock(side_effect=OSError()),
            )
        first = self.vault.list_items()[0].summary.reference
        results = []
        migrate_integration_document(
            self.vault, "stripe-file", "stripe", document, results.append
        )
        self.assertEqual(self.vault.list_items()[0].summary.reference, first)
        with self.assertRaises(VaultError):
            migrate_integration_document(
                self.vault,
                "stripe-file",
                "stripe",
                self.document(account={"api_key": "changed-source"}),
                Mock(),
            )

    def test_tenant_migration_requires_origin_from_reviewed_installation(self):
        document = self.document(
            account={
                "domain": "tenant.atlassian.net",
                "email": "private-user@example.test",
                "api_token": "synthetic-jira-source",
            }
        )
        with self.assertRaises(VaultError):
            migrate_integration_document(
                self.vault,
                "jira-file",
                "jira",
                document,
                Mock(),
                source_accounts=("account",),
            )
        self.assertEqual(self.vault.list_items(), ())
        results = []
        migrate_integration_document(
            self.vault,
            "jira-file",
            "jira",
            document,
            results.append,
            source_accounts=("account",),
            helper_catalog=[
                {
                    "helper": "integration_jira",
                    "endpoint": "https://tenant.atlassian.net/rest/api/3/myself",
                }
            ],
        )
        self.assertNotIn(
            "email", results[0].reveal()["accounts"]["account"]["credential"]
        )

    def test_environment_conversion_preserves_other_lines_tokens_sessions_and_crlf(
        self,
    ):
        original = '# keep comment\r\nOPENAI_API_KEY="synthetic-model-key"\r\nGOOGLE_CLIENT_SECRET=synthetic-client-secret\r\nACCESS_TOKEN=generated-token\r\nSESSION_ID=existing-session\r\nOTHER_SETTING=original\r\n'
        results = []
        outcome = migrate_environment_document(
            self.vault, "env-file", Secret(original), results.append
        )
        text = results[0].reveal()
        self.assertEqual(outcome.imported, 2)
        self.assertEqual(text.count("craftbot-vault://"), 2)
        self.assertNotIn("synthetic-model-key", text)
        self.assertNotIn("synthetic-client-secret", text)
        self.assertEqual(
            text.splitlines(keepends=True)[3:], original.splitlines(keepends=True)[3:]
        )
        self.assertEqual(text.count("\r\n"), original.count("\r\n"))
        again = []
        outcome = migrate_environment_document(
            self.vault, "env-file", Secret(text), again.append
        )
        self.assertEqual(outcome.imported, 0)
        self.assertEqual(again[0].reveal(), text)

    def test_duplicate_and_dynamic_environment_sources_abort_before_any_import(self):
        for raw in (
            "OPENAI_API_KEY=first\nOPENAI_API_KEY=second\n",
            "OPENAI_API_KEY=${OTHER_KEY}\n",
            "OPENAI_API_KEY=$(command)\n",
        ):
            with self.subTest(raw=raw), self.assertRaises(VaultError):
                migrate_environment_document(
                    self.vault, "env-file", Secret(raw), Mock()
                )
            self.assertEqual(self.vault.list_items(), ())

    def test_environment_bom_and_quoted_comments_survive_and_unknown_sources_report_review(
        self,
    ):
        text = '\ufeffexport XAI_API_KEY="synthetic-x-key" # keep comment\r\nCUSTOM_API_KEY=unmigrated-custom-source\r\nSESSION_TOKEN=existing\r\n'
        committed = []
        result = migrate_environment_document(
            self.vault, "env-file", Secret(text), committed.append
        )
        self.assertEqual((result.imported, result.review_required), (1, 1))
        self.assertTrue(
            committed[0]
            .reveal()
            .startswith('\ufeffexport XAI_API_KEY="craftbot-vault://')
        )
        self.assertIn(" # keep comment\r\n", committed[0].reveal())
        self.assertEqual(
            committed[0].reveal().splitlines(keepends=True)[1:],
            text.splitlines(keepends=True)[1:],
        )
