"""Google Drive provider — conformance + one end-to-end wiring check.

No network: the client API method is stubbed. What's real is the chain
execute() → resolve → bind → client method → shaped result.
"""

from __future__ import annotations

import asyncio

import pytest

from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.google_drive import GoogleDriveProvider
from craftos_integrations.providers.google_drive.provider import BoundGoogleDriveClient

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


class TestGoogleDriveConformance(ProviderConformance):
    provider = GoogleDriveProvider()
    credential_fixtures = [
        GOOGLE_CRED,
        {"access_token": "at", "email": "  User@X.com "},  # messy legacy shape
        {"access_token": "at"},  # identity-less pre-multi-account shape → None
    ]


@pytest.fixture
def system(tmp_path):
    sys = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path), providers=[GoogleDriveProvider()]
    )
    sys.store_credential("google_drive", "a@x.com", dict(GOOGLE_CRED))
    sys.store_credential(
        "google_drive",
        "b@y.com",
        {**GOOGLE_CRED, "email": "b@y.com", "access_token": "at-b"},
    )
    sys.set_alias("google_drive", "b@y.com", "work")
    return sys


def test_execute_runs_search_against_resolved_accounts_client(system, monkeypatch):
    seen = []

    def fake_search(self, query, max_results=50, fields=None):
        seen.append((self._cred.email, query, max_results))
        return {"ok": True, "result": [{"id": "f1", "name": "budget.pdf"}]}

    monkeypatch.setattr(BoundGoogleDriveClient, "search_drive", fake_search)

    result = run(
        system.execute(
            "google_drive",
            "search_drive_files",
            {"query": "name contains 'budget'", "max_results": 5},
            account="work",
        )
    )
    # work account's client, mapped args (query passthrough, max_results)
    assert seen == [("b@y.com", "name contains 'budget'", 5)]
    assert result == {
        "status": "success",
        "result": [{"id": "f1", "name": "budget.pdf"}],
    }

    run(system.execute("google_drive", "search_drive_files", {"query": "q2"}))
    assert seen[-1] == ("a@x.com", "q2", 50)  # primary + legacy default of 50
