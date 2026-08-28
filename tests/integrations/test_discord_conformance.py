"""Discord bridge-provider conformance + binding/verify tests.

No network: verify_token's HTTP is monkeypatched. What's real is
conformance, the credential binding, identity extraction, and the
token-verification flow mirroring the legacy DiscordHandler.login().
"""

from __future__ import annotations

import craftos_integrations.providers.discord.provider as discord_mod
from craftos_integrations.providers.discord import DiscordProvider
from craftos_integrations.providers.discord.provider import BoundDiscordClient
from craftos_integrations.providers._shared import ClientListenerAdapter

from .conformance import ProviderConformance

# Realistic SHAPE, fake values — asdict(DiscordCredential) as verify_token
# builds it after a successful GET /users/@me with the bot token.
DISCORD_CRED = {
    "bot_token": "MTAwFakeBotTokenFakeBotToken.GfAkE.FakeSignatureFakeSignature",
    "user_token": "",
    "bot_id": "1234567890123456789",
    "bot_username": "craftbot",
}


class TestDiscordConformance(ProviderConformance):
    provider = DiscordProvider()
    credential_fixtures = [
        DISCORD_CRED,  # real post-verify shape (bot id captured)
        # pre-bridge raw-token credential saved before the id was cached
        {"bot_token": "MTAwOldToken.x.y", "bot_id": "", "bot_username": ""},
        {},  # junk — must not raise
    ]


def test_identity_is_lowercased_bot_id():
    provider = DiscordProvider()
    assert provider.identity_of(DISCORD_CRED) == "1234567890123456789"
    assert provider.identity_of({"bot_id": "  987654321  "}) == "987654321"
    assert provider.identity_of({"bot_token": "MTAwOld.x.y"}) is None
    assert provider.identity_of({"bot_id": ""}) is None
    assert provider.identity_of({"bot_id": "   "}) is None
    assert provider.identity_of({"bot_id": 123}) is None  # non-str tolerated


def test_oauth_spec_declares_token_only():
    provider = DiscordProvider()
    try:
        provider.oauth_spec()
    except NotImplementedError:
        pass
    else:
        raise AssertionError("discord must declare token-only via NotImplementedError")
    assert not hasattr(provider, "run_login")  # no OAuth add-account flow


def test_binding_replaces_disk_plumbing():
    client = BoundDiscordClient()
    client.bind_credential(dict(DISCORD_CRED, extra_junk_key="ignored"), lambda c: None)
    assert client.has_credentials()
    cred = client._load()
    assert cred.bot_token == DISCORD_CRED["bot_token"]
    assert cred.bot_id == DISCORD_CRED["bot_id"]
    assert cred.bot_username == "craftbot"


def test_build_client_binds_credential():
    client = DiscordProvider().build_client(DISCORD_CRED, lambda c: None)
    assert isinstance(client, BoundDiscordClient)
    assert client._load().bot_token == DISCORD_CRED["bot_token"]


def test_bridge_surface_is_empty():
    provider = DiscordProvider()
    assert provider.operations() == []
    assert provider.guidance() == ""


def test_make_listener_wraps_legacy_gateway_loop():
    async def emit(event):
        pass

    provider = DiscordProvider()
    client = provider.build_client(DISCORD_CRED, lambda c: None)
    assert client.supports_listening  # gateway websocket loop
    listener = provider.make_listener(client, None, emit)
    assert isinstance(listener, ClientListenerAdapter)
    assert hasattr(listener, "start") and hasattr(listener, "stop")
    assert listener.cursor() is None  # legacy loop keeps watermarks in memory


def test_verify_token_rejects_missing_token():
    provider = DiscordProvider()
    ok, msg, cred = provider.verify_token({})
    assert not ok and cred is None
    ok, msg, cred = provider.verify_token({"bot_token": "   "})
    assert not ok and cred is None


def test_verify_token_success_captures_bot_id(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "GET" and url.endswith("/users/@me")
        assert kwargs["headers"]["Authorization"] == "Bot MTAwFake.x.y"
        return {
            "ok": True,
            "result": {"id": "424242424242", "username": "CraftBot", "bot": True},
        }

    monkeypatch.setattr(discord_mod, "http_request", fake_request)
    provider = DiscordProvider()
    ok, msg, cred = provider.verify_token({"bot_token": " MTAwFake.x.y "})
    assert ok, msg
    assert cred["bot_token"] == "MTAwFake.x.y"
    assert cred["bot_id"] == "424242424242"
    assert cred["bot_username"] == "CraftBot"
    assert cred["user_token"] == ""
    assert "CraftBot" in msg
    assert provider.identity_of(cred) == "424242424242"


def test_verify_token_passes_optional_user_token_through(monkeypatch):
    def fake_request(method, url, **kwargs):
        return {"ok": True, "result": {"id": "77", "username": "CraftBot"}}

    monkeypatch.setattr(discord_mod, "http_request", fake_request)
    ok, msg, cred = DiscordProvider().verify_token(
        {"bot_token": "MTAwFake.x.y", "user_token": " user_tok_123 "}
    )
    assert ok, msg
    assert cred["user_token"] == "user_tok_123"  # stored, never verified


def test_verify_token_auth_failure(monkeypatch):
    def fake_request(method, url, **kwargs):
        return {"error": "HTTP 401", "details": "401 Unauthorized"}

    monkeypatch.setattr(discord_mod, "http_request", fake_request)
    ok, msg, cred = DiscordProvider().verify_token({"bot_token": "MTAwBad.x.y"})
    assert not ok and cred is None and "Invalid Discord bot token" in msg
