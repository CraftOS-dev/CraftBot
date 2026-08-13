"""Google Docs provider — conformance + one end-to-end wiring check.

No network: the client API method is stubbed. What's real is the chain
execute() → resolve → bind → client method → shaped result.
"""

from __future__ import annotations

import asyncio

import pytest

from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.google_docs import GoogleDocsProvider
from craftos_integrations.providers.google_docs.provider import BoundGoogleDocsClient

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


class TestGoogleDocsConformance(ProviderConformance):
    provider = GoogleDocsProvider()
    credential_fixtures = [
        GOOGLE_CRED,
        {"access_token": "at", "email": "  User@X.com "},  # messy legacy shape
        {"access_token": "at"},  # identity-less pre-multi-account shape → None
    ]


@pytest.fixture
def system(tmp_path):
    sys = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path), providers=[GoogleDocsProvider()]
    )
    sys.store_credential("google_docs", "a@x.com", dict(GOOGLE_CRED))
    sys.store_credential(
        "google_docs",
        "b@y.com",
        {**GOOGLE_CRED, "email": "b@y.com", "access_token": "at-b"},
    )
    sys.set_alias("google_docs", "b@y.com", "school")
    return sys


def test_execute_runs_search_against_resolved_accounts_client(system, monkeypatch):
    seen = []

    def fake_search(self, query, max_results=50):
        seen.append((self._cred.email, query, max_results))
        return {
            "ok": True,
            "result": [{"id": "doc-1", "name": "Meeting Notes"}],
        }

    monkeypatch.setattr(BoundGoogleDocsClient, "search_documents", fake_search)

    result = run(
        system.execute(
            "google_docs",
            "search_google_docs",
            {"query": "Meeting", "max_results": 3},
            account="school",
        )
    )
    # school account's client, mapped args
    assert seen == [("b@y.com", "Meeting", 3)]
    assert result == {
        "status": "success",
        "result": [{"id": "doc-1", "name": "Meeting Notes"}],
    }

    run(system.execute("google_docs", "search_google_docs", {"query": "Meeting"}))
    assert seen[-1] == ("a@x.com", "Meeting", 50)  # primary + arg-map default
