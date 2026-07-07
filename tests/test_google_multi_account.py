# -*- coding: utf-8 -*-
"""Multi-account support for the Google integrations (Gmail, Calendar, Drive,
Docs, YouTube) — one smallest-possible check per touched unit:

  - credentials_store: filename sanitization + secondary-file glob doesn't
    catch the paired _config.json file.
  - resolve_account: exact / substring / ambiguous / not-found / default-
    primary resolution.
  - run_google_login: first account -> primary file; second -> secondary
    file; re-auth of an existing email -> overwrite (no new file).
  - registry: two accounts for the same platform cache as separate client
    instances; invalidate_client drops all of them.
"""

import asyncio

import pytest

from craftos_integrations.config import ConfigStore
from craftos_integrations import credentials_store as cs
from craftos_integrations.spec import IntegrationSpec
from craftos_integrations.integrations import _google_common as gc
from craftos_integrations import registry
from craftos_integrations.base import BasePlatformClient


@pytest.fixture(autouse=True)
def isolated_credentials_dir(tmp_path, monkeypatch):
    """Point ConfigStore.project_root at a scratch dir so tests never touch
    the real ~/.credentials, and reset the registry between tests."""
    monkeypatch.setattr(ConfigStore, "project_root", tmp_path)
    registry.reset()
    yield
    registry.reset()


SPEC = IntegrationSpec(name="gmail", cred_class=gc.GoogleCredential, cred_file="gmail.json")


def _cred(email: str) -> gc.GoogleCredential:
    return gc.GoogleCredential(
        access_token="tok", refresh_token="ref", token_expiry=0.0,
        client_id="cid", client_secret="csec", email=email,
    )


# ── credentials_store ────────────────────────────────────────────────────


def test_sanitize_and_secondary_glob_ignores_config_file():
    assert cs.sanitize_account("Alan@Gmail.com") == "alan_gmail_com"
    fname = cs.account_filename("gmail", "alan@gmail.com")
    assert fname == "gmail__alan_gmail_com.json"

    cs.save_credential(fname, _cred("alan@gmail.com"))
    cs.save_config("gmail_config.json", gc.GoogleCredential())  # decoy, wrong dir key but same prefix risk

    secondaries = cs.list_account_files("gmail")
    assert secondaries == [fname]
    assert "gmail_config.json" not in secondaries


# ── resolve_account ──────────────────────────────────────────────────────


def test_resolve_account_default_primary_and_not_connected():
    fname, err = gc.resolve_account(SPEC, None)
    assert fname is None and "Not connected" in err

    cs.save_credential(SPEC.cred_file, _cred("alan@gmail.com"))
    fname, err = gc.resolve_account(SPEC, None)
    assert err is None and fname == SPEC.cred_file


def test_resolve_account_exact_and_substring_and_ambiguous():
    cs.save_credential(SPEC.cred_file, _cred("alan@gmail.com"))
    cs.save_credential(cs.account_filename("gmail", "alan@corp.com"), _cred("alan@corp.com"))

    # exact (case-insensitive)
    fname, err = gc.resolve_account(SPEC, "ALAN@GMAIL.COM")
    assert err is None and fname == SPEC.cred_file

    # unique substring
    fname, err = gc.resolve_account(SPEC, "corp")
    assert err is None and fname == cs.account_filename("gmail", "alan@corp.com")

    # ambiguous substring -> error lists both matches
    fname, err = gc.resolve_account(SPEC, "alan")
    assert fname is None
    assert "alan@gmail.com" in err and "alan@corp.com" in err

    # no match -> error lists connected accounts
    fname, err = gc.resolve_account(SPEC, "nobody@example.com")
    assert fname is None
    assert "alan@gmail.com" in err and "alan@corp.com" in err


# ── run_google_login ──────────────────────────────────────────────────────


class _StubOAuth:
    def __init__(self, email):
        self._email = email

    async def run(self):
        return {
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_in": 3600,
            "userinfo": {"email": self._email},
        }


def test_login_first_account_fills_primary_then_secondary_then_overwrites():
    ok, msg = asyncio.run(gc.run_google_login(SPEC, _StubOAuth("alan@gmail.com"), "Gmail"))
    assert ok and cs.has_credential(SPEC.cred_file)
    assert gc.list_google_accounts(SPEC) == [("alan@gmail.com", SPEC.cred_file)]

    # second, different email -> new secondary file, primary untouched
    ok, msg = asyncio.run(gc.run_google_login(SPEC, _StubOAuth("alan@corp.com"), "Gmail"))
    assert ok
    accounts = dict(gc.list_google_accounts(SPEC))
    assert accounts["alan@gmail.com"] == SPEC.cred_file
    assert accounts["alan@corp.com"] == cs.account_filename("gmail", "alan@corp.com")

    # re-auth of the primary email -> same two files, no third one created
    asyncio.run(gc.run_google_login(SPEC, _StubOAuth("alan@gmail.com"), "Gmail"))
    assert len(gc.list_google_accounts(SPEC)) == 2


def test_logout_removing_primary_promotes_a_secondary():
    asyncio.run(gc.run_google_login(SPEC, _StubOAuth("alan@gmail.com"), "Gmail"))
    asyncio.run(gc.run_google_login(SPEC, _StubOAuth("alan@corp.com"), "Gmail"))

    ok, _ = asyncio.run(gc.run_google_logout(SPEC, "Gmail", "alan@gmail.com"))
    assert ok
    accounts = gc.list_google_accounts(SPEC)
    assert accounts == [("alan@corp.com", SPEC.cred_file)]  # promoted into the bare file


# ── registry: per-account client caching ─────────────────────────────────


class _DummyClient(BasePlatformClient):
    PLATFORM_ID = "dummy_multi_account"

    def has_credentials(self):
        return True

    async def connect(self):
        pass

    async def send_message(self, recipient, text, **kwargs):
        return {}


def test_registry_caches_per_account_and_invalidate_drops_all():
    registry.register_client(_DummyClient)

    primary = registry.get_client("dummy_multi_account")
    secondary = registry.get_client("dummy_multi_account", "alan@corp.com")
    again_primary = registry.get_client("dummy_multi_account")

    assert primary is not secondary
    assert primary is again_primary
    assert primary._account is None
    assert secondary._account == "alan@corp.com"

    registry.invalidate_client("dummy_multi_account")
    assert registry.get_client("dummy_multi_account") is not primary


# ── shared alias namespace across the Google family ───────────────────────


def test_alias_shared_across_google_services_with_legacy_migration():
    from craftos_integrations import accounts as acc
    from craftos_integrations.integrations.gmail import GMAIL
    from craftos_integrations.integrations.google_calendar import GCAL

    cs.save_credential(GMAIL.cred_file, _cred("alan@gmail.com"))
    cs.save_credential(GCAL.cred_file, _cred("alan@gmail.com"))

    # Simulate pre-migration state: alias set the old way, per-service.
    acc.set_alias("gmail", "alan@gmail.com", "personal")

    # Reading through Gmail migrates it to the shared "google" namespace.
    accounts = gc.run_google_list_accounts(GMAIL)
    assert accounts[0]["alias"] == "personal"
    assert acc.get_alias("google", "alan@gmail.com") == "personal"
    assert acc.get_alias("gmail", "alan@gmail.com") is None  # legacy key cleaned up

    # Calendar never had its own alias — it inherits via the shared namespace.
    cal_accounts = gc.run_google_list_accounts(GCAL)
    assert cal_accounts[0]["alias"] == "personal"

    # Setting the alias through Calendar updates the shared value Gmail sees too.
    ok, _ = gc.run_google_set_alias(GCAL, "alan@gmail.com", "work")
    assert ok
    assert gc.run_google_list_accounts(GMAIL)[0]["alias"] == "work"
