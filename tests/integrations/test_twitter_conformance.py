"""Twitter/X bridge provider — conformance + binding wiring.

No network: HTTP and the legacy poll loop are stubbed. What's real is the
binding chain bind_credential → _load → _auth_header, the start_listening
user_id/username backfill routed through persist instead of the legacy
file, and the token-verification flow mirroring the legacy
TwitterHandler.login() (OAuth 1.0a-signed GET /2/users/me).
"""

from __future__ import annotations

import asyncio

from craftos_integrations.providers.twitter.client import TwitterClient
from craftos_integrations.providers._shared import ClientListenerAdapter
from craftos_integrations.providers.twitter import TwitterProvider
from craftos_integrations.providers.twitter.provider import BoundTwitterClient

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


# Real twitter.json shape after a legacy /twitter login (all four OAuth 1.0a
# values + user id/username captured from GET /2/users/me).
TWITTER_CRED = {
    "api_key": "fakeConsumerKey123",
    "api_secret": "fakeConsumerSecret456",
    "access_token": "1234567890-fakeAccessToken",
    "access_token_secret": "fakeAccessTokenSecret789",
    "user_id": "1234567890123456789",
    "username": "CraftBot",
}

# Tokens saved before user id/username were captured — no identity.
LEGACY_CRED = {
    "api_key": "fakeConsumerKey123",
    "api_secret": "fakeConsumerSecret456",
    "access_token": "1234567890-fakeAccessToken",
    "access_token_secret": "fakeAccessTokenSecret789",
    "user_id": "",
    "username": "",
}


class TestTwitterConformance(ProviderConformance):
    provider = TwitterProvider()
    credential_fixtures = [
        TWITTER_CRED,
        LEGACY_CRED,  # identity-less shape → None
        {},  # junk
    ]


def test_identity_prefers_user_id_falls_back_to_username():
    provider = TwitterProvider()
    # Numeric user id is the stable key (survives handle renames).
    assert provider.identity_of(TWITTER_CRED) == "1234567890123456789"
    assert provider.identity_of({"user_id": " 42 ", "username": "Whatever"}) == "42"
    # Pre-bridge credential without a user id: username, lowercased.
    assert provider.identity_of({"user_id": "", "username": "  CraftBot  "}) == (
        "craftbot"
    )
    assert provider.identity_of(LEGACY_CRED) is None  # → UNIDENTIFIED in core
    assert provider.identity_of({"user_id": 42}) is None  # junk never raises
    assert provider.identity_of({"username": 42}) is None


def test_token_only_no_oauth_no_run_login():
    provider = TwitterProvider()
    try:
        provider.oauth_spec()
        raise AssertionError("oauth_spec must raise NotImplementedError")
    except NotImplementedError:
        pass
    assert not hasattr(provider, "run_login")


def test_refresh_is_none_oauth1_tokens_do_not_expire():
    assert run(TwitterProvider().refresh(dict(TWITTER_CRED))) is None


def test_bridge_surface_is_empty():
    provider = TwitterProvider()
    assert provider.operations() == []
    assert provider.guidance() == ""


def test_binding_injects_credential_and_signs_headers():
    provider = TwitterProvider()
    client = provider.build_client(
        {**TWITTER_CRED, "stray_key": "ignored"}, lambda c: None
    )
    assert isinstance(client, BoundTwitterClient)
    assert client.has_credentials()  # no disk fallback
    cred = client._load()
    assert cred.api_key == TWITTER_CRED["api_key"]
    assert cred.access_token_secret == TWITTER_CRED["access_token_secret"]
    # The OAuth 1.0a signature is built from the bound credential.
    header = client._auth_header("GET", "https://api.twitter.com/2/users/me")
    assert header["Authorization"].startswith("OAuth ")
    assert "fakeConsumerKey123" in header["Authorization"]

    unbound = BoundTwitterClient()
    assert not unbound.has_credentials()


def test_make_listener_wraps_the_legacy_poll_loop():
    provider = TwitterProvider()
    client = provider.build_client(dict(TWITTER_CRED), lambda c: None)

    async def emit(event):
        pass

    listener = provider.make_listener(client, None, emit)
    assert isinstance(listener, ClientListenerAdapter)
    assert client.supports_listening
    # Poll watermarks are instance state — two bound accounts don't collide.
    other = provider.build_client(dict(TWITTER_CRED), lambda c: None)
    client._since_id = "111"
    assert other._since_id is None
    assert client._seen_ids is not other._seen_ids


def test_start_listening_backfills_identity_via_persist(monkeypatch):
    """The legacy save_credential at ~line 340 (user_id/username backfill)
    must never fire for a bound client — the update goes through persist."""
    persisted = []
    provider = TwitterProvider()
    client = provider.build_client(dict(LEGACY_CRED), persisted.append)

    async def fake_get_me(self):
        return {
            "ok": True,
            "result": {"id": "1234567890123456789", "username": "CraftBot"},
        }

    started = []

    async def fake_super_start(self, callback):
        started.append(callback)

    monkeypatch.setattr(BoundTwitterClient, "get_me", fake_get_me)
    monkeypatch.setattr(TwitterClient, "start_listening", fake_super_start)

    async def callback(msg):
        pass

    run(client.start_listening(callback))
    assert started == [callback]  # delegated to the legacy loop
    assert persisted == [
        dict(LEGACY_CRED, user_id="1234567890123456789", username="CraftBot")
    ]
    assert client._load().user_id == "1234567890123456789"
    assert client._load().username == "CraftBot"

    # Second start with a synced identity: no further persist.
    run(client.start_listening(callback))
    assert len(persisted) == 1


def test_verify_token_mirrors_legacy_login(monkeypatch):
    provider = TwitterProvider()
    calls = []

    def fake_request(method, url, headers=None, params=None, expected=None, **kwargs):
        calls.append((method, url, headers, params))
        return {
            "ok": True,
            "result": {
                "data": {
                    "id": "1234567890123456789",
                    "name": "Craft Bot",
                    "username": "CraftBot",
                }
            },
        }

    monkeypatch.setattr(
        "craftos_integrations.providers.twitter.provider.http_request", fake_request
    )
    ok, message, credential = provider.verify_token(
        {
            "api_key": " fakeConsumerKey123 ",
            "api_secret": "fakeConsumerSecret456",
            "access_token": "1234567890-fakeAccessToken",
            "access_token_secret": "fakeAccessTokenSecret789",
        }
    )
    assert ok
    assert "@CraftBot" in message
    assert credential == TWITTER_CRED  # whitespace stripped, identity captured
    assert provider.identity_of(credential) == "1234567890123456789"
    method, url, headers, params = calls[0]
    assert (method, url) == ("GET", "https://api.twitter.com/2/users/me")
    assert params == {"user.fields": "id,name,username"}
    # Signed with the legacy module's own OAuth 1.0a helper.
    assert headers["Authorization"].startswith("OAuth ")
    assert "oauth_consumer_key" in headers["Authorization"]
    assert "oauth_signature=" in headers["Authorization"]


def test_verify_token_failure_paths(monkeypatch):
    provider = TwitterProvider()

    ok, message, credential = provider.verify_token({})
    assert not ok and credential is None
    assert "api_key" in message and "access_token_secret" in message

    # Partial input names only the missing keys.
    ok, message, credential = provider.verify_token(
        {"api_key": "k", "api_secret": "s", "access_token": "t"}
    )
    assert not ok and credential is None
    assert "access_token_secret" in message and " api_key" not in message

    monkeypatch.setattr(
        "craftos_integrations.providers.twitter.provider.http_request",
        lambda *a, **k: {"error": "HTTP 401", "details": "Unauthorized"},
    )
    ok, message, credential = provider.verify_token(
        {
            "api_key": "k",
            "api_secret": "s",
            "access_token": "t",
            "access_token_secret": "ts",
        }
    )
    assert not ok and credential is None
    assert "Twitter auth failed" in message
