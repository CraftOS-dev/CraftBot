# -*- coding: utf-8 -*-
"""Lark Calendar integration - events, scheduling, free/busy.

Same Custom App as ``lark.py`` (messaging) and ``lark_drive.py`` - App ID +
Secret + tenant_access_token - but registered as a sibling integration with
its own credential file (``lark_calendar.json``) so it shows as an
independent tile in the UI. Permissions are gated separately per service.

API quirk worth knowing: Lark's Calendar API expects Unix timestamps as
**strings** inside ``{"timestamp": "1730000000"}`` objects. The client
methods accept ``int`` and stringify internally so callers don't have to
think about it.

Required Lark permissions (Permissions & Scopes tab on the Custom App):
  - ``calendar:calendar`` (full read-write) OR
    ``calendar:calendar:readonly`` (read-only)
  - For events with attendees: ``calendar:calendar.event.attendee``
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ... import (
    BasePlatformClient,
    IntegrationHandler,
    IntegrationSpec,
    has_credential,
    load_credential,
    register_client,
    register_handler,
    remove_credential,
    save_credential,
)
from ...helpers import Result, request as http_request
from ...logger import get_logger
from .._lark_common import (
    LARK_API_BASE,
    LarkCredential,
    make_headers,
    validate_and_mint_token,
)

logger = get_logger(__name__)


LARK_CALENDAR = IntegrationSpec(
    name="lark_calendar",
    cred_class=LarkCredential,
    cred_file="lark_calendar.json",
    platform_id="lark_calendar",
)


# -----------------------------------------------------------------
# Handler
# -----------------------------------------------------------------


@register_handler(LARK_CALENDAR.name)
class LarkCalendarHandler(IntegrationHandler):
    spec = LARK_CALENDAR
    display_name = "Lark Calendar"
    description = "Events, scheduling, and free/busy on Lark Calendar"
    auth_type = "token"
    icon = "lark"
    connect_help = [
        "Use the same Custom App you created for /lark (or create one at open.larksuite.com/app)",
        "Permissions & Scopes â†’ enable: calendar:calendar (read-write) and calendar:calendar.event.attendee (for invites)",
        "Version Management â†’ Create Version â†’ submit for tenant admin approval - required for new scopes to take effect",
        "Credentials & Basic Info â†’ copy App ID + App Secret and paste them below (same values as /lark)",
    ]
    fields = [
        {
            "key": "app_id",
            "label": "App ID",
            "placeholder": "cli_xxxxxxxxxx",
            "password": False,
        },
        {
            "key": "app_secret",
            "label": "App Secret",
            "placeholder": "From Credentials & Basic Info tab",
            "password": True,
        },
    ]

    async def login(self, args: List[str]) -> Tuple[bool, str]:
        if len(args) < 2:
            return False, (
                "Usage: /lark_calendar login <app_id> <app_secret>\n"
                "Use the same App ID + Secret as /lark; just make sure calendar:* "
                "scopes are enabled on the same Custom App."
            )
        app_id, app_secret = args[0], args[1]
        token, token_expires_at, err = validate_and_mint_token(app_id, app_secret)
        if err:
            return False, err

        save_credential(
            self.spec.cred_file,
            LarkCredential(
                app_id=app_id,
                app_secret=app_secret,
                tenant_access_token=token,
                token_expires_at=token_expires_at,
            ),
        )
        return True, f"Lark Calendar connected: {app_id}"

    async def logout(self, args: List[str]) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return False, "No Lark Calendar credentials found."
        remove_credential(self.spec.cred_file)
        return True, "Removed Lark Calendar credential."

    async def status(self) -> Tuple[bool, str]:
        if not has_credential(self.spec.cred_file):
            return True, "Lark Calendar: Not connected"
        cred = load_credential(self.spec.cred_file, LarkCredential)
        if not cred:
            return True, "Lark Calendar: Connected\n  - app configured"
        return True, f"Lark Calendar: Connected\n  - {cred.app_id}"


# -----------------------------------------------------------------
# Client
# -----------------------------------------------------------------


@register_client
class LarkCalendarClient(BasePlatformClient):
    spec = LARK_CALENDAR
    PLATFORM_ID = LARK_CALENDAR.platform_id

    def __init__(self) -> None:
        super().__init__()
        self._cred: Optional[LarkCredential] = None

    def has_credentials(self) -> bool:
        return has_credential(self.spec.cred_file)

    def _load(self) -> LarkCredential:
        if self._cred is None:
            self._cred = load_credential(self.spec.cred_file, LarkCredential)
        if self._cred is None:
            raise RuntimeError(
                "No Lark Calendar credentials. Use /lark_calendar login first."
            )
        return self._cred

    def _headers(self) -> Dict[str, str]:
        return make_headers(self._load(), self.spec.cred_file)

    async def connect(self) -> None:
        self._load()
        self._connected = True

    async def send_message(self, recipient: str, text: str, **kwargs) -> Result:
        return {
            "error": "Lark Calendar does not support send_message - use create_event"
        }

    @property
    def supports_listening(self) -> bool:
        return False

    # ----- Calendars -----

    def list_calendars(self, page_size: int = 20, page_token: str = "") -> Result:
        """List the bot's accessible calendars (its own + any shared with it)."""
        params: Dict[str, str] = {"page_size": str(min(page_size, 1000))}
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET",
            f"{LARK_API_BASE}/calendar/v4/calendars",
            params=params,
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_primary_calendar(self) -> Result:
        """Get the bot's primary calendar (the one it owns by default)."""
        return http_request(
            "POST",
            f"{LARK_API_BASE}/calendar/v4/calendars/primary",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_calendar(self, calendar_id: str) -> Result:
        """Fetch a single calendar's metadata."""
        return http_request(
            "GET", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}",
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def create_calendar(self, summary: str,
                        description: str = "",
                        permissions: str = "private",
                        color: Optional[int] = None,
                        summary_alias: str = "") -> Result:
        """Create a secondary calendar owned by the bot.

        ``permissions``: private | show_only_free_busy | public.
        ``color`` is an RGB int32 (Lark's own encoding; -1 = default).
        """
        body: Dict[str, Any] = {"summary": summary}
        if description:
            body["description"] = description
        if permissions:
            body["permissions"] = permissions
        if color is not None:
            body["color"] = color
        if summary_alias:
            body["summary_alias"] = summary_alias
        return http_request(
            "POST", f"{LARK_API_BASE}/calendar/v4/calendars",
            headers=self._headers(), json=body, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_calendar(self, calendar_id: str,
                        summary: Optional[str] = None,
                        description: Optional[str] = None,
                        permissions: Optional[str] = None,
                        color: Optional[int] = None,
                        summary_alias: Optional[str] = None) -> Result:
        """Patch a calendar. Only fields with non-None values are sent."""
        body: Dict[str, Any] = {}
        if summary is not None:
            body["summary"] = summary
        if description is not None:
            body["description"] = description
        if permissions is not None:
            body["permissions"] = permissions
        if color is not None:
            body["color"] = color
        if summary_alias is not None:
            body["summary_alias"] = summary_alias
        if not body:
            return {"error": "No fields provided to update"}
        return http_request(
            "PATCH", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}",
            headers=self._headers(), json=body, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def delete_calendar(self, calendar_id: str) -> Result:
        """Delete a calendar the bot owns."""
        return http_request(
            "DELETE", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}",
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d) or {"deleted": True, "calendar_id": calendar_id},
        )

    def search_calendars(self, query: str, page_size: int = 20,
                         page_token: str = "") -> Result:
        """Search across calendars the bot can see by name."""
        params: Dict[str, str] = {"page_size": str(min(page_size, 100))}
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "POST", f"{LARK_API_BASE}/calendar/v4/calendars/search",
            params=params, headers=self._headers(),
            json={"query": query}, expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def subscribe_calendar(self, calendar_id: str) -> Result:
        """Subscribe to (follow) a shared calendar so it shows up in list_calendars."""
        return http_request(
            "POST", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/subscribe",
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def unsubscribe_calendar(self, calendar_id: str) -> Result:
        """Unsubscribe from a shared calendar."""
        return http_request(
            "POST", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/unsubscribe",
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ----- Events -----

    def list_events(
        self,
        calendar_id: str,
        start_time: int,
        end_time: int,
        page_size: int = 50,
        page_token: str = "",
    ) -> Result:
        """List events in a date range. Times are Unix seconds (int)."""
        params: Dict[str, str] = {
            "start_time": str(start_time),
            "end_time": str(end_time),
            "page_size": str(min(page_size, 1000)),
        }
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET",
            f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events",
            params=params,
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def get_event(self, calendar_id: str, event_id: str) -> Result:
        return http_request(
            "GET",
            f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events/{event_id}",
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def create_event(
        self,
        calendar_id: str,
        summary: str,
        start_time: int,
        end_time: int,
        description: str = "",
        location: str = "",
        with_video_meeting: bool = False,
    ) -> Result:
        """Create an event. Times are Unix seconds (int).

        ``with_video_meeting=True`` asks Lark to auto-generate a Lark Meeting
        URL and attach it. Attendees are added separately via
        ``add_event_attendees`` after creation - Lark's create endpoint
        doesn't accept attendees in the same body.
        """
        body: Dict[str, Any] = {
            "summary": summary,
            "start_time": {"timestamp": str(start_time)},
            "end_time": {"timestamp": str(end_time)},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = {"name": location}
        if with_video_meeting:
            body["vchat"] = {"vc_type": "vc"}
        return http_request(
            "POST",
            f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events",
            headers=self._headers(),
            json=body,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def update_event(
        self,
        calendar_id: str,
        event_id: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        location: Optional[str] = None,
    ) -> Result:
        """Patch an event. Only fields with non-None values are sent."""
        body: Dict[str, Any] = {}
        if summary is not None:
            body["summary"] = summary
        if description is not None:
            body["description"] = description
        if start_time is not None:
            body["start_time"] = {"timestamp": str(start_time)}
        if end_time is not None:
            body["end_time"] = {"timestamp": str(end_time)}
        if location is not None:
            body["location"] = {"name": location}
        if not body:
            return {"error": "No fields provided to update"}
        return http_request(
            "PATCH",
            f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events/{event_id}",
            headers=self._headers(),
            json=body,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def delete_event(
        self, calendar_id: str, event_id: str, need_notification: bool = True
    ) -> Result:
        """Delete an event. ``need_notification`` controls whether attendees
        are emailed about the cancellation."""
        params = {"need_notification": "true" if need_notification else "false"}
        return http_request(
            "DELETE",
            f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events/{event_id}",
            params=params,
            headers=self._headers(),
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def search_events(
        self,
        calendar_id: str,
        query: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        page_size: int = 20,
    ) -> Result:
        """Full-text search over event summary/description in one calendar."""
        body: Dict[str, Any] = {"query": query}
        if start_time is not None and end_time is not None:
            body["filter"] = {
                "start_time": {"timestamp": str(start_time)},
                "end_time": {"timestamp": str(end_time)},
            }
        return http_request(
            "POST",
            f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events/search",
            params={"page_size": str(min(page_size, 100))},
            headers=self._headers(),
            json=body,
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ----- Attendees -----

    def add_event_attendees(
        self,
        calendar_id: str,
        event_id: str,
        user_ids: Optional[List[str]] = None,
        emails: Optional[List[str]] = None,
        chat_ids: Optional[List[str]] = None,
        need_notification: bool = True,
    ) -> Result:
        """Invite attendees to an event.

        Pass any combination of ``user_ids`` (Lark open_ids), ``emails``
        (external attendees), and ``chat_ids`` (group chats - every member
        gets invited). Lark's API normalizes these into a single
        ``attendees`` list with per-entry ``type``.
        """
        attendees: List[Dict[str, str]] = []
        for uid in user_ids or []:
            attendees.append({"type": "user", "user_id": uid})
        for em in emails or []:
            attendees.append({"type": "third_party", "third_party_email": em})
        for cid in chat_ids or []:
            attendees.append({"type": "chat", "chat_id": cid})
        if not attendees:
            return {"error": "No attendees provided"}
        return http_request(
            "POST",
            f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events/{event_id}/attendees",
            headers=self._headers(),
            json={"attendees": attendees, "need_notification": need_notification},
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ----- Free/busy -----

    def check_free_busy(
        self, user_ids: List[str], start_time: int, end_time: int
    ) -> Result:
        """Bulk free/busy query for a list of users over a time window.

        Returns each user's busy intervals in the window - useful for
        finding a meeting slot that works for everyone.
        """
        return http_request(
            "POST",
            f"{LARK_API_BASE}/calendar/v4/freebusy/list",
            headers=self._headers(),
            json={
                "time_min": {"timestamp": str(start_time)},
                "time_max": {"timestamp": str(end_time)},
                "user_id_list": user_ids,
            },
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ----- Event RSVP -----

    def reply_event(self, calendar_id: str, event_id: str,
                    rsvp_status: str) -> Result:
        """Reply to an event invitation. ``rsvp_status``: accept | decline | tentative."""
        return http_request(
            "POST", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events/{event_id}/reply",
            headers=self._headers(),
            json={"rsvp_status": rsvp_status},
            expected=(200,),
            transform=lambda d: d.get("data", d) or {"replied": True, "rsvp_status": rsvp_status},
        )

    # ----- Event attendees: list / batch delete / chat members -----

    def list_event_attendees(self, calendar_id: str, event_id: str,
                             page_size: int = 100, page_token: str = "") -> Result:
        """List attendees on an event."""
        params: Dict[str, str] = {"page_size": str(min(page_size, 200))}
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events/{event_id}/attendees",
            params=params, headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def batch_delete_event_attendees(self, calendar_id: str, event_id: str,
                                     attendee_ids: List[str],
                                     need_notification: bool = True) -> Result:
        """Remove attendees by attendee_id from an event in one call."""
        return http_request(
            "POST", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events/{event_id}/attendees/batch_delete",
            headers=self._headers(),
            json={
                "attendee_ids": attendee_ids,
                "need_notification": need_notification,
            },
            expected=(200,),
            transform=lambda d: d.get("data", d) or {"removed": attendee_ids},
        )

    def list_event_attendee_chat_members(self, calendar_id: str, event_id: str,
                                         attendee_id: str,
                                         page_size: int = 100, page_token: str = "") -> Result:
        """List the chat members behind a chat-type attendee."""
        params: Dict[str, str] = {"page_size": str(min(page_size, 200))}
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events/{event_id}/attendees/{attendee_id}/chat_members",
            params=params, headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def add_meeting_room_to_event(self, calendar_id: str, event_id: str,
                                  meeting_room_id: str,
                                  need_notification: bool = True) -> Result:
        """Book a meeting room by attaching it as a resource-type attendee."""
        return http_request(
            "POST", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events/{event_id}/attendees",
            headers=self._headers(),
            json={
                "attendees": [{"type": "resource", "room_id": meeting_room_id}],
                "need_notification": need_notification,
            },
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ----- Recurring event instances -----

    def list_event_instances(self, calendar_id: str, event_id: str,
                             start_time: int, end_time: int,
                             page_size: int = 50, page_token: str = "") -> Result:
        """List concrete instances of a recurring event in a window."""
        params: Dict[str, str] = {
            "start_time": str(start_time),
            "end_time": str(end_time),
            "page_size": str(min(page_size, 100)),
        }
        if page_token:
            params["page_token"] = page_token
        return http_request(
            "GET", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/events/{event_id}/instances",
            params=params, headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    # ----- Calendar ACL (sharing) -----

    def list_calendar_acls(self, calendar_id: str) -> Result:
        """List the access-control entries (sharing permissions) on a calendar."""
        return http_request(
            "GET", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/acls",
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def create_calendar_acl(self, calendar_id: str, user_id: str,
                            role: str = "reader") -> Result:
        """Share a calendar with a user.

        ``role``: owner | reader | writer | free_busy_reader.
        ``user_id`` is the Lark open_id (ou_...).
        """
        return http_request(
            "POST", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/acls",
            headers=self._headers(),
            json={
                "role": role,
                "scope": {"type": "user", "user_id": user_id},
            },
            expected=(200,),
            transform=lambda d: d.get("data", d),
        )

    def delete_calendar_acl(self, calendar_id: str, acl_id: str) -> Result:
        """Revoke a sharing permission."""
        return http_request(
            "DELETE", f"{LARK_API_BASE}/calendar/v4/calendars/{calendar_id}/acls/{acl_id}",
            headers=self._headers(), expected=(200,),
            transform=lambda d: d.get("data", d) or {"deleted": True, "acl_id": acl_id},
        )
