# -*- coding: utf-8 -*-
"""Google Calendar - granular Google integration.

Connect just Calendar (without granting Gmail/Drive/YouTube scopes) by
clicking Connect on the Google Calendar card. Credential is saved to
``gcal.json``.

See ``gmail.py`` for the canonical per-service shape - this file is
structurally identical, differing only in scope, REST surface, and
listener (Calendar doesn't poll for incoming messages).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    register_client,
    register_handler,
)
from ...helpers import Result, request as http_request
from ...logger import get_logger
from .._google_common import (
    CALENDAR_SCOPES,
    GoogleApiClientMixin,
    GoogleCredential,
    make_google_oauth,
    run_google_login,
    run_google_logout,
    run_google_status,
)

logger = get_logger(__name__)

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


GCAL = IntegrationSpec(
    name="google_calendar",
    cred_class=GoogleCredential,
    cred_file="gcal.json",
    platform_id="google_calendar",
)


# -----------------------------------------------------------------
# Handler - auth flow only
# -----------------------------------------------------------------


@register_handler(GCAL.name)
class GoogleCalendarHandler(IntegrationHandler):
    spec = GCAL
    display_name = "Google Calendar"
    description = "Calendar events, availability, and Meet links"
    auth_type = "oauth"
    icon = "google_calendar"
    fields: List = []

    oauth = make_google_oauth(CALENDAR_SCOPES)

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        return await run_google_login(self.spec, self.oauth, "Google Calendar")

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        return await run_google_logout(self.spec, "Google Calendar")

    async def status(self) -> Tuple[bool, str]:
        return await run_google_status(self.spec, "Google Calendar")


# -----------------------------------------------------------------
# Client - Calendar REST methods (no listener; Calendar isn't push-based)
# -----------------------------------------------------------------


@register_client
class GoogleCalendarClient(GoogleApiClientMixin, BasePlatformClient):
    spec = GCAL
    PLATFORM_ID = GCAL.platform_id

    def __init__(self):
        super().__init__()
        self._cred: Optional[GoogleCredential] = None

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return {
            "error": "Google Calendar does not support send_message - use create_meet_event"
        }

    @property
    def supports_listening(self) -> bool:
        return False

    # ----- REST methods -----

    def create_meet_event(
        self, calendar_id: str = "primary", event_data: Optional[Dict[str, Any]] = None
    ) -> Result:
        return http_request(
            "POST",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
            headers=self._headers(),
            params={"conferenceDataVersion": 1},
            json=event_data or {},
        )

    def check_availability(
        self,
        calendar_id: str = "primary",
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
    ) -> Result:
        return http_request(
            "POST",
            f"{CALENDAR_API_BASE}/freeBusy",
            headers=self._headers(),
            json={
                "timeMin": time_min,
                "timeMax": time_max,
                "items": [{"id": calendar_id}],
            },
            expected=(200,),
        )

    def list_events(
        self,
        calendar_id: str = "primary",
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        max_results: int = 50,
    ) -> Result:
        params: Dict[str, Any] = {
            "maxResults": max_results,
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        return http_request(
            "GET",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
            headers=self._auth_header(),
            params=params,
            expected=(200,),
            transform=lambda d: d.get("items", []),
        )

    def get_event(self, event_id: str, calendar_id: str = "primary") -> Result:
        return http_request(
            "GET",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event_id}",
            headers=self._auth_header(),
            expected=(200,),
        )

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> Result:
        return http_request(
            "DELETE",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "event_id": event_id},
        )

    def list_calendars(self) -> Result:
        return http_request(
            "GET",
            f"{CALENDAR_API_BASE}/users/me/calendarList",
            headers=self._auth_header(),
            expected=(200,),
            transform=lambda d: d.get("items", []),
        )
