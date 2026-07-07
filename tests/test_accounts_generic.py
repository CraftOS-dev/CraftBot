# -*- coding: utf-8 -*-
"""Generic multi-account layer (craftos_integrations/accounts.py) — tested
against a synthetic credential shape (not Gmail's) to prove it's genuinely
integration-agnostic, not accidentally coupled to an `email` field.
"""

from dataclasses import dataclass

import pytest

from craftos_integrations.config import ConfigStore
from craftos_integrations import credentials_store as cs
from craftos_integrations import accounts as acc
from craftos_integrations import registry


@pytest.fixture(autouse=True)
def isolated_credentials_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)
    registry.reset()
    yield


@dataclass
class FakeCredential:
    """Stand-in for a non-Google integration's credential — identity lives
    in `workspace_id`, nothing here is named `email`."""

    token: str = ""
    workspace_id: str = ""


STEM = "fakeplatform"
PLATFORM_ID = "fake"


def identity_of(cred: FakeCredential) -> str:
    return cred.workspace_id


def _cred(workspace_id: str) -> FakeCredential:
    return FakeCredential(token="tok", workspace_id=workspace_id)


# ── list / resolve ────────────────────────────────────────────────────────


def test_list_accounts_primary_first_then_secondaries():
    cs.save_credential(f"{STEM}.json", _cred("T-primary"))
    cs.save_credential(cs.account_filename(STEM, "T-second"), _cred("T-second"))

    accounts = acc.list_accounts(PLATFORM_ID, STEM, FakeCredential, identity_of)
    assert [a.identity for a in accounts] == ["T-primary", "T-second"]
    assert accounts[0].is_primary and not accounts[1].is_primary


def test_resolve_account_exact_substring_ambiguous_not_found():
    cs.save_credential(f"{STEM}.json", _cred("acme-corp"))
    cs.save_credential(cs.account_filename(STEM, "acme-personal"), _cred("acme-personal"))

    # default -> primary
    fname, err = acc.resolve_account(PLATFORM_ID, STEM, FakeCredential, identity_of, None, "Fake")
    assert err is None and fname == f"{STEM}.json"

    # exact
    fname, err = acc.resolve_account(
        PLATFORM_ID, STEM, FakeCredential, identity_of, "acme-personal", "Fake"
    )
    assert err is None and fname == cs.account_filename(STEM, "acme-personal")

    # ambiguous substring (both contain "acme")
    fname, err = acc.resolve_account(
        PLATFORM_ID, STEM, FakeCredential, identity_of, "acme", "Fake"
    )
    assert fname is None and "acme-corp" in err and "acme-personal" in err

    # not found
    fname, err = acc.resolve_account(
        PLATFORM_ID, STEM, FakeCredential, identity_of, "nope", "Fake"
    )
    assert fname is None and "acme-corp" in err and "acme-personal" in err


# ── alias ─────────────────────────────────────────────────────────────────


def test_alias_set_get_remove_and_resolve_by_alias():
    cs.save_credential(f"{STEM}.json", _cred("T-primary"))
    acc.set_alias(PLATFORM_ID, "T-primary", "Work")

    assert acc.get_alias(PLATFORM_ID, "T-primary") == "Work"

    accounts = acc.list_accounts(PLATFORM_ID, STEM, FakeCredential, identity_of)
    assert accounts[0].display == "Work"

    # resolves by alias, case-insensitive
    fname, err = acc.resolve_account(PLATFORM_ID, STEM, FakeCredential, identity_of, "work", "Fake")
    assert err is None and fname == f"{STEM}.json"

    # empty alias clears it
    acc.set_alias(PLATFORM_ID, "T-primary", "")
    assert acc.get_alias(PLATFORM_ID, "T-primary") is None

    acc.set_alias(PLATFORM_ID, "T-primary", "Personal")
    acc.remove_alias(PLATFORM_ID, "T-primary")
    assert acc.get_alias(PLATFORM_ID, "T-primary") is None


# ── resolve_save_target (login/invite placement) ──────────────────────────


def test_resolve_save_target_fills_primary_then_allocates_secondary_then_updates_existing():
    # nothing connected -> primary
    target = acc.resolve_save_target(STEM, FakeCredential, identity_of, "T-a")
    assert target == f"{STEM}.json"
    cs.save_credential(target, _cred("T-a"))

    # different identity -> new secondary
    target = acc.resolve_save_target(STEM, FakeCredential, identity_of, "T-b")
    assert target == cs.account_filename(STEM, "T-b")
    cs.save_credential(target, _cred("T-b"))

    # same identity as primary -> update in place, no third file
    target = acc.resolve_save_target(STEM, FakeCredential, identity_of, "T-a")
    assert target == f"{STEM}.json"
    assert len(acc.list_accounts(PLATFORM_ID, STEM, FakeCredential, identity_of)) == 2


# ── remove_account (promotes a secondary when primary is removed) ────────


def test_remove_account_promotes_secondary_when_primary_removed():
    cs.save_credential(f"{STEM}.json", _cred("T-a"))
    cs.save_credential(cs.account_filename(STEM, "T-b"), _cred("T-b"))

    acc.remove_account(STEM, f"{STEM}.json")

    accounts = acc.list_accounts(PLATFORM_ID, STEM, FakeCredential, identity_of)
    assert len(accounts) == 1
    assert accounts[0].identity == "T-b"
    assert accounts[0].is_primary
    assert accounts[0].filename == f"{STEM}.json"  # promoted into the bare file


def test_remove_account_last_one_leaves_nothing_connected():
    cs.save_credential(f"{STEM}.json", _cred("T-a"))
    acc.remove_account(STEM, f"{STEM}.json")
    assert acc.list_accounts(PLATFORM_ID, STEM, FakeCredential, identity_of) == []


# ── promote_to_primary (explicit "set primary" swap) ──────────────────────


def test_promote_to_primary_swaps_contents_and_preserves_both_accounts():
    cs.save_credential(f"{STEM}.json", _cred("T-a"))
    secondary_file = cs.account_filename(STEM, "T-b")
    cs.save_credential(secondary_file, _cred("T-b"))

    ok = acc.promote_to_primary(STEM, secondary_file)
    assert ok

    accounts = acc.list_accounts(PLATFORM_ID, STEM, FakeCredential, identity_of)
    by_identity = {a.identity: a for a in accounts}
    assert len(accounts) == 2
    assert by_identity["T-b"].is_primary and by_identity["T-b"].filename == f"{STEM}.json"
    assert not by_identity["T-a"].is_primary

    # promoting the already-primary account is a no-op
    assert acc.promote_to_primary(STEM, f"{STEM}.json") is False
