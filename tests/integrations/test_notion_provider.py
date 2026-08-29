"""Notion provider — conformance + wiring.

No network: the client API method is stubbed. What's real is the full
chain execute() → resolve → bind → client method → shaped result.
"""

from __future__ import annotations

import asyncio

from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.notion import NotionProvider
from craftos_integrations.providers.notion.provider import BoundNotionClient

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


# Real OAuth-response shape (workspace-scoped token; no expiry fields).
NOTION_CRED = {
    "access_token": "secret-at-1",
    "workspace_id": "WS-1234-ABCD",  # mixed case: identity must lowercase it
    "workspace_name": "Acme",
    "bot_id": "Bot-99",
}

# Pre-multi-account notion.json shape — token only, no identity → UNIDENTIFIED.
LEGACY_CRED = {"token": "secret_legacytoken"}


class TestNotionConformance(ProviderConformance):
    provider = NotionProvider()
    credential_fixtures = [
        NOTION_CRED,
        LEGACY_CRED,  # identity-less pre-multi-account shape → None
        {},  # junk
    ]


def test_identity_is_workspace_id_lowercased():
    provider = NotionProvider()
    assert provider.identity_of(NOTION_CRED) == "ws-1234-abcd"
    # bot id is the fallback when workspace id is missing
    assert provider.identity_of({"bot_id": "Bot-99"}) == "bot-99"
    assert provider.identity_of(LEGACY_CRED) is None  # → UNIDENTIFIED in core


def test_oauth_spec_is_the_native_workspace_picker():
    spec = NotionProvider().oauth_spec()
    assert spec.authorize_url == "https://api.notion.com/v1/oauth/authorize"
    assert spec.token_url == "https://api.notion.com/v1/oauth/token"
    assert spec.extra_authorize_params["owner"] == "user"
    assert spec.has_chooser  # Notion's authorize page picks the workspace


def test_refresh_is_none_tokens_do_not_expire():
    assert run(NotionProvider().refresh(dict(NOTION_CRED))) is None


def test_binding_accepts_both_token_key_shapes():
    client = BoundNotionClient()
    assert not client.has_credentials()  # no disk fallback
    client.bind_credential(dict(NOTION_CRED), lambda c: None)
    assert client.has_credentials()
    assert client._load().token == "secret-at-1"

    legacy_client = BoundNotionClient()
    legacy_client.bind_credential(dict(LEGACY_CRED), lambda c: None)
    assert legacy_client._load().token == "secret_legacytoken"


def test_execute_runs_operation_against_resolved_accounts_client(tmp_path, monkeypatch):
    system = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path), providers=[NotionProvider()]
    )
    system.store_credential("notion", "ws-1234-abcd", dict(NOTION_CRED))
    system.store_credential(
        "notion",
        "ws-other",
        {**NOTION_CRED, "workspace_id": "ws-other", "access_token": "secret-at-2"},
    )
    system.set_alias("notion", "ws-other", "company")

    seen = []

    def fake_search(self, query, filter_type=None, page_size=100):
        seen.append((self._cred.token, query, filter_type))
        return [
            {
                "id": "p1",
                "object": "page",
                "url": "https://notion.so/p1",
                "properties": {
                    "Name": {"type": "title", "title": [{"plain_text": "Roadmap"}]}
                },
            }
        ]

    monkeypatch.setattr(BoundNotionClient, "search", fake_search)

    result = run(
        system.execute(
            "notion", "search_notion", {"query": "roadmap"}, account="company"
        )
    )
    assert result["status"] == "success"
    # lean shaping (default include_metadata=False) mirrors the legacy action
    assert result["result"] == [
        {
            "id": "p1",
            "object": "page",
            "title": "Roadmap",
            "url": "https://notion.so/p1",
        }
    ]
    assert seen == [("secret-at-2", "roadmap", None)]  # company workspace's client

    run(system.execute("notion", "search_notion", {"query": "roadmap"}))
    assert seen[-1] == ("secret-at-1", "roadmap", None)  # primary by default
