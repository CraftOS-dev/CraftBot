"""Google Calendar provider — conformance + one end-to-end wiring check.

No network: the client API method is stubbed. What's real is the chain
execute() → resolve → bind → client method → shaped (lean) result.
"""

from __future__ import annotations

import asyncio

import pytest

from craftos_integrations.core.storage import FileCredentialStore
from craftos_integrations.core.system import IntegrationSystem
from craftos_integrations.providers.google_calendar import GoogleCalendarProvider
from craftos_integrations.providers.google_calendar.provider import (
    BoundGoogleCalendarClient,
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


class TestCalendarConformance(ProviderConformance):
    provider = GoogleCalendarProvider()
    credential_fixtures = [
        GOOGLE_CRED,
        {"access_token": "at", "email": "  User@X.com "},  # messy legacy shape
        {"access_token": "at"},  # identity-less pre-multi-account shape → None
    ]


@pytest.fixture
def system(tmp_path):
    sys = IntegrationSystem(
        store=FileCredentialStore(root=tmp_path),
        providers=[GoogleCalendarProvider()],
    )
    sys.store_credential("google_calendar", "a@x.com", dict(GOOGLE_CRED))
    sys.store_credential(
        "google_calendar",
        "b@y.com",
        {**GOOGLE_CRED, "email": "b@y.com", "access_token": "at-b"},
    )
    sys.set_alias("google_calendar", "b@y.com", "school")
    return sys


RAW_EVENT = {
    "kind": "calendar#event",  # metadata the lean shaping drops
    "etag": '"etag-1"',
    "id": "ev-1",
    "summary": "Standup",
    "start": {"dateTime": "2026-08-12T09:00:00Z"},
    "end": {"dateTime": "2026-08-12T09:15:00Z"},
    "status": "confirmed",
    "htmlLink": "https://calendar.google.com/event?eid=ev-1",
    "creator": {"email": "a@x.com"},  # dropped by lean shaping
    "attendees": [
        {"email": "b@y.com", "responseStatus": "accepted", "self": True},
    ],
}


def test_execute_lists_events_against_resolved_accounts_client(system, monkeypatch):
    seen = []

    def fake_list_events(
        self, calendar_id="primary", time_min=None, time_max=None, max_results=50
    ):
        seen.append((self._cred.email, calendar_id, time_min, time_max, max_results))
        return {"ok": True, "result": [RAW_EVENT]}

    monkeypatch.setattr(BoundGoogleCalendarClient, "list_events", fake_list_events)

    result = run(
        system.execute(
            "google_calendar",
            "list_google_calendar_events",
            {"time_min": "2026-08-12T00:00:00Z", "max_results": 10},
            account="school",
        )
    )
    # school account's client, mapped args (calendar_id default applied)
    assert seen == [("b@y.com", "primary", "2026-08-12T00:00:00Z", None, 10)]
    # lean shaping applied (no include_metadata): metadata keys dropped,
    # attendees reduced to email/displayName/responseStatus/organizer
    assert result == {
        "status": "success",
        "result": [
            {
                "id": "ev-1",
                "summary": "Standup",
                "start": {"dateTime": "2026-08-12T09:00:00Z"},
                "end": {"dateTime": "2026-08-12T09:15:00Z"},
                "status": "confirmed",
                "htmlLink": "https://calendar.google.com/event?eid=ev-1",
                "attendees": [{"email": "b@y.com", "responseStatus": "accepted"}],
            }
        ],
    }

    raw = run(
        system.execute(
            "google_calendar",
            "list_google_calendar_events",
            {"include_metadata": True},
        )
    )
    assert seen[-1] == ("a@x.com", "primary", None, None, 50)  # primary + defaults
    assert raw["result"][0]["kind"] == "calendar#event"  # raw passthrough
