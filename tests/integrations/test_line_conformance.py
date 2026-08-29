"""LINE provider — conformance + wiring.

No network: verify_token's HTTP call is monkeypatched. What's real is
the bridge contract — token-only OAuth declaration, per-account credential
binding, bot-user-id identity, and the no-listener declaration (LINE is
webhook-push only).
"""

from __future__ import annotations

import asyncio

import pytest

from craftos_integrations.providers.line import LineProvider
from craftos_integrations.providers.line.provider import BoundLineClient

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


# Real credential shape as verify_token stores it (bot user id captured
# from GET /v2/bot/info at verify time; mixed case: identity must lowercase it).
LINE_CRED = {
    "channel_access_token": "test-channel-token-1",
    "channel_secret": "test-channel-secret-1",
    "bot_user_id": "Ub1234ABCDEF9876",
    "bot_display_name": "CraftBot",
}

# Pre-identity-capture shape — token only, no bot user id → UNIDENTIFIED.
LEGACY_CRED = {"channel_access_token": "test-old-token"}


class TestLineConformance(ProviderConformance):
    provider = LineProvider()
    credential_fixtures = [
        LINE_CRED,
        LEGACY_CRED,  # identity-less shape → None
        {},  # junk
    ]


def test_identity_is_bot_user_id_lowercased():
    provider = LineProvider()
    assert provider.identity_of(LINE_CRED) == "ub1234abcdef9876"
    assert provider.identity_of(LEGACY_CRED) is None  # → UNIDENTIFIED in core
    # junk shapes never raise
    assert provider.identity_of({"bot_user_id": "   "}) is None
    assert provider.identity_of({"bot_user_id": 123}) is None


def test_oauth_spec_declares_token_only():
    with pytest.raises(NotImplementedError):
        LineProvider().oauth_spec()
    assert not hasattr(LineProvider(), "run_login")


def test_refresh_is_none_tokens_do_not_expire():
    assert run(LineProvider().refresh(dict(LINE_CRED))) is None


def test_bridge_surface_is_empty():
    provider = LineProvider()
    assert provider.operations() == []
    assert provider.guidance() == ""


def test_no_listener_line_is_webhook_push_only():
    async def emit(event):
        pass

    provider = LineProvider()
    client = provider.build_client(dict(LINE_CRED), lambda c: None)
    assert client.supports_listening is False  # legacy client declaration
    assert provider.make_listener(client, None, emit) is None


def test_binding_injects_credential_and_ignores_extra_keys():
    client = BoundLineClient()
    assert not client.has_credentials()  # no disk fallback
    client.bind_credential({**LINE_CRED, "stray_key": "x"}, lambda c: None)
    assert client.has_credentials()
    cred = client._load()
    assert cred.channel_access_token == "test-channel-token-1"
    assert cred.bot_user_id == "Ub1234ABCDEF9876"
    # the auth header the legacy REST methods build uses the bound token
    assert client._headers()["Authorization"] == "Bearer test-channel-token-1"


def test_verify_token_mirrors_legacy_login(monkeypatch):
    """Same check as LineHandler.login(): GET /v2/bot/info with the token;
    the bot's userId lands in the credential so identity_of works."""
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("headers", {})))
        return {"result": {"userId": "Ub1234ABCDEF9876", "displayName": "CraftBot"}}

    monkeypatch.setattr(
        "craftos_integrations.providers.line.provider.http_request", fake_request
    )
    provider = LineProvider()
    ok, message, credential = provider.verify_token(
        {
            "channel_access_token": " test-channel-token-1 ",
            "channel_secret": "test-channel-secret-1",
        }
    )
    assert ok and credential is not None
    assert "CraftBot" in message
    assert credential == LINE_CRED  # stored shape == fixture shape
    assert provider.identity_of(credential) == "ub1234abcdef9876"

    method, url, headers = calls[0]
    assert method == "GET"
    assert url == "https://api.line.me/v2/bot/info"
    assert headers["Authorization"] == "Bearer test-channel-token-1"


def test_verify_token_rejects_bad_or_missing_token(monkeypatch):
    provider = LineProvider()

    ok, message, credential = provider.verify_token({})
    assert not ok and credential is None

    monkeypatch.setattr(
        "craftos_integrations.providers.line.provider.http_request",
        lambda *a, **k: {"error": "HTTP 401"},
    )
    ok, message, credential = provider.verify_token(
        {"channel_access_token": "bad-token"}
    )
    assert not ok and credential is None
    assert "Invalid channel access token" in message
