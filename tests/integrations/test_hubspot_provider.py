"""HubSpot provider — first non-Google provider with rotating tokens.

No network: HTTP is monkeypatched; client API methods are stubbed. What's
real is conformance, the credential binding, refresh-persistence routing
through the core (the part that differs from Slack), and the full chain
execute() → resolve → bind → client method → shaped result (incl. the
legacy pick_result shaping).
"""

from __future__ import annotations

import asyncio
import time

import pytest

import craftos_integrations.providers.hubspot.provider as hubspot_mod
from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.hubspot import HubSpotProvider
from craftos_integrations.providers.hubspot.provider import BoundHubSpotClient

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


HUBSPOT_CRED = {
    "access_token": "at-1",
    "refresh_token": "rt-1",
    "token_expiry": 1e12,  # far future: no refresh during normal calls
    "hub_id": "12345678",
    "hub_domain": "acme.hubspot.com",
    "user_email": "ops@acme.com",
    "auth_kind": "oauth",
}


class TestHubSpotConformance(ProviderConformance):
    provider = HubSpotProvider()
    credential_fixtures = [
        HUBSPOT_CRED,  # real OAuth-invite shape (hub id captured)
        # pre-identity Private-App-token shape (hub_id never captured) → None
        {"access_token": "pat-na1-old-token", "auth_kind": "token"},
        {},  # junk — must not raise
    ]


def test_identity_is_lowercased_hub_id():
    provider = HubSpotProvider()
    assert provider.identity_of(HUBSPOT_CRED) == "12345678"
    assert provider.identity_of({"hub_id": 12345678}) == "12345678"  # int tolerated
    assert provider.identity_of({"access_token": "pat-na1-x"}) is None
    assert provider.identity_of({"hub_id": ""}) is None
    assert provider.identity_of({"hub_id": "   "}) is None


def test_oauth_spec_matches_legacy_handler():
    spec = HubSpotProvider().oauth_spec()
    assert spec.authorize_url == "https://app.hubspot.com/oauth/authorize"
    assert spec.token_url == "https://api.hubapi.com/oauth/v1/token"
    assert "crm.objects.contacts.read" in spec.scopes and "oauth" in spec.scopes
    assert spec.has_chooser  # HubSpot's authorize page has an account/hub chooser


def test_operations_are_the_full_legacy_surface():
    assert len(HubSpotProvider().operations()) == 90


def test_binding_replaces_disk_plumbing():
    client = BoundHubSpotClient()
    assert not client.has_credentials()  # no disk fallback
    client.bind_credential(HUBSPOT_CRED, lambda c: None)
    assert client.has_credentials()
    assert client._load().access_token == "at-1"
    assert client._load().hub_id == "12345678"


# ── refresh: legacy logic, AccountSet persistence ────────────────────────────────


@pytest.fixture
def oauth_config(monkeypatch):
    monkeypatch.setattr(
        hubspot_mod.ConfigStore,
        "_oauth",
        {
            "HUBSPOT_SHARED_CLIENT_ID": "cid",
            "HUBSPOT_SHARED_CLIENT_SECRET": "csec",
        },
    )


def test_refresh_persists_through_core_not_disk(monkeypatch, oauth_config):
    persisted = {}

    def fake_http(method, url, **kwargs):
        assert method == "POST"
        assert url == "https://api.hubapi.com/oauth/v1/token"
        assert kwargs["data"] == {
            "grant_type": "refresh_token",
            "client_id": "cid",
            "client_secret": "csec",
            "refresh_token": "rt-1",
        }
        return {"ok": True, "result": {"access_token": "at-2", "expires_in": 1800}}

    monkeypatch.setattr(hubspot_mod, "http_request", fake_http)
    client = BoundHubSpotClient()
    # Expired token: the inherited _get_valid_access_token must refresh
    # inline through the binding's override.
    client.bind_credential({**HUBSPOT_CRED, "token_expiry": 100.0}, persisted.update)
    token = client._get_valid_access_token()
    assert token == "at-2"
    assert persisted["access_token"] == "at-2"
    assert persisted["refresh_token"] == "rt-1"  # not rotated → carried forward
    assert persisted["hub_id"] == "12345678"
    assert persisted["token_expiry"] > time.time()  # 1800s ahead minus 60s margin


def test_refresh_keeps_rotated_refresh_token(monkeypatch, oauth_config):
    persisted = {}
    monkeypatch.setattr(
        hubspot_mod,
        "http_request",
        lambda *a, **k: {
            "ok": True,
            "result": {"access_token": "at-2", "refresh_token": "rt-2"},
        },
    )
    client = BoundHubSpotClient()
    client.bind_credential(dict(HUBSPOT_CRED), persisted.update)
    assert client._refresh_access_token() == "at-2"
    assert persisted["refresh_token"] == "rt-2"  # HubSpot rotated it


def test_refresh_failure_returns_stale_token_and_persists_nothing(
    monkeypatch, oauth_config
):
    persisted = {}
    monkeypatch.setattr(
        hubspot_mod, "http_request", lambda *a, **k: {"error": "invalid_grant"}
    )
    client = BoundHubSpotClient()
    client.bind_credential({**HUBSPOT_CRED, "token_expiry": 100.0}, persisted.update)
    assert client._refresh_access_token() is None
    assert persisted == {}
    # Legacy fallback: stale token is returned so HubSpot answers a clean 401.
    assert client._get_valid_access_token() == "at-1"


def test_private_app_tokens_never_hit_the_refresh_endpoint(monkeypatch):
    def exploding_http(*a, **k):  # pragma: no cover - fails the test if reached
        raise AssertionError("Private App tokens must not attempt refresh")

    monkeypatch.setattr(hubspot_mod, "http_request", exploding_http)
    cred = {
        "access_token": "pat-na1-token",
        "hub_id": "999",
        "auth_kind": "token",
    }
    client = BoundHubSpotClient()
    client.bind_credential(cred, lambda c: None)
    assert client._get_valid_access_token() == "pat-na1-token"
    assert run(HubSpotProvider().refresh(dict(cred))) is None  # non-expiring


# ── execute() wiring through IntegrationSystem ───────────────────────────


@pytest.fixture
def system(tmp_path):
    sys = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path), providers=[HubSpotProvider()]
    )
    sys.store_credential("hubspot", "12345678", dict(HUBSPOT_CRED))
    sys.store_credential(
        "hubspot",
        "87654321",
        {
            **HUBSPOT_CRED,
            "hub_id": "87654321",
            "hub_domain": "beta.hubspot.com",
            "access_token": "at-beta",
        },
    )
    sys.set_alias("hubspot", "87654321", "beta")
    return sys


def test_execute_runs_operation_against_resolved_hubs_client(system, monkeypatch):
    seen = []

    async def fake_create_contact(self, properties, **kw):
        seen.append((self._cred.hub_id, properties))
        # Full mutated object, as HubSpot returns it — the legacy
        # pick_result(["id"]) shaping must reduce it.
        return {
            "ok": True,
            "result": {
                "id": "999",
                "properties": properties,
                "createdAt": "2026-01-01T00:00:00Z",
            },
        }

    monkeypatch.setattr(BoundHubSpotClient, "create_contact", fake_create_contact)

    result = run(
        system.execute(
            "hubspot",
            "create_hubspot_contact",
            {"properties": {"email": "jane@example.com"}},
            account="beta",
        )
    )
    # ok-envelope collapsed + legacy pick_result(["id"]) shaping.
    assert result == {"status": "success", "result": {"id": "999"}}
    assert seen == [("87654321", {"email": "jane@example.com"})]  # beta hub's client

    run(
        system.execute(
            "hubspot", "create_hubspot_contact", {"properties": {"email": "b@x.com"}}
        )
    )
    assert seen[-1][0] == "12345678"  # primary hub by default


def test_operation_error_shape_is_agent_friendly(system, monkeypatch):
    async def fake_delete_contact(self, contact_id):
        return {"error": "API error: 404", "details": "contact not found"}

    monkeypatch.setattr(BoundHubSpotClient, "delete_contact", fake_delete_contact)
    result = run(
        system.execute(
            "hubspot",
            "delete_hubspot_contact",
            {"contact_id": "404404"},
            account="12345678",
        )
    )
    assert result["status"] == "error"
    assert "404" in result["message"]
