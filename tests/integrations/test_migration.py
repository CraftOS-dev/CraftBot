"""The one-time legacy upgrade migration, and sentinel upgrade on re-auth.

AccountManager itself never reads pre-multi-account single-credential files — the
migration lives one layer up, in ``IntegrationSystem._migrate_legacy``:
a legacy file with NO AccountSet document (a user upgrading from ≤ V1.4.2)
is imported as the first account, with a provider-derived identity
(LEGACY sentinel if the credential predates identity capture). Once the
document exists the legacy file is never consulted again, and removing the
last account deletes the legacy file too — so a disconnect can never be
resurrected by the migration.
"""

from __future__ import annotations

import json

from craftos_integrations.contracts import LEGACY_IDENTITY
from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem

from .conftest import cred


def _write_legacy(tmp_path, pid, payload):
    (tmp_path / f"{pid}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_legacy_file_alone_is_ignored(mgr, tmp_path):
    _write_legacy(tmp_path, "notion", {"token": "secret"})
    assert mgr.list_accounts("notion") == []
    assert mgr.load_set("notion") is None


def test_ignoring_legacy_leaves_the_file_untouched(mgr, tmp_path):
    _write_legacy(tmp_path, "notion", {"token": "secret"})
    mgr.list_accounts("notion")
    assert (tmp_path / "notion.json").exists()
    assert json.loads((tmp_path / "notion.json").read_text()) == {
        "token": "secret"
    }


def test_reauth_upgrades_sentinel_in_place_never_duplicates(mgr, tmp_path):
    # A sentinel account can still exist (e.g. an identity-less OAuth
    # success, or a migrated credential without a derivable identity);
    # seed one directly.
    mgr.upsert_account("linkedin", LEGACY_IDENTITY, {"access_token": "old"})
    mgr.set_alias("linkedin", LEGACY_IDENTITY, "me")
    mgr.set_listening("linkedin", LEGACY_IDENTITY, False)

    stored = mgr.upsert_account("linkedin", "A@Corp.com", cred("a@corp.com"))

    assert stored == "a@corp.com"
    accounts = mgr.list_accounts("linkedin")
    assert [a.identity for a in accounts] == ["a@corp.com"]  # no duplicate
    upgraded = accounts[0]
    assert upgraded.is_primary
    assert upgraded.alias == "me"  # alias survived the upgrade
    assert upgraded.listen is False  # listen flag survived
    assert mgr.credential_for("linkedin", "a@corp.com")["access_token"] == "tok-a@corp.com"


def test_upsert_refuses_empty_identity(mgr):
    import pytest

    with pytest.raises(ValueError, match="unaddressable"):
        mgr.upsert_account("gmail", "", cred("x"))
    with pytest.raises(ValueError, match="unaddressable"):
        mgr.upsert_account("gmail", None, cred("x"))


def test_no_legacy_no_v2_reads_as_disconnected(mgr):
    assert mgr.list_accounts("gmail") == []
    assert mgr.load_set("gmail") is None


# ════════════════════════════════════════════════════════════════════════
# System-level one-time migration (IntegrationSystem._migrate_legacy)
# ════════════════════════════════════════════════════════════════════════


def _system(tmp_path):
    from .test_system import FakeProvider

    return IntegrationSystem(
        store=FileCredentialStore(root=tmp_path),
        providers=[FakeProvider("gmail")],
    )


def test_system_migrates_legacy_file_on_first_load(tmp_path):
    _write_legacy(tmp_path, "gmail", cred("old@x.com"))
    system = _system(tmp_path)
    accounts = system.list_accounts("gmail")
    assert [a.identity for a in accounts] == ["old@x.com"]  # real identity
    assert accounts[0].is_primary
    assert (tmp_path / "gmail.accounts.json").exists()
    # The legacy file is left in place until disconnect — but is never
    # consulted again once the document exists:
    _write_legacy(tmp_path, "gmail", cred("intruder@x.com"))
    assert [a.identity for a in system.list_accounts("gmail")] == ["old@x.com"]


def test_system_migrates_identityless_credential_to_sentinel(tmp_path):
    _write_legacy(tmp_path, "gmail", {"access_token": "tok"})  # no email
    system = _system(tmp_path)
    assert [a.identity for a in system.list_accounts("gmail")] == [LEGACY_IDENTITY]


def test_disconnect_after_migration_deletes_legacy_and_never_resurrects(tmp_path):
    _write_legacy(tmp_path, "gmail", cred("old@x.com"))
    system = _system(tmp_path)
    assert [a.identity for a in system.list_accounts("gmail")] == ["old@x.com"]

    system.remove_account("gmail", "old@x.com")

    assert not (tmp_path / "gmail.accounts.json").exists()  # document gone
    assert not (tmp_path / "gmail.json").exists()  # legacy file gone too
    # ...so the migration has nothing to re-import: no resurrection.
    assert system.list_accounts("gmail") == []
    assert not (tmp_path / "gmail.accounts.json").exists()


def test_batch_disconnect_all_also_deletes_legacy(tmp_path):
    _write_legacy(tmp_path, "gmail", cred("old@x.com"))
    system = _system(tmp_path)
    system.list_accounts("gmail")  # migrate

    system.apply_account_changes("gmail", {"disconnect": ["old@x.com"]})

    assert not (tmp_path / "gmail.json").exists()
    assert system.list_accounts("gmail") == []
