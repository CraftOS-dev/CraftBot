"""Outlook provider — first non-Google provider WITH token refresh.

No network: HTTP is monkeypatched; client API methods are stubbed. What's
real is conformance, the credential binding, refresh-persistence routing
through the core (incl. Microsoft's refresh-token rotation), the
select_account chooser fix, and the full chain execute() → resolve →
bind → client method → shaped result.
"""

from __future__ import annotations

import asyncio

import pytest

import craftos_integrations.providers.outlook.provider as outlook_mod
from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.outlook import OutlookProvider
from craftos_integrations.providers.outlook.provider import BoundOutlookClient

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


OUTLOOK_CRED = {
    "access_token": "at-1",
    "refresh_token": "rt-1",
    "token_expiry": 1e12,  # far future: no refresh during normal calls
    "client_id": "cid",
    "email": "a@contoso.com",
}


class TestOutlookConformance(ProviderConformance):
    provider = OutlookProvider()
    credential_fixtures = [
        OUTLOOK_CRED,  # real login shape (email/UPN captured)
        {"access_token": "at", "email": "  User@Contoso.com "},  # messy shape
        {"access_token": "at", "refresh_token": "rt"},  # no-email legacy → None
        {},  # junk — must not raise
    ]


def test_identity_is_lowercased_email():
    provider = OutlookProvider()
    assert provider.identity_of(OUTLOOK_CRED) == "a@contoso.com"
    assert provider.identity_of({"email": "  User@Contoso.com "}) == "user@contoso.com"
    assert provider.identity_of({"access_token": "at"}) is None
    assert provider.identity_of({"email": "   "}) is None


def test_oauth_spec_matches_legacy_handler_and_carries_the_chooser_fix():
    spec = OutlookProvider().oauth_spec()
    assert (
        spec.authorize_url
        == "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    )
    assert spec.token_url == "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    assert "Mail.Send" in spec.scopes and "offline_access" in spec.scopes
    # THE multi-account fix: without select_account, "Add account" silently
    # re-auths the browser's signed-in Microsoft account.
    assert spec.extra_authorize_params["prompt"] == "select_account"
    assert spec.extra_authorize_params["response_mode"] == "query"  # legacy param
    assert spec.has_chooser


def test_binding_replaces_disk_plumbing():
    client = BoundOutlookClient()
    assert not client.has_credentials()  # no disk fallback
    client.bind_credential(OUTLOOK_CRED, lambda c: None)
    assert client.has_credentials()
    assert client._load().email == "a@contoso.com"
    assert client._load().access_token == "at-1"


def test_refresh_persists_through_core_not_disk(monkeypatch):
    persisted = {}

    def fake_http(method, url, **kwargs):
        assert url == outlook_mod.MS_TOKEN_URL
        data = kwargs["data"]
        assert data["refresh_token"] == "rt-1"
        assert data["grant_type"] == "refresh_token"
        assert data["scope"] == outlook_mod.OUTLOOK_SCOPES
        assert "client_secret" not in data  # PKCE public client
        return {
            "result": {
                "access_token": "at-2",
                "refresh_token": "rt-2",  # Microsoft rotates refresh tokens
                "expires_in": 3600,
            }
        }

    monkeypatch.setattr(outlook_mod, "http_request", fake_http)
    client = BoundOutlookClient()
    client.bind_credential(dict(OUTLOOK_CRED), persisted.update)
    token = client.refresh_access_token()
    assert token == "at-2"
    assert persisted["access_token"] == "at-2"
    assert persisted["refresh_token"] == "rt-2"  # rotated token persisted
    assert persisted["email"] == "a@contoso.com"  # identity carried forward


def test_refresh_keeps_old_refresh_token_when_not_rotated(monkeypatch):
    persisted = {}
    monkeypatch.setattr(
        outlook_mod,
        "http_request",
        lambda *a, **k: {"result": {"access_token": "at-2", "expires_in": 3600}},
    )
    client = BoundOutlookClient()
    client.bind_credential(dict(OUTLOOK_CRED), persisted.update)
    assert client.refresh_access_token() == "at-2"
    assert persisted["refresh_token"] == "rt-1"  # carried forward


def test_refresh_failure_returns_none_and_persists_nothing(monkeypatch):
    persisted = {}
    monkeypatch.setattr(
        outlook_mod, "http_request", lambda *a, **k: {"error": "invalid_grant"}
    )
    client = BoundOutlookClient()
    client.bind_credential(dict(OUTLOOK_CRED), persisted.update)
    assert client.refresh_access_token() is None
    assert persisted == {}


def test_provider_refresh_returns_refreshed_credential(monkeypatch):
    """Out-of-band refresh (GoogleProviderBase.refresh style): the provider
    returns the refreshed dict for the core to store."""
    monkeypatch.setattr(
        outlook_mod,
        "http_request",
        lambda *a, **k: {"result": {"access_token": "at-2", "expires_in": 3600}},
    )
    refreshed = run(OutlookProvider().refresh(dict(OUTLOOK_CRED)))
    assert refreshed is not None
    assert refreshed["access_token"] == "at-2"
    assert refreshed["email"] == "a@contoso.com"

    monkeypatch.setattr(
        outlook_mod, "http_request", lambda *a, **k: {"error": "invalid_grant"}
    )
    assert run(OutlookProvider().refresh(dict(OUTLOOK_CRED))) is None


@pytest.fixture
def system(tmp_path):
    sys = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path), providers=[OutlookProvider()]
    )
    sys.store_credential("outlook", "a@contoso.com", dict(OUTLOOK_CRED))
    sys.store_credential(
        "outlook",
        "b@fabrikam.com",
        {**OUTLOOK_CRED, "email": "b@fabrikam.com", "access_token": "at-b"},
    )
    sys.set_alias("outlook", "b@fabrikam.com", "work")
    return sys


def test_execute_runs_operation_against_resolved_accounts_client(system, monkeypatch):
    seen = []

    def fake_list_emails(self, n=10, unread_only=False, folder="inbox"):
        seen.append((self._cred.email, n, unread_only))
        return {"ok": True, "result": {"emails": [], "count": 0}}

    monkeypatch.setattr(BoundOutlookClient, "list_emails", fake_list_emails)

    result = run(
        system.execute("outlook", "list_outlook_emails", {"count": 3}, account="work")
    )
    assert result == {"status": "success", "result": {"emails": [], "count": 0}}
    assert seen == [("b@fabrikam.com", 3, False)]  # work account's client, mapped args

    run(system.execute("outlook", "list_outlook_emails", {}))
    assert seen[-1] == ("a@contoso.com", 10, False)  # primary + legacy defaults


def test_operation_error_shape_is_agent_friendly(system, monkeypatch):
    monkeypatch.setattr(
        BoundOutlookClient,
        "send_email",
        lambda self, **k: {"error": "API error: 403", "details": "insufficient scope"},
    )
    result = run(
        system.execute(
            "outlook",
            "send_outlook_email",
            {"to": "x@y.com", "subject": "s", "body": "b"},
            account="a@contoso.com",
        )
    )
    assert result["status"] == "error"
    assert "403" in result["message"]
