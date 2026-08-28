"""Mutations: upsert, remove, primary, listen, aliases (incl. family), batch."""

from __future__ import annotations

import pytest

from craftos_integrations.contracts import AccountResolutionError
from craftos_integrations.core.accounts import AccountManager

from .conftest import _family, cred


# ── upsert ───────────────────────────────────────────────────────────────


def test_first_account_becomes_primary(mgr):
    mgr.upsert_account("gmail", "a@x.com", cred("a@x.com"))
    accounts = mgr.list_accounts("gmail")
    assert accounts[0].is_primary and accounts[0].identity == "a@x.com"


def test_second_account_does_not_steal_primary(two_accounts):
    accounts = two_accounts.list_accounts("gmail")
    assert [a.identity for a in accounts] == ["a@x.com", "b@y.com"]
    assert accounts[0].is_primary and not accounts[1].is_primary


def test_reauth_updates_credential_in_place(two_accounts):
    two_accounts.upsert_account("gmail", "A@X.com", {"access_token": "fresh"})
    accounts = two_accounts.list_accounts("gmail")
    assert len(accounts) == 2  # no duplicate from case difference
    assert two_accounts.credential_for("gmail", "a@x.com") == {"access_token": "fresh"}
    assert accounts[0].alias == "work"  # alias untouched by re-auth


# ── remove ───────────────────────────────────────────────────────────────


def test_remove_secondary(two_accounts):
    two_accounts.remove_account("gmail", "school")
    assert [a.identity for a in two_accounts.list_accounts("gmail")] == ["a@x.com"]


def test_remove_primary_promotes_oldest_remaining(mgr):
    mgr.upsert_account("gmail", "a@x.com", cred("a@x.com"))
    mgr.upsert_account("gmail", "b@y.com", cred("b@y.com"))
    mgr.upsert_account("gmail", "c@z.com", cred("c@z.com"))
    mgr.remove_account("gmail", "a@x.com")
    accounts = mgr.list_accounts("gmail")
    assert accounts[0].identity == "b@y.com"  # oldest remaining
    assert accounts[0].is_primary


def test_remove_last_account_deletes_document(mgr, tmp_path):
    mgr.upsert_account("gmail", "a@x.com", cred("a@x.com"))
    mgr.remove_account("gmail", "a@x.com")
    assert mgr.list_accounts("gmail") == []
    assert not (tmp_path / "gmail.accounts.json").exists()


def test_failed_remove_has_no_side_effects(two_accounts):
    with pytest.raises(AccountResolutionError):
        two_accounts.remove_account("gmail", "nope")
    assert len(two_accounts.list_accounts("gmail")) == 2


# ── primary / listen ─────────────────────────────────────────────────────


def test_set_primary_by_alias(two_accounts):
    two_accounts.set_primary("gmail", "school")
    accounts = two_accounts.list_accounts("gmail")
    assert accounts[0].identity == "b@y.com" and accounts[0].is_primary


def test_listen_defaults_true_and_toggles(two_accounts):
    assert all(a.listen for a in two_accounts.list_accounts("gmail"))
    two_accounts.set_listening("gmail", "school", False)
    by_id = {a.identity: a for a in two_accounts.list_accounts("gmail")}
    assert by_id["b@y.com"].listen is False
    assert by_id["a@x.com"].listen is True


# ── aliases ──────────────────────────────────────────────────────────────


def test_duplicate_alias_rejected(two_accounts):
    with pytest.raises(ValueError, match="already the nickname"):
        two_accounts.set_alias("gmail", "b@y.com", "work")


def test_alias_clear(two_accounts):
    two_accounts.set_alias("gmail", "b@y.com", None)
    by_id = {a.identity: a for a in two_accounts.list_accounts("gmail")}
    assert by_id["b@y.com"].alias is None


def test_alias_propagates_across_google_family(mgr):
    mgr.upsert_account("gmail", "a@x.com", cred("a@x.com"))
    mgr.upsert_account("google_calendar", "a@x.com", cred("a@x.com"))
    mgr.set_alias("gmail", "a@x.com", "work")
    calendar = mgr.list_accounts("google_calendar")
    assert calendar[0].alias == "work"
    assert mgr.resolve("google_calendar", "work") == "a@x.com"


def test_alias_uniqueness_is_family_wide(mgr):
    mgr.upsert_account("gmail", "a@x.com", cred("a@x.com"))
    mgr.upsert_account("google_calendar", "b@y.com", cred("b@y.com"))
    mgr.set_alias("gmail", "a@x.com", "work")
    with pytest.raises(ValueError, match="already the nickname"):
        mgr.set_alias("google_calendar", "b@y.com", "work")


def test_sync_family_aliases_heals_partial_write(mgr, store):
    mgr.upsert_account("gmail", "a@x.com", cred("a@x.com"))
    mgr.upsert_account("google_calendar", "a@x.com", cred("a@x.com"))
    mgr.set_alias("gmail", "a@x.com", "work")
    # Simulate a partial family write: calendar's copy reverted out-of-band
    # to an older alias state.
    raw = store.load("google_calendar")
    raw["accounts"]["a@x.com"]["alias"] = "stale"
    raw["accounts"]["a@x.com"]["alias_updated_at"] = "2020-01-01T00:00:00+00:00"
    store.replace("google_calendar", raw)

    mgr.sync_family_aliases("google_calendar")
    assert mgr.list_accounts("google_calendar")[0].alias == "work"


def test_alias_dies_with_account_and_is_reusable(two_accounts):
    two_accounts.remove_account("gmail", "school")
    two_accounts.upsert_account("gmail", "c@z.com", cred("c@z.com"))
    two_accounts.set_alias("gmail", "c@z.com", "school")  # no leak, no clash
    assert two_accounts.resolve("gmail", "school") == "c@z.com"


# ── batched UI save ──────────────────────────────────────────────────────


def test_apply_changes_runs_in_deterministic_order(mgr):
    mgr.upsert_account("gmail", "a@x.com", cred("a@x.com"))
    mgr.upsert_account("gmail", "b@y.com", cred("b@y.com"))
    mgr.upsert_account("gmail", "c@z.com", cred("c@z.com"))
    result = mgr.apply_changes(
        "gmail",
        {
            "disconnect": ["a@x.com"],  # removes the current primary
            "primary": "c@z.com",  # then explicit primary choice wins
            "aliases": {"c@z.com": "main"},
            "listen": {"b@y.com": False},
        },
    )
    by_id = {a.identity: a for a in result}
    assert set(by_id) == {"b@y.com", "c@z.com"}
    assert by_id["c@z.com"].is_primary and by_id["c@z.com"].alias == "main"
    assert by_id["b@y.com"].listen is False


def test_apply_changes_ui_wire_batch_alias_survives_reopen(store, clock):
    """Regression (Manage-modal alias bug hunt): the EXACT wire shape the
    frontend sends on "Save changes" — empty disconnect list, null primary,
    aliases keyed by identity, empty listen map — must persist the alias so a
    fresh manager over the same store (= closing and reopening the modal)
    still sees it, with alias_updated_at stamped."""
    mgr = AccountManager(store, family_members=_family, clock=clock)
    mgr.upsert_account("gmail", "a@x.com", cred("a@x.com"))
    mgr.upsert_account("gmail", "b@y.com", cred("b@y.com"))

    result = mgr.apply_changes(
        "gmail",
        {"disconnect": [], "primary": None,
         "aliases": {"b@y.com": "jobsearch"}, "listen": {}},
    )
    assert {a.identity: a.alias for a in result} == {
        "a@x.com": None, "b@y.com": "jobsearch",
    }

    # "Reopen": a brand-new manager over the same store, after the family
    # alias sync that every UI list path runs.
    reopened = AccountManager(store, family_members=_family, clock=clock)
    reopened.sync_family_aliases("gmail")
    assert {a.identity: a.alias for a in reopened.list_accounts("gmail")} == {
        "a@x.com": None, "b@y.com": "jobsearch",
    }
    raw = store.load("gmail")
    assert raw["accounts"]["b@y.com"]["alias_updated_at"]  # stamped


def test_apply_changes_failure_keeps_earlier_valid_steps(mgr):
    mgr.upsert_account("gmail", "a@x.com", cred("a@x.com"))
    mgr.upsert_account("gmail", "b@y.com", cred("b@y.com"))
    with pytest.raises(AccountResolutionError):
        mgr.apply_changes(
            "gmail",
            {"disconnect": ["b@y.com"], "primary": "ghost@nowhere.com"},
        )
    # The disconnect (individually atomic and valid) stayed applied.
    assert [a.identity for a in mgr.list_accounts("gmail")] == ["a@x.com"]
