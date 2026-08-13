"""Every rule of the account-resolution contract (plan §4)."""

from __future__ import annotations

import pytest

from craftos_integrations.contracts import AccountResolutionError

from .conftest import cred


def test_empty_hint_resolves_to_primary(two_accounts):
    assert two_accounts.resolve("gmail", None) == "a@x.com"
    assert two_accounts.resolve("gmail", "") == "a@x.com"
    assert two_accounts.resolve("gmail", "   ") == "a@x.com"


def test_exact_identity_match_case_insensitive(two_accounts):
    assert two_accounts.resolve("gmail", "B@Y.COM") == "b@y.com"


def test_identity_always_outranks_alias(mgr):
    # The abandoned PR's wrong-account bug: an alias equal to another
    # account's real email must never steal its resolution. set_alias
    # refuses to create that state; even if legacy data contains it, exact
    # identity wins because rule 2 runs before rule 3.
    mgr.upsert_account("gmail", "one@x.com", cred("one@x.com"))
    mgr.upsert_account("gmail", "two@x.com", cred("two@x.com"))
    with pytest.raises(ValueError, match="another connected account's identity"):
        mgr.set_alias("gmail", "one@x.com", "two@x.com")
    assert mgr.resolve("gmail", "two@x.com") == "two@x.com"


def test_exact_alias_match(two_accounts):
    assert two_accounts.resolve("gmail", "school") == "b@y.com"
    assert two_accounts.resolve("gmail", "SCHOOL") == "b@y.com"


def test_unique_substring_of_identity(two_accounts):
    assert two_accounts.resolve("gmail", "b@y") == "b@y.com"


def test_unique_substring_of_alias(two_accounts):
    assert two_accounts.resolve("gmail", "scho") == "b@y.com"


def test_ambiguous_substring_lists_candidates(two_accounts):
    with pytest.raises(AccountResolutionError) as err:
        two_accounts.resolve("gmail", "com")  # matches both identities
    message = str(err.value)
    assert "a@x.com" in message and "b@y.com" in message
    assert "work" in message and "school" in message


def test_no_match_lists_connected_accounts(two_accounts):
    with pytest.raises(AccountResolutionError) as err:
        two_accounts.resolve("gmail", "nope")
    message = str(err.value)
    assert "No gmail account matches 'nope'" in message
    assert "a@x.com" in message and "b@y.com" in message


def test_non_string_hint_is_rejected_with_helpful_error(two_accounts):
    with pytest.raises(AccountResolutionError, match="must be a string"):
        two_accounts.resolve("gmail", ["work"])  # LLMs emit lists sometimes


def test_not_connected(mgr):
    with pytest.raises(AccountResolutionError, match="not connected"):
        mgr.resolve("gmail", "anything")
