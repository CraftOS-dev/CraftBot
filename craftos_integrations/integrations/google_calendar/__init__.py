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
    run_google_list_accounts,
    run_google_login,
    run_google_logout,
    run_google_set_alias,
    run_google_set_primary,
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
        return await run_google_logout(self.spec, "Google Calendar", args[0] if args else None)

    async def status(self) -> Tuple[bool, str]:
        return await run_google_status(self.spec, "Google Calendar")

    def list_accounts(self):
        return run_google_list_accounts(self.spec)

    async def set_primary(self, account_id: str) -> Tuple[bool, str]:
        return await run_google_set_primary(self.spec, "Google Calendar", account_id)

    def set_alias(self, account_id: str, alias: str) -> Tuple[bool, str]:
        return run_google_set_alias(self.spec, account_id, alias)


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

    # ----- Events -----

    def insert_event(
        self,
        calendar_id: str,
        event_data: Dict[str, Any],
        send_updates: str = "none",
        supports_attachments: bool = False,
        conference_data_version: int = 0,
    ) -> Result:
        params: Dict[str, Any] = {"sendUpdates": send_updates}
        if supports_attachments:
            params["supportsAttachments"] = "true"
        if conference_data_version:
            params["conferenceDataVersion"] = conference_data_version
        return http_request(
            "POST",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events",
            headers=self._headers(),
            params=params,
            json=event_data,
            expected=(200,),
        )

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        event_data: Dict[str, Any],
        send_updates: str = "none",
    ) -> Result:
        return http_request(
            "PUT",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event_id}",
            headers=self._headers(),
            params={"sendUpdates": send_updates},
            json=event_data,
            expected=(200,),
        )

    def patch_event(
        self,
        calendar_id: str,
        event_id: str,
        event_data: Dict[str, Any],
        send_updates: str = "none",
    ) -> Result:
        return http_request(
            "PATCH",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event_id}",
            headers=self._headers(),
            params={"sendUpdates": send_updates},
            json=event_data,
            expected=(200,),
        )

    def move_event(
        self,
        calendar_id: str,
        event_id: str,
        destination_calendar_id: str,
        send_updates: str = "none",
    ) -> Result:
        return http_request(
            "POST",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event_id}/move",
            headers=self._auth_header(),
            params={
                "destination": destination_calendar_id,
                "sendUpdates": send_updates,
            },
            expected=(200,),
        )

    def quick_add_event(
        self, calendar_id: str, text: str, send_updates: str = "none"
    ) -> Result:
        return http_request(
            "POST",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/quickAdd",
            headers=self._auth_header(),
            params={"text": text, "sendUpdates": send_updates},
            expected=(200,),
        )

    def list_event_instances(
        self,
        calendar_id: str,
        event_id: str,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        max_results: int = 50,
    ) -> Result:
        params: Dict[str, Any] = {"maxResults": max_results}
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        return http_request(
            "GET",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/{event_id}/instances",
            headers=self._auth_header(),
            params=params,
            expected=(200,),
            transform=lambda d: {"instances": d.get("items", [])},
        )

    def import_event(self, calendar_id: str, event_data: Dict[str, Any]) -> Result:
        return http_request(
            "POST",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/events/import",
            headers=self._headers(),
            json=event_data,
            expected=(200,),
        )

    # ----- Calendars (the resource itself) -----

    def get_calendar(self, calendar_id: str = "primary") -> Result:
        return http_request(
            "GET",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}",
            headers=self._auth_header(),
            expected=(200,),
        )

    def create_calendar(
        self,
        summary: str,
        description: Optional[str] = None,
        time_zone: Optional[str] = None,
        location: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {"summary": summary}
        if description:
            payload["description"] = description
        if time_zone:
            payload["timeZone"] = time_zone
        if location:
            payload["location"] = location
        return http_request(
            "POST",
            f"{CALENDAR_API_BASE}/calendars",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {
                "id": d.get("id"),
                "summary": d.get("summary"),
                "timeZone": d.get("timeZone"),
            },
        )

    def update_calendar(
        self,
        calendar_id: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        time_zone: Optional[str] = None,
        location: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if summary is not None:
            payload["summary"] = summary
        if description is not None:
            payload["description"] = description
        if time_zone is not None:
            payload["timeZone"] = time_zone
        if location is not None:
            payload["location"] = location
        return http_request(
            "PUT",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def patch_calendar(
        self,
        calendar_id: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        time_zone: Optional[str] = None,
        location: Optional[str] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if summary is not None:
            payload["summary"] = summary
        if description is not None:
            payload["description"] = description
        if time_zone is not None:
            payload["timeZone"] = time_zone
        if location is not None:
            payload["location"] = location
        return http_request(
            "PATCH",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def delete_calendar(self, calendar_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "calendar_id": calendar_id},
        )

    def clear_calendar(self, calendar_id: str = "primary") -> Result:
        """Clears all events on the PRIMARY calendar. No-op on secondary."""
        return http_request(
            "POST",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/clear",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"cleared": True, "calendar_id": calendar_id},
        )

    # ----- CalendarList (the user's view: subscriptions, colors, visibility) -----

    def get_calendar_list_entry(self, calendar_id: str) -> Result:
        return http_request(
            "GET",
            f"{CALENDAR_API_BASE}/users/me/calendarList/{calendar_id}",
            headers=self._auth_header(),
            expected=(200,),
        )

    def subscribe_calendar(
        self,
        calendar_id: str,
        color_id: Optional[str] = None,
        summary_override: Optional[str] = None,
        selected: Optional[bool] = None,
        hidden: Optional[bool] = None,
    ) -> Result:
        payload: Dict[str, Any] = {"id": calendar_id}
        if color_id is not None:
            payload["colorId"] = color_id
        if summary_override is not None:
            payload["summaryOverride"] = summary_override
        if selected is not None:
            payload["selected"] = selected
        if hidden is not None:
            payload["hidden"] = hidden
        return http_request(
            "POST",
            f"{CALENDAR_API_BASE}/users/me/calendarList",
            headers=self._headers(),
            json=payload,
            expected=(200,),
            transform=lambda d: {"id": d.get("id"), "summary": d.get("summary")},
        )

    def update_calendar_list_entry(
        self,
        calendar_id: str,
        color_id: Optional[str] = None,
        summary_override: Optional[str] = None,
        selected: Optional[bool] = None,
        hidden: Optional[bool] = None,
    ) -> Result:
        payload: Dict[str, Any] = {}
        if color_id is not None:
            payload["colorId"] = color_id
        if summary_override is not None:
            payload["summaryOverride"] = summary_override
        if selected is not None:
            payload["selected"] = selected
        if hidden is not None:
            payload["hidden"] = hidden
        return http_request(
            "PATCH",
            f"{CALENDAR_API_BASE}/users/me/calendarList/{calendar_id}",
            headers=self._headers(),
            json=payload,
            expected=(200,),
        )

    def unsubscribe_calendar(self, calendar_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{CALENDAR_API_BASE}/users/me/calendarList/{calendar_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"unsubscribed": True, "calendar_id": calendar_id},
        )

    # ----- ACL (per-calendar sharing) -----

    def list_calendar_acl(self, calendar_id: str = "primary") -> Result:
        return http_request(
            "GET",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/acl",
            headers=self._auth_header(),
            expected=(200,),
            transform=lambda d: {
                "acl": [
                    {
                        "id": r.get("id"),
                        "role": r.get("role"),
                        "scope_type": r.get("scope", {}).get("type"),
                        "scope_value": r.get("scope", {}).get("value"),
                    }
                    for r in d.get("items", [])
                ]
            },
        )

    def get_calendar_acl_rule(self, calendar_id: str, rule_id: str) -> Result:
        return http_request(
            "GET",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/acl/{rule_id}",
            headers=self._auth_header(),
            expected=(200,),
        )

    def add_calendar_acl_rule(
        self,
        calendar_id: str,
        scope_type: str,
        scope_value: str,
        role: str,
        send_notifications: bool = True,
    ) -> Result:
        """scope_type: user|group|domain|default. role: none|freeBusyReader|reader|writer|owner."""
        payload = {"role": role, "scope": {"type": scope_type, "value": scope_value}}
        return http_request(
            "POST",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/acl",
            headers=self._headers(),
            json=payload,
            params={"sendNotifications": str(send_notifications).lower()},
            expected=(200,),
            transform=lambda d: {"id": d.get("id"), "role": d.get("role")},
        )

    def update_calendar_acl_rule(
        self,
        calendar_id: str,
        rule_id: str,
        role: str,
        scope_type: Optional[str] = None,
        scope_value: Optional[str] = None,
        send_notifications: bool = True,
    ) -> Result:
        payload: Dict[str, Any] = {"role": role}
        if scope_type or scope_value:
            payload["scope"] = {}
            if scope_type:
                payload["scope"]["type"] = scope_type
            if scope_value:
                payload["scope"]["value"] = scope_value
        return http_request(
            "PUT",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/acl/{rule_id}",
            headers=self._headers(),
            json=payload,
            params={"sendNotifications": str(send_notifications).lower()},
            expected=(200,),
        )

    def delete_calendar_acl_rule(self, calendar_id: str, rule_id: str) -> Result:
        return http_request(
            "DELETE",
            f"{CALENDAR_API_BASE}/calendars/{calendar_id}/acl/{rule_id}",
            headers=self._auth_header(),
            expected=(204,),
            transform=lambda _d: {"deleted": True, "rule_id": rule_id},
        )

    # ----- Settings & colors -----

    def list_calendar_settings(self) -> Result:
        return http_request(
            "GET",
            f"{CALENDAR_API_BASE}/users/me/settings",
            headers=self._auth_header(),
            expected=(200,),
            transform=lambda d: {
                "settings": {s.get("id"): s.get("value") for s in d.get("items", [])}
            },
        )

    def get_calendar_setting(self, setting_id: str) -> Result:
        """setting_id examples: timezone, locale, autoAddHangouts, weekStart."""
        return http_request(
            "GET",
            f"{CALENDAR_API_BASE}/users/me/settings/{setting_id}",
            headers=self._auth_header(),
            expected=(200,),
            transform=lambda d: {"id": d.get("id"), "value": d.get("value")},
        )

    def get_calendar_colors(self) -> Result:
        return http_request(
            "GET",
            f"{CALENDAR_API_BASE}/colors",
            headers=self._auth_header(),
            expected=(200,),
            transform=lambda d: {
                "calendar": d.get("calendar", {}),
                "event": d.get("event", {}),
            },
        )
