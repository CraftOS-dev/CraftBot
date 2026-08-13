"""LinkedIn provider — first expiring-token non-Google provider.

No network: HTTP and client API methods are stubbed. What's real is
conformance, the credential binding, the legacy-shaped token refresh
persisting through the core (never to linkedin.json), the chooser-less
OAuth declaration, and the full chain execute() → resolve → bind →
person-URN construction → client method → shaped result.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.linkedin import LinkedInProvider
from craftos_integrations.providers.linkedin.provider import BoundLinkedInClient

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


# Real OAuth shape: legacy LinkedInCredential fields + the identity
# keys (email/sub from the OpenID userinfo) captured at login.
LINKEDIN_CRED = {
    "access_token": "AQV-work-token",
    "refresh_token": "AQW-work-refresh",
    "token_expiry": time.time() + 3600,
    "client_id": "li-client-id",
    "client_secret": "li-client-secret",
    "linkedin_id": "AbC123xYz",
    "user_id": "AbC123xYz",
    "email": "Person@Example.com",
    "sub": "AbC123xYz",
}

# LinkedIn returned no email (member hid it) — sub is the identity.
SUB_ONLY_CRED = {
    "access_token": "AQV-sub-token",
    "linkedin_id": "AbC123xYz",
    "sub": "AbC123xYz",
}

# Pre-multi-account linkedin.json shape: neither email nor sub key → LEGACY_IDENTITY.
LEGACY_CRED = {
    "access_token": "AQV-old-token",
    "refresh_token": "AQW-old-refresh",
    "token_expiry": 0.0,
    "client_id": "li-client-id",
    "client_secret": "li-client-secret",
    "linkedin_id": "OldId999",
    "user_id": "OldId999",
}


class TestLinkedInConformance(ProviderConformance):
    provider = LinkedInProvider()
    credential_fixtures = [
        LINKEDIN_CRED,  # real OAuth shape (email captured)
        SUB_ONLY_CRED,  # no email → identity is the OpenID sub claim
        LEGACY_CRED,  # pre-identity legacy shape → None
        {},  # junk — must not raise
    ]


def test_identity_is_email_then_sub_then_none():
    provider = LinkedInProvider()
    assert provider.identity_of(LINKEDIN_CRED) == "person@example.com"
    assert provider.identity_of(SUB_ONLY_CRED) == "abc123xyz"
    assert provider.identity_of({"email": "   ", "sub": "AbC123xYz"}) == "abc123xyz"
    assert provider.identity_of(LEGACY_CRED) is None  # → LEGACY_IDENTITY in core
    assert provider.identity_of({}) is None


def test_oauth_spec_has_no_chooser_and_no_fictitious_prompt_param():
    spec = LinkedInProvider().oauth_spec()
    assert spec.authorize_url == "https://www.linkedin.com/oauth/v2/authorization"
    assert spec.token_url == "https://www.linkedin.com/oauth/v2/accessToken"
    assert set(spec.scopes) == {"openid", "profile", "email", "w_member_social"}
    # LinkedIn's OAuth documents NO account-chooser/prompt parameter. The
    # abandoned PR shipped a fictitious ``prompt=login`` that does nothing
    # — declare the missing chooser instead and document the browser
    # log-out workaround (conformance-enforced via GUIDANCE.md).
    assert spec.has_chooser is False
    assert "prompt" not in spec.extra_authorize_params
    assert dict(spec.extra_authorize_params) == {}


def test_guidance_documents_the_add_account_workaround():
    guidance = LinkedInProvider().guidance().lower()
    assert "log out of linkedin.com" in guidance
    assert "add account" in guidance


def test_binding_replaces_disk_plumbing():
    client = BoundLinkedInClient()
    assert not client.has_credentials()  # no disk fallback
    client.bind_credential(LINKEDIN_CRED, lambda c: None)
    assert client.has_credentials()
    assert client._load().access_token == "AQV-work-token"
    assert client._load().linkedin_id == "AbC123xYz"


def test_refresh_persists_through_the_core(monkeypatch):
    """Legacy refresh semantics, but the refreshed credential goes through
    persist() (the core routes it to the right account entry) and keeps
    the identity keys that are not LinkedInCredential fields."""
    calls = []

    def fake_http_request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("data")))
        return {"ok": True, "result": {"access_token": "AQV-new", "expires_in": 5184000}}

    monkeypatch.setattr(
        "craftos_integrations.providers.linkedin.provider.http_request",
        fake_http_request,
    )

    persisted = []
    provider = LinkedInProvider()
    client = provider.build_client(dict(LINKEDIN_CRED), persisted.append)
    token = client.refresh_access_token()

    assert token == "AQV-new"
    assert calls == [
        (
            "POST",
            "https://www.linkedin.com/oauth/v2/accessToken",
            {
                "grant_type": "refresh_token",
                "refresh_token": "AQW-work-refresh",
                "client_id": "li-client-id",
                "client_secret": "li-client-secret",
            },
        )
    ]
    assert len(persisted) == 1
    updated = persisted[0]
    assert updated["access_token"] == "AQV-new"
    assert updated["refresh_token"] == "AQW-work-refresh"  # unchanged
    # ~60-day expiry, renewed a day early (legacy math preserved).
    assert updated["token_expiry"] == pytest.approx(
        time.time() + 5184000 - 86400, abs=30
    )
    # Identity keys are not dataclass fields — they must survive refresh,
    # or the account would degrade to legacy shape on its next migration.
    assert updated["email"] == "Person@Example.com"
    assert updated["sub"] == "AbC123xYz"


def test_provider_refresh_returns_updated_credential(monkeypatch):
    monkeypatch.setattr(
        "craftos_integrations.providers.linkedin.provider.http_request",
        lambda *a, **kw: {"ok": True, "result": {"access_token": "AQV-oob"}},
    )
    provider = LinkedInProvider()
    refreshed = run(provider.refresh(dict(LINKEDIN_CRED)))
    assert refreshed is not None and refreshed["access_token"] == "AQV-oob"

    # Missing refresh material → None (nothing persisted, nothing raised).
    assert run(provider.refresh(dict(SUB_ONLY_CRED))) is None


def test_refresh_failure_persists_nothing(monkeypatch):
    monkeypatch.setattr(
        "craftos_integrations.providers.linkedin.provider.http_request",
        lambda *a, **kw: {"error": "invalid_grant"},
    )
    persisted = []
    client = LinkedInProvider().build_client(dict(LINKEDIN_CRED), persisted.append)
    assert client.refresh_access_token() is None
    assert persisted == []


@pytest.fixture
def system(tmp_path):
    sys = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path), providers=[LinkedInProvider()]
    )
    sys.store_credential("linkedin", "person@example.com", dict(LINKEDIN_CRED))
    sys.store_credential(
        "linkedin",
        "consult@example.com",
        {
            **{k: v for k, v in LINKEDIN_CRED.items()},
            "access_token": "AQV-consult-token",
            "linkedin_id": "ZzTop777",
            "user_id": "ZzTop777",
            "email": "Consult@Example.com",
            "sub": "ZzTop777",
        },
    )
    sys.set_alias("linkedin", "consult@example.com", "consulting")
    return sys


def test_execute_builds_person_urn_from_resolved_accounts_client(
    system, monkeypatch
):
    seen = []

    def fake_create_text_post(self, author_urn, text, visibility="PUBLIC"):
        seen.append((self._cred.linkedin_id, author_urn, text, visibility))
        return {"ok": True, "result": {"id": "urn:li:share:9"}}

    monkeypatch.setattr(BoundLinkedInClient, "create_text_post", fake_create_text_post)

    result = run(
        system.execute(
            "linkedin",
            "create_linkedin_post",
            {"text": "Hello network"},
            account="consulting",
        )
    )
    assert result == {"status": "success", "result": {"id": "urn:li:share:9"}}
    # The consulting account's client and ITS person URN — not primary's.
    assert seen == [("ZzTop777", "urn:li:person:ZzTop777", "Hello network", "PUBLIC")]

    run(
        system.execute(
            "linkedin",
            "create_linkedin_post",
            {"text": "hi", "visibility": "CONNECTIONS"},
        )
    )
    assert seen[-1] == (
        "AbC123xYz",
        "urn:li:person:AbC123xYz",
        "hi",
        "CONNECTIONS",
    )  # primary account by default


def test_operation_error_shape_is_agent_friendly(system, monkeypatch):
    def fake_get_post(self, post_urn):
        return {"error": "API error: 401", "details": "revoked"}

    monkeypatch.setattr(BoundLinkedInClient, "get_post", fake_get_post)
    result = run(
        system.execute(
            "linkedin",
            "get_linkedin_post",
            {"post_urn": "urn:li:share:123"},
            account="person@example.com",
        )
    )
    assert result["status"] == "error"
    assert "401" in result["message"]
