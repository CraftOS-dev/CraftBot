"""Slack provider — the first non-Google provider.

No network: client API methods are stubbed. What's real is conformance,
the credential binding, and the full chain execute() → resolve → bind →
client method → shaped result (incl. the legacy pick_result shaping).
"""

from __future__ import annotations

import asyncio

import pytest

from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.slack import SlackProvider
from craftos_integrations.providers.slack.provider import BoundSlackClient

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


SLACK_CRED = {
    "bot_token": "xoxb-acme-token",
    "workspace_id": "T0AB12CD3",
    "team_name": "Acme",
}


class TestSlackConformance(ProviderConformance):
    provider = SlackProvider()
    credential_fixtures = [
        SLACK_CRED,  # real OAuth/login shape (team id captured)
        {"bot_token": "xoxb-old-token"},  # pre-identity legacy shape → None
        {},  # junk — must not raise
    ]


def test_identity_is_lowercased_team_id():
    provider = SlackProvider()
    assert provider.identity_of(SLACK_CRED) == "t0ab12cd3"
    assert provider.identity_of({"bot_token": "xoxb-old-token"}) is None
    assert provider.identity_of({"workspace_id": "   "}) is None


def test_oauth_spec_matches_legacy_handler():
    spec = SlackProvider().oauth_spec()
    assert spec.authorize_url == "https://slack.com/oauth/v2/authorize"
    assert spec.token_url == "https://slack.com/api/oauth.v2.access"
    assert "chat:write" in spec.scopes and "channels:read" in spec.scopes
    assert spec.has_chooser  # Slack's authorize page has a workspace picker


def test_binding_replaces_disk_plumbing():
    client = BoundSlackClient()
    assert not client.has_credentials()  # no disk fallback
    client.bind_credential(SLACK_CRED, lambda c: None)
    assert client.has_credentials()
    assert client._load().bot_token == "xoxb-acme-token"
    assert client._load().workspace_id == "T0AB12CD3"


def test_refresh_is_a_noop_for_non_expiring_tokens():
    assert run(SlackProvider().refresh(dict(SLACK_CRED))) is None


@pytest.fixture
def system(tmp_path):
    sys = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path), providers=[SlackProvider()]
    )
    sys.store_credential("slack", "t0ab12cd3", dict(SLACK_CRED))
    sys.store_credential(
        "slack",
        "t9zz99xy8",
        {
            "bot_token": "xoxb-beta-token",
            "workspace_id": "T9ZZ99XY8",
            "team_name": "Beta",
        },
    )
    sys.set_alias("slack", "t9zz99xy8", "beta")
    return sys


def test_execute_runs_operation_against_resolved_workspaces_client(system, monkeypatch):
    seen = []

    async def fake_send_message(self, recipient, text, **kwargs):
        seen.append((self._cred.workspace_id, recipient, text, kwargs.get("thread_ts")))
        # Slack-style body: "ok" sits alongside the payload fields.
        return {
            "ok": True,
            "channel": recipient,
            "ts": "111.222",
            "message": {"text": text},
        }

    monkeypatch.setattr(BoundSlackClient, "send_message", fake_send_message)

    result = run(
        system.execute(
            "slack",
            "send_slack_message",
            {"channel": "C1", "text": "hi"},
            account="beta",
        )
    )
    # ok-envelope collapsed + legacy pick_result(["channel", "ts"]) shaping.
    assert result == {"status": "success", "result": {"channel": "C1", "ts": "111.222"}}
    assert seen == [("T9ZZ99XY8", "C1", "hi", None)]  # beta workspace's client

    run(system.execute("slack", "send_slack_message", {"channel": "C2", "text": "yo"}))
    assert seen[-1][0] == "T0AB12CD3"  # primary workspace by default


def test_operation_error_shape_is_agent_friendly(system, monkeypatch):
    async def fake_send_message(self, recipient, text, **kwargs):
        return {"error": "not_in_channel", "details": {"ok": False}}

    monkeypatch.setattr(BoundSlackClient, "send_message", fake_send_message)
    result = run(
        system.execute(
            "slack",
            "send_slack_message",
            {"channel": "C1", "text": "hi"},
            account="t0ab12cd3",
        )
    )
    assert result["status"] == "error"
    assert "not_in_channel" in result["message"]
