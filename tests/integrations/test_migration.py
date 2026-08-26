"""Account-store behaviour around the identity sentinel.

UNIDENTIFIED is not about the old credential FILE (that format was
removed on 2026-08-26) — it is the sentinel for a credential whose
``identity_of()`` returns None, which fresh connects hit too (LinkedIn and
Notion tokens carry no stable id). The contract under test is that the
first re-auth which DOES yield an identity upgrades the sentinel record in
place instead of creating a duplicate account.
"""

from __future__ import annotations


from craftos_integrations.contracts import UNIDENTIFIED
from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem

from .conftest import cred


def test_reauth_upgrades_sentinel_in_place_never_duplicates(mgr, tmp_path):
    # A sentinel account can still exist (e.g. an identity-less OAuth
    # success, or a migrated credential without a derivable identity);
    # seed one directly.
    mgr.upsert_account("linkedin", UNIDENTIFIED, {"access_token": "old"})
    mgr.set_alias("linkedin", UNIDENTIFIED, "me")
    mgr.set_listening("linkedin", UNIDENTIFIED, False)

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
# System-level account handling
# ════════════════════════════════════════════════════════════════════════


def _system(tmp_path):
    from .test_system import FakeProvider

    return IntegrationSystem(
        store=FileCredentialStore(root=tmp_path),
        providers=[FakeProvider("gmail")],
    )


