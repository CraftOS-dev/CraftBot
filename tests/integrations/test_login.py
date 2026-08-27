"""Provider run_login flows and IntegrationSystem.add_account.

The OAuth dance itself is monkeypatched at OAuthFlow.run — these tests
assert the surrounding contract: which authorize params the flow was
given, how identity is extracted, and what credential shape is returned.

No pytest-asyncio in this repo — async paths are driven with asyncio.run.
"""

from __future__ import annotations

import asyncio

import pytest

from craftos_integrations.contracts import UNIDENTIFIED
from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.oauth_flow import OAuthFlow
from craftos_integrations.providers.hubspot.provider import HubSpotProvider
from craftos_integrations.providers.linkedin.provider import LinkedInProvider
from craftos_integrations.providers.notion.provider import NotionProvider
from craftos_integrations.providers.outlook.provider import OutlookProvider
from craftos_integrations.providers.slack.provider import SlackProvider

from .conftest import cred
from .test_system import FakeProvider


def run(coro):
    return asyncio.run(coro)


def patch_flow(monkeypatch, result):
    """Stub OAuthFlow.run with a canned result, capturing the effective
    per-run flow config (authorize params, endpoint)."""
    captured = {}

    async def fake_run(self):
        captured["extra"] = dict(self.extra_auth_params)
        captured["auth_url"] = self.auth_url
        return result

    monkeypatch.setattr(OAuthFlow, "run", fake_run)
    return captured


# ════════════════════════════════════════════════════════════════════════
# run_login — one smoke per provider
# ════════════════════════════════════════════════════════════════════════


def test_outlook_run_login_extracts_upn_and_forces_chooser(monkeypatch):
    captured = patch_flow(
        monkeypatch,
        {
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
            "userinfo": {"mail": "User@Corp.com", "userPrincipalName": "u@corp.com"},
            "raw": {},
        },
    )
    identity, credential, message = run(OutlookProvider().run_login())
    assert identity == "user@corp.com"  # mail outranks UPN, lowercased
    assert credential["access_token"] == "at"
    assert credential["refresh_token"] == "rt"
    assert "user@corp.com" in message
    # The chooser fix this port exists for + the carried legacy param.
    assert captured["extra"]["prompt"] == "select_account"
    assert captured["extra"]["response_mode"] == "query"
    # The shared module-level flow is copied, never mutated.
    from craftos_integrations.providers.outlook.client import OUTLOOK_OAUTH

    assert "prompt" not in OUTLOOK_OAUTH.extra_auth_params


def test_outlook_run_login_refuses_identityless_result(monkeypatch):
    patch_flow(
        monkeypatch,
        {"access_token": "at", "refresh_token": "", "expires_in": 0, "userinfo": {}, "raw": {}},
    )
    identity, credential, message = run(OutlookProvider().run_login())
    # Documented judgment call: Graph /me always returns a UPN on success,
    # so an empty userinfo means the fetch failed — re-prompt, don't store.
    assert identity is None
    assert credential is None
    assert "try again" in message.lower()


def test_linkedin_run_login_no_fictitious_params(monkeypatch):
    captured = patch_flow(
        monkeypatch,
        {
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 5184000,
            "userinfo": {"email": "Me@Corp.com", "sub": "AbC123", "name": "Me"},
            "raw": {},
        },
    )
    identity, credential, message = run(LinkedInProvider().run_login())
    assert identity == "me@corp.com"
    assert credential["email"] == "Me@Corp.com"
    assert credential["sub"] == "AbC123"
    assert credential["linkedin_id"] == "AbC123"
    assert LinkedInProvider().identity_of(credential) == identity
    # LinkedIn's OAuth has NO chooser param — nothing may be invented here.
    assert captured["extra"] == {}


def test_linkedin_run_login_identityless_still_returns_credential(monkeypatch):
    patch_flow(
        monkeypatch,
        {"access_token": "at", "refresh_token": "", "expires_in": 0, "userinfo": {}, "raw": {}},
    )
    identity, credential, message = run(LinkedInProvider().run_login())
    assert identity is None
    assert credential is not None  # stored under UNIDENTIFIED by the core
    assert credential["access_token"] == "at"


def test_notion_run_login_workspace_identity(monkeypatch):
    captured = patch_flow(
        monkeypatch,
        {
            "access_token": "ntok",
            "refresh_token": "",
            "expires_in": 0,
            "userinfo": {},
            "raw": {"workspace_id": "WS-1", "bot_id": "B1", "workspace_name": "Acme"},
        },
    )
    identity, credential, message = run(NotionProvider().run_login())
    assert identity == "ws-1"
    assert credential["token"] == "ntok"  # legacy client key, accepted by build_client
    assert credential["workspace_name"] == "Acme"
    assert NotionProvider().identity_of(credential) == identity
    assert "Acme" in message
    assert captured["extra"] == {"owner": "user"}  # same as the legacy flow


def test_hubspot_run_login_introspects_hub_id(monkeypatch):
    patch_flow(
        monkeypatch,
        {"access_token": "hs-at", "refresh_token": "hs-rt", "expires_in": 1800, "userinfo": {}, "raw": {}},
    )
    import craftos_integrations.providers.hubspot.provider as hs

    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(url)
        return {"result": {"hub_id": 12345, "hub_domain": "acme.hubspot.com", "user": "me@acme.com"}}

    monkeypatch.setattr(hs, "http_request", fake_request)
    identity, credential, message = run(HubSpotProvider().run_login())
    assert identity == "12345"
    assert credential["hub_id"] == "12345"
    assert credential["auth_kind"] == "oauth"
    assert credential["user_email"] == "me@acme.com"
    assert "acme.hubspot.com" in message
    assert any("access-tokens/hs-at" in url for url in calls)


def test_hubspot_run_login_survives_failed_introspection(monkeypatch):
    patch_flow(
        monkeypatch,
        {"access_token": "hs-at", "refresh_token": "hs-rt", "expires_in": 1800, "userinfo": {}, "raw": {}},
    )
    import craftos_integrations.providers.hubspot.provider as hs

    monkeypatch.setattr(hs, "http_request", lambda *a, **k: {"error": "HTTP 500"})
    identity, credential, message = run(HubSpotProvider().run_login())
    assert identity is None
    assert credential is not None  # the token itself is valid — keep it
    assert credential["access_token"] == "hs-at"
    assert "without an account identity" in message


def test_slack_run_login_team_identity(monkeypatch):
    patch_flow(
        monkeypatch,
        {
            "access_token": "xoxb-1",
            "refresh_token": "",
            "expires_in": 0,
            "userinfo": {},
            "raw": {"ok": True, "access_token": "xoxb-1", "team": {"id": "T123", "name": "Acme"}},
        },
    )
    identity, credential, message = run(SlackProvider().run_login())
    assert identity == "t123"
    assert credential["bot_token"] == "xoxb-1"
    assert credential["workspace_id"] == "T123"
    assert "Acme" in message


def test_slack_run_login_surfaces_ok_false(monkeypatch):
    patch_flow(
        monkeypatch,
        {
            "access_token": "",
            "refresh_token": "",
            "expires_in": 0,
            "userinfo": {},
            "raw": {"ok": False, "error": "invalid_code"},
        },
    )
    identity, credential, message = run(SlackProvider().run_login())
    assert identity is None and credential is None
    assert "invalid_code" in message


def test_run_login_oauth_error_fails_cleanly(monkeypatch):
    patch_flow(monkeypatch, {"error": "access_denied"})
    for provider in (OutlookProvider(), LinkedInProvider(), NotionProvider(), SlackProvider()):
        identity, credential, message = run(provider.run_login())
        assert identity is None and credential is None
        assert "access_denied" in message


# ════════════════════════════════════════════════════════════════════════
# IntegrationSystem.add_account
# ════════════════════════════════════════════════════════════════════════


class LoginFakeProvider(FakeProvider):
    """FakeProvider with a canned run_login result."""

    def __init__(self, pid, login_result):
        super().__init__(pid)
        self.login_result = login_result

    async def run_login(self):
        return self.login_result


def make_system(tmp_path, *providers):
    return IntegrationSystem(store=FileCredentialStore(root=tmp_path), providers=list(providers))


def test_add_account_success_stores_and_lists(tmp_path):
    provider = LoginFakeProvider(
        "slack", ("t1", {"email": "t1", "bot_token": "xoxb"}, "Slack connected")
    )
    system = make_system(tmp_path, provider)
    ok, message, accounts = run(system.add_account("slack"))
    assert ok is True
    assert message == "Slack connected"
    assert [a.identity for a in accounts] == ["t1"]
    assert accounts[0].is_primary
    # The integration system writes ONLY the AccountSet document — no legacy mirror file.
    assert (tmp_path / "slack.accounts.json").exists()
    assert not (tmp_path / "slack.json").exists()


def test_add_account_failure_returns_current_accounts(tmp_path):
    provider = LoginFakeProvider("slack", (None, None, "Slack OAuth failed: denied"))
    system = make_system(tmp_path, provider)
    system.store_credential("slack", "t0", cred("t0"))
    ok, message, accounts = run(system.add_account("slack"))
    assert ok is False
    assert "denied" in message
    assert [a.identity for a in accounts] == ["t0"]  # untouched


def test_add_account_identityless_stores_legacy_sentinel(tmp_path):
    provider = LoginFakeProvider("linkedin", (None, {"access_token": "at"}, "connected"))
    system = make_system(tmp_path, provider)
    ok, message, accounts = run(system.add_account("linkedin"))
    assert ok is True
    assert [a.identity for a in accounts] == [UNIDENTIFIED]


def test_add_account_without_run_login_raises(tmp_path):
    system = make_system(tmp_path, FakeProvider("gmail"))
    with pytest.raises(LookupError, match="interactive login"):
        run(system.add_account("gmail"))
    with pytest.raises(LookupError, match="Unknown integration"):
        run(system.add_account("github"))
