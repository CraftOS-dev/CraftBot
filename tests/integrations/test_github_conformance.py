"""GitHub bridge provider — conformance + binding wiring.

No network: HTTP and the legacy poll loop are stubbed. What's real is the
binding chain bind_credential → _load → _headers and the start_listening
username backfill routed through persist instead of the legacy file.
"""

from __future__ import annotations

import asyncio

from craftos_integrations.integrations.github import GitHubClient
from craftos_integrations.providers._shared import LegacyListenerAdapter
from craftos_integrations.providers.github import GitHubProvider
from craftos_integrations.providers.github.provider import BoundGitHubClient

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


# Real github.json shape after a legacy /github login (PAT + captured login).
GITHUB_CRED = {
    "access_token": "ghp_abc123",
    "username": "OctoCat",  # mixed case: identity must lowercase it
}

# Token saved before the username was captured — no identity → LEGACY_IDENTITY.
LEGACY_CRED = {"access_token": "ghp_abc123", "username": ""}


class TestGitHubConformance(ProviderConformance):
    provider = GitHubProvider()
    credential_fixtures = [
        GITHUB_CRED,
        LEGACY_CRED,  # identity-less shape → None
        {},  # junk
    ]


def test_identity_is_username_lowercased():
    provider = GitHubProvider()
    assert provider.identity_of(GITHUB_CRED) == "octocat"
    assert provider.identity_of({"username": "  Hubber  "}) == "hubber"
    assert provider.identity_of(LEGACY_CRED) is None  # → LEGACY_IDENTITY in core
    assert provider.identity_of({"username": 42}) is None  # junk never raises


def test_token_only_no_oauth_no_run_login():
    provider = GitHubProvider()
    try:
        provider.oauth_spec()
        raise AssertionError("oauth_spec must raise NotImplementedError")
    except NotImplementedError:
        pass
    assert not hasattr(provider, "run_login")


def test_refresh_is_none_pats_do_not_rotate():
    assert run(GitHubProvider().refresh(dict(GITHUB_CRED))) is None


def test_bridge_surface_is_empty():
    provider = GitHubProvider()
    assert provider.operations() == []
    assert provider.guidance() == ""


def test_binding_injects_credential_and_headers():
    provider = GitHubProvider()
    client = provider.build_client(
        {**GITHUB_CRED, "stray_key": "ignored"}, lambda c: None
    )
    assert isinstance(client, BoundGitHubClient)
    assert client.has_credentials()  # no disk fallback
    assert client._load().access_token == "ghp_abc123"
    assert client._headers()["Authorization"] == "Bearer ghp_abc123"

    unbound = BoundGitHubClient()
    assert not unbound.has_credentials()


def test_make_listener_wraps_the_legacy_poll_loop():
    provider = GitHubProvider()
    client = provider.build_client(dict(GITHUB_CRED), lambda c: None)

    async def emit(event):
        pass

    listener = provider.make_listener(client, None, emit)
    assert isinstance(listener, LegacyListenerAdapter)
    assert client.supports_listening


def test_start_listening_backfills_username_via_persist(monkeypatch):
    """The legacy save_credential at ~line 284 (username backfill) must
    never fire for a bound client — the update goes through persist."""
    persisted = []
    provider = GitHubProvider()
    client = provider.build_client(dict(LEGACY_CRED), persisted.append)

    async def fake_user(self):
        return {"ok": True, "result": {"login": "OctoCat", "id": 1}}

    started = []

    async def fake_super_start(self, callback):
        started.append(callback)

    monkeypatch.setattr(BoundGitHubClient, "get_authenticated_user", fake_user)
    monkeypatch.setattr(GitHubClient, "start_listening", fake_super_start)

    async def callback(msg):
        pass

    run(client.start_listening(callback))
    assert started == [callback]  # delegated to the legacy loop
    assert persisted == [{"access_token": "ghp_abc123", "username": "OctoCat"}]
    assert client._load().username == "OctoCat"

    # Second start with a synced username: no further persist.
    run(client.start_listening(callback))
    assert len(persisted) == 1


def test_verify_token_mirrors_legacy_login(monkeypatch):
    provider = GitHubProvider()
    calls = []

    def fake_request(method, url, headers=None, expected=None, **kwargs):
        calls.append((method, url, headers))
        return {"ok": True, "result": {"login": "OctoCat", "name": "Octo Cat"}}

    monkeypatch.setattr(
        "craftos_integrations.providers.github.provider.http_request", fake_request
    )
    ok, message, credential = provider.verify_token({"access_token": " ghp_abc123 "})
    assert ok
    assert "OctoCat" in message
    assert credential == {"access_token": "ghp_abc123", "username": "OctoCat"}
    assert provider.identity_of(credential) == "octocat"
    method, url, headers = calls[0]
    assert (method, url) == ("GET", "https://api.github.com/user")
    assert headers["Authorization"] == "Bearer ghp_abc123"


def test_verify_token_failure_paths(monkeypatch):
    provider = GitHubProvider()

    ok, message, credential = provider.verify_token({})
    assert not ok and credential is None
    assert "github.com/settings/tokens" in message

    monkeypatch.setattr(
        "craftos_integrations.providers.github.provider.http_request",
        lambda *a, **k: {"error": "HTTP 401", "details": "Bad credentials"},
    )
    ok, message, credential = provider.verify_token({"access_token": "ghp_bad"})
    assert not ok and credential is None
    assert "GitHub auth failed" in message
