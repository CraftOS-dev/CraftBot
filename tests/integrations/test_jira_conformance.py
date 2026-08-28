"""Jira bridge provider — conformance + wiring.

Auth-layer bridge: no operations, no guidance, no OAuth. What's tested is
the identity scheme (user + site), the binding over the legacy client, the
token verifier (network stubbed), and the legacy-listener adapter.
"""

from __future__ import annotations

import asyncio

from craftos_integrations.providers._shared import ClientListenerAdapter
from craftos_integrations.providers.jira import JiraProvider
from craftos_integrations.providers.jira import provider as jira_provider_module
from craftos_integrations.providers.jira.provider import BoundJiraClient

from .conformance import ProviderConformance

import pytest


def run(coro):
    return asyncio.run(coro)


# Real token-connect shape (handler fields: domain, email, api_token).
# Mixed case on purpose: identity must lowercase both halves.
JIRA_CRED = {
    "domain": "MyCompany.atlassian.net",
    "email": "You@Example.com",
    "api_token": "ATATT3xFfGF0-secret",
}

JUNK_CRED = {"domain": 42, "email": None, "token": ["nope"]}


class TestJiraConformance(ProviderConformance):
    provider = JiraProvider()
    credential_fixtures = [
        JIRA_CRED,
        JUNK_CRED,  # malformed — identity_of must return None, never raise
        {},
    ]


# ── identity: user AND site ──────────────────────────────────────────────


def test_identity_is_email_at_site_host_lowercased():
    provider = JiraProvider()
    assert (
        provider.identity_of(JIRA_CRED) == "you@example.com@mycompany.atlassian.net"
    )


def test_identity_same_user_two_sites_is_two_accounts():
    provider = JiraProvider()
    a = provider.identity_of({**JIRA_CRED, "domain": "site-a.atlassian.net"})
    b = provider.identity_of({**JIRA_CRED, "domain": "site-b.atlassian.net"})
    assert a != b and a and b


def test_identity_site_url_scheme_is_stripped():
    provider = JiraProvider()
    # OAuth-shape credential: accountId + site_url with scheme and path.
    cred = {
        "accountId": "5B10AC8D",
        "site_url": "https://MyCompany.atlassian.net/",
    }
    assert provider.identity_of(cred) == "5b10ac8d@mycompany.atlassian.net"


def test_identity_none_when_either_half_missing():
    provider = JiraProvider()
    assert provider.identity_of({"email": "you@example.com"}) is None  # no site
    assert provider.identity_of({"domain": "x.atlassian.net"}) is None  # no user
    assert provider.identity_of(JUNK_CRED) is None
    assert provider.identity_of({}) is None


# ── token-only: no OAuth, no refresh ─────────────────────────────────────


def test_oauth_spec_is_declared_token_only():
    with pytest.raises(NotImplementedError):
        JiraProvider().oauth_spec()


def test_no_run_login():
    assert not hasattr(JiraProvider(), "run_login")


def test_refresh_is_none_tokens_do_not_expire():
    assert run(JiraProvider().refresh(dict(JIRA_CRED))) is None


# ── bridge surface ───────────────────────────────────────────────────────


def test_bridge_has_no_operations_and_no_guidance():
    provider = JiraProvider()
    assert provider.operations() == []
    assert provider.guidance() == ""


# ── binding ──────────────────────────────────────────────────────────────


def test_binding_injects_credential_and_ignores_extra_keys():
    provider = JiraProvider()
    persisted = []
    client = provider.build_client(
        {**JIRA_CRED, "account_id": "5B10AC8D", "not_a_field": "x"},
        persisted.append,
    )
    assert isinstance(client, BoundJiraClient)
    assert client.has_credentials()
    cred = client._load()
    assert cred.domain == "MyCompany.atlassian.net"
    assert cred.email == "You@Example.com"
    assert cred.api_token == "ATATT3xFfGF0-secret"
    assert persisted == []  # no refresh path — persist never called


def test_unbound_client_never_falls_back_to_disk():
    client = BoundJiraClient()
    assert not client.has_credentials()
    with pytest.raises(RuntimeError):
        client._load()


# ── verify_token (network stubbed) ───────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_verify_token_success_mirrors_legacy_login(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        calls.append((url, headers))
        return _FakeResponse(
            200,
            {
                "accountId": "5B10AC8D",
                "displayName": "Ahmad A",
                "emailAddress": "you@example.com",
            },
        )

    monkeypatch.setattr(jira_provider_module.httpx, "get", fake_get)

    provider = JiraProvider()
    ok, message, credential = provider.verify_token(
        {
            "domain": "https://MyCompany.atlassian.net/",
            "email": "  You@Example.com ",
            "api_token": " ATATT3xFfGF0-secret ",
        }
    )
    assert ok, message
    assert "Ahmad A" in message and "mycompany.atlassian.net" in message.lower()
    # Scheme/slash stripped exactly like JiraHandler.login(); v3 tried first.
    assert calls[0][0] == "https://MyCompany.atlassian.net/rest/api/3/myself"
    assert calls[0][1]["Authorization"].startswith("Basic ")
    assert credential["domain"] == "MyCompany.atlassian.net"
    assert credential["email"] == "You@Example.com"
    assert credential["api_token"] == "ATATT3xFfGF0-secret"
    assert credential["account_id"] == "5B10AC8D"
    # The verified credential is identity-bearing (user + site).
    assert (
        JiraProvider().identity_of(credential)
        == "you@example.com@mycompany.atlassian.net"
    )


def test_verify_token_auth_failure_falls_back_v2_then_hints(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        calls.append(url)
        return _FakeResponse(401, text="Unauthorized")

    monkeypatch.setattr(jira_provider_module.httpx, "get", fake_get)

    ok, message, credential = JiraProvider().verify_token(dict(JIRA_CRED))
    assert not ok and credential is None
    assert "401" in message and "API token" in message
    # Same v3 → v2 fallback the legacy handler runs.
    assert [u.split("/rest/api/")[1] for u in calls] == ["3/myself", "2/myself"]


def test_verify_token_missing_fields_never_calls_network(monkeypatch):
    def boom(*a, **k):  # pragma: no cover - guards against network use
        raise AssertionError("network must not be touched")

    monkeypatch.setattr(jira_provider_module.httpx, "get", boom)
    ok, message, credential = JiraProvider().verify_token({"email": "x@y.com"})
    assert not ok and credential is None


# ── listener ─────────────────────────────────────────────────────────────


def test_make_listener_is_legacy_adapter_over_the_bound_client():
    provider = JiraProvider()

    async def emit(event):
        pass

    client = provider.build_client(dict(JIRA_CRED), lambda c: None)
    listener = provider.make_listener(client, None, emit)
    assert isinstance(listener, ClientListenerAdapter)
    assert listener._client is client
    assert listener.cursor() is None  # legacy loop keeps its own watermark
