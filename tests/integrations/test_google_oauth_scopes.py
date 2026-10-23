"""Verify the submission contract against real Google OAuth URL builders."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from craftos_integrations.config import ConfigStore
from craftos_integrations.oauth_flow import OAuthFlow
from craftos_integrations.providers._google_common import make_google_oauth
from craftos_integrations.providers.gmail import GmailProvider
from craftos_integrations.providers.google_calendar import GoogleCalendarProvider
from craftos_integrations.providers.google_docs import GoogleDocsProvider
from craftos_integrations.providers.google_drive import GoogleDriveProvider
from craftos_integrations.providers.google_youtube import GoogleYoutubeProvider
from scripts.verify_google_oauth_scopes import audit

PROVIDERS = [
    GmailProvider(),
    GoogleCalendarProvider(),
    GoogleDocsProvider(),
    GoogleDriveProvider(),
    GoogleYoutubeProvider(),
]
MANIFEST = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "craftos_integrations/google_oauth_scopes.json"
    ).read_text("utf-8")
)


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda provider: provider.id)
def test_authorization_url_matches_submission_contract(provider, monkeypatch):
    monkeypatch.setattr(ConfigStore, "_oauth", {"GOOGLE_CLIENT_ID": "test-client-id"})
    flow = make_google_oauth(provider.scopes)
    flow.extra_auth_params = dict(provider.oauth_spec().extra_authorize_params)
    url, context = flow._build_auth_url()
    query = parse_qs(urlparse(url).query)
    expected = set(MANIFEST["services"][provider.id]) | set(MANIFEST["identity_scopes"])
    assert set(query["scope"][0].split()) == expected
    assert set(provider.oauth_spec().scopes) == expected
    assert query["code_challenge_method"] == ["S256"]
    assert context["state"] == query["state"][0]
    assert query["prompt"] == ["consent select_account"]


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda provider: provider.id)
def test_google_login_only_needs_email_identity(provider, monkeypatch):
    async def fake_run(self):
        return {
            "access_token": "test-token",
            "userinfo": {"email": "Reviewer@Example.com"},
        }

    monkeypatch.setattr(OAuthFlow, "run", fake_run)
    monkeypatch.setattr(ConfigStore, "_oauth", {"GOOGLE_CLIENT_ID": "test-client-id"})
    identity, credential, _message = asyncio.run(provider.run_login())
    assert identity == "reviewer@example.com"
    assert credential["email"] == "reviewer@example.com"


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda provider: provider.id)
def test_declined_google_consent_does_not_produce_credentials(provider, monkeypatch):
    async def fake_run(self):
        return {"error": "access_denied"}

    monkeypatch.setattr(OAuthFlow, "run", fake_run)
    identity, credential, message = asyncio.run(provider.run_login())
    assert identity is None
    assert credential is None
    assert "access_denied" in message


def test_manifest_is_exact_union_of_connector_requests():
    assert audit()["passed"]


def test_scope_audit_rejects_extra_console_permission(tmp_path):
    console = tmp_path / "scopes.txt"
    console.write_text(
        "\n".join(
            MANIFEST["console_scopes"]
            + ["https://www.googleapis.com/auth/contacts.readonly"]
        ),
        encoding="utf-8",
    )
    result = audit(console_file=console)
    assert not result["passed"]
    assert result["checks"]["observed_console"]["unexpected"] == [
        "https://www.googleapis.com/auth/contacts.readonly"
    ]


def test_scope_audit_rejects_extra_browser_request_without_printing_url(tmp_path):
    auth = tmp_path / "auth-url.txt"
    auth.write_text(
        "https://accounts.google.com/o/oauth2/v2/auth?state=private-state"
        "&scope=https://www.googleapis.com/auth/youtube.readonly",
        encoding="utf-8",
    )
    result = audit(auth_file=auth, provider_id="google_youtube")
    assert not result["passed"]
    assert "private-state" not in json.dumps(result)
    assert result["checks"]["observed_authorization_request"]["unexpected"] == [
        "https://www.googleapis.com/auth/youtube.readonly"
    ]
