"""YouTube provider — conformance + one end-to-end wiring check.

No network: the client API method is stubbed. What's real is the chain
execute() → resolve → bind → client method → shaped (lean) result.
"""

from __future__ import annotations

import asyncio

import pytest

from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.google_youtube import GoogleYoutubeProvider
from craftos_integrations.providers.google_youtube.provider import (
    BoundGoogleYoutubeClient,
)

from .conformance import ProviderConformance


def run(coro):
    return asyncio.run(coro)


GOOGLE_CRED = {
    "access_token": "at-1",
    "refresh_token": "rt-1",
    "token_expiry": 1e12,  # far future: no refresh during normal calls
    "client_id": "cid",
    "client_secret": "csec",
    "email": "a@x.com",
}


class TestGoogleYoutubeConformance(ProviderConformance):
    provider = GoogleYoutubeProvider()
    credential_fixtures = [
        GOOGLE_CRED,
        {"access_token": "at", "email": "  User@X.com "},  # messy legacy shape
        {"access_token": "at"},  # identity-less pre-multi-account shape → None
    ]


@pytest.fixture
def system(tmp_path):
    sys = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path), providers=[GoogleYoutubeProvider()]
    )
    sys.store_credential("google_youtube", "a@x.com", dict(GOOGLE_CRED))
    sys.store_credential(
        "google_youtube",
        "b@y.com",
        {**GOOGLE_CRED, "email": "b@y.com", "access_token": "at-b"},
    )
    sys.set_alias("google_youtube", "b@y.com", "creator")
    return sys


def test_execute_runs_search_against_resolved_accounts_client(system, monkeypatch):
    seen = []

    def fake_search(self, query, max_results=25, type_filter="video"):
        seen.append((self._cred.email, query, max_results, type_filter))
        return {
            "ok": True,
            "result": [
                {
                    "id": {"videoId": "vid-1"},
                    "snippet": {
                        "title": "T",
                        "channelTitle": "C",
                        "publishedAt": "2026-01-01T00:00:00Z",
                        "description": "D",
                    },
                }
            ],
        }

    monkeypatch.setattr(BoundGoogleYoutubeClient, "search", fake_search)

    result = run(
        system.execute(
            "google_youtube",
            "search_youtube",
            {"query": "cats", "max_results": 3},
            account="creator",
        )
    )
    # creator account's client, mapped args (type → type_filter, defaults)
    assert seen == [("b@y.com", "cats", 3, "video")]
    # lean shaping applied (no include_metadata)
    assert result == {
        "status": "success",
        "result": [
            {
                "videoId": "vid-1",
                "title": "T",
                "channelTitle": "C",
                "publishedAt": "2026-01-01T00:00:00Z",
                "description": "D",
            }
        ],
    }

    raw = run(
        system.execute(
            "google_youtube",
            "search_youtube",
            {"query": "cats", "include_metadata": True},
        )
    )
    assert seen[-1] == ("a@x.com", "cats", 25, "video")  # primary + defaults
    assert raw["result"][0]["id"] == {"videoId": "vid-1"}  # raw passthrough
