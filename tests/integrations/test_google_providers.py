"""Google provider base + Gmail reference provider.

No network: HTTP is monkeypatched; client API methods are stubbed. What's
real is the full chain execute() → resolve → bind → client method → shaped
result, and refresh-persistence routing.
"""

from __future__ import annotations

import asyncio

import pytest

import craftos_integrations.providers._google as google_mod
from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.gmail import GmailProvider
from craftos_integrations.providers.gmail.provider import BoundGmailClient

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


GOOGLE_CRED = {
    "access_token": "at-1",
    "refresh_token": "rt-1",
    "token_expiry": 1e12,  # far future: no refresh during normal calls
    "client_id": "cid",
    "client_secret": "csec",
    "email": "a@x.com",
}


class TestGmailConformance(ProviderConformance):
    provider = GmailProvider()
    credential_fixtures = [
        GOOGLE_CRED,
        {"access_token": "at", "email": "  User@X.com "},  # messy legacy shape
        {"access_token": "at"},  # identity-less pre-multi-account shape → None
    ]


def test_oauth_spec_carries_the_chooser_fix():
    spec = GmailProvider().oauth_spec()
    assert spec.extra_authorize_params["prompt"] == "consent select_account"
    assert spec.extra_authorize_params["access_type"] == "offline"
    assert spec.has_chooser


def test_binding_replaces_disk_plumbing():
    client = BoundGmailClient()
    assert not client.has_credentials()  # no disk fallback
    client.bind_credential(GOOGLE_CRED, lambda c: None)
    assert client.has_credentials()
    assert client._load().email == "a@x.com"
    assert client._load().access_token == "at-1"


def test_refresh_persists_through_core_not_disk(monkeypatch):
    persisted = {}

    def fake_http(method, url, **kwargs):
        assert url == google_mod.GOOGLE_TOKEN_URL
        assert kwargs["data"]["refresh_token"] == "rt-1"
        return {"result": {"access_token": "at-2", "expires_in": 3600}}

    monkeypatch.setattr(google_mod, "http_request", fake_http)
    client = BoundGmailClient()
    client.bind_credential(dict(GOOGLE_CRED), persisted.update)
    token = client.refresh_access_token()
    assert token == "at-2"
    assert persisted["access_token"] == "at-2"
    assert persisted["refresh_token"] == "rt-1"  # carried forward
    assert persisted["email"] == "a@x.com"


def test_refresh_failure_returns_none_and_persists_nothing(monkeypatch):
    persisted = {}
    monkeypatch.setattr(
        google_mod, "http_request", lambda *a, **k: {"error": "invalid_grant"}
    )
    client = BoundGmailClient()
    client.bind_credential(dict(GOOGLE_CRED), persisted.update)
    assert client.refresh_access_token() is None
    assert persisted == {}


@pytest.fixture
def system(tmp_path):
    sys = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path), providers=[GmailProvider()]
    )
    sys.store_credential("gmail", "a@x.com", dict(GOOGLE_CRED))
    sys.store_credential(
        "gmail", "b@y.com", {**GOOGLE_CRED, "email": "b@y.com", "access_token": "at-b"}
    )
    sys.set_alias("gmail", "b@y.com", "school")
    return sys


def test_execute_runs_operation_against_resolved_accounts_client(system, monkeypatch):
    seen = []

    def fake_list_emails(self, n=5, unread_only=True):
        seen.append((self._cred.email, n, unread_only))
        return {"ok": True, "result": ["mail"]}

    monkeypatch.setattr(BoundGmailClient, "list_emails", fake_list_emails)

    result = run(system.execute("gmail", "list_gmail", {"count": 3}, account="school"))
    assert result == {"status": "success", "result": ["mail"]}
    assert seen == [("b@y.com", 3, True)]  # school account's client, mapped args

    run(system.execute("gmail", "list_gmail", {}))
    assert seen[-1] == ("a@x.com", 5, True)  # primary + client-side defaults


def test_operation_error_shape_is_agent_friendly(system, monkeypatch):
    monkeypatch.setattr(
        BoundGmailClient,
        "send_email",
        lambda self, **k: {"error": "API error: 403", "details": "insufficient scope"},
    )
    result = run(
        system.execute(
            "gmail", "send_gmail", {"subject": "s", "body": "b"}, account="a@x.com"
        )
    )
    assert result["status"] == "error"
    assert "403" in result["message"]


def test_default_providers_importable():
    from craftos_integrations.providers import default_providers

    providers = default_providers()
    assert any(p.id == "gmail" for p in providers)
